"""Raw AWS response shapes become Janitor records in one place: janitor.providers.normalize."""

from datetime import UTC, datetime

import pytest
from botocore.exceptions import ClientError, NoCredentialsError
from helpers import DEV, TOOLS

from janitor.config import DeploymentTags
from janitor.providers import normalize as n
from janitor.providers.guard import ReadOnlyViolation

NOW = datetime(2026, 10, 1, tzinfo=UTC)
WHEN = datetime(2026, 1, 31, 12, 0, tzinfo=UTC)
AMIS = {"ami-0aaa", "ami-0bbb", "ami-0ccc"}


def ebs(snap, size):
    return {"DeviceName": "/dev/xvda", "Ebs": {"SnapshotId": snap, "VolumeSize": size}}


# Resources


def test_image_sums_ebs_sizes_and_lists_snapshots():
    raw = {
        "ImageId": "ami-0aaa",
        "Name": "base-linux",
        "CreationDate": "2026-01-31T12:00:00.000Z",
        "State": "available",
        "BlockDeviceMappings": [ebs("snap-01", 8), ebs("snap-02", 100)],
        "Tags": [{"Key": "owner", "Value": "platform"}],
        "SourceImageId": "ami-0src",
    }
    r = n.image(raw, TOOLS, "us-east-1")
    assert (r.id, r.type, r.account, r.region, r.name) == (
        "ami-0aaa",
        "ami",
        TOOLS,
        "us-east-1",
        "base-linux",
    )
    assert r.created_at == "2026-01-31T12:00:00Z"
    assert r.size_gb == 108
    assert r.snapshot_ids == ["snap-01", "snap-02"]
    assert r.tags == {"owner": "platform"}
    assert r.source_ami_id == "ami-0src"
    assert r.state == "available"


def test_instance_store_image_without_tags_or_name():
    raw = {
        "ImageId": "ami-0bbb",
        "CreationDate": "2026-01-31T12:00:00.000Z",
        "BlockDeviceMappings": [{"DeviceName": "/dev/sdb", "VirtualName": "ephemeral0"}],
    }
    r = n.image(raw, TOOLS, "us-east-1")
    assert r.size_gb is None
    assert r.snapshot_ids == []
    assert r.tags == {}
    assert r.name == "ami-0bbb"
    assert r.source_ami_id is None


@pytest.mark.parametrize(
    ("tags", "managed"),
    [
        ([{"Key": "aws:dlm:lifecycle-policy-id", "Value": "policy-1"}], "dlm"),
        ([{"Key": "aws:backup:source-resource", "Value": "x"}], "aws_backup"),
        ([], None),
    ],
)
def test_image_managed_markers(tags, managed):
    raw = {"ImageId": "ami-0ccc", "CreationDate": "2026-01-31T12:00:00.000Z", "Tags": tags}
    assert n.image(raw, TOOLS, "us-east-1").managed_by == managed


def snap(**extra):
    return {
        "SnapshotId": "snap-0abc",
        "VolumeId": "vol-0123",
        "VolumeSize": 30,
        "StartTime": WHEN,
        "State": "completed",
        "Description": "",
        **extra,
    }


def test_snapshot_built_by_create_image():
    r = n.snapshot(
        snap(Description="Created by CreateImage(i-0123abcd) for ami-0aaa from vol-0123"),
        TOOLS,
        "us-east-1",
    )
    assert (r.type, r.linked_ami_id, r.source_volume_id) == ("snapshot", "ami-0aaa", "vol-0123")
    assert (r.size_gb, r.created_at, r.name, r.storage_tier) == (
        30,
        "2026-01-31T12:00:00Z",
        "snap-0abc",
        "standard",
    )


def test_snapshot_copied_for_destination_ami():
    raw = snap(
        VolumeId="vol-ffffffff",
        Description="Copied for DestinationAmi ami-0d1e from SourceAmi ami-0f0a for SourceSnapshot "
        "snap-0a1d. Task created on 1,700,000,000,000.",
    )
    r = n.snapshot(raw, TOOLS, "us-west-2")
    assert r.linked_ami_id == "ami-0d1e"
    assert r.source_volume_id is None  # vol-ffffffff is AWS's "no volume"
    assert n.copy_of(raw) == ("ami-0d1e", "ami-0f0a")
    assert n.copy_of(snap()) is None


def test_snapshot_tier_name_and_managed():
    r = n.snapshot(
        snap(StorageTier="archive", Tags=[{"Key": "Name", "Value": "nightly"}]), DEV, "us-east-1"
    )
    assert (r.storage_tier, r.name, r.managed_by) == ("archive", "nightly", None)
    backup = n.snapshot(
        snap(Description="This snapshot is created by the AWS Backup service."), DEV, "us-east-1"
    )
    assert backup.managed_by == "aws_backup"
    dlm = n.snapshot(snap(Tags=[{"Key": "aws:dlm:lifecycle-policy-id", "Value": "p"}]), DEV, "x")
    assert dlm.managed_by == "dlm"


def test_volume_attachment_and_settings():
    raw = {
        "VolumeId": "vol-0a",
        "Size": 100,
        "CreateTime": WHEN,
        "State": "in-use",
        "VolumeType": "gp3",
        "Iops": 3000,
        "Throughput": 125,
        "Encrypted": True,
        "Attachments": [{"InstanceId": "i-0123", "State": "attached"}],
        "Tags": [{"Key": "Name", "Value": "api-data"}],
    }
    r = n.volume(raw, DEV, "us-east-1")
    assert (r.type, r.name, r.size_gb, r.state, r.attached_instance) == (
        "volume",
        "api-data",
        100,
        "in-use",
        "i-0123",
    )
    assert (r.volume_type, r.iops, r.throughput, r.encrypted) == ("gp3", 3000, 125, True)
    detached = n.volume({**raw, "Attachments": [], "Tags": []}, DEV, "us-east-1")
    assert (detached.attached_instance, detached.name) == (None, "vol-0a")


def test_db_instance_snapshot():
    raw = {
        "DBSnapshotIdentifier": "orders-before-upgrade",
        "DBSnapshotArn": "arn:aws:rds:us-east-1:222222222222:snapshot:orders-before-upgrade",
        "DBInstanceIdentifier": "orders",
        "SnapshotCreateTime": WHEN,
        "AllocatedStorage": 50,
        "SnapshotType": "manual",
        "Status": "available",
        "TagList": [{"Key": "owner", "Value": "data"}],
    }
    r = n.db_snapshot(raw, DEV, "us-east-1", cluster=False, now=NOW)
    assert r.id == raw["DBSnapshotArn"]
    assert (r.type, r.name, r.source_db_id, r.db_kind, r.size_gb) == (
        "rds_snapshot",
        "orders-before-upgrade",
        "orders",
        "instance",
        50,
    )
    assert (r.created_at, r.tags, r.managed_by, r.state) == (
        "2026-01-31T12:00:00Z",
        {"owner": "data"},
        None,
        "available",
    )


def test_db_cluster_snapshot_types_and_missing_times():
    raw = {
        "DBClusterSnapshotIdentifier": "rds:billing-2026-01-31",
        "DBClusterSnapshotArn": "arn:aws:rds:us-east-1:222222222222:cluster-snapshot:x",
        "DBClusterIdentifier": "billing",
        "AllocatedStorage": 1,
        "SnapshotType": "automated",
        "Status": "creating",
    }
    r = n.db_snapshot(raw, DEV, "us-east-1", cluster=True, now=NOW)
    assert (r.db_kind, r.source_db_id, r.managed_by) == ("cluster", "billing", "rds_automated")
    assert r.created_at == "2026-10-01T00:00:00Z"  # still creating: no time yet
    original = n.db_snapshot(
        {**raw, "OriginalSnapshotCreateTime": WHEN, "SnapshotType": "awsbackup"},
        DEV,
        "us-east-1",
        cluster=True,
        now=NOW,
    )
    assert (original.created_at, original.managed_by) == ("2026-01-31T12:00:00Z", "aws_backup")


def test_databases():
    assert n.database({"DBInstanceIdentifier": "orders"}, DEV, "us-east-1", cluster=False).kind == (
        "instance"
    )
    cluster = n.database({"DBClusterIdentifier": "billing"}, DEV, "us-east-1", cluster=True)
    assert (cluster.id, cluster.kind, cluster.account) == ("billing", "cluster", DEV)


def test_shares_from_launch_permissions():
    perms = [
        {"UserId": DEV},
        {"Group": "all"},
        {"OrganizationArn": "arn:aws:organizations::111111111111:organization/o-x"},
        {"OrganizationalUnitArn": "arn:aws:organizations::111111111111:ou/o-x/ou-y"},
    ]
    got = [(s.image_id, s.principal_type) for s in n.shares("ami-0aaa", perms)]
    assert got == [
        ("ami-0aaa", "account"),
        ("ami-0aaa", "group"),
        ("ami-0aaa", "org"),
        ("ami-0aaa", "ou"),
    ]
    assert n.shares("ami-0aaa", perms)[0].principal == DEV


def test_fill_copy_sources_from_snapshot_descriptions():
    copy = n.image(
        {"ImageId": "ami-0new", "CreationDate": "2026-01-31T12:00:00.000Z"}, TOOLS, "us-west-2"
    )
    known = n.image(
        {
            "ImageId": "ami-0has",
            "CreationDate": "2026-01-31T12:00:00.000Z",
            "SourceImageId": "ami-0keep",
        },
        TOOLS,
        "us-west-2",
    )
    n.fill_copy_sources([copy, known], {"ami-0new": "ami-0src", "ami-0has": "ami-0other"})
    assert copy.source_ami_id == "ami-0src"
    assert known.source_ami_id == "ami-0keep"  # SourceImageId wins


# Usage


def test_instance_usage_skips_terminated_and_other_images():
    reservations = [
        {
            "Instances": [
                {
                    "InstanceId": "i-01",
                    "ImageId": "ami-0aaa",
                    "State": {"Name": "running"},
                    "Tags": [{"Key": "Name", "Value": "api-1"}],
                },
                {"InstanceId": "i-02", "ImageId": "ami-0aaa", "State": {"Name": "terminated"}},
                {"InstanceId": "i-03", "ImageId": "ami-0zzz", "State": {"Name": "running"}},
                {"InstanceId": "i-04", "ImageId": "ami-0bbb", "State": {"Name": "stopped"}},
            ]
        }
    ]
    got = [
        (u.image_id, u.ref_type, u.ref_id, u.ref_name, u.ref_state)
        for u in n.instance_usage(reservations, DEV, "us-east-1", AMIS)
    ]
    assert got == [
        ("ami-0aaa", "instance", "i-01", "api-1", "running"),
        ("ami-0bbb", "instance", "i-04", "i-04", "stopped"),
    ]


TEMPLATES = [
    {
        "LaunchTemplateId": "lt-1",
        "LaunchTemplateName": "web",
        "DefaultVersionNumber": 2,
        "LatestVersionNumber": 4,
    }
]
VERSIONS = {
    ("lt-1", 2): {"LaunchTemplateData": {"ImageId": "ami-0aaa"}},
    ("lt-1", 3): {"LaunchTemplateData": {"ImageId": "ami-0ccc"}},
    ("lt-1", 4): {"LaunchTemplateData": {"ImageId": "resolve:ssm:/golden/web"}},
}


def test_template_default_and_latest_versions_count():
    usage, unresolved = n.template_usage(TEMPLATES, VERSIONS, DEV, "us-east-1", AMIS)
    assert [(u.image_id, u.ref_type, u.ref_id, u.ref_name) for u in usage] == [
        ("ami-0aaa", "launch_template", "lt-1", "web")
    ]
    assert [(x.ref_type, x.ref_id, x.value) for x in unresolved] == [
        ("launch_template", "lt-1", "resolve:ssm:/golden/web")
    ]
    assert n.template_versions_needed(TEMPLATES, []) == {("lt-1", 2), ("lt-1", 4)}


def group(name, desired=2, **spec):
    return {"AutoScalingGroupName": name, "DesiredCapacity": desired, **spec}


@pytest.mark.parametrize(
    ("version", "image"),
    [("$Latest", None), ("$Default", "ami-0aaa"), (None, "ami-0aaa"), ("3", "ami-0ccc")],
)
def test_asg_pinned_version_resolution(version, image):
    lt = {"LaunchTemplateId": "lt-1"}
    if version:
        lt["Version"] = version
    groups = [group("web-asg", LaunchTemplate=lt)]
    assert ("lt-1", 3 if version == "3" else 4 if version == "$Latest" else 2) in (
        n.template_versions_needed(TEMPLATES, groups)
    )
    usage, unresolved = n.asg_usage(groups, TEMPLATES, VERSIONS, {}, DEV, "us-east-1", AMIS)
    if image is None:  # $Latest is version 4, an SSM parameter
        assert usage == []
        assert [(x.ref_type, x.ref_id) for x in unresolved] == [("asg", "web-asg")]
    else:
        assert [(u.image_id, u.ref_type, u.ref_id, u.ref_state) for u in usage] == [
            (image, "asg", "web-asg", "active")
        ]


def test_asg_mixed_instances_policy_by_name_and_launch_config():
    mixed = group(
        "batch",
        desired=0,
        MixedInstancesPolicy={
            "LaunchTemplate": {
                "LaunchTemplateSpecification": {"LaunchTemplateName": "web", "Version": "3"}
            }
        },
    )
    legacy = group("legacy", LaunchConfigurationName="lc-old")
    configs = {"lc-old": {"LaunchConfigurationName": "lc-old", "ImageId": "ami-0bbb"}}
    usage, _ = n.asg_usage([mixed, legacy], TEMPLATES, VERSIONS, configs, DEV, "us-east-1", AMIS)
    assert [(u.image_id, u.ref_id, u.ref_state) for u in usage] == [
        ("ami-0ccc", "batch", "inactive"),
        ("ami-0bbb", "legacy", "active"),
    ]


def test_launch_config_usage():
    configs = [
        {"LaunchConfigurationName": "lc-old", "ImageId": "ami-0bbb"},
        {"LaunchConfigurationName": "lc-other", "ImageId": "ami-0zzz"},
    ]
    assert [
        (u.image_id, u.ref_type, u.ref_id) for u in n.launch_config_usage(configs, DEV, "x", AMIS)
    ] == [("ami-0bbb", "launch_config", "lc-old")]


# Errors


def client_error(code, operation="DescribeImages"):
    return ClientError({"Error": {"Code": code, "Message": f"{code} happened"}}, operation)


@pytest.mark.parametrize(
    ("exc", "kind", "detail"),
    [
        (client_error("ExpiredToken"), "expired", "ExpiredToken happened"),
        (client_error("RequestExpired"), "expired", "RequestExpired happened"),
        (client_error("UnauthorizedOperation"), "denied", "ec2:DescribeImages"),
        (client_error("AccessDenied", "DescribeDBSnapshots"), "denied", "rds:DescribeDBSnapshots"),
        (
            client_error("AccessDenied", "DescribeAutoScalingGroups"),
            "denied",
            "autoscaling:DescribeAutoScalingGroups",
        ),
        (client_error("AccessDenied", "AssumeRole"), "denied", "sts:AssumeRole"),
        (client_error("RequestLimitExceeded"), "throttled", "RequestLimitExceeded happened"),
        (client_error("Throttling"), "throttled", "Throttling happened"),
        (ReadOnlyViolation("stopped ec2:DeleteSnapshot"), "blocked", "stopped ec2:DeleteSnapshot"),
        (NoCredentialsError(), "expired", "Unable to locate credentials"),
        (ValueError("boom"), "other", "boom"),
    ],
)
def test_classify_errors(exc, kind, detail):
    assert n.classify(exc) == (kind, detail)


# Deployments

TAGS = DeploymentTags()


def tagged(name, desired=2, in_service=2, **tags):
    return group(
        name,
        desired,
        CreatedTime=WHEN,
        Tags=[{"Key": k.replace("_", "-"), "Value": v} for k, v in tags.items()],
        Instances=[{"LifecycleState": "InService"}] * in_service + [{"LifecycleState": "Pending"}],
        LaunchTemplate={"LaunchTemplateId": "lt-1", "Version": "3"},
    )


def test_only_asgs_with_the_state_tag_are_deployments():
    groups = [
        tagged(
            "dev-web-1.2.0-7",
            role="web",
            env="dev",
            version="1.2.0",
            deploy_state="deployed",
            deployment_id="7",
        ),
        group("eks-nodes", LaunchTemplate={"LaunchTemplateId": "lt-1"}),
    ]
    [d] = n.asg_deployments(groups, TEMPLATES, VERSIONS, {}, DEV, "us-east-1", TAGS, "dev-acct")
    assert (d.kind, d.app, d.env, d.version, d.state, d.deployment_id) == (
        "ec2",
        "web",
        "dev",
        "1.2.0",
        "deployed",
        "7",
    )
    assert (d.resource_id, d.name, d.created_at) == (
        "dev-web-1.2.0-7",
        "dev-web-1.2.0-7",
        "2026-01-31T12:00:00Z",
    )
    assert (d.desired, d.running) == (2, 2)  # the pending instance isn't running yet
    assert (d.launch_template, d.launch_template_version, d.ami_id) == ("web", "3", "ami-0ccc")


def test_asg_deployment_falls_back_to_the_group_name_and_the_account_name():
    groups = [tagged("old-batch", desired=0, in_service=0, deploy_state="undeployed")]
    [d] = n.asg_deployments(groups, TEMPLATES, VERSIONS, {}, DEV, "us-east-1", TAGS, "dev-acct")
    assert (d.app, d.env, d.version, d.state, d.desired) == (
        "old-batch",
        "dev-acct",
        "",
        "undeployed",
        0,
    )


def test_asg_deployment_image_from_launch_config_or_none_for_ssm():
    legacy = tagged("a", role="a", deploy_state="deployed")
    del legacy["LaunchTemplate"]
    legacy["LaunchConfigurationName"] = "lc-a"
    ssm = tagged("b", role="b", deploy_state="deployed")
    ssm["LaunchTemplate"] = {"LaunchTemplateName": "web", "Version": "$Latest"}
    found = n.asg_deployments(
        [legacy, ssm],
        TEMPLATES,
        VERSIONS,
        {"lc-a": {"ImageId": "ami-0bbb"}},
        DEV,
        "us-east-1",
        TAGS,
        "dev",
    )
    assert [(d.app, d.ami_id, d.launch_template, d.launch_template_version) for d in found] == [
        ("a", "ami-0bbb", "", ""),
        ("b", None, "web", "4"),
    ]


def test_renamed_tags_are_read_first_present_wins():
    tags = DeploymentTags(app=["service", "role"], state="stage")
    groups = [tagged("x", role="r", stage="deployed")]
    [d] = n.asg_deployments(groups, TEMPLATES, VERSIONS, {}, DEV, "us-east-1", tags, "dev")
    assert (d.app, d.state) == ("r", "deployed")


CLUSTER = "arn:aws:ecs:us-east-1:222222222222:cluster/apps"


def service(desired=3, running=3, rollout="COMPLETED", status="ACTIVE", tags=None, extra=()):
    return {
        "serviceArn": "arn:aws:ecs:us-east-1:222222222222:service/apps/orders-api",
        "serviceName": "orders-api",
        "clusterArn": CLUSTER,
        "status": status,
        "desiredCount": desired,
        "runningCount": running,
        "createdAt": WHEN,
        "taskDefinition": "arn:aws:ecs:us-east-1:222222222222:task-definition/orders-api:42",
        "deployments": [{"status": "PRIMARY", "rolloutState": rollout}, *extra],
        "tags": [{"key": k, "value": v} for k, v in (tags or {}).items()],
    }


def taskdef(image="registry.example/orders-api:2.7.0", **tags):
    return {
        "taskDefinition": {
            "family": "orders-api",
            "revision": 42,
            "containerDefinitions": [{"image": image}, {"image": "sidecar:1"}],
        },
        "tags": [{"key": k, "value": v} for k, v in tags.items()],
    }


def test_ecs_service_is_a_deployment_with_its_task_definition_version():
    d = n.ecs_deployment(
        service(), taskdef(app="orders", version="2.7.1"), DEV, "us-east-1", TAGS, "dev"
    )
    assert (d.kind, d.app, d.env, d.version, d.state) == (
        "ecs",
        "orders",
        "dev",
        "2.7.1",
        "deployed",
    )
    assert (d.cluster, d.name, d.task_definition, d.image) == (
        "apps",
        "orders-api",
        "orders-api:42",
        "registry.example/orders-api:2.7.0",
    )
    assert (d.desired, d.running, d.created_at, d.ami_id) == (3, 3, "2026-01-31T12:00:00Z", None)


def test_ecs_version_falls_back_to_the_image_tag_and_env_to_the_service_tag():
    d = n.ecs_deployment(service(tags={"env": "qas"}), taskdef(), DEV, "us-east-1", TAGS, "dev")
    assert (d.app, d.env, d.version) == ("orders-api", "qas", "2.7.0")
    digest = taskdef(image="registry.example/orders-api@sha256:abc")
    assert n.ecs_deployment(service(), digest, DEV, "us-east-1", TAGS, "dev").version == ""
    assert n.ecs_deployment(service(), None, DEV, "us-east-1", TAGS, "dev").version == ""
    port = taskdef(image="registry.example:5000/orders-api")
    assert n.ecs_deployment(service(), port, DEV, "us-east-1", TAGS, "dev").version == ""


@pytest.mark.parametrize(
    ("svc", "state"),
    [
        (service(desired=0, running=0), "deployed"),  # stopped, not an earlier version
        (service(status="DRAINING"), "undeploying"),
        (service(rollout="IN_PROGRESS"), "deploying"),
        (service(rollout="FAILED"), "failed"),
        (service(rollout=None, extra=[{"status": "ACTIVE"}]), "deploying"),
        (service(rollout=None), "deployed"),
    ],
)
def test_ecs_state(svc, state):
    assert n.ecs_deployment(svc, taskdef(), DEV, "us-east-1", TAGS, "dev").state == state


def instance(iid, state="running", **tags):
    return {
        "InstanceId": iid,
        "ImageId": "ami-0aaa",
        "State": {"Name": state},
        "LaunchTime": WHEN,
        "Tags": [{"Key": k.replace("_", "-"), "Value": v} for k, v in tags.items()],
    }


def test_instances_outside_any_asg_are_deployments():
    in_asg = instance("i-1", role="web")
    in_asg["Tags"].append({"Key": "aws:autoscaling:groupName", "Value": "dev-web-1.2.0-7"})
    lone = instance("i-2", role="bastion", version="1.0", Name="tools-bastion")
    lone["Tags"] += [
        {"Key": "aws:ec2launchtemplate:id", "Value": "lt-1"},
        {"Key": "aws:ec2launchtemplate:version", "Value": "3"},
    ]
    stopped = instance("i-3", state="stopped", Name="jump-box")
    untagged = instance("i-4")
    going = instance("i-5", state="shutting-down", Name="old")
    reservations = [{"Instances": [in_asg, lone]}, {"Instances": [stopped, untagged, going]}]
    found = n.standalone_instances(reservations, TEMPLATES, TOOLS, "us-east-1", TAGS, "admin")
    assert [(d.unit, d.app, d.name, d.version, d.desired, d.running) for d in found] == [
        ("instance", "bastion", "tools-bastion", "1.0", 1, 1),
        ("instance", "jump-box", "jump-box", "", 0, 0),
        ("instance", "i-4", "i-4", "", 1, 1),
    ]
    lone = found[0]
    assert (lone.kind, lone.env, lone.state, lone.resource_id) == (
        "ec2",
        "admin",
        "deployed",
        "i-2",
    )
    assert (lone.ami_id, lone.launch_template, lone.launch_template_version) == (
        "ami-0aaa",
        "web",
        "3",
    )
    assert lone.created_at == "2026-01-31T12:00:00Z"


def test_asg_and_ecs_deployments_name_their_unit():
    groups = [tagged("g", role="web", deploy_state="deployed")]
    [asg] = n.asg_deployments(groups, TEMPLATES, VERSIONS, {}, DEV, "us-east-1", TAGS, "dev")
    ecs = n.ecs_deployment(service(), taskdef(), DEV, "us-east-1", TAGS, "dev")
    assert (asg.unit, ecs.unit) == ("asg", "service")


def test_restore_accounts_reads_restore_attribute():
    attrs = [
        {"AttributeName": "restore", "AttributeValues": ["222222222222", "all"]},
        {"AttributeName": "other", "AttributeValues": ["x"]},
    ]
    assert n.restore_accounts(attrs) == ["222222222222", "all"]
    assert n.restore_accounts([]) == []
