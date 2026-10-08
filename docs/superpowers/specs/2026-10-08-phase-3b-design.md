# Phase 3b: remaining rules, select all matching, help panel, walkthrough

Status: decided in chat 2026-10-08. Builds on the base spec §8, §9, §11, §13 and the phase 3
specs; where they disagree, this document wins. The Deployments page (already on `main`) is
unchanged.

## Decisions (user)

| Topic | Decision |
|---|---|
| R6 name groups | The AMI name minus a trailing date or version, by a configurable pattern. No tags. |
| R6 keep count | The **3** newest per group, per account and region. |
| Walkthrough | Opens once per browser on first visit; replayable from a help menu. |

Assumed (not asked): W1 and W2 warn by default and can be set to block in `policy`, as the base
spec says. W5 adds one read-only call per manual RDS snapshot.

## Configuration (`policy`, all optional)

```yaml
policy:
  keep_newest_per_name_group: 3        # R6; >= 1
  ami_name_group_pattern: '^(?P<group>.+?)[-_.]?(\d{8,14}|v?\d+(\.\d+)*)$'   # R6
  keep_name_patterns: []               # R7; regexes, matched with re.search on the AMI name
  source_with_live_copies: warn        # W1: warn | block
  rds_last_copy: warn                  # W2: warn | block
```

- Each regex must compile; the pattern must have a named group `group`. Otherwise startup fails
  naming the field and the regex error.
- A name the group pattern doesn't match is its own group (its whole name).

## Rules

Rules stay deterministic and pure. Several now look across resources, so `rules.evaluate` takes
a `RuleContext` built once per scan by `rules.context(resources, databases, policy)` — pure, no
I/O. `recompute_rules` builds it from the store, so policy edits still apply without a rescan.

| ID | Applies when | Outcome | Message (example) |
|---|---|---|---|
| R6 | AMI is among the `keep_newest_per_name_group` newest (by `created_at`, ties by ID) AMIs in its group, same account and region | block | "It is the 2nd newest of 7 AMIs named ecs-gpu-* in us-east-1; Janitor keeps the 3 newest." |
| R7 | AMI name matches any `keep_name_patterns` regex | block | "Its name matches the keep pattern ^golden-." |
| W1 | AMI has copies (AMIs whose `source_ami_id` is its ID) in other regions in the scan | `source_with_live_copies` | "It was copied to us-west-2 and eu-west-1 (2 AMIs). The copies keep working, but this is their source." |
| W2 | RDS snapshot is the newest snapshot of its `source_db_id` (same account, region) and that DB isn't in the scan's databases | `rds_last_copy` | "Database orders-db is gone, and this is its newest snapshot. It may be the last copy." |
| W3 | EBS snapshot is the newest snapshot of its source volume, and that volume exists in the scan | warn | "It is the newest snapshot of vol-0abc, which still exists." |
| W5 | Manual RDS snapshot is shared with other accounts, or public | warn | "Shared with 222222222222 and 333333333333. They lose access to it." / "It is public." |

- `managed` resources are already blocked by R3; W2/W3 still compute over every snapshot so
  "newest" means newest of all copies, managed or not.
- A failed volume or database check already makes the snapshot `unknown` (R2); W2/W3 add nothing
  beyond that.
- Rule definitions in `/api/meta` render the live values: "the 3 newest", the keep patterns (or
  "none configured"), and the W1/W2 outcome. A rule's `outcome` in meta is the configured one.
- Plans: the backing-snapshot expansion still skips only R1. Simulate re-evaluates with the
  context from the plan's scan; the live re-check refreshes only the selected resources.

## Scan: RDS snapshot shares (W5)

- AWS: for each **manual** RDS snapshot (`managed_by` is null), call
  `DescribeDBSnapshotAttributes` (instance) or `DescribeDBClusterSnapshotAttributes` (cluster)
  and read the `restore` attribute: account IDs, or `all` for public. This is part of the
  existing `rds_snapshot` segment; a failure there fails that segment as today.
- `Resource.shared_with: list[str]` (RDS snapshot; `"all"` means public). Store column
  `shared_with` (JSON), `SCHEMA_VERSION` 8.
- Read-only locks: both operations start with `Describe`, and the session policy already allows
  `rds:Describe*`. No lock changes.
- Mock seed: a few manual RDS snapshots shared with other fake accounts, one public.

## Selection: "Select all N matching"

- `POST /api/actions/plan` accepts either `{type, ids}` (as today) or
  `{type, selection: {filter, exclude}}`, where `filter` is the resource-list filter (same keys
  as `GET /api/resources`) and `exclude` is a list of IDs. The server resolves it against the
  current scan. Exactly one of `ids` / `selection` is required (422 otherwise).
- `MAX_SELECTION` rises to 5,000. A selection resolving to more fails with 400: "N resources
  match. Narrow the filters to 5,000 or fewer, then plan again."
- The stored plan keeps the request form (`ids` or `selection`) for the audit entry.
- UI: when every row on the page is selected and more match, the selection bar offers
  "Select all N matching". In that mode the bar says "All N matching selected" (minus excluded),
  unchecking a row excludes it, and **Clear** leaves the mode. Changing filters, sort, or type
  clears the selection in that mode (explicit selections still persist across filter changes).

## Filters

- `name_regex`: Python `re.search` on the name, case-insensitive, via a SQLite function. An
  invalid regex returns 400 "That name pattern isn't a valid regular expression: <error>."
  FilterBar gets a "Name pattern" input, kept in the URL as `name`.
- `source_ami`: AMIs whose `source_ami_id` is the ID, and snapshots whose `linked_ami_id` is.
- `source_db`: RDS snapshots whose `source_db_id` is the ID.
- `source_ami` and `source_db` are kept in the URL and shown as removable pills
  ("Source AMI: ami-…"). The detail drawer links to them: "See its copies" (AMI with copies),
  "See all snapshots of this database" (RDS snapshot).
- All three apply to list, stats, CSV/JSON export, and select-all-matching.

## Help panel

- A right-side help panel (`Sheet`), opened by `openHelp(topic)` from a `HelpContext`. Topics:
  `status:<status>`, `rule:<id>`, `stat:<name>`, `page:<type>`. Content comes from `/api/meta`
  definitions (status and rule text, never hardcoded) plus short static page/stat text in one
  frontend module `help.ts`.
- Each topic shows: what it means, why it blocks or allows deletion, what to do. Rules show their
  configured outcome. A footer links to **How Janitor decides**.
- Info links (an "i" icon button, labelled "About <thing>") on: status badges (the popover gains
  "Learn more"), rule results in the drawer and the plan popup, and the stat cards.
- Opening help over the resource drawer stacks on top; closing it returns to the drawer.
- Top bar gets a **Help** menu: "Open help", "Replay walkthrough", "How Janitor decides".

## Walkthrough

- Six steps, each anchored to an element with `data-tour="<step>"`: pick a type (sidebar),
  filter (filter bar), read a status (first status badge), select (row checkbox), plan (Plan
  delete button, explaining the popup), see what is deployed (the Deployments grid). Steps 2–5
  open the AMIs page first if needed; step 6 opens Deployments.
- A small in-repo component: a highlight ring around the anchor plus a card with step N of 6,
  Back, Next/Done, and Skip. `Esc` skips. If an anchor is missing (e.g. no rows), the card shows
  centered without a ring.
- Auto-opens once when `localStorage["janitor:tour"]` is unset, then sets it to `done` on finish
  or skip. If storage throws, it never auto-opens. Replay from the Help menu ignores the flag.

## Copy

Sentence case, verbs on buttons, no "successfully", "please", or `!` (enforced by
`copy.test.ts`). Errors say what happened, then what to do.

## Testing

- Config: defaults; bad regex and missing `group` rejected; outcomes accept warn|block only.
- Rules (pure): R6 ranks per account+region+group, ties by ID, unmatched name is its own group;
  R7 matches; W1 only for copies in other regions; W1/W2 block when configured; W2 newest only
  and only when the DB is gone; W3 newest only and only when the volume exists; W5 accounts and
  public; meta explanations render live values.
- AWS (moto): manual RDS snapshot shares read through the guarded session; automated snapshots
  make no attribute call.
- Store/API: `shared_with` round-trips; `name_regex`, `source_ami`, `source_db` filter lists,
  stats, and exports; bad regex → 400; plan by selection resolves with exclude; over 5,000 → 400;
  both or neither of ids/selection → 422.
- Frontend: select-all-matching flow and exclude; filter change clears all-mode; name pattern
  and source pills round-trip through the URL; help panel renders a rule from meta; Info link
  opens the right topic; walkthrough auto-opens once, skips with Esc, replays from the menu, and
  doesn't auto-open when storage throws.

## Out of scope

Phase 4 items; the deferred minors from the phase 3 reviews; tag-based AMI groups.
