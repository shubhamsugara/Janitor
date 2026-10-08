from collections import defaultdict

import pytest
from helpers import DEV, NOW, TOOLS, UNSCANNED, days_ago

from janitor.linker import LinkContext, link
from janitor.models import STATUSES, Database, Inventory, Resource, Share, Usage

CTX = LinkContext(
    owner_account=TOOLS, account_names={TOOLS: "tools", DEV: "dev"}, orphan_after_days=90, now=NOW
)


FAILED_CTX = dict(
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


def test_ami_shared_with_an_account_no_usage_check_reached_is_unknown():
    # Accounts are discovered from launch permissions; one without a usage check can't be proven.
    ctx = LinkContext(**FAILED_CTX, scanned={(TOOLS, "us-east-1"), (DEV, "us-east-1")})
    shared = [Share("ami-1", "account", UNSCANNED)]
    statuses, result = status([res("ami-1", "ami")], shared, ctx=ctx)
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


# Failed checks (phase 3): what depends on a failed segment is unknown, never deletable.


def test_ami_is_unknown_when_a_permitted_accounts_usage_check_failed():
    ctx = LinkContext(**FAILED_CTX, failed={(DEV, "us-east-1", "usage")})
    shared = [Share("ami-1", "account", DEV)]
    statuses, result = status([res("ami-1", "ami")], shared, ctx=ctx)
    assert statuses["ami-1"] == "unknown"
    assert "dev" in result["ami-1"][1] and "us-east-1" in result["ami-1"][1]
    used = [Usage("ami-1", DEV, "us-east-1", "instance", "i-1")]
    assert status([res("ami-1", "ami")], shared, used, ctx=ctx)[0]["ami-1"] == "in_use"


def test_ami_is_unknown_when_the_owners_own_usage_check_failed():
    ctx = LinkContext(**FAILED_CTX, failed={(TOOLS, "us-east-1", "usage")})
    assert status([res("ami-1", "ami")], ctx=ctx)[0]["ami-1"] == "unknown"


def test_ami_is_unknown_when_shared_with_an_account_not_scanned_in_its_region():
    ctx = LinkContext(**FAILED_CTX, scanned={(TOOLS, "eu-west-1"), (DEV, "us-east-1")})
    ami = res("ami-1", "ami", region="eu-west-1")
    statuses, result = status([ami], [Share("ami-1", "account", DEV)], ctx=ctx)
    assert statuses["ami-1"] == "unknown"
    assert "doesn't scan dev in eu-west-1" in result["ami-1"][1]


def test_owner_snapshot_is_unknown_when_its_regions_ami_list_failed():
    ctx = LinkContext(**FAILED_CTX, failed={(TOOLS, "us-east-1", "ami")})
    snaps = [
        res("snap-1", "snapshot", created_at=days_ago(200)),
        res("snap-2", "snapshot", created_at=days_ago(200), region="us-west-2"),
    ]
    statuses, result = status(snaps, ctx=ctx)
    assert statuses == {"snap-1": "unknown", "snap-2": "orphaned"}
    assert "AMIs" in result["snap-1"][1]


def test_snapshot_is_unknown_when_its_volume_list_failed_and_the_volume_is_missing():
    ctx = LinkContext(**FAILED_CTX, failed={(DEV, "us-east-1", "volume")})
    snap = res(
        "snap-1", "snapshot", account=DEV, source_volume_id="vol-1", created_at=days_ago(200)
    )
    statuses, result = status([snap], ctx=ctx)
    assert statuses["snap-1"] == "unknown" and "volumes" in result["snap-1"][1]


def test_manual_rds_snapshot_is_unknown_when_its_database_list_failed():
    ctx = LinkContext(**FAILED_CTX, failed={(DEV, "us-east-1", "database")})
    statuses, _ = status(
        [
            res("rds-manual", "rds_snapshot", account=DEV, source_db_id="db1"),
            res(
                "rds-auto",
                "rds_snapshot",
                account=DEV,
                source_db_id="db1",
                managed_by="rds_automated",
            ),
        ],
        ctx=ctx,
    )
    assert statuses == {"rds-manual": "unknown", "rds-auto": "managed"}


# Only instances are use; launch templates, ASGs, and launch configs are references (W6).


def test_an_ami_only_a_launch_template_names_is_not_in_use_but_is_referenced():
    from janitor.linker import references

    ami = res("ami-1", "ami")
    shared = [Share("ami-1", "account", DEV)]
    named = [
        Usage("ami-1", DEV, "us-east-1", "launch_template", "lt-1", "uat-api v3"),
        Usage("ami-1", DEV, "us-east-1", "asg", "web-asg", "web-asg", "inactive"),
    ]
    statuses, result = status([ami], shared, named)
    assert statuses["ami-1"] == "orphaned"
    assert "No instance uses it" in result["ami-1"][1]
    inv = Inventory([ami], shared, named, [])
    text = references(inv, CTX)["ami-1"]
    assert text == (
        "Launch template uat-api v3 in dev and Auto Scaling group web-asg in dev still name it, "
        "so their next launch would fail."
    )


def test_a_stopped_instance_in_a_member_account_is_use():
    stopped = [Usage("ami-1", DEV, "us-east-1", "instance", "i-1", "dev-api", "stopped")]
    statuses, _ = status([res("ami-1", "ami")], [Share("ami-1", "account", DEV)], stopped)
    assert statuses["ami-1"] == "in_use"


def test_references_outside_permissions_or_region_dont_count():
    from janitor.linker import references

    named = [
        Usage("ami-1", DEV, "us-east-1", "launch_template", "lt-1", "x"),  # dev not permitted
        Usage("ami-1", TOOLS, "eu-west-1", "launch_config", "lc-1", "y"),  # another region
    ]
    assert references(Inventory([res("ami-1", "ami")], [], named, []), CTX) == {}


# Ignored accounts (janitor.yaml ignore_accounts): they don't count against an AMI, and W7 says so.


def test_an_ami_shared_only_with_an_ignored_account_can_be_orphaned():
    from janitor.linker import ignored_shares

    ctx = LinkContext(**FAILED_CTX, scanned={(TOOLS, "us-east-1")}, ignored={UNSCANNED})
    ami = res("ami-1", "ami")
    shared = [Share("ami-1", "account", UNSCANNED)]
    statuses, _ = status([ami], shared, ctx=ctx)
    assert statuses["ami-1"] == "orphaned"
    assert ignored_shares(Inventory([ami], shared, [], []), ctx) == {"ami-1": UNSCANNED}


def test_ignoring_one_account_doesnt_excuse_another_that_couldnt_be_checked():
    ctx = LinkContext(
        **FAILED_CTX,
        scanned={(TOOLS, "us-east-1"), (DEV, "us-east-1")},
        failed={(DEV, "us-east-1", "usage")},
        ignored={UNSCANNED},
    )
    shared = [Share("ami-1", "account", UNSCANNED), Share("ami-1", "account", DEV)]
    assert status([res("ami-1", "ami")], shared, ctx=ctx)[0]["ami-1"] == "unknown"
