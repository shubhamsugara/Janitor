from collections import defaultdict

import pytest
from helpers import DEV, NOW, TOOLS, UNSCANNED, days_ago

from janitor.linker import LinkContext, link
from janitor.models import STATUSES, Database, Inventory, Resource, Share, Usage

CTX = LinkContext(
    owner_account=TOOLS, account_names={TOOLS: "tools", DEV: "dev"}, orphan_after_days=90, now=NOW
)


def res(id, type, **kw):
    fields = {"account": TOOLS, "region": "us-east-1", "name": id, "created_at": days_ago(100)} | kw
    return Resource(id=id, type=type, **fields)


def status(resources, shares=(), usage=(), databases=(), ctx=CTX):
    result = link(Inventory(list(resources), list(shares), list(usage), list(databases)), ctx)
    return {rid: s for rid, (s, _) in result.items()}, result


def test_ami_used_by_permitted_account_in_its_region_is_in_use():
    ami = res("ami-1", "ami")
    statuses, result = status(
        [ami],
        [Share("ami-1", "account", DEV)],
        [Usage("ami-1", DEV, "us-east-1", "instance", "i-1", "dev-api-1")],
    )
    assert statuses["ami-1"] == "in_use"
    assert "dev-api-1" in result["ami-1"][1] and "dev" in result["ami-1"][1]


@pytest.mark.parametrize(
    "usage",
    [
        Usage("ami-1", DEV, "us-east-1", "instance", "i-1"),  # dev has no launch permission
        Usage("ami-1", TOOLS, "eu-west-1", "instance", "i-1"),  # permissions are region-scoped
    ],
)
def test_ami_usage_outside_permissions_is_ignored(usage):
    assert status([res("ami-1", "ami")], usage=[usage])[0]["ami-1"] == "orphaned"


def test_ami_shared_with_unscanned_account_is_unknown():
    statuses, result = status([res("ami-1", "ami")], [Share("ami-1", "account", UNSCANNED)])
    assert statuses["ami-1"] == "unknown" and UNSCANNED in result["ami-1"][1]


@pytest.mark.parametrize("kind", ["group", "org", "ou"])
def test_ami_shared_publicly_or_with_org_is_unknown(kind):
    assert status([res("ami-1", "ami")], [Share("ami-1", kind, "all")])[0]["ami-1"] == "unknown"


def test_precedence_in_use_beats_unknown_and_managed_beats_unknown():
    used = res("ami-1", "ami")
    managed = res("ami-2", "ami", managed_by="aws_backup")
    shares = [Share("ami-1", "group", "all"), Share("ami-2", "group", "all")]
    statuses, _ = status(
        [used, managed], shares, [Usage("ami-1", TOOLS, "us-east-1", "instance", "i-1")]
    )
    assert statuses == {"ami-1": "in_use", "ami-2": "managed"}


@pytest.mark.parametrize(("days", "expected"), [(90, "orphaned"), (89, "idle")])
def test_unused_ami_age_threshold(days, expected):
    assert status([res("ami-1", "ami", created_at=days_ago(days))])[0]["ami-1"] == expected


def test_snapshot_statuses():
    resources = [
        res("ami-1", "ami", snapshot_ids=["snap-bdm"]),
        res("snap-bdm", "snapshot"),
        res("snap-desc", "snapshot", linked_ami_id="ami-1"),
        res("snap-dangling", "snapshot", linked_ami_id="ami-gone", created_at=days_ago(5)),
        res("snap-dev", "snapshot", account=DEV, linked_ami_id="ami-elsewhere"),
        res("snap-dlm", "snapshot", managed_by="dlm"),
        res("vol-1", "volume", attached_instance="i-1"),
        res("snap-vol", "snapshot", source_volume_id="vol-1", created_at=days_ago(400)),
        res("snap-other-region", "snapshot", source_volume_id="vol-1", region="eu-west-1"),
        res("snap-young", "snapshot", source_volume_id="vol-gone", created_at=days_ago(10)),
    ]
    statuses, result = status(resources)
    assert statuses["snap-bdm"] == "in_use"
    assert statuses["snap-desc"] == "in_use"
    assert statuses["snap-dangling"] == "orphaned" and "ami-gone" in result["snap-dangling"][1]
    assert statuses["snap-dev"] == "unknown"
    assert statuses["snap-dlm"] == "managed"
    assert statuses["snap-vol"] == "idle"
    assert statuses["snap-other-region"] == "orphaned"
    assert statuses["snap-young"] == "idle"


def test_volume_statuses():
    statuses, result = status(
        [
            res("vol-a", "volume", attached_instance="i-1"),
            res("vol-old", "volume", created_at=days_ago(200)),
            res("vol-new", "volume", created_at=days_ago(10)),
        ]
    )
    assert statuses == {"vol-a": "in_use", "vol-old": "orphaned", "vol-new": "idle"}
    assert "i-1" in result["vol-a"][1]


def test_rds_snapshot_statuses():
    statuses, _ = status(
        [
            res("rds-auto", "rds_snapshot", managed_by="rds_automated", source_db_id="db1"),
            res("rds-live", "rds_snapshot", source_db_id="db1"),
            res("rds-gone", "rds_snapshot", source_db_id="db-gone", created_at=days_ago(200)),
            res("rds-gone-new", "rds_snapshot", source_db_id="db-gone", created_at=days_ago(5)),
            res("rds-other-acct", "rds_snapshot", source_db_id="db1", account=DEV),
        ],
        databases=[Database("db1", TOOLS, "us-east-1", "instance")],
    )
    assert statuses == {
        "rds-auto": "managed",
        "rds-live": "idle",
        "rds-gone": "orphaned",
        "rds-gone-new": "idle",
        "rds-other-acct": "orphaned",
    }  # databases are per account


def test_every_status_per_type_appears_in_the_seed(inventory, config):
    result = link(inventory, LinkContext.from_config(config, NOW))
    by_type = defaultdict(set)
    for r in inventory.resources:
        by_type[r.type].add(result[r.id][0])
    assert by_type == {
        "ami": set(STATUSES),
        "snapshot": set(STATUSES),
        "volume": {"in_use", "idle", "orphaned"},
        "rds_snapshot": {"managed", "idle", "orphaned"},
    }
    assert all(reason.endswith(".") for _, reason in result.values())
