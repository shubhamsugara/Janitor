"""Lock 2: reach each account through AssumeRole with a Describe-only session policy.

AWS grants the intersection of the role's permissions and the session policy, so even an admin
role can only describe. Source credentials come from the profile's source_profile, which the
user keeps fresh with their usual MFA session; mfa_serial is therefore not sent.
"""

import json

import boto3
import botocore.session
from botocore.config import Config as BotoConfig

from janitor.config import Config
from janitor.providers import guard

SESSION_NAME = "janitor-readonly"
SESSION_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": ["ec2:Describe*", "autoscaling:Describe*", "rds:Describe*"],
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
    """Refuse to start in AWS mode unless every account's profile assumes a role."""
    profiles = _profiles()
    problems = []
    for account in config.accounts.values():
        profile = profiles.get(account.profile)
        if profile is None:
            problems.append(f"{account.profile} (for {account.name}) isn't in your AWS config")
        elif not profile.get("role_arn") or not profile.get("source_profile"):
            problems.append(
                f"{account.profile} (for {account.name}) needs role_arn and source_profile"
            )
    if problems:
        raise ProfileError(
            "Janitor can't use these AWS profiles: "
            + "; ".join(problems)
            + ". Fix them in your AWS config, then start again."
        )


def assume(config: Config, account_id: str) -> boto3.Session:
    """Return a guarded session for the account, limited by the session policy."""
    profile = _profiles()[config.accounts[account_id].profile]
    region = config.owner.regions[0]
    source = boto3.Session(profile_name=profile["source_profile"], region_name=region)
    guard.install(source, extra=frozenset({"AssumeRole"}))
    params = {
        "RoleArn": profile["role_arn"],
        "RoleSessionName": SESSION_NAME,
        "DurationSeconds": 3600,
        "Policy": json.dumps(SESSION_POLICY),
    }
    if profile.get("external_id"):
        params["ExternalId"] = profile["external_id"]
    creds = source.client("sts", config=CLIENT_CONFIG).assume_role(**params)["Credentials"]
    session = boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        region_name=region,
    )
    guard.install(session)
    return session
