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
    (d) =>
      (!f.kind || d.kind === f.kind) && (f.accounts.length === 0 || f.accounts.includes(d.account)) && (!q || d.app.toLowerCase().includes(q)),
  );
}
