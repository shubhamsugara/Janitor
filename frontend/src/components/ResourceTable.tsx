import type { ReactNode } from "react";
import type { Meta, Resource, ResourceType } from "../api";
import { accountName, formatDate, formatGiB, formatUsd } from "../format";
import { Skeleton } from "../ui/spinner";
import { Table, TBody, Td, Th, THead, Tr } from "../ui/table";
import AwsIcon from "./AwsIcon";
import StatusBadge, { OutcomeBadge } from "./StatusBadge";

interface Props {
  meta: Meta;
  type: ResourceType;
  items: Resource[];
  loading: boolean;
  sort: string;
  onSort: (sort: string) => void;
  selected: Resource[];
  onSelect: (selected: Resource[]) => void;
  onOpen: (id: string) => void;
  empty: ReactNode;
}

const COLUMNS: { key: string; label: string; sortable: boolean; className?: string }[] = [
  { key: "name", label: "Name", sortable: true },
  { key: "status", label: "Status", sortable: true },
  { key: "outcome", label: "Delete check", sortable: false },
  { key: "account", label: "Account", sortable: true },
  { key: "region", label: "Region", sortable: true },
  { key: "created_at", label: "Created", sortable: true },
  { key: "size_gb", label: "Size", sortable: true, className: "text-right" },
  { key: "est_monthly_cost", label: "Est. cost", sortable: true, className: "text-right" },
];

/** The resource list: server-sorted, page-level selection, name opens the detail drawer. */
export default function ResourceTable({ meta, items, loading, sort, onSort, selected, onSelect, onOpen, empty }: Props) {
  const selectedIds = new Set(selected.map((r) => r.id));
  const allOnPage = items.length > 0 && items.every((r) => selectedIds.has(r.id));
  const column = sort.replace(/^-/, "");
  const descending = sort.startsWith("-");

  function toggle(r: Resource) {
    onSelect(selectedIds.has(r.id) ? selected.filter((s) => s.id !== r.id) : [...selected, r]);
  }
  function toggleAll() {
    const onPage = new Set(items.map((r) => r.id));
    onSelect(allOnPage ? selected.filter((s) => !onPage.has(s.id)) : [...selected.filter((s) => !onPage.has(s.id)), ...items]);
  }

  return (
    <Table sticky aria-busy={loading || undefined}>
      <THead sticky>
        <tr>
          <Th className="w-10" data-tour="select">
            <input type="checkbox" className="size-4 accent-[var(--accent)]" checked={allOnPage} onChange={toggleAll} disabled={loading} aria-label="Select all on this page" />
          </Th>
          {COLUMNS.map((c) => (
            <Th
              key={c.key}
              className={c.className}
              sort={c.sortable ? { active: column === c.key, descending, onClick: () => onSort(column === c.key && !descending ? `-${c.key}` : c.key) } : undefined}
            >
              {c.label}
            </Th>
          ))}
        </tr>
      </THead>
      <TBody busy={loading && items.length > 0}>
        {loading && items.length === 0 ? (
          Array.from({ length: 8 }, (_, i) => (
            <Tr key={i}>
              {Array.from({ length: COLUMNS.length + 1 }, (_, j) => (
                <Td key={j}>
                  <Skeleton className="h-4 w-full max-w-32" />
                </Td>
              ))}
            </Tr>
          ))
        ) : items.length === 0 ? (
          <tr>
            <td colSpan={COLUMNS.length + 1} className="px-3 py-16 text-center text-muted">
              {empty}
            </td>
          </tr>
        ) : (
          items.map((r, i) => (
            <Tr key={r.id} className={selectedIds.has(r.id) ? "[&>td]:bg-accent-soft/60" : undefined}>
              <Td>
                <input type="checkbox" className="size-4 accent-[var(--accent)]" checked={selectedIds.has(r.id)} onChange={() => toggle(r)} disabled={loading} aria-label={`Select ${r.name || r.id}`} />
              </Td>
              <Td className="max-w-[340px]">
                <div className="flex min-w-0 items-center gap-3">
                  <AwsIcon kind={r.type} size={28} />
                  <div className="min-w-0">
                    <button type="button" onClick={() => onOpen(r.id)} className="block max-w-full truncate text-left font-medium text-ink hover:text-accent" title={r.name || r.id}>
                      {r.name || r.id}
                    </button>
                    <div className="truncate font-mono text-[11px] text-muted" title={r.id}>
                      {r.id}
                    </div>
                  </div>
                </div>
              </Td>
              <Td data-tour={i === 0 ? "status" : undefined}>
                <StatusBadge meta={meta} type={r.type} status={r.status} reason={r.status_reason} />
              </Td>
              <Td>
                <OutcomeBadge outcome={r.outcome} />
              </Td>
              <Td className="whitespace-nowrap">{accountName(meta, r.account)}</Td>
              <Td className="whitespace-nowrap text-muted">{r.region}</Td>
              <Td className="whitespace-nowrap text-muted">{formatDate(r.created_at)}</Td>
              <Td className="text-right whitespace-nowrap tabular-nums">{formatGiB(r.size_gb)}</Td>
              <Td className="text-right whitespace-nowrap tabular-nums">{formatUsd(r.est_monthly_cost)}</Td>
            </Tr>
          ))
        )}
      </TBody>
    </Table>
  );
}
