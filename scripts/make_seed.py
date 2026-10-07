#!/usr/bin/env python3
"""Generate fixtures/seed.json, the mock dataset. Fake IDs only; fixed RNG seed.

Every status per type appears, plus the demo moments: an in-use AMI, a prod-tagged
volume, a dangling copied snapshot, snapshots of a deleted database, and an AMI shared
with an account Janitor doesn't scan.
"""

import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

ANCHOR = datetime(2026, 10, 1, tzinfo=UTC)
TOOLS, DEV, PROD, UNSCANNED = (
    "111111111111",
    "222222222222",
    "333333333333",
    "444444444444",
)
EAST, WEST, EU = "us-east-1", "us-west-2", "eu-west-1"
OUT = Path(__file__).resolve().parents[1] / "fixtures" / "seed.json"


def ts(days_ago: float) -> str:
    return (ANCHOR - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp(days_ago: float) -> str:
    """14-digit name timestamp, so it never looks like a 12-digit account ID."""
    return (ANCHOR - timedelta(days=days_ago)).strftime("%Y%m%d%H%M%S")


class Seed:
    def __init__(self) -> None:
        self.rng = random.Random(20261001)
        self.resources: list[dict] = []
        self.shares: list[dict] = []
        self.usage: list[dict] = []
        self.databases: list[dict] = []

    def new_id(self, prefix: str) -> str:
        return f"{prefix}-0000{self.rng.getrandbits(52):013x}"

    def add(self, **fields) -> str:
        self.resources.append(fields)
        return fields["id"]

    def ami(
        self,
        region,
        name,
        days,
        *,
        size=8,
        tags=None,
        source=None,
        managed_by=None,
        shared_with=(),
    ):
        """An AMI in the owner account plus its root snapshot."""
        ami_id, snap_id = self.new_id("ami"), self.new_id("snap")
        tags = {"owner": "platform"} if tags is None else tags
        self.add(
            id=ami_id,
            type="ami",
            account=TOOLS,
            region=region,
            name=name,
            created_at=ts(days),
            size_gb=size,
            state="available",
            tags=tags,
            snapshot_ids=[snap_id],
            source_ami_id=source,
            managed_by=managed_by,
        )
        self.add(
            id=snap_id,
            type="snapshot",
            account=TOOLS,
            region=region,
            name=f"{name}-root",
            created_at=ts(days),
            size_gb=size,
            state="completed",
            tags=dict(tags),
            linked_ami_id=ami_id,
            managed_by=managed_by,
        )
        for principal in shared_with:
            kind = "account" if principal.isdigit() else "group"
            self.shares.append(
                {"image_id": ami_id, "principal_type": kind, "principal": principal}
            )
        return ami_id

    def use(self, image_id, account, region, ref_type, ref_name):
        prefix = {"instance": "i", "launch_template": "lt"}.get(ref_type)
        ref_id = self.new_id(prefix) if prefix else ref_name
        self.usage.append(
            {
                "image_id": image_id,
                "account": account,
                "region": region,
                "ref_type": ref_type,
                "ref_id": ref_id,
                "ref_name": ref_name,
            }
        )

    def volume(
        self,
        account,
        region,
        name,
        days,
        *,
        size=20,
        vtype="gp3",
        attached=False,
        tags=None,
    ):
        return self.add(
            id=self.new_id("vol"),
            type="volume",
            account=account,
            region=region,
            name=name,
            created_at=ts(days),
            size_gb=size,
            state="in-use" if attached else "available",
            tags={"owner": "platform"} if tags is None else tags,
            attached_instance=self.new_id("i") if attached else None,
            volume_type=vtype,
        )

    def snapshot(
        self,
        account,
        region,
        name,
        days,
        *,
        size=20,
        volume=None,
        linked_ami=None,
        tags=None,
        managed_by=None,
    ):
        return self.add(
            id=self.new_id("snap"),
            type="snapshot",
            account=account,
            region=region,
            name=name,
            created_at=ts(days),
            size_gb=size,
            state="completed",
            tags={"owner": "platform"} if tags is None else tags,
            source_volume_id=volume or self.new_id("vol"),
            linked_ami_id=linked_ami,
            managed_by=managed_by,
        )

    def database(self, account, region, db_id, kind="instance"):
        self.databases.append(
            {"id": db_id, "account": account, "region": region, "kind": kind}
        )

    def rds_snapshot(
        self,
        account,
        region,
        db_id,
        days,
        *,
        kind="instance",
        size=50,
        automated=False,
        managed_by=None,
        tags=None,
    ):
        name = f"rds:{db_id}-{stamp(days)}" if automated else f"{db_id}-{stamp(days)}"
        arn_kind = "cluster-snapshot" if kind == "cluster" else "snapshot"
        return self.add(
            id=f"arn:aws:rds:{region}:{account}:{arn_kind}:{name}",
            type="rds_snapshot",
            account=account,
            region=region,
            name=name,
            created_at=ts(days),
            size_gb=size,
            state="available",
            tags={"owner": "data"} if tags is None else tags,
            source_db_id=db_id,
            db_kind=kind,
            managed_by="rds_automated" if automated else managed_by,
        )

    def to_json(self) -> dict:
        return {
            "anchor": ts(0),
            "resources": self.resources,
            "shares": self.shares,
            "usage": self.usage,
            "databases": self.databases,
        }


def build() -> dict:
    s = Seed()

    # base-linux in the primary region: shared with dev and prod; only the newest is in use.
    s.ami(
        EAST, f"base-linux-{stamp(400)}", 400, tags={}, shared_with=[DEV, PROD]
    )  # orphaned, no owner tag
    s.ami(
        EAST,
        f"base-linux-{stamp(300)}",
        300,
        tags={"owner": "platform", "retain": "true"},
        shared_with=[DEV, PROD],
    )  # orphaned but protected
    base_200 = s.ami(
        EAST, f"base-linux-{stamp(200)}", 200, shared_with=[DEV, PROD]
    )  # source of a live copy
    s.ami(
        EAST, f"base-linux-{stamp(120)}", 120, shared_with=[DEV, PROD]
    )  # orphaned, deletable
    s.ami(EAST, f"base-linux-{stamp(60)}", 60, shared_with=[DEV, PROD])  # idle
    base_20 = s.ami(EAST, f"base-linux-{stamp(20)}", 20, shared_with=[DEV, PROD])
    s.use(base_20, DEV, EAST, "instance", "dev-api-1")
    s.use(base_20, PROD, EAST, "asg", "prod-api-asg")

    web_10 = s.ami(EAST, f"app-web-{stamp(10)}", 10, shared_with=[PROD])
    s.use(web_10, PROD, EAST, "launch_template", "prod-web v7")
    s.ami(EAST, f"app-web-{stamp(45)}", 45, shared_with=[PROD])  # idle
    web_150 = s.ami(EAST, f"app-web-{stamp(150)}", 150, shared_with=[PROD])  # orphaned

    bastion = s.ami(EAST, f"bastion-{stamp(500)}", 500)
    s.use(bastion, TOOLS, EAST, "instance", "tools-bastion")
    s.ami(EAST, f"partner-export-{stamp(250)}", 250, shared_with=[UNSCANNED])  # unknown
    s.ami(
        EAST, f"public-demo-{stamp(180)}", 180, shared_with=["all"]
    )  # unknown: public
    s.ami(
        EAST,
        f"AwsBackup_i-0000a1b2c3d4e5f60-{stamp(40)}",
        40,
        managed_by="aws_backup",
        tags={
            "owner": "platform",
            "aws:backup:source-resource": "instance/i-0000a1b2c3d4e5f60",
        },
    )
    s.ami(EAST, f"test-build-{stamp(5)}", 5)  # idle and too new

    # Copies in other regions get new AMI IDs and are shared within their own region.
    west_copy = s.ami(
        WEST, f"base-linux-{stamp(20)}", 19, source=base_20, shared_with=[DEV]
    )
    s.use(west_copy, DEV, WEST, "instance", "dev-worker-1")
    eu_copy = s.ami(
        EU, f"base-linux-{stamp(200)}", 199, source=base_200, shared_with=[PROD]
    )
    s.use(eu_copy, PROD, EU, "instance", "prod-eu-api-1")
    s.ami(
        EU, f"app-web-{stamp(150)}", 149, source=web_150, shared_with=[PROD]
    )  # orphaned copy

    # Dangling snapshots: their AMI was deregistered, the snapshot stayed.
    s.snapshot(
        TOOLS,
        WEST,
        "copy-of-retired-api-root",
        210,
        size=30,
        linked_ami=s.new_id("ami"),
    )
    s.snapshot(
        TOOLS, EAST, "retired-api-root", 220, size=30, linked_ami=s.new_id("ami")
    )
    s.snapshot(
        TOOLS,
        EAST,
        "nightly-tools-data",
        3,
        managed_by="dlm",
        tags={
            "owner": "platform",
            "aws:dlm:lifecycle-policy-id": "policy-0000example0001",
        },
    )
    # An AMI built in dev, where Janitor doesn't list AMIs: usage is unknown.
    s.snapshot(
        DEV,
        EAST,
        "dev-sandbox-image-root",
        130,
        linked_ami=s.new_id("ami"),
        tags={"owner": "dev-team"},
    )

    data_vol = s.volume(TOOLS, EAST, "tools-ci-data", 365, size=100, attached=True)
    s.snapshot(
        TOOLS, EAST, "tools-ci-data-weekly", 100, size=100, volume=data_vol
    )  # idle: volume exists
    s.snapshot(TOOLS, EAST, "tools-ci-data-old", 400, size=100)  # orphaned: volume gone
    s.snapshot(TOOLS, EAST, "tools-migration-temp", 12, size=40)  # idle: young
    s.volume(TOOLS, EAST, "tools-runner-cache", 200, size=50)  # orphaned
    s.volume(TOOLS, EAST, "tools-scratch", 15, size=10)  # idle
    s.volume(TOOLS, EAST, "tools-bastion-root", 500, size=8, attached=True)

    s.volume(DEV, EAST, "dev-api-1-root", 20, attached=True, tags={"owner": "dev-team"})
    s.volume(
        DEV,
        EAST,
        "dev-old-cache",
        180,
        size=200,
        vtype="gp2",
        tags={"owner": "dev-team"},
    )
    s.volume(
        DEV, EAST, "dev-test-data", 150, size=80, tags={}
    )  # orphaned, no owner tag
    s.volume(
        PROD,
        EAST,
        "prod-api-root",
        300,
        attached=True,
        tags={"owner": "platform", "env": "prod"},
    )
    s.volume(
        PROD,
        EAST,
        "prod-scratch-data",
        240,
        size=500,
        vtype="io2",
        tags={"owner": "data", "env": "prod"},
    )  # orphaned; needs typed confirmation
    s.volume(
        PROD,
        EAST,
        "prod-ledger-archive",
        400,
        size=1000,
        vtype="st1",
        tags={"owner": "finance", "env": "prod", "retain": "true"},
    )  # protected
    s.volume(
        PROD,
        EU,
        "prod-eu-api-root",
        199,
        attached=True,
        tags={"owner": "platform", "env": "prod"},
    )
    s.volume(
        PROD,
        EU,
        "prod-eu-reindex",
        20,
        size=60,
        tags={"owner": "search", "env": "prod"},
    )

    s.database(DEV, EAST, "dev-orders")
    s.rds_snapshot(DEV, EAST, "dev-orders", 1, automated=True)
    s.rds_snapshot(DEV, EAST, "dev-orders", 2, automated=True)
    s.rds_snapshot(DEV, EAST, "dev-orders", 95)  # idle: database exists
    s.rds_snapshot(DEV, EAST, "dev-orders", 60, tags={})  # idle, no owner tag
    s.rds_snapshot(DEV, EAST, "dev-legacy", 300)  # orphaned: database deleted
    s.rds_snapshot(
        DEV, EAST, "dev-legacy", 200
    )  # orphaned: newest copy of a deleted database
    s.database(DEV, EAST, "dev-analytics", "cluster")
    s.rds_snapshot(DEV, EAST, "dev-analytics", 40, kind="cluster", size=120)
    s.rds_snapshot(DEV, EAST, "dev-reports", 120, kind="cluster", size=80)  # orphaned
    s.rds_snapshot(
        DEV, EAST, "dev-reports", 10, kind="cluster", size=80
    )  # idle, too new
    s.database(PROD, EAST, "prod-orders")
    s.rds_snapshot(
        PROD,
        EAST,
        "prod-orders",
        7,
        managed_by="aws_backup",
        tags={"owner": "data", "env": "prod"},
    )
    s.rds_snapshot(PROD, EAST, "prod-orders", 90, tags={"owner": "data", "env": "prod"})

    # Background noise from a fixed RNG.
    for n in range(60):
        days = s.rng.randint(1, 700)
        tags = (
            {"owner": s.rng.choice(["platform", "data", "dev-team"])}
            if s.rng.random() < 0.8
            else {}
        )
        volume = data_vol if s.rng.random() < 0.2 else None
        region = EAST if volume else s.rng.choice([EAST, WEST, EU])
        s.snapshot(
            TOOLS,
            region,
            f"tools-backup-{n:03d}",
            days,
            size=s.rng.choice([8, 20, 50, 100]),
            volume=volume,
            tags=tags,
        )
    for n in range(20):
        days = s.rng.randint(1, 500)
        s.volume(
            DEV,
            EAST,
            f"dev-ephemeral-{n:03d}",
            days,
            size=s.rng.choice([10, 20, 40]),
            attached=s.rng.random() < 0.5,
            tags={"owner": "dev-team"},
        )
    return s.to_json()


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(build(), indent=1) + "\n")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
