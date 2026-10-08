import { describe, expect, it } from "vitest";
import type { Deployment } from "./api";
import { cellLabel, columnsOf, compareVersions, filterItems, rowsOf } from "./deployments";

function dep(over: Partial<Deployment>): Deployment {
  return {
    kind: "ec2",
    account: "222222222222",
    account_name: "dev",
    region: "us-east-1",
    env: "dev",
    app: "api",
    version: "1.0.0",
    state: "deployed",
    resource_id: "r",
    name: "r",
    created_at: "2026-09-01T00:00:00Z",
    desired: 2,
    running: 2,
    deployment_id: "",
    launch_template: "",
    launch_template_version: "",
    ami_id: null,
    ami: null,
    cluster: "",
    task_definition: "",
    image: "",
    ...over,
  };
}

describe("compareVersions", () => {
  it("compares dotted parts as numbers", () => {
    expect(compareVersions("3.10.0", "3.9.1")).toBeGreaterThan(0);
    expect(compareVersions("2.4.0", "2.4.1")).toBeLessThan(0);
    expect(compareVersions("1.2", "1.2.0")).toBeLessThan(0);
    expect(compareVersions("13.0.0.28", "13.0.0.28")).toBe(0);
  });

  it("falls back to text for parts that aren't numbers", () => {
    expect(compareVersions("1.0.0-rc2", "1.0.0-rc1")).toBeGreaterThan(0);
    expect(compareVersions("", "1.0")).toBeLessThan(0);
  });
});

describe("columnsOf", () => {
  it("orders envs from sandbox to production, then by name and region", () => {
    const items = [
      dep({ env: "prd", region: "us-west-2" }),
      dep({ env: "prd", region: "us-east-1" }),
      dep({ env: "uat" }),
      dep({ env: "billing-lab" }),
      dep({ env: "dev" }),
      dep({ env: "sbx" }),
      dep({ env: "qas" }),
    ];
    expect(columnsOf(items).map((c) => `${c.env} ${c.region}`)).toEqual([
      "sbx us-east-1",
      "dev us-east-1",
      "qas us-east-1",
      "uat us-east-1",
      "prd us-east-1",
      "prd us-west-2",
      "billing-lab us-east-1",
    ]);
  });
});

describe("rowsOf", () => {
  const items = [
    dep({ app: "api", env: "dev", version: "3.1.0", state: "undeploying", created_at: "2026-09-01T00:00:00Z" }),
    dep({ app: "api", env: "dev", version: "3.2.0", state: "deploying", created_at: "2026-09-30T00:00:00Z" }),
    dep({ app: "api", env: "prd", version: "3.0.5", state: "deployed" }),
    dep({ app: "api", env: "prd", version: "3.0.4", state: "undeployed", created_at: "2026-08-01T00:00:00Z" }),
    dep({ app: "web", env: "uat", version: "2.4.1" }),
    dep({ app: "web", env: "prd", version: "2.4.1", state: "undeployed" }),
  ];

  it("groups by app, newest live first, with undeployed rows as history", () => {
    const [api, web] = rowsOf(items);
    expect(api.app).toBe("api");
    const dev = api.cells["dev|us-east-1"];
    expect(dev.live.map((d) => d.version)).toEqual(["3.2.0", "3.1.0"]);
    expect(cellLabel(dev)).toBe("3.1.0 → 3.2.0");
    const prd = api.cells["prd|us-east-1"];
    expect(prd.live.map((d) => d.version)).toEqual(["3.0.5"]);
    expect(prd.history.map((d) => d.version)).toEqual(["3.0.4"]);
    expect(cellLabel(prd)).toBe("3.0.5");
    expect(web.cells["prd|us-east-1"].live).toEqual([]);
    expect(cellLabel(web.cells["prd|us-east-1"])).toBe("Not running");
  });

  it("marks drift: the newest live version, and cells behind it", () => {
    const [api, web] = rowsOf(items);
    expect(api.versions).toEqual(["3.2.0", "3.0.5"]);
    expect(api.latest).toBe("3.2.0");
    expect(web.versions).toEqual(["2.4.1"]); // an undeployed group isn't running
  });
});

describe("filterItems", () => {
  const items = [
    dep({ app: "api", kind: "ec2", env: "dev" }),
    dep({ app: "orders-api", kind: "ecs", env: "prd" }),
    dep({ app: "reports", kind: "ecs", env: "dev" }),
  ];

  it("filters by kind, env, and app text", () => {
    expect(filterItems(items, { kind: "ecs", envs: [], q: "" }).map((d) => d.app)).toEqual(["orders-api", "reports"]);
    expect(filterItems(items, { kind: "", envs: ["dev"], q: "" }).map((d) => d.app)).toEqual(["api", "reports"]);
    expect(filterItems(items, { kind: "", envs: [], q: "API" }).map((d) => d.app)).toEqual(["api", "orders-api"]);
  });
});
