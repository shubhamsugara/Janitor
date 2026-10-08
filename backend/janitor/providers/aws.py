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
from janitor.providers.base import OnSegment, phase_one, usage_pairs

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
        sessions = self._assume_all(list(config.accounts))
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
                seg.error_kind, seg.error = normalize.classify(exc)
            seg.duration_ms = int((time.monotonic() - start) * 1000)
            with lock:
                segments.append(seg)
            if on_segment:
                on_segment(seg)

        listers = {
            "ami": self._amis,
            "snapshot": self._snapshots,
            "volume": self._volumes,
            "rds_snapshot": self._rds_snapshots,
            "database": self._databases,
        }
        with ThreadPoolExecutor(config.scan.concurrency) as pool:
            for account, region, kind in phase_one(config):
                pool.submit(run, account, region, kind, listers[kind])

        amis = [r for r in rows.resources if r.type == "ami"]
        normalize.fill_copy_sources(amis, rows.copies)
        ami_ids = {a.id for a in amis}

        def usage(sess: boto3.Session, account: str, region: str) -> _Rows:
            return self._usage(sess, account, region, ami_ids)

        with ThreadPoolExecutor(config.scan.concurrency) as pool:
            for account, region in usage_pairs(config, amis, rows.shares):
                pool.submit(run, account, region, "usage", usage)

        return Inventory(
            resources=rows.resources,
            shares=rows.shares,
            usage=rows.usage,
            databases=rows.databases,
            segments=segments,
            unresolved=rows.unresolved,
        )

    def recheck(self, items: list[dict]) -> dict[str, str]:
        return {}

    # Sessions and clients

    def _assume_all(self, accounts: list[str]) -> dict[str, boto3.Session | Exception]:
        def one(account: str) -> boto3.Session | Exception:
            try:
                return session.assume(self._config, account)
            except Exception as exc:  # every segment of this account reports it
                return exc

        with ThreadPoolExecutor(min(len(accounts), self._config.scan.concurrency) or 1) as pool:
            return dict(zip(accounts, pool.map(one, accounts), strict=True))

    def _client(self, sess: boto3.Session, service: str, region: str):
        with self._client_lock:
            return sess.client(service, region_name=region, config=session.CLIENT_CONFIG)

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
            for raw in self._pages(ec2, "describe_images", "Images", Owners=["self"])
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
