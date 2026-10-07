# Session handoff

Read this first, then the spec.

## Status

- **Design spec approved:** [`docs/superpowers/specs/2026-10-06-janitor-poc-design.md`](superpowers/specs/2026-10-06-janitor-poc-design.md) (commit `fa5f040`).
- **No code yet.** No implementation plan written yet.
- The original vision docs moved to `test-docs/` (that move is not committed yet).

## Next step

Write the implementation plan with the `superpowers:writing-plans` skill. Split the
spec into three plans, each producing working, testable software on its own. Write
plan 1 first and save it to `docs/superpowers/plans/`.

1. **Backend core on mock data:** config, models, MockProvider + seed fixture
   (`scripts/make_seed.py`), store (SQLite), linker, rules, definitions,
   plan/simulate, FastAPI routes, leak check (`scripts/check_private.py`).
2. **UI + container:** React + TypeScript + Vite + Cloudscape SPA, base-path
   handling, Dockerfile, `docker-compose.yml`, Makefile, Playwright end-to-end test.
3. **Read-only AWS provider:** assume-role with the Describe-only session policy,
   the botocore guard, moto tests, live re-check in simulate.

After the plan is reviewed, the user chooses the execution method
(subagent-driven or native) before any code is written.

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
