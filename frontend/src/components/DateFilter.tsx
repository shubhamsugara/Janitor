import { useState } from "react";
import { Calendar, ChevronDown } from "lucide-react";
import { fromRange, type Filters, type RangeValue } from "../filters";
import { Button } from "../ui/button";
import { cn } from "../ui/cn";
import { Input } from "../ui/input";
import { Popover } from "../ui/popover";

const PRESETS: { label: string; value: RangeValue }[] = [
  { label: "Last 30 days", value: { type: "relative", amount: 30, unit: "day" } },
  { label: "Last 90 days", value: { type: "relative", amount: 90, unit: "day" } },
  { label: "Last 1 year", value: { type: "relative", amount: 1, unit: "year" } },
];

/** Created-date filter: presets, or a custom from/to. */
export default function DateFilter({ filters, onChange }: { filters: Filters; onChange: (f: Filters) => void }) {
  const [open, setOpen] = useState(false);
  const [from, setFrom] = useState(filters.from);
  const [to, setTo] = useState(filters.to);
  const active = Boolean(filters.from || filters.to);
  const invalid = Boolean(from && to && from > to);

  function apply(value: RangeValue | null) {
    onChange(fromRange(value, filters));
    setOpen(false);
  }

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) {
          setFrom(filters.from);
          setTo(filters.to);
        }
      }}
      className="w-72"
      trigger={
        <button
          type="button"
          className={cn(
            "inline-flex h-9 items-center gap-1.5 rounded-lg border px-3 text-[13px] font-medium transition-colors",
            active ? "border-accent/40 bg-accent-soft text-accent" : "border-dashed border-line bg-card text-ink hover:bg-subtle",
          )}
        >
          <Calendar className="size-3.5" aria-hidden />
          <span>
            Created
            {active && <span className="font-normal">: {filters.from || "…"} – {filters.to || "…"}</span>}
          </span>
          <ChevronDown className="size-3.5 opacity-60" aria-hidden />
        </button>
      }
    >
      <div className="space-y-3">
        <div className="grid gap-1">
          {PRESETS.map((p) => (
            <button key={p.label} type="button" onClick={() => apply(p.value)} className="rounded-lg px-2.5 py-2 text-left text-[13px] hover:bg-subtle">
              {p.label}
            </button>
          ))}
        </div>
        <div className="border-t border-line pt-3">
          <div className="mb-2 text-[11px] font-semibold tracking-wider text-muted uppercase">Custom range</div>
          <div className="grid grid-cols-2 gap-2">
            <label className="text-xs text-muted">
              From
              <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="mt-1 h-8 px-2 text-[13px]" />
            </label>
            <label className="text-xs text-muted">
              To
              <Input type="date" value={to} onChange={(e) => setTo(e.target.value)} className="mt-1 h-8 px-2 text-[13px]" />
            </label>
          </div>
          {invalid && <p className="mt-2 text-xs text-red-600 dark:text-red-400">The start date is after the end date. Choose an earlier start.</p>}
          <div className="mt-3 flex justify-between gap-2">
            <Button size="sm" variant="ghost" onClick={() => apply(null)}>
              Clear dates
            </Button>
            <Button size="sm" variant="primary" disabled={invalid || (!from && !to)} onClick={() => apply({ type: "absolute", startDate: from, endDate: to })}>
              Apply
            </Button>
          </div>
        </div>
      </div>
    </Popover>
  );
}
