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
    assert [r["id"] for r in defs["rules"]] == ["R1", "R2", "R3", "R4", "R5", "W4"]


def test_r4_protected_tag_key_is_case_insensitive():
    assert ids(res(tags={"Owner": "me", "Retain": "true"})) == {("R4", "block")}
