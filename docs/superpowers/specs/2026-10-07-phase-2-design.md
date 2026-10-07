# Janitor phase 2: fixes, linkage, insight — design

- **Date:** 2026-10-07
- **Status:** Approved in conversation; pending review of this document
- **Builds on:** [`2026-10-06-janitor-poc-design.md`](2026-10-06-janitor-poc-design.md) (the base spec; everything there still holds unless this document changes it) and the phase 1 MVP on `main`.
- **Replaces:** the earlier phase 2 plan (bug fixes only). Its 11 fixes are kept in §9.

---

## 1. Goal

After using the MVP, the user wants Janitor to make linkage obvious, give cost numbers they can trust, and look the part. Phase 2 delivers, on mock data:

1. **Linkage you can see (top priority).** Selecting any resource shows a diagram of what it comes from and what uses it, across accounts and regions, and states plainly which *active* resources use it.
2. **Cost you can trust.** Per-region AWS prices from AWS's official price list, with a breakdown for every number.
3. **Insight per category.** A stats header with charts on every resource page, following the filters.
4. **Better filtering and export.** Account (by environment), region, status, tag, and a created-date range; export the filtered list as CSV or PDF.
5. **A UI worth showing.** Official AWS icons, a top bar, dark mode, stronger visual states.
6. **The deferred fixes.** All issues found in phase 1 review and testing.

### Success criteria

- Clicking any resource opens a panel whose default tab is a diagram; clicking a node re-centers on it.
- For a snapshot behind an in-use AMI, the panel says which running instances use it, through which AMI.
- Every cost shown can be expanded into quantity × rate, with region and price-list date.
- A filtered view's URL reproduces the same view; its CSV contains every matching row; its PDF shows the same filters and totals.
- The public repo still contains no AWS icon files, no real account IDs, and no organization-specific names.

### Out of scope (later phases)

Read-only AWS provider (now phase 3), live Pricing API, Docker/ECS, CI, the 200k-snapshot performance work, rules R6/R7/W1/W2/W3/W5, "select all N matching", the first-run walkthrough.

## 2. Mock data and model changes

### Accounts

| Account | Name | Owns | Regions |
|---|---|---|---|
| 111111111111 | tools (owner) | ami, snapshot, volume | us-east-1, us-west-2, eu-west-1 |
| 555555555555 | sbx | volume, rds_snapshot | default |
| 222222222222 | dev | snapshot, volume, rds_snapshot | default |
| 666666666666 | uat | volume, rds_snapshot | default |
| 777777777777 | qas | volume, rds_snapshot | default |
| 333333333333 | prd | volume, rds_snapshot | us-east-1, us-west-2, eu-west-1 |
| 444444444444 | (not in config) | — | — |

AMIs built in us-east-1 are shared there with sbx, dev, uat, qas, and prd. Copies in us-west-2 and eu-west-1 are shared within their region with prd. `config/janitor.example.yaml` and `scripts/make_seed.py` change to match; every demo moment from phase 1 stays.

### New fields

| Record | Field | Values |
|---|---|---|
| `Resource` (volume) | `iops: int \| None`, `throughput: int \| None` (MiB/s), `encrypted: bool \| None` | from `DescribeVolumes` in phase 3 |
| `Resource` (snapshot) | `storage_tier: str \| None` | `standard` or `archive` |
| `Resource` (all) | `cost_breakdown: dict \| None` | §3 |
| `Usage` | `ref_state: str` | instance: `running`, `stopped`, `pending`, `stopping`; ASG: `active` (desired > 0) or `inactive`; launch template / launch config: `""` |

`Usage` gains `active: bool | None` as a derived property: `True` for a running instance or active ASG, `False` for stopped/inactive, `None` for launch templates and configs (a reference, not a running thing).

## 3. Cost model

### Price data

- `scripts/fetch_prices.py` (stdlib only) streams AWS's official Price List bulk files (`pricing.us-east-1.amazonaws.com/offers/v1.0/aws/{AmazonEC2,AmazonRDS}/current/<region>/index.csv`) row by row, keeps only the EBS storage, IOPS, throughput, snapshot, and RDS backup-storage rows for the configured regions, and writes `fixtures/prices.json`. The EC2 file is ~300 MB per region, so the script is run on demand (`make prices`), not at startup.
- `fixtures/prices.json` is committed. It records `source` (URLs), `publication_date` (from the price list), `fetched_at`, `currency`, and per-region rates:

```json
{
  "source": ["https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/us-east-1/index.csv"],
  "publication_date": "2026-09-30T00:00:00Z",
  "currency": "USD",
  "regions": {
    "us-east-1": {
      "ebs_gb_month": {"gp3": 0.08, "gp2": 0.10, "io1": 0.125, "io2": 0.125, "st1": 0.045, "sc1": 0.015, "standard": 0.05},
      "gp3_iops_month": 0.005,
      "gp3_throughput_mibps_month": 0.04,
      "io1_iops_month": 0.065,
      "io2_iops_month_tiers": [[32000, 0.065], [64000, 0.0455], [null, 0.03185]],
      "snapshot_gb_month": {"standard": 0.05, "archive": 0.0125},
      "rds_snapshot_gb_month": 0.095
    }
  }
}
```

(Values above illustrate the shape; the committed file holds what the script fetched.)

- `config.pricing` becomes a fallback used only for a region or rate missing from `prices.json`; a breakdown line that used it says so.

### Formulas (monthly, USD)

| Type | Cost |
|---|---|
| Volume | `size × ebs_gb_month[type]` + gp3: `max(0, iops − 3000) × gp3_iops_month + max(0, throughput − 125) × gp3_throughput_mibps_month` + io1: `iops × io1_iops_month` + io2: provisioned IOPS through `io2_iops_month_tiers` (first 32,000, next 32,000, the rest) |
| Snapshot | `size × snapshot_gb_month[storage_tier or "standard"]` — an upper bound: snapshots are incremental |
| RDS snapshot | `size × rds_snapshot_gb_month` — an upper bound; automated snapshots may be covered by free backup storage |
| AMI | the sum of its backing snapshots' costs (not added again in totals that already count snapshots) |

### Breakdown

Every resource stores `cost_breakdown`:

```json
{"region": "us-east-1", "source_date": "2026-09-30", "estimate": "upper bound: snapshots are incremental",
 "lines": [{"label": "Storage (gp3)", "quantity": 500, "unit": "GiB-month", "rate": 0.08, "amount": 40.0},
           {"label": "IOPS above 3,000", "quantity": 2000, "unit": "IOPS-month", "rate": 0.005, "amount": 10.0}],
 "fallback": false}
```

`est_monthly_cost` equals the sum of `lines[].amount`, rounded to cents. Plan and stats totals that include both AMIs and snapshots count each snapshot once (AMIs are excluded from sums, as today).

## 4. Linkage

### Graph API

`GET /api/resources/{id}/graph` (depth 2 from the selected resource) returns:

```json
{
  "root": "ami-0000…",
  "nodes": [{"id": "ami-0000…", "kind": "ami", "label": "base-linux-…", "status": "in_use",
             "account": "111111111111", "account_name": "tools", "region": "us-east-1",
             "active": null, "depth": 0}],
  "edges": [{"source": "ami-0000…", "target": "instance:i-0000…", "relation": "used_by"}],
  "used_by": {"active": 2, "total": 3, "summary": "Used by 2 running instances in dev and prd, and 1 launch template."},
  "truncated": false
}
```

- **Node kinds:** resources (`ami`, `snapshot`, `volume`, `rds_snapshot`) keep their own IDs; context nodes are prefixed so IDs never collide: `instance:<id>`, `asg:<account>:<region>:<name>`, `launch_template:<id>`, `launch_config:<account>:<region>:<name>`, `account:<id>`, `database:<account>:<region>:<id>`.
- **Edges point downstream** (where it came from → what depends on it):

| Relation | Source → target |
|---|---|
| `snapshot_of` | volume → snapshot |
| `backs` | snapshot → AMI |
| `copied_to` | source AMI → copy |
| `used_by` | AMI → instance / launch template / ASG / launch config |
| `shared_with` | AMI → account |
| `attached_to` | volume → instance |
| `snapshot_of_db` | database → RDS snapshot |

- **Traversal:** breadth-first in both directions from the root to depth 2. A lane cap of 25 nodes per depth replaces the rest with one `more` node (`"kind": "more", "label": "+14 more"`) and sets `truncated`.
- **`used_by`** (the bug fix): AMI → its usage; snapshot → the usage of every registered AMI it backs; volume → its attached instance; RDS snapshot → none. `summary` names counts by kind, the accounts, and, for a snapshot, the AMI it goes through.

### Diagram (frontend)

- React Flow (`@xyflow/react`), read-only: no dragging edges or editing.
- **Layout (pure function `layoutGraph(graph) → positioned nodes`):** lanes by signed depth (upstream left, root center, downstream right); within a lane, sort by kind then label; fixed spacing. A node reachable both ways keeps its first lane.
- **Node:** AWS icon, label, status color strip, account · region, and a green "running" dot for active users.
- **Interaction:** click a resource node to re-center on it (load its graph); click a context node to show its details in a tooltip; pan, zoom, fit-to-view button; a legend for relations and colors.
- Edge labels show the relation in words ("backs", "copy of", "used by", "attached to", "shared with").

## 5. Stats per category

`GET /api/stats` takes the same filters as `/api/resources` and returns:

```json
{"total": 84, "orphaned": 48, "size_gib": 2100, "est_monthly_usd": 105.0,
 "orphaned_gib": 1930, "orphaned_usd": 96.5, "blocked": 30, "deletable": 54,
 "by_status": [{"key": "orphaned", "count": 48, "gib": 1930, "usd": 96.5}],
 "by_account": [...], "by_region": [...],
 "by_age": [{"key": "<30d", ...}, {"key": "30–90d"}, {"key": "90–180d"}, {"key": "180–365d"}, {"key": ">1y"}]}
```

"Blocked" means the resource has at least one block result. Each resource page shows a stats header (cards: total, orphaned, waste $/month, blocked vs deletable) and charts (by status, account, region, age) using Cloudscape's built-in charts. The overview gets one mini chart per type.

## 6. Filters

- `account`, `region`, `status` accept comma-separated lists; `created_from` / `created_to` must be `YYYY-MM-DD` (422 otherwise).
- UI: a Cloudscape property filter for account (shown by name), region, status, and tag, plus a date-range picker for created date.
- Filter, sort, and page state live in the URL query string, so links reproduce views.

## 7. Export

- **CSV:** `GET /api/resources/export.csv` with the list filters and sort. Streams every matching row. Columns: `id, name, type, account, account_name, region, status, status_reason, delete_check, created_at, size_gib, est_monthly_usd, tags`. Filename `janitor-<type>-<YYYYMMDD>.csv`. Cells starting with `=`, `+`, `-`, `@`, tab, or carriage return are prefixed with `'` to prevent formula injection.
- **PDF:** the UI fetches `GET /api/resources/export.json` (same filters, at most 5,000 rows, with `total` and `truncated`), builds a report model (pure function, tested), and renders it with jsPDF + jspdf-autotable: title, data source, generated time, filters used, stats summary, then the table. When truncated, the PDF says "Showing 5,000 of N; export CSV for all rows." jsPDF is loaded on demand so it doesn't grow the main bundle.
- Both export routes are registered before `/api/resources/{id}` so the ID route doesn't capture them.

## 8. Look and feel

- **Icons:** `scripts/fetch_icons.py` finds the current "Icon package" link on AWS's Architecture Icons page, downloads the zip, extracts the SVGs Janitor needs (AMI, EBS snapshot, EBS volume, RDS, EC2 instance, Auto Scaling, launch template, account), and writes them to `frontend/public/aws-icons/<kind>.svg`, which is gitignored. `make icons` runs it. `<AwsIcon kind>` uses the file when present and a simple built-in glyph otherwise. AWS permits these icons for architecture diagrams; keeping them out of the public repo avoids redistributing them.
- **Shell:** Cloudscape top navigation with the name, data-source badge (**Mock data**), scan status with **Scan now**, and a light/dark toggle (remembered per browser).
- **Resource panel:** clicking a row opens the app layout's split panel with tabs Diagram (default), Details, Cost, Rules, Tags. A context holds the selected ID so diagram clicks can change it.
- Status colors, one-line status chips, hover states on rows and nodes.

## 9. Fixes carried from the earlier phase 2 plan

1. The Status column wraps ("Orph/aned").
2. "Simulate deleting 1 resources?" pluralization.
3. The header pairs "N orphaned" with the whole set's size and cost.
4. An empty protected-tag value or an unquoted YAML `true` gives an unclear error.
5. The typed-confirmation hint hardcodes "10".
6. Mixed popup counts include backing snapshots.
7. Selecting an AMI with its own snapshot blocks the snapshot.
8. The pre-commit leak check reads the working tree, not staged content.
9. The status popover says "Can be deleted" even when a rule blocks.
10. The missing-IDs warning doesn't say what to do.
11. List responses can arrive out of order; **Scan now** misses scans started elsewhere; a huge `page` returns 500.

Also: simulate's skipped items carry their rule title, so the result bar reads "2 skipped (in use)" (base spec §9.5).

## 10. Dependencies

New, pinned exactly; approved by the user on 2026-10-07:

| Package | Version | License | Use |
|---|---|---|---|
| @xyflow/react | 12.12.0 | MIT | diagram |
| jspdf | 4.2.1 | MIT | PDF export |
| jspdf-autotable | 5.0.8 | MIT | PDF tables |
| vitest (dev) | 5.0.3 | MIT | frontend tests |
| @testing-library/react (dev) | 16.3.3 | MIT | frontend tests |
| @testing-library/dom (dev) | 10.4.2 | MIT | frontend tests |
| jsdom (dev) | 30.1.2 | MIT | test DOM |

No new Python dependencies.

## 11. Testing

- **Backend (pytest):** cost formulas against a fixture price table (gp3 extras, io2 tiers, archive tier, AMI sums, fallback flag); graph nodes and edges per type, depth and lane cap, prefixed IDs; transitive `used_by` for a snapshot behind an in-use AMI; stats breakdowns and blocked/deletable; multi-value and date filters (including 422 on bad dates); CSV rows, columns, and formula-injection escaping; the 11 fixes; the price and icon scripts' parsing on small sample inputs (no network in tests).
- **Frontend (Vitest + Testing Library):** `layoutGraph` lanes and ordering; the PDF report model (filters, totals, truncation note); URL ↔ filter state round trip; `DeleteModal` variants and counts; `StatusBadge` wording; the copy-rule check; `sequencer`.
- **Browser check:** select a snapshot behind an in-use AMI and see the chain to running instances; export CSV and PDF from a filtered view; toggle dark mode.

## 12. Risks

- **Price list size:** ~1 GB of downloads for three regions. Mitigated by streaming and running on demand; the committed `prices.json` keeps the app working without it.
- **Icon package changes:** AWS republishes quarterly and renames files. The script matches by name patterns and reports any it can't find; the UI falls back to glyphs.
- **Diagram crowding:** the lane cap and `more` nodes keep large fan-outs readable.
- **Bundle size:** React Flow adds weight; jsPDF loads only on export.

## 13. Roadmap change

Phase 2 is now fixes plus these features. Read-only AWS becomes phase 3; the final product (container, ECS, scale, CI) stays phase 4. `docs/superpowers/plans/2026-10-07-janitor-roadmap.md` is updated to match.
