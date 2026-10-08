"""Which checks a scan runs: per-account regions, and usage wherever an AMI is shared."""

from helpers import DEV, PROD, TOOLS, days_ago

from janitor.config import Config
from janitor.models import Resource, Share
from janitor.providers.base import first_phase, second_phase


def config(**accounts) -> Config:
    return Config.model_validate(
        {
            "admin": {
                "account": TOOLS,
                "profile": "example-tools",
                "regions": ["us-east-1", "us-west-2", "eu-west-1"],
            },
            "member_role": "example-janitor-read",
            "accounts": accounts or {DEV: {"name": "dev"}},
        }
    )


def ami(region: str) -> Resource:
    return Resource(f"ami-{region}", "ami", TOOLS, region, "base", days_ago(10))


def test_accounts_default_to_the_admin_regions():
    c = config()
    assert c.regions_for(DEV) == ["us-east-1", "us-west-2", "eu-west-1"]
    assert {r for _, r, _ in first_phase(c)} == {"us-east-1", "us-west-2", "eu-west-1"}


def test_an_account_lists_its_resources_only_in_its_own_regions():
    c = config(**{PROD: {"name": "prd-eu", "regions": ["eu-west-1", "eu-central-1"]}})
    plan = second_phase(c, [PROD], [], [])
    lists = {(r, k) for a, r, k in plan if a == PROD and k != "usage"}
    assert {r for r, _ in lists} == {"eu-west-1", "eu-central-1"}
    assert {k for _, k in lists} == {"snapshot", "volume", "rds_snapshot", "database", "ecs"}


def test_usage_is_also_checked_where_an_ami_is_shared_with_the_account():
    # Launch permissions are region-scoped: an AMI in us-east-1 shared with an EU-only account
    # can be launched there, so "nothing uses it" needs a usage check in us-east-1 too.
    c = config(**{PROD: {"name": "prd-eu", "regions": ["eu-west-1"]}})
    plan = second_phase(c, [PROD], [ami("us-east-1")], [Share("ami-us-east-1", "account", PROD)])
    usage = {r for a, r, k in plan if a == PROD and k == "usage"}
    assert usage == {"eu-west-1", "us-east-1"}
    assert ("us-east-1", "volume") not in {(r, k) for a, r, k in plan if a == PROD}


def test_admin_usage_and_ecs_run_in_every_admin_region():
    plan = second_phase(config(), [], [], [])
    regions = ("us-east-1", "us-west-2", "eu-west-1")
    assert plan == [(TOOLS, r, k) for r in regions for k in ("usage", "ecs")]


def test_ecs_runs_only_in_an_accounts_own_regions():
    # ECS services are deployments, not AMI users: no ECS check where an AMI is merely shared.
    c = config(**{PROD: {"name": "prd-eu", "regions": ["eu-west-1"]}})
    plan = second_phase(c, [PROD], [ami("us-east-1")], [Share("ami-us-east-1", "account", PROD)])
    assert {r for a, r, k in plan if a == PROD and k == "ecs"} == {"eu-west-1"}


def test_ignored_accounts_are_never_contacted():
    from janitor.providers.base import member_accounts

    c = Config.model_validate(config().model_dump() | {"ignore_accounts": ["444444444444"]})
    shares = [Share("ami-x", "account", "444444444444"), Share("ami-x", "account", PROD)]
    assert member_accounts(c, shares) == sorted([DEV, PROD])
