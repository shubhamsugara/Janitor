import pytest
from helpers import EXAMPLE, NOW, days_ago

from janitor.config import Policy, load_config
from janitor.definitions import build
from janitor.models import Resource, RuleResult
from janitor.rules import RULES_BY_ID, evaluate, explain, strictest

POLICY = Policy(orphan_after_days=90, min_age_days=30, protected_tags={"retain": "true"})


def res(**kw):
    fields = {
        "id": "x",
        "type": "volume",
        "account": "111111111111",
        "region": "us-east-1",
        "name": "x",
        "created_at": days_ago(100),
        "tags": {"owner": "me"},
        "status": "orphaned",
    }
    return Resource(**(fields | kw))


def ids(resource, **kw):
    return {(h.rule_id, h.outcome) for h in evaluate(resource, POLICY, NOW, **kw)}


def test_clean_orphan_passes_every_rule():
    assert ids(res()) == set()


@pytest.mark.parametrize(
    ("status", "rule"), [("in_use", "R1"), ("unknown", "R2"), ("managed", "R3")]
)
def test_status_rules_block(status, rule):
    assert ids(res(status=status, status_reason="Because.")) == {(rule, "block")}


def test_r4_protected_tag_blocks():
    assert ids(res(tags={"owner": "me", "retain": "true"})) == {("R4", "block")}


def test_r4_protected_tag_value_is_case_insensitive():
    assert ids(res(tags={"owner": "me", "retain": "True"})) == {("R4", "block")}


@pytest.mark.parametrize(("days", "blocked"), [(29, True), (30, False)])
def test_r5_minimum_age(days, blocked):
    assert (("R5", "block") in ids(res(created_at=days_ago(days)))) is blocked


def test_w4_missing_owner_tag_warns_and_key_case_is_ignored():
    assert ids(res(tags={})) == {("W4", "warn")}
    assert ids(res(tags={"Owner": "me"})) == set()


def test_skip_drops_a_rule():
    assert ids(res(status="in_use"), skip=frozenset({"R1"})) == set()


def test_strictest_wins():
    block, warn = RuleResult("x", "R1", "block", ""), RuleResult("x", "W4", "warn", "")
    assert strictest([warn, block]) == "block"
    assert strictest([warn]) == "warn"
    assert strictest([]) == "pass"


def test_explanations_use_live_config_values(config):
    assert "30 days" in explain(RULES_BY_ID["R5"], POLICY)
    assert "retain=true" in explain(RULES_BY_ID["R4"], POLICY)
    defs = build(config)
    assert "older than 90 days" in defs["statuses"]["orphaned"]["meaning"]
    assert set(defs["by_type"]) == {"ami", "snapshot", "volume", "rds_snapshot"}
    assert [r["id"] for r in defs["rules"]] == [
        "R1", "R2", "R3", "R4", "R5", "R6", "R7", "W1", "W2", "W3", "W4", "W5", "W6", "W7"
    ]


def test_r4_protected_tag_key_is_case_insensitive():
    assert ids(res(tags={"Owner": "me", "Retain": "true"})) == {("R4", "block")}


@pytest.mark.parametrize(
    "tags",
    [
        {"owner": "me", "Retain": "true", "retain": "no"},
        {"owner": "me", "retain": "no", "Retain": "true"},
    ],
)
def test_r4_blocks_when_any_case_variant_of_the_key_matches(tags):
    """AWS tag keys are case-sensitive, so one resource can carry both."""
    assert ids(res(tags=tags)) == {("R4", "block")}


def test_w6_referenced_warns_with_what_names_it():
    text = "Launch template uat-api v3 in uat still names it, so its next launch would fail."
    ami = res(type="ami", referenced_by=text)
    hits = evaluate(ami, POLICY, NOW)
    assert ("W6", "warn") in {(h.rule_id, h.outcome) for h in hits}
    assert next(h.message for h in hits if h.rule_id == "W6") == text
    assert ("W6", "warn") not in ids(res(type="ami"))


def test_w7_warns_when_an_ami_is_shared_with_ignored_accounts():
    ami = res(type="ami", ignored_shares="444444444444")
    hits = {h.rule_id: h for h in evaluate(ami, POLICY, NOW)}
    assert hits["W7"].outcome == "warn"
    assert hits["W7"].message == (
        "Shared with 444444444444, which Janitor is set to ignore. Anyone there loses access to it."
    )
    assert "W7" not in {h.rule_id for h in evaluate(res(type="ami"), POLICY, NOW)}


def test_deployment_help_is_a_glossary_with_the_configured_tags():
    from janitor.config import Config, DeploymentTags

    config = load_config(EXAMPLE)
    help = build(config)["deployments"]
    terms = [t["term"] for t in help["terms"]]
    assert terms == [
        "Column",
        "Row (app)",
        "EC2 deployment",
        "Standalone instance",
        "ECS deployment",
        "Deploy state",
        "Run status",
        "Count",
        "Live version",
        "Earlier version",
        "Drift",
    ]
    text = " ".join(t["definition"] for t in help["terms"])
    assert "`deploy-state`" in text and "`role`" in text and "rolloutState" in text
    renamed = Config.model_validate(
        config.model_dump() | {"deployments": {"tags": DeploymentTags(state="stage").model_dump()}}
    )
    assert "`stage`" in " ".join(t["definition"] for t in build(renamed)["deployments"]["terms"])


# --- Cross-resource rules (phase 3b) -------------------------------------------------------

from janitor.models import Database  # noqa: E402
from janitor.rules import context, outcome  # noqa: E402


def ami(id, name, age, region="us-east-1", account="111111111111", **kw):
    return res(id=id, type="ami", name=name, created_at=days_ago(age), region=region,
               account=account, **kw)


def hits(resource, resources, databases=(), policy=POLICY):
    ctx = context(list(resources), list(databases), policy)
    return {h.rule_id: h for h in evaluate(resource, policy, NOW, ctx)}


def test_r6_keeps_newest_per_group_and_region():
    amis = [ami(f"ami-{n}", f"ecs-gpu-2026090{n}", age=10 * n) for n in range(1, 6)]
    kept = {a.id for a in amis if "R6" in hits(a, amis)}
    assert kept == {"ami-1", "ami-2", "ami-3"}
    assert hits(amis[1], amis)["R6"].message == (
        "It is the 2nd newest of 5 AMIs named ecs-gpu* in us-east-1; Janitor keeps the 3 newest."
    )
    assert hits(amis[0], amis)["R6"].outcome == "block"
    assert hits(amis[0], amis)["R6"].message.startswith("It is the newest of 5 AMIs")


def test_r6_ties_break_by_id():
    amis = [ami(f"ami-{c}", f"base-{n}", age=40) for n, c in enumerate("dcba")]
    assert {a.id for a in amis if "R6" in hits(a, amis)} == {"ami-a", "ami-b", "ami-c"}


def test_r6_unmatched_name_is_its_own_group():
    lone = ami("ami-1", "golden (copy) [x]", age=200)
    others = [ami(f"ami-{n}", f"golden-{n}", age=n) for n in range(2, 6)]
    assert hits(lone, [lone, *others])["R6"].message == (
        "It is the only AMI named golden (copy) [x] in us-east-1; Janitor keeps the 3 newest."
    )


def test_r6_counts_per_account_and_region():
    east = [ami(f"ami-e{n}", f"app-{n}", age=n) for n in range(1, 5)]
    west = ami("ami-w", "app-9", age=500, region="us-west-2")
    other = ami("ami-o", "app-8", age=400, account="222222222222")
    pool = [*east, west, other]
    assert "R6" in hits(west, pool) and "R6" in hits(other, pool)
    assert "R6" not in hits(east[3], pool)


def test_r7_matches_keep_pattern():
    policy = POLICY.model_copy(update={"keep_name_patterns": ["^golden-", "-lts$"]})
    keep = ami("ami-1", "base-lts", age=100)
    assert hits(keep, [keep], policy=policy)["R7"].message == (
        "Its name matches the keep pattern -lts$."
    )
    assert "R7" not in hits(ami("ami-2", "base-1", age=100), [], policy=policy)


def test_w1_only_for_copies_in_other_regions():
    src = ami("ami-src", "base-1", age=100)
    west = ami("ami-w", "base-1", age=90, region="us-west-2", source_ami_id="ami-src")
    eu = ami("ami-eu", "base-1", age=90, region="eu-west-1", source_ami_id="ami-src")
    same = ami("ami-same", "base-2", age=90, source_ami_id="ami-src")
    w1 = hits(src, [src, west, eu, same])["W1"]
    assert (w1.outcome, w1.message) == (
        "warn",
        "It was copied to eu-west-1 and us-west-2 (2 AMIs). The copies keep working, but this "
        "is their source.",
    )
    assert "W1" not in hits(src, [src, same])


def test_w1_blocks_when_configured():
    policy = POLICY.model_copy(update={"source_with_live_copies": "block"})
    src = ami("ami-src", "base-1", age=100)
    west = ami("ami-w", "base-1", age=90, region="us-west-2", source_ami_id="ami-src")
    assert hits(src, [src, west], policy=policy)["W1"].outcome == "block"
    assert outcome(RULES_BY_ID["W1"], policy) == "block"


def rds(id, age, db="orders-db", **kw):
    return res(id=id, type="rds_snapshot", name=id, created_at=days_ago(age), source_db_id=db,
               db_kind="instance", **kw)


def test_w2_newest_snapshot_of_gone_db_only():
    old, new = rds("snap-old", 200), rds("snap-new", 100)
    assert hits(new, [old, new])["W2"].message == (
        "Database orders-db is gone, and this is its newest snapshot. It may be the last copy."
    )
    assert hits(new, [old, new])["W2"].outcome == "warn"
    assert "W2" not in hits(old, [old, new])


def test_w2_silent_when_db_exists():
    old, new = rds("snap-old", 200), rds("snap-new", 100)
    db = Database("orders-db", "111111111111", "us-east-1", "instance")
    assert "W2" not in hits(new, [old, new], [db])


def test_w2_blocks_when_configured():
    policy = POLICY.model_copy(update={"rds_last_copy": "block"})
    new = rds("snap-new", 100)
    assert hits(new, [new], policy=policy)["W2"].outcome == "block"


def test_w3_newest_snapshot_of_existing_volume_only():
    vol = res(id="vol-1", type="volume")
    old = res(id="snap-1", type="snapshot", created_at=days_ago(200), source_volume_id="vol-1")
    new = res(id="snap-2", type="snapshot", created_at=days_ago(100), source_volume_id="vol-1")
    assert hits(new, [vol, old, new])["W3"].message == (
        "It is the newest snapshot of vol-1, which still exists."
    )
    assert "W3" not in hits(old, [vol, old, new])
    assert "W3" not in hits(new, [old, new])  # the volume is gone


def test_w5_accounts_and_public():
    shared = rds("snap-1", 100, shared_with=["222222222222", "333333333333"])
    assert hits(shared, [])["W5"].message == (
        "Shared with 222222222222 and 333333333333. They lose access to it."
    )
    assert hits(rds("snap-2", 100, shared_with=["all"]), [])["W5"].message == "It is public."
    assert "W5" not in hits(rds("snap-3", 100), [])


def test_explain_renders_live_values():
    policy = POLICY.model_copy(update={"keep_name_patterns": ["^golden-"]})
    assert "3 newest" in explain(RULES_BY_ID["R6"], POLICY)
    assert "none configured" in explain(RULES_BY_ID["R7"], POLICY)
    assert "^golden-" in explain(RULES_BY_ID["R7"], policy)


def test_w2_silent_when_the_database_check_failed():
    # A failed database check makes the snapshot unknown (R2); W2 mustn't claim the DB is gone.
    new = rds("snap-new", 100, status="unknown", status_reason="Couldn't list databases.")
    assert "W2" not in hits(new, [new])
