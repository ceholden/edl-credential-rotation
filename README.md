# edl-credential-rotation

AWS CDK tooling for automatically refreshing Earthdata Login temporary S3 credentials
([DAAC /s3credentials](https://nasa.github.io/cumulus-distribution-api/#temporary-s3-credentials)).

Two approaches are provided:

1. **Standalone CDK app** (`cdk/app.py`) — deploys a scheduler that writes fresh credentials
   directly into a target Lambda's environment variables.
2. **`EarthdataCredentialCache` construct** — a reusable CDK construct that caches credentials
   in SecretsManager so multiple services can share them without each independently calling
   the DAAC credentials endpoint.

## Usage

### Standalone CDK app

The standalone app (`cdk/app.py`) is a self-contained deployment that rotates credentials into
a target Lambda's environment variables every 30 minutes.

#### Environment settings

```
$ export STACKNAME=<Name of your stack>
$ export PROJECT=<The project name for resource cost tracking>
$ export LAMBDA=<The ARN of the Lambda that will receive new S3 credentials>
$ export USERNAME=<A valid Earthdata Login username>
$ export PASSWORD=<A valid Earthdata Login password>
```

#### CDK commands

```bash
# Preview the CloudFormation template
$ cdk synth

# Show a diff against the current deployment
$ cdk diff

# Deploy
$ cdk deploy
```

### EarthdataCredentialCache construct

The `EarthdataCredentialCache` construct is a reusable CDK construct for inclusion in your
own CDK application. It addresses the thundering-herd problem that arises when many services
independently call the DAAC credentials endpoint: instead, a single Lambda refreshes the
credentials on a schedule and stores them in SecretsManager for any service to read.

See `examples/app.py` for a minimal CDK application using the construct.

```python
from edl_credential_rotation import EarthdataCredentialCache

class MyStack(Stack):
    def __init__(self, scope, id, **kwargs):
        super().__init__(scope, id, **kwargs)
        self.edl_cache = EarthdataCredentialCache(self, "EdlCache")
```

The system deployed by this construct:

```mermaid
sequenceDiagram
    box Grey EDL Credential Cache
    participant EDL
    participant CredRot
    participant SSM
    end

    box Blue User Application
    participant App
    participant Bucket as DAAC Bucket
    end

    loop Every 30 Minutes
        CredRot->>EDL: Request S3 credentials
        EDL->>CredRot: Return credentials
        CredRot->>SSM: Store credentials
    end

    App->>SSM: Read secret
    SSM->>App: Return credentials
    App->>Bucket: Fetch data using direct S3 access
```

Once credentials are stored in SecretsManager they can be retrieved in several ways — see the
[AWS documentation](https://docs.aws.amazon.com/secretsmanager/latest/userguide/retrieving-secrets.html)
for options. Common patterns:

- **Lambda** — retrieve the secret during [static initialization](https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtime-environment.html#static-initialization)
  so it is fetched once per container, not per invocation. AWS also provides a
  [SecretsManager extension layer](https://docs.aws.amazon.com/lambda/latest/dg/with-secrets-manager.html)
  that handles caching automatically.
- **AWS Batch** — configure the secret in the JobDefinition; Batch injects it as an environment variable.
- **Long-lived processes** — use a singleton that fetches, caches, and refreshes the secret before expiry.

## Development

### Requirements

- Python>=3.9
- Docker
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- aws-cli
- An IAM role with sufficient permissions for creating, destroying and modifying the relevant stack resources.

To begin, install developer and application dependencies using `uv`,

```
$ uv sync --all-groups
```

Then run the following to install the project's pre-commit hooks

```
$ pre-commit install
```

## Linting, formatting, and type checks

This project uses `ruff` for lint/formatting and `mypy` for type checks,

```
$ scripts/format
$ scripts/lint
$ scripts/typecheck
```

## Tests

To run unit test for the credential rotation Lambda function,

```
scripts/test
```
