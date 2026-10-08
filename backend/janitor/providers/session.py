"""Lock 2: reach every account through AssumeRole with a Describe-only session policy.

Like the user's own AWS config, every hop starts from the same source credentials (the admin
profile's source_profile, kept fresh by the user's usual MFA session): the admin role, and
member_role (or an account's own role) in every other account. There is no role chaining, and
no Janitor session can assume anything further. AWS grants the intersection of a role's
permissions and the session policy, so even an admin role can only describe. mfa_serial is not
sent: the source credentials are already an MFA session.
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
    source_login = (profile or {}).get("source_profile")
    for account_id, account in config.accounts.items():
        if not account.profile:
            continue
        found = _profiles().get(account.profile)
        where = f"{account.profile} (for {account.name})"
        if found is None:
            problems.append(f"{where} isn't in your AWS config")
        elif f":{account_id}:role/" not in found.get("role_arn", ""):
            problems.append(f"{where} assumes a role in another account")
        elif found.get("source_profile") != source_login:
            problems.append(f"{where} uses a different source login than the admin profile")
    if problems:
        raise ProfileError(
            "Janitor can't reach your accounts: "
            + "; ".join(problems)
            + ". Fix them in janitor.yaml or your AWS config, then start again."
        )


def _assume(
    sts, role_arn: str, policy: dict, region: str, session_name: str = "", **extra
) -> boto3.Session:
    """AssumeRole through an STS client (from a guarded session) with the session policy.

    A profile's role_session_name is kept: trust policies may require it (e.g. for audit).
    """
    params = {
        "RoleArn": role_arn,
        "RoleSessionName": session_name or SESSION_NAME,
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


def source(config: Config) -> boto3.Session:
    """The user's source credentials, guarded: the only extra call it may make is AssumeRole."""
    profile = _profiles()[config.admin.profile]
    session = boto3.Session(profile_name=profile["source_profile"], region_name=config.regions[0])
    guard.install(session, extra=frozenset({"AssumeRole"}))
    return session


def assume_admin(config: Config, sts) -> boto3.Session:
    """A guarded, Describe-only session in the admin account. `sts` comes from source()."""
    profile = _profiles()[config.admin.profile]
    extra = {"ExternalId": profile["external_id"]} if profile.get("external_id") else {}
    admin = _assume(
        sts,
        profile["role_arn"],
        SESSION_POLICY,
        config.regions[0],
        profile.get("role_session_name", ""),
        **extra,
    )
    guard.install(admin)
    return admin


def assume_member(config: Config, account_id: str, sts) -> boto3.Session:
    """A guarded, Describe-only session in another account, assumed from the source login.

    `sts` is one client made from source() and shared by parallel hops: boto3 Sessions aren't
    thread-safe, clients are.
    """
    account = config.accounts.get(account_id)
    if account and account.profile:  # checked at startup: same account, same source login
        profile = _profiles()[account.profile]
        extra = {"ExternalId": profile["external_id"]} if profile.get("external_id") else {}
        member = _assume(
            sts,
            profile["role_arn"],
            SESSION_POLICY,
            config.regions[0],
            profile.get("role_session_name", ""),
            **extra,
        )
        guard.install(member)
        return member
    role_arn = f"arn:aws:iam::{account_id}:role/{config.role_for(account_id)}"
    member = _assume(sts, role_arn, SESSION_POLICY, config.regions[0])
    guard.install(member)
    return member
