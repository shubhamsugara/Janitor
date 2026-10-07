import type { ReactNode } from "react";
import { CircleDollarSign, Layers, ShieldCheck, TriangleAlert, type LucideIcon } from "lucide-react";
import type { Meta, Stats } from "../api";
import BarList from "../charts/BarList";
import StatusDonut from "../charts/StatusDonut";
import { accountName, formatGiB, formatMoney } from "../format";
import { Card, CardBody, CardHeader } from "../ui/card";
import { cn } from "../ui/cn";

export function Kpi({ label, value, detail, icon: Icon, tone = "neutral" }: { label: string; value: ReactNode; detail: string; icon: LucideIcon; tone?: "neutral" | "danger" | "warning" | "accent" }) {
  const tones = {
    neutral: "bg-subtle text-muted",
    danger: "bg-red-500/10 text-red-600 dark:text-red-400",
    warning: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
    accent: "bg-accent-soft text-accent",
  };
  return (
    <Card className="p-5">
      <div className="flex items-center justify-between">
        <span className="text-[13px] font-medium text-muted">{label}</span>
        <span className={cn("flex size-8 items-center justify-center rounded-lg", tones[tone])}>
          <Icon className="size-4" aria-hidden />
        </span>
      </div>
      <div className="mt-3 text-[28px] leading-none font-semibold tracking-tight tabular-nums">{value}</div>
      <div className="mt-2 text-[13px] text-muted">{detail}</div>
    </Card>
  );
}

/** Headline numbers and breakdowns for the resources that match the current filters. */
export default function StatsHeader({ stats, meta }: { stats: Stats; meta: Meta }) {
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi label="Matching" value={stats.total.toLocaleString()} detail={formatGiB(stats.size_gib)} icon={Layers} />
        <Kpi label="Orphaned" value={stats.orphaned.toLocaleString()} detail={formatGiB(stats.orphaned_gib)} icon={TriangleAlert} tone="danger" />
        <Kpi
          label="Waste"
          value={stats.orphaned_usd == null ? "—" : `~${formatMoney(stats.orphaned_usd)}`}
          detail="Orphaned resources, per month"
          icon={CircleDollarSign}
          tone="warning"
        />
        <Kpi label="Blocked · deletable" value={`${stats.blocked.toLocaleString()} · ${stats.deletable.toLocaleString()}`} detail="By the delete rules" icon={ShieldCheck} tone="accent" />
      </div>
      <Card>
        <CardHeader title="Breakdown" description="For the resources that match your filters. Costs are monthly estimates." />
        <CardBody className="grid gap-8 md:grid-cols-2 xl:grid-cols-[1.35fr_1fr_1fr_1fr]">
          <div className="min-w-0">
            <h3 className="mb-3 text-[13px] font-medium text-muted">By status</h3>
            <StatusDonut buckets={stats.by_status} meta={meta} total={stats.total} size={132} />
          </div>
          <BarList title="By account" buckets={stats.by_account} label={(key) => accountName(meta, key)} />
          <BarList title="By region" buckets={stats.by_region} label={(key) => key} />
          <BarList title="By age" buckets={stats.by_age} label={(key) => key} />
        </CardBody>
      </Card>
    </div>
  );
}
