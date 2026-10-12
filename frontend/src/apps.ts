import type { Deployment } from "./api";
import { columnsOf } from "./deployments";

/** The categorical palette has 8 validated hues; more apps fold into "Other". */
export const MAX_SERIES = 8;

export interface AppFilters {
  envs: string[]; // account names, as the Deployments columns
  regions: string[];
  q: string;
}

export interface Series {
  app: string;
  key: string; // "s0".."s7": app names can hold dots, which chart libraries read as paths
  slot: number; // palette slot, fixed per app
}

export type Point = { label: string } & Record<string, number | string>;

export function filterApps(items: Deployment[], f: AppFilters): Deployment[] {
  const q = f.q.trim().toLowerCase();
  return items.filter(
    (d) =>
      (f.envs.length === 0 || f.envs.includes(d.account_name)) &&
      (f.regions.length === 0 || f.regions.includes(d.region)) &&
      (!q || d.app.toLowerCase().includes(q)),
  );
}

/** Apps by running instances and tasks, biggest first. */
function rank(items: Deployment[]): string[] {
  const running = new Map<string, number>();
  for (const d of items) running.set(d.app, (running.get(d.app) ?? 0) + d.running);
  return [...running.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([app]) => app);
}

/** A stacked area per app over env columns. Colors follow the app, not its rank in the current
 * filter: the biggest apps overall keep their slots, and others take the slots left free. */
export function chartOf(shown: Deployment[], all: Deployment[]): { points: Point[]; series: Series[]; other: boolean } {
  const visible = rank(shown);
  const top = visible.slice(0, MAX_SERIES);
  const fixed = new Map(rank(all).slice(0, MAX_SERIES).map((app, slot) => [app, slot]));
  const free = [...Array(MAX_SERIES).keys()].filter((slot) => ![...fixed.entries()].some(([app, s]) => s === slot && top.includes(app)));
  const series = top.map((app, i) => ({ app, key: `s${i}`, slot: fixed.get(app) ?? (free.shift() as number) }));
  const keyOf = new Map(series.map((s) => [s.app, s.key]));
  const points = columnsOf(shown).map((c) => {
    const point: Point = { label: `${c.name} · ${c.region}`, other: 0 };
    for (const s of series) point[s.key] = 0;
    for (const d of shown) {
      if (d.account !== c.account || d.region !== c.region) continue;
      const key = keyOf.get(d.app) ?? "other";
      point[key] = (point[key] as number) + d.running;
    }
    return point;
  });
  return { points, series, other: visible.length > MAX_SERIES };
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
