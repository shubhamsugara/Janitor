# Janitor

Finds unused AMIs, EBS snapshots, EBS volumes, and RDS snapshots, explains why each one is
or isn't safe to delete, and walks a simulated delete flow. It never deletes anything.

This is the MVP: it runs on mock data with fake account IDs. See
[`docs/superpowers/plans/2026-10-07-janitor-roadmap.md`](docs/superpowers/plans/2026-10-07-janitor-roadmap.md).

## Run it

Needs Python 3.12 (through [uv](https://docs.astral.sh/uv/)) and Node 22.12 or later.

    make setup   # once
    make run     # builds the UI, serves everything at http://127.0.0.1:8080

For development, `make dev` runs the API with reload on :8080 and the UI on
http://127.0.0.1:5173. `make test` runs the backend tests, lint, leak check, and type check.

Without `config/janitor.yaml`, Janitor uses `config/janitor.example.yaml` in mock mode.
