import { useMemo, useState } from "react";
import { Background, Controls, Handle, MarkerType, NodeToolbar, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import type { Graph, GraphNode, Meta } from "../api";
import { RELATION_LABELS, diagramHeight, layoutGraph, nodeDetails } from "../graphLayout";
import AwsIcon from "./AwsIcon";
import "./diagram.css";

const RESOURCE_KINDS = new Set(["ami", "snapshot", "volume", "rds_snapshot"]);

type NodeData = { node: GraphNode; isRoot: boolean; statusLabel: string; lane: number; upper: boolean };
type JanitorNode = Node<NodeData, "janitor">;

/** Rendered above the canvas (a portal), so a neighbouring node never covers it. */
function HoverCard({ data, visible }: { data: NodeData; visible: boolean }) {
  const { kind, title, rows } = nodeDetails(data.node, data.statusLabel);
  // Open toward the middle of the canvas, so the card isn't clipped at its edges.
  const align = data.lane > 0 ? "end" : data.lane < 0 ? "start" : "center";
  return (
    <NodeToolbar isVisible={visible} position={data.upper ? Position.Bottom : Position.Top} align={align} offset={10}>
      <div className="janitor-hovercard" role="tooltip">
        <div className="janitor-hovercard-kind">{kind}</div>
        <div className="janitor-hovercard-title">{title}</div>
        <dl>
          {rows.map(([k, v]) => (
            <div key={k}>
              <dt>{k}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
      </div>
    </NodeToolbar>
  );
}

function JanitorNodeView({ data }: NodeProps<JanitorNode>) {
  const { node, isRoot, statusLabel } = data;
  const [hover, setHover] = useState(false);
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
    <div className={classes} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
      {node.kind !== "more" && <HoverCard data={data} visible={hover} />}
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
  height?: string; // a CSS height; default: tall enough for the fullest lane
}

/** Where a resource comes from (left) and what depends on it (right). Click a resource to re-center. */
export default function LinkageDiagram({ graph, meta, dark, onSelect, height }: Props) {
  const { nodes, edges } = useMemo(() => {
    const active = new Set(graph.nodes.filter((n) => n.active).map((n) => n.id));
    const nodes: JanitorNode[] = layoutGraph(graph).map(({ node, x, y, isRoot }) => ({
      id: node.id,
      type: "janitor",
      position: { x, y },
      draggable: false,
      connectable: false,
      data: {
        node,
        isRoot,
        statusLabel: node.status ? meta.definitions.statuses[node.status].label : "",
        lane: node.depth,
        upper: y < 0,
      },
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
    <div className="janitor-diagram" style={{ height: height ?? diagramHeight(graph) }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        colorMode={dark ? "dark" : "light"}
        fitView
        fitViewOptions={{ maxZoom: 1, padding: 0.15 }}
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
