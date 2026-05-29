from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    stackname: str = Field(description="Name of your stack")
    project: str = Field(description="The project name for resource cost tracking")
    lambda_name: str = Field(
        description="The Arn of the Lambda that will receive new S3 Credentials"
    )
    username: str = Field(description="A valid Earth Data Login user name")
    password: str = Field(description="A valid Earth Data Login password")
    bootstrap_qualifier: str | None = Field(
        default=None,
        description="CDK Bootstrap qualifier",
    )

    model_config = {"env_file": ".env", "extra": "allow"}


settings = Settings()
