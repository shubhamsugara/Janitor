import { describe, expect, it } from "vitest";
import type { Deployment } from "./api";
import { appDetail, chartOf, filterApps, MAX_SERIES } from "./apps";

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
    unit: "asg",
    tags: {},
    ...over,
  };
}

const PRD = { account: "333333333333", account_name: "prd-us" };

describe("filterApps", () => {
  const items = [
    dep({ app: "api" }),
    dep({ app: "web", ...PRD, region: "us-west-2" }),
    dep({ app: "orders-api", ...PRD }),
  ];
  it("filters by env (account), region, and app name", () => {
    expect(filterApps(items, { envs: ["prd-us"], regions: [], q: "" }).map((d) => d.app)).toEqual(["web", "orders-api"]);
    expect(filterApps(items, { envs: [], regions: ["us-west-2"], q: "" }).map((d) => d.app)).toEqual(["web"]);
    expect(filterApps(items, { envs: [], regions: [], q: "API" }).map((d) => d.app)).toEqual(["api", "orders-api"]);
  });
});

describe("chartOf", () => {
  it("stacks running counts per app over env columns, biggest apps first", () => {
    const items = [
      dep({ app: "api", running: 2 }),
      dep({ app: "api", ...PRD, running: 6 }),
      dep({ app: "web", ...PRD, running: 1 }),
    ];
    const chart = chartOf(items, items);
    expect(chart.series.map((s) => [s.app, s.slot])).toEqual([
      ["api", 0],
      ["web", 1],
    ]);
    expect(chart.points.map((p) => p.label)).toEqual(["dev · us-east-1", "prd-us · us-east-1"]);
    expect(chart.points[1]).toMatchObject({ s0: 6, s1: 1 });
    expect(chart.points[0]).toMatchObject({ s0: 2, s1: 0 });
    expect(chart.other).toBe(false);
  });

  it("folds apps past the palette into Other", () => {
    const items = Array.from({ length: MAX_SERIES + 3 }, (_, i) => dep({ app: `app-${String(i).padStart(2, "0")}`, running: 100 - i }));
    const chart = chartOf(items, items);
    expect(chart.series).toHaveLength(MAX_SERIES);
    expect(chart.other).toBe(true);
    expect(chart.points[0].other).toBe(92 + 91 + 90); // apps 8, 9, and 10
  });

  it("keeps an app's color when a filter hides bigger apps", () => {
    const all = [dep({ app: "big", running: 9 }), dep({ app: "mid", running: 5 }), dep({ app: "small", running: 1 })];
    const shown = all.filter((d) => d.app !== "big");
    const slots = Object.fromEntries(chartOf(shown, all).series.map((s) => [s.app, s.slot]));
    expect(slots).toEqual({ mid: 1, small: 2 });
  });
});

describe("appDetail", () => {
  it("lists every resource and merges tags with how many resources carry each value", () => {
    const items = [
      dep({ app: "api", name: "dev-api-1", tags: { owner: "core", env: "dev" } }),
      dep({ app: "api", ...PRD, name: "prd-api-1", tags: { owner: "core", env: "prd" } }),
      dep({ app: "web", tags: { owner: "web" } }),
    ];
    const detail = appDetail(items, "api");
    expect(detail.resources.map((d) => d.name)).toEqual(["dev-api-1", "prd-api-1"]);
    expect(detail.tags).toEqual([
      { key: "env", values: [{ value: "dev", count: 1 }, { value: "prd", count: 1 }] },
      { key: "owner", values: [{ value: "core", count: 2 }] },
    ]);
    expect([detail.running, detail.places]).toEqual([4, 2]);
  });
});
