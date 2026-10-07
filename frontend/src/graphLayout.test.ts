import { describe, expect, it } from "vitest";
import type { Graph, GraphNode } from "./api";
import { LANE_WIDTH, ROW_HEIGHT, layoutGraph } from "./graphLayout";

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
