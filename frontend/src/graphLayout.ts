import type { Graph, GraphNode, NodeKind } from "./api";

export const LANE_WIDTH = 300;
export const ROW_HEIGHT = 92;
const KIND_ORDER: NodeKind[] = [
  "ami",
  "snapshot",
  "volume",
  "rds_snapshot",
  "database",
  "instance",
  "asg",
  "launch_template",
  "launch_config",
  "account",
  "more",
];

export const RELATION_LABELS: Record<string, string> = {
  backs: "backs",
  copied_to: "copy",
  used_by: "used by",
  shared_with: "shared with",
  attached_to: "attached to",
  snapshot_of: "snapshot",
  snapshot_of_db: "snapshot",
};

export interface Placed {
  node: GraphNode;
  x: number;
  y: number;
  isRoot: boolean;
}

function rank(node: GraphNode, root: string): number {
  return node.id === root ? -1 : KIND_ORDER.indexOf(node.kind);
}

/** Lanes by signed depth (upstream left, the root at 0, downstream right); each lane centered on y = 0. */
export function layoutGraph(graph: Graph): Placed[] {
  const lanes = new Map<number, GraphNode[]>();
  for (const node of graph.nodes) lanes.set(node.depth, [...(lanes.get(node.depth) ?? []), node]);
  const placed: Placed[] = [];
  for (const [depth, nodes] of lanes) {
    nodes.sort((a, b) => rank(a, graph.root) - rank(b, graph.root) || a.label.localeCompare(b.label));
    nodes.forEach((node, i) =>
      placed.push({
        node,
        x: depth * LANE_WIDTH,
        y: (i - (nodes.length - 1) / 2) * ROW_HEIGHT,
        isRoot: node.id === graph.root,
      }),
    );
  }
  return placed;
}
