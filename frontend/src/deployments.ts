import type { Deployment } from "./api";

/** Envs from sandbox to production; others follow, by name. */
const ENV_ORDER = ["sbx", "sandbox", "dev", "qa", "qas", "test", "uat", "stg", "stage", "staging", "prd", "prod", "production"];

export interface Column {
  key: string;
  env: string;
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
  envs: string[];
  q: string;
}

export const columnKey = (d: Pick<Deployment, "env" | "region">) => `${d.env}|${d.region}`;

function envRank(env: string): number {
  const i = ENV_ORDER.indexOf(env.toLowerCase());
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
  for (const d of items) seen.set(columnKey(d), { key: columnKey(d), env: d.env, region: d.region });
  return [...seen.values()].sort(
    (a, b) => envRank(a.env) - envRank(b.env) || a.env.localeCompare(b.env) || a.region.localeCompare(b.region),
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

/** What a cell shows: the live version, `old → new` during a switch, or "Not running". */
export function cellLabel(cell: Cell): string {
  const [newest, previous] = cell.live;
  if (!newest) return "Not running";
  if (previous && previous.version !== newest.version) return `${previous.version || "?"} → ${newest.version || "?"}`;
  return newest.version || "No version tag";
}

export function filterItems(items: Deployment[], f: DeploymentFilters): Deployment[] {
  const q = f.q.trim().toLowerCase();
  return items.filter(
    (d) => (!f.kind || d.kind === f.kind) && (f.envs.length === 0 || f.envs.includes(d.env)) && (!q || d.app.toLowerCase().includes(q)),
  );
}
