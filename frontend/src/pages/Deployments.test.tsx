import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { api, type Deployment, type DeploymentsData, type Meta } from "../api";
import Deployments from "./Deployments";

vi.mock("../api", () => ({ api: { deployments: vi.fn() } }));

const meta = {
  provider: "mock",
  definitions: { statuses: { in_use: { label: "In use", meaning: "" } }, by_type: {} },
} as unknown as Meta;

function dep(over: Partial<Deployment>): Deployment {
  return {
    kind: "ec2",
    account: "222222222222",
    account_name: "dev",
    region: "us-east-1",
    env: "dev",
    app: "api",
    version: "3.1.0",
    state: "deployed",
    resource_id: over.name ?? "r",
    name: "r",
    created_at: "2026-09-01T00:00:00Z",
    desired: 2,
    running: 2,
    deployment_id: "",
    launch_template: "dev-api",
    launch_template_version: "7",
    ami_id: "ami-0001",
    ami: { id: "ami-0001", name: "base-linux", status: "in_use" },
    cluster: "",
    task_definition: "",
    image: "",
    ...over,
  };
}

function renderWith(data: DeploymentsData, url = "/deployments") {
  vi.mocked(api.deployments).mockResolvedValue(data);
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Deployments meta={meta} notify={() => {}} />
    </MemoryRouter>,
  );
}

describe("Deployments", () => {
  const items = [
    dep({ name: "dev-api-3.1.0-1", env: "dev", version: "3.1.0" }),
    dep({ name: "prd-api-3.0.5-2", env: "prd", account: "333333333333", account_name: "prd-us", version: "3.0.5" }),
    dep({ name: "prd-api-3.0.4-1", env: "prd", account: "333333333333", account_name: "prd-us", version: "3.0.4", state: "undeployed", desired: 0 }),
    dep({ kind: "ecs", name: "orders-api", app: "orders-api", env: "dev", version: "2.8.0", state: "failed", ami_id: null, ami: null }),
  ];

  it("shows each app's version per env and marks drift", async () => {
    renderWith({ scan_id: 1, items, failed: [] });
    expect(await screen.findByText("api")).toBeTruthy();
    expect(screen.getByText("2 versions")).toBeTruthy();
    expect(screen.getByText("3.0.5").className).toContain("amber"); // behind 3.1.0
    expect(screen.getByText("Failed")).toBeTruthy();
  });

  it("opens a drawer with what runs now and the earlier versions", async () => {
    renderWith({ scan_id: 1, items, failed: [] });
    fireEvent.click(await screen.findByText("3.0.5"));
    expect(await screen.findByText("Running now")).toBeTruthy();
    expect(screen.getByText("prd-api-3.0.5-2")).toBeTruthy();
    expect(screen.getByText("Earlier versions")).toBeTruthy();
    expect(screen.getByText("prd-api-3.0.4-1")).toBeTruthy();
    expect(screen.getAllByText("dev-api, version 7")).toHaveLength(2); // live and earlier
    expect(screen.getAllByText("prd")).toHaveLength(2); // the env tag, shown per deployment
  });

  it("filters by kind from the URL", async () => {
    renderWith({ scan_id: 1, items, failed: [] }, "/deployments?kind=ecs");
    expect(await screen.findByText("orders-api")).toBeTruthy();
    expect(screen.queryByText("api")).toBeNull();
  });

  it("names checks that failed", async () => {
    const failed = [
      { account: "333333333333", account_name: "prd", region: "us-east-1", kind: "ecs", error_kind: "denied", message: "Janitor isn't allowed to call ecs:ListClusters." },
    ];
    renderWith({ scan_id: 1, items, failed });
    expect(await screen.findByText("Some deployments may be missing")).toBeTruthy();
    expect(screen.getByText(/ecs:ListClusters/)).toBeTruthy();
  });
});
