# Session handoff

Read this first, then the spec.

## Status

- **Design spec approved:** [`docs/superpowers/specs/2026-10-06-janitor-poc-design.md`](superpowers/specs/2026-10-06-janitor-poc-design.md) (commit `fa5f040`).
- **Roadmap (4 phases):** [`docs/superpowers/plans/2026-10-07-janitor-roadmap.md`](superpowers/plans/2026-10-07-janitor-roadmap.md)
  — 1 MVP, 2 bug fixes, 3 new features, 4 final product.
- **Phase 1 (MVP) built** on branch `phase-1-mvp` from
  [`docs/superpowers/plans/2026-10-07-phase-1-mvp.md`](superpowers/plans/2026-10-07-phase-1-mvp.md):
  84 backend tests pass, `tsc` clean, UI checked in a browser. A whole-branch review
  found 4 important issues, all fixed with tests. Not merged to `main`, not pushed.
- Run it: `make setup` once, then `make run` → http://127.0.0.1:8080 (mock data).

## Next step

1. The user tries the MVP and decides how to integrate the branch (merge, PR, or keep).
2. Write the phase 2 (bug fixes) plan. Start from these known items:
   - Status column text wraps ("Orph/aned"); "Simulate deleting 1 resources?" pluralization.
   - Resources header shows the whole filtered set's size and cost next to "N orphaned".
   - Mixed popup counts include backing snapshots ("the other 4" for 2 AMIs).
   - Typed-confirmation hint hardcodes "10"; serve `typed_confirm_min_items` via `/api/meta`.
   - Status popover says "Can be deleted" even when a rule blocks it.
   - Missing-IDs warning doesn't say what to do.
   - Empty protected-tag value or unquoted `true` in YAML gives an unclear config error.
   - Selecting an AMI and its own snapshot blocks the snapshot (API only).
   - Pre-commit leak check reads the working tree, not staged content.
   - List fetches aren't sequenced; Scan now doesn't re-poll a scan started elsewhere;
     a huge `page` value returns 500.
   - Frontend tests (Vitest) for popup variants and selection.

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
