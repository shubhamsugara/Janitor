import type { ReactNode } from "react";
import { Link } from "react-router";
import type { Deployment, DeploymentState, Meta } from "../api";
import { runStatus, type Cell, type RunKey } from "../deployments";
import { formatDate } from "../format";
import { Badge } from "../ui/badge";
import { Card } from "../ui/card";
import StatusBadge from "./StatusBadge";

export const STATES: Record<DeploymentState, { label: string; tone: "neutral" | "accent" | "success" | "warning" | "danger" }> = {
  deployed: { label: "Deployed", tone: "success" },
  deploying: { label: "Deploying", tone: "accent" },
  undeploying: { label: "Draining", tone: "warning" },
  undeployed: { label: "Undeployed", tone: "neutral" },
  failed: { label: "Failed", tone: "danger" },
};

export const RUN_TONES: Record<RunKey, "neutral" | "success" | "warning" | "danger"> = {
  running: "success",
  partial: "warning",
  stopped: "neutral",
  stopping: "warning",
  down: "danger",
};

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[10rem_1fr] gap-3 py-1.5 text-[13px]">
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

function Ami({ d, meta }: { d: Deployment; meta: Meta }) {
  if (!d.ami_id) return <span className="text-muted">Not known: the launch template doesn't name an AMI ID.</span>;
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <Link to={`/amis?q=${encodeURIComponent(d.ami_id)}`} className="font-mono text-xs text-accent hover:underline">
        {d.ami_id}
      </Link>
      {d.ami ? (
        <>
          <span className="text-muted">{d.ami.name}</span>
          <StatusBadge meta={meta} type="ami" status={d.ami.status} />
        </>
      ) : (
        <span className="text-muted">Not in this scan (owned by another account)</span>
      )}
    </span>
  );
}

function Details({ d, meta }: { d: Deployment; meta: Meta }) {
  const state = STATES[d.state];
  const run = runStatus(d);
  return (
    <Card className="px-5 py-3">
      <div className="flex items-center justify-between gap-3 border-b border-line pb-2">
        <div className="font-mono text-[13px] font-medium">{d.version || "No version tag"}</div>
        <span className="flex gap-1.5">
          <Badge tone={state.tone}>{state.label}</Badge>
          <Badge tone={RUN_TONES[run.key]}>{run.label}</Badge>
        </span>
      </div>
      <dl className="pt-1">
        {d.kind === "ec2" ? (
          <>
            <Field label="Auto Scaling group">{d.name}</Field>
            {d.deployment_id && <Field label="Deployment ID">{d.deployment_id}</Field>}
            <Field label="Instances">
              {d.running} running of {d.desired} desired
            </Field>
            <Field label="Launch template">
              {d.launch_template ? `${d.launch_template}, version ${d.launch_template_version || "unknown"}` : "None (launch configuration)"}
            </Field>
            <Field label="AMI">
              <Ami d={d} meta={meta} />
            </Field>
          </>
        ) : (
          <>
            <Field label="Cluster">{d.cluster}</Field>
            <Field label="Service">{d.name}</Field>
            <Field label="Tasks">
              {d.running} running of {d.desired} desired
            </Field>
            <Field label="Task definition">{d.task_definition}</Field>
            <Field label="Image">
              <span className="font-mono text-xs">{d.image || "Unknown"}</span>
            </Field>
          </>
        )}
        <Field label="Env">{d.env}</Field>
        <Field label="Account">
          {d.account_name} · {d.region}
        </Field>
        <Field label="Created">{formatDate(d.created_at)}</Field>
      </dl>
    </Card>
  );
}

/** One app in one env: what runs now, then the versions before it. */
export default function DeploymentPanel({ cell, meta }: { cell: Cell; meta: Meta }) {
  return (
    <div className="space-y-6">
      <section className="space-y-3">
        <h3 className="text-[15px] font-semibold tracking-tight">{cell.live.length > 1 ? "Running now (switch in progress)" : "Running now"}</h3>
        {cell.live.length === 0 ? (
          <p className="text-[13px] text-muted">Nothing runs here now. The last version is listed below.</p>
        ) : (
          cell.live.map((d) => <Details key={d.resource_id} d={d} meta={meta} />)
        )}
      </section>
      {cell.history.length > 0 && (
        <section className="space-y-3">
          <h3 className="text-[15px] font-semibold tracking-tight">Earlier versions</h3>
          <p className="text-[13px] text-muted">Scaled to zero and kept until someone removes them.</p>
          {cell.history.map((d) => (
            <Details key={d.resource_id} d={d} meta={meta} />
          ))}
        </section>
      )}
    </div>
  );
}
