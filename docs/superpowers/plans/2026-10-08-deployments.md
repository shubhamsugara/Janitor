# Deployments plan

Spec: [`2026-10-08-deployments-design.md`](../specs/2026-10-08-deployments-design.md). Branch
`deployments`. Tests first in every task; `make test` green before each commit.

1. **Model and config.** `models.Deployment`, `Inventory.deployments`; `config.Deployments` /
   `DeploymentTags` with defaults; example config documents them. Tests: config defaults and
   overrides.
2. **Normalize (pure).** `normalize.asg_deployments(groups, templates, versions, configs, account,
   region, tags, fallback_env)` and `normalize.ecs_deployment(service, taskdef, cluster, account,
   region, tags, fallback_env)`. Tests in `test_normalize.py`.
3. **Read-only locks.** Session policy adds `ecs:Describe*`, `ecs:List*`; `OPERATIONS` adds
   `ListClusters`, `ListServices`, `DescribeServices`, `DescribeTaskDefinition`. Update the lock
   tests. Dev dependency: the `ecs` extra for moto (same pin).
4. **AWS provider.** `_Rows.deployments`; `_usage` also returns EC2 deployments; new `_ecs` lister;
   `base.second_phase` plans `ecs` for the admin and every member in its own regions. moto tests.
5. **Store and scanner.** `deployments` table, `SCHEMA_VERSION = 6`, `save_deployments`,
   `deployments(scan_id)`, pruned with the scan; scanner saves them. Tests.
6. **Mock and seed.** `make_seed.py` emits `deployments` (+ matching `asg` usage rows);
   `MockProvider` reads them and counts `ecs` segments. `make seed`. Tests.
7. **API.** `GET /api/deployments` with `ami`, `account_name`, and `failed`. Tests.
8. **Frontend.** `api.ts` types and call; `deployments.ts` (columns, cells, version order, drift)
   with vitest; `pages/Deployments.tsx` (matrix, filters in the URL, banner) and
   `components/DeploymentPanel.tsx` (drawer); sidebar section and route.
9. **Docs.** README (ECS permissions for the member role), AGENTS.md mental model line,
   HANDOFF status.
