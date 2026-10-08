# Janitor

Finds unused AMIs, EBS snapshots, EBS volumes, and RDS snapshots, explains why each one is
or isn't safe to delete, and walks a simulated delete flow. It never deletes anything. Its
Deployments page shows which version of each app runs in each env.

It runs on mock data with fake account IDs, or reads real AWS accounts read-only. See
[`docs/superpowers/plans/2026-10-07-janitor-roadmap.md`](docs/superpowers/plans/2026-10-07-janitor-roadmap.md).

## Run it

Needs Python 3.12 (through [uv](https://docs.astral.sh/uv/)) and Node 22.12 or later.

    make setup   # once
    make run     # builds the UI, serves everything at http://127.0.0.1:8080

For development, `make dev` runs the API with reload on :8080 and the UI on
http://127.0.0.1:5173. `make test` runs the backend tests, lint, leak check, and type check.

Without `config/janitor.yaml`, Janitor uses `config/janitor.example.yaml` in mock mode.

## Run it against AWS (read-only)

Janitor needs one AWS profile: the admin account's, which owns the AMIs. Like your own AWS
config, it starts every hop from that profile's source login (your MFA session): the admin role,
and `member_role` in every other account (an account can name its own `role`). It finds those
accounts in the AMIs' launch permissions, plus any you list. Every session carries a policy that
allows only `ec2:Describe*`, `autoscaling:Describe*`, `rds:Describe*`, `ecs:Describe*`, and
`ecs:List*`, so no Janitor session can assume anything further, and a runtime guard stops any
call that isn't a Describe, List, or Get before it is sent.

1. Copy `config/janitor.example.yaml` to `config/janitor.yaml` (gitignored). Set `admin` (account
   ID, display name, profile, regions) and `member_role`. `accounts` is optional: display names,
   a per-account `profile` (Janitor uses that AWS profile's `role_arn` and `role_session_name`;
   it must use the same source login as the admin profile) or `role` when it differs from
   `member_role`, `regions` when the account uses other regions than the admin, and accounts to
   scan even if no AMI is shared with them. An account's usage is also checked in any region where
   an admin AMI is shared with it, so "nothing uses it" is always proven.
2. The admin profile in your AWS config needs `role_arn` and `source_profile`. Each account's
   role must trust that source login, as your per-account profiles already rely on.
3. Refresh your MFA session for the source profile as usual.
4. `make run-aws`. The first scan runs in the background. An account whose role can't be assumed
   shows as a failed check, and AMIs shared with it show as Unknown.

An account you can't reach (no role, or someone else's) keeps the AMIs shared with it Unknown.
If you're sure nobody there needs them, list it under `ignore_accounts`: Janitor stops contacting
it, and those AMIs get warning W7 instead of being held back.

An AMI is **in use** only when an instance (running or stopped) was launched from it. A launch
template, Auto Scaling group, or launch configuration that only names it adds a **Referenced**
warning, and deleting it then requires typing `delete`.

### Delete rules you can tune

Under `policy` in `janitor.yaml`:

- `keep_newest_per_name_group` (default 3): R6 never offers the newest AMIs of a name group, per
  account and region. A group is the name minus a trailing date or version
  (`ami_name_group_pattern`); a name without one is its own group.
- `keep_name_patterns`: regexes; R7 keeps any AMI whose name matches one.
- `source_with_live_copies` and `rds_last_copy` (`warn` or `block`): W1 for an AMI copied to
  other regions, W2 for the newest snapshot of a deleted database.

W5 reads who can restore each manual RDS snapshot (`rds:DescribeDBSnapshotAttributes` and
`rds:DescribeDBClusterSnapshotAttributes`, inside `rds:Describe*`).

### Deployments

The Deployments page is a grid of apps by env and region, from the same scan:

- **EC2 apps** are Auto Scaling groups your deploy tool tagged with a state (`deploy-state` by
  default: `deploying`, `deployed`, `undeploying`, `undeployed`). Janitor reads their app, env,
  version, and deployment ID tags, the launch template version they pin, and its AMI. Other
  groups are ignored. Instances in no Auto Scaling group are listed too, marked standalone.
- **ECS apps** are services, with the version from their task definition's tags (or the image
  tag). A service scaled to 0 is shown Stopped; beside a running service for the same app (the
  idle side of a blue/green pair) it is an earlier version.

The tag names are set under `deployments.tags` in `janitor.yaml`. For ECS, each role Janitor
assumes needs `ecs:ListClusters`, `ecs:ListServices`, `ecs:DescribeServices`, and
`ecs:DescribeTaskDefinition`. Without them only ECS shows a failed check; AMI results don't
change.

Behind a TLS-inspecting proxy, `make run-aws` on macOS trusts the system keychain's certificates
(through `AWS_CA_BUNDLE`). Elsewhere, set `AWS_CA_BUNDLE` to your organization's CA bundle.
