# Deployments: what runs where

Status: approved 2026-10-08. Branch `deployments`.

## Goal

A read-only **Deployments** page, below the resource pages in the sidebar: for every app in
every env, which version is live and what it runs on. Visibility only: no rules, no plans, no
delete flow.

## How the apps are deployed (what Janitor reads)

An in-house deploy tool ships each app with one of two families of strategy:

- **EC2 (blue/green, destroy-before-create).** Each deploy makes a launch template version that
  names the AMI, and a new auto scaling group tagged `role`, `env`, `version`, `deployment-id`,
  and `deploy-state`. The state moves `deploying → deployed → undeploying → undeployed`. Old
  groups stay at capacity 0 with `deploy-state=undeployed` until someone prunes them.
- **ECS (rolling, blue/green).** Each deploy registers a task definition revision tagged `app`
  and `version`, then points a service at it. ECS blue/green keeps two services per app and
  scales the inactive one to 0.

Scheduled and task-only apps (EventBridge rules, task definitions with no service) are out of
scope: showing them needs `events:List*` as well.

## Data

`models.Deployment`, one row per ASG or ECS service:

| Field | EC2 | ECS |
|---|---|---|
| `kind` | `ec2` | `ecs` |
| `account`, `region` | where it was found | where it was found |
| `env` | first of `tags.env` on the ASG, else the account's name | first of `tags.env` on the service or task definition, else the account's name |
| `app` | first of `tags.app` on the ASG, else the ASG name | first of `tags.app` on the task definition or service, else the service name |
| `version` | first of `tags.version` | first of `tags.version` on the task definition, else the first container's image tag |
| `state` | the `tags.state` value | `undeployed` if desired is 0; `undeploying` if draining; `failed`/`deploying` from the primary deployment's rollout state; else `deployed` |
| `resource_id`, `name` | ASG name | service ARN, service name |
| `created_at` | ASG creation time | service creation time |
| `desired`, `running` | desired capacity, in-service instances | desired count, running count |
| `deployment_id` | `tags.deployment_id` | "" |
| `launch_template`, `launch_template_version` | the ASG's template name and pinned version number | "" |
| `ami_id` | the image of that version (or of the launch configuration); SSM references stay empty | null |
| `cluster`, `task_definition`, `image` | "" | cluster name, `family:revision`, first container image |

Only ASGs that carry the `tags.state` key are deployments; other ASGs (node groups, hand-made
groups) are ignored, as the deploy tool's own listing does.

**Instances in no ASG** (no `aws:autoscaling:groupName` tag) are deployments too, one row each,
`unit = "instance"`: hand-made servers, older strategies, bastions, a DR server kept stopped.
App is the first `tags.app`, else `Name`, else the instance ID; desired is 1 while pending or
running, running is 1 while running. They come from the usage check's instance list: no new
calls. Each row's `unit` is `asg`, `instance`, or `service`. Target group membership is not
read (it would need `elasticloadbalancing:Describe*`).

Config, with these defaults (`janitor.example.yaml` documents them):

```yaml
deployments:
  tags:
    app: [role, app]        # first tag present wins
    env: [env]
    version: [version]
    state: deploy-state
    deployment_id: deployment-id
```

## Scan

- **EC2** deployments come out of the existing `usage` check: it already pages through ASGs,
  launch templates, and the versions ASGs pin. No new calls; a failed `usage` check shows the
  same "couldn't check" message it does today.
- **ECS** is a new check kind, `ecs`, planned for the admin and every member account in that
  account's own regions: `ListClusters`, `ListServices`, `DescribeServices` (with tags), and
  `DescribeTaskDefinition` (with tags, cached per ARN). A failed `ecs` check affects only the
  Deployments page; the linker never reads it.
- **Read-only locks.** Lock 2's session policy adds `ecs:Describe*` and `ecs:List*`. Lock 3 (the
  guard) already allows only `Describe*`/`List*`/`Get*`. `OPERATIONS` lists the four ECS calls.
- Rows are stored in a `deployments` table keyed by `scan_id` and pruned with the scan.
  `SCHEMA_VERSION` goes to 6.

## API

`GET /api/deployments` returns `{scan_id, items, failed}`:

- `items`: every row, plus `ami` (`{id, name, status}` when the AMI is in the scan, else null)
  and `account_name`.
- `failed`: the shown scan's failed `usage` and `ecs` checks, worded by `segment_message()`.

## UI

- Sidebar: a **Deployments** section after **Resources**, with one item, "Deployments".
- Page: a matrix with apps as rows and **account · region** as columns, labeled with the
  account's name. Columns are sorted by a known env order matched on the name's first word (sbx,
  dev, qa/qas, uat, stg, prd/prod, so `prd-us` sorts as prd; others last), then region. Env tags
  are not columns: a deploy tool may tag every prod account's ASGs `env=prd` while ECS services
  carry no env tag, which split one account across two columns in the first real scan. The env
  tag is shown in the drawer.
- A cell shows the live version. "Live" means any state except `undeployed`, newest first. Two
  live rows (a switch in progress) show `old → new`. In-progress and failed cells get a colored
  badge. A cell with only undeployed rows shows "Not running" and its last version.
- Every cell shows how many instances or tasks run ("2 instances", "6 tasks"), summed across
  its rows, and a "N standalone" badge for instances in no ASG. Versions running side by side
  are listed newest first; `old → new` is only for a switch (a deploying or undeploying row).
- Next to the deploy state, a **run status** from desired and running counts: running, `1 of 3
  running`, Stopped (scaled to 0), `Stopping: N still running`, or `No instances/tasks running`
  (wants some, has none). The deploy state alone misled: an ASG stays `deployed` after it is
  scaled to 0, and an ECS service stays `deployed` while its tasks fail to start. Cells show it
  only when it isn't simply running; the drawer always does.
- A row whose live versions differ across envs shows "N versions", and cells below the newest
  version (dotted numeric order) are amber.
- Filters: kind (EC2/ECS), account, and search on app. Kept in the URL.
- Clicking a cell opens a drawer with the live rows' details: ASG, deployment ID, capacity,
  launch template + version, AMI (name, status, link to the AMI page). For ECS: cluster,
  service, task definition, image, counts. Earlier versions (undeployed rows) come last.
- A banner lists failed checks that affect the page.
- Copy follows the existing rules (sentence case, no "successfully", "please", or `!`).

## Mock data

`fixtures/seed.json` gains `deployments` (made-up apps: `api`, `web`, `worker` on EC2;
`orders-api`, `billing-svc`, `reports` on ECS) across sbx, dev, uat, qas, and prd in two
regions. They include a switch in progress, a failed rollout, version drift, ECS blue/green
standby, and undeployed history. EC2 rows reference AMIs that are already in use, and each gets a
matching `asg` usage row, so no AMI status changes.

## Testing

- Pure: normalize ASG → deployment (state tag filter, tag fallbacks, pinned template version
  image, launch config image, SSM image left empty); ECS service → deployment (state mapping,
  version fallback to image tag).
- moto: tagged ASGs with launch template versions, and ECS clusters/services/task definitions.
  A guard test covers that every sent operation is in `OPERATIONS`.
- Store round-trip and pruning; the API shape; mock segments include `ecs`.
- vitest: column order, cell grouping, version comparison, drift.
