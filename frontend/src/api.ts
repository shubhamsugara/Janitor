export type ResourceType = "ami" | "snapshot" | "volume" | "rds_snapshot";
export type Status = "in_use" | "managed" | "unknown" | "orphaned" | "idle";
export type Outcome = "block" | "warn" | "pass";

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
  managed_by: string | null;
  est_monthly_cost: number | null;
  status: Status;
  status_reason: string;
  outcome: Outcome;
}

export interface Stats {
  total: number;
  orphaned: number;
  size_gib: number;
  est_monthly_usd: number | null;
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
  accounts: { id: string; name: string; owns: string[]; regions: string[] }[];
  definitions: {
    statuses: Record<Status, StatusDefinition>;
    by_type: Record<ResourceType, Partial<Record<Status, string>>>;
    rules: RuleDefinition[];
    precedence: Status[];
    notes: string[];
  };
}

export interface Scan {
  id: number;
  started_at: string;
  finished_at: string | null;
  provider: string;
  status: string;
}

export interface OverviewData {
  last_scan: Scan | null;
  scanning: boolean;
  types: { type: ResourceType; total: number; orphaned: number; orphaned_gib: number; orphaned_usd: number | null }[];
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
  skipped: { id: string; name: string; reason: string }[];
  failed: { id: string; reason: string }[];
  totals: Totals;
}

export interface ResourceDetail {
  resource: Resource;
  rules: { id: string; title: string; outcome: Outcome; message: string }[];
  related: {
    links: { relation: string; id: string; name: string; region: string; status: Status }[];
    shares: { principal_type: string; principal: string }[];
    usage: { account: string; region: string; ref_type: string; ref_id: string; ref_name: string }[];
  };
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
  resource: (id: string) => request<ResourceDetail>(`/api/resources/${encodeURIComponent(id)}`),
  startScan: () => request<{ started: boolean }>("/api/scans", { method: "POST" }),
  latestScan: () => request<{ scan: Scan | null; running: boolean }>("/api/scans/latest"),
  plan: (type: ResourceType, ids: string[]) =>
    request<Plan>("/api/actions/plan", { method: "POST", body: JSON.stringify({ type, ids }) }),
  simulate: (planId: string, confirmation: string) =>
    request<SimulateResult>("/api/actions/simulate", {
      method: "POST",
      body: JSON.stringify({ plan_id: planId, confirmation }),
    }),
  audit: (page: number) => request<{ items: AuditEntry[]; total: number }>(`/api/audit?page=${page}&page_size=25`),
};

/** Start a scan and wait until it finishes. */
export async function runScan(): Promise<Scan | null> {
  await api.startScan();
  for (;;) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    const { scan, running } = await api.latestScan();
    if (!running) {
      if (scan?.status === "failed") throw new Error("The scan failed. Check the server log, then scan again.");
      return scan;
    }
  }
}
