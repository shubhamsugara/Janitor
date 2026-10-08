"""Lock 2: reach every account through AssumeRole with a Describe-only session policy.

Source credentials (the admin profile's source_profile, kept fresh by the user's usual MFA
session) assume the admin role; the admin session then assumes `member_role` in each other
account. AWS grants the intersection of a role's permissions and the session policy, so even an
admin role can only describe, and the admin session can additionally assume only the member role.
mfa_serial is not sent: the source credentials are already an MFA session.
"""

import json

import boto3
import botocore.session
from botocore.config import Config as BotoConfig

from janitor.config import Config
from janitor.providers import guard

SESSION_NAME = "janitor-readonly"
DESCRIBE = ["ec2:Describe*", "autoscaling:Describe*", "rds:Describe*"]
SESSION_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": DESCRIBE,
            "Resource": "*",
        }
    ],
}


def ADMIN_POLICY(member_role: str) -> dict:  # noqa: N802 - a constant, parameterized
    """Describe, plus assuming the member role in other accounts, and nothing else."""
    return {
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow", "Action": DESCRIBE, "Resource": "*"},
            {
                "Effect": "Allow",
                "Action": "sts:AssumeRole",
                "Resource": f"arn:aws:iam::*:role/{member_role}",
            },
        ],
    }


CLIENT_CONFIG = BotoConfig(retries={"mode": "adaptive", "max_attempts": 10})


class ProfileError(Exception):
    """The local AWS config can't be used to reach the configured accounts."""


def _profiles() -> dict[str, dict]:
    return botocore.session.Session().full_config.get("profiles", {})


def check_profiles(config: Config) -> None:
    """Refuse to start in AWS mode unless the admin profile assumes a role and member_role is set."""
    profile = _profiles().get(config.admin.profile)
    problems = []
    if not config.admin.profile or profile is None:
        problems.append(
            f"admin profile {config.admin.profile or '(none)'} isn't in your AWS config"
        )
    elif not profile.get("role_arn") or not profile.get("source_profile"):
        problems.append(f"admin profile {config.admin.profile} needs role_arn and source_profile")
    if not config.member_role:
        problems.append("member_role isn't set (the role Janitor assumes in every other account)")
    if problems:
        raise ProfileError(
            "Janitor can't reach your accounts: "
            + "; ".join(problems)
            + ". Fix them in janitor.yaml or your AWS config, then start again."
        )


def _assume(sts, role_arn: str, policy: dict, region: str, **extra) -> boto3.Session:
    """AssumeRole through an STS client (from a guarded session) with the session policy."""
    params = {
        "RoleArn": role_arn,
        "RoleSessionName": SESSION_NAME,
        "DurationSeconds": 3600,
        "Policy": json.dumps(policy),
        **extra,
    }
    creds = sts.assume_role(**params)["Credentials"]
    return boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        region_name=region,
    )


def assume_admin(config: Config) -> boto3.Session:
    """A guarded admin session: Describe, and AssumeRole into member_role only."""
    profile = _profiles()[config.admin.profile]
    region = config.regions[0]
    source = boto3.Session(profile_name=profile["source_profile"], region_name=region)
    guard.install(source, extra=frozenset({"AssumeRole"}))
    extra = {"ExternalId": profile["external_id"]} if profile.get("external_id") else {}
    sts = source.client("sts", config=CLIENT_CONFIG)
    admin = _assume(sts, profile["role_arn"], ADMIN_POLICY(config.member_role), region, **extra)
    guard.install(admin, extra=frozenset({"AssumeRole"}))
    return admin


def assume_member(config: Config, admin: boto3.Session, account_id: str, sts=None) -> boto3.Session:
    """A guarded, Describe-only session in another account, reached from the admin session.

    Pass `sts` (a client made from `admin`) when hopping in parallel: boto3 Sessions aren't
    thread-safe, clients are.
    """
    if account_id == config.admin.account:
        return admin
    role_arn = f"arn:aws:iam::{account_id}:role/{config.member_role}"
    sts = sts or admin.client("sts", config=CLIENT_CONFIG)
    member = _assume(sts, role_arn, SESSION_POLICY, config.regions[0])
    guard.install(member)
    return member
