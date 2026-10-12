import type { Deployment } from "./api";
import { columnsOf } from "./deployments";

/** The categorical palette has 8 validated hues; more apps fold into "Other". */
export const MAX_SERIES = 8;

export interface AppFilters {
  envs: string[]; // account names, as the Deployments columns
  regions: string[];
  q: string;
}

export interface Leaf {
  name: string; // the treemap labels by name
  app: string;
  env: string;
  running: number;
  slot: number | null;
}

export interface Group {
  name: string;
  env: string;
  running: number;
  slot: number | null; // palette slot; null past the palette (drawn neutral)
  children: Leaf[];
}

export function filterApps(items: Deployment[], f: AppFilters): Deployment[] {
  const q = f.q.trim().toLowerCase();
  return items.filter(
    (d) =>
      (f.envs.length === 0 || f.envs.includes(d.account_name)) &&
      (f.regions.length === 0 || f.regions.includes(d.region)) &&
      (!q || d.app.toLowerCase().includes(q)),
  );
}

/** A treemap: one block per env (account name, regions combined), one rectangle per app sized by
 * running instances and tasks. Colors follow the env, not its rank: slots come from the env order
 * of all deployments, so a filter never repaints the envs that remain. */
export function treemapOf(shown: Deployment[], all: Deployment[]): Group[] {
  const order = [...new Set(columnsOf(all).map((c) => c.name))];
  const slotOf = (env: string) => {
    const i = order.indexOf(env);
    return i >= 0 && i < MAX_SERIES ? i : null;
  };
  const byEnv = new Map<string, Map<string, number>>();
  for (const d of shown) {
    if (d.running <= 0) continue;
    const apps = byEnv.get(d.account_name) ?? new Map<string, number>();
    apps.set(d.app, (apps.get(d.app) ?? 0) + d.running);
    byEnv.set(d.account_name, apps);
  }
  return [...byEnv.entries()]
    .map(([env, apps]) => {
      const slot = slotOf(env);
      const children = [...apps.entries()]
        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
        .map(([app, running]) => ({ name: app, app, env, running, slot }));
      return { name: env, env, slot, running: children.reduce((n, c) => n + c.running, 0), children };
    })
    .sort((a, b) => b.running - a.running || order.indexOf(a.env) - order.indexOf(b.env));
}

export interface AppDetail {
  resources: Deployment[];
  tags: { key: string; values: { value: string; count: number }[] }[];
  running: number;
  places: number; // account × region pairs
}

/** Every resource an app runs on, and every tag they carry with how many resources carry each value. */
export function appDetail(items: Deployment[], app: string): AppDetail {
  const resources = items
    .filter((d) => d.app === app)
    .sort((a, b) => a.account_name.localeCompare(b.account_name) || a.region.localeCompare(b.region) || b.created_at.localeCompare(a.created_at));
  const counts = new Map<string, Map<string, number>>();
  for (const d of resources) {
    for (const [key, value] of Object.entries(d.tags ?? {})) {
      const values = counts.get(key) ?? new Map<string, number>();
      values.set(value, (values.get(value) ?? 0) + 1);
      counts.set(key, values);
    }
  }
  const tags = [...counts.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, values]) => ({
      key,
      values: [...values.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([value, count]) => ({ value, count })),
    }));
  return {
    resources,
    tags,
    running: resources.reduce((n, d) => n + d.running, 0),
    places: new Set(resources.map((d) => `${d.account}|${d.region}`)).size,
  };
}
