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

Janitor reaches each account through `sts:AssumeRole` with a session policy that allows only
`ec2:Describe*`, `autoscaling:Describe*`, and `rds:Describe*`, so even an admin role can only
describe. A runtime guard also stops any call that isn't a Describe, List, or Get before it is sent.

1. Copy `config/janitor.example.yaml` to `config/janitor.yaml` (gitignored) and fill in your
   account IDs, regions, and AWS profile names.
2. Each profile in your AWS config needs `role_arn` and `source_profile`. Janitor refuses to start
   and names any profile that doesn't have them.
3. Refresh your MFA session for the source profile as usual.
4. `make run-aws`. The first scan starts in the background; the Overview shows progress and any
   checks that failed. Resources that depend on a failed check show as Unknown and can't be deleted.

Behind a TLS-inspecting proxy, `make run-aws` on macOS trusts the system keychain's certificates
(through `AWS_CA_BUNDLE`). Elsewhere, set `AWS_CA_BUNDLE` to your organization's CA bundle.
