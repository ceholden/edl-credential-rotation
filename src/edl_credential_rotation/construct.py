from pathlib import Path

from aws_cdk import Duration, Stack
from aws_cdk.aws_iam import IGrantable
from aws_cdk.aws_ssm import StringParameter
from aws_cdk.aws_logs import RetentionDays
from aws_cdk import aws_events, aws_events_targets
from aws_cdk.aws_lambda import (
    Architecture,
    Code,
    Function,
    Runtime,
    RuntimeFamily,
)

from constructs import Construct

HERE = Path(__file__).parent
DOCKERFILE = HERE / "Dockerfile"

LPDAAC_S3CREDENTIALS_URL = "https://data.lpdaac.earthdatacloud.nasa.gov/s3credentials"


class EarthdataCredentialCache(Construct):
    """Cache DAAC S3 credentials in SSM Parameter Store for shared use.

    Periodically fetches fresh temporary S3 credentials from a DAAC
    /s3credentials endpoint using an Earthdata Login username/password stored in
    a SecureString SSM parameter, then writes them to a separate SecureString
    parameter. Multiple services can read from that parameter without each
    independently hitting the DAAC credentials endpoint (avoiding thundering-herd
    problems).

    CloudFormation cannot create SecureString parameters, so neither parameter
    is managed by this construct:

    * The Earthdata Login username/password parameter must be created manually
      (as a SecureString containing JSON with "USERNAME" and "PASSWORD" keys)
      before the rotator Lambda will succeed.
    * The S3 credentials parameter is created by the rotator Lambda on its first
      run and is not deleted when the stack is destroyed.

    Both parameters are encrypted with the AWS managed `aws/ssm` KMS key.

    Parameters
    ----------
    scope
        Provide the parent of this construct (usually a CDK stack)
    id
        A unique identifier within the scope used as a namespace for the resources
    daac_s3credentials_url
        The endpoint for the DAAC `/s3credentials` endpoint you wish to use
        (default: endpoint for LPDAAC)
    architecture
        The architecture for the Lambda runtime (default: X86_64)
    runtime
        The Python runtime for the refresh Lambda (default: Python 3.12)
    rotation_frequency_minutes
        Frequency for rotation schedule in minutes. If None, do not schedule the
        credentials rotation. (default: 30 minutes)
    parameter_prefix
        Prefix for the SSM parameter names. Must start with "/".
        (default: "/<stack name>/<construct id>")
    """

    def __init__(
        self,
        scope: Construct,
        id: str,
        daac_s3credentials_url: str = LPDAAC_S3CREDENTIALS_URL,
        architecture: Architecture = Architecture.X86_64,
        runtime: Runtime = Runtime.PYTHON_3_12,
        rotation_frequency_minutes: int | None = 30,
        parameter_prefix: str | None = None,
    ) -> None:
        super().__init__(scope, id)

        if runtime.family != RuntimeFamily.PYTHON:
            raise ValueError(f"Runtime must be Python based, got {runtime}")
        self._runtime = runtime

        self._lambda_code = Code.from_docker_build(
            path=str(HERE.absolute()),
            file=DOCKERFILE.name,
            build_args={
                "PYTHON_VERSION": runtime.name.replace("python", ""),
            },
        )

        stack = Stack.of(self)
        if parameter_prefix is None:
            parameter_prefix = f"/{stack.stack_name}/{id}"
        elif not parameter_prefix.startswith("/"):
            raise ValueError(
                f"parameter_prefix must start with '/', got {parameter_prefix}"
            )
        parameter_prefix = parameter_prefix.rstrip("/")

        # NB: user must create and populate this parameter manually
        self.edl_user_account_credentials = (
            StringParameter.from_secure_string_parameter_attributes(
                self,
                "EdlUserAccountCredentials",
                parameter_name=f"{parameter_prefix}/edl-user-account-credentials",
            )
        )

        self.edl_s3_credentials = (
            StringParameter.from_secure_string_parameter_attributes(
                self,
                "EdlS3Credentials",
                parameter_name=f"{parameter_prefix}/edl-s3-credentials",
            )
        )

        # This Lambda sets the following keys in the `edl_s3_credentials` parameter,
        #   * ACCESS_KEY_ID
        #   * SECRET_ACCESS_KEY
        #   * SESSION_TOKEN
        self.s3_credentials_rotator = Function(
            self,
            "S3CredentialsRotator",
            runtime=self._runtime,
            code=self._lambda_code,
            handler="app.s3credentials.handler",
            memory_size=128,
            timeout=Duration.minutes(1),
            environment={
                "DAAC_S3CREDENTIALS_URL": daac_s3credentials_url,
                "USER_PASS_PARAMETER_NAME": (
                    self.edl_user_account_credentials.parameter_name
                ),
                "S3_CREDENTIALS_PARAMETER_NAME": self.edl_s3_credentials.parameter_name,
            },
            log_retention=RetentionDays.ONE_WEEK,
        )
        self.edl_user_account_credentials.grant_read(self.s3_credentials_rotator)
        self.edl_s3_credentials.grant_write(self.s3_credentials_rotator)

        if rotation_frequency_minutes:
            self.edl_credential_rotator_schedule = aws_events.Rule(
                self,
                "EdlCredentialRotatorSchedule",
                schedule=aws_events.Schedule.rate(
                    Duration.minutes(rotation_frequency_minutes),
                ),
            )

            self.edl_credential_rotator_schedule.add_target(
                aws_events_targets.LambdaFunction(
                    handler=self.s3_credentials_rotator,
                )
            )

    def grant_read(self, grantee: IGrantable) -> None:
        """Grant permission to read the cached S3 credentials parameter"""
        self.edl_s3_credentials.grant_read(grantee)
