import { Link } from "react-router";
import type { Deployment, Meta } from "../api";
import type { AppDetail } from "../apps";
import { runStatus } from "../deployments";
import { Badge } from "../ui/badge";
import { Card, CardBody, CardHeader } from "../ui/card";
import { Table, TBody, Td, Th, THead, Tr } from "../ui/table";
import { RUN_TONES, STATES } from "./DeploymentPanel";
import StatusBadge from "./StatusBadge";

const UNITS: Record<Deployment["unit"], string> = { asg: "Auto Scaling group", instance: "Standalone instance", service: "ECS service" };

/** What the resource runs: launch template and AMI for EC2, task definition and image for ECS. */
function Runs({ d, meta }: { d: Deployment; meta: Meta }) {
  if (d.kind === "ecs")
    return (
      <div className="space-y-0.5">
        <div>{d.task_definition}</div>
        <div className="font-mono text-xs text-muted break-all">{d.image}</div>
      </div>
    );
  return (
    <div className="space-y-1">
      {d.launch_template && (
        <div>
          {d.launch_template}, version {d.launch_template_version || "unknown"}
        </div>
      )}
      {d.ami_id ? (
        <div className="flex flex-wrap items-center gap-1.5">
          <Link to={`/amis?q=${encodeURIComponent(d.ami_id)}`} className="font-mono text-xs text-accent hover:underline">
            {d.ami_id}
          </Link>
          {d.ami && <StatusBadge meta={meta} type="ami" status={d.ami.status} />}
        </div>
      ) : (
        <div className="text-muted">No AMI ID</div>
      )}
    </div>
  );
}

/** One app: every resource it runs on, and every tag those resources carry. */
export default function AppPanel({ detail, meta }: { detail: AppDetail; meta: Meta }) {
  return (
    <div className="space-y-6">
      <p className="text-[13px] text-muted">
        {detail.resources.length} resources in {detail.places} account and region pairs, {detail.running} instances or tasks running.
      </p>
      <Card>
        <CardHeader title="Resources" description="Auto Scaling groups, standalone instances, and ECS services this app runs on." />
        <CardBody className="pt-3">
          <Table aria-label="Resources">
            <THead>
              <tr>
                <Th>Resource</Th>
                <Th>Where</Th>
                <Th>Version</Th>
                <Th>Status</Th>
                <Th>Runs</Th>
              </tr>
            </THead>
            <TBody>
              {detail.resources.map((d) => {
                const run = runStatus(d);
                return (
                  <Tr key={`${d.account}|${d.resource_id}`}>
                    <Td className="align-top">
                      <div className="font-medium break-all">{d.name}</div>
                      <div className="text-xs text-muted">{UNITS[d.unit] ?? d.unit}</div>
                    </Td>
                    <Td className="align-top whitespace-nowrap">
                      {d.account_name}
                      <div className="text-xs text-muted">{d.region}</div>
                    </Td>
                    <Td className="align-top font-mono text-xs">{d.version || "—"}</Td>
                    <Td className="align-top">
                      <div className="flex flex-col items-start gap-1">
                        {d.unit !== "instance" && <Badge tone={STATES[d.state].tone}>{STATES[d.state].label}</Badge>}
                        <Badge tone={RUN_TONES[run.key]}>{run.label}</Badge>
                      </div>
                    </Td>
                    <Td className="align-top text-[13px]">
                      <Runs d={d} meta={meta} />
                    </Td>
                  </Tr>
                );
              })}
            </TBody>
          </Table>
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Tags" description="Every tag on these resources, with how many carry each value." />
        <CardBody className="pt-3">
          {detail.tags.length === 0 ? (
            <p className="text-[13px] text-muted">These resources have no tags.</p>
          ) : (
            <Table aria-label="Tags">
              <THead>
                <tr>
                  <Th className="w-48">Key</Th>
                  <Th>Values</Th>
                </tr>
              </THead>
              <TBody>
                {detail.tags.map((t) => (
                  <Tr key={t.key}>
                    <Td className="align-top font-mono text-xs break-all">{t.key}</Td>
                    <Td>
                      <div className="flex flex-wrap gap-1.5">
                        {t.values.map((v) => (
                          <span key={v.value} className="inline-flex items-center gap-1 rounded-md bg-subtle px-2 py-0.5 font-mono text-xs">
                            <span className="break-all">{v.value}</span>
                            {v.count > 1 && <span className="text-muted">× {v.count}</span>}
                          </span>
                        ))}
                      </div>
                    </Td>
                  </Tr>
                ))}
              </TBody>
            </Table>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
