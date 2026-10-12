import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { api, type Deployment, type DeploymentsData, type Meta } from "../api";
import Apps from "./Apps";

vi.mock("../api", () => ({ api: { deployments: vi.fn() } }));

const meta = { provider: "mock", definitions: { statuses: { in_use: { label: "In use", meaning: "" } }, by_type: {} } } as unknown as Meta;

function dep(over: Partial<Deployment>): Deployment {
  return {
    kind: "ec2", account: "222222222222", account_name: "dev", region: "us-east-1", env: "dev", app: "api", version: "3.1.0",
    state: "deployed", resource_id: over.name ?? "r", name: "r", created_at: "2026-09-01T00:00:00Z", desired: 2, running: 2,
    deployment_id: "", launch_template: "dev-api", launch_template_version: "7", ami_id: "ami-0001",
    ami: { id: "ami-0001", name: "base-linux", status: "in_use" }, cluster: "", task_definition: "", image: "", unit: "asg", tags: {},
    ...over,
  };
}

const items = [
  dep({ name: "dev-api-3.1.0-1", tags: { owner: "core", team: "platform" } }),
  dep({ name: "prd-api-3.0.5-2", account: "333333333333", account_name: "prd-us", region: "us-west-2", version: "3.0.5", tags: { owner: "core" } }),
  dep({ kind: "ecs", unit: "service", name: "orders-api", app: "orders-api", task_definition: "orders-api:4", image: "registry.example/orders-api:2.8.0", ami_id: null, ami: null, running: 3, desired: 3, tags: { owner: "commerce" } }),
];

function renderAt(url = "/apps", data: DeploymentsData = { scan_id: 1, items, failed: [] }) {
  vi.mocked(api.deployments).mockResolvedValue(data);
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Apps meta={meta} notify={() => {}} />
    </MemoryRouter>,
  );
}

describe("Apps", () => {
  it("lists every app with its color and running count", async () => {
    renderAt();
    const list = await screen.findByRole("list", { name: "Apps" });
    expect(within(list).getByText("api")).toBeTruthy();
    expect(within(list).getByText("orders-api")).toBeTruthy();
    expect(within(list).getByText("4 running · 2 places")).toBeTruthy();
  });

  it("opens an app with its resources and tags", async () => {
    renderAt();
    const list = await screen.findByRole("list", { name: "Apps" });
    fireEvent.click(within(list).getByRole("button", { name: /^api/ }));
    expect(await screen.findByText("dev-api-3.1.0-1")).toBeTruthy();
    expect(screen.getByText("prd-api-3.0.5-2")).toBeTruthy();
    const tags = screen.getByRole("table", { name: "Tags" });
    expect(within(tags).getByText("owner")).toBeTruthy();
    expect(within(tags).getByText("core")).toBeTruthy();
    expect(within(tags).getByText("× 2")).toBeTruthy();
    expect(screen.getAllByText("dev-api, version 7")).toHaveLength(2); // both groups use it
  });

  it("filters by env, region, and app name from the URL", async () => {
    renderAt("/apps?region=us-west-2");
    const list = await screen.findByRole("list", { name: "Apps" });
    expect(within(list).getByText("api")).toBeTruthy();
    expect(within(list).queryByText("orders-api")).toBeNull();
  });
});
