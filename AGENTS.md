# Janitor - finds unused AWS AMIs, EBS snapshots, EBS volumes, and RDS snapshots

Explains why each is or isn't safe to delete and walks a **simulated** delete. It never deletes.
A read-only **Deployments** page shows which app version runs in each env (tagged ASGs, ECS services).
Python 3.12 + FastAPI + boto3 + SQLite (`backend/`); React 19 + TS + Vite + Tailwind 4 + Radix
(`frontend/`). Read `docs/HANDOFF.md` first for current status and the next step.

## Quick Start

| Task | Command |
|------|---------|
| First setup (venv, deps, git hooks) | `make setup` |
| Dev: API with reload :8080, UI :5173 | `make dev` |
| Built app on mock data / real AWS (read-only) | `make run` / `make run-aws` |
| Everything CI checks (pytest, ruff, leak check, tsc, vitest) | `make test` |
| One backend / frontend test file | `.venv/bin/python -m pytest backend/tests/test_rules.py -q` / `cd frontend && npx vitest run src/format.test.ts` |
| Regenerate mock data / prices / AWS icons | `make seed` / `make prices` / `make icons` |

Without `config/janitor.yaml` the app runs in mock mode on `config/janitor.example.yaml`.

## Critical Warnings

1. **The repo is public.** Never commit real account IDs, AWS profile names, internal hostnames,
   ticket keys, or company names. Use fake IDs whose 12 digits are all the same (`111111111111`).
   The pre-commit hook runs `scripts/check_private.py --staged`. It rejects any other 12-digit
   number and any term in the gitignored `.private-terms` file. Fixture timestamps use 14 digits
   (`YYYYMMDDhhmmss`) so they never look like account IDs. Real settings live only in the
   gitignored `config/janitor.yaml`: never copy values from it into tracked files.
2. **Read-only, three locks. Never add a write call.** Lock 1: `providers/base.py` `CloudProvider`
   has read methods only. Lock 2: `providers/session.py` assumes every role with a session policy
   that allows only `ec2/autoscaling/rds/ecs:Describe*` and `ecs:List*`. Lock 3:
   `providers/guard.py` rejects any operation not named `Describe*`/`List*`/`Get*` before it is sent. Each lock has a test.
   Deletes exist only as plans and audit entries (`plans.py`).
3. **Ask before** adding a dependency (all pins are exact), pushing, or merging.
4. **The base spec is partly superseded.** `docs/superpowers/specs/2026-10-06-*` still says
   Cloudscape, docker compose, and "launch templates make an AMI in use". In reality the UI kit is
   in-repo (`frontend/src/ui/`), there is no container yet, and **only instances** make an AMI
   `in_use` (templates/ASGs/launch configs add warning W6). Newer specs win.

## Mental Model

```text
provider.list_inventory()      mock.py (fixtures/seed.json) | aws.py -> normalize.py (only file that knows AWS field names)
  -> linker.link()             status + one-sentence reason per resource (pure)
  -> linker.references()       W6 "Referenced" text for AMIs that templates/ASGs only name
  -> pricing.apply_costs()     rates from fixtures/prices.json, fallback config.pricing
  -> store.save_inventory()    SQLite, every row keyed by scan_id
  -> scanner.recompute_rules() rules.evaluate(); also run at startup, so config edits apply without a rescan
  -> main.py (FastAPI /api/*)  -> frontend/src/api.ts
```

**AWS scan, two phases (`providers/base.py`):** the admin account's AMIs, snapshots, and volumes in
the admin's regions come first. Member accounts are the AMIs' launch-permission principals plus
`config.accounts`, minus `ignore_accounts`, which are never contacted. Every hop starts from the
admin profile's source login, with no role chaining: the scan assumes the admin role, then
`member_role` in each other account. An account entry can override that with its own `role`, its
own `profile` (whose `role_arn` the scan uses), and its own `regions`. Phase two reads usage in
the admin account, then each member's lists and usage in its own regions. It also checks a
member's usage in every region where an admin AMI is shared with it. Each account × region ×
kind is a `Segment`; a failed segment makes the affected resources `unknown`.

## Business Rules

| Rule | Constraint | Where |
|------|-----------|-------|
| Status precedence | `in_use > managed > unknown > orphaned > idle` | `linker.py` |
| AMI in use | An instance (running or stopped) launched from it, in a permitted account, **in its own region**. Launch permissions are region-scoped; a copy is a new AMI ID with its own snapshots. | `linker.py` |
| Rule outcome | Strictest wins: `block > warn > pass`. Only block/warn results are stored. | `rules.py` |
| Blocks | R1 in use, R2 unknown, R3 AWS-managed, R4 protected tag (case-insensitive key and value), R5 younger than `min_age_days` | `rules.py` |
| Warns | W4 no `owner` tag, W6 referenced by template/ASG/launch config, W7 shared with an `ignore_accounts` account (it would otherwise be `unknown`) | `rules.py` |
| Typed confirm | Typing `delete` is required when the plan has at least `typed_confirm_min_items` deletable items, any warn result, or an `env=prod` tag | `plans.py` `_needs_typing` |
| Readable scans | Readers use the newest `ok` **or `partial`** scan (`READABLE`); only the two newest scans' data are kept; the audit log is never pruned | `store.py` |
| Simulate | Returns 409 if the scan **or the config** changed since the plan; AWS mode re-checks items live first | `plans.py`, `aws.py` |

## Conventions

| Area | Rule |
|------|------|
| Help text | Status/rule wording comes from `definitions.py` + `rules.py` via `GET /api/meta`. Never hardcode it in the UI. |
| UI copy | Sentence case; buttons start with a verb; errors say what happened, then what to do. No "successfully", "please", or `!`. Enforced by `frontend/src/copy.test.ts`. |
| Error messages | Failed-check text lives in `scanner.segment_message()`. Name the account, role, or permission involved. |
| Purity | `linker.py`, `normalize.py`, `graph.py` do no I/O. Keep AWS calls in `providers/aws.py`. |
| Tests | AWS paths use moto (`tests/aws_helpers.py`). `tests/helpers.py` `NOW` equals the seed's anchor, so ages are exact. Write tests first. |
| Python | ruff (E, F, I, UP, B), line length 100. Use `httpx2`, not `httpx`, for `TestClient`. |
| Comments | Sparse. Docstrings explain why; each module's docstring is its spec. Read it before editing. |
| Workflow | Spec in `docs/superpowers/specs/`, plan in `docs/superpowers/plans/` (dated), one branch per phase, conventional commits in plain English (`fix(linker): join two references with and`). Update `docs/HANDOFF.md` when a phase ends. |
| TLS proxy | On macOS the Makefile exports keychain certs for `SSL_CERT_FILE` / `AWS_CA_BUNDLE`. Don't disable verification. |

## Related Context

- `README.md` - running against AWS, config layout (`admin`, `member_role`, `accounts`, `ignore_accounts`)
- `docs/HANDOFF.md` - status, next step, verified dependency pins
- `docs/superpowers/specs/` - design specs; the newest phase spec wins over older ones
- `docs/superpowers/plans/2026-10-07-janitor-roadmap.md` - four-phase roadmap
