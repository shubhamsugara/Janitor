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


def item(resource_id, type, account, region="us-east-1", **extra):
    return {
        "id": resource_id,
        "type": type,
        "account": account,
        "region": region,
        "name": resource_id,
        **extra,
    }


def test_recheck_finds_deleted_and_newly_attached_volumes(aws):
    ec2 = account_session(DEV).client("ec2")
    gone = ec2.create_volume(AvailabilityZone="us-east-1a", Size=1)["VolumeId"]
    ec2.delete_volume(VolumeId=gone)
    attached = ec2.create_volume(AvailabilityZone="us-east-1a", Size=1)["VolumeId"]
    instance = ec2.run_instances(ImageId=MOTO_BASE_AMI, MinCount=1, MaxCount=1)["Instances"][0]
    ec2.attach_volume(VolumeId=attached, InstanceId=instance["InstanceId"], Device="/dev/sdf")
    quiet = ec2.create_volume(AvailabilityZone="us-east-1a", Size=1)["VolumeId"]
    snap = ec2.create_snapshot(VolumeId=quiet)["SnapshotId"]

    reasons = AwsProvider(make_config(), clock=lambda: NOW).recheck(
        [
            item(gone, "volume", DEV),
            item(attached, "volume", DEV),
            item(quiet, "volume", DEV),
            item(snap, "snapshot", DEV),
        ]
    )
    assert reasons == {
        gone: "It no longer exists.",
        attached: f"It is now attached to {instance['InstanceId']}.",
    }


def test_recheck_finds_new_use_and_new_launch_permissions(aws):
    world = build_world()
    tools = account_session(TOOLS).client("ec2")
    builder = tools.run_instances(ImageId=MOTO_BASE_AMI, MinCount=1, MaxCount=1)["Instances"][0]
    quiet = tools.create_image(InstanceId=builder["InstanceId"], Name="quiet")["ImageId"]
    widened = tools.create_image(InstanceId=builder["InstanceId"], Name="widened")["ImageId"]
    tools.modify_image_attribute(ImageId=widened, LaunchPermission={"Add": [{"Group": "all"}]})
    dev_share = [{"principal_type": "account", "principal": DEV}]

    reasons = AwsProvider(make_config(), clock=lambda: NOW).recheck(
        [
            item(world["ami"], "ami", TOOLS, shares=dev_share),
            item(quiet, "ami", TOOLS, shares=[]),
            item(widened, "ami", TOOLS, shares=[]),
        ]
    )
    assert reasons == {
        world["ami"]: f"Instance {world['used_by']} in dev now uses it.",
        widened: "Its launch permissions changed since the scan.",
    }


def test_recheck_rds_snapshot_that_is_gone(aws):
    rds = account_session(DEV).client("rds")
    rds.create_db_instance(
        DBInstanceIdentifier="orders",
        DBInstanceClass="db.t3.micro",
        Engine="postgres",
        AllocatedStorage=20,
        MasterUsername="admin1",
        MasterUserPassword="password1",
    )
    kept = rds.create_db_snapshot(DBInstanceIdentifier="orders", DBSnapshotIdentifier="kept")[
        "DBSnapshot"
    ]
    arn = f"arn:aws:rds:us-east-1:{DEV}:snapshot:gone"
    reasons = AwsProvider(make_config(), clock=lambda: NOW).recheck(
        [
            {**item(arn, "rds_snapshot", DEV), "name": "gone"},
            {**item(kept["DBSnapshotArn"], "rds_snapshot", DEV), "name": "kept"},
        ]
    )
    assert reasons == {arn: "It no longer exists."}


def test_recheck_reports_accounts_it_cant_reach(aws):
    config_file = aws / "aws-config"
    config_file.write_text(
        config_file.read_text().replace(
            f"role_arn = arn:aws:iam::{DEV}:role/janitor-read\nsource_profile = example-base",
            f"role_arn = arn:aws:iam::{DEV}:role/janitor-read\nsource_profile = example-nokeys",
        )
        + "[profile example-nokeys]\nregion = us-east-1\n"
    )
    reasons = AwsProvider(make_config(), clock=lambda: NOW).recheck(
        [item("vol-0abc", "volume", DEV)]
    )
    assert reasons["vol-0abc"].startswith("Janitor couldn't re-check it live: ")


def test_disabled_amis_are_listed_so_their_snapshots_stay_in_use(aws, monkeypatch):
    # DescribeImages hides disabled AMIs unless asked; a hidden AMI would orphan its snapshots.
    world = build_world()
    calls = record_calls(monkeypatch)
    provider = AwsProvider(make_config(), clock=lambda: NOW)
    provider.list_inventory()
    provider.recheck([item(world["ami"], "ami", TOOLS, shares=[])])
    image_calls = [p for op, p in calls if op == "DescribeImages"]
    assert image_calls and all(p.get("IncludeDisabled") is True for p in image_calls)


def test_recheck_sends_at_most_200_filter_values_per_call(aws, monkeypatch):
    ids = [f"vol-{n:017x}" for n in range(450)]
    calls = record_calls(monkeypatch)
    reasons = AwsProvider(make_config(), clock=lambda: NOW).recheck(
        [item(i, "volume", DEV) for i in ids]
    )
    sizes = [len(p["Filters"][0]["Values"]) for op, p in calls if op == "DescribeVolumes"]
    assert sizes and max(sizes) <= 200 and sum(sizes) == 450
    assert reasons == {i: "It no longer exists." for i in ids}


def test_a_check_that_fails_while_reporting_still_reports_as_failed(aws, monkeypatch):
    # A check missing from the report would read as ok and could make snapshots look orphaned.
    from janitor.providers import aws as aws_module

    def broken(exc):
        raise TypeError("classify broke")

    monkeypatch.setattr(aws_module.normalize, "classify", broken)
    monkeypatch.setattr(
        aws_module.session,
        "assume",
        lambda config, account: (_ for _ in ()).throw(RuntimeError("no")),
    )
    inventory = AwsProvider(make_config(), clock=lambda: NOW).list_inventory()
    planned = (
        2 * 3 + 2 * 4
    )  # tools: ami, snapshot, volume; dev: snapshot, volume, rds_snapshot, database
    assert len(inventory.segments) >= planned
    assert all(not s.ok and s.error_kind == "other" for s in inventory.segments)
