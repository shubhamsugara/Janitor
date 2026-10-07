import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Table from "@cloudscape-design/components/table";
import type { CostBreakdown as Breakdown } from "../api";
import { formatMoney, formatRate, formatUsd } from "../format";

/** Quantity × rate for every line, with the price list's region and date. */
export default function CostBreakdown({ breakdown }: { breakdown: Breakdown | null }) {
  if (!breakdown) return <Box>No cost: this resource has no size, or Janitor has no price for it.</Box>;
  const source = breakdown.source_date ? ` from the AWS price list of ${breakdown.source_date}` : "";
  return (
    <SpaceBetween size="s">
      <Table
        variant="embedded"
        items={breakdown.lines}
        columnDefinitions={[
          { id: "label", header: "Item", cell: (l) => l.label },
          { id: "quantity", header: "Quantity", cell: (l) => `${l.quantity.toLocaleString()} ${l.unit}` },
          { id: "rate", header: "Rate", cell: (l) => formatRate(l.rate) },
          { id: "amount", header: "Monthly", cell: (l) => formatMoney(l.amount) },
        ]}
      />
      <Box variant="h4">Total: {formatUsd(breakdown.total)}</Box>
      <Box color="text-body-secondary">
        {breakdown.region} prices{source}.{breakdown.estimate ? ` ${breakdown.estimate}` : ""}
      </Box>
      {breakdown.fallback && (
        <Alert type="warning">
          Some rates weren't in the AWS price list for {breakdown.region}, so Janitor used its configured fallback
          rates or left the item out. Run make prices to refresh the price list.
        </Alert>
      )}
    </SpaceBetween>
  );
}
