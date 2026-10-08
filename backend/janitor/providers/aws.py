"""Read real AWS accounts. Every call is a Describe, every session carries the Describe-only
session policy (session.py), and the guard (guard.py) stops anything else before it is sent.

A scan is split into segments, one per (account, region, kind). Segments run in a thread pool
and fail independently; a failed segment contributes no rows, and the linker turns what depends
on it into "unknown".
"""

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime

import boto3

from janitor.config import Config
from janitor.models import Database, Inventory, Resource, Segment, Share, Unresolved, Usage
from janitor.providers import normalize, session
from janitor.providers.base import OnSegment, first_phase, member_accounts, second_phase

OPERATIONS = frozenset(
    {
        "DescribeImages",
        "DescribeImageAttribute",
        "DescribeSnapshots",
        "DescribeVolumes",
        "DescribeDBSnapshots",
        "DescribeDBClusterSnapshots",
        "DescribeDBInstances",
        "DescribeDBClusters",
        "DescribeInstances",
        "DescribeLaunchTemplates",
        "DescribeLaunchTemplateVersions",
        "DescribeAutoScalingGroups",
        "DescribeLaunchConfigurations",
    }
)
MAX_FILTER_VALUES = 200
LIVE_STATES = ["pending", "running", "shutting-down", "stopping", "stopped"]


@dataclass
class _Rows:
    resources: list[Resource] = field(default_factory=list)
    shares: list[Share] = field(default_factory=list)
    usage: list[Usage] = field(default_factory=list)
    databases: list[Database] = field(default_factory=list)
    unresolved: list[Unresolved] = field(default_factory=list)
    copies: dict[str, str] = field(default_factory=dict)  # destination AMI -> source AMI

    def count(self) -> int:
        return len(self.resources) + len(self.databases) + len(self.usage)

    def add(self, other: "_Rows") -> None:
        self.resources += other.resources
        self.shares += other.shares
        self.usage += other.usage
        self.databases += other.databases
        self.unresolved += other.unresolved
        self.copies |= other.copies


class AwsProvider:
    name = "aws"

    def __init__(
        self,
        config: Config,
        clock: Callable[[], datetime] | None = None,
        page_size: int | None = None,
    ):
        self._config = config
        self._clock = clock or (lambda: datetime.now(UTC))
        self._page_size = page_size
        self._client_lock = threading.Lock()  # boto3 sessions aren't thread-safe; clients are

    # Public, read-only

    def list_inventory(self, on_segment: OnSegment | None = None) -> Inventory:
        config = self._config
        sessions = self._sessions([])  # the admin first; members once their IDs are known
        rows, segments = _Rows(), []
        lock = threading.Lock()

        def run(account: str, region: str, kind: str, work: Callable[..., _Rows]) -> None:
            start = time.monotonic()
            seg = Segment(account, region, kind, ok=True)
            try:
                found = sessions[account]
                if isinstance(found, Exception):
                    raise found
                result = work(found, account, region)
                seg.items = result.count()
                with lock:
                    rows.add(result)
            except Exception as exc:
                seg.ok = False
                seg.error_kind, seg.error = "other", str(exc)
                try:
                    seg.error_kind, seg.error = normalize.classify(exc)
                except Exception:
                    pass  # keep "other": the check must still report as failed
            finally:
                # Always report: a check missing from the report would read as ok (fail-open).
                seg.duration_ms = int((time.monotonic() - start) * 1000)
                with lock:
                    segments.append(seg)
                if on_segment:
                    on_segment(seg)

        with ThreadPoolExecutor(config.scan.concurrency) as pool:
            for account, region, kind in first_phase(config):
                pool.submit(run, account, region, kind, self._listers[kind])

        amis = [r for r in rows.resources if r.type == "ami"]
        normalize.fill_copy_sources(amis, rows.copies)
        ami_ids = {a.id for a in amis}
        members = member_accounts(config, rows.shares)
        sessions = self._sessions(members, admin=sessions[config.admin.account])

        def usage(sess: boto3.Session, account: str, region: str) -> _Rows:
            return self._usage(sess, account, region, ami_ids)

        with ThreadPoolExecutor(config.scan.concurrency) as pool:
            for account, region, kind in second_phase(config, members, amis, rows.shares):
                work = usage if kind == "usage" else self._listers[kind]
                pool.submit(run, account, region, kind, work)

        return Inventory(
            resources=rows.resources,
            shares=rows.shares,
            usage=rows.usage,
            databases=rows.databases,
            segments=segments,
            unresolved=rows.unresolved,
        )

    def recheck(self, items: list[dict]) -> dict[str, str]:
        """Re-read would-delete items just before a simulated delete; {id: reason} to skip.

        Existence, volume attachment, AMI launch permissions, and instances now running an AMI.
        Launch templates and ASGs are not re-read (that is a full usage scan); the scan covered
        them. Anything Janitor can't re-check is skipped with the reason.
        """
        config = self._config
        groups: dict[tuple[str, str], list[dict]] = {}
        for item in items:
            groups.setdefault((item["account"], item["region"]), []).append(item)
        users = {
            (account, i["region"])
            for i in items
            if i["type"] == "ami"
            for account in self._permitted(i)
        }
        accounts = sorted({a for a, _ in groups} | {a for a, _ in users})
        sessions = self._sessions([a for a in accounts if a != config.admin.account])
        reasons: dict[str, str] = {}

        def unreachable(group: list[dict], exc: Exception) -> None:
            detail = normalize.classify(exc)[1].strip().rstrip(".")
            for i in group:
                reasons.setdefault(i["id"], f"Janitor couldn't re-check it live: {detail}.")

        for (account, region), group in groups.items():
            try:
                found = sessions[account]
                if isinstance(found, Exception):
                    raise found
                reasons |= self._recheck_group(found, region, group)
            except Exception as exc:
                unreachable(group, exc)

        amis = [i for i in items if i["type"] == "ami" and i["id"] not in reasons]
        for account, region in sorted(users):
            here = [i for i in amis if i["region"] == region and account in self._permitted(i)]
            if not here:
                continue
            try:
                found = sessions[account]
                if isinstance(found, Exception):
                    raise found
                ec2 = self._client(found, "ec2", region)
                running = self._by_ids(
                    ec2,
                    "describe_instances",
                    "Reservations",
                    "image-id",
                    [i["id"] for i in here],
                    Filters=[{"Name": "instance-state-name", "Values": LIVE_STATES}],
                )
                for use in normalize.instance_usage(
                    list(running), account, region, {i["id"] for i in here}
                ):
                    reasons.setdefault(
                        use.image_id,
                        f"Instance {use.ref_id} in {config.account_name(account)} now uses it.",
                    )
            except Exception as exc:
                unreachable([i for i in here if i["id"] not in reasons], exc)
        return reasons

    def _permitted(self, ami: dict) -> set[str]:
        """The admin plus every account the scan saw in the AMI's launch permissions."""
        shares = ami.get("shares") or []
        return {ami["account"]} | {
            s["principal"] for s in shares if s["principal_type"] == "account"
        }

    def _recheck_group(self, sess: boto3.Session, region: str, group: list[dict]) -> dict[str, str]:
        gone = "It no longer exists."
        reasons: dict[str, str] = {}
        ids = {t: [i["id"] for i in group if i["type"] == t] for t in ("ami", "snapshot", "volume")}
        ec2 = self._client(sess, "ec2", region)
        if ids["volume"]:
            live = {
                v["VolumeId"]: v
                for v in self._by_ids(
                    ec2, "describe_volumes", "Volumes", "volume-id", ids["volume"]
                )
            }
            for vid in ids["volume"]:
                if vid not in live:
                    reasons[vid] = gone
                elif attached := normalize.volume(live[vid], "", region).attached_instance:
                    reasons[vid] = f"It is now attached to {attached}."
        if ids["snapshot"]:
            live = {
                s["SnapshotId"]
                for s in self._by_ids(
                    ec2,
                    "describe_snapshots",
                    "Snapshots",
                    "snapshot-id",
                    ids["snapshot"],
                    OwnerIds=["self"],
                )
            }
            reasons |= {sid: gone for sid in ids["snapshot"] if sid not in live}
        if ids["ami"]:
            live = {
                img["ImageId"]
                for img in self._by_ids(
                    ec2,
                    "describe_images",
                    "Images",
                    "image-id",
                    ids["ami"],
                    Owners=["self"],
                    IncludeDisabled=True,  # a disabled AMI still owns its snapshots
                )
            }
            for ami in (i for i in group if i["type"] == "ami"):
                if ami["id"] not in live:
                    reasons[ami["id"]] = gone
                    continue
                perms = ec2.describe_image_attribute(
                    ImageId=ami["id"], Attribute="launchPermission"
                )
                now = {
                    (s.principal_type, s.principal)
                    for s in normalize.shares(ami["id"], perms.get("LaunchPermissions") or [])
                }
                then = {(s["principal_type"], s["principal"]) for s in ami.get("shares") or []}
                if now - then:
                    reasons[ami["id"]] = "Its launch permissions changed since the scan."
        rds_items = [i for i in group if i["type"] == "rds_snapshot"]
        if rds_items:
            rds = self._client(sess, "rds", region)
            for snap in rds_items:
                cluster = ":cluster-snapshot:" in snap["id"]
                try:
                    if cluster:
                        rds.describe_db_cluster_snapshots(DBClusterSnapshotIdentifier=snap["name"])
                    else:
                        rds.describe_db_snapshots(DBSnapshotIdentifier=snap["name"])
                except rds.exceptions.ClientError as exc:
                    if "NotFound" not in exc.response.get("Error", {}).get("Code", ""):
                        raise
                    reasons[snap["id"]] = gone
        return reasons

    # Sessions and clients

    @property
    def _listers(self) -> dict[str, Callable[..., _Rows]]:
        return {
            "ami": self._amis,
            "snapshot": self._snapshots,
            "volume": self._volumes,
            "rds_snapshot": self._rds_snapshots,
            "database": self._databases,
        }

    def _sessions(
        self, members: list[str], admin: boto3.Session | Exception | None = None
    ) -> dict[str, boto3.Session | Exception]:
        """The admin session (assumed unless given) and one session per member account.

        Every hop starts from the source login, so accounts fail independently. A failure is kept
        in place of the session, so every check of that account reports it.
        """
        config = self._config
        try:
            with self._client_lock:  # one client, made once; every hop below shares it
                sts = session.source(config).client("sts", config=session.CLIENT_CONFIG)
        except Exception as exc:  # no source credentials: nothing can be reached
            sts = exc

        def hop(assume: Callable[[], boto3.Session]) -> boto3.Session | Exception:
            if isinstance(sts, Exception):
                return sts
            try:
                return assume()
            except Exception as exc:
                return exc

        if admin is None:
            admin = hop(lambda: session.assume_admin(config, sts))
        workers = min(len(members), config.scan.concurrency) or 1
        with ThreadPoolExecutor(workers) as pool:
            found = dict(
                zip(
                    members,
                    pool.map(lambda a: hop(lambda: session.assume_member(config, a, sts)), members),
                    strict=True,
                )
            )
        return {config.admin.account: admin, **found}

    def _client(self, sess: boto3.Session, service: str, region: str):
        with self._client_lock:
            return sess.client(service, region_name=region, config=session.CLIENT_CONFIG)

    def _by_ids(self, client, operation: str, key: str, name: str, ids: list[str], **params):
        """Like _pages, filtered to `ids`; EC2 takes at most 200 values per filter."""
        extra = params.pop("Filters", [])
        for start in range(0, len(ids), MAX_FILTER_VALUES):
            chunk = {"Name": name, "Values": ids[start : start + MAX_FILTER_VALUES]}
            yield from self._pages(client, operation, key, Filters=[chunk, *extra], **params)

    def _pages(self, client, operation: str, key: str, **params):
        config = {"PageSize": self._page_size} if self._page_size else {}
        for page in client.get_paginator(operation).paginate(**params, PaginationConfig=config):
            yield from page.get(key) or []

    # Listers: one per segment kind

    def _amis(self, sess: boto3.Session, account: str, region: str) -> _Rows:
        ec2 = self._client(sess, "ec2", region)
        rows = _Rows()
        rows.resources = [
            normalize.image(raw, account, region)
            for raw in self._pages(
                ec2, "describe_images", "Images", Owners=["self"], IncludeDisabled=True
            )
        ]

        def permissions(ami: Resource) -> list[Share]:
            # Any failure here fails the whole segment: an AMI with unknown shares can't be judged.
            perms = ec2.describe_image_attribute(ImageId=ami.id, Attribute="launchPermission")
            return normalize.shares(ami.id, perms.get("LaunchPermissions") or [])

        with ThreadPoolExecutor(self._config.scan.concurrency) as pool:
            for found in pool.map(permissions, rows.resources):
                rows.shares += found
        return rows

    def _snapshots(self, sess: boto3.Session, account: str, region: str) -> _Rows:
        ec2 = self._client(sess, "ec2", region)
        rows = _Rows()
        for raw in self._pages(ec2, "describe_snapshots", "Snapshots", OwnerIds=["self"]):
            if raw.get("OwnerId", account) != account:
                continue
            rows.resources.append(normalize.snapshot(raw, account, region))
            if copy := normalize.copy_of(raw):
                rows.copies[copy[0]] = copy[1]
        return rows

    def _volumes(self, sess: boto3.Session, account: str, region: str) -> _Rows:
        ec2 = self._client(sess, "ec2", region)
        return _Rows(
            resources=[
                normalize.volume(raw, account, region)
                for raw in self._pages(ec2, "describe_volumes", "Volumes")
            ]
        )

    def _rds_snapshots(self, sess: boto3.Session, account: str, region: str) -> _Rows:
        rds = self._client(sess, "rds", region)
        now = self._clock()
        found = [
            normalize.db_snapshot(raw, account, region, cluster=False, now=now)
            for raw in self._pages(rds, "describe_db_snapshots", "DBSnapshots")
        ] + [
            normalize.db_snapshot(raw, account, region, cluster=True, now=now)
            for raw in self._pages(rds, "describe_db_cluster_snapshots", "DBClusterSnapshots")
        ]
        return _Rows(resources=found)

    def _databases(self, sess: boto3.Session, account: str, region: str) -> _Rows:
        rds = self._client(sess, "rds", region)
        found = [
            normalize.database(raw, account, region, cluster=False)
            for raw in self._pages(rds, "describe_db_instances", "DBInstances")
        ] + [
            normalize.database(raw, account, region, cluster=True)
            for raw in self._pages(rds, "describe_db_clusters", "DBClusters")
        ]
        return _Rows(databases=found)

    def _usage(self, sess: boto3.Session, account: str, region: str, ami_ids: set[str]) -> _Rows:
        ec2 = self._client(sess, "ec2", region)
        autoscaling = self._client(sess, "autoscaling", region)
        rows = _Rows()
        reservations = self._pages(
            ec2,
            "describe_instances",
            "Reservations",
            Filters=[{"Name": "instance-state-name", "Values": LIVE_STATES}],
        )
        rows.usage += normalize.instance_usage(list(reservations), account, region, ami_ids)

        templates = list(self._pages(ec2, "describe_launch_templates", "LaunchTemplates"))
        groups = list(self._pages(autoscaling, "describe_auto_scaling_groups", "AutoScalingGroups"))
        configs = list(
            self._pages(autoscaling, "describe_launch_configurations", "LaunchConfigurations")
        )
        versions = {}
        needed: dict[str, list[str]] = {}
        for template_id, number in normalize.template_versions_needed(templates, groups):
            needed.setdefault(template_id, []).append(str(number))
        for template_id, numbers in needed.items():
            for raw in self._pages(
                ec2,
                "describe_launch_template_versions",
                "LaunchTemplateVersions",
                LaunchTemplateId=template_id,
                Versions=numbers,
            ):
                versions[(template_id, raw["VersionNumber"])] = raw

        found, unresolved = normalize.template_usage(templates, versions, account, region, ami_ids)
        rows.usage += found
        rows.unresolved += unresolved
        by_name = {c["LaunchConfigurationName"]: c for c in configs}
        found, unresolved = normalize.asg_usage(
            groups, templates, versions, by_name, account, region, ami_ids
        )
        rows.usage += found
        rows.unresolved += unresolved
        rows.usage += normalize.launch_config_usage(configs, account, region, ami_ids)
        return rows
