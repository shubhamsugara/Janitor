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
- Run it: `make setup` once, then `make run` → http://127.0.0.1:8080 (mock data).

## Next step

1. Phase 2 is built on branch `phase-2`; the user decides how to integrate it.
2. Next: plan phase 3 (read-only AWS provider) from the roadmap. `make prices` and `make icons`
   refresh the price list and the local AWS icons.
3. Behind a TLS-inspecting proxy, `make icons` (and possibly `make prices`) fails with
   `CERTIFICATE_VERIFY_FAILED`. Point Python at the machine's trusted roots instead of turning
   verification off: `security find-certificate -a -p /Library/Keychains/System.keychain
   /System/Library/Keychains/SystemRootCertificates.keychain > /tmp/roots.pem`, then
   `SSL_CERT_FILE=/tmp/roots.pem make icons`.

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
