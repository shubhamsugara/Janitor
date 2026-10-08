import { CircleAlert, TriangleAlert } from "lucide-react";
import type { FailedCheck, Meta, OverviewData } from "../api";
import { formatDate } from "../format";
import { Card, CardBody, CardHeader } from "../ui/card";

const KIND_LABELS: Record<string, string> = {
  ami: "AMIs",
  snapshot: "EBS snapshots",
  volume: "EBS volumes",
  rds_snapshot: "RDS snapshots",
  database: "databases",
  usage: "what uses AMIs",
};

/** One line per account and message, so an expired session for one account reads once. */
export function groupChecks(checks: FailedCheck[]): { key: string; label: string; message: string; count: number }[] {
  const groups = new Map<string, FailedCheck[]>();
  for (const check of checks) {
    const key = `${check.account}\u0000${check.message}`;
    groups.set(key, [...(groups.get(key) ?? []), check]);
  }
  return [...groups.entries()].map(([key, group]) => {
    const [first] = group;
    const label =
      group.length > 1 ? first.account_name : `${first.account_name} · ${first.region} · ${KIND_LABELS[first.kind] ?? first.kind}`;
    return { key, label, message: first.message, count: group.length };
  });
}

/** Failed checks, a failed newest scan, and image references Janitor can't read. */
export default function ScanHealth({ data, meta }: { data: OverviewData; meta: Meta }) {
  const failed = data.segments_failed ?? [];
  const unresolved = data.unresolved ?? [];
  const names = Object.fromEntries((meta.accounts ?? []).map((a) => [a.id, a.name]));
  if (!failed.length && !unresolved.length && !data.newest_failed) return null;

  return (
    <div className="space-y-4">
      {data.newest_failed && (
        <div role="alert" className="flex items-start gap-3 rounded-xl border border-red-500/30 bg-red-500/5 px-4 py-3 text-[13px]">
          <CircleAlert className="mt-0.5 size-4 shrink-0 text-red-600 dark:text-red-400" aria-hidden />
          <p>
            The last scan failed: {data.newest_failed.message}
            {data.last_scan?.finished_at && ` Showing data from ${formatDate(data.last_scan.finished_at)}.`}
          </p>
        </div>
      )}
      {failed.length > 0 && (
        <Card className="border-amber-500/30">
          <CardHeader
            title={
              <span className="inline-flex items-center gap-2">
                <TriangleAlert className="size-4 text-amber-600 dark:text-amber-400" aria-hidden />
                Some checks failed
              </span>
            }
            description="Resources that depend on a failed check show as Unknown and can't be deleted."
          />
          <CardBody className="pt-3">
            <ul className="space-y-1.5 text-[13px]">
              {groupChecks(failed).map((line) => (
                <li key={line.key}>
                  <span className="font-medium">{line.label}</span>
                  {line.count > 1 && <span className="text-muted"> ({line.count} checks)</span>}: {line.message}
                </li>
              ))}
            </ul>
          </CardBody>
        </Card>
      )}
      {unresolved.length > 0 && (
        <Card>
          <CardHeader
            title="Image references Janitor can't read"
            description={`${unresolved.length} launch ${unresolved.length === 1 ? "template picks its" : "templates pick their"} image through an SSM parameter. Janitor can't read those, so check them before deleting AMIs.`}
          />
          <CardBody className="pt-3">
            <ul className="space-y-1 font-mono text-xs text-muted">
              {unresolved.map((u) => (
                <li key={`${u.account}-${u.region}-${u.ref_type}-${u.ref_id}`} className="truncate" title={u.value}>
                  {names[u.account] ?? u.account} · {u.region} · {u.ref_id}: {u.value}
                </li>
              ))}
            </ul>
          </CardBody>
        </Card>
      )}
    </div>
  );
}
