"""Locks 2 and 3: the Describe-only session policy and the runtime guard."""

import json

import boto3
import pytest
from aws_helpers import record_calls, write_aws_config
from helpers import DEV, EXAMPLE, TOOLS
from moto import mock_aws

from janitor.config import load_config
from janitor.providers.guard import ReadOnlyViolation
from janitor.providers.session import SESSION_POLICY, ProfileError, assume, check_profiles


@pytest.fixture
def config():
    return load_config(EXAMPLE)


@pytest.fixture
def profiles(tmp_path, monkeypatch, config):
    write_aws_config(
        tmp_path, monkeypatch, {account_id: a.name for account_id, a in config.accounts.items()}
    )
    # The example config names profiles example-<name>, which is what write_aws_config writes.
    return tmp_path


def test_session_policy_allows_only_describe():
    (statement,) = SESSION_POLICY["Statement"]
    assert statement["Effect"] == "Allow"
    assert statement["Action"] == ["ec2:Describe*", "autoscaling:Describe*", "rds:Describe*"]


def test_check_profiles_names_every_bad_profile(tmp_path, monkeypatch, config):
    names = {account_id: a.name for account_id, a in config.accounts.items()}
    names.pop(DEV)  # example-dev missing entirely
    write_aws_config(tmp_path, monkeypatch, names)
    path = tmp_path / "aws-config"
    text = path.read_text().replace(
        "[profile example-tools]\nrole_arn = arn:aws:iam::111111111111:role/janitor-read\n",
        "[profile example-tools]\n",
    )
    path.write_text(text)
    with pytest.raises(ProfileError) as error:
        check_profiles(config)
    assert "example-dev" in str(error.value)
    assert "example-tools" in str(error.value)
    assert "role_arn" in str(error.value)


def test_check_profiles_passes_when_all_profiles_assume_roles(profiles, config):
    check_profiles(config)


@mock_aws
def test_assume_role_sends_the_session_policy(profiles, config, monkeypatch):
    calls = record_calls(monkeypatch)
    assume(config, DEV)
    (params,) = [p for op, p in calls if op == "AssumeRole"]
    assert params["RoleArn"] == f"arn:aws:iam::{DEV}:role/janitor-read"
    assert params["RoleSessionName"] == "janitor-readonly"
    assert params["DurationSeconds"] == 3600
    assert json.loads(params["Policy"]) == SESSION_POLICY


@mock_aws
def test_guard_stops_a_mutating_call_before_it_is_sent(profiles, config):
    session = assume(config, TOOLS)
    ec2 = session.client("ec2", region_name="us-east-1")
    # Create a snapshot through an unguarded client in the same account.
    raw = _raw_client(session)
    vol = raw.create_volume(AvailabilityZone="us-east-1a", Size=1)
    snap = raw.create_snapshot(VolumeId=vol["VolumeId"])
    with pytest.raises(ReadOnlyViolation, match="DeleteSnapshot"):
        ec2.delete_snapshot(SnapshotId=snap["SnapshotId"])
    found = raw.describe_snapshots(SnapshotIds=[snap["SnapshotId"]])["Snapshots"]
    assert [s["SnapshotId"] for s in found] == [snap["SnapshotId"]]
    assert ec2.describe_snapshots(OwnerIds=["self"])["Snapshots"]


def _raw_client(session):
    creds = session.get_credentials().get_frozen_credentials()
    return boto3.client(
        "ec2",
        region_name="us-east-1",
        aws_access_key_id=creds.access_key,
        aws_secret_access_key=creds.secret_key,
        aws_session_token=creds.token,
    )
