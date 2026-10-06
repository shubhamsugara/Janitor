# Janitor — local proof of concept: design

- **Date:** 2026-10-06
- **Status:** Design — pending review
- **Supersedes for this round:** the stack, auth, Claude, LocalStack, and delete
  sections of [`janitor-spec-1.md`](../../../janitor-spec-1.md). That file remains
  the long-term vision; this spec is what gets built now.

---

## 1. Goal

Prove, on a laptop, that Janitor can:

1. Inventory **AMIs, EBS snapshots, EBS volumes, and RDS snapshots** from a seeded
   mock dataset **and** from real AWS accounts (read-only).
2. Compute — not guess — whether each resource is in use, using cross-account and
   cross-region linkage.
3. Explain every status in plain English inside the app.
4. Walk the full delete flow (plan → blocked/mixed/clean popup → confirm → result →
   audit) **without deleting anything**.

The same container image must later run on ECS Fargate behind an internal load
balancer under a path prefix, with no rebuild.

**Principle:** policy and humans decide; the app proves its reasoning.

### Success criteria

- `docker compose up` on a fresh clone shows the full UI on mock data with no AWS
  credentials.
- Pointed at real accounts, a scan completes across all configured accounts and
  regions (including a region with ~200k snapshots), and list/filter/count queries
  return in under 500 ms.
- No code path, credential, or runtime call can delete or modify an AWS resource
  (three independent locks, §10, each covered by a test).
- Any user can explain any status from inside the app.

### Out of scope (each is its own later round)

- Claude analyst (verdict suggestions). The design leaves a slot for it (§17).
- Real deletes, quarantine.
- ECS deployment (the image is ECS-ready; the infrastructure is not part of this round).
- Login / SSO (local binds to `127.0.0.1` only).
- Video and deck.
- LocalStack (mock covers demos; real read-only AWS covers proof).

## 2. Domain model: how AMIs move between accounts and regions

Janitor is built for an organization shaped like this (all names generic):

- An **owner account** (e.g. `tools`) builds AMIs in a **primary region** and adds
  **launch permissions** for other accounts.
- **Launch permissions are region-scoped.** An AMI in region R can be launched only
  in region R. So for an AMI in R, only the permitted accounts' usage **in R**
  matters.
- **Share** (within a region): every permitted account launches the **same AMI ID**,
  backed by **one set of owner-owned snapshots**.
- **Copy** (to another region): the owner account copies the AMI into each other
  region, producing a **new AMI ID and new snapshots** (snapshot description
  `Copied for DestinationAmi <new> from SourceAmi <src> …`). Each copy is then
  shared within its own region. Copies are independent: deregistering the source
  does not affect them. Copies are the main source of dangling snapshots.
- **Deregistering is per region:** it removes the AMI for every account using it in
  that region. Running instances keep running; new launches and ASG scale-outs that
  reference it fail.

**Design consequence:** in-use consumers are **derived from each AMI's actual launch
permissions** (read from AWS), scoped to the AMI's region — never from a hand-written
topology list. The config only maps account IDs to credentials.

RDS snapshots and EBS volumes are owned by the accounts that run the workloads, not
by the owner account, so each account declares which types it owns (§4).

## 3. Architecture

One container, one process — the same shape as a single Fargate task.

```
browser ──► FastAPI (port 8080, configurable base path)
              ├─ /api/*    JSON API
              ├─ /*        built React + Cloudscape SPA (static)
              ├─ scanner   background job (on "Scan now", or at startup if cache empty)
              │    └─ CloudProvider (read-only interface)
              │         ├─ MockProvider  seeded fixture (fake IDs, committed)
              │         └─ AwsProvider   boto3, Describe-only session policy + guard
              ├─ linker    edges + status after each scan (pure)
              ├─ rules     deterministic block/warn/pass (pure)
              └─ store     SQLite (WAL) at $JANITOR_DB, mounted volume
```

### Units

| Unit | Responsibility | Depends on |
|---|---|---|
| `config` | Load + validate `janitor.yaml` (pydantic). Invalid config stops startup. | — |
| `providers` | `CloudProvider` protocol with read-only methods only; `MockProvider`, `AwsProvider`, the read-only guard. | config |
| `scanner` | Fan out provider calls across account × region, write a new scan generation, record per-segment success/failure. | providers, store |
| `linker` | Rows → edges + status + status reason. Pure function. | — |
| `rules` | Resource + context → rule results. Pure function. Each rule is self-describing. | config |
| `definitions` | Plain-English status and rule definitions with live config values. Single source for help text. | rules, config |
| `store` | Schema, filtered/paginated/counted queries, plans, append-only audit. | — |
| `plans` | Resolve selection, expand AMIs to snapshots, evaluate rules, simulate. | store, rules, providers |
| `api` | Thin FastAPI routers. | all of the above |
| `web` | React SPA; talks only to `api`. | — |

### Repository layout

```
backend/janitor/      config.py  models.py  scanner.py  linker.py  rules.py
                      definitions.py  store.py  plans.py  main.py
                      providers/{base.py, mock.py, aws.py, guard.py}
                      api/{meta.py, resources.py, scans.py, actions.py, audit.py}
backend/tests/
frontend/src/         api/  components/  pages/  help/
config/janitor.example.yaml        # committed, fake IDs
fixtures/seed.json                 # committed, generated by scripts/make_seed.py
scripts/{make_seed.py, check_private.py}
Dockerfile  docker-compose.yml  Makefile
```

## 4. Configuration

`config/janitor.yaml` is **gitignored**. Only `config/janitor.example.yaml` (fake IDs)
is committed.

```yaml
provider: mock            # mock | aws (overridable by JANITOR_PROVIDER)
owner:
  account: "111111111111"
  regions: [us-east-1, us-west-2, eu-west-1]   # default regions for every account
accounts:                 # every account an AMI may be shared with, plus type owners
  "111111111111": { name: tools, profile: example-tools, owns: [ami, snapshot, volume] }
  "222222222222": { name: dev,   profile: example-dev,   owns: [volume, rds_snapshot] }
  "333333333333": { name: prod,  profile: example-prod,  owns: [volume, rds_snapshot],
                    regions: [us-east-1, eu-west-1] }   # optional per-account override
policy:
  orphan_after_days: 90
  min_age_days: 30
  keep_newest_per_name_group: 5
  ami_name_group_pattern: '^(?P<group>.+?)[-_.]?(\d{8,14}|v?\d+(\.\d+)*)$'
  keep_name_patterns: []          # regexes; real list lives in the private config
  protected_tags: { retain: "true", "janitor:keep": "true" }
  source_with_live_copies: warn   # warn | block
  rds_last_copy: warn             # warn | block
  typed_confirm_min_items: 10
pricing:                           # estimates only; labeled as such in the UI
  snapshot_gb_month: 0.05
  rds_snapshot_gb_month: 0.095
  volume_gb_month: { gp3: 0.08, gp2: 0.10, io1: 0.125, io2: 0.125, st1: 0.045, sc1: 0.015, standard: 0.05 }
scan:
  concurrency: 8
```

Validation: the owner account must appear in `accounts`; only the owner may own `ami`;
every profile must exist in the local AWS config.

AMIs are scanned only in the owner account; usage is scanned only for
`(account, region)` pairs that appear in some AMI's launch permissions in that region,
plus the owner account in every region.

## 5. Data model (SQLite, WAL)

Every scan-produced row carries `scan_id`. Readers use the latest **completed** scan;
a running scan never mixes with it. The current and previous scans are kept; older
ones are pruned. `audit` is never pruned.

| Table | Columns |
|---|---|
| `scans` | id, started_at, finished_at, provider, status (`running`/`ok`/`partial`/`failed`) |
| `scan_segments` | scan_id, account, region, kind (`owner`/`consumer`), resource_kind, ok, error, item_count, duration_ms |
| `resources` | scan_id, id, type (`ami`/`snapshot`/`volume`/`rds_snapshot`), account, region, name, created_at, size_gb, state, tags_json, est_monthly_cost, status, status_reason, raw_json; nullable: source_ami_id, source_ami_region, linked_ami_id, origin (`built`/`copied`), source_volume_id, source_snapshot_id, attached_instance, volume_type, source_db_id, db_kind (`instance`/`cluster`), managed_by |
| `ami_shares` | scan_id, image_id, principal_type (`account`/`group`/`org`/`ou`), principal |
| `usage` | scan_id, image_id, account, region, ref_type (`instance`/`launch_template`/`asg`/`launch_config`), ref_id, ref_name |
| `edges` | scan_id, src_id, dst_id, rel (`ami_snapshot`, `ami_copy_of`, `snapshot_volume`, `volume_snapshot`, `volume_instance`, `rds_source_db`, `ami_used_by`) |
| `policy_results` | scan_id, resource_id, rule_id, outcome (`block`/`warn`/`pass`), message |
| `plans` | id, created_at, scan_id, selection_json, results_json |
| `audit` | id, ts, actor, action (`scan_started`/`scan_finished`/`plan`/`simulate`), payload_json |

`resources.id` is the native ID for EC2 resources (`ami-…`, `snap-…`, `vol-…`, globally
unique) and the snapshot **ARN** for RDS snapshots (identifiers are only unique per
account and region); the RDS identifier is stored as `name`.

Indexes on `resources`: (scan_id, type, region), (scan_id, type, status),
(scan_id, type, created_at), (scan_id, name), (scan_id, source_ami_id),
(scan_id, linked_ami_id). A `REGEXP` function is registered on every connection.

`policy_results` is recomputed after each scan and at startup, so config changes take
effect without rescanning.

## 6. Statuses

Five statuses. Each resource also gets a one-sentence **status reason** specific to
it (e.g. "Its description names ami-0abc, which is no longer registered.").

| | in_use | managed | idle | orphaned | unknown |
|---|---|---|---|---|---|
| **AMI** | Referenced by an instance, launch template, ASG, or launch config in a permitted account in its region | Created by AWS Backup or DLM | Unused, younger than `orphan_after_days` | Unused, older than `orphan_after_days` | Usage cannot be proven (§7.3) |
| **EBS snapshot** | Backs a registered AMI (block-device mapping, or its `Copied for DestinationAmi X` names a registered X) | Created by AWS Backup or DLM | No AMI link, and either its source volume exists or it is younger than threshold | Dangling (names an AMI that is no longer registered), or no AMI link, source volume gone, older than threshold | AMI list for its region failed |
| **EBS volume** | Attached | — | Unattached, younger than threshold | Unattached, older than threshold | — |
| **RDS snapshot** | — | Automated or AWS Backup snapshot type | Manual, source DB instance/cluster exists | Manual, source DB gone, older than threshold | Source DB list failed |

When more than one applies, precedence is **in_use > managed > unknown > orphaned >
idle** (proven usage beats a failed check elsewhere; both block).

Stated plainly in the UI:
- Volume age is measured from creation; AWS does not expose detach time.
- Snapshot cost is an estimate (`size × rate`); snapshots are incremental.

## 7. Scanner

### 7.1 Calls (all paginated)

| Kind | Calls |
|---|---|
| AMIs (owner account, each region) | `DescribeImages(Owners=[self])`; `DescribeImageAttribute(launchPermission)` per AMI |
| EBS snapshots (owners) | `DescribeSnapshots(OwnerIds=[self])` |
| EBS volumes (owners) | `DescribeVolumes` |
| Usage (permitted account × region) | `DescribeInstances` (all non-terminated states), `DescribeLaunchTemplates` + `DescribeLaunchTemplateVersions`, `DescribeAutoScalingGroups`, `DescribeLaunchConfigurations` |
| RDS (owners) | `DescribeDBSnapshots`, `DescribeDBClusterSnapshots`, `DescribeDBInstances`, `DescribeDBClusters`, `DescribeDBSnapshotAttributes` (manual only) |

Rows are streamed page by page into the store; nothing holds a full region in memory.

### 7.2 Launch-template resolution

An AMI is in use via a launch template if it appears in:
- the version an ASG actually pins: `$Latest` → latest version number, `$Default` →
  default version number, explicit → that number; for both `LaunchTemplate` and
  `MixedInstancesPolicy.LaunchTemplate.LaunchTemplateSpecification`; **or**
- any launch template's default or latest version (conservative: covers fleets, node
  groups, and manual launches).

Images referenced as `resolve:ssm:…` cannot be resolved read-only with the current
session policy; they are listed as "unresolved references" on the scan and in the UI.

### 7.3 When status is `unknown`

An AMI is `unknown` (and blocked) when any of these hold:
- a permitted account has no entry in `accounts`;
- a permitted account's usage segment for that region failed;
- launch permission includes `group: all` (public) or an organization / OU ARN.

### 7.4 Linkage

- AMI → snapshots: block-device mappings.
- Snapshot → AMI: block-device map, else description
  `Created by CreateImage\((i-[0-9a-f]+)\) for (ami-[0-9a-f]+)` (origin `built`) or
  `Copied for DestinationAmi (ami-[0-9a-f]+) from SourceAmi (ami-[0-9a-f]+)` (origin
  `copied`).
- AMI copy → source: `SourceImageId`/`SourceImageRegion` when present, else the source
  AMI parsed from its snapshots' copy descriptions.
- Snapshot → source volume; volume → source snapshot; volume → attached instance.
- RDS snapshot → source DB instance or cluster.
- Managed: RDS `SnapshotType` in (`automated`, `awsbackup`); EBS snapshots and AMIs with
  AWS Backup or DLM markers (`aws:backup:source-resource`, `aws:dlm:lifecycle-policy-id`
  tags, or the AWS Backup description).

### 7.5 Failure handling

- Each `(account, region, resource_kind)` is a segment; one failing never stops others.
- botocore adaptive retry; throttling surfaces as a UI state.
- Scan status: `ok` (all segments ok), `partial` (some failed), `failed` (none ok or
  config/credential error).
- One scan at a time; `POST /api/scans` returns 409 while one runs.

## 8. Rules

Deterministic code. Strictest outcome wins: **block > warn > pass**. Each rule has an
id, title, and explanation template rendered with live config values.

| ID | Rule | Types | Outcome |
|---|---|---|---|
| R1 | In use | all | block |
| R2 | Usage unknown | all | block |
| R3 | Managed by AWS | all | block |
| R4 | Protected tag (`policy.protected_tags`) | all | block |
| R5 | Younger than `min_age_days` | all | block |
| R6 | Among N newest in its name group, per region | AMI | block |
| R7 | Name matches `keep_name_patterns` | AMI | block |
| W1 | Source AMI with live copies in other regions | AMI | warn (configurable to block) |
| W2 | Newest snapshot of a deleted DB (possible last copy) | RDS | warn + typed confirm (configurable to block) |
| W3 | Newest snapshot of a volume that still exists | snapshot | warn |
| W4 | Missing `owner` tag | all | warn |
| W5 | Manual snapshot shared with other accounts | RDS | warn |

**Typed confirmation** (type `delete`) is required when the deletable set has
≥ `typed_confirm_min_items` items, any warned item, or any item tagged `env=prod`.

## 9. Simulated delete flow

1. **Select:** explicit IDs, or "all matching filters" sent as
   `{filter, include, exclude}` — never a client-side list of 200k IDs.
2. **`POST /api/actions/plan`:** resolves the selection against the current scan;
   expands each AMI to its backing snapshots not used by any other registered AMI;
   evaluates rules; returns `variant` (`all_blocked`/`mixed`/`none_blocked`), blocked
   items with rule + reason, deletable items with warnings, totals (count, GiB,
   est. $/month), share impact per AMI, `requires_typed_confirmation`, `plan_id`.
3. **Popup:** three variants, always headed
   **"Simulation — nothing will be deleted."**
   - All blocked: "Can't delete these resources", each with its reason; Close only.
   - Mixed: "N blocked will be skipped", then "Simulate deleting the other M?";
     Cancel / Simulate M.
   - None blocked: "Simulate deleting N resources?"; Cancel / Simulate.
4. **`POST /api/actions/simulate {plan_id, confirmation}`:** returns 409 if the scan
   changed since the plan; in AWS mode re-reads the selected resources and their usage
   live (read-only); re-evaluates rules; writes one audit entry with per-item outcome
   (`would_delete`/`skipped`); returns `{would_delete, skipped, failed}`.
5. **Result bar:** e.g. "Simulated: 3 would be deleted (40 GiB, ~$2.00/month),
   2 skipped (in use)." Rows stay; the Audit page lists the simulation.

## 10. Read-only guarantees (three locks)

1. **Interface:** `CloudProvider` exposes read methods only; there is no delete,
   modify, or tag method to call.
2. **IAM:** every account is accessed via `sts:AssumeRole` with an inline session
   policy allowing only `ec2:Describe*`, `autoscaling:Describe*`, `rds:Describe*`.
   Effective permissions are the intersection, so AWS rejects anything else even if
   the underlying role is admin. Profiles without a `role_arn` are refused.
3. **Runtime guard:** a botocore `before-call` hook on every client raises before
   sending any operation whose name does not start with `Describe`, `List`, or `Get`.

Each lock has a dedicated test.

## 11. API

All routes under `$JANITOR_BASE_PATH`.

| Route | Purpose |
|---|---|
| `GET /health` | Load balancer health check → `{"status":"ok"}` |
| `GET /api/meta` | Provider, read-only flag, account names and regions, status and rule definitions with live config values |
| `GET /api/overview` | Per-type counts, waste, last scan time, failed segments |
| `GET /api/resources` | Params: `type, q, name_regex, account, region, status, created_from, created_to, tag (k:v), source_ami, source_db, sort, page, page_size` → `{items, total}` |
| `GET /api/stats` | Same filters → `{total, orphaned, size_gib, est_monthly_usd}` (`null` cost for AMIs) |
| `GET /api/resources/{id}` | Detail, edges, rule results, status reason, share impact |
| `POST /api/scans` · `GET /api/scans/latest` | Start scan (409 if running) · progress + segments |
| `POST /api/actions/plan` · `POST /api/actions/simulate` | §9 |
| `GET /api/audit` | Paginated audit log |

Filters combine with AND; date range is inclusive; `q` matches name or ID
case-insensitively.

## 12. UI

React + TypeScript + Vite + Cloudscape. Copy rules: sentence case; buttons start
with a verb; no "successfully", "please", or exclamation marks; errors say what
happened, then what to do.

- **Shell (`AppLayout`):** top bar with name, data-source badge (**Mock data** /
  **AWS · read-only**), scan status + **Scan now**, dark-mode toggle, help menu.
  Side nav: Overview · AMIs · EBS snapshots · EBS volumes · RDS snapshots · Audit ·
  How Janitor decides. Right drawer: help panel.
- **Overview:** four type cards: total, waste line ("1,204 orphaned · 3.1 TiB"),
  last scan time, per-region failure chips with Retry.
- **Resource screen:** stats (from the filtered set); property filter with live match
  count; table with server-side pagination and sorting, status chips with Info
  popovers, header checkbox offering "Select all N matching"; selection bar
  (count · Clear · Plan delete); split panel with tabs Details · Tags · Related
  (edges, copies, share impact) · Rules (results + status reason) · Actions.
- **Delete popup + result bar:** §9.
- **Audit:** scans and simulations, expandable to items.
- **States:** skeleton loading; "No scan yet — Run first scan"; empty type; filters
  match nothing (Reset); partial region failure; throttling ("AWS is throttling
  requests. Retrying"); permission denied (names the missing permission); expired
  credentials ("AWS session expired. Refresh your MFA session, then Scan now").
- **Selection:** persists across filter changes, clears on type change, may include
  blocked items (blocked at plan time, not selection time).
- **Filters in the URL** query string.
- **Base path:** the SPA is built with relative asset paths; the server injects
  `<base href="$JANITOR_BASE_PATH/">` into `index.html`; the API client uses relative
  URLs. The same image serves at `/` locally and at a prefix such as `/janitor` on ECS.
- **Deferred:** j/k/x shortcuts (only `/` and `Esc` now), CSV export, saved filters,
  cost breakdown.

## 13. In-app explanations

- **Single source:** `GET /api/meta` returns every status and rule definition rendered
  with live config values ("older than 90 days"). Help text and logic share these
  definitions.
- **Info links** on every status chip, rule, and stat open the help panel: what it
  means, why it blocks or allows deletion, what to do.
- **Status reason** on each resource (detail panel and popup).
- **"How Janitor decides" page:** per-type status tables, all rules, the share/copy
  model (§2), and the safety model (§10).
- **First-run walkthrough:** five steps using Cloudscape's annotation/tutorial
  components: pick a type → filter → read a status → select → see the plan popup.
  Replayable from the help menu.

## 14. Local runtime and credentials

- `docker compose up` — one service:
  - ports `127.0.0.1:8080:8080`
  - volumes `./data:/data`, `./config:/config:ro`, `~/.aws:/home/janitor/.aws:ro`
    (needed only for AWS mode)
  - env `JANITOR_PROVIDER`, `JANITOR_CONFIG=/config/janitor.yaml`,
    `JANITOR_BASE_PATH=/`, `JANITOR_DB=/data/janitor.db`
- Without `config/janitor.yaml`, the app starts in mock mode with the example config.
- **AWS mode:** the user refreshes their MFA session on the host as usual. For each
  account, Janitor reads `role_arn` and `source_profile` from the named profile, then
  assumes the role with the session policy (session name `janitor-readonly`).
  Credentials are refreshed each scan (chained-role sessions last at most one hour).
- **Image:** multi-stage — Node 22 build of the SPA → Python 3.12 slim runtime, non-root
  user, port 8080.
- **Make targets:** `make dev` (uvicorn reload + Vite dev server proxying `/api`),
  `make test`, `make seed`, `make up`.
- **Dependencies (pinned):** FastAPI, uvicorn, boto3, pydantic, PyYAML; dev: pytest,
  moto, httpx, ruff. Frontend: React, TypeScript, Vite, `@cloudscape-design/*`,
  React Router, Vitest, Testing Library, Playwright. Anything else requires approval.

## 15. Public-repo hygiene

This repository is public. Nothing organization-specific is committed.

- **Gitignored:** `config/janitor.yaml`, `data/`, `*.db`, `.env`, `.private-terms`.
- **Committed fixtures use fake IDs only** (`111111111111`-style accounts,
  `ami-0000…`-style resources). `scripts/make_seed.py` generates `fixtures/seed.json`
  from a fixed RNG seed and includes every status per type plus the demo moments:
  in-use AMI, prod-tagged volume, dangling copied snapshot, RDS last copy, AMI shared
  with an unscanned account. Timestamps in fixture names use 14 digits
  (`YYYYMMDDhhmmss`) so they never look like account IDs.
- **Leak check (`scripts/check_private.py`)**, run as a pre-commit hook and in CI:
  fails on any 12-digit number not in the fake-ID allowlist; locally, also fails on any
  term listed in the gitignored `.private-terms` file.
- **CI also runs gitleaks** for secrets.

## 16. Testing

- **Rules:** pass and block cases per rule; strictest-wins.
- **Linker:** every status per type; description parsing (built and copied);
  launch-template version resolution (`$Latest`, `$Default`, explicit,
  MixedInstancesPolicy); share list → unknown; managed detection.
- **AwsProvider (moto):** multi-page pagination; multi-account assume-role with the
  session policy actually passed; RDS instance and cluster snapshots.
- **Read-only guard:** a mutating call raises before sending; every operation the
  provider uses is asserted to be Describe/List/Get.
- **Store:** AND-combined filters, inclusive date range, regex, counts, pagination;
  200k-snapshot performance test (list + count < 500 ms, marked slow).
- **API:** all three popup variants; AMI → snapshot expansion; stale plan → 409;
  simulate writes audit; base path `/janitor` serves health, API, and SPA.
- **Frontend (Vitest + Testing Library):** popup variants; selection model; base-path
  URL building.
- **E2E (Playwright, mock mode):** overview → AMIs → filter → select all → plan →
  blocked popup → simulate → audit.
- **CI (GitHub Actions):** ruff, pytest, vitest, Playwright, image build, leak check,
  gitleaks.

## 17. Later rounds

1. **Claude analyst:** `delete`/`keep`/`review` suggestion + reason per resource, shown
   beside the rules; rules still win. Inputs are metadata only; names and tags are
   untrusted input.
2. **ECS deploy:** existing internal ALB, path prefix, EFS for SQLite, task role with
   the read-only policy. The image from this round is reused unchanged.
3. **Real delete:** behind a separate write role, dry-run default, live re-verify (already
   built here), optional Recycle Bin retention as an undo net.
4. **Video and deck.**

## 18. Risks and open questions

- **`resolve:ssm:` image references** can't be resolved without `ssm:GetParameter`;
  shown as unresolved for now. Adding that permission is a later decision.
- **Per-AMI `DescribeImageAttribute`** is one call per AMI; fine for thousands with
  concurrency, monitored via segment duration.
- **AMIs referenced directly by Spot/EC2 Fleet requests** (without a launch template)
  are not checked.
- **`SourceImageId` availability** varies by AMI age; the description fallback covers
  older copies.
