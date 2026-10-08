import { useEffect, useMemo, useState } from "react";
import { ChevronDown, Regex, Search, Tag, X, type LucideIcon } from "lucide-react";
import type { Meta, ResourceType, Status } from "../api";
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
  type?: ResourceType; // narrows the account choices to accounts that have this type
  filters: Filters;
  onChange: (f: Filters) => void;
  total: number | null;
}

/** Accounts that have this type in the scan, plus any already selected (so they can be cleared). */
function accountsFor(meta: Meta, type: ResourceType | undefined, selected: string[]) {
  const present = type ? meta.accounts_by_type?.[type] : undefined;
  if (!present) return meta.accounts;
  const keep = new Set([...present, ...selected]);
  return meta.accounts.filter((a) => keep.has(a.id));
}

interface TextFilterProps {
  label: string;
  icon: LucideIcon;
  hint: string;
  placeholder: string;
  clearLabel: string;
  value: string;
  onApply: (value: string) => void;
}

/** A pill that opens a one-field form: the tag and name pattern filters. */
function TextFilter({ label, icon: Icon, hint, placeholder, clearLabel, value, onApply }: TextFilterProps) {
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
          <Icon className="size-3.5" aria-hidden />
          <span>
            {label}
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
          {hint}
          <Input autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={placeholder} className="mt-1" />
        </label>
        <div className="flex justify-between">
          <Button size="sm" variant="ghost" onClick={() => { onApply(""); setOpen(false); }}>
            {clearLabel}
          </Button>
          <Button size="sm" variant="primary" type="submit">
            Apply
          </Button>
        </div>
      </form>
    </Popover>
  );
}

/** A filter set from a link in the detail panel; it has no picker, only a remove button. */
function SourcePill({ label, value, what, onRemove }: { label: string; value: string; what: string; onRemove: () => void }) {
  return (
    <span className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-accent/40 bg-accent-soft pr-1.5 pl-3 text-[13px] font-medium text-accent">
      <span className="max-w-72 truncate" title={value}>{`${label}: ${value}`}</span>
      <button type="button" onClick={onRemove} aria-label={`Remove the ${what} filter`} className="rounded p-0.5 hover:bg-accent/10">
        <X className="size-3.5" aria-hidden />
      </button>
    </span>
  );
}

/** Search plus filter pills. Every change goes back to page 1 (the URL holds the state). */
export default function FilterBar({ meta, type, filters, onChange, total }: Props) {
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
    () => accountsFor(meta, type, filters.account).map((a) => ({ value: a.id, text: a.name, label: (
        <span>
          <span className="font-medium">{a.name}</span>
          {a.name !== a.id && <span className="text-muted"> {a.id}</span>}
        </span>
      ) })),
    [meta, type, filters.account],
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
    <div data-tour="filter" className="flex flex-wrap items-center gap-2">
      <div className="relative w-full sm:w-64">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" aria-hidden />
        <Input value={q} onChange={(e) => setTyped(e.target.value)} placeholder="Search name or ID" aria-label="Search name or ID" className="pl-9" />
        {q && (
          <button type="button" onClick={() => setTyped("")} className="absolute top-1/2 right-2 -translate-y-1/2 rounded p-0.5 text-muted hover:text-ink" aria-label="Clear search">
            <X className="size-3.5" />
          </button>
        )}
      </div>
      {accountOptions.length > 1 && (
        <MultiSelect label="Account" options={accountOptions} value={filters.account} onChange={(account) => set({ account })} />
      )}
      <MultiSelect label="Status" options={statusOptions} value={filters.status} onChange={(status) => set({ status })} />
      <MultiSelect label="Region" options={regionOptions} value={filters.region} onChange={(region) => set({ region })} />
      <TextFilter
        label="Tag"
        icon={Tag}
        hint="Tag as key=value, or just a key"
        placeholder="env=prod"
        clearLabel="Clear tag"
        value={filters.tag}
        onApply={(tag) => set({ tag })}
      />
      <TextFilter
        label="Name pattern"
        icon={Regex}
        hint="A regular expression, matched anywhere in the name and ignoring case"
        placeholder="^base-linux-"
        clearLabel="Clear pattern"
        value={filters.name}
        onApply={(name) => set({ name })}
      />
      <DateFilter filters={filters} onChange={onChange} />
      {filters.sourceAmi && (
        <SourcePill label="Source AMI" value={filters.sourceAmi} what="source AMI" onRemove={() => set({ sourceAmi: "" })} />
      )}
      {filters.sourceDb && (
        <SourcePill label="Source database" value={filters.sourceDb} what="source database" onRemove={() => set({ sourceDb: "" })} />
      )}
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
