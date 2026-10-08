#!/usr/bin/env python3
"""Generate fixtures/seed.json, the mock dataset. Fake IDs only; fixed RNG seed.

Every status per type appears, plus the demo moments: an in-use AMI with running and
stopped users, a prod-tagged volume, a dangling copied snapshot, snapshots of a deleted
database, and an AMI shared with an account Janitor doesn't scan.

Deployments: EC2 apps (tagged ASGs, each also an `asg` user of its AMI), instances in no ASG,
and ECS services, with a switch in progress, a failed rollout, version drift, a blue/green
standby, a stopped server, and old versions.
"""

import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

ANCHOR = datetime(2026, 10, 1, tzinfo=UTC)
TOOLS, DEV, PRD, UNSCANNED = (
    "111111111111",
    "222222222222",
    "333333333333",
    "444444444444",
)
SBX, UAT, QAS = "555555555555", "666666666666", "777777777777"
ENVS = [SBX, DEV, UAT, QAS, PRD]
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
        self.deployments: list[dict] = []

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
            storage_tier="standard",
        )
        for principal in shared_with:
            kind = "account" if principal.isdigit() else "group"
            self.shares.append(
                {"image_id": ami_id, "principal_type": kind, "principal": principal}
            )
        return ami_id

    def use(self, image_id, account, region, ref_type, ref_name, state=""):
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
                "ref_state": state,
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
        iops=None,
        throughput=None,
        encrypted=True,
    ):
        if vtype == "gp3":
            iops, throughput = iops or 3000, throughput or 125
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
            iops=iops,
            throughput=throughput,
            encrypted=encrypted,
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
        tier="standard",
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
            storage_tier=tier,
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

    def asg(
        self, account, region, env, app, version, state, days, ami, *, desired=2, n=1
    ):
        """A deploy tool's ASG: tagged with a state, launched from a template version."""
        name = f"{env}-{app}-{version}-{n}"
        running = desired if state in ("deployed", "deploying") else 0
        self.deployments.append(
            {
                "kind": "ec2",
                "account": account,
                "region": region,
                "env": env,
                "app": app,
                "version": version,
                "state": state,
                "resource_id": name,
                "name": name,
                "created_at": ts(days),
                "desired": desired,
                "running": running,
                "deployment_id": str(n),
                "launch_template": f"{env}-{app}",
                "launch_template_version": str(n),
                "ami_id": ami,
                "unit": "asg",
            }
        )
        self.use(ami, account, region, "asg", name, "active" if desired else "inactive")

    def lone(self, ref_name, env, app, version):
        """An instance in no ASG, from its usage row (same ID, AMI, and place)."""
        use = next(u for u in self.usage if u["ref_name"] == ref_name)
        running = use["ref_state"] == "running"
        self.deployments.append(
            {
                "kind": "ec2",
                "account": use["account"],
                "region": use["region"],
                "env": env,
                "app": app,
                "version": version,
                "state": "deployed",
                "resource_id": use["ref_id"],
                "name": ref_name,
                "created_at": ts(60),
                "desired": int(running),
                "running": int(running),
                "ami_id": use["image_id"],
                "unit": "instance",
            }
        )

    def service(
        self, account, region, env, app, version, state, days, *, desired=2, name=None
    ):
        """An ECS service and the task definition revision it runs."""
        name = name or app
        revision = sum(1 for d in self.deployments if d["app"] == app) + 1
        self.deployments.append(
            {
                "kind": "ecs",
                "account": account,
                "region": region,
                "env": env,
                "app": app,
                "version": version,
                "state": state,
                "resource_id": f"arn:aws:ecs:{region}:{account}:service/apps/{name}",
                "name": name,
                "created_at": ts(days),
                "desired": desired,
                "running": 0 if state == "failed" else desired,
                "cluster": "apps",
                "task_definition": f"{app}:{revision}",
                "image": f"registry.example/{app}:{version}",
                "unit": "service",
            }
        )

    def to_json(self) -> dict:
        return {
            "anchor": ts(0),
            "resources": self.resources,
            "shares": self.shares,
            "usage": self.usage,
            "databases": self.databases,
            "deployments": self.deployments,
            # Accounts an AMI is shared with whose role Janitor can't assume (mock only).
            "unreachable": [UNSCANNED],
        }


def build() -> dict:
    s = Seed()
    prod = {"env": "prod"}

    # base-linux in the primary region, shared with every environment; only the newest is used.
    s.ami(
        EAST, f"base-linux-{stamp(400)}", 400, tags={}, shared_with=ENVS
    )  # orphaned, no owner tag
    s.ami(
        EAST,
        f"base-linux-{stamp(300)}",
        300,
        tags={"owner": "platform", "retain": "true"},
        shared_with=ENVS,
    )  # orphaned but protected
    base_200 = s.ami(
        EAST, f"base-linux-{stamp(200)}", 200, shared_with=ENVS
    )  # source of a live copy
    s.ami(
        EAST, f"base-linux-{stamp(120)}", 120, shared_with=ENVS
    )  # orphaned, deletable
    s.ami(EAST, f"base-linux-{stamp(60)}", 60, shared_with=ENVS)  # idle
    base_20 = s.ami(EAST, f"base-linux-{stamp(20)}", 20, shared_with=ENVS)
    s.use(base_20, DEV, EAST, "instance", "dev-api-1", "running")
    s.use(base_20, PRD, EAST, "asg", "prd-api-asg", "active")
    s.use(base_20, QAS, EAST, "instance", "qas-api-1", "stopped")
    s.use(base_20, UAT, EAST, "launch_template", "uat-api v3")

    web_10 = s.ami(EAST, f"app-web-{stamp(10)}", 10, shared_with=[UAT, QAS, PRD])
    s.use(web_10, PRD, EAST, "launch_template", "prd-web v7")
    s.use(web_10, PRD, EAST, "asg", "prd-web-asg", "active")
    s.ami(EAST, f"app-web-{stamp(45)}", 45, shared_with=[UAT, QAS, PRD])  # idle
    web_150 = s.ami(
        EAST, f"app-web-{stamp(150)}", 150, shared_with=[UAT, QAS, PRD]
    )  # orphaned

    bastion = s.ami(EAST, f"bastion-{stamp(500)}", 500)
    s.use(bastion, TOOLS, EAST, "instance", "tools-bastion", "running")
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

    # Copies in other regions get new AMI IDs and are shared within their own region with prd.
    west_copy = s.ami(
        WEST, f"base-linux-{stamp(20)}", 19, source=base_20, shared_with=[PRD]
    )
    s.use(west_copy, PRD, WEST, "instance", "prd-dr-api-1", "stopped")
    eu_copy = s.ami(
        EU, f"base-linux-{stamp(200)}", 199, source=base_200, shared_with=[PRD]
    )
    s.use(eu_copy, PRD, EU, "instance", "prd-eu-api-1", "running")
    s.ami(
        EU, f"app-web-{stamp(150)}", 149, source=web_150, shared_with=[PRD]
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

    data_vol = s.volume(
        TOOLS,
        EAST,
        "tools-ci-data",
        365,
        size=100,
        attached=True,
        iops=6000,
        throughput=250,
    )
    s.snapshot(
        TOOLS, EAST, "tools-ci-data-weekly", 100, size=100, volume=data_vol
    )  # idle: volume exists
    s.snapshot(
        TOOLS, EAST, "tools-ci-data-old", 400, size=100, tier="archive"
    )  # orphaned, archived
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
        SBX, EAST, "sbx-playground", 300, size=40, vtype="gp2", tags={}, encrypted=False
    )
    s.volume(
        SBX, EAST, "sbx-notebook-data", 10, size=20, tags={"owner": "data-science"}
    )
    s.volume(
        UAT,
        EAST,
        "uat-api-root",
        60,
        attached=True,
        tags={"owner": "platform", "env": "uat"},
    )
    s.volume(
        UAT,
        EAST,
        "uat-load-test-data",
        120,
        size=300,
        vtype="io1",
        iops=3000,
        tags={"owner": "perf", "env": "uat"},
    )
    s.volume(
        QAS,
        EAST,
        "qas-api-root",
        45,
        attached=True,
        tags={"owner": "platform", "env": "qas"},
    )
    s.volume(
        QAS,
        EAST,
        "qas-regression-cache",
        95,
        size=100,
        tags={"owner": "qa", "env": "qas"},
    )
    s.volume(
        PRD,
        EAST,
        "prd-api-root",
        300,
        attached=True,
        tags={"owner": "platform", **prod},
    )
    s.volume(
        PRD,
        EAST,
        "prd-scratch-data",
        240,
        size=500,
        vtype="io2",
        iops=40000,
        tags={"owner": "data", **prod},
    )  # orphaned; needs typed confirmation; tiered IOPS
    s.volume(
        PRD,
        EAST,
        "prd-ledger-archive",
        400,
        size=1000,
        vtype="st1",
        tags={"owner": "finance", "retain": "true", **prod},
    )  # protected
    s.volume(
        PRD,
        EU,
        "prd-eu-api-root",
        199,
        attached=True,
        tags={"owner": "platform", **prod},
    )
    s.volume(PRD, EU, "prd-eu-reindex", 20, size=60, tags={"owner": "search", **prod})

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
    s.database(PRD, EAST, "prd-orders")
    s.rds_snapshot(
        PRD,
        EAST,
        "prd-orders",
        7,
        managed_by="aws_backup",
        tags={"owner": "data", **prod},
    )
    s.rds_snapshot(PRD, EAST, "prd-orders", 90, tags={"owner": "data", **prod})
    s.database(SBX, EAST, "sbx-demo")
    s.rds_snapshot(SBX, EAST, "sbx-demo", 50, tags={"owner": "data-science"})
    s.rds_snapshot(UAT, EAST, "uat-orders", 150)  # orphaned: database deleted
    s.database(QAS, EAST, "qas-orders")
    s.rds_snapshot(QAS, EAST, "qas-orders", 1, automated=True)

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
            s.rng.choice(ENVS),
            EAST,
            f"ephemeral-{n:03d}",
            days,
            size=s.rng.choice([10, 20, 40]),
            attached=s.rng.random() < 0.5,
            tags={"owner": "dev-team"},
        )
    deployments(s, base_20, web_10, west_copy)
    return s.to_json()


def deployments(s: Seed, base: str, web: str, west_base: str) -> None:
    """Apps in sbx, dev, uat, qas, and prd (two regions). Env names match the account names."""
    envs = {"sbx": SBX, "dev": DEV, "uat": UAT, "qas": QAS, "prd": PRD}
    # api: blue/green on EC2 (not in sbx: its share of the AMI stays unused for the demo). dev
    # is mid-switch; prd keeps its previous group, scaled to 0.
    for env, version, n in (("qas", "3.1.0", 9), ("uat", "3.1.0", 11)):
        s.asg(envs[env], EAST, env, "api", version, "deployed", 12, base, n=n)
    s.asg(DEV, EAST, "dev", "api", "3.1.0", "undeploying", 12, base, n=21)
    s.asg(DEV, EAST, "dev", "api", "3.2.0", "deploying", 0.1, base, n=22)
    s.asg(PRD, EAST, "prd", "api", "3.0.5", "deployed", 9, base, desired=6, n=31)
    s.asg(PRD, EAST, "prd", "api", "3.0.4", "undeployed", 30, base, desired=0, n=30)
    s.asg(PRD, WEST, "prd", "api", "3.0.5", "deployed", 9, west_base, desired=2, n=32)
    # web: only uat, qas, and prd can launch its AMI. prd is a version behind.
    s.asg(UAT, EAST, "uat", "web", "2.4.1", "deployed", 6, web, n=5)
    s.asg(QAS, EAST, "qas", "web", "2.4.1", "deployed", 7, web, n=4)
    s.asg(PRD, EAST, "prd", "web", "2.4.0", "deployed", 8, web, desired=4, n=3)
    s.asg(PRD, EAST, "prd", "web", "2.3.9", "undeployed", 40, web, desired=0, n=2)
    # worker: destroy-before-create on EC2.
    s.asg(DEV, EAST, "dev", "worker", "1.8.0", "deployed", 4, base, desired=1, n=8)
    s.asg(PRD, EAST, "prd", "worker", "1.7.2", "deployed", 20, base, desired=1, n=6)

    # orders-api: rolling on ECS. The qas rollout of 2.8.0 failed.
    for env, version in (("sbx", "2.8.0"), ("dev", "2.8.0"), ("uat", "2.7.3")):
        s.service(envs[env], EAST, env, "orders-api", version, "deployed", 3)
    s.service(QAS, EAST, "qas", "orders-api", "2.8.0", "failed", 0.2)
    s.service(PRD, EAST, "prd", "orders-api", "2.7.3", "deployed", 15, desired=6)
    s.service(PRD, WEST, "prd", "orders-api", "2.7.3", "deployed", 15, desired=2)
    # billing-svc: blue/green on ECS; prd's green side is the standby, scaled to 0.
    s.service(
        DEV, EAST, "dev", "billing-svc", "5.1.0", "deployed", 2, name="billing-svc-blue"
    )
    s.service(
        PRD,
        EAST,
        "prd",
        "billing-svc",
        "5.0.1",
        "deployed",
        11,
        desired=4,
        name="billing-svc-blue",
    )
    s.service(
        PRD,
        EAST,
        "prd",
        "billing-svc",
        "5.0.0",
        "undeployed",
        25,
        desired=0,
        name="billing-svc-green",
    )
    # reports: a small ECS service in two envs.
    s.service(DEV, EAST, "dev", "reports", "0.9.2", "deployed", 1, desired=1)
    s.service(UAT, EAST, "uat", "reports", "0.9.1", "deployed", 10, desired=1)

    # Instances in no ASG: a bastion, an old api server beside the ASGs, and prd's DR and EU
    # servers (DR kept stopped).
    s.lone("tools-bastion", "tools", "tools-bastion", "")
    s.lone("dev-api-1", "dev", "api", "3.0.9")
    s.lone("qas-api-1", "qas", "api", "3.0.2")
    s.lone("prd-dr-api-1", "prd", "api", "3.0.5")
    s.lone("prd-eu-api-1", "prd", "api", "3.0.5")


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(build(), indent=1) + "\n")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
