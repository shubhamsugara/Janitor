import { useCallback, useEffect, useMemo, useState } from "react";
import { TriangleAlert } from "lucide-react";
import { useSearchParams } from "react-router";
import { api, type DeploymentsData } from "../api";
import DeploymentPanel, { RUN_TONES, STATES } from "../components/DeploymentPanel";
import MultiSelect from "../components/MultiSelect";
import { groupChecks } from "../components/ScanHealth";
import { cellLabel, cellSummary, columnsOf, compareVersions, filterItems, rowsOf, type Cell, type Column, type DeploymentFilters } from "../deployments";
import { plural } from "../format";
import type { PageProps } from "../nav";
import { Badge } from "../ui/badge";
import { Card, CardBody, CardHeader } from "../ui/card";
import { cn } from "../ui/cn";
import { Input } from "../ui/input";
import { Sheet } from "../ui/sheet";
import { Spinner } from "../ui/spinner";
import { Table, TBody, Td, Th, THead, Tr } from "../ui/table";

// One width for every account column, so the grid reads evenly; long content wraps instead.
const APP_WIDTH = 220;
const COLUMN_WIDTH = 168;

const KINDS: { value: DeploymentFilters["kind"]; label: string }[] = [
  { value: "", label: "All" },
  { value: "ec2", label: "EC2" },
  { value: "ecs", label: "ECS" },
];

function parse(search: URLSearchParams): DeploymentFilters {
  const kind = search.get("kind");
  return {
    kind: kind === "ec2" || kind === "ecs" ? kind : "",
    accounts: (search.get("account") ?? "").split(",").filter(Boolean),
    q: search.get("q") ?? "",
  };
}

function toSearch(f: DeploymentFilters): URLSearchParams {
  const s = new URLSearchParams();
  if (f.kind) s.set("kind", f.kind);
  if (f.accounts.length) s.set("account", f.accounts.join(","));
  if (f.q) s.set("q", f.q);
  return s;
}

function CellButton({ cell, latest, onOpen }: { cell: Cell; latest: string | null; onOpen: () => void }) {
  const [newest] = cell.live;
  const behind = Boolean(newest && latest && compareVersions(newest.version, latest) < 0);
  const state = newest && newest.state !== "deployed" ? STATES[newest.state] : null;
  const summary = newest ? cellSummary(cell) : null;
  const run = summary?.run ?? null; // shown only when it isn't simply running
  return (
    <button
      type="button"
      onClick={onOpen}
      className="flex w-full flex-col items-start gap-1 rounded-lg px-2 py-1.5 text-left hover:bg-subtle focus-visible:ring-4 focus-visible:ring-ring focus-visible:outline-none"
    >
      <span
        className={cn(
          "font-mono text-[13px] break-words",
          !newest && "font-sans text-muted",
          behind && "text-amber-700 dark:text-amber-400",
        )}
        title={behind ? `Behind ${latest}` : undefined}
      >
        {cellLabel(cell)}
      </span>
      {summary && <span className="text-xs text-muted">{summary.count}</span>}
      {(state || (run && run.key !== "running") || Boolean(summary?.standalone)) && (
        <span className="flex flex-wrap gap-1">
          {state && newest.unit !== "instance" && <Badge tone={state.tone}>{state.label}</Badge>}
          {run && run.key !== "running" && <Badge tone={RUN_TONES[run.key]}>{run.label}</Badge>}
          {Boolean(summary?.standalone) && (
            <span title="Instances in no Auto Scaling group">
              <Badge>{summary?.standalone} standalone</Badge>
            </span>
          )}
        </span>
      )}
      {!newest && cell.history[0] && <span className="text-xs text-muted">Last: {cell.history[0].version || "no version tag"}</span>}
    </button>
  );
}

export default function Deployments({ meta, notify }: PageProps) {
  const [search, setSearch] = useSearchParams();
  const filters = useMemo(() => parse(search), [search]);
  const setFilters = useCallback((next: DeploymentFilters) => setSearch(toSearch(next), { replace: true }), [setSearch]);
  const [data, setData] = useState<DeploymentsData | null>(null);
  const [open, setOpen] = useState<{ app: string; column: Column; cell: Cell } | null>(null);

  useEffect(() => {
    api.deployments().then(setData).catch((e: Error) => notify("error", e.message));
  }, [notify]);

  const all = data?.items ?? [];
  const accountOptions = useMemo(
    () => columnsOf(all).filter((c, i, cols) => cols.findIndex((x) => x.account === c.account) === i).map((c) => ({ value: c.account, label: c.name, text: c.name })),
    [all],
  );
  const shown = useMemo(() => filterItems(all, filters), [all, filters]);
  const columns = useMemo(() => columnsOf(shown), [shown]);
  const rows = useMemo(() => rowsOf(shown), [shown]);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">
          Deployments {data && <span className="font-normal text-muted">({plural(rowsOf(all).length, "app")})</span>}
        </h2>
        <p className="mt-1 text-[13px] text-muted">
          Which version of each app runs in each account and region, from the last scan. EC2 apps are Auto Scaling groups tagged by your deploy tool; ECS apps are services. Read-only.
        </p>
      </div>

      {data && data.failed.length > 0 && (
        <Card className="border-amber-500/30">
          <CardHeader
            title={
              <span className="inline-flex items-center gap-2">
                <TriangleAlert className="size-4 text-amber-600 dark:text-amber-400" aria-hidden />
                Some deployments may be missing
              </span>
            }
            description="Janitor couldn't check these accounts, so their apps aren't listed."
          />
          <CardBody className="pt-3">
            <ul className="space-y-1.5 text-[13px]">
              {groupChecks(data.failed).map((line) => (
                <li key={line.key}>
                  <span className="font-medium">{line.label}</span>
                  {line.count > 1 && <span className="text-muted"> ({line.count} checks)</span>}: {line.message}
                </li>
              ))}
            </ul>
          </CardBody>
        </Card>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <div role="group" aria-label="Kind" className="inline-flex gap-1 rounded-lg bg-subtle p-1">
          {KINDS.map((k) => (
            <button
              key={k.label}
              type="button"
              aria-pressed={filters.kind === k.value}
              onClick={() => setFilters({ ...filters, kind: k.value })}
              className={cn(
                "rounded-md px-3 py-1 text-[13px] font-medium text-muted transition-colors hover:text-ink",
                filters.kind === k.value && "bg-card text-ink shadow-card",
              )}
            >
              {k.label}
            </button>
          ))}
        </div>
        <MultiSelect label="Account" options={accountOptions} value={filters.accounts} onChange={(accounts) => setFilters({ ...filters, accounts })} />
        <Input
          aria-label="Search apps"
          placeholder="Search apps"
          value={filters.q}
          onChange={(e) => setFilters({ ...filters, q: e.target.value })}
          className="w-60"
        />
      </div>

      <Card data-tour="deployments">
        {!data ? (
          <Spinner label="Loading deployments" className="justify-center py-16" />
        ) : all.length === 0 ? (
          <p className="px-6 py-16 text-center text-muted">
            No deployments in the last scan. Janitor lists Auto Scaling groups that carry the deploy state tag, and every ECS service.
          </p>
        ) : rows.length === 0 ? (
          <p className="py-16 text-center text-muted">No apps match these filters.</p>
        ) : (
          <Table className="table-fixed" style={{ width: APP_WIDTH + columns.length * COLUMN_WIDTH, minWidth: "100%" }}>
            <colgroup>
              <col style={{ width: APP_WIDTH }} />
              {columns.map((c) => (
                <col key={c.key} style={{ width: COLUMN_WIDTH }} />
              ))}
            </colgroup>
            <THead>
              <tr>
                <Th className="sticky left-0 z-[1] bg-card">App</Th>
                {columns.map((c) => (
                  <Th key={c.key} className="truncate" title={`${c.name} · ${c.region}`}>
                    <div className="truncate">{c.name}</div>
                    <div className="font-normal tracking-normal normal-case">{c.region}</div>
                  </Th>
                ))}
              </tr>
            </THead>
            <TBody>
              {rows.map((row) => (
                <Tr key={row.app}>
                  <Td className="sticky left-0 z-[1] bg-card align-top">
                    <div className="font-medium break-words">{row.app}</div>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {row.kinds.map((k) => (
                        <Badge key={k}>{k.toUpperCase()}</Badge>
                      ))}
                      {row.versions.length > 1 && <Badge tone="warning">{row.versions.length} versions</Badge>}
                    </div>
                  </Td>
                  {columns.map((c) => {
                    const cell = row.cells[c.key];
                    return (
                      <Td key={c.key} className="px-1.5 align-top">
                        {cell ? (
                          <CellButton cell={cell} latest={row.latest} onOpen={() => setOpen({ app: row.app, column: c, cell })} />
                        ) : (
                          <span className="px-2 text-muted" aria-label="Not deployed here">
                            –
                          </span>
                        )}
                      </Td>
                    );
                  })}
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </Card>

      <Sheet open={Boolean(open)} onClose={() => setOpen(null)} title={open ? `${open.app} · ${open.column.name} · ${open.column.region}` : "Deployment"}>
        {open && <DeploymentPanel cell={open.cell} meta={meta} />}
      </Sheet>
    </div>
  );
}
