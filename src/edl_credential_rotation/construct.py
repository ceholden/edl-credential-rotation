from pathlib import Path

from aws_cdk import Duration
from aws_cdk.aws_secretsmanager import Secret
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
    """Cache DAAC S3 credentials in SecretsManager for shared use.

    Periodically fetches fresh temporary S3 credentials from a DAAC
    /s3credentials endpoint using an Earthdata Login username/password stored in
    SecretsManager, then writes them back to a separate SecretsManager secret.
    Multiple services can read from that secret without each independently
    hitting the DAAC credentials endpoint (avoiding thundering-herd problems).

    The Earthdata Login username/password secret must be manually populated
    before the rotator Lambda will succeed.

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
    """

    def __init__(
        self,
        scope: Construct,
        id: str,
        daac_s3credentials_url: str = LPDAAC_S3CREDENTIALS_URL,
        architecture: Architecture = Architecture.X86_64,
        runtime: Runtime = Runtime.PYTHON_3_12,
        rotation_frequency_minutes: int | None = 30,
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

        # NB: user must populate the values manually
        self.edl_user_account_credentials = Secret(
            self,
            id="EdlUserAccountCredentials",
            description="Earthdata Login account username and password credentials.",
        )

        self.edl_s3_credentials = Secret(
            self,
            id="EdlS3Credentials",
            description="Earthdata credentials permitting direct AWS S3 access.",
        )

        # This Lambda sets the following keys in the `edl_s3_credentials` Secret,
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
                "USER_PASS_SECRET_ID": self.edl_user_account_credentials.secret_arn,
                "S3_CREDENTIALS_SECRET_ID": self.edl_s3_credentials.secret_arn,
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
