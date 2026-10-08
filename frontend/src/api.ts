export type ResourceType = "ami" | "snapshot" | "volume" | "rds_snapshot";
export type Status = "in_use" | "managed" | "unknown" | "orphaned" | "idle";
export type Outcome = "block" | "warn" | "pass";
export type NodeKind =
  | ResourceType
  | "instance"
  | "asg"
  | "launch_template"
  | "launch_config"
  | "account"
  | "database"
  | "more";

export interface CostLine {
  label: string;
  quantity: number;
  unit: string;
  rate: number;
  amount: number;
}

export interface CostBreakdown {
  region: string;
  source_date: string | null;
  estimate: string | null;
  lines: CostLine[];
  fallback: boolean;
  total: number;
}

export interface Resource {
  id: string;
  type: ResourceType;
  account: string;
  region: string;
  name: string;
  created_at: string;
  size_gb: number | null;
  state: string;
  tags: Record<string, string>;
  snapshot_ids: string[];
  source_ami_id: string | null;
  source_db_id?: string | null; // RDS snapshot
  shared_with?: string[]; // manual RDS snapshot: "all" means public
  managed_by: string | null;
  attached_instance: string | null;
  volume_type: string | null;
  iops: number | null;
  throughput: number | null;
  encrypted: boolean | null;
  storage_tier: string | null;
  est_monthly_cost: number | null;
  cost_breakdown: CostBreakdown | null;
  status: Status;
  status_reason: string;
  outcome: Outcome;
}

export interface Bucket {
  key: string;
  count: number;
  gib: number;
  usd: number | null;
}

export interface Stats {
  total: number;
  orphaned: number;
  size_gib: number;
  est_monthly_usd: number | null;
  orphaned_gib: number;
  orphaned_usd: number | null;
  blocked: number;
  deletable: number;
  by_status: Bucket[];
  by_account: Bucket[];
  by_region: Bucket[];
  by_age: Bucket[];
}

export interface ResourcePage {
  items: Resource[];
  total: number;
  stats: Stats | null;
  scan_id: number | null;
}

export interface StatusDefinition {
  label: string;
  blocks: boolean;
  meaning: string;
  what_to_do: string;
}

export interface RuleDefinition {
  id: string;
  title: string;
  outcome: Outcome;
  explanation: string;
}

export interface Meta {
  provider: string;
  read_only: boolean;
  owner: { account: string; regions: string[] };
  policy: { orphan_after_days: number; min_age_days: number; typed_confirm_min_items: number };
  prices: { source_date: string | null; fallback: boolean };
  accounts: { id: string; name: string; regions: string[] }[];
  /** Accounts that have each type in the shown scan; filters offer only these. */
  accounts_by_type?: Partial<Record<ResourceType, string[]>>;
  definitions: {
    statuses: Record<Status, StatusDefinition>;
    by_type: Record<ResourceType, Partial<Record<Status, string>>>;
    rules: RuleDefinition[];
    precedence: Status[];
    notes: string[];
    deployments: {
      summary: string;
      terms: { term: string; definition: string }[];
    };
  };
}

export interface Unresolved {
  account: string;
  region: string;
  ref_type: string;
  ref_id: string;
  value: string;
}

export interface Scan {
  id: number;
  started_at: string;
  finished_at: string | null;
  provider: string;
  status: "running" | "ok" | "partial" | "failed" | string;
  notes?: { error?: string; unresolved?: Unresolved[] };
}

export interface FailedCheck {
  account: string;
  account_name: string;
  region: string;
  kind: string;
  error_kind: string;
  message: string;
}

export interface ScanProgress {
  scan: Scan | null;
  running: boolean;
  segments?: unknown[];
  progress?: { done: number; failed: number };
}

export interface OverviewData {
  last_scan: Scan | null;
  scanning: boolean;
  types: { type: ResourceType; total: number; orphaned: number; orphaned_gib: number; orphaned_usd: number | null }[];
  segments_failed?: FailedCheck[];
  unresolved?: Unresolved[];
  newest_failed?: { finished_at: string | null; message: string } | null;
}

export interface RuleHit {
  rule_id: string;
  title: string;
  outcome: Outcome;
  message: string;
}

export interface PlanItem {
  id: string;
  type: ResourceType;
  name: string;
  account: string;
  region: string;
  status: Status;
  status_reason: string;
  size_gb: number | null;
  est_monthly_cost: number | null;
  tags: Record<string, string>;
  parent: string | null;
  rules: RuleHit[];
}

export interface ShareImpact {
  ami_id: string;
  region: string;
  accounts: { id: string; name: string; scanned: boolean }[];
  other: string[];
  copies: { id: string; region: string; status: Status }[];
}

export interface Totals {
  count: number;
  size_gib: number;
  est_monthly_usd: number;
}

export interface Plan {
  plan_id: string;
  variant: "all_blocked" | "mixed" | "none_blocked";
  blocked: PlanItem[];
  deletable: PlanItem[];
  missing: string[];
  totals: Totals;
  share_impact: ShareImpact[];
  requires_typed_confirmation: boolean;
}

export interface SimulateResult {
  would_delete: PlanItem[];
  skipped: { id: string; name: string; rule: string; reason: string }[];
  failed: { id: string; reason: string }[];
  totals: Totals;
}

export interface ResourceDetail {
  resource: Resource;
  rules: { id: string; title: string; outcome: Outcome; message: string }[];
  related: {
    links: { relation: string; id: string; name: string; region: string; status: Status }[];
    shares: { principal_type: string; principal: string }[];
    usage: { account: string; region: string; ref_type: string; ref_id: string; ref_name: string; ref_state: string }[];
  };
}

export interface GraphNode {
  id: string;
  kind: NodeKind;
  label: string;
  status: Status | null;
  account: string;
  account_name: string;
  region: string;
  active: boolean | null;
  state: string;
  depth: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  relation: string;
}

export interface Graph {
  root: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  used_by: { active: number | null; total: number; summary: string };
  truncated: boolean;
}

export interface ExportData {
  items: Record<string, string | number | null>[];
  total: number;
  truncated: boolean;
  limit: number;
  stats: Stats;
  filters: Record<string, string>;
  generated_at: string;
  provider: string;
}

export type DeploymentState = "deploying" | "deployed" | "undeploying" | "undeployed" | "failed";

/** An ASG a deploy tool tagged, an instance in no ASG, or an ECS service. Shown as found; never judged. */
export interface Deployment {
  kind: "ec2" | "ecs";
  account: string;
  account_name: string;
  region: string;
  env: string;
  app: string;
  version: string;
  state: DeploymentState;
  resource_id: string;
  name: string;
  created_at: string;
  desired: number;
  running: number;
  deployment_id: string;
  launch_template: string;
  launch_template_version: string;
  ami_id: string | null;
  ami: { id: string; name: string; status: Status } | null;
  cluster: string;
  task_definition: string;
  image: string;
  unit: "asg" | "instance" | "service"; // instance: an EC2 instance in no Auto Scaling group
}

export interface DeploymentsData {
  scan_id: number | null;
  items: Deployment[];
  failed: FailedCheck[];
}

export interface AuditEntry {
  id: number;
  ts: string;
  actor: string;
  action: string;
  payload: Record<string, unknown>;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `The server returned ${response.status}. Try again.`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  meta: () => request<Meta>("/api/meta"),
  overview: () => request<OverviewData>("/api/overview"),
  resources: (params: URLSearchParams) => request<ResourcePage>(`/api/resources?${params}`),
  stats: (params: URLSearchParams) => request<Stats | null>(`/api/stats?${params}`),
  resource: (id: string) => request<ResourceDetail>(`/api/resources/${encodeURIComponent(id)}`),
  graph: (id: string) => request<Graph>(`/api/resources/${encodeURIComponent(id)}/graph`),
  exportJson: (params: URLSearchParams) => request<ExportData>(`/api/resources/export.json?${params}`),
  startScan: () => request<{ started: boolean }>("/api/scans", { method: "POST" }),
  latestScan: () => request<ScanProgress>("/api/scans/latest"),
  plan: (type: ResourceType, ids: string[]) =>
    request<Plan>("/api/actions/plan", { method: "POST", body: JSON.stringify({ type, ids }) }),
  simulate: (planId: string, confirmation: string) =>
    request<SimulateResult>("/api/actions/simulate", {
      method: "POST",
      body: JSON.stringify({ plan_id: planId, confirmation }),
    }),
  deployments: () => request<DeploymentsData>("/api/deployments"),
  audit: (page: number) => request<{ items: AuditEntry[]; total: number }>(`/api/audit?page=${page}&page_size=25`),
};

export function exportCsvUrl(params: URLSearchParams): string {
  return `/api/resources/export.csv?${params}`;
}

/** Start a scan and wait until it finishes. A partial scan finished; a failed one throws its reason. */
export async function runScan(onProgress?: (checksDone: number) => void): Promise<Scan | null> {
  await api.startScan();
  for (;;) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    const { scan, running, progress } = await api.latestScan();
    if (progress) onProgress?.(progress.done);
    if (!running) {
      if (scan?.status === "failed") throw new Error(scan.notes?.error ?? "The scan failed. Check the server log, then scan again.");
      return scan;
    }
  }
}
