import type { Deployment } from "./api";

/** Envs from sandbox to production, matched on a name's first word (prd-us is prd); others follow. */
const ENV_ORDER = ["sbx", "sandbox", "dev", "qa", "qas", "test", "uat", "stg", "stage", "staging", "prd", "prod", "production"];

/** Where deployments run: one account in one region, named by the account. Env tags can't be
 * columns: a deploy tool may tag every prod account's ASGs env=prd while ECS services carry no
 * env tag, which would split one account across two columns. */
export interface Column {
  key: string;
  account: string;
  name: string;
  region: string;
}

export interface Cell {
  live: Deployment[]; // every state but undeployed, newest first
  history: Deployment[]; // undeployed, newest first
}

export interface AppRow {
  app: string;
  kinds: Deployment["kind"][];
  cells: Record<string, Cell>;
  versions: string[]; // each cell's current version, distinct, newest first
  latest: string | null;
}

export interface DeploymentFilters {
  kind: "" | Deployment["kind"];
  accounts: string[];
  q: string;
}

export const columnKey = (d: Pick<Deployment, "account" | "region">) => `${d.account}|${d.region}`;

function envRank(name: string): number {
  const i = ENV_ORDER.indexOf(name.toLowerCase().split(/[^a-z0-9]+/)[0] ?? "");
  return i < 0 ? ENV_ORDER.length : i;
}

/** Dotted parts compare as numbers when both are numbers, else as text. */
export function compareVersions(a: string, b: string): number {
  const pa = a.split(/[.\-+_]/);
  const pb = b.split(/[.\-+_]/);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const x = pa[i];
    const y = pb[i];
    if (x === undefined || y === undefined) return x === undefined ? -1 : 1;
    const nx = Number(x);
    const ny = Number(y);
    const diff = x !== "" && y !== "" && !Number.isNaN(nx) && !Number.isNaN(ny) ? nx - ny : x.localeCompare(y);
    if (diff !== 0) return diff;
  }
  return 0;
}

export function columnsOf(items: Deployment[]): Column[] {
  const seen = new Map<string, Column>();
  for (const d of items) seen.set(columnKey(d), { key: columnKey(d), account: d.account, name: d.account_name, region: d.region });
  return [...seen.values()].sort(
    (a, b) => envRank(a.name) - envRank(b.name) || a.name.localeCompare(b.name) || a.region.localeCompare(b.region),
  );
}

const newestFirst = (a: Deployment, b: Deployment) => b.created_at.localeCompare(a.created_at);

export function rowsOf(items: Deployment[]): AppRow[] {
  const byApp = new Map<string, Deployment[]>();
  for (const d of items) byApp.set(d.app, [...(byApp.get(d.app) ?? []), d]);
  return [...byApp.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([app, rows]) => {
      const cells: Record<string, Cell> = {};
      for (const d of rows) {
        const cell = (cells[columnKey(d)] ??= { live: [], history: [] });
        (d.state === "undeployed" ? cell.history : cell.live).push(d);
      }
      for (const cell of Object.values(cells)) {
        cell.live.sort(newestFirst);
        cell.history.sort(newestFirst);
      }
      const current = Object.values(cells).flatMap((c) => (c.live[0] ? [c.live[0].version] : []));
      const versions = [...new Set(current)].sort((a, b) => compareVersions(b, a));
      return { app, kinds: [...new Set(rows.map((d) => d.kind))].sort(), cells, versions, latest: versions[0] ?? null };
    });
}

export type RunKey = "running" | "partial" | "stopped" | "down" | "stopping";

/** Whether anything actually runs, from desired and running counts. The deploy state is the deploy
 * tool's lifecycle tag: an ASG stays "deployed" after it is scaled to 0, and an ECS service stays
 * "deployed" while its tasks keep failing to start. */
export function runStatus(d: Deployment): { key: RunKey; label: string } {
  const unit = d.kind === "ecs" ? "tasks" : "instances";
  if (d.desired === 0) return d.running === 0 ? { key: "stopped", label: "Stopped" } : { key: "stopping", label: `Stopping: ${d.running} still running` };
  if (d.running === 0) return { key: "down", label: `No ${unit} running` };
  return { key: d.running < d.desired ? "partial" : "running", label: `${d.running} of ${d.desired} running` };
}

/** What a cell shows: `old → new` during a switch, else every live version (newest first), or
 * "Not running". Instances in no ASG run beside a deployment, so their versions are listed. */
export function cellLabel(cell: Cell): string {
  const [newest, previous] = cell.live;
  if (!newest) return "Not running";
  const switching = cell.live.length === 2 && cell.live.some((d) => d.state === "deploying" || d.state === "undeploying");
  if (switching && previous.version !== newest.version) return `${previous.version || "?"} → ${newest.version || "?"}`;
  const versions = [...new Set(cell.live.map((d) => d.version).filter(Boolean))].sort((a, b) => compareVersions(b, a));
  return versions.join(", ") || "No version tag";
}

/** How many instances or tasks run in a cell, how many instances are in no ASG, and the run
 * status of the cell as a whole. */
export function cellSummary(cell: Cell): { count: string; standalone: number; run: ReturnType<typeof runStatus> } {
  const running = cell.live.reduce((n, d) => n + d.running, 0);
  const desired = cell.live.reduce((n, d) => n + d.desired, 0);
  const ecs = cell.live.length > 0 && cell.live.every((d) => d.kind === "ecs");
  const unit = ecs ? (running === 1 ? "task" : "tasks") : running === 1 ? "instance" : "instances";
  return {
    count: `${running} ${unit}`,
    standalone: cell.live.filter((d) => d.unit === "instance").length,
    run: runStatus({ ...cell.live[0], kind: ecs ? "ecs" : "ec2", desired, running }),
  };
}

export function filterItems(items: Deployment[], f: DeploymentFilters): Deployment[] {
  const q = f.q.trim().toLowerCase();
  return items.filter(
    (d) =>
      (!f.kind || d.kind === f.kind) && (f.accounts.length === 0 || f.accounts.includes(d.account)) && (!q || d.app.toLowerCase().includes(q)),
  );
}
