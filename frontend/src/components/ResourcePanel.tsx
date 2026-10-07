import { useEffect, useState, type ReactNode } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Spinner from "@cloudscape-design/components/spinner";
import Table from "@cloudscape-design/components/table";
import Tabs from "@cloudscape-design/components/tabs";
import { api, type Graph, type Meta, type ResourceDetail } from "../api";
import { accountName, formatDate, formatGiB, formatUsd } from "../format";
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
    <div>
      <Box variant="awsui-key-label">{label}</Box>
      <div>{children}</div>
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

  if (error) return <Alert type="error">{error}</Alert>;
  if (!detail || !graph) return <Spinner size="large" />;
  const r = detail.resource;
  const tags = Object.entries(r.tags);

  return (
    <SpaceBetween size="m">
      <SpaceBetween size="xs" direction="horizontal" alignItems="center">
        <Box variant="h3">{r.name || r.id}</Box>
        <StatusBadge meta={meta} type={r.type} status={r.status} reason={r.status_reason} />
      </SpaceBetween>
      <Alert type={graph.used_by.active ? "success" : "info"} header="Used by">
        {graph.used_by.summary}
      </Alert>
      <Tabs
        activeTabId={tab}
        onChange={({ detail: change }) => setTab(change.activeTabId)}
        tabs={[
          {
            id: "diagram",
            label: "Diagram",
            content: (
              <SpaceBetween size="s">
                <LinkageDiagram graph={graph} meta={meta} dark={dark} onSelect={onSelect} />
                <div className="janitor-legend">
                  {LEGEND.map(([label, color, style]) => (
                    <span key={label} className={style} style={{ ["--legend-color" as string]: color }}>
                      {label}
                    </span>
                  ))}
                </div>
                <Box color="text-body-secondary" fontSize="body-s">
                  Click a resource to center the diagram on it. Scroll to zoom, drag to pan.
                  {graph.truncated && " Some links are collapsed into \"+N more\" nodes."}
                </Box>
              </SpaceBetween>
            ),
          },
          {
            id: "details",
            label: "Details",
            content: (
              <SpaceBetween size="l">
                <ColumnLayout columns={4} variant="text-grid">
                  <Field label="ID">{r.id}</Field>
                  <Field label="Account">{accountName(meta, r.account)}</Field>
                  <Field label="Region">{r.region}</Field>
                  <Field label="Created">{formatDate(r.created_at)}</Field>
                  <Field label="Size">{formatGiB(r.size_gb)}</Field>
                  <Field label="Est. cost">{formatUsd(r.est_monthly_cost)}</Field>
                  <Field label="State">{r.state || "—"}</Field>
                  {r.type === "volume" && <Field label="Type">{r.volume_type ?? "—"}</Field>}
                  {r.type === "volume" && <Field label="IOPS · throughput">{`${r.iops ?? "—"} · ${r.throughput ?? "—"} MiB/s`}</Field>}
                  {r.type === "volume" && <Field label="Encrypted">{r.encrypted == null ? "—" : r.encrypted ? "Yes" : "No"}</Field>}
                  {r.type === "snapshot" && <Field label="Storage tier">{r.storage_tier ?? "standard"}</Field>}
                </ColumnLayout>
                <Field label="Status reason">{r.status_reason}</Field>
              </SpaceBetween>
            ),
          },
          { id: "cost", label: "Cost", content: <CostBreakdown breakdown={r.cost_breakdown} /> },
          {
            id: "rules",
            label: "Rules",
            content: (
              <Table
                variant="embedded"
                items={detail.rules}
                columnDefinitions={[
                  { id: "rule", header: "Rule", cell: (rule) => `${rule.id} · ${rule.title}` },
                  { id: "outcome", header: "Outcome", cell: (rule) => <OutcomeBadge outcome={rule.outcome} /> },
                  { id: "message", header: "Detail", cell: (rule) => rule.message || "Passed." },
                ]}
              />
            ),
          },
          {
            id: "tags",
            label: `Tags (${tags.length})`,
            content: tags.length ? (
              <Table
                variant="embedded"
                items={tags}
                columnDefinitions={[
                  { id: "key", header: "Key", cell: ([key]) => key },
                  { id: "value", header: "Value", cell: ([, value]) => value },
                ]}
              />
            ) : (
              <Box>No tags.</Box>
            ),
          },
        ]}
      />
    </SpaceBetween>
  );
}
