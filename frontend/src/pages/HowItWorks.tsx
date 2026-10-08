import { Rocket, ShieldCheck } from "lucide-react";
import type { Status } from "../api";
import StatusBadge from "../components/StatusBadge";
import { TYPE_PAGES, type PageProps } from "../nav";
import { Badge } from "../ui/badge";
import { Card, CardBody, CardHeader } from "../ui/card";
import { Table, TBody, Td, Th, THead, Tr } from "../ui/table";

/** Server text marks tag names with backticks; show them as code. */
function WithCode({ text }: { text: string }) {
  return (
    <>
      {text.split("`").map((part, i) =>
        i % 2 ? (
          <code key={i} className="rounded bg-subtle px-1 py-0.5 font-mono text-xs text-ink">
            {part}
          </code>
        ) : (
          part
        ),
      )}
    </>
  );
}

export default function HowItWorks({ meta }: PageProps) {
  const defs = meta.definitions;
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">How Janitor decides</h2>
        <p className="mt-1 text-[13px] text-muted">Policy and people decide; Janitor shows its reasoning.</p>
      </div>
      <Card className="flex items-start gap-4 p-5">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
          <ShieldCheck className="size-5" aria-hidden />
        </span>
        <div>
          <h3 className="font-semibold">Read-only by design</h3>
          <p className="mt-1 text-[13px] text-muted">
            Janitor only reads. It has no way to delete or change anything: every delete is a simulation recorded in the audit log.
          </p>
        </div>
      </Card>
      <Card>
        <CardHeader title="Statuses" description={`When more than one applies: ${defs.precedence.map((s) => defs.statuses[s].label).join(" > ")}.`} />
        <CardBody className="pt-3">
          <Table>
            <THead>
              <tr>
                <Th>Status</Th>
                <Th>Meaning</Th>
                <Th>Deletion</Th>
                <Th>What to do</Th>
              </tr>
            </THead>
            <TBody>
              {defs.precedence.map((s: Status) => (
                <Tr key={s}>
                  <Td>
                    <StatusBadge meta={meta} type="ami" status={s} />
                  </Td>
                  <Td>{defs.statuses[s].meaning}</Td>
                  <Td className="text-muted">{defs.statuses[s].blocks ? "Blocked" : "Allowed if no rule blocks it"}</Td>
                  <Td className="text-muted">{defs.statuses[s].what_to_do}</Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        </CardBody>
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        {TYPE_PAGES.map((page) => (
          <Card key={page.type}>
            <CardHeader title={page.title} />
            <CardBody className="space-y-3 pt-3">
              {(Object.entries(defs.by_type[page.type]) as [Status, string][]).map(([status, text]) => (
                <div key={status} className="flex items-start gap-3 text-[13px]">
                  <StatusBadge meta={meta} type={page.type} status={status} />
                  <span className="pt-0.5">{text}</span>
                </div>
              ))}
            </CardBody>
          </Card>
        ))}
      </div>
      <Card>
        <CardHeader title="Rules" description="The strictest outcome wins: block, then warn, then pass." />
        <CardBody className="pt-3">
          <Table>
            <THead>
              <tr>
                <Th>ID</Th>
                <Th>Rule</Th>
                <Th>Outcome</Th>
                <Th>Why</Th>
              </tr>
            </THead>
            <TBody>
              {defs.rules.map((r) => (
                <Tr key={r.id}>
                  <Td className="font-mono text-xs">{r.id}</Td>
                  <Td className="font-medium">{r.title}</Td>
                  <Td>
                    <Badge tone={r.outcome === "block" ? "danger" : "warning"}>{r.outcome === "block" ? "Block" : "Warn"}</Badge>
                  </Td>
                  <Td className="text-muted">{r.explanation}</Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        </CardBody>
      </Card>
      {defs.deployments && (
        <Card>
          <CardHeader
            title={
              <span className="inline-flex items-center gap-2">
                <Rocket className="size-4 text-accent" aria-hidden />
                Deployments
              </span>
            }
            description={defs.deployments.summary}
          />
          <CardBody className="space-y-5 pt-3">
            <div className="grid gap-4 lg:grid-cols-3">
              {defs.deployments.sources.map((s) => (
                <div key={s.title} className="rounded-lg border border-line p-4">
                  <h3 className="text-[13px] font-semibold">{s.title}</h3>
                  <p className="mt-1 text-[13px] text-muted">
                    <WithCode text={s.text} />
                  </p>
                </div>
              ))}
            </div>
            <div>
              <h3 className="text-[13px] font-semibold">Run status, beside the deploy state</h3>
              <dl className="mt-2 grid gap-x-6 gap-y-1.5 text-[13px] sm:grid-cols-[max-content_1fr]">
                {defs.deployments.run.map((r) => (
                  <div key={r.label} className="contents">
                    <dt className="font-medium">{r.label}</dt>
                    <dd className="text-muted">{r.meaning}</dd>
                  </div>
                ))}
              </dl>
            </div>
            <ul className="list-disc space-y-1.5 pl-5 text-[13px] text-muted">
              {defs.deployments.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </CardBody>
        </Card>
      )}
      <Card>
        <CardHeader title="Notes" />
        <CardBody className="pt-3">
          <ul className="list-disc space-y-1.5 pl-5 text-[13px] text-muted">
            {defs.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </CardBody>
      </Card>
    </div>
  );
}
