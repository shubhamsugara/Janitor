import { describe, expect, it } from "vitest";
import type { Deployment } from "./api";
import { cellLabel, columnsOf, compareVersions, filterItems, rowsOf, runStatus } from "./deployments";

const DEV = "222222222222";
const PRD = "333333333333";
const UAT = "666666666666";

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
  it("is one column per account and region, from sandbox to production", () => {
    const items = [
      dep({ account: "333333333333", account_name: "prd-us", env: "prd", region: "us-west-2" }),
      dep({ account: "333333333333", account_name: "prd-us", env: "prd", region: "us-east-1" }),
      dep({ account: "888888888888", account_name: "prd-eu", env: "prd", region: "eu-west-1" }),
      dep({ account: "666666666666", account_name: "uat", env: "uat" }),
      dep({ account: "111111111111", account_name: "admin", env: "admin" }),
      dep({ account: "222222222222", account_name: "dev", env: "dev" }),
      dep({ account: "555555555555", account_name: "sbx", env: "sbx" }),
      dep({ account: "777777777777", account_name: "qas", env: "qas" }),
    ];
    expect(columnsOf(items).map((c) => `${c.name} ${c.region}`)).toEqual([
      "sbx us-east-1",
      "dev us-east-1",
      "qas us-east-1",
      "uat us-east-1",
      "prd-eu eu-west-1",
      "prd-us us-east-1",
      "prd-us us-west-2",
      "admin us-east-1",
    ]);
  });

  it("keeps an ASG tagged env=prd and an untagged ECS service in the same account together", () => {
    const items = [
      dep({ kind: "ec2", account: "333333333333", account_name: "prd-us", env: "prd", app: "web" }),
      dep({ kind: "ecs", account: "333333333333", account_name: "prd-us", env: "prd-us", app: "orders" }),
    ];
    expect(columnsOf(items)).toHaveLength(1);
    const [orders, web] = rowsOf(items);
    expect(Object.keys(orders.cells)).toEqual(Object.keys(web.cells));
  });
});

describe("rowsOf", () => {
  const items = [
    dep({ app: "api", version: "3.1.0", state: "undeploying", created_at: "2026-09-01T00:00:00Z" }),
    dep({ app: "api", version: "3.2.0", state: "deploying", created_at: "2026-09-30T00:00:00Z" }),
    dep({ app: "api", account: PRD, version: "3.0.5", state: "deployed" }),
    dep({ app: "api", account: PRD, version: "3.0.4", state: "undeployed", created_at: "2026-08-01T00:00:00Z" }),
    dep({ app: "web", account: UAT, version: "2.4.1" }),
    dep({ app: "web", account: PRD, version: "2.4.1", state: "undeployed" }),
  ];

  it("groups by app, newest live first, with undeployed rows as history", () => {
    const [api, web] = rowsOf(items);
    expect(api.app).toBe("api");
    const dev = api.cells[`${DEV}|us-east-1`];
    expect(dev.live.map((d) => d.version)).toEqual(["3.2.0", "3.1.0"]);
    expect(cellLabel(dev)).toBe("3.1.0 → 3.2.0");
    const prd = api.cells[`${PRD}|us-east-1`];
    expect(prd.live.map((d) => d.version)).toEqual(["3.0.5"]);
    expect(prd.history.map((d) => d.version)).toEqual(["3.0.4"]);
    expect(cellLabel(prd)).toBe("3.0.5");
    expect(web.cells[`${PRD}|us-east-1`].live).toEqual([]);
    expect(cellLabel(web.cells[`${PRD}|us-east-1`])).toBe("Not running");
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
    dep({ app: "api", kind: "ec2" }),
    dep({ app: "orders-api", kind: "ecs", account: PRD }),
    dep({ app: "reports", kind: "ecs" }),
  ];

  it("filters by kind, account, and app text", () => {
    expect(filterItems(items, { kind: "ecs", accounts: [], q: "" }).map((d) => d.app)).toEqual(["orders-api", "reports"]);
    expect(filterItems(items, { kind: "", accounts: [DEV], q: "" }).map((d) => d.app)).toEqual(["api", "reports"]);
    expect(filterItems(items, { kind: "", accounts: [], q: "API" }).map((d) => d.app)).toEqual(["api", "orders-api"]);
  });
});

describe("runStatus", () => {
  it("says whether anything runs, apart from the deploy state", () => {
    expect(runStatus(dep({ desired: 2, running: 2 }))).toEqual({ key: "running", label: "2 of 2 running" });
    expect(runStatus(dep({ desired: 3, running: 1 }))).toEqual({ key: "partial", label: "1 of 3 running" });
    expect(runStatus(dep({ desired: 0, running: 0 }))).toEqual({ key: "stopped", label: "Stopped" });
    expect(runStatus(dep({ desired: 2, running: 0 }))).toEqual({ key: "down", label: "No instances running" });
    expect(runStatus(dep({ kind: "ecs", desired: 2, running: 0 }))).toEqual({ key: "down", label: "No tasks running" });
    expect(runStatus(dep({ desired: 0, running: 1 }))).toEqual({ key: "stopping", label: "Stopping: 1 still running" });
  });
});
