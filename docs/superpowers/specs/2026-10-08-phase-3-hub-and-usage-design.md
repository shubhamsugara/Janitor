# Phase 3 fixes: hub access, instance-based "in use", focused diagram

Status: decided in chat 2026-10-08 after the first real scan. The user answered two rounds of
questions and said "let's try this first" (no further issues for this round). Builds on
[`2026-10-08-phase-3-aws-provider-design.md`](2026-10-08-phase-3-aws-provider-design.md); where
the two disagree, this document wins.

## Revision (2026-10-08, after checking the user's AWS config)

The user's profiles assume every account's role directly from one source login; none chain
through admin, so member roles trust that login, not the admin role. Decided: **every hop starts
from the admin profile's source_profile** (admin role and member roles side by side, no
chaining), every session gets the Describe-only `SESSION_POLICY` (the admin no longer needs
`sts:AssumeRole`), and `accounts.<id>.role` overrides `member_role` per account. Accounts fail
independently: a denied admin hop no longer blocks the members. Sections below that say "from
admin" read as "from the source login".

## What went wrong in the first real scan

1. **Diagram floods.** Selecting an AMI walks two hops both ways: up to the AMI it was copied
   from, then out to every sibling made from that source. Base AMIs are shared by the EC2, ECS,
   and ECS GPU lines, so nearly every AMI appears.
2. **"In use" is wrong.** Any launch template's default or latest version, any ASG (even at zero
   capacity), or any launch configuration naming an AMI made it in use, so AMIs no instance
   runs showed as in use.
3. **The account model doesn't fit.** One profile and an `owns` list per account. In reality the
   admin account owns the AMIs, shares them with every account in the region, and can assume a
   role into every account. The user needs, per AMI: which instances use it, in which accounts.

## Decisions (user)

| Topic | Decision |
|---|---|
| In use | An instance (running or stopped) launched from the AMI, in an account allowed to launch it, in its region. |
| Templates, ASGs, launch configs | Don't make it in use. They add a **Referenced** warning; deleting requires typing `delete`. |
| Reaching accounts | Hub: Janitor assumes the admin role (profile, as today), then from admin assumes one role name that exists in every account. |
| Which accounts | Every account in the admin AMIs' launch permissions, plus any listed in config. |
| Other accounts list | EBS volumes, EBS snapshots, RDS snapshots (and are checked for usage). Admin lists AMIs, snapshots, volumes. |
| Regions | Every account in the admin's regions. |
| Diagram | The AMI's own links only: snapshots, accounts it's shared with and the instances using it there, references, its copies. No source or sibling AMIs. |

## Configuration

```yaml
provider: aws
admin:
  account: "111111111111"
  name: tools                 # display name (default "admin")
  profile: example-tools      # needs role_arn + source_profile (unchanged rule)
  regions: [us-east-1, us-west-2, eu-west-1]
member_role: example-janitor-read   # assumed from admin in every other account
accounts:                     # optional display names; listed accounts are always scanned
  "222222222222": { name: dev }
policy: ...                   # unchanged
pricing: ...                  # unchanged
scan: { concurrency: 8 }
```

- A config with the old top-level `owner` key fails with: "janitor.yaml uses the old layout
  (owner, and accounts with profile and owns). Move to admin, member_role, and accounts names:
  see config/janitor.example.yaml."
- `member_role` must be a valid IAM role name (`[\w+=,.@-]{1,64}`). Required in AWS mode
  (checked with the profile at startup); optional in mock mode.
- `Config.account_name(id)`: the admin's name for the admin, the listed name, else the ID.
- `Config.regions` = `admin.regions`. Per-account region overrides and `owns` are removed.

## Access (locks 2 and 3, extended)

1. Source credentials → `AssumeRole(admin role_arn)` with the **admin session policy**:
   `ec2:Describe*`, `autoscaling:Describe*`, `rds:Describe*`, and `sts:AssumeRole` on
   `arn:aws:iam::*:role/<member_role>` only.
2. Admin session → `AssumeRole(arn:aws:iam::<account>:role/<member_role>)` with the existing
   Describe-only **session policy**, session name `janitor-readonly`, 3600 s.
3. The guard is installed on every session. Sessions that call STS allow exactly one extra
   operation, `AssumeRole`; member sessions allow none.

A member account whose role can't be assumed fails all its checks with `error_kind="denied"`
or `"expired"` and `error="sts:AssumeRole"`; its message is "Janitor can't assume <role> in
<account>. Check that the role exists there and trusts the admin account, then Scan now."

## Scan plan

1. **Admin:** `ami`, `snapshot`, `volume`, `usage` in each region (pool).
2. **Discover** accounts = account principals in the AMIs' launch permissions ∪ listed accounts,
   minus admin. Public, organization, and OU shares are not accounts and stay unknown.
3. **Members:** `snapshot`, `volume`, `rds_snapshot`, `database`, `usage` in each region (pool).

The mock provider follows the same plan. The seed lists `unreachable` accounts; the mock
reports their checks failed (`denied`, `sts:AssumeRole`) so the showcase still shows an AMI that
can't be proven unused.

## Statuses

- **AMI in use:** a permitted account's instance in the AMI's region. Reason as today
  ("Used by instance dev-api-1 in dev and 2 more.").
- **Referenced** (new resource field `referenced_by`, text): when no instance uses it but a
  permitted account's launch template, ASG, or launch configuration in its region names it, e.g.
  "Launch template uat-api v3 in uat still names it, so its next launch would fail." The status
  then follows the normal unknown / managed / orphaned / idle rules.
- **Unknown from coverage:** an account in the AMI's launch permissions without a successful
  `usage` check in the AMI's region (failed, or not scanned) makes it unknown; public, org, OU as
  today. "Scanned" comes from the scan's usage segments, not from config.
- Snapshot rule "owner's AMI list failed" now reads "admin's".

## Rules

New **W6 Referenced** (warn, AMI): message = `referenced_by`. Any warning already requires typed
confirmation, so no change to the dialog logic.

## Diagram (`graph.py`)

- **AMI root:**
  - Upstream: its snapshots.
  - Downstream: one node per account it is shared with that has usage or couldn't be checked. Admin is shown as an account node only when it has usage.
  - Each account node leads to its instances (`used_by`) and its templates, ASGs, and launch configs (`references`).
  - Accounts that were checked and use nothing collapse into one node: "N accounts · not used".
  - Accounts that couldn't be checked are labelled "<name> · couldn't check".
  - Copies of this AMI go downstream (`copied_to`).
  - **No** source AMI and no siblings.
- **AMI reached from another node** (a copy, or the AMI behind a snapshot): only its account and usage nodes, never its snapshots or copies, so the walk never fans out through AMI lineage.
- **Snapshot root:** its backing AMIs, which expand as non-root AMIs, and its source volume.
- **Volume and RDS:** unchanged.
- **`used_by` summary:**
  - Instances first: "Used by 2 running instances and 1 stopped instance in dev and prd."
  - Then references: "Also named by 1 launch template in uat."
  - `active` counts running instances; `total` counts instances.
- **Share impact in the plan:** "scanned" means the account has an ok usage check in that region.

## API and UI

- `GET /api/meta` `accounts`: the admin, the listed accounts, and every account in the newest readable scan's segments, as `{id, name, regions}`. The `owns` field is removed. `owner` keeps its shape (`account`, `regions`) and holds the admin's values.
- Definitions text for AMI `in_use` changes to the instance rule; W6 appears in the rules list.
- Diagram: a `references` edge style (dashed, muted) and a label for it.

## Testing

- Config: new layout loads; old layout rejected with the message; member_role validation.
- Session (moto): AssumeRole sequence admin → member with the two policies; guard on both;
  `check_profiles` checks the admin profile and member_role.
- AwsProvider (moto): an account found only in launch permissions is scanned through the hub; a
  member whose role can't be assumed fails only its checks; its shared AMI is unknown.
- Linker: launch-template-only AMI is idle/orphaned with `referenced_by`; instance makes in use;
  an account in launch permissions without a usage segment → unknown.
- Rules: W6 warns with the reference text.
- Graph: AMI root has no source or sibling AMIs; usage hangs under account nodes; unused accounts
  collapse; a copy reached downstream expands only to usage.
- Mock: the seed's unreachable account fails; the scan is partial; `app-web` (templates/ASG only)
  is idle with W6.

## Out of scope

Everything deferred from the phase 3 review, phase 3b rules, per-account role overrides.
