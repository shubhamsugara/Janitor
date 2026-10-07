import { useState } from "react";
import type { NodeKind } from "../api";

// AWS category colors: compute orange, storage green, database purple, management pink.
const GLYPHS: Record<NodeKind, { text: string; color: string }> = {
  ami: { text: "AMI", color: "#ED7100" },
  instance: { text: "EC2", color: "#ED7100" },
  asg: { text: "ASG", color: "#ED7100" },
  launch_template: { text: "LT", color: "#ED7100" },
  launch_config: { text: "LC", color: "#ED7100" },
  snapshot: { text: "SNAP", color: "#7AA116" },
  volume: { text: "EBS", color: "#7AA116" },
  rds_snapshot: { text: "RDS", color: "#C925D1" },
  database: { text: "DB", color: "#C925D1" },
  account: { text: "ACCT", color: "#E7157B" },
  more: { text: "…", color: "#687078" },
};

/** The official AWS icon when `make icons` has fetched it; otherwise a labeled tile in its category color. */
export default function AwsIcon({ kind, size = 32 }: { kind: NodeKind; size?: number }) {
  const [failed, setFailed] = useState(false);
  if (!failed && kind !== "more") {
    return <img src={`/aws-icons/${kind}.svg`} width={size} height={size} alt="" onError={() => setFailed(true)} />;
  }
  const glyph = GLYPHS[kind];
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="6" fill={glyph.color} />
      <text x="16" y="20" textAnchor="middle" fontSize={glyph.text.length > 3 ? 8 : 10} fontWeight="700" fill="#fff" fontFamily="sans-serif">
        {glyph.text}
      </text>
    </svg>
  );
}
