import type { ResourceType } from "./api";

/** A created-date range: fixed dates, or "the last N units" resolved against today. */
export type RangeValue =
  | { type: "absolute"; startDate: string; endDate: string }
  | { type: "relative"; amount: number; unit: "day" | "week" | "month" | "year"; key?: string };

/** A resource page's filter, sort, and page state. It lives in the URL so links reproduce views. */
export interface Filters {
  q: string;
  status: string[];
  account: string[];
  region: string[];
  tag: string;
  from: string; // YYYY-MM-DD, created on or after
  to: string; // YYYY-MM-DD, created on or before
  name: string; // a regular expression on the name
  sourceAmi: string; // AMIs copied from it, and snapshots that name it
  sourceDb: string; // RDS snapshots of this database
  sort: string;
  page: number;
}

export const DEFAULT_SORT = "-created_at";
export const EMPTY: Filters = {
  q: "",
  status: [],
  account: [],
  region: [],
  tag: "",
  from: "",
  to: "",
  name: "",
  sourceAmi: "",
  sourceDb: "",
  sort: DEFAULT_SORT,
  page: 1,
};
const LISTS = ["status", "account", "region"] as const;
/** Text filters: [Filters key, URL key, API key]. */
const TEXTS = [
  ["tag", "tag", "tag"],
  ["name", "name", "name_regex"],
  ["sourceAmi", "source_ami", "source_ami"],
  ["sourceDb", "source_db", "source_db"],
] as const;

export function parseFilters(search: URLSearchParams): Filters {
  const list = (key: string) => (search.get(key) ?? "").split(",").filter(Boolean);
  const page = Number(search.get("page"));
  return {
    q: search.get("q") ?? "",
    status: list("status"),
    account: list("account"),
    region: list("region"),
    tag: search.get("tag") ?? "",
    from: search.get("from") ?? "",
    to: search.get("to") ?? "",
    name: search.get("name") ?? "",
    sourceAmi: search.get("source_ami") ?? "",
    sourceDb: search.get("source_db") ?? "",
    sort: search.get("sort") || DEFAULT_SORT,
    page: Number.isInteger(page) && page > 0 ? page : 1,
  };
}

/** The URL form: only non-default values, so links stay short. */
export function toSearch(f: Filters): URLSearchParams {
  const s = new URLSearchParams();
  if (f.q) s.set("q", f.q);
  for (const key of LISTS) if (f[key].length) s.set(key, f[key].join(","));
  for (const [key, url] of TEXTS) if (f[key]) s.set(url, f[key]);
  if (f.from) s.set("from", f.from);
  if (f.to) s.set("to", f.to);
  if (f.sort !== DEFAULT_SORT) s.set("sort", f.sort);
  if (f.page > 1) s.set("page", String(f.page));
  return s;
}

/** The API form: the server calls the date filters created_from and created_to. */
export function toApiParams(type: ResourceType, f: Filters, extra: Record<string, string> = {}): URLSearchParams {
  const s = new URLSearchParams({ type, ...extra });
  if (f.q) s.set("q", f.q);
  for (const [key, , api] of TEXTS) if (f[key]) s.set(api, f[key]);
  for (const key of LISTS) if (f[key].length) s.set(key, f[key].join(","));
  if (f.from) s.set("created_from", f.from);
  if (f.to) s.set("created_to", f.to);
  return s;
}

/** The filter part of the API form as a plain object, for "Select all N matching". */
export function filtersToApi(type: ResourceType, f: Filters): Record<string, string> {
  return Object.fromEntries(toApiParams(type, f));
}

export function hasFilters(f: Filters): boolean {
  return Boolean(f.q || f.from || f.to || TEXTS.some(([key]) => f[key]) || LISTS.some((key) => f[key].length));
}

export function toRange(f: Filters): RangeValue | null {
  return f.from || f.to ? { type: "absolute", startDate: f.from, endDate: f.to } : null;
}

/** Date-range picker value → from/to. A relative range ("last 30 days") is resolved against `today`. */
export function fromRange(value: RangeValue | null, f: Filters, today = new Date()): Filters {
  if (!value) return { ...f, from: "", to: "", page: 1 };
  if (value.type === "absolute") {
    return { ...f, from: value.startDate.slice(0, 10), to: value.endDate.slice(0, 10), page: 1 };
  }
  const start = new Date(today);
  if (value.unit === "year") start.setFullYear(start.getFullYear() - value.amount);
  else if (value.unit === "month") start.setMonth(start.getMonth() - value.amount);
  else if (value.unit === "week") start.setDate(start.getDate() - 7 * value.amount);
  else start.setDate(start.getDate() - value.amount);
  return { ...f, from: isoDate(start), to: isoDate(today), page: 1 };
}

function isoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
