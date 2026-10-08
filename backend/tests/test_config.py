import pytest
import yaml
from helpers import EXAMPLE
from pydantic import ValidationError

from janitor.config import ConfigError, load_config


def test_example_config_loads():
    config = load_config(EXAMPLE)
    assert config.provider == "mock"
    assert (config.admin.account, config.admin.name) == ("111111111111", "tools")
    assert config.regions == ["us-east-1", "us-west-2", "eu-west-1"]
    assert config.member_role == "example-janitor-read"
    assert config.account_name("111111111111") == "tools"
    assert config.account_name("222222222222") == "dev"
    assert config.account_name("444444444444") == "444444444444"  # discovered, unnamed
    assert [a.name for a in config.accounts.values()] == ["sbx", "dev", "uat", "qas", "prd"]
    assert config.policy.protected_tags == {"retain": "true", "janitor:keep": "true"}


def test_old_layout_gets_a_migration_message(tmp_path):
    path = tmp_path / "janitor.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "owner": {"account": "111111111111", "regions": ["us-east-1"]},
                "accounts": {"111111111111": {"name": "tools", "profile": "p", "owns": ["ami"]}},
            }
        )
    )
    with pytest.raises(ConfigError, match="uses the old layout") as error:
        load_config(path)
    assert "input_value" not in str(error.value)  # no echo of the file's contents


def test_missing_config_falls_back_to_example_in_mock_mode(tmp_path, monkeypatch):
    (tmp_path / "janitor.example.yaml").write_text(
        EXAMPLE.read_text().replace("provider: mock", "provider: aws")
    )
    monkeypatch.setenv("JANITOR_PROVIDER", "aws")
    assert load_config(tmp_path / "janitor.yaml").provider == "mock"


def test_env_overrides_provider(tmp_path, monkeypatch):
    path = tmp_path / "janitor.yaml"
    path.write_text(EXAMPLE.read_text())
    monkeypatch.setenv("JANITOR_PROVIDER", "aws")
    assert load_config(path).provider == "aws"


def test_missing_config_and_example_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="No config"):
        load_config(tmp_path / "janitor.yaml")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["admin"].update(account="12345"), "12 digits"),
        (lambda d: d["accounts"].update({"12345": {"name": "x"}}), "12 digits"),
        (lambda d: d["policy"].update(typo_field=1), "Extra inputs"),
        (lambda d: d.update(member_role="bad role!"), "member_role"),
        (lambda d: d["admin"].update(regions=[]), "regions"),
    ],
)
def test_invalid_config_is_rejected(tmp_path, change, message):
    data = yaml.safe_load(EXAMPLE.read_text())
    change(data)
    path = tmp_path / "janitor.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValidationError, match=message):
        load_config(path)


def test_protected_tag_values_accept_yaml_booleans(tmp_path):
    data = yaml.safe_load(EXAMPLE.read_text())
    data["policy"]["protected_tags"] = {"retain": True}
    path = tmp_path / "janitor.yaml"
    path.write_text(yaml.safe_dump(data))  # dumps as an unquoted `true`
    assert load_config(path).policy.protected_tags == {"retain": "true"}


@pytest.mark.parametrize("value", ["", "  ", None])
def test_protected_tag_needs_a_value(tmp_path, value):
    data = yaml.safe_load(EXAMPLE.read_text())
    data["policy"]["protected_tags"] = {"retain": value}
    path = tmp_path / "janitor.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValidationError, match="needs a value"):
        load_config(path)


def _variant(tmp_path, change):
    data = yaml.safe_load(EXAMPLE.read_text())
    change(data)
    path = tmp_path / "janitor.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def test_scan_concurrency_defaults_and_bounds(tmp_path):
    assert load_config(EXAMPLE).scan.concurrency == 8
    for bad in (0, 33):
        path = _variant(tmp_path, lambda d, bad=bad: d.update(scan={"concurrency": bad}))
        with pytest.raises(ValidationError):
            load_config(path)


def test_an_account_can_override_the_member_role(tmp_path):
    def change(d):
        d["accounts"]["555555555555"]["role"] = "example-other-read"

    config = load_config(_variant(tmp_path, change))
    assert config.role_for("555555555555") == "example-other-read"
    assert config.role_for("222222222222") == "example-janitor-read"  # the default
    assert config.role_for("444444444444") == "example-janitor-read"  # discovered, unnamed
    bad = _variant(tmp_path, lambda d: d["accounts"]["555555555555"].update(role="bad role!"))
    with pytest.raises(ValidationError, match="role"):
        load_config(bad)


def test_an_account_can_name_its_profile(tmp_path):
    config = load_config(
        _variant(tmp_path, lambda d: d["accounts"]["222222222222"].update(profile="example-dev"))
    )
    assert config.accounts["222222222222"].profile == "example-dev"


def test_an_account_can_list_its_own_regions(tmp_path):
    config = load_config(
        _variant(tmp_path, lambda d: d["accounts"]["333333333333"].update(regions=["eu-west-1"]))
    )
    assert config.regions_for("333333333333") == ["eu-west-1"]
    assert config.regions_for("222222222222") == config.regions  # default: the admin's
    empty = _variant(tmp_path, lambda d: d["accounts"]["333333333333"].update(regions=[]))
    with pytest.raises(ValidationError, match="regions"):
        load_config(empty)


def test_ignore_accounts(tmp_path):
    config = load_config(_variant(tmp_path, lambda d: d.update(ignore_accounts=["444444444444"])))
    assert config.ignore_accounts == ["444444444444"]
    for bad, message in (
        (["12345"], "12 digits"),
        (["111111111111"], "admin"),
        (["222222222222"], "both listed and ignored"),
    ):
        path = _variant(tmp_path, lambda d, bad=bad: d.update(ignore_accounts=bad))
        with pytest.raises(ValidationError, match=message):
            load_config(path)


def test_an_account_listed_twice_is_an_error_not_a_silent_overwrite(tmp_path):
    # YAML keeps only the last of two equal keys, so one entry would quietly vanish.
    path = tmp_path / "janitor.yaml"
    text = EXAMPLE.read_text().replace(
        '  "222222222222": { name: dev }\n',
        '  "222222222222": { name: dev }\n  "222222222222": { name: dev-dr, regions: [us-west-2] }\n',
    )
    assert text.count('"222222222222"') == 2
    path.write_text(text)
    with pytest.raises(ConfigError, match="222222222222 is listed twice") as error:
        load_config(path)
    assert "one entry can cover several regions" in str(error.value)


def test_deployment_tags_default_to_the_deploy_tool_tags():
    tags = load_config(EXAMPLE).deployments.tags
    assert tags.app == ["role", "app"]
    assert tags.env == ["env"]
    assert tags.version == ["version"]
    assert (tags.state, tags.deployment_id) == ("deploy-state", "deployment-id")


def test_deployment_tags_can_be_renamed(tmp_path):
    data = yaml.safe_load(EXAMPLE.read_text())
    data["deployments"] = {"tags": {"app": ["service"], "state": "stage"}}
    path = tmp_path / "janitor.yaml"
    path.write_text(yaml.safe_dump(data))
    tags = load_config(path).deployments.tags
    assert (tags.app, tags.state, tags.env) == (["service"], "stage", ["env"])


def test_deployment_tag_lists_cant_be_empty(tmp_path):
    data = yaml.safe_load(EXAMPLE.read_text())
    data["deployments"] = {"tags": {"version": []}}
    path = tmp_path / "janitor.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValidationError):
        load_config(path)


def test_policy_defaults_for_3b():
    policy = load_config(EXAMPLE).policy
    assert policy.keep_newest_per_name_group == 3
    assert policy.keep_name_patterns == []
    assert (policy.source_with_live_copies, policy.rds_last_copy) == ("warn", "warn")
    assert policy.group_regex.match("ecs-gpu-20260901").group("group") == "ecs-gpu"
    assert policy.group_regex.match("base-v1.2.3").group("group") == "base"


def test_bad_keep_pattern_is_rejected(tmp_path):
    path = _variant(tmp_path, lambda d: d["policy"].update(keep_name_patterns=["^ok", "(bad"]))
    with pytest.raises(ValidationError, match=r"keep_name_patterns: '\(bad' isn't a valid"):
        load_config(path)


def test_keep_patterns_compile_once(tmp_path):
    path = _variant(tmp_path, lambda d: d["policy"].update(keep_name_patterns=["^golden-"]))
    policy = load_config(path).policy
    assert [p.pattern for p in policy.keep_regexes] == ["^golden-"]
    assert policy.keep_regexes is policy.keep_regexes


@pytest.mark.parametrize("pattern", ["^(.+)-\\d+$", "(?P<group"])
def test_group_pattern_needs_group(tmp_path, pattern):
    path = _variant(tmp_path, lambda d: d["policy"].update(ami_name_group_pattern=pattern))
    with pytest.raises(ValidationError, match="ami_name_group_pattern"):
        load_config(path)


@pytest.mark.parametrize("field", ["source_with_live_copies", "rds_last_copy"])
def test_outcome_accepts_warn_or_block_only(tmp_path, field):
    assert load_config(_variant(tmp_path, lambda d: d["policy"].update({field: "block"})))
    with pytest.raises(ValidationError, match=field):
        load_config(_variant(tmp_path, lambda d: d["policy"].update({field: "pass"})))


def test_keep_newest_is_at_least_one(tmp_path):
    path = _variant(tmp_path, lambda d: d["policy"].update(keep_newest_per_name_group=0))
    with pytest.raises(ValidationError, match="keep_newest_per_name_group"):
        load_config(path)
