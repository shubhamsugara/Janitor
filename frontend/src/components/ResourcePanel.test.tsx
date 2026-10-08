import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { api, type Meta, type ResourceDetail } from "../api";
import ResourcePanel from "./ResourcePanel";

vi.mock("../api", () => ({ api: { resource: vi.fn(), graph: vi.fn() } }));
vi.mock("./LinkageDiagram", () => ({ default: () => null }));

const meta = {
  accounts: [],
  owner: { account: "111111111111", regions: ["us-east-1"] },
  definitions: { statuses: { idle: { label: "Idle", meaning: "" }, orphaned: { label: "Orphaned", meaning: "" } }, by_type: {}, rules: [] },
} as unknown as Meta;

function detail(resource: Partial<ResourceDetail["resource"]>, links: ResourceDetail["related"]["links"] = []) {
  return {
    resource: { id: "x", type: "ami", account: "111111111111", region: "us-east-1", name: "x", created_at: "2026-01-01T00:00:00Z", tags: {}, status: "idle", status_reason: "", ...resource },
    rules: [],
    related: { links, shares: [], usage: [] },
  } as unknown as ResourceDetail;
}

function show(d: ResourceDetail) {
  vi.mocked(api.resource).mockResolvedValue(d);
  vi.mocked(api.graph).mockResolvedValue({ nodes: [], edges: [], used_by: { summary: "Nothing uses it." }, truncated: false } as never);
  render(
    <MemoryRouter>
      <ResourcePanel id="x" meta={meta} dark={false} onSelect={() => {}} />
    </MemoryRouter>,
  );
}

describe("ResourcePanel links to filtered lists", () => {
  it("links an AMI with copies to its copies", async () => {
    show(detail({ id: "ami-0000aaaa" }, [{ relation: "copy", id: "ami-0000bbbb", name: "x", region: "us-west-2", status: "idle" }]));
    const link = await screen.findByRole("link", { name: "See its copies" });
    expect(link.getAttribute("href")).toBe("/amis?source_ami=ami-0000aaaa");
  });

  it("doesn't offer copies for an AMI without any", async () => {
    show(detail({ id: "ami-0000aaaa" }));
    await screen.findByText("Nothing uses it.");
    expect(screen.queryByRole("link", { name: "See its copies" })).toBeNull();
  });

  it("links an RDS snapshot to every snapshot of its database", async () => {
    show(detail({ id: "arn:1", type: "rds_snapshot", source_db_id: "orders-db" }));
    const link = await screen.findByRole("link", { name: "See all snapshots of this database" });
    expect(link.getAttribute("href")).toBe("/rds-snapshots?source_db=orders-db");
  });
});
