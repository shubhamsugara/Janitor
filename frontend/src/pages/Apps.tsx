import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { ResponsiveContainer, Tooltip, Treemap } from "recharts";
import { api, type DeploymentsData } from "../api";
import { appDetail, filterApps, treemapOf, type AppFilters, type Leaf } from "../apps";
import AppPanel from "../components/AppPanel";
import MultiSelect from "../components/MultiSelect";
import { OTHER_COLOR, SERIES_DARK, SERIES_LIGHT } from "../colors";
import { columnsOf } from "../deployments";
import { plural } from "../format";
import type { PageProps } from "../nav";
import { useDark } from "../theme";
import { Card, CardBody, CardHeader } from "../ui/card";
import { cn } from "../ui/cn";
import { Input } from "../ui/input";
import { Sheet } from "../ui/sheet";
import { Spinner } from "../ui/spinner";

function parse(search: URLSearchParams): AppFilters {
  const list = (key: string) => (search.get(key) ?? "").split(",").filter(Boolean);
  return { envs: list("env"), regions: list("region"), q: search.get("q") ?? "" };
}

function toSearch(f: AppFilters): URLSearchParams {
  const s = new URLSearchParams();
  if (f.envs.length) s.set("env", f.envs.join(","));
  if (f.regions.length) s.set("region", f.regions.join(","));
  if (f.q) s.set("q", f.q);
  return s;
}

/** Near-black or white text, whichever reads on the tile's fill. */
function inkFor(hex: string): string {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.3 ? "#0b0b0b" : "#ffffff";
}

interface TileProps {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  depth?: number;
  index?: number;
  name?: string;
  env?: string;
  running?: number;
  slot?: number | null;
  palette: string[];
}

/** One app's rectangle, filled with its env's color. The env's first tile also names the env, top left. */
function Tile({ x = 0, y = 0, width = 0, height = 0, depth, index, name, env, running, slot, palette }: TileProps) {
  if (depth !== 2) return null; // the env blocks are the union of their tiles
  const fill = slot == null ? OTHER_COLOR : palette[slot];
  const ink = inkFor(fill);
  const roomy = width > 64 && height > 34;
  return (
    <g className="cursor-pointer">
      <rect x={x} y={y} width={width} height={height} fill={fill} stroke="var(--card)" strokeWidth={2} />
      {index === 0 && width > 48 && height > 20 && (
        <text x={x + 6} y={y + 15} fill={ink} fontSize={11} fontWeight={600}>
          {env}
        </text>
      )}
      {roomy && (
        <text x={x + 6} y={y + height - 8} fill={ink} fontSize={11}>
          {name}, {running}
        </text>
      )}
    </g>
  );
}

const options = (values: string[]) => values.map((v) => ({ value: v, label: v, text: v }));

export default function Apps({ meta, notify }: PageProps) {
  const [search, setSearch] = useSearchParams();
  const filters = useMemo(() => parse(search), [search]);
  const setFilters = useCallback((next: AppFilters) => setSearch(toSearch(next), { replace: true }), [setSearch]);
  const [data, setData] = useState<DeploymentsData | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const dark = useDark();
  const palette = dark ? SERIES_DARK : SERIES_LIGHT;

  useEffect(() => {
    api.deployments().then(setData).catch((e: Error) => notify("error", e.message));
  }, [notify]);

  const all = useMemo(() => data?.items ?? [], [data]);
  const envOptions = useMemo(() => options([...new Set(columnsOf(all).map((c) => c.name))]), [all]);
  const regionOptions = useMemo(() => options([...new Set(all.map((d) => d.region))].sort()), [all]);
  const shown = useMemo(() => filterApps(all, filters), [all, filters]);
  const groups = useMemo(() => treemapOf(shown, all), [shown, all]);
  const apps = useMemo(() => {
    const byApp = new Map<string, { running: number; places: Set<string> }>();
    for (const d of shown) {
      const app = byApp.get(d.app) ?? { running: 0, places: new Set<string>() };
      app.running += d.running;
      app.places.add(`${d.account}|${d.region}`);
      byApp.set(d.app, app);
    }
    return [...byApp.entries()].sort((a, b) => b[1].running - a[1].running || a[0].localeCompare(b[0]));
  }, [shown]);
  const detail = useMemo(() => (open ? appDetail(shown, open) : null), [open, shown]);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">
          Apps {data && <span className="font-normal text-muted">({plural(apps.length, "app")})</span>}
        </h2>
        <p className="mt-1 text-[13px] text-muted">
          Running instances and tasks per app across envs, from the last scan. Open an app to see the resources it runs on and their tags. Read-only.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <MultiSelect label="Env" options={envOptions} value={filters.envs} onChange={(envs) => setFilters({ ...filters, envs })} />
        <MultiSelect label="Region" options={regionOptions} value={filters.regions} onChange={(regions) => setFilters({ ...filters, regions })} />
        <Input aria-label="Search apps" placeholder="Search apps" value={filters.q} onChange={(e) => setFilters({ ...filters, q: e.target.value })} className="w-60" />
      </div>

      {!data ? (
        <Card>
          <Spinner label="Loading apps" className="justify-center py-16" />
        </Card>
      ) : apps.length === 0 ? (
        <Card>
          <p className="py-16 text-center text-muted">{all.length ? "No apps match these filters." : "No apps in the last scan."}</p>
        </Card>
      ) : (
        <>
          <Card>
            <CardHeader
              title="Running by env"
              description="Each block is an env; each rectangle inside is an app, sized by its running instances and tasks. Click an app to open it."
            />
            <CardBody className="pt-2">
              {groups.length === 0 ? (
                <p className="py-10 text-center text-[13px] text-muted">Nothing is running in these envs.</p>
              ) : (
                <>
                  <div className="h-[28rem]">
                    <ResponsiveContainer width="100%" height="100%">
                      <Treemap
                        data={groups as unknown as Record<string, unknown>[]}
                        dataKey="running"
                        nameKey="name"
                        aspectRatio={4 / 3}
                        isAnimationActive={false}
                        content={<Tile palette={palette} />}
                        onClick={(node) => {
                          const leaf = node as unknown as Partial<Leaf>;
                          if (leaf.app) setOpen(leaf.app);
                        }}
                      >
                        <Tooltip
                          content={({ payload }) => {
                            const leaf = payload?.[0]?.payload as Partial<Leaf> | undefined;
                            if (!leaf?.app) return null;
                            return (
                              <div className="rounded-[10px] border border-line bg-card px-3 py-2 text-xs text-ink shadow-card">
                                <div className="font-medium">{leaf.app}</div>
                                <div className="text-muted">
                                  {leaf.env}: {leaf.running} running
                                </div>
                              </div>
                            );
                          }}
                        />
                      </Treemap>
                    </ResponsiveContainer>
                  </div>
                  <ul aria-label="Legend" className="mt-3 flex flex-wrap justify-center gap-x-4 gap-y-1.5 text-xs">
                    {groups.map((g) => (
                      <li key={g.env} className="inline-flex items-center gap-1.5">
                        <span className="size-2.5 rounded-sm" style={{ background: g.slot == null ? OTHER_COLOR : palette[g.slot] }} aria-hidden />
                        {g.env} <span className="text-muted">{g.running}</span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="All apps" description="Biggest first, including apps with nothing running." />
            <CardBody className="pt-3">
              <ul aria-label="Apps" className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {apps.map(([app, info]) => (
                  <li key={app}>
                    <button
                      type="button"
                      onClick={() => setOpen(app)}
                      className={cn(
                        "flex w-full items-start gap-2.5 rounded-lg border border-line px-3 py-2 text-left hover:bg-subtle",
                        "focus-visible:ring-4 focus-visible:ring-ring focus-visible:outline-none",
                      )}
                    >
                      <span className="min-w-0">
                        <span className="block font-medium break-words">{app}</span>
                        <span className="block text-xs text-muted">
                          {info.running} running · {plural(info.places.size, "place")}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </CardBody>
          </Card>
        </>
      )}

      <Sheet open={Boolean(detail)} onClose={() => setOpen(null)} title={open ?? "App"}>
        {detail && <AppPanel detail={detail} meta={meta} />}
      </Sheet>
    </div>
  );
}
