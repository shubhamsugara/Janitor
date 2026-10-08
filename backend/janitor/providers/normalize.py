"""Raw AWS response shapes → Janitor records. Pure: no I/O, and the only place that knows AWS's
field names. Missing optional fields never raise.
"""

import re
from datetime import datetime

from botocore.exceptions import (
    ClientError,
    CredentialRetrievalError,
    NoCredentialsError,
    TokenRetrievalError,
)

from janitor.config import DeploymentTags
from janitor.models import (
    Database,
    Deployment,
    Resource,
    Share,
    Unresolved,
    Usage,
    format_ts,
    parse_ts,
)
from janitor.providers.guard import ReadOnlyViolation

BUILT = re.compile(r"Created by CreateImage\((i-[0-9a-f]+)\) for (ami-[0-9a-f]+)")
COPIED = re.compile(r"Copied for DestinationAmi (ami-[0-9a-f]+) from SourceAmi (ami-[0-9a-f]+)")
BACKUP_DESCRIPTION = "created by the AWS Backup service"
NO_VOLUME = "vol-ffffffff"  # what AWS reports when a snapshot has no source volume
SSM = "resolve:ssm:"


def _ts(value: datetime | str) -> str:
    return format_ts(parse_ts(value) if isinstance(value, str) else value)


def _tags(raw: dict, key: str = "Tags") -> dict[str, str]:
    return {t["Key"]: t.get("Value", "") for t in raw.get(key) or []}


def _managed(tags: dict[str, str], description: str = "") -> str | None:
    if "aws:backup:source-resource" in tags or BACKUP_DESCRIPTION in description:
        return "aws_backup"
    if "aws:dlm:lifecycle-policy-id" in tags:
        return "dlm"
    return None


# Resources


def image(raw: dict, account: str, region: str) -> Resource:
    tags = _tags(raw)
    disks = [m["Ebs"] for m in raw.get("BlockDeviceMappings") or [] if "Ebs" in m]
    sizes = [d["VolumeSize"] for d in disks if d.get("VolumeSize") is not None]
    return Resource(
        id=raw["ImageId"],
        type="ami",
        account=account,
        region=region,
        name=raw.get("Name") or raw["ImageId"],
        created_at=_ts(raw["CreationDate"]),
        size_gb=sum(sizes) if sizes else None,
        state=raw.get("State", ""),
        tags=tags,
        snapshot_ids=[d["SnapshotId"] for d in disks if d.get("SnapshotId")],
        source_ami_id=raw.get("SourceImageId"),
        managed_by=_managed(tags, raw.get("Description") or ""),
    )


def copy_of(raw_snapshot: dict) -> tuple[str, str] | None:
    """(destination AMI, source AMI) from a copied snapshot's description, else None."""
    match = COPIED.search(raw_snapshot.get("Description") or "")
    return (match.group(1), match.group(2)) if match else None


def snapshot(raw: dict, account: str, region: str) -> Resource:
    tags = _tags(raw)
    description = raw.get("Description") or ""
    built, copied = BUILT.search(description), COPIED.search(description)
    linked = built.group(2) if built else copied.group(1) if copied else None
    volume_id = raw.get("VolumeId")
    return Resource(
        id=raw["SnapshotId"],
        type="snapshot",
        account=account,
        region=region,
        name=tags.get("Name") or raw["SnapshotId"],
        created_at=_ts(raw["StartTime"]),
        size_gb=raw.get("VolumeSize"),
        state=raw.get("State", ""),
        tags=tags,
        linked_ami_id=linked,
        source_volume_id=volume_id if volume_id and volume_id != NO_VOLUME else None,
        managed_by=_managed(tags, description),
        storage_tier=raw.get("StorageTier") or "standard",
    )


def volume(raw: dict, account: str, region: str) -> Resource:
    tags = _tags(raw)
    attachments = raw.get("Attachments") or []
    return Resource(
        id=raw["VolumeId"],
        type="volume",
        account=account,
        region=region,
        name=tags.get("Name") or raw["VolumeId"],
        created_at=_ts(raw["CreateTime"]),
        size_gb=raw.get("Size"),
        state=raw.get("State", ""),
        tags=tags,
        attached_instance=attachments[0].get("InstanceId") if attachments else None,
        volume_type=raw.get("VolumeType"),
        iops=raw.get("Iops"),
        throughput=raw.get("Throughput"),
        encrypted=raw.get("Encrypted"),
    )


RDS_MANAGED = {"automated": "rds_automated", "awsbackup": "aws_backup"}


def db_snapshot(raw: dict, account: str, region: str, cluster: bool, now: datetime) -> Resource:
    prefix = "DBCluster" if cluster else "DB"
    created = raw.get("SnapshotCreateTime") or raw.get("OriginalSnapshotCreateTime") or now
    tags = _tags(raw, "TagList")
    return Resource(
        id=raw[f"{prefix}SnapshotArn"],
        type="rds_snapshot",
        account=account,
        region=region,
        name=raw[f"{prefix}SnapshotIdentifier"],
        created_at=_ts(created),
        size_gb=raw.get("AllocatedStorage"),
        state=raw.get("Status", ""),
        tags=tags,
        source_db_id=raw.get("DBClusterIdentifier" if cluster else "DBInstanceIdentifier"),
        db_kind="cluster" if cluster else "instance",
        managed_by=RDS_MANAGED.get(raw.get("SnapshotType", "")) or _managed(tags),
    )


def database(raw: dict, account: str, region: str, cluster: bool) -> Database:
    key = "DBClusterIdentifier" if cluster else "DBInstanceIdentifier"
    return Database(raw[key], account, region, "cluster" if cluster else "instance")


def shares(image_id: str, launch_permissions: list[dict]) -> list[Share]:
    kinds = (
        ("UserId", "account"),
        ("Group", "group"),
        ("OrganizationArn", "org"),
        ("OrganizationalUnitArn", "ou"),
    )
    found = []
    for perm in launch_permissions:
        for key, kind in kinds:
            if perm.get(key):
                found.append(Share(image_id, kind, perm[key]))
    return found


def fill_copy_sources(amis: list[Resource], copies: dict[str, str]) -> None:
    """Give copied AMIs without SourceImageId the source named by their snapshots' descriptions."""
    for ami in amis:
        if not ami.source_ami_id and ami.id in copies:
            ami.source_ami_id = copies[ami.id]


# Usage


def instance_usage(
    reservations: list[dict], account: str, region: str, ami_ids: set[str]
) -> list[Usage]:
    found = []
    for reservation in reservations:
        for inst in reservation.get("Instances") or []:
            state = (inst.get("State") or {}).get("Name", "")
            if state == "terminated" or inst.get("ImageId") not in ami_ids:
                continue
            name = _tags(inst).get("Name") or inst["InstanceId"]
            found.append(
                Usage(inst["ImageId"], account, region, "instance", inst["InstanceId"], name, state)
            )
    return found


def _by_id_or_name(templates: list[dict], spec: dict) -> dict | None:
    for t in templates:
        if spec.get("LaunchTemplateId") == t["LaunchTemplateId"] or (
            spec.get("LaunchTemplateName") == t["LaunchTemplateName"]
        ):
            return t
    return None


def _pinned(template: dict, version: str | None) -> int | None:
    """The version number an ASG actually launches from."""
    if version in (None, "", "$Default"):
        return template.get("DefaultVersionNumber")
    if version == "$Latest":
        return template.get("LatestVersionNumber")
    try:
        return int(version)
    except ValueError:
        return None


def _asg_templates(group: dict) -> list[dict]:
    specs = []
    if group.get("LaunchTemplate"):
        specs.append(group["LaunchTemplate"])
    mixed = (group.get("MixedInstancesPolicy") or {}).get("LaunchTemplate") or {}
    if mixed.get("LaunchTemplateSpecification"):
        specs.append(mixed["LaunchTemplateSpecification"])
    return specs


def template_versions_needed(templates: list[dict], groups: list[dict]) -> set[tuple[str, int]]:
    """Every template's default and latest versions, plus each version an ASG pins."""
    needed = set()
    for t in templates:
        for key in ("DefaultVersionNumber", "LatestVersionNumber"):
            if t.get(key) is not None:
                needed.add((t["LaunchTemplateId"], t[key]))
    for group in groups:
        for spec in _asg_templates(group):
            template = _by_id_or_name(templates, spec)
            number = template and _pinned(template, spec.get("Version"))
            if number is not None:
                needed.add((template["LaunchTemplateId"], number))
    return needed


def _image_ref(
    image_id: str | None,
    ami_ids: set[str],
    unresolved: list[Unresolved],
    where: tuple[str, str, str, str],
) -> str | None:
    """Return the image ID if it's one of ours; record SSM references as unresolved."""
    if not image_id:
        return None
    if image_id.startswith(SSM):
        unresolved.append(Unresolved(*where, image_id))
        return None
    return image_id if image_id in ami_ids else None


def _version_image(versions: dict, template_id: str, number: int | None) -> str | None:
    version = versions.get((template_id, number)) or {}
    return (version.get("LaunchTemplateData") or {}).get("ImageId")


def template_usage(
    templates: list[dict], versions: dict, account: str, region: str, ami_ids: set[str]
) -> tuple[list[Usage], list[Unresolved]]:
    """A template's default or latest version naming an AMI counts as use (fleets, node groups)."""
    usage, unresolved = [], []
    for t in templates:
        tid = t["LaunchTemplateId"]
        seen = set()
        for key in ("DefaultVersionNumber", "LatestVersionNumber"):
            image_id = _version_image(versions, tid, t.get(key))
            if image_id in seen:
                continue
            seen.add(image_id)
            where = (account, region, "launch_template", tid)
            if ref := _image_ref(image_id, ami_ids, unresolved, where):
                usage.append(
                    Usage(ref, account, region, "launch_template", tid, t["LaunchTemplateName"])
                )
    return usage, unresolved


def asg_usage(
    groups: list[dict],
    templates: list[dict],
    versions: dict,
    configs: dict[str, dict],
    account: str,
    region: str,
    ami_ids: set[str],
) -> tuple[list[Usage], list[Unresolved]]:
    usage, unresolved = [], []
    for group in groups:
        name = group["AutoScalingGroupName"]
        state = "active" if group.get("DesiredCapacity", 0) > 0 else "inactive"
        images = []
        for spec in _asg_templates(group):
            template = _by_id_or_name(templates, spec)
            if template:
                number = _pinned(template, spec.get("Version"))
                images.append(_version_image(versions, template["LaunchTemplateId"], number))
        if group.get("LaunchConfigurationName"):
            images.append((configs.get(group["LaunchConfigurationName"]) or {}).get("ImageId"))
        for image_id in dict.fromkeys(images):
            if ref := _image_ref(image_id, ami_ids, unresolved, (account, region, "asg", name)):
                usage.append(Usage(ref, account, region, "asg", name, name, state))
    return usage, unresolved


def launch_config_usage(
    configs: list[dict], account: str, region: str, ami_ids: set[str]
) -> list[Usage]:
    return [
        Usage(c["ImageId"], account, region, "launch_config", c["LaunchConfigurationName"])
        for c in configs
        if c.get("ImageId") in ami_ids
    ]


# Deployments


def _first(tags: dict[str, str], keys: list[str]) -> str:
    return next((tags[k] for k in keys if tags.get(k)), "")


def asg_deployments(
    groups: list[dict],
    templates: list[dict],
    versions: dict,
    configs: dict[str, dict],
    account: str,
    region: str,
    keys: DeploymentTags,
    fallback_env: str,
) -> list[Deployment]:
    """ASGs a deploy tool tagged with a state; other groups aren't deployments."""
    found = []
    for group in groups:
        tags = _tags(group)
        if keys.state not in tags:
            continue
        name = group["AutoScalingGroupName"]
        template_name, number, image_id = "", None, None
        if specs := _asg_templates(group):
            template = _by_id_or_name(templates, specs[0])
            if template:
                template_name = template["LaunchTemplateName"]
                number = _pinned(template, specs[0].get("Version"))
                image_id = _version_image(versions, template["LaunchTemplateId"], number)
        elif group.get("LaunchConfigurationName"):
            image_id = (configs.get(group["LaunchConfigurationName"]) or {}).get("ImageId")
        found.append(
            Deployment(
                kind="ec2",
                account=account,
                region=region,
                env=_first(tags, keys.env) or fallback_env,
                app=_first(tags, keys.app) or name,
                version=_first(tags, keys.version),
                state=tags[keys.state],
                resource_id=name,
                name=name,
                created_at=_ts(group["CreatedTime"]) if group.get("CreatedTime") else "",
                desired=group.get("DesiredCapacity", 0),
                running=sum(
                    i.get("LifecycleState") == "InService" for i in group.get("Instances") or []
                ),
                deployment_id=tags.get(keys.deployment_id, ""),
                launch_template=template_name,
                launch_template_version="" if number is None else str(number),
                ami_id=None if not image_id or image_id.startswith(SSM) else image_id,
                unit="asg",
            )
        )
    return found


def standalone_instances(
    reservations: list[dict],
    templates: list[dict],
    account: str,
    region: str,
    keys: DeploymentTags,
    fallback_env: str,
) -> list[Deployment]:
    """Instances in no ASG: hand-made servers, older deploy strategies, bastions. One row each."""
    names = {t["LaunchTemplateId"]: t["LaunchTemplateName"] for t in templates}
    found = []
    for reservation in reservations:
        for raw in reservation.get("Instances") or []:
            tags = _tags(raw)
            state = (raw.get("State") or {}).get("Name", "")
            if "aws:autoscaling:groupName" in tags or state in ("shutting-down", "terminated"):
                continue
            iid = raw["InstanceId"]
            name = tags.get("Name") or iid
            template_id = tags.get("aws:ec2launchtemplate:id", "")
            found.append(
                Deployment(
                    kind="ec2",
                    account=account,
                    region=region,
                    env=_first(tags, keys.env) or fallback_env,
                    app=_first(tags, keys.app) or name,
                    version=_first(tags, keys.version),
                    state="deployed",  # it exists; whether it runs is desired/running
                    resource_id=iid,
                    name=name,
                    created_at=_ts(raw["LaunchTime"]) if raw.get("LaunchTime") else "",
                    desired=int(state in ("pending", "running")),
                    running=int(state == "running"),
                    deployment_id=tags.get(keys.deployment_id, ""),
                    launch_template=names.get(template_id, template_id),
                    launch_template_version=tags.get("aws:ec2launchtemplate:version", ""),
                    ami_id=raw.get("ImageId"),
                    unit="instance",
                )
            )
    return found


def _ecs_tags(raw: dict | None) -> dict[str, str]:
    return {t["key"]: t.get("value", "") for t in (raw or {}).get("tags") or []}


def _ecs_state(service: dict) -> str:
    """ECS has no deploy-state tag. A service scaled to 0 is still deployed (its run status says
    Stopped); the UI makes it an earlier version only beside a running service for the same app."""
    if service.get("status") == "DRAINING":
        return "undeploying"
    deployments = service.get("deployments") or []
    primary = next((d for d in deployments if d.get("status") == "PRIMARY"), {})
    rollout = primary.get("rolloutState")
    if rollout == "FAILED":
        return "failed"
    if rollout == "IN_PROGRESS" or (rollout is None and len(deployments) > 1):
        return "deploying"
    return "deployed"


def ecs_deployment(
    service: dict,
    taskdef: dict | None,
    account: str,
    region: str,
    keys: DeploymentTags,
    fallback_env: str,
) -> Deployment:
    """An ECS service and the task definition it runs (DescribeTaskDefinition with tags)."""
    definition = (taskdef or {}).get("taskDefinition") or {}
    def_tags, svc_tags = _ecs_tags(taskdef), _ecs_tags(service)
    containers = definition.get("containerDefinitions") or []
    image = containers[0].get("image", "") if containers else ""
    tag = image.rpartition(":")[2] if ":" in image and "@" not in image else ""
    image_tag = "" if "/" in tag else tag  # registry.example:5000/app has a port, not a tag
    family = definition.get("family") or service["taskDefinition"].rpartition("/")[2]
    revision = definition.get("revision")
    return Deployment(
        kind="ecs",
        account=account,
        region=region,
        env=_first(svc_tags, keys.env) or _first(def_tags, keys.env) or fallback_env,
        app=_first(def_tags, keys.app) or _first(svc_tags, keys.app) or service["serviceName"],
        version=_first(def_tags, keys.version) or image_tag,
        state=_ecs_state(service),
        resource_id=service["serviceArn"],
        name=service["serviceName"],
        created_at=_ts(service["createdAt"]) if service.get("createdAt") else "",
        desired=service.get("desiredCount", 0),
        running=service.get("runningCount", 0),
        cluster=service.get("clusterArn", "").rpartition("/")[2],
        task_definition=f"{family.partition(':')[0]}:{revision}" if revision else family,
        image=image,
        unit="service",
    )


# Errors

EXPIRED = {
    "ExpiredToken",
    "ExpiredTokenException",
    "RequestExpired",
    "InvalidClientTokenId",
}
DENIED = {"AccessDenied", "AccessDeniedException", "UnauthorizedOperation", "AuthFailure"}
THROTTLED = {
    "Throttling",
    "ThrottlingException",
    "RequestLimitExceeded",
    "TooManyRequestsException",
}


def _service(operation: str) -> str:
    if operation.startswith("DescribeDB"):
        return "rds"
    if operation in ("DescribeAutoScalingGroups", "DescribeLaunchConfigurations"):
        return "autoscaling"
    if operation == "AssumeRole":
        return "sts"
    return "ec2"


def classify(exc: BaseException) -> tuple[str, str]:
    """(error_kind, detail). For "denied", the detail is the service:Operation refused."""
    if isinstance(exc, ReadOnlyViolation):
        return "blocked", str(exc)
    if isinstance(exc, NoCredentialsError | TokenRetrievalError | CredentialRetrievalError):
        return "expired", str(exc)
    if isinstance(exc, ClientError):
        error = exc.response.get("Error", {})
        code, message = error.get("Code", ""), error.get("Message") or str(exc)
        if code in EXPIRED:
            return "expired", message
        if code in DENIED:
            return "denied", f"{_service(exc.operation_name)}:{exc.operation_name}"
        if code in THROTTLED:
            return "throttled", message
        return "other", message
    return "other", str(exc)
