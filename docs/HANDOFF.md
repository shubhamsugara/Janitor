# Session handoff

Read this first, then the spec.

## Status

- **Design spec approved:** [`docs/superpowers/specs/2026-10-06-janitor-poc-design.md`](superpowers/specs/2026-10-06-janitor-poc-design.md) (commit `fa5f040`).
- **Roadmap (4 phases):** [`docs/superpowers/plans/2026-10-07-janitor-roadmap.md`](superpowers/plans/2026-10-07-janitor-roadmap.md)
  — 1 MVP, 2 bug fixes, 3 new features, 4 final product.
- **Phase 1 (MVP)** is merged to `main` locally (not pushed).
- **Phase 2** is built on branch `phase-2` from
  [`docs/superpowers/plans/2026-10-07-phase-2.md`](superpowers/plans/2026-10-07-phase-2.md):
  linkage diagram and "used by", costs from the AWS price list (`fixtures/prices.json`), stats,
  filters in the URL, CSV and PDF export, five environment accounts, and the phase 1 fixes.
- **UI refresh** on branch `ui-refresh` from
  [`docs/superpowers/plans/2026-10-07-ui-refresh.md`](superpowers/plans/2026-10-07-ui-refresh.md):
  Cloudscape replaced by Tailwind 4 + Radix + Recharts (in-repo kit in `frontend/src/ui/`);
  sidebar layout, KPI cards, filter pills, slide-over detail drawer, light and dark themes.
- **Phase 3 (AWS provider)** on branch `phase-3` from
  [`docs/superpowers/plans/2026-10-08-phase-3-aws-provider.md`](superpowers/plans/2026-10-08-phase-3-aws-provider.md):
  read-only `AwsProvider` (AssumeRole with a Describe-only session policy, botocore guard), scan
  segments with partial failures, `unknown` from failed checks, live re-check before a simulated
  delete, and scan-health UI. Tested on moto; **the first real scan is the user's** (`make run-aws`).
  Rules R6/R7/W1/W2/W3/W5, select-all-matching, help panel, and walkthrough are phase 3b.
- **Phase 3 fixes** (same branch) from
  [`docs/superpowers/plans/2026-10-08-phase-3-hub-and-usage.md`](superpowers/plans/2026-10-08-phase-3-hub-and-usage.md),
  after the first real scan: config is now `admin` + `member_role` + optional `accounts` names
  (the old `owner`/`owns` layout is rejected with a migration message); accounts are discovered
  from launch permissions and reached from the same source login as the admin (per-account `role` override); only instances make an AMI in use
  (templates, ASGs, launch configs add warning W6 "Referenced"); the diagram shows an AMI's own
  links, with usage grouped under accounts.
- **Config follow-ups** (same branch, after real scans): an account entry can name an AWS
  `profile` (its role_arn and role_session_name win) and its own `regions` (default: admin's);
  usage is also checked wherever an admin AMI is shared with the account. `ignore_accounts` are
  never contacted and don't hold an AMI back (warning W7 instead). An account listed twice in
  janitor.yaml is refused with the line number. Each page's Account filter lists only accounts
  that have that type, and hides when there is one.
- **Deployments** on branch `deployments` from
  [`docs/superpowers/plans/2026-10-08-deployments.md`](superpowers/plans/2026-10-08-deployments.md):
  a read-only page (sidebar, below Resources) of apps × env · region showing the live version.
  EC2 apps are ASGs tagged with a deploy state (read from the usage check's pages, with launch
  template version and AMI); ECS apps are services (new `ecs` check; the session policy adds
  `ecs:Describe*`/`ecs:List*`). Tag names live under `deployments.tags`. Checked by the user on a
  real scan, then fixed: columns are account · region (not the env tag), a run status beside the
  deploy state, instances in no ASG listed as standalone, counts in every cell, even column
  widths, a lone ECS service at 0 is Stopped (not an earlier version), and a glossary on How
  Janitor decides. **Follow-ups, not built:** target group membership for instances (needs
  `elasticloadbalancing:Describe*`, the user's call), ECS rolling history from earlier task
  definition revisions, and scheduled/task-only apps (needs `events:List*`).
- **Phase 3b** on branch `phase-3b` from
  [`docs/superpowers/plans/2026-10-08-phase-3b.md`](superpowers/plans/2026-10-08-phase-3b.md):
  rules R6 (keep the 3 newest per AMI name group), R7, W1, W2, W3, W5 from a per-scan rule
  context; manual RDS snapshot shares; name pattern, source AMI, and source DB filters;
  "Select all N matching" resolved on the server (up to 5,000); a help panel with Info links; and
  a five-step first-run walkthrough, replayable from the Help menu.
- Run it: `make setup` once, then `make run` → http://127.0.0.1:8080 (mock data), or
  `make run-aws` with a real `config/janitor.yaml` (see README).

## Next step

1. Phases 1–3 and Deployments are merged to `main` (not pushed). Phase 3b is on `phase-3b`.
2. Next: try phase 3b on a real scan (`make run-aws`), decide how to integrate it, then plan
   phase 4. `make prices` and `make icons` refresh the price list and the local AWS icons.
3. Behind a TLS-inspecting proxy, Python alone fails with `CERTIFICATE_VERIFY_FAILED`. On macOS,
   `make prices` and `make icons` handle it: they export the system keychain's certificates to
   `.venv/trusted-certs.pem` and point `SSL_CERT_FILE` at it (verification stays on). Elsewhere,
   set `SSL_CERT_FILE` to your organization's CA bundle. boto3 reads `AWS_CA_BUNDLE` instead;
   `make run-aws` sets it from the keychain on macOS.

## Verified dependency pins (Python 3.12, checked 2026-10-06)

| Package | Version |
|---|---|
| fastapi | 0.142.2 |
| uvicorn[standard] | 0.54.0 |
| boto3 | 1.43.108 |
| pydantic | 2.13.5 |
| pyyaml | 6.0.3 |
| pytest (dev) | 9.1.1 |
| httpx2 (dev) | 2.13.1 |
| moto[ec2,rds,autoscaling,sts] (dev) | 5.2.3 |
| ruff (dev) | 0.16.10 |

Use **`httpx2`, not `httpx`**: with this Starlette version, `fastapi.testclient`
warns that `httpx` is deprecated. Checked: `TestClient` works with `httpx2` and
raises no deprecation warning; moto does not need `httpx`.

Python 3.12 is not installed system-wide (3.13 and 3.14 are); `uv` is, so use
`uv venv --python 3.12`.

## Rules for this repo

- **The repo is public.** Never commit real account IDs, AWS profile names,
  internal hostnames, or ticket keys. Real settings go in the gitignored
  `config/janitor.yaml`; only `config/janitor.example.yaml` with fake IDs
  (`111111111111`) is committed.
- **Ask before pushing** to GitHub.
- **Ask before adding any dependency** not listed in spec §14.
