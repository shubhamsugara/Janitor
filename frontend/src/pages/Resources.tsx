import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, Trash, X } from "lucide-react";
import { useSearchParams } from "react-router";
import { api, exportCsvUrl, type Plan, type Resource, type ResourcePage, type ResourceType } from "../api";
import DeleteModal from "../components/DeleteModal";
import FilterBar from "../components/FilterBar";
import ResourceTable from "../components/ResourceTable";
import StatsHeader from "../components/StatsHeader";
import { useDetail } from "../detail";
import { buildReport, downloadPdf } from "../export/pdfReport";
import { EMPTY, filtersToApi, hasFilters, parseFilters, toApiParams, toSearch, type Filters } from "../filters";
import { formatGiB, formatUsd, simulationSummary } from "../format";
import type { PageProps } from "../nav";
import { sequencer } from "../sequencer";
import { Button } from "../ui/button";
import { Card } from "../ui/card";
import { Menu } from "../ui/dropdown";

const PAGE_SIZE = 50;

interface Props extends PageProps {
  type: ResourceType;
  title: string;
}

export default function Resources({ meta, notify, type, title }: Props) {
  const [search, setSearch] = useSearchParams();
  const filters = useMemo(() => parseFilters(search), [search]);
  const setFilters = useCallback((next: Filters) => setSearch(toSearch(next), { replace: true }), [setSearch]);
  const [data, setData] = useState<ResourcePage | null>(null);
  const [loading, setLoading] = useState(true);
  const [picked, setPicked] = useState<Resource[]>([]);
  // "Select all N matching": every match except the rows unchecked since; null = only `picked`.
  const [all, setAll] = useState<{ total: number; exclude: Set<string> } | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [planning, setPlanning] = useState(false);
  const [exporting, setExporting] = useState(false);
  const { open } = useDetail();
  const nextRequest = useMemo(sequencer, []);

  const load = useCallback(() => {
    const isCurrent = nextRequest(); // ignore responses for filters the user has moved past
    setLoading(true);
    const params = toApiParams(type, filters, { page: String(filters.page), page_size: String(PAGE_SIZE), sort: filters.sort });
    api
      .resources(params)
      .then((result) => {
        if (isCurrent()) setData(result);
      })
      .catch((e: Error) => {
        if (isCurrent()) notify("error", e.message);
      })
      .finally(() => {
        if (isCurrent()) setLoading(false);
      });
  }, [type, filters, notify, nextRequest]);
  useEffect(load, [load]);
  // All-matching means "these filters", so any filter or sort change ends it. Paging doesn't.
  const query = JSON.stringify({ ...filters, page: 0 });
  useEffect(() => setAll(null), [query]);

  const items = data?.items ?? [];
  const selected = all ? items.filter((r) => !all.exclude.has(r.id)) : picked;
  const count = all ? all.total - all.exclude.size : picked.length;
  const select = (next: Resource[]) => {
    if (!all) return setPicked(next);
    const keep = new Set(next.map((r) => r.id));
    const exclude = new Set(all.exclude);
    for (const r of items) {
      if (keep.has(r.id)) exclude.delete(r.id);
      else exclude.add(r.id);
    }
    setAll({ ...all, exclude });
  };
  const clearSelection = () => {
    setAll(null);
    setPicked([]);
  };
  const pageSelected = items.length > 0 && items.every((r) => picked.some((p) => p.id === r.id));
  const canSelectAll = !all && pageSelected && (data?.total ?? 0) > items.length;

  const filtered = hasFilters(filters);
  const reset = () => setFilters({ ...EMPTY, sort: filters.sort });
  const pages = Math.max(1, Math.ceil((data?.total ?? 0) / PAGE_SIZE));

  async function planDelete() {
    setPlanning(true);
    try {
      setPlan(
        all
          ? await api.planMatching(type, filtersToApi(type, filters), [...all.exclude])
          : await api.plan(type, picked.map((r) => r.id)),
      );
    } catch (e) {
      notify("error", (e as Error).message);
    } finally {
      setPlanning(false);
    }
  }

  async function exportAs(format: string) {
    const params = toApiParams(type, filters, { sort: filters.sort });
    if (format === "csv") {
      const link = document.createElement("a");
      link.href = exportCsvUrl(params);
      link.download = "";
      link.click();
      return;
    }
    setExporting(true);
    try {
      const report = buildReport(await api.exportJson(params), meta, type, title);
      await downloadPdf(report);
      notify("success", `Exported ${report.rows.length.toLocaleString()} rows to ${report.filename}.`);
    } catch (e) {
      notify("error", `Couldn't build the PDF (${(e as Error).message}). Try again, or export CSV.`);
    } finally {
      setExporting(false);
    }
  }

  const stats = data?.stats;
  const summary = stats
    ? `${stats.orphaned.toLocaleString()} orphaned · ${formatGiB(stats.orphaned_gib)}` + (stats.orphaned_usd != null ? ` · ${formatUsd(stats.orphaned_usd)}` : "")
    : "Loading";

  const empty =
    data?.scan_id == null && !loading ? (
      "No scan yet. Run a scan from the top bar."
    ) : filtered ? (
      <div className="space-y-3">
        <p>No resources match these filters.</p>
        <Button size="sm" onClick={reset}>
          Reset filters
        </Button>
      </div>
    ) : (
      `No ${title} found.`
    );

  return (
    <div className="space-y-6 pb-24">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">
            {title} {data && <span className="font-normal text-muted">({data.total.toLocaleString()})</span>}
          </h2>
          <p className="mt-1 text-[13px] text-muted">{summary}</p>
        </div>
        <div className="flex items-center gap-2">
          <Menu
            label="Export"
            loading={exporting}
            onSelect={exportAs}
            items={[
              { id: "csv", label: "CSV", description: "All matching rows" },
              { id: "pdf", label: "PDF report", description: "Up to 5,000 rows" },
            ]}
          />
          <Button variant="primary" disabled={count === 0} loading={planning} onClick={planDelete}>
            {count ? `Plan delete (${count.toLocaleString()})` : "Plan delete"}
          </Button>
        </div>
      </div>

      {stats && stats.total > 0 && <StatsHeader stats={stats} meta={meta} />}

      <Card>
        <div className="border-b border-line p-4">
          <FilterBar meta={meta} type={type} filters={filters} onChange={setFilters} total={data?.total ?? null} />
        </div>
        <ResourceTable
          meta={meta}
          type={type}
          items={items}
          loading={loading}
          sort={filters.sort}
          onSort={(sort) => setFilters({ ...filters, sort, page: 1 })}
          selected={selected}
          onSelect={select}
          onOpen={open}
          empty={empty}
        />
        <div className="flex items-center justify-between px-4 py-3 text-[13px] text-muted">
          <span>
            Page {filters.page.toLocaleString()} of {pages.toLocaleString()}
          </span>
          <div className="flex gap-1">
            <Button size="sm" variant="ghost" disabled={filters.page <= 1} onClick={() => setFilters({ ...filters, page: filters.page - 1 })} aria-label="Previous page">
              <ChevronLeft className="size-4" />
            </Button>
            <Button size="sm" variant="ghost" disabled={filters.page >= pages} onClick={() => setFilters({ ...filters, page: filters.page + 1 })} aria-label="Next page">
              <ChevronRight className="size-4" />
            </Button>
          </div>
        </div>
      </Card>

      {count > 0 && (
        <div className="animate-pop-in fixed bottom-6 left-1/2 z-20 flex -translate-x-1/2 items-center gap-3 rounded-2xl border border-line bg-card py-2 pr-2 pl-4 shadow-2xl">
          <span className="text-sm font-medium">
            {!all
              ? `${count.toLocaleString()} selected`
              : all.exclude.size
                ? `${count.toLocaleString()} of ${all.total.toLocaleString()} matching selected`
                : `All ${all.total.toLocaleString()} matching selected`}
          </span>
          {canSelectAll && (
            <Button size="sm" variant="secondary" onClick={() => setAll({ total: data!.total, exclude: new Set() })}>
              {`Select all ${data!.total.toLocaleString()} matching`}
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={clearSelection}>
            <X className="size-3.5" aria-hidden />
            Clear
          </Button>
          <Button size="sm" variant="primary" loading={planning} onClick={planDelete}>
            <Trash className="size-3.5" aria-hidden />
            Plan delete
          </Button>
        </div>
      )}

      {plan && (
        <DeleteModal
          plan={plan}
          meta={meta}
          onClose={() => setPlan(null)}
          onSimulated={(result) => {
            setPlan(null);
            clearSelection();
            notify("success", simulationSummary(result));
          }}
        />
      )}
    </div>
  );
}
