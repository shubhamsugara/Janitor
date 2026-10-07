import { useCallback, useEffect, useMemo, useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Header from "@cloudscape-design/components/header";
import Link from "@cloudscape-design/components/link";
import Pagination from "@cloudscape-design/components/pagination";
import Select, { type SelectProps } from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Table, { type TableProps } from "@cloudscape-design/components/table";
import TextFilter from "@cloudscape-design/components/text-filter";
import { api, type Plan, type Resource, type ResourcePage, type ResourceType, type Status } from "../api";
import DeleteModal from "../components/DeleteModal";
import ResourceDetailPanel from "../components/ResourceDetail";
import StatusBadge, { OutcomeBadge } from "../components/StatusBadge";
import { accountName, formatDate, formatGiB, formatUsd, simulationSummary } from "../format";
import type { PageProps } from "../nav";

const PAGE_SIZE = 50;
const STATUS_ORDER: Status[] = ["in_use", "managed", "unknown", "orphaned", "idle"];
const ANY_STATUS: SelectProps.Option = { label: "Any status", value: "" };
const ANY_REGION: SelectProps.Option = { label: "Any region", value: "" };

interface Props extends PageProps {
  type: ResourceType;
  title: string;
}

export default function Resources({ meta, notify, type, title }: Props) {
  const [text, setText] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<SelectProps.Option>(ANY_STATUS);
  const [region, setRegion] = useState<SelectProps.Option>(ANY_REGION);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState({ field: "created_at", descending: true });
  const [data, setData] = useState<ResourcePage | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Resource[]>([]);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [planning, setPlanning] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(text);
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [text]);

  const load = useCallback(() => {
    setLoading(true);
    const params = new URLSearchParams({
      type,
      page: String(page),
      page_size: String(PAGE_SIZE),
      sort: `${sort.descending ? "-" : ""}${sort.field}`,
    });
    if (query) params.set("q", query);
    if (status.value) params.set("status", status.value);
    if (region.value) params.set("region", region.value);
    api
      .resources(params)
      .then(setData)
      .catch((e: Error) => notify("error", e.message))
      .finally(() => setLoading(false));
  }, [type, page, sort, query, status, region, notify]);
  useEffect(load, [load]);

  const regionOptions = useMemo(() => {
    const regions = new Set([...meta.owner.regions, ...meta.accounts.flatMap((a) => a.regions)]);
    return [ANY_REGION, ...[...regions].sort().map((r) => ({ label: r, value: r }))];
  }, [meta]);

  const filtered = Boolean(text || status.value || region.value);
  function resetFilters() {
    setText("");
    setStatus(ANY_STATUS);
    setRegion(ANY_REGION);
    setPage(1);
  }

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
            setDetailId(r.id);
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
    ? `${stats.orphaned.toLocaleString()} orphaned · ${formatGiB(stats.size_gib)}` +
      (stats.est_monthly_usd != null ? ` · ${formatUsd(stats.est_monthly_usd)}` : "")
    : undefined;

  return (
    <SpaceBetween size="l">
      <Table
        variant="full-page"
        trackBy="id"
        items={data?.items ?? []}
        columnDefinitions={columns}
        loading={loading}
        loadingText={`Loading ${title}`}
        selectionType="multi"
        selectedItems={selected}
        onSelectionChange={({ detail }) => setSelected(detail.selectedItems)}
        sortingColumn={{ sortingField: sort.field }}
        sortingDescending={sort.descending}
        onSortingChange={({ detail }) => {
          setSort({ field: detail.sortingColumn.sortingField ?? "created_at", descending: Boolean(detail.isDescending) });
          setPage(1);
        }}
        header={
          <Header
            variant="h1"
            counter={data ? `(${data.total.toLocaleString()})` : undefined}
            description={description}
            actions={
              <SpaceBetween direction="horizontal" size="xs">
                {selected.length > 0 && <Button onClick={() => setSelected([])}>Clear selection</Button>}
                <Button variant="primary" disabled={selected.length === 0} loading={planning} onClick={planDelete}>
                  {selected.length ? `Plan delete (${selected.length})` : "Plan delete"}
                </Button>
              </SpaceBetween>
            }
          >
            {title}
          </Header>
        }
        filter={
          <SpaceBetween direction="horizontal" size="xs">
            <TextFilter
              filteringText={text}
              filteringPlaceholder="Find by name or ID"
              countText={data ? `${data.total.toLocaleString()} matches` : ""}
              onChange={({ detail }) => setText(detail.filteringText)}
            />
            <Select
              selectedOption={status}
              options={[ANY_STATUS, ...STATUS_ORDER.map((s) => ({ label: meta.definitions.statuses[s].label, value: s }))]}
              onChange={({ detail }) => {
                setStatus(detail.selectedOption);
                setPage(1);
              }}
            />
            <Select
              selectedOption={region}
              options={regionOptions}
              onChange={({ detail }) => {
                setRegion(detail.selectedOption);
                setPage(1);
              }}
            />
            {filtered && <Button onClick={resetFilters}>Reset filters</Button>}
          </SpaceBetween>
        }
        pagination={
          <Pagination
            currentPageIndex={page}
            pagesCount={Math.max(1, Math.ceil((data?.total ?? 0) / PAGE_SIZE))}
            onChange={({ detail }) => setPage(detail.currentPageIndex)}
          />
        }
        empty={
          <Box textAlign="center" color="inherit">
            {data?.scan_id == null ? (
              "No scan yet. Run a scan from the overview."
            ) : filtered ? (
              <SpaceBetween size="s">
                <Box>No resources match these filters.</Box>
                <Button onClick={resetFilters}>Reset filters</Button>
              </SpaceBetween>
            ) : (
              `No ${title} found.`
            )}
          </Box>
        }
      />
      {detailId && <ResourceDetailPanel id={detailId} meta={meta} onClose={() => setDetailId(null)} />}
      {plan && (
        <DeleteModal
          plan={plan}
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
