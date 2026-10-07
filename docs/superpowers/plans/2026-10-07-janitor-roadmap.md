# Janitor roadmap

The design spec ([`2026-10-06-janitor-poc-design.md`](../specs/2026-10-06-janitor-poc-design.md))
describes the finished product. We deliver it in four phases. Each phase ends with an app
you can run.

| Phase | Goal | Plan |
|---|---|---|
| 1. MVP | A working app on mock data: inventory, statuses with reasons, core rules, simulated delete flow, audit, basic UI | [`2026-10-07-phase-1-mvp.md`](2026-10-07-phase-1-mvp.md) |
| 2. Bug fixes | Fix what using the MVP turns up; fill test gaps; error and empty states | Written after the MVP has been used |
| 3. New features | Read-only AWS, remaining rules, richer filters and selection, help and walkthrough | Written after phase 2 |
| 4. Final product | Container, ECS-ready base path, scale and performance, CI, polish | Written after phase 3 |

## Phase 1: MVP (this round)

- Mock provider with a generated seed fixture (fake IDs only).
- Statuses for AMIs, EBS snapshots, EBS volumes, and RDS snapshots, each with a one-sentence reason.
- Rules R1–R5 (block) and W4 (warn); strictest wins.
- SQLite store; scan on startup and on **Scan now**.
- Plan → popup (all blocked / mixed / none blocked) → simulate → audit. Nothing is deleted.
- React + Cloudscape UI: overview, one table per type, detail panel, delete popup, audit, "How Janitor decides".
- Leak check for the public repo.

## Phase 2: bug fixes

Scope comes from using the MVP. Known candidates:
- Frontend tests (Vitest + Testing Library): popup variants, selection model.
- UI states from spec §12: skeleton loading, empty type, filters match nothing.
- A review of every message against the copy rules (spec §12).

## Phase 3: new features

- AwsProvider: assume-role with the Describe-only session policy, the botocore guard, moto
  tests (spec §10, §16). Provider returns raw AWS shapes, normalized in one place.
- Scan segments per account × region × kind, partial failures, `unknown` from failures,
  throttling and credential states (spec §7.5, §12).
- Snapshot description parsing and launch-template version resolution (spec §7.2, §7.4).
- Rules R6, R7, W1, W2, W3, W5 (spec §8).
- "Select all N matching" with `{filter, include, exclude}`; filters for name regex, source
  AMI, and source DB; filters in the URL (spec §9, §11, §12).
- Live re-check during simulate in AWS mode (spec §9).
- Help panel, Info links, first-run walkthrough (spec §13).

## Phase 4: final product

- Multi-stage Docker image, `docker-compose.yml`, base-path handling (`<base href>`
  injection, relative URLs) (spec §12, §14).
- Scale: indexes and the 200k-snapshot performance test (list + count < 500 ms) (spec §5, §16).
- CI on GitHub Actions: ruff, pytest, vitest, Playwright, image build, leak check, gitleaks.
- Playwright end-to-end test of the main flow.
- Polish: dark mode, top bar, keyboard shortcuts (`/`, `Esc`).
