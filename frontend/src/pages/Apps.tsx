import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, type DeploymentsData } from "../api";
import { appDetail, chartOf, filterApps, type AppFilters } from "../apps";
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
  const chart = useMemo(() => chartOf(shown, all), [shown, all]);
  const colorOf = useMemo(() => new Map(chart.series.map((s) => [s.app, palette[s.slot]])), [chart, palette]);
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
              description={
                chart.other
                  ? `The ${chart.series.length} biggest apps by running count; the rest are in Other. Click an area to open its app.`
                  : "Click an area to open its app."
              }
            />
            <CardBody className="pt-2">
              <ul aria-label="Legend" className="mb-3 flex flex-wrap gap-x-4 gap-y-1.5 text-xs">
                {chart.series.map((s) => (
                  <li key={s.key}>
                    <button type="button" onClick={() => setOpen(s.app)} className="inline-flex items-center gap-1.5 hover:text-accent">
                      <span className="size-2.5 rounded-sm" style={{ background: palette[s.slot] }} aria-hidden />
                      {s.app}
                    </button>
                  </li>
                ))}
                {chart.other && (
                  <li className="inline-flex items-center gap-1.5 text-muted">
                    <span className="size-2.5 rounded-sm" style={{ background: OTHER_COLOR }} aria-hidden />
                    Other
                  </li>
                )}
              </ul>
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={chart.points} margin={{ top: 8, right: 56, left: 0, bottom: 8 }}>
                    <CartesianGrid vertical={false} stroke="var(--border)" />
                    <XAxis dataKey="label" tick={{ fill: "var(--muted)", fontSize: 11 }} tickLine={false} axisLine={{ stroke: "var(--border)" }} interval={0} />
                    <YAxis allowDecimals={false} tick={{ fill: "var(--muted)", fontSize: 11 }} tickLine={false} axisLine={false} width={40} />
                    <Tooltip
                      contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, color: "var(--ink)", fontSize: 12 }}
                      itemStyle={{ color: "var(--ink)" }}
                      cursor={{ stroke: "var(--muted)", strokeWidth: 1 }}
                    />
                    {chart.series.map((s) => (
                      <Area
                        key={s.key}
                        dataKey={s.key}
                        name={s.app}
                        stackId="apps"
                        type="linear"
                        fill={palette[s.slot]}
                        fillOpacity={0.85}
                        stroke="var(--card)"
                        strokeWidth={2}
                        isAnimationActive={false}
                        className="cursor-pointer"
                        onClick={() => setOpen(s.app)}
                      />
                    ))}
                    {chart.other && (
                      <Area dataKey="other" name="Other" stackId="apps" type="linear" fill={OTHER_COLOR} fillOpacity={0.6} stroke="var(--card)" strokeWidth={2} isAnimationActive={false} />
                    )}
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="All apps" description="Biggest first. Colored apps are in the chart." />
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
                      <span className="mt-1 size-2.5 shrink-0 rounded-full" style={{ background: colorOf.get(app) ?? OTHER_COLOR }} aria-hidden />
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
