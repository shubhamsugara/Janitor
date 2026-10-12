import type { Graph, GraphNode, NodeKind } from "./api";

export const NODE_WIDTH = 236; // matches .janitor-node in diagram.css
export const LANE_WIDTH = 400; // node plus room for an edge and its label
export const ROW_HEIGHT = 116;
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
  references: "names it",
  shared_with: "shared with",
  attached_to: "attached to",
  snapshot_of: "snapshot",
  snapshot_of_db: "snapshot",
};

const KIND_LABELS: Record<NodeKind, string> = {
  ami: "AMI",
  snapshot: "EBS snapshot",
  volume: "EBS volume",
  rds_snapshot: "RDS snapshot",
  database: "RDS database",
  instance: "EC2 instance",
  asg: "Auto Scaling group",
  launch_template: "Launch template",
  launch_config: "Launch configuration",
  account: "AWS account",
  more: "More links",
};

const RESOURCE_KINDS = new Set<NodeKind>(["ami", "snapshot", "volume", "rds_snapshot"]);

/** A resource's node ID is its AWS ID; other nodes use "kind:...:awsId" keys. Accounts and "more" have none. */
function awsId(node: GraphNode): string {
  if (RESOURCE_KINDS.has(node.kind)) return node.id;
  if (node.kind === "account" || node.kind === "more") return "";
  return node.id.slice(node.id.lastIndexOf(":") + 1);
}

/** What the hover card on a diagram node shows: what it is, then where it lives. Empty fields are left out. */
export function nodeDetails(node: GraphNode, statusLabel: string): { kind: string; title: string; rows: [string, string][] } {
  const id = awsId(node);
  const rows: [string, string][] = [
    ["ID", id === node.label ? "" : id],
    ["Status", statusLabel],
    ["State", node.status === null ? node.state : ""],
    ["Account", node.account_name],
    ["Region", node.region],
  ];
  return { kind: KIND_LABELS[node.kind] ?? node.kind, title: node.label, rows: rows.filter(([, v]) => v) };
}

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

/** Canvas height for a graph: tall enough for its fullest lane at full size, within bounds. */
export function diagramHeight(graph: Graph): number {
  const lanes = new Map<number, number>();
  for (const node of graph.nodes) lanes.set(node.depth, (lanes.get(node.depth) ?? 0) + 1);
  const rows = Math.max(0, ...lanes.values());
  return Math.min(900, Math.max(360, rows * ROW_HEIGHT + 80));
}
