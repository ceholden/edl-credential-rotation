"""Tests for `edl_credential_rotator`"""

import json

import boto3
import responses
from moto import mock_aws

from edl_credential_rotation.handlers import s3credentials
from edl_credential_rotation.handlers.s3credentials import (
    EDL_AUTH_HOST,
    S3Credentials,
    fetch_s3_credentials,
)

LPDAAC_S3CREDENTIALS_URL = "https://data.lpdaac.earthdatacloud.nasa.gov/s3credentials"
EXPECTED_REDIRECT = f"https://{EDL_AUTH_HOST}/oauth/authorize"


@responses.activate
def test_fetch_s3_credentials_correct_redirect() -> None:
    """Test credential fetching works with the expected redirect"""
    resp1 = responses.Response(
        responses.GET,
        LPDAAC_S3CREDENTIALS_URL,
        status=307,
        headers={"location": EXPECTED_REDIRECT},
    )
    resp2 = responses.Response(
        responses.GET,
        EXPECTED_REDIRECT,
        json={
            "secretAccessKey": "foo",
            "accessKeyId": "baz",
            "sessionToken": "buz",
            "expiration": "2021-01-27 00:50:09+00:00",
        },
    )

    responses.add(resp1)
    responses.add(resp2)

    s3creds = fetch_s3_credentials(LPDAAC_S3CREDENTIALS_URL, "user", "password")
    # TypedDict doesn't support isinstance checks, but we can check the
    # keys match the expected type annotation
    assert list(s3creds) == list(S3Credentials.__annotations__)
    assert resp1.call_count == 1
    assert resp2.call_count == 1
    assert "Authorization" in resp2.calls[0].request.headers


@responses.activate
def test_fetch_s3_credentials_no_auth_bad_redirect() -> None:
    """Test credential fetching doesn't send user/password to unknown redirect"""
    redirect = "https://test.bad/"
    resp1 = responses.Response(
        responses.GET,
        LPDAAC_S3CREDENTIALS_URL,
        status=307,
        headers={"location": redirect},
    )
    resp2 = responses.Response(
        responses.GET,
        redirect,
        json={
            "secretAccessKey": "foo",
            "accessKeyId": "baz",
            "sessionToken": "buz",
            "expiration": "2021-01-27 00:50:09+00:00",
        },
    )

    responses.add(resp1)
    responses.add(resp2)

    fetch_s3_credentials(LPDAAC_S3CREDENTIALS_URL, "user", "password")
    assert resp1.call_count == 1
    assert resp2.call_count == 1
    # If our redirect was bad, ensure we don't pass our user/password via auth header
    assert "Authorization" not in resp2.calls[0].request.headers


@mock_aws
def test_edl_s3credential_rotator(monkeypatch) -> None:
    """Test rotator reads user/pass and writes S3 credentials to SSM"""
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    ssm = boto3.client("ssm")
    ssm.put_parameter(
        Name="/test/user-pass",
        Value=json.dumps({"USERNAME": "user", "PASSWORD": "password"}),
        Type="SecureString",
    )

    s3_credentials = S3Credentials(
        secret_access_key="foo",
        access_key_id="baz",
        session_token="buz",
        expiration="2021-01-27 00:50:09+00:00",
    )
    calls = []

    def fake_fetch(url: str, username: str, password: str) -> S3Credentials:
        calls.append((url, username, password))
        return s3_credentials

    monkeypatch.setattr(s3credentials, "fetch_s3_credentials", fake_fetch)

    for _ in range(2):
        s3credentials.edl_s3credential_rotator(
            LPDAAC_S3CREDENTIALS_URL, "/test/user-pass", "/test/s3-credentials"
        )

    assert calls[0] == (LPDAAC_S3CREDENTIALS_URL, "user", "password")
    param = ssm.get_parameter(Name="/test/s3-credentials", WithDecryption=True)
    assert param["Parameter"]["Type"] == "SecureString"
    assert param["Parameter"]["Version"] == 2
    assert json.loads(param["Parameter"]["Value"]) == {
        "SECRET_ACCESS_KEY": "foo",
        "ACCESS_KEY_ID": "baz",
        "SESSION_TOKEN": "buz",
        "EXPIRATION": "2021-01-27 00:50:09+00:00",
    }
