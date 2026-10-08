"""Fake AWS profiles for moto tests: one static-key base profile, one role profile per account."""

from botocore.client import BaseClient

ADMIN_ROLE = "example-admin-read"
MEMBER_ROLE = "example-janitor-read"


def write_aws_config(tmp_path, monkeypatch, admin: str = "111111111111", extra: str = "") -> None:
    """One static-key base profile and the admin profile, which assumes ADMIN_ROLE in `admin`.

    Member accounts need no profile (Janitor assumes member_role from the same source login);
    `extra` appends more profile sections verbatim.
    """
    lines = [
        "[profile example-base]",
        "aws_access_key_id = testing",
        "aws_secret_access_key = testing",
        "region = us-east-1",
        "[profile example-tools]",
        f"role_arn = arn:aws:iam::{admin}:role/{ADMIN_ROLE}",
        "source_profile = example-base",
        "[profile example-sbx]",  # the example config names this profile for sbx
        f"role_arn = arn:aws:iam::555555555555:role/{MEMBER_ROLE}",
        "source_profile = example-base",
    ]
    config = tmp_path / "aws-config"
    config.write_text("\n".join(lines) + "\n" + extra)
    (tmp_path / "aws-credentials").write_text("")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(config))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "aws-credentials"))
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")  # no slow instance-metadata lookups
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE"):
        monkeypatch.delenv(key, raising=False)


def record_calls(monkeypatch) -> list[tuple[str, dict]]:
    """Record (operation name, params) for every AWS call that reaches botocore's sender."""
    calls: list[tuple[str, dict]] = []
    original = BaseClient._make_api_call

    def wrapper(self, operation_name, api_params):
        calls.append((operation_name, api_params))
        return original(self, operation_name, api_params)

    monkeypatch.setattr(BaseClient, "_make_api_call", wrapper)
    return calls


def account_session(account_id: str, region: str = "us-east-1"):
    """An unguarded moto session inside an account, for creating test resources."""
    import boto3

    sts = boto3.client(
        "sts", region_name=region, aws_access_key_id="testing", aws_secret_access_key="testing"
    )
    creds = sts.assume_role(
        RoleArn=f"arn:aws:iam::{account_id}:role/setup", RoleSessionName="setup"
    )["Credentials"]
    return boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        region_name=region,
    )
