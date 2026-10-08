# Phase 3: read-only AWS provider

Status: decided in chat 2026-10-08 ("AWS provider first", "role_arn + MFA", install boto3 and
moto at the HANDOFF pins). Per the user's standing preference, spec and plan go straight to
execution without a review stop.

Base spec: [`2026-10-06-janitor-poc-design.md`](2026-10-06-janitor-poc-design.md) §2, §4, §6,
§7, §9, §10, §12, §14, §16. This document narrows those sections to what phase 3 builds and
records the decisions they left open.

## Goal

Point Janitor at real AWS accounts and get the same screens, statuses, rules, and simulated
delete flow as mock mode, with three independent locks proving nothing can change in AWS.

## What the user decided

- **Scope:** the AWS provider and everything it needs to be trustworthy: the three locks,
  scan segments with partial failures, `unknown` from failures, throttling and credential
  states in the UI, and a live re-check during simulate. Rules R6, R7, W1, W2, W3, W5,
  "select all N matching", the help panel, and the walkthrough move to **phase 3b**.
- **Credentials:** profiles with `role_arn` and `source_profile`; the user refreshes an MFA
  session on the laptop as usual. Profiles without `role_arn` are refused.
- **Dependencies:** `boto3==1.43.108`; dev `moto[ec2,rds,autoscaling,sts]==5.2.3`. Nothing else.

## Architecture

```
Scanner ──► CloudProvider.list_inventory(on_segment) ─► Inventory (+ segments, unresolved)
              ├─ MockProvider   seed fixture; every segment ok
              └─ AwsProvider
                   ├─ session.py   profile → AssumeRole(session policy) → guarded boto3 Session
                   ├─ guard.py     before-call hook: only Describe*/List*/Get* leave the process
                   ├─ normalize.py raw AWS dicts → Resource/Share/Usage/Database (pure)
                   └─ aws.py       segments across account × region × kind, thread pool
linker(inventory, ctx with failed segments) → status; scanner sets scan ok | partial | failed
plans.simulate → provider.recheck(items) → live skips (AWS mode)
```

The linker, rules, store, graph, and UI keep their shapes. The provider returns raw AWS
shapes; `normalize.py` is the one place they become Janitor records.

## Configuration

- New optional block `scan: { concurrency: 8 }` (1–32).
- In AWS mode, startup checks every account's profile in the local AWS config
  (`AWS_CONFIG_FILE` or `~/.aws/config`): it must exist and have `role_arn` and
  `source_profile`. Any failure stops startup with one message naming each bad profile.
- New validation (both modes): an account that owns `snapshot` must also own `volume`.
  Janitor judges a snapshot by whether its source volume still exists; without that
  account's volumes it would call live snapshots orphaned.

## The three locks (base spec §10)

1. **Interface:** `CloudProvider` has `list_inventory` and `recheck`; both read. No write method.
2. **Session policy:** for each account, `sts:AssumeRole(RoleArn=<profile role_arn>,
   RoleSessionName="janitor-readonly", DurationSeconds=3600, Policy=<below>, ExternalId=<profile
   external_id if set>)`, called with the `source_profile` credentials. `mfa_serial` is not
   sent: the source credentials are already an MFA session. Roles are assumed again on every
   scan and every re-check (chained sessions last an hour at most).

   ```json
   {"Version": "2012-10-17", "Statement": [{"Effect": "Allow",
     "Action": ["ec2:Describe*", "autoscaling:Describe*", "rds:Describe*"], "Resource": "*"}]}
   ```
3. **Runtime guard:** a botocore `before-call` handler registered on every session Janitor
   creates raises `ReadOnlyViolation` before sending any operation whose name does not start
   with `Describe`, `List`, or `Get`. The STS client used for AssumeRole allows exactly one
   extra name, `AssumeRole`.

Each lock has a test: the provider class exposes no other public methods; the Policy parameter
actually sent equals the JSON above; a `DeleteSnapshot` call through a guarded session raises
and the snapshot still exists; every operation a full moto scan sends is in the allowed set.

## Scan segments (base spec §7.5)

A segment is `(account, region, kind)` with kind one of `ami`, `snapshot`, `volume`,
`rds_snapshot`, `database`, `usage`. Each records `ok`, `error_kind`, `error`, `items`,
`duration_ms`.

| Kind | Accounts × regions | Calls (paginated) |
|---|---|---|
| `ami` | owner × its regions | `DescribeImages(Owners=[self])`, `DescribeImageAttribute(launchPermission)` per AMI |
| `snapshot` | owners of `snapshot` | `DescribeSnapshots(OwnerIds=[self])` |
| `volume` | owners of `volume` | `DescribeVolumes` |
| `rds_snapshot` | owners of `rds_snapshot` | `DescribeDBSnapshots`, `DescribeDBClusterSnapshots` (manual, automated, awsbackup) |
| `database` | owners of `rds_snapshot` | `DescribeDBInstances`, `DescribeDBClusters` |
| `usage` | owner in every region, plus every configured account a launch permission names, in that AMI's region if the account is scanned there | `DescribeInstances` (non-terminated), `DescribeLaunchTemplates` + `DescribeLaunchTemplateVersions` (`$Default`, `$Latest`), `DescribeAutoScalingGroups`, `DescribeLaunchConfigurations` |

- Two phases: all `ami`, `snapshot`, `volume`, `rds_snapshot`, `database` segments run in a
  thread pool of `scan.concurrency`; then the `usage` segments, whose pairs come from the
  launch permissions phase one found.
- A failed segment contributes no rows. If any launch-permission read fails, the whole `ami`
  segment for that region fails (an AMI with unknown shares can't be judged).
- An account whose AssumeRole fails fails every one of its segments with that error.
- botocore adaptive retry, 10 attempts.
- Usage rows are kept only for image IDs in the owner's AMI set.
- Launch-template resolution exactly as base spec §7.2. An image given as `resolve:ssm:…`
  becomes an **unresolved reference** `{account, region, ref_type, ref_id, value}` stored on the
  scan and shown on Overview. It does not change any status (risk noted below).
- Rows are held in memory per scan. Streaming page by page is phase 4 (scale).

### Error kinds

| `error_kind` | From | Message shown |
|---|---|---|
| `expired` | `ExpiredToken*`, `RequestExpired`, `NoCredentialsError`, `TokenRetrievalError`, an `InvalidClientTokenId` on AssumeRole | AWS session expired. Refresh your MFA session, then Scan now. |
| `denied` | `AccessDenied*`, `UnauthorizedOperation`, `AuthFailure` | Janitor isn't allowed to call `<service:Operation>` in `<account> · <region>`. Ask for read access, then Scan now. |
| `throttled` | `Throttling*`, `RequestLimitExceeded`, `TooManyRequestsException` after retries | AWS throttled requests in `<account> · <region>`. Scan again in a few minutes. |
| `blocked` | `ReadOnlyViolation` | Janitor stopped a call that isn't read-only. Report this; nothing was sent. |
| `other` | anything else | The error text, then "Scan again; if it repeats, check the server log." |

## Normalization (base spec §7.4)

Pure functions in `normalize.py`, each tested with real AWS response shapes:

- **AMI:** id, `Name`, `CreationDate`, size = sum of EBS `VolumeSize`, `snapshot_ids` from EBS
  mappings, tags, `source_ami_id` from `SourceImageId`, else from a backing snapshot's
  `Copied for DestinationAmi <this> from SourceAmi <src>` description.
- **Snapshot:** id, name = `Name` tag or id, `StartTime`, `VolumeSize`, `StorageTier`
  (`archive` or `standard`), `source_volume_id` (`vol-ffffffff` means none), `linked_ami_id` from
  `Created by CreateImage(i-…) for ami-…` or `Copied for DestinationAmi ami-…`.
- **Volume:** id, name, `CreateTime`, `Size`, `State`, `VolumeType`, `Iops`, `Throughput`,
  `Encrypted`, `attached_instance` from the first attachment.
- **RDS snapshot:** id = ARN, name = identifier, created = `SnapshotCreateTime`, else
  `OriginalSnapshotCreateTime`, else now (still creating); size = `AllocatedStorage`;
  `source_db_id`, `db_kind`.
- **Managed:** `aws:backup:source-resource` tag or an AWS Backup description → `aws_backup`;
  `aws:dlm:lifecycle-policy-id` tag → `dlm`; RDS `SnapshotType` `automated` → `rds_automated`,
  `awsbackup` → `aws_backup`.
- **Shares:** `UserId` → account, `Group: all` → group, `OrganizationArn` → org,
  `OrganizationalUnitArn` → ou.
- Missing optional fields never raise; a missing name falls back to the id.

## Statuses from failures (base spec §6, §7.3)

The linker receives the failed segments and the scanned `(account, region)` pairs.

- **AMI → unknown** when a configured account its launch permissions name: has a failed
  `usage` segment in the AMI's region ("Janitor couldn't read what dev uses in us-east-1"),
  or isn't scanned in that region ("Janitor doesn't scan dev in eu-west-1"). The existing
  public, organization, and unscanned-account cases stay. Proven usage still wins.
- **Snapshot → unknown** when the owner's `ami` segment in its region failed and nothing
  proves use; or when its account's `volume` segment in that region failed and the source
  volume isn't found.
- **RDS snapshot → unknown** (manual only) when its account's `database` segment in that
  region failed.
- Precedence stays `in_use > managed > unknown > orphaned > idle`.

## Scans

- Scan status: `ok` (every segment ok), `partial` (some failed), `failed` (none ok, or an
  exception). Readers use the newest `ok` or `partial` scan. A `failed` scan keeps the
  previous data on screen.
- Segments are written to a new `scan_segments` table as each finishes, so the UI can show
  progress. Unresolved references go in `scans.notes` (JSON). `SCHEMA_VERSION` → 3.
- In AWS mode, the startup scan (empty cache) runs in the background; the server answers at
  once. Mock mode keeps the synchronous startup scan.
- `GET /api/scans/latest` adds `segments` (all, for the newest scan) and
  `progress: {done, failed}`. `GET /api/overview` adds `segments_failed` (failed segments of
  the scan being shown, with messages) and `unresolved`.

## Live re-check during simulate (base spec §9)

`CloudProvider.recheck(items) -> {id: reason}` runs before the audit entry is written, for
every would-delete item (selected and riding along). Mock returns `{}`.

| Type | Re-read | Skip reason |
|---|---|---|
| any | `Describe*` by ID | "It no longer exists." |
| volume | `DescribeVolumes` | "It is now attached to i-…." |
| AMI | `DescribeImageAttribute` | "Its launch permissions changed since the scan." |
| AMI | `DescribeInstances(image-id)` in the owner and each permitted, configured account in its region | "Instance i-… in dev now uses it." |
| any | re-check call failed | "Janitor couldn't re-check it live: <message>." |

Launch templates and ASGs are not re-read (that is a full usage scan); the scan covered them.
A skipped AMI keeps its backing snapshots, exactly as a blocked parent does today.

## UI

- Top bar: the **AWS · read-only** badge (exists); a **Partial scan** warning badge linking to
  Overview when the shown scan is partial.
- Scan now while running: "Scanning · 12 checks done".
- Overview, when the shown scan is partial: a card "Some checks failed" listing each failed
  segment as `account · region · kind` with its message, grouped so a credential failure for
  one account reads as one line ("dev: AWS session expired…"); and "Resources that depend on a
  failed check show as Unknown and can't be deleted."
- Overview, when the newest scan failed outright: "The last scan failed: <message>. Showing
  data from <time>."
- Overview, unresolved references: "3 launch templates pick their image through an SSM
  parameter. Janitor can't read those, so check them before deleting AMIs." with the list.
- `runScan` treats `partial` as finished (not an error).

## Testing

- `normalize`: each mapping above, description parsing (built, copied), copy-source
  fallback, managed detection, launch-template resolution (`$Latest`, `$Default`, explicit,
  `MixedInstancesPolicy`), `resolve:ssm:` → unresolved, missing fields, error classification.
- Locks: as listed above.
- `AwsProvider` on moto, multi-account through AssumeRole into each account's role: an owner
  AMI shared with dev and used by a dev instance; a copied snapshot description; volumes;
  RDS instance and cluster snapshots; pagination across pages; one account whose role can't
  be assumed → its segments fail, others succeed.
- Linker: every failure rule above, and proven use beating a failed segment.
- Scanner and store: `partial` scans are read; all-failed is `failed` and keeps old data;
  segments and notes round-trip; progress counts.
- Simulate: a provider re-check reason moves an item to skipped and keeps its snapshots.
- API: `create_app` with an injected provider; `scans/latest` segments; overview failures.
- Frontend: Overview failed-checks card and unresolved note; Partial scan badge;
  `runScan` accepts `partial`.

## Out of scope (phase 3b or later)

Rules R6, R7, W1, W2, W3, W5; `DescribeDBSnapshotAttributes` (only W5 needs it); select all N
matching; name-regex, source-AMI, source-DB filters; help panel; walkthrough; streaming rows to
the store; `ssm:GetParameter`.

## Risks

- **`resolve:ssm:` images** are listed, not resolved, so an AMI used only that way can look
  orphaned. The Overview note is the mitigation; adding `ssm:GetParameter` is a later decision.
- **Per-AMI `DescribeImageAttribute`** is one call per AMI; with thousands of AMIs a single
  persistent throttle fails the region's `ami` segment (conservative: everything there is
  unknown, nothing becomes deletable).
- **moto fidelity:** moto ignores session policies and some pagination; the session-policy
  test asserts the parameter sent, not AWS's enforcement. The first real scan is the user's.
