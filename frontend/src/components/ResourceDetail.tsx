import { useEffect, useState, type ReactNode } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Spinner from "@cloudscape-design/components/spinner";
import Table from "@cloudscape-design/components/table";
import { api, type Meta, type ResourceDetail } from "../api";
import { accountName, formatDate, formatGiB, formatUsd } from "../format";
import StatusBadge, { OutcomeBadge } from "./StatusBadge";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <Box variant="awsui-key-label">{label}</Box>
      <div>{children}</div>
    </div>
  );
}

export default function ResourceDetailPanel({ id, meta, onClose }: { id: string; meta: Meta; onClose: () => void }) {
  const [detail, setDetail] = useState<ResourceDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDetail(null);
    setError(null);
    api.resource(id).then(setDetail).catch((e: Error) => setError(e.message));
  }, [id]);

  const r = detail?.resource;
  return (
    <Container header={<Header variant="h2" actions={<Button onClick={onClose}>Close details</Button>}>{r?.name || id}</Header>}>
      {error ? (
        <Alert type="error">{error}</Alert>
      ) : !detail || !r ? (
        <Spinner />
      ) : (
        <SpaceBetween size="l">
          <ColumnLayout columns={4} variant="text-grid">
            <Field label="ID">{r.id}</Field>
            <Field label="Status">
              <StatusBadge meta={meta} type={r.type} status={r.status} reason={r.status_reason} />
            </Field>
            <Field label="Account">{accountName(meta, r.account)}</Field>
            <Field label="Region">{r.region}</Field>
            <Field label="Created">{formatDate(r.created_at)}</Field>
            <Field label="Size">{formatGiB(r.size_gb)}</Field>
            <Field label="Est. cost">{formatUsd(r.est_monthly_cost)}</Field>
            <Field label="State">{r.state || "—"}</Field>
          </ColumnLayout>
          <Field label="Status reason">{r.status_reason}</Field>
          <Table
            header={<Header variant="h3">Rules</Header>}
            variant="embedded"
            items={detail.rules}
            columnDefinitions={[
              { id: "rule", header: "Rule", cell: (rule) => `${rule.id} · ${rule.title}` },
              { id: "outcome", header: "Outcome", cell: (rule) => <OutcomeBadge outcome={rule.outcome} /> },
              { id: "message", header: "Detail", cell: (rule) => rule.message || "Passed." },
            ]}
          />
          {detail.related.links.length > 0 && (
            <Table
              header={<Header variant="h3">Related</Header>}
              variant="embedded"
              items={detail.related.links}
              columnDefinitions={[
                { id: "relation", header: "Relation", cell: (l) => l.relation },
                { id: "name", header: "Name", cell: (l) => l.name || l.id },
                { id: "region", header: "Region", cell: (l) => l.region },
                { id: "status", header: "Status", cell: (l) => meta.definitions.statuses[l.status].label },
              ]}
            />
          )}
          {detail.related.shares.length > 0 && (
            <Field label="Launch permissions">
              {detail.related.shares
                .map((s) => (s.principal_type === "account" ? accountName(meta, s.principal) : `${s.principal_type}: ${s.principal}`))
                .join(", ")}
            </Field>
          )}
          {detail.related.usage.length > 0 && (
            <Field label="Used by">
              {detail.related.usage
                .map((u) => `${u.ref_type.replace("_", " ")} ${u.ref_name || u.ref_id} (${accountName(meta, u.account)})`)
                .join(", ")}
            </Field>
          )}
          <Field label="Tags">
            {Object.entries(r.tags).length
              ? Object.entries(r.tags).map(([k, v]) => `${k}=${v}`).join(", ")
              : "No tags."}
          </Field>
        </SpaceBetween>
      )}
    </Container>
  );
}
