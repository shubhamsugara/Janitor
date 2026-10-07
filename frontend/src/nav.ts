import type { Meta, ResourceType } from "./api";

export const TYPE_PAGES: { type: ResourceType; path: string; title: string }[] = [
  { type: "ami", path: "/amis", title: "AMIs" },
  { type: "snapshot", path: "/snapshots", title: "EBS snapshots" },
  { type: "volume", path: "/volumes", title: "EBS volumes" },
  { type: "rds_snapshot", path: "/rds-snapshots", title: "RDS snapshots" },
];

export type Notify = (type: "success" | "error" | "info", content: string) => void;

export interface PageProps {
  meta: Meta;
  notify: Notify;
}
