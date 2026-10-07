import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import DateRangePicker, { type DateRangePickerProps } from "@cloudscape-design/components/date-range-picker";
import Header from "@cloudscape-design/components/header";
import Link from "@cloudscape-design/components/link";
import Pagination from "@cloudscape-design/components/pagination";
import PropertyFilter, { type PropertyFilterProps } from "@cloudscape-design/components/property-filter";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Table, { type TableProps } from "@cloudscape-design/components/table";
import { api, exportCsvUrl, type Plan, type Resource, type ResourcePage, type ResourceType, type Status } from "../api";
import DeleteModal from "../components/DeleteModal";
import StatsHeader from "../components/StatsHeader";
import StatusBadge, { OutcomeBadge } from "../components/StatusBadge";
import { useDetail } from "../detail";
import { buildReport, downloadPdf } from "../export/pdfReport";
import { EMPTY, fromQuery, fromRange, hasFilters, parseFilters, toApiParams, toQuery, toRange, toSearch, type Filters } from "../filters";
import { accountName, formatDate, formatGiB, formatUsd, simulationSummary } from "../format";
import type { PageProps } from "../nav";
import { sequencer } from "../sequencer";

const PAGE_SIZE = 50;
const STATUSES: Status[] = ["in_use", "managed", "unknown", "orphaned", "idle"];
const RELATIVE_RANGES: DateRangePickerProps.RelativeOption[] = [
  { key: "last-30-days", amount: 30, unit: "day", type: "relative" },
  { key: "last-90-days", amount: 90, unit: "day", type: "relative" },
  { key: "last-year", amount: 1, unit: "year", type: "relative" },
];

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
  const [selected, setSelected] = useState<Resource[]>([]);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [planning, setPlanning] = useState(false);
  const [exporting, setExporting] = useState(false);
  const { open } = useDetail();
  const nextRequest = useMemo(sequencer, []);

  const load = useCallback(() => {
    const isCurrent = nextRequest(); // ignore responses for filters the user has moved past
    setLoading(true);
    const params = toApiParams(type, filters, {
      page: String(filters.page),
      page_size: String(PAGE_SIZE),
      sort: filters.sort,
    });
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

  const filteringProperties: PropertyFilterProps.FilteringProperty[] = useMemo(
    () => [
      {
        key: "account",
        propertyLabel: "Account",
        groupValuesLabel: "Accounts",
        operators: [{ operator: "=", format: (value) => accountName(meta, String(value)) }],
      },
      { key: "region", propertyLabel: "Region", groupValuesLabel: "Regions", operators: ["="] },
      {
        key: "status",
        propertyLabel: "Status",
        groupValuesLabel: "Statuses",
        operators: [{ operator: "=", format: (value) => meta.definitions.statuses[value as Status]?.label ?? String(value) }],
      },
      { key: "tag", propertyLabel: "Tag (key=value)", groupValuesLabel: "Tags", operators: ["="] },
    ],
    [meta],
  );
  const filteringOptions: PropertyFilterProps.FilteringOption[] = useMemo(() => {
    const regions = [...new Set([...meta.owner.regions, ...meta.accounts.flatMap((a) => a.regions)])].sort();
    return [
      ...meta.accounts.map((a) => ({ propertyKey: "account", value: a.id, label: a.name })),
      ...regions.map((r) => ({ propertyKey: "region", value: r })),
      ...STATUSES.map((s) => ({ propertyKey: "status", value: s, label: meta.definitions.statuses[s].label })),
    ];
  }, [meta]);

  const filtered = hasFilters(filters);
  const reset = () => setFilters({ ...EMPTY, sort: filters.sort });

  async function planDelete() {
    setPlanning(true);
    try {
      setPlan(await api.plan(type, selected.map((r) => r.id)));
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

  const columns: TableProps.ColumnDefinition<Resource>[] = [
    {
      id: "name",
      header: "Name",
      sortingField: "name",
      cell: (r) => (
        <Link
          href={`#${r.id}`}
          onFollow={(e) => {
            e.preventDefault();
            open(r.id);
          }}
        >
          {r.name || r.id}
        </Link>
      ),
    },
    { id: "id", header: "ID", sortingField: "id", cell: (r) => (type === "rds_snapshot" ? r.name : r.id) },
    {
      id: "status",
      header: "Status",
      sortingField: "status",
      cell: (r) => <StatusBadge meta={meta} type={r.type} status={r.status} reason={r.status_reason} />,
    },
    { id: "outcome", header: "Delete check", cell: (r) => <OutcomeBadge outcome={r.outcome} /> },
    { id: "account", header: "Account", sortingField: "account", cell: (r) => accountName(meta, r.account) },
    { id: "region", header: "Region", sortingField: "region", cell: (r) => r.region },
    { id: "created_at", header: "Created", sortingField: "created_at", cell: (r) => formatDate(r.created_at) },
    { id: "size_gb", header: "Size", sortingField: "size_gb", cell: (r) => formatGiB(r.size_gb) },
    { id: "cost", header: "Est. cost", sortingField: "est_monthly_cost", cell: (r) => formatUsd(r.est_monthly_cost) },
  ];

  const stats = data?.stats;
  const description = stats
    ? `${stats.orphaned.toLocaleString()} orphaned · ${formatGiB(stats.orphaned_gib)}` +
      (stats.orphaned_usd != null ? ` · ${formatUsd(stats.orphaned_usd)}` : "")
    : undefined;

  return (
    <SpaceBetween size="l">
      <Header
        variant="h1"
        counter={data ? `(${data.total.toLocaleString()})` : undefined}
        description={description}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown
              loading={exporting}
              items={[
                { id: "csv", text: "CSV, all matching rows" },
                { id: "pdf", text: "PDF report, up to 5,000 rows" },
              ]}
              onItemClick={({ detail }) => exportAs(detail.id)}
            >
              Export
            </ButtonDropdown>
            {selected.length > 0 && <Button onClick={() => setSelected([])}>Clear selection</Button>}
            <Button variant="primary" disabled={selected.length === 0} loading={planning} onClick={planDelete}>
              {selected.length ? `Plan delete (${selected.length})` : "Plan delete"}
            </Button>
          </SpaceBetween>
        }
      >
        {title}
      </Header>
      {stats && stats.total > 0 && <StatsHeader stats={stats} meta={meta} />}
      <Table
        variant="container"
        trackBy="id"
        items={data?.items ?? []}
        columnDefinitions={columns}
        loading={loading}
        loadingText={`Loading ${title}`}
        selectionType="multi"
        selectedItems={selected}
        onSelectionChange={({ detail }) => setSelected(detail.selectedItems)}
        sortingColumn={{ sortingField: filters.sort.replace(/^-/, "") }}
        sortingDescending={filters.sort.startsWith("-")}
        onSortingChange={({ detail }) =>
          setFilters({
            ...filters,
            sort: `${detail.isDescending ? "-" : ""}${detail.sortingColumn.sortingField ?? "created_at"}`,
            page: 1,
          })
        }
        filter={
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "flex-start" }}>
            <div style={{ flex: "1 1 420px" }}>
              <PropertyFilter
                query={toQuery(filters)}
                onChange={({ detail }) => setFilters(fromQuery(detail, filters))}
                filteringProperties={filteringProperties}
                filteringOptions={filteringOptions}
                filteringPlaceholder="Filter by account, region, status, tag, or name"
                countText={data ? `${data.total.toLocaleString()} matches` : ""}
                hideOperations
                expandToViewport
              />
            </div>
            <DateRangePicker
              value={toRange(filters)}
              onChange={({ detail }) => setFilters(fromRange(detail.value, filters))}
              relativeOptions={RELATIVE_RANGES}
              isValidRange={(value) =>
                value?.type === "absolute" && value.startDate && value.endDate && value.startDate > value.endDate
                  ? { valid: false, errorMessage: "The start date is after the end date. Choose an earlier start." }
                  : { valid: true }
              }
              dateOnly
              placeholder="Created between"
              expandToViewport
            />
            {filtered && <Button onClick={reset}>Reset filters</Button>}
          </div>
        }
        pagination={
          <Pagination
            currentPageIndex={filters.page}
            pagesCount={Math.max(1, Math.ceil((data?.total ?? 0) / PAGE_SIZE))}
            onChange={({ detail }) => setFilters({ ...filters, page: detail.currentPageIndex })}
          />
        }
        empty={
          <Box textAlign="center" color="inherit">
            {data?.scan_id == null ? (
              "No scan yet. Run a scan from the top bar."
            ) : filtered ? (
              <SpaceBetween size="s">
                <Box>No resources match these filters.</Box>
                <Button onClick={reset}>Reset filters</Button>
              </SpaceBetween>
            ) : (
              `No ${title} found.`
            )}
          </Box>
        }
      />
      {plan && (
        <DeleteModal
          plan={plan}
          meta={meta}
          onClose={() => setPlan(null)}
          onSimulated={(result) => {
            setPlan(null);
            setSelected([]);
            notify("success", simulationSummary(result));
          }}
        />
      )}
    </SpaceBetween>
  );
}
