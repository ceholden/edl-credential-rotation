"""
Example CDK application using this construct
"""

import os
from typing import Any

from aws_cdk import App, Tags, Stack
from constructs import Construct

from edl_credential_rotation import EarthdataCredentialRotation

stack_name = os.environ["STACK_NAME"]


class EdlCredentialRotatorStack(Stack):
    """EDL Credentials Rotator CDK stack."""

    def __init__(self, scope: Construct, stack_id: str, **kwargs: Any) -> None:
        super().__init__(scope, f"{stack_id}App", **kwargs)
        self.edl_credential_rotator = EarthdataCredentialRotation(self, stack_id)


app = App()
stack = EdlCredentialRotatorStack(
    app,
    stack_name,
)

for k, v in dict(
    Stack=stack_name,
).items():
    Tags.of(app).add(k, v)

app.synth()
