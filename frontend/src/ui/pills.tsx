import type { Outcome, Status } from "../api";
import { STATUS_COLORS } from "../colors";
import { cn } from "./cn";

/** A status as a colored dot plus its label: color never carries the meaning alone. */
export function StatusPill({ status, label, className }: { status: Status; label: string; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full border border-line bg-card px-2 py-0.5 text-xs font-medium whitespace-nowrap", className)}>
      <span className="size-2 rounded-full" style={{ background: STATUS_COLORS[status] }} aria-hidden />
      {label}
    </span>
  );
}

const OUTCOMES: Record<Outcome, { label: string; className: string }> = {
  block: { label: "Blocked", className: "bg-subtle text-muted" },
  warn: { label: "Review", className: "bg-amber-500/10 text-amber-700 dark:text-amber-400" },
  pass: { label: "Deletable", className: "bg-accent-soft text-accent" },
};

export function OutcomePill({ outcome }: { outcome: Outcome }) {
  const o = OUTCOMES[outcome];
  return <span className={cn("inline-flex rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap", o.className)}>{o.label}</span>;
}
