import { describe, expect, it } from "vitest";
import type { Deployment } from "./api";
import { appDetail, filterApps, MAX_SERIES, treemapOf } from "./apps";

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

describe("treemapOf", () => {
  it("groups apps under envs, sized by running, biggest first", () => {
    const items = [
      dep({ app: "api", running: 2 }),
      dep({ app: "web", running: 5 }),
      dep({ app: "api", ...PRD, running: 6 }),
      dep({ app: "api", ...PRD, region: "us-west-2", running: 1 }),
      dep({ app: "idle", ...PRD, running: 0 }),
    ];
    const groups = treemapOf(items, items);
    expect(groups.map((g) => [g.env, g.running, g.slot])).toEqual([
      ["dev", 7, 0], // a tie keeps the Deployments column order
      ["prd-us", 7, 1],
    ]);
    expect(groups[1].children).toEqual([{ name: "api", app: "api", env: "prd-us", running: 7, slot: 1 }]); // regions combine; idle apps take no space
    expect(groups[0].children.map((c) => c.app)).toEqual(["web", "api"]);
  });

  it("keeps an env's color when a filter hides other envs", () => {
    const all = [dep({ app: "api" }), dep({ app: "api", ...PRD })];
    const [only] = treemapOf(all.filter((d) => d.account_name === "prd-us"), all);
    expect([only.env, only.slot]).toEqual(["prd-us", 1]);
  });

  it("leaves envs past the palette uncolored", () => {
    const all = Array.from({ length: MAX_SERIES + 1 }, (_, i) => dep({ account: `${i}`.repeat(12).slice(0, 12), account_name: `env-${i}` }));
    expect(treemapOf(all, all).filter((g) => g.slot === null)).toHaveLength(1);
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
