import { useCallback, useEffect, useState } from "react";
import { ArrowUpRight, CircleDollarSign, Layers, RefreshCw, TriangleAlert } from "lucide-react";
import { Link } from "react-router";
import { api, runScan, type OverviewData, type Stats } from "../api";
import StatusDonut from "../charts/StatusDonut";
import AwsIcon from "../components/AwsIcon";
import { Kpi } from "../components/StatsHeader";
import { formatDate, formatGiB, formatMoney } from "../format";
import { TYPE_PAGES, type PageProps } from "../nav";
import { Button } from "../ui/button";
import { Card } from "../ui/card";
import { Skeleton } from "../ui/spinner";

export const SCAN_POLL_MS = 1500;

export default function Overview({ meta, notify }: PageProps) {
  const [data, setData] = useState<OverviewData | null>(null);
  const [stats, setStats] = useState<Record<string, Stats | null>>({});
  const [scanning, setScanning] = useState(false);

  const load = useCallback(() => {
    api.overview().then(setData).catch((e: Error) => notify("error", e.message));
    Promise.all(TYPE_PAGES.map((p) => api.stats(new URLSearchParams({ type: p.type }))))
      .then((all) => setStats(Object.fromEntries(TYPE_PAGES.map((p, i) => [p.type, all[i]]))))
      .catch(() => setStats({}));
  }, [notify]);
  useEffect(load, [load]);

  // A scan started elsewhere (the top bar, another tab, or at startup) shows as running: keep checking.
  useEffect(() => {
    if (!data?.scanning || scanning) return;
    const timer = setTimeout(load, SCAN_POLL_MS);
    return () => clearTimeout(timer);
  }, [data, scanning, load]);

  async function scan() {
    setScanning(true);
    try {
      await runScan();
      load();
      notify("success", "Scan finished.");
    } catch (e) {
      notify("error", (e as Error).message);
    } finally {
      setScanning(false);
    }
  }

  const types = data?.types ?? [];
  const total = types.reduce((n, t) => n + t.total, 0);
  const orphaned = types.reduce((n, t) => n + t.orphaned, 0);
  const orphanedGib = types.reduce((n, t) => n + t.orphaned_gib, 0);
  // AMI cost is the cost of its snapshots, so the headline waste leaves AMIs out to count each once.
  const waste = types.filter((t) => t.type !== "ami").reduce((n, t) => n + (t.orphaned_usd ?? 0), 0);

  if (data && !data.last_scan) {
    return (
      <Card className="mx-auto mt-12 max-w-md p-10 text-center">
        <h2 className="text-lg font-semibold">No scan yet</h2>
        <p className="mt-1 text-[13px] text-muted">Janitor lists your AMIs, snapshots, and volumes, then explains each status.</p>
        <Button variant="primary" className="mt-5" loading={scanning} onClick={scan}>
          Run first scan
        </Button>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">Cleanup overview</h2>
          <p className="mt-1 text-[13px] text-muted">
            {data?.last_scan ? `Last scan: ${formatDate(data.last_scan.finished_at)}` : "Loading"} · {meta.provider === "mock" ? "Mock data" : "AWS · read-only"}
          </p>
        </div>
        {(scanning || data?.scanning) && (
          <span className="inline-flex items-center gap-2 text-[13px] text-muted" role="status">
            <RefreshCw className="size-3.5 animate-spin" aria-hidden />
            Scanning
          </span>
        )}
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <Kpi label="Resources" value={data ? total.toLocaleString() : "—"} detail="Across the four types" icon={Layers} />
        <Kpi label="Orphaned" value={data ? orphaned.toLocaleString() : "—"} detail={formatGiB(orphanedGib)} icon={TriangleAlert} tone="danger" />
        <Kpi label="Waste" value={data ? `~${formatMoney(waste)}` : "—"} detail="Orphaned, per month" icon={CircleDollarSign} tone="warning" />
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {TYPE_PAGES.map((page) => {
          const summary = types.find((t) => t.type === page.type);
          const s = stats[page.type];
          return (
            <Link key={page.type} to={page.path} className="group">
              <Card className="h-full p-5 transition-shadow group-hover:shadow-lg group-hover:ring-1 group-hover:ring-accent/30">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <AwsIcon kind={page.type} size={32} />
                    <span className="font-semibold">{page.title}</span>
                  </div>
                  <ArrowUpRight className="size-4 text-muted transition-colors group-hover:text-accent" aria-hidden />
                </div>
                <div className="mt-4 text-[28px] leading-none font-semibold tracking-tight tabular-nums">{summary ? summary.total.toLocaleString() : "—"}</div>
                <p className="mt-2 text-[13px] text-muted">
                  {summary
                    ? `${summary.orphaned.toLocaleString()} orphaned · ${formatGiB(summary.orphaned_gib)}` +
                      (summary.orphaned_usd != null ? ` · ~${formatMoney(summary.orphaned_usd)}/mo` : "")
                    : "No data"}
                </p>
                <div className="mt-5 border-t border-line pt-4">
                  {s && s.total > 0 ? <StatusDonut buckets={s.by_status} meta={meta} total={s.total} size={112} /> : <Skeleton className="h-28 w-full" />}
                </div>
              </Card>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
