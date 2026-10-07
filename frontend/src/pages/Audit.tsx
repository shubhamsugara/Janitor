import { useEffect, useState } from "react";
import Box from "@cloudscape-design/components/box";
import ExpandableSection from "@cloudscape-design/components/expandable-section";
import Header from "@cloudscape-design/components/header";
import Pagination from "@cloudscape-design/components/pagination";
import Table from "@cloudscape-design/components/table";
import { api, type AuditEntry } from "../api";
import { formatDate } from "../format";
import type { PageProps } from "../nav";

const ACTIONS: Record<string, string> = {
  scan_started: "Scan started",
  scan_finished: "Scan finished",
  plan: "Plan",
  simulate: "Simulation",
};

function summary(entry: AuditEntry): string {
  const p = entry.payload as Record<string, unknown>;
  switch (entry.action) {
    case "scan_started":
      return `Scan ${p.scan_id} started (${p.provider}).`;
    case "scan_finished":
      return `Scan ${p.scan_id} finished: ${p.status}.`;
    case "plan":
      return `${p.deletable} deletable, ${p.blocked} blocked.`;
    case "simulate": {
      const items = (p.items as { outcome: string }[]) ?? [];
      const would = items.filter((i) => i.outcome === "would_delete").length;
      return `${would} would be deleted, ${items.length - would} skipped.`;
    }
    default:
      return entry.action;
  }
}

export default function Audit({ notify }: PageProps) {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<{ items: AuditEntry[]; total: number } | null>(null);

  useEffect(() => {
    api.audit(page).then(setData).catch((e: Error) => notify("error", e.message));
  }, [page, notify]);

  return (
    <Table
      variant="full-page"
      loading={!data}
      loadingText="Loading the audit log"
      items={data?.items ?? []}
      header={
        <Header variant="h1" counter={data ? `(${data.total})` : undefined} description="Scans and simulations, newest first. Nothing here deleted anything.">
          Audit
        </Header>
      }
      columnDefinitions={[
        { id: "ts", header: "Time", cell: (e) => formatDate(e.ts) },
        { id: "action", header: "Action", cell: (e) => ACTIONS[e.action] ?? e.action },
        { id: "actor", header: "Actor", cell: (e) => e.actor },
        {
          id: "details",
          header: "Details",
          cell: (e) => (
            <ExpandableSection headerText={summary(e)} variant="footer">
              <Box variant="code">
                <pre>{JSON.stringify(e.payload, null, 2)}</pre>
              </Box>
            </ExpandableSection>
          ),
        },
      ]}
      pagination={
        <Pagination
          currentPageIndex={page}
          pagesCount={Math.max(1, Math.ceil((data?.total ?? 0) / 25))}
          onChange={({ detail }) => setPage(detail.currentPageIndex)}
        />
      }
      empty={<Box textAlign="center">No activity yet.</Box>}
    />
  );
}
