"""Load and validate janitor.yaml. Invalid config stops startup."""

import os
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ResourceType = Literal["ami", "snapshot", "volume", "rds_snapshot"]
ACCOUNT_ID = re.compile(r"^\d{12}$")
ROLE_NAME = re.compile(r"^[\w+=,.@-]{1,64}$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Admin(_Strict):
    """The account that owns the AMIs and shares them with the other accounts."""

    account: str
    name: str = "admin"
    profile: str = ""  # needs role_arn and source_profile; required in AWS mode
    regions: list[str] = Field(min_length=1)

    @field_validator("account")
    @classmethod
    def _account_id(cls, account: str) -> str:
        if not ACCOUNT_ID.match(account):
            raise ValueError(f"admin account {account!r} must be 12 digits")
        return account


class AccountName(_Strict):
    name: str
    role: str = ""  # overrides member_role for this account
    profile: str = ""  # an AWS profile for this account: its role_arn and role_session_name win
    regions: list[str] | None = Field(
        None, min_length=1
    )  # where it has resources; default: admin's

    @field_validator("role")
    @classmethod
    def _role_name(cls, role: str) -> str:
        if role and not ROLE_NAME.match(role):
            raise ValueError(f"role {role!r} isn't a valid IAM role name")
        return role


class Policy(_Strict):
    orphan_after_days: int = Field(90, ge=1)
    min_age_days: int = Field(30, ge=0)
    protected_tags: dict[str, str] = Field(default_factory=dict)
    typed_confirm_min_items: int = Field(10, ge=1)

    @field_validator("protected_tags", mode="before")
    @classmethod
    def _tag_values(cls, tags: object) -> object:
        """YAML reads an unquoted `true` as a boolean; an empty value would protect nothing."""
        if not isinstance(tags, dict):
            return tags  # let pydantic report the type error
        clean = {}
        for key, value in tags.items():
            if isinstance(value, bool):
                value = str(value).lower()
            if value is None or not str(value).strip() or not str(key).strip():
                raise ValueError(f'protected tag {key!r} needs a value, for example retain: "true"')
            clean[str(key)] = str(value)
        return clean


class Pricing(_Strict):
    snapshot_gb_month: float = 0.05
    snapshot_archive_gb_month: float = 0.0125
    rds_snapshot_gb_month: float = 0.095
    volume_gb_month: dict[str, float] = Field(default_factory=lambda: {"gp3": 0.08})


class Scan(_Strict):
    concurrency: int = Field(8, ge=1, le=32)


class DeploymentTags(_Strict):
    """The tags a deploy tool puts on its ASGs, ECS services, and task definitions.

    For the lists, the first tag present wins. Only ASGs carrying `state` are deployments.
    """

    app: list[str] = Field(default_factory=lambda: ["role", "app"], min_length=1)
    env: list[str] = Field(default_factory=lambda: ["env"], min_length=1)
    version: list[str] = Field(default_factory=lambda: ["version"], min_length=1)
    state: str = Field("deploy-state", min_length=1)
    deployment_id: str = "deployment-id"


class Deployments(_Strict):
    tags: DeploymentTags = Field(default_factory=DeploymentTags)


class ConfigError(ValueError):
    """janitor.yaml can't be used; the message says why and what to change."""


OLD_LAYOUT = (
    "janitor.yaml uses the old layout (owner, and accounts with profile and owns). Move to "
    "admin, member_role, and accounts names: see config/janitor.example.yaml."
)


class Config(_Strict):
    provider: Literal["mock", "aws"] = "mock"
    admin: Admin
    member_role: str = ""  # the role assumed in every other account, from the same source login
    accounts: dict[str, AccountName] = Field(default_factory=dict)  # display names; always scanned
    # Never contacted, and AMIs shared with them aren't held back by them (rule W7 warns instead).
    ignore_accounts: list[str] = Field(default_factory=list)
    policy: Policy = Field(default_factory=Policy)
    pricing: Pricing = Field(default_factory=Pricing)
    scan: Scan = Field(default_factory=Scan)
    deployments: Deployments = Field(default_factory=Deployments)

    @model_validator(mode="before")
    @classmethod
    def _old_layout(cls, data: object) -> object:
        if isinstance(data, dict) and "owner" in data:
            raise ValueError(OLD_LAYOUT)
        return data

    @field_validator("member_role")
    @classmethod
    def _role_name(cls, role: str) -> str:
        if role and not ROLE_NAME.match(role):
            raise ValueError(f"member_role {role!r} isn't a valid IAM role name")
        return role

    @field_validator("accounts")
    @classmethod
    def _account_ids(cls, accounts: dict[str, AccountName]) -> dict[str, AccountName]:
        for account_id in accounts:
            if not ACCOUNT_ID.match(account_id):
                raise ValueError(f"account ID {account_id!r} must be 12 digits")
        return accounts

    @field_validator("ignore_accounts")
    @classmethod
    def _ignored_ids(cls, ignored: list[str]) -> list[str]:
        for account_id in ignored:
            if not ACCOUNT_ID.match(account_id):
                raise ValueError(f"ignored account ID {account_id!r} must be 12 digits")
        return ignored

    @model_validator(mode="after")
    def _ignore_is_consistent(self) -> "Config":
        for account_id in self.ignore_accounts:
            if account_id == self.admin.account:
                raise ValueError("the admin account can't be ignored")
            if account_id in self.accounts:
                raise ValueError(
                    f"account {self.accounts[account_id].name} is both listed and ignored; "
                    "remove it from one"
                )
        return self

    @property
    def regions(self) -> list[str]:
        """Every account is scanned in the admin's regions."""
        return self.admin.regions

    def regions_for(self, account_id: str) -> list[str]:
        """Where an account's resources are listed: its own regions, else the admin's."""
        if account_id == self.admin.account:
            return self.admin.regions
        account = self.accounts.get(account_id)
        return (account.regions if account else None) or self.admin.regions

    def role_for(self, account_id: str) -> str:
        """The role Janitor assumes in an account: its own override, else member_role."""
        account = self.accounts.get(account_id)
        return (account.role if account else "") or self.member_role

    def account_name(self, account_id: str) -> str:
        if account_id == self.admin.account:
            return self.admin.name
        account = self.accounts.get(account_id)
        return account.name if account else account_id


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that refuses a key repeated in one mapping (YAML would keep only the last)."""

    def construct_mapping(self, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                if isinstance(key, str) and ACCOUNT_ID.match(key):
                    raise ConfigError(
                        f"account {key} is listed twice in janitor.yaml (line {key_node.start_mark.line + 1}). "
                        "List each account once; one entry can cover several regions, for example "
                        "regions: [us-east-1, us-west-2]."
                    )
                raise ConfigError(
                    f"{key!r} appears twice in one section of janitor.yaml "
                    f"(line {key_node.start_mark.line + 1}). Keep one."
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def load_config(path: str | Path | None = None) -> Config:
    """Load `path` (default: $JANITOR_CONFIG, else config/janitor.yaml).

    If the file is missing, fall back to janitor.example.yaml in the same folder and force
    mock mode: without a real config there are no real accounts to read.
    """
    path = Path(path or os.environ.get("JANITOR_CONFIG") or "config/janitor.yaml")
    fallback = not path.exists()
    if fallback:
        example = path.with_name("janitor.example.yaml")
        if not example.exists():
            raise FileNotFoundError(f"No config at {path} and no example at {example}.")
        path = example
    data = yaml.load(path.read_text(), Loader=_UniqueKeyLoader) or {}
    if fallback:
        data["provider"] = "mock"
    elif provider := os.environ.get("JANITOR_PROVIDER"):
        data["provider"] = provider
    if isinstance(data, dict) and "owner" in data:
        raise ConfigError(f"{path}: {OLD_LAYOUT}")  # plain message: don't echo the file back
    return Config.model_validate(data)
