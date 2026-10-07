# Session handoff

Read this first, then the spec.

## Status

- **Design spec approved:** [`docs/superpowers/specs/2026-10-06-janitor-poc-design.md`](superpowers/specs/2026-10-06-janitor-poc-design.md) (commit `fa5f040`).
- **Roadmap (4 phases):** [`docs/superpowers/plans/2026-10-07-janitor-roadmap.md`](superpowers/plans/2026-10-07-janitor-roadmap.md)
  — 1 MVP, 2 bug fixes, 3 new features, 4 final product.
- **Phase 1 plan written (5 tasks), pending review:**
  [`docs/superpowers/plans/2026-10-07-phase-1-mvp.md`](superpowers/plans/2026-10-07-phase-1-mvp.md).
  Its code has not been run yet; executors fix small mistakes as they go.
- **No code yet.**

## Next step

The user reviews the phase 1 plan and chooses the execution method (subagent-driven
or native). Then execute it task by task. Plans for phases 2–4 are written after the
previous phase is in use.

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
