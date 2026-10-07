import Box from "@cloudscape-design/components/box";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Table from "@cloudscape-design/components/table";
import type { Status } from "../api";
import StatusBadge from "../components/StatusBadge";
import { TYPE_PAGES, type PageProps } from "../nav";

export default function HowItWorks({ meta }: PageProps) {
  const defs = meta.definitions;
  return (
    <ContentLayout header={<Header variant="h1" description="Policy and people decide; Janitor shows its reasoning.">How Janitor decides</Header>}>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2">Safety</Header>}>
          Janitor only reads. It has no way to delete or change anything: every delete is a simulation recorded
          in the audit log.
        </Container>
        <Table
          header={<Header variant="h2" description={`When more than one applies: ${defs.precedence.map((s) => defs.statuses[s].label).join(" > ")}.`}>Statuses</Header>}
          items={defs.precedence}
          columnDefinitions={[
            { id: "label", header: "Status", cell: (s: Status) => defs.statuses[s].label },
            { id: "meaning", header: "Meaning", cell: (s: Status) => defs.statuses[s].meaning },
            { id: "blocks", header: "Deletion", cell: (s: Status) => (defs.statuses[s].blocks ? "Blocked" : "Allowed if no rule blocks it") },
            { id: "todo", header: "What to do", cell: (s: Status) => defs.statuses[s].what_to_do },
          ]}
        />
        {TYPE_PAGES.map((page) => (
          <Container key={page.type} header={<Header variant="h2">{page.title}</Header>}>
            <SpaceBetween size="s">
              {(Object.entries(defs.by_type[page.type]) as [Status, string][]).map(([status, text]) => (
                <Box key={status}>
                  <StatusBadge meta={meta} type={page.type} status={status} /> {text}
                </Box>
              ))}
            </SpaceBetween>
          </Container>
        ))}
        <Table
          header={<Header variant="h2" description="The strictest outcome wins: block, then warn, then pass.">Rules</Header>}
          items={defs.rules}
          columnDefinitions={[
            { id: "id", header: "ID", cell: (r) => r.id },
            { id: "title", header: "Rule", cell: (r) => r.title },
            { id: "outcome", header: "Outcome", cell: (r) => (r.outcome === "block" ? "Block" : "Warn") },
            { id: "explanation", header: "Why", cell: (r) => r.explanation },
          ]}
        />
        <Container header={<Header variant="h2">Notes</Header>}>
          <ul>
            {defs.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
}
