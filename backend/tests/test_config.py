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
