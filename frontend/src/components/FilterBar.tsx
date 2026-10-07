import { useEffect, useMemo, useState } from "react";
import { ChevronDown, Search, Tag, X } from "lucide-react";
import type { Meta, Status } from "../api";
import { EMPTY, hasFilters, type Filters } from "../filters";
import { Button } from "../ui/button";
import { cn } from "../ui/cn";
import { Input } from "../ui/input";
import { StatusPill } from "../ui/pills";
import { Popover } from "../ui/popover";
import DateFilter from "./DateFilter";
import MultiSelect, { type Option } from "./MultiSelect";

const STATUSES: Status[] = ["in_use", "managed", "unknown", "orphaned", "idle"];

interface Props {
  meta: Meta;
  filters: Filters;
  onChange: (f: Filters) => void;
  total: number | null;
}

function TagFilter({ value, onApply }: { value: string; onApply: (tag: string) => void }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(value);
  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) setDraft(value);
      }}
      className="w-64"
      trigger={
        <button
          type="button"
          className={cn(
            "inline-flex h-9 items-center gap-1.5 rounded-lg border px-3 text-[13px] font-medium transition-colors",
            value ? "border-accent/40 bg-accent-soft text-accent" : "border-dashed border-line bg-card text-ink hover:bg-subtle",
          )}
        >
          <Tag className="size-3.5" aria-hidden />
          <span>
            Tag
            {value && <span className="font-normal">: {value}</span>}
          </span>
          <ChevronDown className="size-3.5 opacity-60" aria-hidden />
        </button>
      }
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          onApply(draft.trim());
          setOpen(false);
        }}
        className="space-y-2"
      >
        <label className="text-xs text-muted">
          Tag as key=value, or just a key
          <Input autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="env=prod" className="mt-1" />
        </label>
        <div className="flex justify-between">
          <Button size="sm" variant="ghost" onClick={() => { onApply(""); setOpen(false); }}>
            Clear tag
          </Button>
          <Button size="sm" variant="primary" type="submit">
            Apply
          </Button>
        </div>
      </form>
    </Popover>
  );
}

/** Search plus filter pills. Every change goes back to page 1 (the URL holds the state). */
export default function FilterBar({ meta, filters, onChange, total }: Props) {
  // `typed` is what the user is typing; null means "show the filter as it is" (e.g. after Reset).
  const [typed, setTyped] = useState<string | null>(null);
  const q = typed ?? filters.q;
  // Any outside change to the filters (Reset, a pill, navigation) wins over half-typed text.
  useEffect(() => setTyped(null), [filters]);
  useEffect(() => {
    if (typed === null) return;
    const timer = setTimeout(() => {
      setTyped(null);
      if (typed !== filters.q) onChange({ ...filters, q: typed, page: 1 });
    }, 300); // wait for typing to pause
    return () => clearTimeout(timer);
  }, [typed, filters, onChange]);

  const accountOptions: Option[] = useMemo(
    () => meta.accounts.map((a) => ({ value: a.id, text: a.name, label: <span><span className="font-medium">{a.name}</span> <span className="text-muted">{a.id}</span></span> })),
    [meta],
  );
  const regionOptions: Option[] = useMemo(() => {
    const regions = [...new Set([...meta.owner.regions, ...meta.accounts.flatMap((a) => a.regions)])].sort();
    return regions.map((r) => ({ value: r, text: r, label: r }));
  }, [meta]);
  const statusOptions: Option[] = STATUSES.map((s) => ({
    value: s,
    text: meta.definitions.statuses[s].label,
    label: <StatusPill status={s} label={meta.definitions.statuses[s].label} />,
  }));

  const set = (patch: Partial<Filters>) => onChange({ ...filters, ...patch, page: 1 });

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="relative w-full sm:w-64">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" aria-hidden />
        <Input value={q} onChange={(e) => setTyped(e.target.value)} placeholder="Search name or ID" aria-label="Search name or ID" className="pl-9" />
        {q && (
          <button type="button" onClick={() => setTyped("")} className="absolute top-1/2 right-2 -translate-y-1/2 rounded p-0.5 text-muted hover:text-ink" aria-label="Clear search">
            <X className="size-3.5" />
          </button>
        )}
      </div>
      <MultiSelect label="Account" options={accountOptions} value={filters.account} onChange={(account) => set({ account })} />
      <MultiSelect label="Status" options={statusOptions} value={filters.status} onChange={(status) => set({ status })} />
      <MultiSelect label="Region" options={regionOptions} value={filters.region} onChange={(region) => set({ region })} />
      <TagFilter value={filters.tag} onApply={(tag) => set({ tag })} />
      <DateFilter filters={filters} onChange={onChange} />
      <div className="ml-auto flex items-center gap-3">
        {total != null && <span className="text-[13px] text-muted">{total.toLocaleString()} matches</span>}
        {hasFilters(filters) && (
          <Button size="sm" variant="ghost" onClick={() => onChange({ ...EMPTY, sort: filters.sort })}>
            Reset filters
          </Button>
        )}
      </div>
    </div>
  );
}
