import pytest
from helpers import NOW, days_ago

from janitor.config import Policy
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
    assert [r["id"] for r in defs["rules"]] == ["R1", "R2", "R3", "R4", "R5", "W4", "W6", "W7"]


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
