# Phase 3 (AWS provider) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Read real AWS accounts through a read-only `AwsProvider` with three locks, segment-level failure handling, `unknown` from failures, and a live re-check on simulate.

**Architecture:** `providers/session.py` (profile → AssumeRole with a session policy → guarded session), `providers/guard.py` (botocore before-call hook), `providers/normalize.py` (pure raw-AWS → records), `providers/aws.py` (segments over a thread pool). The linker gains failure context; the scanner gains `partial`; the store gains `scan_segments`.

**Tech Stack:** Python 3.12, boto3 1.43.108, moto 5.2.3, FastAPI, SQLite; React 19 + Vitest for the UI bits.

**Spec:** [`docs/superpowers/specs/2026-10-08-phase-3-aws-provider-design.md`](../specs/2026-10-08-phase-3-aws-provider-design.md)

**Execution note:** user's standing preference: no review stop; the plan pins tests, interfaces, files, and expected results, and code is written during execution. Native execution, final reviewer on opus.

## Global Constraints

- Dependencies: `boto3==1.43.108`; dev `moto[ec2,rds,autoscaling,sts]==5.2.3`. Nothing else.
- Session policy actions exactly `ec2:Describe*`, `autoscaling:Describe*`, `rds:Describe*`; session name `janitor-readonly`; `DurationSeconds=3600`.
- Guard allows operation names starting `Describe`, `List`, `Get`; the STS client additionally allows `AssumeRole` only.
- Public repo: test fixtures use fake IDs from the leak-check allowlist (`111111111111`, `222222222222`, `333333333333`, `555555555555`, `666666666666`, `777777777777`); profiles named `example-*`.
- Copy rules (base spec §12): sentence case, buttons start with a verb, no "successfully"/"please"/"!", errors say what happened then what to do.
- Work on branch `phase-3`; never push without asking.

## Review Focus

1. Assume-role fails for one account (expired MFA) → only that account's segments fail; AMIs shared with it become unknown; the scan is `partial`, not `failed` → test in Task 3.
2. An AMI shared with a configured account that isn't scanned in the AMI's region (per-account `regions`) → unknown, never orphaned → test in Task 4.
3. A snapshot in a region where the owner's AMI list failed → unknown, never orphaned/deletable → test in Task 4.
4. Raw shapes with missing optional fields (no `Name` tag, no `SnapshotCreateTime`, instance-store AMI with no EBS mappings, no `Tags` key) → no crash, sensible defaults → tests in Task 2.
5. A newest scan that failed outright must not blank the UI: readers keep the last ok/partial scan, Overview says the last scan failed → tests in Tasks 4 and 6.

---

### Task 1: Dependencies, config, session, guard (locks 2 and 3)

**Files:** `backend/pyproject.toml`, `backend/janitor/config.py`, `config/janitor.example.yaml`, create `backend/janitor/providers/guard.py`, `backend/janitor/providers/session.py`, tests `backend/tests/test_config.py`, `backend/tests/test_session.py`, `backend/tests/aws_helpers.py`.

**Interfaces (produced):**
- `config.Scan(concurrency: int = 8, ge=1, le=32)`; `Config.scan: Scan`.
- `guard.ReadOnlyViolation(Exception)`; `guard.ALLOWED_PREFIXES = ("Describe", "List", "Get")`; `guard.install(session: boto3.Session, extra: frozenset[str] = frozenset()) -> None`.
- `session.SESSION_POLICY: dict`; `session.ProfileError(Exception)`; `session.check_profiles(config) -> None` (raises one `ProfileError` naming every bad profile); `session.assume(config, account_id) -> boto3.Session` (guarded, role assumed with policy); `session.CLIENT_CONFIG` (botocore `Config(retries={"mode": "adaptive", "max_attempts": 10})`).
- `aws_helpers.py`: `write_aws_config(tmp_path, monkeypatch, accounts: dict[str, str]) -> None` writes `[profile example-base]` with static fake keys and `[profile example-<name>] role_arn=arn:aws:iam::<id>:role/janitor-read, source_profile=example-base`, sets `AWS_CONFIG_FILE`, `AWS_SHARED_CREDENTIALS_FILE`, and dummy `AWS_DEFAULT_REGION`.

**Steps:**
1. `uv pip install --python .venv/bin/python boto3==1.43.108 "moto[ec2,rds,autoscaling,sts]==5.2.3"`; add both pins to `pyproject.toml`. Expected: installs.
2. Failing tests:
   - `test_config.py`: `scan.concurrency` defaults to 8, rejects 0 and 33; an account owning `snapshot` without `volume` fails validation with a message containing "must also own volume".
   - `test_session.py` (moto `mock_aws`):
     - `check_profiles` raises naming both a missing profile and one without `role_arn`;
     - `assume` sends AssumeRole with `RoleSessionName == "janitor-readonly"`, `DurationSeconds == 3600`, and `json.loads(Policy) == SESSION_POLICY` (captured with a `before-call.sts.AssumeRole` handler);
     - a client from the assumed session calling `delete_snapshot` raises `ReadOnlyViolation` and the snapshot still exists (checked through an unguarded moto client);
     - `describe_snapshots` through the guarded session works.
   Run `.venv/bin/python -m pytest backend/tests/test_session.py backend/tests/test_config.py -q` → FAIL (modules missing).
3. Implement. `assume` builds `boto3.Session(profile_name=source_profile)`, installs the guard with `extra={"AssumeRole"}`, calls STS, returns `boto3.Session(aws_access_key_id=…, region_name=owner's first region)` with the guard installed. Read profiles via `botocore.session.Session().full_config["profiles"]`. Add `scan:` to the example config.
4. Run → PASS; `make test` green. Commit `feat(aws): session policy and read-only guard`.

### Task 2: Normalization (pure)

**Files:** create `backend/janitor/providers/normalize.py`, `backend/tests/test_normalize.py`; modify `backend/janitor/models.py`.

**Interfaces (produced):**
- `models.Segment(account, region, kind, ok: bool, items: int = 0, error_kind: str = "", error: str = "", duration_ms: int = 0)`.
- `models.Unresolved(account, region, ref_type, ref_id, value)`.
- `models.Inventory` gains `segments: list[Segment] = field(default_factory=list)` and `unresolved: list[Unresolved] = field(default_factory=list)`.
- `normalize.image(raw, account, region) -> Resource`; `snapshot(raw, account, region) -> Resource`; `volume(raw, account, region) -> Resource`; `db_snapshot(raw, account, region, cluster: bool, now) -> Resource`; `shares(image_id, launch_permissions) -> list[Share]`; `instance_usage(reservations, account, region, ami_ids) -> list[Usage]`; `template_images(templates_versions) -> dict[(lt_id), list[(version_number, image_id)]]` helper; `asg_usage(groups, versions, account, region, ami_ids) -> (list[Usage], list[Unresolved])`; `template_usage(...)`; `launch_config_usage(...)`; `fill_copy_sources(resources) -> None`; `classify(exc, operation) -> (error_kind, message)`.

**Steps:**
1. Failing tests in `test_normalize.py`, using literal dicts shaped like real boto3 responses:
   - image: size sums EBS volumes; `snapshot_ids`; `SourceImageId` → `source_ami_id`; instance-store-only image → `size_gb` None, no snapshots; missing `Tags` OK.
   - snapshot: `Created by CreateImage(i-0123) for ami-0abc from vol-…` → `linked_ami_id="ami-0abc"`; `Copied for DestinationAmi ami-0new from SourceAmi ami-0src …` → `linked_ami_id="ami-0new"`; `vol-ffffffff` → `source_volume_id` None; `StorageTier="archive"`; `aws:dlm:lifecycle-policy-id` tag → `managed_by="dlm"`; AWS Backup description → `aws_backup`; no Name tag → name is the id.
   - volume: attachment → `attached_instance`; gp3 iops/throughput/encrypted.
   - db_snapshot: id is ARN, name the identifier, cluster flag sets `db_kind`; `automated` → `rds_automated`; `awsbackup` → `aws_backup`; no `SnapshotCreateTime` falls back to `OriginalSnapshotCreateTime`, then `now`.
   - shares: UserId/Group/OrganizationArn/OrganizationalUnitArn → account/group/org/ou.
   - fill_copy_sources: AMI without `SourceImageId` gets the source from its snapshot's copy description.
   - usage: terminated instances skipped; ASG pinned `$Latest`, `$Default`, explicit `"3"`, and `MixedInstancesPolicy` each resolve to the right version's image; any template's default and latest versions count; `resolve:ssm:/x` → `Unresolved`, not usage; images outside `ami_ids` dropped.
   - classify: `ExpiredToken` → expired; `UnauthorizedOperation` → denied with "ec2:DescribeImages" in the message; `RequestLimitExceeded` → throttled; `ReadOnlyViolation` → blocked; `NoCredentialsError` → expired; `ValueError("x")` → other.
   Run → FAIL.
2. Implement. Run → PASS; `make test` green. Commit `feat(aws): normalize raw AWS shapes into Janitor records`.

### Task 3: AwsProvider (lock 1, segments, moto end to end)

**Files:** create `backend/janitor/providers/aws.py`, `backend/tests/test_aws_provider.py`; modify `backend/janitor/providers/base.py`, `backend/janitor/providers/mock.py`.

**Interfaces:**
- Consumes: `session.assume`, `session.CLIENT_CONFIG`, `normalize.*`, `models.Segment`, `models.Unresolved`.
- Produces:
  - `CloudProvider.list_inventory(on_segment: Callable[[Segment], None] | None = None) -> Inventory`
  - `CloudProvider.recheck(items: list[dict]) -> dict[str, str]`
  - `AwsProvider(config, clock=None, page_size: int | None = None)` with `name = "aws"`
  - `aws.OPERATIONS: frozenset[str]`, every operation name the provider calls
  - `MockProvider` gains `recheck` → `{}` and emits one ok `Segment` per configured (account, region, kind) it would scan.

**Steps:**
1. Failing tests in `test_aws_provider.py` (moto `mock_aws`, `write_aws_config` with owner 111111111111 and dev 222222222222; resources created by assuming each account's role so moto keeps them per account):
   - **Full scan:**
     - An owner AMI in us-east-1 with a launch permission for dev comes back with an account `Share`.
     - A dev instance running that AMI gives a `Usage` with `ref_type="instance"`.
     - A snapshot copied with a `Copied for DestinationAmi` description gets `linked_ami_id`.
     - A dev volume is listed.
     - A dev RDS instance snapshot and a cluster snapshot are listed, along with their `Database` rows.
     - Every segment is ok.
   - **Pagination:** 7 snapshots with `page_size=3` all arrive.
   - **One account's role can't be assumed:** remove dev's `role_arn` target by pointing it at a profile whose source has no credentials. Every dev segment fails with `error_kind="expired"` or `"other"`. Owner segments are ok.
   - **Lock 1:** the public methods of `AwsProvider` are exactly `{"list_inventory", "recheck"}`, plus `name`.
   - **Operation set:** a recording `before-call` handler during the full scan sees only names in `aws.OPERATIONS`, and every name in `OPERATIONS` starts with an allowed prefix.
   - **Progress:** `on_segment` is called once per segment.
   Run → FAIL.
2. Implement the two-phase pool from the spec. A failed launch-permission read fails that region's `ami` segment. Usage pairs are the owner in all its regions, plus every configured account from account shares in the AMI's region when `config.regions_for(account)` contains it. Use paginators with `PaginationConfig={"PageSize": page_size}` when set. `recheck` is stubbed here (`{}`) and filled in Task 5.
3. Run → PASS. If moto lacks a paginator page size for some call, make a ledger ruling and test pagination on a call it supports. Run `make test` and confirm it's green. Commit `feat(aws): AwsProvider with scan segments`.

### Task 4: Failure-aware linker, partial scans, store and API

**Files:** `backend/janitor/linker.py`, `backend/janitor/scanner.py`, `backend/janitor/store.py`, `backend/janitor/main.py`, tests `test_linker.py`, `test_scanner.py`, `test_store.py`, `test_api.py`.

**Interfaces:**
- `LinkContext` gains `failed: set[tuple[str, str, str]] = field(default_factory=set)` (account, region, kind) and `scanned: set[tuple[str, str]] | None = None` (None = everything scanned; mock).
- `LinkContext.from_config(config, now, segments: list[Segment] = ())`. `scanned` comes from the config: every account × `regions_for(account)`.
- `Store`:
  - `SCHEMA_VERSION = 3`
  - `scan_segments(scan_id, account, region, kind, ok, items, error_kind, error, duration_ms)`
  - `scans.notes TEXT`
  - `add_segment(scan_id, seg)`, `segments(scan_id) -> list[dict]`, `set_notes(scan_id, notes: dict)`
  - `latest_scan()` reads status in (`ok`, `partial`)
- `create_app(settings=None, clock=None, provider: CloudProvider | None = None)`. With `config.provider == "aws"` and no injected provider it calls `check_profiles` and builds `AwsProvider`, and the startup scan runs through `scanner.start()`.
- API:
  - `GET /api/scans/latest` → `{scan, running, segments, progress: {done, failed}}`
  - `GET /api/overview` adds `segments_failed: [{account, account_name, region, kind, error_kind, message}]`, `unresolved: [...]`, and `newest_failed: {finished_at, message} | null`, set when the newest scan is `failed` and older data is shown.

**Steps:**
1. Failing tests:
   - `test_linker.py`:
     - An AMI shared with dev, with dev's `usage` segment failed in us-east-1, is `unknown` and its reason names dev and us-east-1. The same AMI with a dev usage row is still `in_use`.
     - An AMI shared with an account whose `regions` excludes the AMI's region is `unknown` ("doesn't scan").
     - A snapshot with no AMI backing, in a region where the owner's `ami` segment failed, is `unknown`.
     - A snapshot whose volume segment failed and whose source volume is missing is `unknown`.
     - A manual RDS snapshot whose `database` segment failed is `unknown`. An automated one is still `managed`.
   - `test_scanner.py`, using a fake provider that returns segments:
     - One failed segment gives scan status `partial`. `store.latest_scan()` returns it and `store.segments(id)` returns both segments.
     - All segments failed gives `failed`, and `latest_scan()` still returns the previous ok scan.
     - Unresolved references are stored in notes.
   - `test_store.py`: segments and notes round-trip.
   - `test_api.py`:
     - With an injected fake provider that has one failed segment, `/api/overview.segments_failed[0].message` contains "Refresh your MFA session", and `/api/scans/latest.progress == {"done": 2, "failed": 1}`.
     - Starting with `provider: aws` in config and a missing profile raises at `create_app`, and the message names the profile.
   Run → FAIL.
2. Implement. The scanner writes segments through `on_segment` as they finish. Status is `failed` if the inventory call raises or no segment is ok, `partial` if any segment failed, `ok` otherwise. The message for a segment comes from the spec's error-kind table and is built in one function, `scanner.segment_message(seg, config)`.
3. Run the tests, expect PASS, and confirm `make test` is green. Commit `feat(aws): unknown from failed checks, partial scans, segment API`.

### Task 5: Live re-check during simulate

**Files:** `backend/janitor/providers/aws.py` (`recheck`), `backend/janitor/plans.py`, `backend/janitor/main.py`, tests `test_aws_provider.py`, `test_api.py` (or `test_plans` cases inside it).

**Interfaces:**
- `plans.simulate(store, config, plan_id, confirmation, recheck: Callable[[list[dict]], dict[str, str]] = lambda items: {})`. `main` passes `provider.recheck`.
- `AwsProvider.recheck(items)`: items are plan item dicts (`id`, `type`, `account`, `region`). It returns `{id: reason}` using the spec's table.

**Steps:**
1. Failing tests:
   - `test_api.py` / plans:
     - A recheck stub returning `{ami_id: "Instance i-1 in dev now uses it."}` moves the AMI to `skipped` with that reason, and its backing snapshots are skipped with "Kept because … is now blocked." (the existing wording).
     - The audit entry records the skip.
   - `test_aws_provider.py` (moto):
     - A deleted volume gives "It no longer exists.", and an attached volume gives "It is now attached to i-…".
     - An AMI with a new dev instance gives "Instance i-… in dev now uses it."
     - An unchanged snapshot is absent from the result.
     - If AssumeRole fails, every item for that account gets "Janitor couldn't re-check it live: …".
   Run the tests and expect FAIL.
2. Implement. Group items by account and region, and use one assumed session per account. Run the tests, expect PASS, and confirm `make test` is green. Commit `feat(aws): live re-check before a simulated delete`.

### Task 6: UI states and docs

**Files:** `frontend/src/api.ts`, `frontend/src/components/TopBar.tsx`, `frontend/src/pages/Overview.tsx`, create `frontend/src/components/ScanHealth.tsx`, tests `frontend/src/pages/Overview.test.tsx`, `frontend/src/components/Shell.test.tsx`, `frontend/src/api.test.ts` (or existing), `docs/HANDOFF.md`, `README.md` if it documents running.

**Interfaces:**
- `OverviewData` adds `segments_failed`, `unresolved`, `newest_failed`.
- `ScanHealth({overview, meta})` renders three things:
  - the "Some checks failed" card, grouping an account whose segments all failed with one `error_kind` into a single line;
  - the newest-failed banner;
  - the unresolved-references note.
- `TopBar` gets a `partial: boolean` prop and shows a **Partial scan** badge that links to `/`.
- `runScan` returns on `ok` or `partial`, throws on `failed` with the server message, and reports progress through an optional `onProgress(done)` callback that drives the "Scanning · N checks done" label.

**Steps:**
1. Failing tests:
   - Overview with `segments_failed` (dev, two regions, expired) shows one line containing "dev" and "Refresh your MFA session", plus the text "show as Unknown".
   - `newest_failed` shows "The last scan failed".
   - `unresolved` with 3 items shows "3 launch templates pick their image through an SSM parameter".
   - TopBar with `partial` shows "Partial scan".
   - `runScan` resolves when the scan status is `partial`.
   Run `cd frontend && npx vitest run` and expect FAIL.
2. Implement it. Run `make test` and confirm it's green, then `npm run build`.
3. Docs:
   - Update the HANDOFF status.
   - Add "Run against AWS" steps: copy the example config to `config/janitor.yaml`, set real IDs and profiles, refresh MFA, then `JANITOR_PROVIDER=aws make run`.
   - Note that the first real scan is the user's.
4. Commit `feat(ui): scan health, partial-scan badge, and AWS run docs`.
