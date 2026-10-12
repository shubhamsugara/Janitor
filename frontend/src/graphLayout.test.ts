import { describe, expect, it } from "vitest";
import type { Graph, GraphNode } from "./api";
import { LANE_WIDTH, NODE_WIDTH, ROW_HEIGHT, diagramHeight, layoutGraph, nodeDetails, RELATION_LABELS } from "./graphLayout";

function node(id: string, kind: GraphNode["kind"], depth: number, label = id): GraphNode {
  return { id, kind, label, status: null, account: "", account_name: "", region: "", active: null, state: "", depth };
}

const graph: Graph = {
  root: "ami-1",
  nodes: [
    node("instance:b", "instance", 1, "b"),
    node("ami-1", "ami", 0),
    node("account:x:r", "account", 1, "a"),
    node("snap-1", "snapshot", -1),
    node("instance:a", "instance", 1, "a"),
    node("snap-2", "snapshot", 0),
  ],
  edges: [],
  used_by: { active: 0, total: 0, summary: "" },
  truncated: false,
};

describe("layoutGraph", () => {
  const placed = Object.fromEntries(layoutGraph(graph).map((p) => [p.node.id, p]));

  it("puts lanes left to right by depth", () => {
    expect(placed["snap-1"].x).toBe(-LANE_WIDTH);
    expect(placed["ami-1"].x).toBe(0);
    expect(placed["instance:a"].x).toBe(LANE_WIDTH);
  });

  it("puts the root first in its lane", () => {
    expect(placed["ami-1"].isRoot).toBe(true);
    expect(placed["ami-1"].y).toBeLessThan(placed["snap-2"].y);
  });

  it("orders a lane by kind, then label, centered on zero", () => {
    const lane = layoutGraph(graph)
      .filter((p) => p.node.depth === 1)
      .sort((a, b) => a.y - b.y)
      .map((p) => p.node.id);
    expect(lane).toEqual(["instance:a", "instance:b", "account:x:r"]);
    expect(placed["instance:a"].y).toBe(-ROW_HEIGHT);
    expect(placed["account:x:r"].y).toBe(ROW_HEIGHT);
  });
});

describe("diagramHeight", () => {
  const lane = (n: number) => ({ ...graph, nodes: Array.from({ length: n }, (_, i) => node(`instance:${i}`, "instance", 1)) });

  it("grows with the tallest lane so labels stay readable", () => {
    expect(diagramHeight(lane(2))).toBe(360);
    expect(diagramHeight(lane(6))).toBe(6 * ROW_HEIGHT + 80);
  });

  it("stops growing at a full lane; the canvas scrolls and zooms from there", () => {
    expect(diagramHeight(lane(26))).toBe(900);
  });
});

describe("relation labels", () => {
  it("names the edge from an account to a template that only references the AMI", () => {
    expect(RELATION_LABELS.references).toBe("names it");
  });
});

describe("spacing", () => {
  it("leaves room between lanes for an edge and its label", () => {
    expect(LANE_WIDTH - NODE_WIDTH).toBeGreaterThanOrEqual(140);
  });

  it("leaves a clear gap between rows", () => {
    expect(ROW_HEIGHT).toBeGreaterThanOrEqual(110);
  });
});

describe("nodeDetails", () => {
  it("names what the resource is, then where it lives", () => {
    const n = { ...node("ami-0abc", "ami", 0, "web-1"), account_name: "admin", region: "us-east-1" };
    expect(nodeDetails(n, "Idle")).toEqual({
      kind: "AMI",
      title: "web-1",
      rows: [
        ["ID", "ami-0abc"],
        ["Status", "Idle"],
        ["Account", "admin"],
        ["Region", "us-east-1"],
      ],
    });
  });

  it("shows the state of a non-resource and skips empty fields", () => {
    const n = { ...node("instance:i-1", "instance", 1, "web-1"), state: "running" };
    expect(nodeDetails(n, "")).toEqual({ kind: "EC2 instance", title: "web-1", rows: [["ID", "i-1"], ["State", "running"]] });
  });

  it("shows the AWS ID, not the diagram's key, and only when the label isn't already it", () => {
    expect(nodeDetails(node("database:111111111111:us-east-1:orders-db", "database", -1, "orders"), "").rows).toEqual([["ID", "orders-db"]]);
    expect(nodeDetails(node("asg:111111111111:us-east-1:web", "asg", 1, "web"), "").rows).toEqual([]);
    expect(nodeDetails(node("account:ami-1:111111111111", "account", 1, "prd"), "").rows).toEqual([]);
  });

  it("has a label for every node kind", () => {
    const kinds = ["ami", "snapshot", "volume", "rds_snapshot", "database", "instance", "asg", "launch_template", "launch_config", "account", "more"] as const;
    for (const k of kinds) expect(nodeDetails(node("x", k, 0), "").kind).not.toBe(k);
  });
});
