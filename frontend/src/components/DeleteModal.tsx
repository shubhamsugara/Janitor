import { useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ExpandableSection from "@cloudscape-design/components/expandable-section";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Modal from "@cloudscape-design/components/modal";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { api, type Meta, type Plan, type PlanItem, type SimulateResult } from "../api";
import { formatGiB, formatUsd, plural } from "../format";

interface Props {
  plan: Plan;
  meta: Meta;
  onClose: () => void;
  onSimulated: (result: SimulateResult) => void;
}

function ItemList({ title, items, blocked }: { title: string; items: PlanItem[]; blocked: boolean }) {
  return (
    <ExpandableSection headerText={`${title} (${items.length})`} defaultExpanded={items.length <= 10}>
      <ul>
        {items.map((item) => {
          const notes = item.rules.filter((r) => r.outcome === (blocked ? "block" : "warn")).map((r) => r.message);
          return (
            <li key={item.id}>
              <strong>{item.name || item.id}</strong> · {item.region}
              {item.parent && ` · backing snapshot of ${item.parent}`}
              {notes.length > 0 && <Box color={blocked ? "text-status-error" : "text-status-warning"}>{notes.join(" ")}</Box>}
            </li>
          );
        })}
      </ul>
    </ExpandableSection>
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
    <Modal
      visible
      onDismiss={onClose}
      closeAriaLabel="Close dialog"
      header="Simulation — nothing will be deleted."
      size="large"
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            {plan.variant === "all_blocked" ? (
              <Button variant="primary" onClick={onClose}>
                Close
              </Button>
            ) : (
              <>
                <Button variant="link" onClick={onClose}>
                  Cancel
                </Button>
                <Button variant="primary" disabled={!canSimulate} loading={busy} onClick={simulate}>
                  {plan.variant === "mixed" ? `Simulate ${topDeletable.toLocaleString()}` : "Simulate"}
                </Button>
              </>
            )}
          </SpaceBetween>
        </Box>
      }
    >
      <SpaceBetween size="m">
        <Box variant="h3">{title}</Box>
        {plan.missing.length > 0 && <Alert type="warning">{missingMessage(plan.missing.length)}</Alert>}
        {plan.blocked.length > 0 && <ItemList title="Blocked" items={plan.blocked} blocked />}
        {plan.variant === "mixed" && <Box>Simulate deleting the other {what}?</Box>}
        {plan.deletable.length > 0 && (
          <>
            <ItemList title="Would be deleted" items={plan.deletable} blocked={false} />
            <Box>
              Total: {plural(plan.totals.count, "resource")}, {formatGiB(plan.totals.size_gib)},{" "}
              {formatUsd(plan.totals.est_monthly_usd)} (estimate)
            </Box>
            {plan.share_impact.map((impact) => (
              <Alert key={impact.ami_id} type="info" header={`Share impact for ${impact.ami_id}`}>
                {impact.accounts.length > 0 &&
                  `Deregistering removes it in ${impact.region} for ${impact.accounts.map((a) => a.name).join(", ")}. `}
                {impact.copies.length > 0 &&
                  `Its copies in ${impact.copies.map((c) => c.region).join(", ")} are separate and stay.`}
                {impact.accounts.length === 0 && impact.copies.length === 0 && "It isn't shared or copied."}
              </Alert>
            ))}
            {needsTyping && (
              <FormField
                label="Type delete to confirm"
                description={`Required for ${meta.policy.typed_confirm_min_items.toLocaleString()} or more items, any warning, or anything tagged env=prod.`}
              >
                <Input value={typed} onChange={({ detail }) => setTyped(detail.value)} placeholder="delete" />
              </FormField>
            )}
          </>
        )}
        {error && <Alert type="error">{error}</Alert>}
      </SpaceBetween>
    </Modal>
  );
}
