import { TriangleAlert } from "lucide-react";
import type { CostBreakdown as Breakdown } from "../api";
import { formatMoney, formatRate, formatUsd } from "../format";
import { Table, TBody, Td, Th, THead, Tr } from "../ui/table";

/** Quantity × rate for every line, with the price list's region and date. */
export default function CostBreakdown({ breakdown }: { breakdown: Breakdown | null }) {
  if (!breakdown) return <p className="text-muted">No cost: this resource has no size, or Janitor has no price for it.</p>;
  const source = breakdown.source_date ? ` from the AWS price list of ${breakdown.source_date}` : "";
  return (
    <div className="space-y-4">
      <div className="overflow-hidden rounded-xl border border-line bg-card">
        <Table>
          <THead>
            <tr>
              <Th>Item</Th>
              <Th>Quantity</Th>
              <Th className="text-right">Rate</Th>
              <Th className="text-right">Monthly</Th>
            </tr>
          </THead>
          <TBody>
            {breakdown.lines.map((l) => (
              <Tr key={l.label}>
                <Td className="font-medium">{l.label}</Td>
                <Td className="text-muted tabular-nums">{`${l.quantity.toLocaleString()} ${l.unit}`}</Td>
                <Td className="text-right text-muted tabular-nums">{formatRate(l.rate)}</Td>
                <Td className="text-right tabular-nums">{formatMoney(l.amount)}</Td>
              </Tr>
            ))}
          </TBody>
        </Table>
        <div className="flex items-center justify-between bg-subtle/60 px-4 py-3">
          <span className="text-[13px] font-medium text-muted">Total</span>
          <span className="text-lg font-semibold tabular-nums">{formatUsd(breakdown.total)}</span>
        </div>
      </div>
      <p className="text-[13px] text-muted">
        {breakdown.region} prices{source}.{breakdown.estimate ? ` ${breakdown.estimate}` : ""}
      </p>
      {breakdown.fallback && (
        <div className="flex gap-2.5 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3.5 py-3 text-[13px]">
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-amber-600" aria-hidden />
          Some rates weren't in the AWS price list for {breakdown.region}, so Janitor used its configured fallback rates or left the item out. Run make
          prices to refresh the price list.
        </div>
      )}
    </div>
  );
}
