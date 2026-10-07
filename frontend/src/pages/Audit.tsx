import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { api, type AuditEntry } from "../api";
import { formatDate } from "../format";
import type { PageProps } from "../nav";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Card } from "../ui/card";
import { Spinner } from "../ui/spinner";
import { Table, TBody, Td, Th, THead, Tr } from "../ui/table";

const ACTIONS: Record<string, { label: string; tone: "neutral" | "accent" | "success" | "warning" }> = {
  scan_started: { label: "Scan started", tone: "neutral" },
  scan_finished: { label: "Scan finished", tone: "success" },
  plan: { label: "Plan", tone: "accent" },
  simulate: { label: "Simulation", tone: "warning" },
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
  const pages = Math.max(1, Math.ceil((data?.total ?? 0) / 25));

  useEffect(() => {
    api.audit(page).then(setData).catch((e: Error) => notify("error", e.message));
  }, [page, notify]);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">
          Audit {data && <span className="font-normal text-muted">({data.total.toLocaleString()})</span>}
        </h2>
        <p className="mt-1 text-[13px] text-muted">Scans and simulations, newest first. Nothing here deleted anything.</p>
      </div>
      <Card>
        {!data ? (
          <Spinner label="Loading the audit log" className="justify-center py-16" />
        ) : data.items.length === 0 ? (
          <p className="py-16 text-center text-muted">No activity yet.</p>
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>Time</Th>
                <Th>Action</Th>
                <Th>Actor</Th>
                <Th>Details</Th>
              </tr>
            </THead>
            <TBody>
              {data.items.map((e) => {
                const action = ACTIONS[e.action] ?? { label: e.action, tone: "neutral" as const };
                return (
                  <Tr key={e.id}>
                    <Td className="whitespace-nowrap text-muted tabular-nums">{formatDate(e.ts)}</Td>
                    <Td>
                      <Badge tone={action.tone}>{action.label}</Badge>
                    </Td>
                    <Td className="text-muted">{e.actor}</Td>
                    <Td>
                      <details>
                        <summary className="cursor-pointer text-[13px] select-none hover:text-accent">{summary(e)}</summary>
                        <pre className="mt-2 max-h-72 overflow-auto rounded-lg bg-subtle p-3 font-mono text-xs">{JSON.stringify(e.payload, null, 2)}</pre>
                      </details>
                    </Td>
                  </Tr>
                );
              })}
            </TBody>
          </Table>
        )}
        <div className="flex items-center justify-between px-4 py-3 text-[13px] text-muted">
          <span>
            Page {page} of {pages}
          </span>
          <div className="flex gap-1">
            <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label="Previous page">
              <ChevronLeft className="size-4" />
            </Button>
            <Button size="sm" variant="ghost" disabled={page >= pages} onClick={() => setPage(page + 1)} aria-label="Next page">
              <ChevronRight className="size-4" />
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}
