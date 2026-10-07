import { useState, type ReactNode } from "react";
import { ChevronRight, Info, TriangleAlert } from "lucide-react";
import { api, type Meta, type Plan, type PlanItem, type SimulateResult } from "../api";
import { formatGiB, formatUsd, plural } from "../format";
import { Button } from "../ui/button";
import { Dialog } from "../ui/dialog";
import { Input } from "../ui/input";

interface Props {
  plan: Plan;
  meta: Meta;
  onClose: () => void;
  onSimulated: (result: SimulateResult) => void;
}

function Callout({ tone, children }: { tone: "info" | "warning" | "error"; children: ReactNode }) {
  const styles = {
    info: "border-accent/30 bg-accent-soft text-ink",
    warning: "border-amber-500/30 bg-amber-500/10 text-ink",
    error: "border-red-500/30 bg-red-500/10 text-ink",
  };
  const Icon = tone === "info" ? Info : TriangleAlert;
  return (
    <div className={`flex gap-2.5 rounded-xl border px-3.5 py-3 text-[13px] ${styles[tone]}`}>
      <Icon className="mt-0.5 size-4 shrink-0 opacity-70" aria-hidden />
      <div>{children}</div>
    </div>
  );
}

function ItemList({ title, items, blocked }: { title: string; items: PlanItem[]; blocked: boolean }) {
  return (
    <details open={items.length <= 10} className="group rounded-xl border border-line">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-2.5 text-[13px] font-medium select-none [&::-webkit-details-marker]:hidden">
        <ChevronRight className="size-4 text-muted transition-transform group-open:rotate-90" aria-hidden />
        {`${title} (${items.length})`}
      </summary>
      <ul className="divide-y divide-line border-t border-line">
        {items.map((item) => {
          const notes = item.rules.filter((r) => r.outcome === (blocked ? "block" : "warn")).map((r) => r.message);
          return (
            <li key={item.id} className="px-4 py-2.5 text-[13px]">
              <span className="font-medium">{item.name || item.id}</span>
              <span className="text-muted"> · {item.region}</span>
              {item.parent && <span className="text-muted">{` · backing snapshot of ${item.parent}`}</span>}
              {notes.length > 0 && (
                <div className={blocked ? "mt-0.5 text-red-600 dark:text-red-400" : "mt-0.5 text-amber-700 dark:text-amber-400"}>{notes.join(" ")}</div>
              )}
            </li>
          );
        })}
      </ul>
    </details>
  );
}

function missingMessage(count: number): string {
  const subject = count === 1 ? "1 selected resource isn't" : `${count.toLocaleString()} selected resources aren't`;
  const left = count === 1 ? "it was" : "they were";
  return `${subject} in the latest scan, so ${left} left out. Reload the list to see the current resources.`;
}

/** The plan popup (base spec §9): all blocked, mixed, or none blocked. Always a simulation. */
export default function DeleteModal({ plan, meta, onClose, onSimulated }: Props) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Counts name what the user selected; backing snapshots ride along with their AMIs.
  const topBlocked = plan.blocked.filter((i) => !i.parent).length;
  const topDeletable = plan.deletable.filter((i) => !i.parent).length;
  const backing = plan.deletable.length - topDeletable;
  const what = plural(topDeletable, "resource") + (backing ? ` and ${plural(backing, "backing snapshot")}` : "");
  const needsTyping = plan.requires_typed_confirmation && plan.deletable.length > 0;
  const canSimulate = !needsTyping || typed.trim().toLowerCase() === "delete";

  const title =
    plan.variant === "all_blocked"
      ? "Can't delete these resources"
      : plan.variant === "mixed"
        ? `${topBlocked.toLocaleString()} blocked will be skipped`
        : `Simulate deleting ${what}?`;

  async function simulate() {
    setBusy(true);
    setError(null);
    try {
      onSimulated(await api.simulate(plan.plan_id, typed));
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <Dialog
      open
      onClose={onClose}
      size="lg"
      title="Simulation — nothing will be deleted."
      footer={
        plan.variant === "all_blocked" ? (
          <Button variant="primary" onClick={onClose}>
            Close
          </Button>
        ) : (
          <>
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button variant="primary" disabled={!canSimulate} loading={busy} onClick={simulate}>
              {plan.variant === "mixed" ? `Simulate ${topDeletable.toLocaleString()}` : "Simulate"}
            </Button>
          </>
        )
      }
    >
      <div className="space-y-4">
        <h3 className="text-lg font-semibold tracking-tight">{title}</h3>
        {plan.missing.length > 0 && <Callout tone="warning">{missingMessage(plan.missing.length)}</Callout>}
        {plan.blocked.length > 0 && <ItemList title="Blocked" items={plan.blocked} blocked />}
        {plan.variant === "mixed" && <p className="font-medium">Simulate deleting the other {what}?</p>}
        {plan.deletable.length > 0 && (
          <>
            <ItemList title="Would be deleted" items={plan.deletable} blocked={false} />
            <p className="text-[13px] text-muted">
              Total: {plural(plan.totals.count, "resource")}, {formatGiB(plan.totals.size_gib)}, {formatUsd(plan.totals.est_monthly_usd)} (estimate)
            </p>
            {plan.share_impact.map((impact) => (
              <Callout key={impact.ami_id} tone="info">
                <div className="font-medium">Share impact for {impact.ami_id}</div>
                {impact.accounts.length > 0 && `Deregistering removes it in ${impact.region} for ${impact.accounts.map((a) => a.name).join(", ")}. `}
                {impact.copies.length > 0 && `Its copies in ${impact.copies.map((c) => c.region).join(", ")} are separate and stay.`}
                {impact.accounts.length === 0 && impact.copies.length === 0 && "It isn't shared or copied."}
              </Callout>
            ))}
            {needsTyping && (
              <label className="block space-y-1.5">
                <span className="text-[13px] font-medium">Type delete to confirm</span>
                <span className="block text-xs text-muted">
                  {`Required for ${meta.policy.typed_confirm_min_items.toLocaleString()} or more items, any warning, or anything tagged env=prod.`}
                </span>
                <Input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="delete" />
              </label>
            )}
          </>
        )}
        {error && <Callout tone="error">{error}</Callout>}
      </div>
    </Dialog>
  );
}
