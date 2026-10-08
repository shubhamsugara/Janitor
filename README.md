# Janitor

Finds unused AMIs, EBS snapshots, EBS volumes, and RDS snapshots, explains why each one is
or isn't safe to delete, and walks a simulated delete flow. It never deletes anything.

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

Janitor needs one AWS profile: the admin account's, which owns the AMIs. From there it assumes one
role name (`member_role`) in every other account. It finds those accounts in the AMIs' launch
permissions, plus any you list. Every hop carries a session policy that allows only
`ec2:Describe*`, `autoscaling:Describe*`, and `rds:Describe*`; the admin hop may also assume
`member_role`, and nothing else. A runtime guard stops any call that isn't a Describe, List, or Get
before it is sent.

1. Copy `config/janitor.example.yaml` to `config/janitor.yaml` (gitignored). Set `admin` (account
   ID, display name, profile, regions) and `member_role`. `accounts` is optional: display names,
   and accounts to scan even if no AMI is shared with them.
2. The admin profile in your AWS config needs `role_arn` and `source_profile`. `member_role` must
   exist in each account and trust the admin role.
3. Refresh your MFA session for the source profile as usual.
4. `make run-aws`. The first scan runs in the background. An account whose role can't be assumed
   shows as a failed check, and AMIs shared with it show as Unknown.

An AMI is **in use** only when an instance (running or stopped) was launched from it. A launch
template, Auto Scaling group, or launch configuration that only names it adds a **Referenced**
warning, and deleting it then requires typing `delete`.

Behind a TLS-inspecting proxy, `make run-aws` on macOS trusts the system keychain's certificates
(through `AWS_CA_BUNDLE`). Elsewhere, set `AWS_CA_BUNDLE` to your organization's CA bundle.
