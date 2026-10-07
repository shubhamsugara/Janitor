import type { Meta, Outcome, ResourceType, Status } from "../api";
import { OutcomePill, StatusPill } from "../ui/pills";
import { Popover } from "../ui/popover";

interface Props {
  meta: Meta;
  type: ResourceType;
  status: Status;
  reason?: string;
}

/** A status pill whose popover explains the status, using the server's definitions. */
export default function StatusBadge({ meta, type, status, reason }: Props) {
  const def = meta.definitions.statuses[status];
  return (
    <Popover
      className="w-80 text-[13px]"
      trigger={
        <button type="button" className="rounded-full hover:ring-2 hover:ring-ring" aria-label={def.label}>
          <StatusPill status={status} label={def.label} />
        </button>
      }
    >
      <div className="space-y-3">
        <div className="font-semibold">{def.label}</div>
        <p className="text-muted">{meta.definitions.by_type[type]?.[status] ?? def.meaning}</p>
        {reason && (
          <div>
            <div className="text-[11px] font-semibold tracking-wider text-muted uppercase">Why this one</div>
            <p>{reason}</p>
          </div>
        )}
        <div>
          {/* Other rules (protected tag, too new) can still block an idle or orphaned resource. */}
          <div className="text-[11px] font-semibold tracking-wider text-muted uppercase">
            {def.blocks ? "Blocks deletion" : "Doesn't block deletion"}
          </div>
          <p>{def.what_to_do}</p>
        </div>
      </div>
    </Popover>
  );
}

export function OutcomeBadge({ outcome }: { outcome: Outcome }) {
  return <OutcomePill outcome={outcome} />;
}
