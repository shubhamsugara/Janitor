import Box from "@cloudscape-design/components/box";
import Popover from "@cloudscape-design/components/popover";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator, { type StatusIndicatorProps } from "@cloudscape-design/components/status-indicator";
import type { Meta, Outcome, ResourceType, Status } from "../api";

const INDICATOR: Record<Status, StatusIndicatorProps.Type> = {
  in_use: "success",
  managed: "info",
  unknown: "warning",
  orphaned: "error",
  idle: "stopped",
};

interface Props {
  meta: Meta;
  type: ResourceType;
  status: Status;
  reason?: string;
}

/** A status chip whose popover explains the status, using the server's definitions. */
export default function StatusBadge({ meta, type, status, reason }: Props) {
  const def = meta.definitions.statuses[status];
  return (
    <Popover
      header={def.label}
      triggerType="text"
      size="medium"
      dismissButton={false}
      content={
        <SpaceBetween size="s">
          <Box>{meta.definitions.by_type[type][status] ?? def.meaning}</Box>
          {reason && (
            <Box>
              <Box variant="awsui-key-label">Why this one</Box>
              {reason}
            </Box>
          )}
          <Box>
            <Box variant="awsui-key-label">{def.blocks ? "Blocks deletion" : "Can be deleted"}</Box>
            {def.what_to_do}
          </Box>
        </SpaceBetween>
      }
    >
      <StatusIndicator type={INDICATOR[status]}>{def.label}</StatusIndicator>
    </Popover>
  );
}

export function OutcomeBadge({ outcome }: { outcome: Outcome }) {
  if (outcome === "block") return <StatusIndicator type="stopped">Blocked</StatusIndicator>;
  if (outcome === "warn") return <StatusIndicator type="warning">Review</StatusIndicator>;
  return <StatusIndicator type="info">Deletable</StatusIndicator>;
}
