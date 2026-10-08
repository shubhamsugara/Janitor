"""AwsProvider end to end on moto: several accounts reached through AssumeRole."""

from datetime import UTC, datetime

import pytest
from aws_helpers import MEMBER_ROLE, account_session, record_calls, write_aws_config
from helpers import DEV, TOOLS
from moto import mock_aws

from janitor.config import Config
from janitor.providers.aws import OPERATIONS, AwsProvider
from janitor.providers.guard import ALLOWED_PREFIXES

NOW = datetime(2026, 10, 8, tzinfo=UTC)
MOTO_BASE_AMI = "ami-12c6146b"  # one of moto's built-in public images


def make_config(**overrides) -> Config:
    """Admin tools in two regions; dev is named here but is also found from launch permissions."""
    data = {
        "provider": "aws",
        "admin": {
            "account": TOOLS,
            "name": "tools",
            "profile": "example-tools",
            "regions": ["us-east-1", "us-west-2"],
        },
        "member_role": MEMBER_ROLE,
        "accounts": {DEV: {"name": "dev"}},
        "scan": {"concurrency": 4},
    }
    data.update(overrides)
    return Config.model_validate(data)


def deny_member(monkeypatch, account: str) -> None:
    """Make the hop from admin into `account` fail, as a missing or untrusting role would."""
    from botocore.exceptions import ClientError

    from janitor.providers import session

    real = session.assume_member

    def assume_member(config, account_id, sts):
        if account_id == account:
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "AssumeRole")
        return real(config, account_id, sts)

    monkeypatch.setattr(session, "assume_member", assume_member)


@pytest.fixture
def aws(tmp_path, monkeypatch):
    write_aws_config(tmp_path, monkeypatch)
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
    regions = ("us-east-1", "us-west-2")
    expected = sorted(
        [(TOOLS, r, k) for r in regions for k in ("ami", "snapshot", "volume", "usage", "ecs")]
        + [
            (DEV, r, k)
            for r in regions
            for k in ("snapshot", "volume", "rds_snapshot", "database", "usage", "ecs")
        ]
    )
    assert got == expected
    assert len(seen) == len(inventory.segments)


def build_deployments(ami: str) -> None:
    """In dev: a live blue/green ASG on `ami`, its undeployed predecessor, an untagged ASG, and
    an ECS service whose task definition carries the app and version tags."""
    dev = account_session(DEV)
    ec2, autoscaling = dev.client("ec2"), dev.client("autoscaling")
    template = ec2.create_launch_template(
        LaunchTemplateName="web", LaunchTemplateData={"ImageId": MOTO_BASE_AMI}
    )["LaunchTemplate"]
    ec2.create_launch_template_version(
        LaunchTemplateId=template["LaunchTemplateId"], LaunchTemplateData={"ImageId": ami}
    )

    def asg(name: str, pinned: str, desired: int, **tags: str) -> None:
        autoscaling.create_auto_scaling_group(
            AutoScalingGroupName=name,
            LaunchTemplate={"LaunchTemplateId": template["LaunchTemplateId"], "Version": pinned},
            MinSize=0,
            MaxSize=2,
            DesiredCapacity=desired,
            AvailabilityZones=["us-east-1a"],
            Tags=[
                {"Key": k.replace("_", "-"), "Value": v, "PropagateAtLaunch": False}
                for k, v in tags.items()
            ],
        )

    asg(
        "dev-web-1.1.0-1", "1", 0, role="web", env="dev", version="1.1.0", deploy_state="undeployed"
    )
    asg(
        "dev-web-1.2.0-2",
        "2",
        1,
        role="web",
        env="dev",
        version="1.2.0",
        deploy_state="deployed",
        deployment_id="2",
    )
    asg("eks-nodes", "1", 0)

    ecs = dev.client("ecs")
    ecs.create_cluster(clusterName="apps")
    taskdef = ecs.register_task_definition(
        family="orders-api",
        containerDefinitions=[
            {"name": "app", "image": "registry.example/orders-api:2.7.0", "memory": 512}
        ],
        tags=[{"key": "app", "value": "orders-api"}, {"key": "version", "value": "2.7.0"}],
    )["taskDefinition"]["taskDefinitionArn"]
    ecs.create_service(
        cluster="apps", serviceName="orders-api", taskDefinition=taskdef, desiredCount=2
    )


def test_deployments_from_tagged_asgs_and_ecs_services(aws):
    world = build_world()
    build_deployments(world["ami"])
    inventory = AwsProvider(make_config(), clock=lambda: NOW).list_inventory()
    assert all(s.ok for s in inventory.segments), [s for s in inventory.segments if not s.ok]
    found = sorted(
        (d.kind, d.account, d.region, d.env, d.app, d.version, d.state)
        for d in inventory.deployments
        if d.unit != "instance"
    )
    assert found == [
        ("ec2", DEV, "us-east-1", "dev", "web", "1.1.0", "undeployed"),
        ("ec2", DEV, "us-east-1", "dev", "web", "1.2.0", "deployed"),
        ("ecs", DEV, "us-east-1", "dev", "orders-api", "2.7.0", "deploying"),  # moto: rolling out
    ]
    live = next(d for d in inventory.deployments if d.state == "deployed" and d.unit == "asg")
    assert (live.ami_id, live.launch_template, live.launch_template_version) == (
        world["ami"],
        "web",
        "2",
    )
    assert (live.deployment_id, live.desired) == ("2", 1)
    ecs = next(d for d in inventory.deployments if d.kind == "ecs")
    assert (ecs.cluster, ecs.task_definition, ecs.desired) == ("apps", "orders-api:1", 2)


def test_instances_in_no_asg_are_deployments_and_asg_instances_are_not(aws):
    world = build_world()
    build_deployments(world["ami"])
    inventory = AwsProvider(make_config(), clock=lambda: NOW).list_inventory()
    lone = {
        (d.account, d.resource_id, d.unit) for d in inventory.deployments if d.unit == "instance"
    }
    # tools' image builder and dev's instance; never the instance dev-web-1.2.0-2 launched
    assert {(a, r) for a, r, _ in lone} >= {(DEV, world["used_by"])}
    assert all(r.startswith("i-") for _, r, _ in lone)
    asg_instances = (
        account_session(DEV)
        .client("autoscaling")
        .describe_auto_scaling_groups(AutoScalingGroupNames=["dev-web-1.2.0-2"])[
            "AutoScalingGroups"
        ][0]["Instances"]
    )
    assert asg_instances and not {i["InstanceId"] for i in asg_instances} & {r for _, r, _ in lone}


def test_an_ecs_check_that_fails_doesnt_touch_amis(aws, monkeypatch):
    from botocore.exceptions import ClientError

    world = build_world()
    real = AwsProvider._ecs

    def denied(self, sess, account, region):
        if account == DEV:
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "ListClusters")
        return real(self, sess, account, region)

    monkeypatch.setattr(AwsProvider, "_ecs", denied)
    inventory = AwsProvider(make_config(), clock=lambda: NOW).list_inventory()
    failed = [(s.account, s.kind, s.error_kind) for s in inventory.segments if not s.ok]
    assert failed == [(DEV, "ecs", "denied")] * 2  # both regions
    assert world["ami"] in {r.id for r in inventory.resources}


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


def test_an_account_whose_role_cant_be_assumed_fails_only_its_segments(aws, monkeypatch):
    world = build_world()
    deny_member(monkeypatch, DEV)
    inventory = AwsProvider(make_config(), clock=lambda: NOW).list_inventory()
    dev_segments = [s for s in inventory.segments if s.account == DEV]
    assert dev_segments and all(
        (s.ok, s.error_kind, s.error) == (False, "denied", "sts:AssumeRole") for s in dev_segments
    )
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


def test_recheck_reports_accounts_it_cant_reach(aws, monkeypatch):
    deny_member(monkeypatch, DEV)
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

    def unreachable(config):
        raise RuntimeError("no")

    monkeypatch.setattr(aws_module.session, "source", unreachable)
    inventory = AwsProvider(make_config(), clock=lambda: NOW).list_inventory()
    # tools: ami, snapshot, volume, usage, ecs; dev (listed): six kinds; two regions each
    assert len(inventory.segments) == 2 * 5 + 2 * 6
    assert all(not s.ok and s.error_kind == "other" for s in inventory.segments)


def test_an_account_found_only_in_launch_permissions_is_scanned_through_the_hub(aws):
    world = build_world()
    inventory = AwsProvider(make_config(accounts={}), clock=lambda: NOW).list_inventory()
    assert {(s.account, s.kind) for s in inventory.segments if s.account == DEV} == {
        (DEV, k) for k in ("snapshot", "volume", "rds_snapshot", "database", "usage", "ecs")
    }
    assert [(u.account, u.ref_id) for u in inventory.usage] == [(DEV, world["used_by"])]
    assert world["dev_volume"] in {r.id for r in inventory.resources}


def test_all_hops_share_one_sts_client_from_the_source_login(aws, monkeypatch):
    # boto3 Sessions aren't thread-safe; clients are. Parallel hops must not each build a client.
    from janitor.providers import session

    made = []
    real_source = session.source

    def counting_source(config):
        src = real_source(config)
        real_client = src.client

        def client(service, *args, **kwargs):
            made.append(service)
            return real_client(service, *args, **kwargs)

        src.client = client
        return src

    monkeypatch.setattr(session, "source", counting_source)
    members = ["222222222222", "333333333333", "555555555555", "666666666666", "777777777777"]
    sessions = AwsProvider(make_config(), clock=lambda: NOW)._sessions(members)
    assert made.count("sts") == 1
    assert all(not isinstance(s, Exception) for s in sessions.values())


def test_members_are_reached_even_when_the_admin_role_is_denied(aws, monkeypatch):
    # Every role trusts the source login, so one account's denial doesn't block the others.
    from botocore.exceptions import ClientError

    from janitor.providers import session

    def denied(config, sts):
        raise ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "AssumeRole")

    monkeypatch.setattr(session, "assume_admin", denied)
    sessions = AwsProvider(make_config(), clock=lambda: NOW)._sessions([DEV])
    assert isinstance(sessions[TOOLS], Exception)
    assert not isinstance(sessions[DEV], Exception)
