# Phase 3 fixes (hub, in use, diagram) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reach every account through the admin hub, count only instances as use (templates warn), and focus the diagram on an AMI's own links.

**Architecture:** New config layout (`admin`, `member_role`, `accounts` names). `session.py` assumes admin then members. The scan plan discovers accounts from launch permissions. The linker splits instances from references (`Resource.referenced_by` + rule W6). `graph.py` walks only downstream from AMIs and hangs usage under account nodes.

**Tech Stack:** Python 3.12, boto3, moto, FastAPI, SQLite; React 19 + Vitest.

**Spec:** [`docs/superpowers/specs/2026-10-08-phase-3-hub-and-usage-design.md`](../specs/2026-10-08-phase-3-hub-and-usage-design.md)

**Execution note:** user's standing preference: no review stop; native execution; final reviewer on opus.

## Global Constraints

- No new dependencies.
- Public repo: fake IDs from the allowlist only; profiles and roles named `example-*`.
- Copy rules (base spec §12).
- Branch `phase-3`; never push without asking.

## Review Focus

1. An AMI shared with an account that appears only in its launch permissions (not in config) must be scanned through the hub, and if that hub hop fails, the AMI is unknown, never orphaned → Task 2 test.
2. An AMI used by a stopped instance in a member account stays in use → Task 3 test.
3. The diagram for an AMI whose source has many other copies shows none of them → Task 4 test.
4. A user's old-layout `janitor.yaml` gives a clear migration message, not a pydantic dump → Task 1 test.
5. Accounts discovered during a scan appear in the account filter → Task 5 test.

---

### Task 1: Config layout and hub sessions

**Files:** `backend/janitor/config.py`, `backend/janitor/providers/session.py`, `config/janitor.example.yaml`, every `owner`/`owns`/`regions_for` call site (`linker.py`, `providers/base.py`, `providers/aws.py`, `main.py`, `graph.py`, `plans.py`), tests `test_config.py`, `test_session.py`, `aws_helpers.py`.

**Interfaces (produced):**
- `config.Admin(account, name="admin", profile, regions)`, `config.AccountName(name)`
- `Config(provider, admin, member_role: str = "", accounts: dict[str, AccountName] = {}, policy, pricing, scan)`
- `Config.account_name(id)`, `Config.regions` (property)
- `session.ADMIN_POLICY(member_role) -> dict`, `session.SESSION_POLICY` (unchanged)
- `session.assume_admin(config) -> Session`
- `session.assume_member(config, admin: Session, account_id) -> Session`
- `session.check_profiles(config)`, which checks the admin profile and `member_role`
- `aws_helpers.write_aws_config(tmp_path, monkeypatch, admin: str = TOOLS)` writes `example-base` + `example-tools` only.

**Steps:**
1. Failing tests:
   - Config:
     - the new example config loads (`admin.account`, `regions`, `account_name` for admin, a named account, and an unnamed account);
     - an old-layout dict is rejected with "uses the old layout";
     - a bad `member_role` like `"bad role!"` is rejected.
   - Session (moto):
     - `assume_admin` sends AssumeRole with `json.loads(Policy) == ADMIN_POLICY("example-janitor-read")`;
     - `assume_member` sends a second AssumeRole to `arn:aws:iam::222222222222:role/example-janitor-read` with `SESSION_POLICY`;
     - a member session's `delete_snapshot` raises `ReadOnlyViolation`;
     - `check_profiles` names a missing admin profile and an empty `member_role`.
2. Implement, then update every call site so the existing suite runs again. In mock mode the example config is used.
3. Run `make test` and confirm it's green. Commit `feat(config): admin hub layout and member sessions`.

### Task 2: Discovery and the hub scan

**Files:** `backend/janitor/providers/base.py`, `providers/aws.py`, `providers/mock.py`, `scanner.py` (`segment_message`), `scripts/make_seed.py`, `fixtures/seed.json`, tests `test_aws_provider.py`, `test_mock_provider.py`, `test_scanner.py`.

**Interfaces:**
- `base.ADMIN_KINDS = ("ami", "snapshot", "volume", "usage")`, `base.MEMBER_KINDS = ("snapshot", "volume", "rds_snapshot", "database", "usage")`
- `base.admin_plan(config) -> list[(account, region, kind)]`
- `base.member_accounts(config, shares) -> list[str]`
- `base.member_plan(config, accounts) -> list[...]`
- Seed key `unreachable: [account]`.
- `MockProvider` reports failed checks for those accounts: `error_kind="denied"`, `error="sts:AssumeRole"`.
- `segment_message` special-cases `error == "sts:AssumeRole"` ("Janitor can't assume <role> in <name>…").

**Steps:**
1. Failing tests:
   - moto:
     - an AMI shared with dev (dev not in config) gets dev scanned, and dev's instance shows as usage;
     - a member whose `member_role` assume fails fails only its own checks;
     - the admin's checks are `ami`/`snapshot`/`volume`/`usage` per region.
   - Mock:
     - the unreachable account's checks fail with `sts:AssumeRole`;
     - `partner-export` is unknown;
     - the scan is partial.
   - Scanner: the AssumeRole message has no region.
2. Implement; regenerate the seed (`make seed`). Run `make test` and confirm it's green (adjust tests that asserted an `ok` mock scan to `partial`, and record a ledger ruling). Commit `feat(aws): discover accounts from launch permissions and scan them through the admin hub`.

### Task 3: Instances are use; templates are references (W6)

**Files:** `backend/janitor/models.py` (`referenced_by`), `store.py` (column, `SCHEMA_VERSION = 4`), `linker.py`, `rules.py`, `definitions.py`, tests `test_linker.py`, `test_rules.py`, `test_scanner.py`.

**Interfaces:**
- `Resource.referenced_by: str | None`
- `LinkContext.scanned` comes from usage segments (`None` when there are no segments)
- `rules.W6`

**Steps:**
1. Failing tests:
   - linker:
     - a launch-template-only AMI (100 days) is `orphaned`, and its `referenced_by` names the template and account;
     - a stopped member instance makes it `in_use`;
     - a launch-permission account with no usage segment, when segments exist, makes it `unknown`.
   - rules: W6 warns with the `referenced_by` text.
   - scanner (mock): the `app-web` 10-day AMI is `idle` with W6.
2. Implement. Run `make test` and confirm it's green. Commit `feat(linker): only instances make an AMI in use; templates add a Referenced warning`.

### Task 4: Focused diagram

**Files:** `backend/janitor/graph.py`, `backend/janitor/plans.py` (share impact `scanned`), `frontend/src/components/LinkageDiagram.tsx`, `frontend/src/components/diagram.css`, tests `test_graph.py`, `test_api.py`.

**Steps:**
1. Failing tests in `test_graph.py`, built on a small store:
   - the root AMI's graph has no source AMI and no sibling copies;
   - an instance in dev hangs under the `account:<ami>:<dev>` node via `used_by`;
   - a launch template hangs under its account via `references`;
   - three shared accounts with no usage collapse to one "3 accounts · not used" node;
   - an unreachable account node is labelled "couldn't check";
   - a downstream copy expands only to its usage;
   - the `used_by` summary separates instances from "Also named by".
2. Implement it, plus a frontend label and dashed style for `references`. Run `make test` and confirm it's green. Commit `feat(graph): an AMI's own links only, usage grouped by account`.

### Task 5: Meta accounts, docs, verify

**Files:** `backend/janitor/main.py` (meta accounts), `frontend/src/api.ts` (`Meta.accounts` without `owns`), `README.md`, `docs/HANDOFF.md`, tests `test_api.py`.

**Steps:**
1. Failing test: after an injected scan whose segments include account 222222222222, which isn't listed in config, `/api/meta.accounts` contains it, with its ID as its name.
2. Implement. Update the README AWS section and HANDOFF for the new layout. Run `make test` and confirm it's green, then `npm run build`. Do a browser check in mock mode: the AMI diagram for `base-linux` 20d shows account nodes with instances and no sibling AMIs.
3. Commit `feat(api): discovered accounts in meta; docs for the hub layout`.
