"""Load and validate janitor.yaml. Invalid config stops startup."""

import os
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ResourceType = Literal["ami", "snapshot", "volume", "rds_snapshot"]
ACCOUNT_ID = re.compile(r"^\d{12}$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Owner(_Strict):
    account: str
    regions: list[str] = Field(min_length=1)


class Account(_Strict):
    name: str
    profile: str
    owns: list[ResourceType] = Field(default_factory=list)
    regions: list[str] | None = None


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


class Config(_Strict):
    provider: Literal["mock", "aws"] = "mock"
    owner: Owner
    accounts: dict[str, Account]
    policy: Policy = Field(default_factory=Policy)
    pricing: Pricing = Field(default_factory=Pricing)

    @field_validator("accounts")
    @classmethod
    def _account_ids(cls, accounts: dict[str, Account]) -> dict[str, Account]:
        for account_id in accounts:
            if not ACCOUNT_ID.match(account_id):
                raise ValueError(f"account ID {account_id!r} must be 12 digits")
        return accounts

    @model_validator(mode="after")
    def _owner_rules(self) -> "Config":
        if self.owner.account not in self.accounts:
            raise ValueError(f"owner account {self.owner.account} must be listed under accounts")
        for account_id, account in self.accounts.items():
            if "ami" in account.owns and account_id != self.owner.account:
                raise ValueError(f"only the owner account may own ami (found in {account.name})")
        return self

    def account_name(self, account_id: str) -> str:
        account = self.accounts.get(account_id)
        return account.name if account else account_id

    def regions_for(self, account_id: str) -> list[str]:
        return self.accounts[account_id].regions or self.owner.regions


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
    data = yaml.safe_load(path.read_text()) or {}
    if fallback:
        data["provider"] = "mock"
    elif provider := os.environ.get("JANITOR_PROVIDER"):
        data["provider"] = provider
    return Config.model_validate(data)
