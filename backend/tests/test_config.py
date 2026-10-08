import pytest
import yaml
from helpers import EXAMPLE
from pydantic import ValidationError

from janitor.config import load_config


def test_example_config_loads():
    config = load_config(EXAMPLE)
    assert config.provider == "mock"
    assert config.owner.account == "111111111111"
    assert config.account_name("222222222222") == "dev"
    assert config.account_name("444444444444") == "444444444444"
    assert config.regions_for("333333333333") == ["us-east-1", "us-west-2", "eu-west-1"]
    assert [a.name for a in config.accounts.values()] == [
        "tools",
        "sbx",
        "dev",
        "uat",
        "qas",
        "prd",
    ]
    assert config.regions_for("222222222222") == ["us-east-1", "us-west-2", "eu-west-1"]
    assert config.policy.protected_tags == {"retain": "true", "janitor:keep": "true"}


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
        (lambda d: d["owner"].update(account="999999999999"), "owner account"),
        (lambda d: d["accounts"]["222222222222"]["owns"].append("ami"), "only the owner"),
        (lambda d: d["accounts"].update({"12345": {"name": "x", "profile": "x"}}), "12 digits"),
        (lambda d: d["policy"].update(typo_field=1), "Extra inputs"),
        (lambda d: d["accounts"]["222222222222"]["owns"].append("bucket"), "owns"),
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


def test_snapshot_owner_must_also_own_volumes(tmp_path):
    path = _variant(
        tmp_path, lambda d: d["accounts"]["222222222222"].update(owns=["snapshot", "rds_snapshot"])
    )
    with pytest.raises(ValidationError, match="must also own volume"):
        load_config(path)
