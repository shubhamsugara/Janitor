"""Locks 2 and 3 through the admin hub: Describe-only session policies and the runtime guard."""

import json

import boto3
import pytest
from aws_helpers import MEMBER_ROLE, record_calls, write_aws_config
from helpers import DEV, EXAMPLE, TOOLS
from moto import mock_aws

from janitor.config import load_config
from janitor.providers.guard import ReadOnlyViolation
from janitor.providers.session import (
    SESSION_POLICY,
    ProfileError,
    assume_admin,
    assume_member,
    check_profiles,
    source,
)


@pytest.fixture
def config():
    return load_config(EXAMPLE)


@pytest.fixture
def profiles(tmp_path, monkeypatch):
    write_aws_config(tmp_path, monkeypatch)
    return tmp_path


def test_member_session_policy_allows_only_describe_and_list():
    (statement,) = SESSION_POLICY["Statement"]
    assert statement["Effect"] == "Allow"
    assert statement["Action"] == [
        "ec2:Describe*",
        "autoscaling:Describe*",
        "rds:Describe*",
        "ecs:Describe*",
        "ecs:List*",  # ECS lists clusters and services; there is no Describe for that
    ]


def test_check_profiles_names_the_admin_profile_and_member_role(tmp_path, monkeypatch, config):
    write_aws_config(tmp_path, monkeypatch)
    path = tmp_path / "aws-config"
    path.write_text(path.read_text().replace("[profile example-tools]", "[profile other]"))
    broken = config.model_copy(update={"member_role": ""})
    with pytest.raises(ProfileError) as error:
        check_profiles(broken)
    assert "example-tools" in str(error.value) and "member_role" in str(error.value)


def test_check_profiles_passes(profiles, config):
    check_profiles(config)


def hops(config):
    sts = source(config).client("sts")
    return sts, assume_admin(config, sts)


@mock_aws
def test_admin_and_member_hops_both_come_from_the_source_login(profiles, config, monkeypatch):
    calls = record_calls(monkeypatch)
    sts, _ = hops(config)
    assume_member(config, DEV, sts)
    first, second = [p for op, p in calls if op == "AssumeRole"]
    assert first["RoleArn"] == f"arn:aws:iam::{TOOLS}:role/example-admin-read"
    assert second["RoleArn"] == f"arn:aws:iam::{DEV}:role/{MEMBER_ROLE}"
    # Neither session may assume anything further: both carry the Describe-only policy.
    assert json.loads(first["Policy"]) == json.loads(second["Policy"]) == SESSION_POLICY
    assert {p["RoleSessionName"] for p in (first, second)} == {"janitor-readonly"}
    assert {p["DurationSeconds"] for p in (first, second)} == {3600}


@mock_aws
def test_an_account_can_name_its_own_role(profiles, config, monkeypatch):
    from janitor.config import AccountName

    custom = config.model_copy(
        update={"accounts": {DEV: AccountName(name="dev", role="example-other-read")}}
    )
    calls = record_calls(monkeypatch)
    sts, _ = hops(custom)
    assume_member(custom, DEV, sts)
    assert [p["RoleArn"] for op, p in calls if op == "AssumeRole"][-1] == (
        f"arn:aws:iam::{DEV}:role/example-other-read"
    )


@mock_aws
def test_member_session_lands_in_the_member_account(profiles, config):
    sts, _ = hops(config)
    member = assume_member(config, DEV, sts)
    assert member.client("sts").get_caller_identity()["Account"] == DEV


@mock_aws
def test_guard_stops_mutating_calls_on_every_session(profiles, config):
    sts, admin = hops(config)
    for session in (source(config), admin, assume_member(config, DEV, sts)):
        ec2 = session.client("ec2", region_name="us-east-1")
        raw = _raw_client(admin)
        vol = raw.create_volume(AvailabilityZone="us-east-1a", Size=1)
        snap = raw.create_snapshot(VolumeId=vol["VolumeId"])
        with pytest.raises(ReadOnlyViolation, match="DeleteSnapshot"):
            ec2.delete_snapshot(SnapshotId=snap["SnapshotId"])
        assert raw.describe_snapshots(SnapshotIds=[snap["SnapshotId"]])["Snapshots"]


def _raw_client(session):
    creds = session.get_credentials().get_frozen_credentials()
    return boto3.client(
        "ec2",
        region_name="us-east-1",
        aws_access_key_id=creds.access_key,
        aws_secret_access_key=creds.secret_key,
        aws_session_token=creds.token,
    )


DEV_PROFILE = f"""[profile example-dev]
role_arn = arn:aws:iam::{DEV}:role/{MEMBER_ROLE}
source_profile = example-base
role_session_name = example-person
"""


def with_dev_profile(config):
    from janitor.config import AccountName

    return config.model_copy(
        update={"accounts": {DEV: AccountName(name="dev", profile="example-dev")}}
    )


def test_an_account_profile_supplies_its_role_and_session_name(tmp_path, monkeypatch, config):
    write_aws_config(tmp_path, monkeypatch, extra=DEV_PROFILE)  # before moto takes over the env
    custom = with_dev_profile(config)
    check_profiles(custom)
    with mock_aws():
        calls = record_calls(monkeypatch)
        sts, _ = hops(custom)
        member = assume_member(custom, DEV, sts)
        params = [p for op, p in calls if op == "AssumeRole"][-1]
        assert params["RoleArn"] == f"arn:aws:iam::{DEV}:role/{MEMBER_ROLE}"
        assert params["RoleSessionName"] == "example-person"  # trust policies may require it
        assert json.loads(params["Policy"]) == SESSION_POLICY
        assert member.client("sts").get_caller_identity()["Account"] == DEV


@pytest.mark.parametrize(
    ("profile_text", "problem"),
    [
        ("", "example-dev (for dev) isn't in your AWS config"),
        (
            DEV_PROFILE.replace(DEV, TOOLS),
            "example-dev (for dev) assumes a role in another account",
        ),
        (
            DEV_PROFILE.replace("source_profile = example-base", "source_profile = other"),
            "example-dev (for dev) uses a different source login",
        ),
    ],
)
def test_check_profiles_checks_account_profiles(
    tmp_path, monkeypatch, config, profile_text, problem
):
    write_aws_config(tmp_path, monkeypatch, extra=profile_text)
    with pytest.raises(ProfileError, match=problem.replace("(", r"\(").replace(")", r"\)")):
        check_profiles(with_dev_profile(config))
