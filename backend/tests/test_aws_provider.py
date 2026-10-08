"""AwsProvider end to end on moto: several accounts reached through AssumeRole."""

from datetime import UTC, datetime

import pytest
from aws_helpers import account_session, record_calls, write_aws_config
from helpers import DEV, TOOLS
from moto import mock_aws

from janitor.config import Config
from janitor.providers.aws import OPERATIONS, AwsProvider
from janitor.providers.guard import ALLOWED_PREFIXES

NOW = datetime(2026, 10, 8, tzinfo=UTC)
MOTO_BASE_AMI = "ami-12c6146b"  # one of moto's built-in public images


def make_config(**overrides) -> Config:
    data = {
        "provider": "aws",
        "owner": {"account": TOOLS, "regions": ["us-east-1", "us-west-2"]},
        "accounts": {
            TOOLS: {
                "name": "tools",
                "profile": "example-tools",
                "owns": ["ami", "snapshot", "volume"],
            },
            DEV: {
                "name": "dev",
                "profile": "example-dev",
                "owns": ["snapshot", "volume", "rds_snapshot"],
            },
        },
        "scan": {"concurrency": 4},
    }
    data.update(overrides)
    return Config.model_validate(data)


@pytest.fixture
def aws(tmp_path, monkeypatch):
    write_aws_config(tmp_path, monkeypatch, {TOOLS: "tools", DEV: "dev"})
    with mock_aws():
        yield tmp_path


def build_world() -> dict:
    """An owner AMI shared with dev and run there, a copied snapshot, volumes, RDS snapshots."""
    tools = account_session(TOOLS).client("ec2")
    builder = tools.run_instances(ImageId=MOTO_BASE_AMI, MinCount=1, MaxCount=1)["Instances"][0]
    ami = tools.create_image(InstanceId=builder["InstanceId"], Name="base-linux")["ImageId"]
    tools.modify_image_attribute(ImageId=ami, LaunchPermission={"Add": [{"UserId": DEV}]})
    tools_volume = tools.create_volume(AvailabilityZone="us-east-1a", Size=8)["VolumeId"]
    copied = tools.create_snapshot(
        VolumeId=tools_volume,
        Description=f"Copied for DestinationAmi {ami} from SourceAmi ami-0f0a1d2e3c4b5a697 "
        "for SourceSnapshot snap-0a1d. Task created on 1,700,000,000,000.",
    )["SnapshotId"]

    dev = account_session(DEV)
    dev_ec2 = dev.client("ec2")
    used = dev_ec2.run_instances(ImageId=ami, MinCount=1, MaxCount=1)["Instances"][0]["InstanceId"]
    dev_volume = dev_ec2.create_volume(AvailabilityZone="us-east-1a", Size=20)["VolumeId"]
    rds = dev.client("rds")
    rds.create_db_instance(
        DBInstanceIdentifier="orders",
        DBInstanceClass="db.t3.micro",
        Engine="postgres",
        AllocatedStorage=20,
        MasterUsername="admin1",
        MasterUserPassword="password1",
    )
    rds.create_db_snapshot(DBInstanceIdentifier="orders", DBSnapshotIdentifier="orders-snap")
    rds.create_db_cluster(
        DBClusterIdentifier="billing",
        Engine="aurora-postgresql",
        MasterUsername="admin1",
        MasterUserPassword="password1",
    )
    rds.create_db_cluster_snapshot(
        DBClusterIdentifier="billing", DBClusterSnapshotIdentifier="billing-snap"
    )
    return {"ami": ami, "copied": copied, "used_by": used, "dev_volume": dev_volume}


def test_full_scan_across_accounts(aws):
    world = build_world()
    inventory = AwsProvider(make_config(), clock=lambda: NOW).list_inventory()

    assert all(s.ok for s in inventory.segments), [s for s in inventory.segments if not s.ok]
    by_id = {r.id: r for r in inventory.resources}
    ami = by_id[world["ami"]]
    assert (ami.type, ami.account, ami.region, ami.name) == (
        "ami",
        TOOLS,
        "us-east-1",
        "base-linux",
    )
    assert [(s.principal_type, s.principal) for s in inventory.shares if s.image_id == ami.id] == [
        ("account", DEV)
    ]
    assert [(u.account, u.region, u.ref_type, u.ref_id) for u in inventory.usage] == [
        (DEV, "us-east-1", "instance", world["used_by"])
    ]
    assert by_id[world["copied"]].linked_ami_id == world["ami"]
    assert by_id[world["dev_volume"]].account == DEV
    rds = {r.name: r for r in inventory.resources if r.type == "rds_snapshot"}
    assert rds["orders-snap"].db_kind == "instance"
    assert rds["billing-snap"].db_kind == "cluster"
    assert {(d.id, d.kind) for d in inventory.databases} >= {
        ("orders", "instance"),
        ("billing", "cluster"),
    }
    # moto's built-in public snapshots belong to another account and must not appear.
    assert {r.account for r in inventory.resources} == {TOOLS, DEV}


def test_segments_cover_every_account_region_and_kind(aws):
    build_world()
    seen = []
    inventory = AwsProvider(make_config(), clock=lambda: NOW).list_inventory(on_segment=seen.append)
    got = sorted((s.account, s.region, s.kind) for s in inventory.segments)
    expected = sorted(
        [
            (TOOLS, r, k)
            for r in ("us-east-1", "us-west-2")
            for k in ("ami", "snapshot", "volume", "usage")
        ]
        + [
            (DEV, r, k)
            for r in ("us-east-1", "us-west-2")
            for k in ("snapshot", "volume", "rds_snapshot", "database")
        ]
        + [(DEV, "us-east-1", "usage")]  # the AMI is shared with dev in us-east-1 only
    )
    assert got == expected
    assert len(seen) == len(inventory.segments)


def test_pagination_reads_every_page(aws, monkeypatch):
    # moto pages DescribeDBInstances (20 records minimum) but ignores page size for EC2 lists.
    rds = account_session(DEV).client("rds")
    for i in range(25):
        rds.create_db_instance(
            DBInstanceIdentifier=f"db{i}",
            DBInstanceClass="db.t3.micro",
            Engine="postgres",
            AllocatedStorage=20,
            MasterUsername="admin1",
            MasterUserPassword="password1",
        )
    calls = record_calls(monkeypatch)
    inventory = AwsProvider(make_config(), clock=lambda: NOW, page_size=20).list_inventory()
    assert {f"db{i}" for i in range(25)} <= {d.id for d in inventory.databases}
    assert sum(1 for op, _ in calls if op == "DescribeDBInstances") >= 3  # 2 pages + 1 region


def test_an_account_whose_role_cant_be_assumed_fails_only_its_segments(aws):
    world = build_world()
    config_file = aws / "aws-config"
    config_file.write_text(
        config_file.read_text().replace(
            f"role_arn = arn:aws:iam::{DEV}:role/janitor-read\nsource_profile = example-base",
            f"role_arn = arn:aws:iam::{DEV}:role/janitor-read\nsource_profile = example-nokeys",
        )
        + "[profile example-nokeys]\nregion = us-east-1\n"
    )
    inventory = AwsProvider(make_config(), clock=lambda: NOW).list_inventory()
    dev_segments = [s for s in inventory.segments if s.account == DEV]
    assert dev_segments and all(not s.ok and s.error_kind == "expired" for s in dev_segments)
    assert all(s.ok for s in inventory.segments if s.account == TOOLS)
    assert {r.account for r in inventory.resources} == {TOOLS}
    assert world["ami"] in {r.id for r in inventory.resources}


def test_provider_exposes_only_read_methods():
    public = {name for name in dir(AwsProvider) if not name.startswith("_")}
    assert public == {"name", "list_inventory", "recheck"}


def test_every_operation_sent_is_listed_and_read_only(aws, monkeypatch):
    build_world()
    calls = record_calls(monkeypatch)
    AwsProvider(make_config(), clock=lambda: NOW).list_inventory()
    sent = {op for op, _ in calls}
    assert sent - {"AssumeRole"} <= OPERATIONS
    assert "AssumeRole" in sent
    assert all(op.startswith(ALLOWED_PREFIXES) for op in OPERATIONS)
