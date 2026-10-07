import { useEffect, useState, type ReactNode } from "react";
import { CircleCheck, Info } from "lucide-react";
import { api, type Graph, type Meta, type ResourceDetail } from "../api";
import { accountName, formatDate, formatGiB, formatUsd } from "../format";
import { Spinner } from "../ui/spinner";
import { Table, TBody, Td, Th, THead, Tr } from "../ui/table";
import { Tabs } from "../ui/tabs";
import AwsIcon from "./AwsIcon";
import CostBreakdown from "./CostBreakdown";
import LinkageDiagram from "./LinkageDiagram";
import StatusBadge, { OutcomeBadge } from "./StatusBadge";

const LEGEND: [string, string, string][] = [
  ["used by", "#00802f", ""],
  ["backs · snapshot", "#7aa116", ""],
  ["copy in another region", "#ed7100", "dashed"],
  ["shared with", "#e7157b", "dotted"],
];

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-1 truncate text-[13px] font-medium" title={typeof children === "string" ? children : undefined}>
        {children}
      </dd>
    </div>
  );
}

interface Props {
  id: string;
  meta: Meta;
  dark: boolean;
  onSelect: (id: string) => void;
}

export default function ResourcePanel({ id, meta, dark, onSelect }: Props) {
  const [detail, setDetail] = useState<ResourceDetail | null>(null);
  const [graph, setGraph] = useState<Graph | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState("diagram");

  useEffect(() => {
    let current = true; // a newer selection makes this one's responses stale
    setDetail(null);
    setGraph(null);
    setError(null);
    Promise.all([api.resource(id), api.graph(id)])
      .then(([d, g]) => {
        if (current) {
          setDetail(d);
          setGraph(g);
        }
      })
      .catch((e: Error) => {
        if (current) setError(e.message);
      });
    return () => {
      current = false;
    };
  }, [id]);

  if (error) return <p className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-[13px]">{error}</p>;
  if (!detail || !graph) return <Spinner label="Loading details" className="justify-center py-24" />;
  const r = detail.resource;
  const tags = Object.entries(r.tags);
  const active = (graph.used_by.active ?? 0) > 0;

  return (
    <div className="space-y-5">
      <div className="flex items-start gap-4">
        <AwsIcon kind={r.type} size={44} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="truncate text-xl font-semibold tracking-tight" title={r.name || r.id}>
              {r.name || r.id}
            </h2>
            <StatusBadge meta={meta} type={r.type} status={r.status} reason={r.status_reason} />
          </div>
          <p className="mt-1 truncate font-mono text-xs text-muted" title={r.id}>
            {r.id}
          </p>
        </div>
      </div>

      <div
        className={
          active
            ? "flex gap-3 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3"
            : "flex gap-3 rounded-xl border border-accent/25 bg-accent-soft px-4 py-3"
        }
      >
        {active ? <CircleCheck className="mt-0.5 size-4 shrink-0 text-emerald-600 dark:text-emerald-400" aria-hidden /> : <Info className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />}
        <div className="text-[13px]">
          <div className="font-semibold">Used by</div>
          <p className="mt-0.5">{graph.used_by.summary}</p>
        </div>
      </div>

      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          {
            id: "diagram",
            label: "Diagram",
            content: (
              <div className="space-y-3">
                <LinkageDiagram graph={graph} meta={meta} dark={dark} onSelect={onSelect} />
                <div className="janitor-legend">
                  {LEGEND.map(([label, color, style]) => (
                    <span key={label} className={style} style={{ ["--legend-color" as string]: color }}>
                      {label}
                    </span>
                  ))}
                </div>
                <p className="text-xs text-muted">
                  Click a resource to center the diagram on it. Scroll to zoom, drag to pan.
                  {graph.truncated && " Some links are collapsed into \"+N more\" nodes."}
                </p>
              </div>
            ),
          },
          {
            id: "details",
            label: "Details",
            content: (
              <div className="space-y-5 rounded-xl border border-line bg-card p-5">
                <dl className="grid grid-cols-2 gap-x-6 gap-y-4 md:grid-cols-4">
                  <Field label="Account">{accountName(meta, r.account)}</Field>
                  <Field label="Region">{r.region}</Field>
                  <Field label="Created">{formatDate(r.created_at)}</Field>
                  <Field label="State">{r.state || "—"}</Field>
                  <Field label="Size">{formatGiB(r.size_gb)}</Field>
                  <Field label="Est. cost">{formatUsd(r.est_monthly_cost)}</Field>
                  {r.type === "volume" && <Field label="Type">{r.volume_type ?? "—"}</Field>}
                  {r.type === "volume" && <Field label="IOPS · throughput">{`${r.iops ?? "—"} · ${r.throughput ?? "—"} MiB/s`}</Field>}
                  {r.type === "volume" && <Field label="Encrypted">{r.encrypted == null ? "—" : r.encrypted ? "Yes" : "No"}</Field>}
                  {r.type === "snapshot" && <Field label="Storage tier">{r.storage_tier ?? "standard"}</Field>}
                </dl>
                <div className="border-t border-line pt-4">
                  <div className="text-xs text-muted">Status reason</div>
                  <p className="mt-1 text-[13px]">{r.status_reason}</p>
                </div>
              </div>
            ),
          },
          { id: "cost", label: "Cost", content: <CostBreakdown breakdown={r.cost_breakdown} /> },
          {
            id: "rules",
            label: "Rules",
            content: (
              <div className="overflow-hidden rounded-xl border border-line bg-card">
                <Table>
                  <THead>
                    <tr>
                      <Th>Rule</Th>
                      <Th>Outcome</Th>
                      <Th>Detail</Th>
                    </tr>
                  </THead>
                  <TBody>
                    {detail.rules.map((rule) => (
                      <Tr key={rule.id}>
                        <Td className="font-medium whitespace-nowrap">{`${rule.id} · ${rule.title}`}</Td>
                        <Td>
                          <OutcomeBadge outcome={rule.outcome} />
                        </Td>
                        <Td className="text-muted">{rule.message || "Passed."}</Td>
                      </Tr>
                    ))}
                  </TBody>
                </Table>
              </div>
            ),
          },
          {
            id: "tags",
            label: `Tags (${tags.length})`,
            content: tags.length ? (
              <div className="flex flex-wrap gap-2">
                {tags.map(([key, value]) => (
                  <span key={key} className="inline-flex overflow-hidden rounded-lg border border-line bg-card text-[13px]">
                    <span className="bg-subtle px-2.5 py-1 text-muted">{key}</span>
                    <span className="px-2.5 py-1 font-medium">{value}</span>
                  </span>
                ))}
              </div>
            ) : (
              <p className="text-muted">No tags.</p>
            ),
          },
        ]}
      />
    </div>
  );
}
