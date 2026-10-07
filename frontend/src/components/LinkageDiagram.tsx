import { useMemo } from "react";
import { Background, Controls, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import type { Graph, GraphNode, Meta } from "../api";
import { RELATION_LABELS, diagramHeight, layoutGraph } from "../graphLayout";
import AwsIcon from "./AwsIcon";
import "./diagram.css";

const RESOURCE_KINDS = new Set(["ami", "snapshot", "volume", "rds_snapshot"]);

type NodeData = { node: GraphNode; isRoot: boolean; statusLabel: string };
type JanitorNode = Node<NodeData, "janitor">;

function JanitorNodeView({ data }: NodeProps<JanitorNode>) {
  const { node, isRoot, statusLabel } = data;
  const classes = [
    "janitor-node",
    `status-${node.status ?? "none"}`,
    isRoot ? "root" : "",
    node.active ? "active" : "",
    node.kind === "more" ? "more" : "",
    RESOURCE_KINDS.has(node.kind) && !isRoot ? "clickable" : "",
  ].join(" ");
  const meta = [statusLabel, node.account_name, node.region].filter(Boolean).join(" · ");
  return (
    <div className={classes} title={node.id}>
      <Handle type="target" position={Position.Left} />
      {node.kind !== "more" && <AwsIcon kind={node.kind} size={28} />}
      <div className="janitor-node-text">
        <div className="janitor-node-label">{node.label}</div>
        {meta && <div className="janitor-node-meta">{meta}</div>}
        {node.status === null && node.state && (
          <div className="janitor-node-state">
            {node.active ? "● " : node.active === false ? "○ " : ""}
            {node.state}
          </div>
        )}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

const NODE_TYPES = { janitor: JanitorNodeView };

interface Props {
  graph: Graph;
  meta: Meta;
  dark: boolean;
  onSelect: (id: string) => void;
}

/** Where a resource comes from (left) and what depends on it (right). Click a resource to re-center. */
export default function LinkageDiagram({ graph, meta, dark, onSelect }: Props) {
  const { nodes, edges } = useMemo(() => {
    const active = new Set(graph.nodes.filter((n) => n.active).map((n) => n.id));
    const nodes: JanitorNode[] = layoutGraph(graph).map(({ node, x, y, isRoot }) => ({
      id: node.id,
      type: "janitor",
      position: { x, y },
      draggable: false,
      connectable: false,
      data: { node, isRoot, statusLabel: node.status ? meta.definitions.statuses[node.status].label : "" },
    }));
    const edges: Edge[] = graph.edges.map((e) => ({
      id: `${e.source}->${e.target}:${e.relation}`,
      source: e.source,
      target: e.target,
      label: RELATION_LABELS[e.relation] ?? e.relation,
      animated: e.relation === "used_by" && active.has(e.target),
      markerEnd: { type: MarkerType.ArrowClosed },
      className: `edge-${e.relation}`,
    }));
    return { nodes, edges };
  }, [graph, meta]);

  return (
    <div className="janitor-diagram" style={{ height: diagramHeight(graph) }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        colorMode={dark ? "dark" : "light"}
        fitView
        minZoom={0.2}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        onNodeClick={(_, n) => {
          const kind = (n.data as NodeData).node.kind;
          if (RESOURCE_KINDS.has(kind) && n.id !== graph.root) onSelect(n.id);
        }}
      >
        <Background />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
