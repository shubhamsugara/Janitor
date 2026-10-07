import type { DateRangePickerProps } from "@cloudscape-design/components/date-range-picker";
import type { PropertyFilterProps } from "@cloudscape-design/components/property-filter";
import type { ResourceType } from "./api";

/** A resource page's filter, sort, and page state. It lives in the URL so links reproduce views. */
export interface Filters {
  q: string;
  status: string[];
  account: string[];
  region: string[];
  tag: string;
  from: string; // YYYY-MM-DD, created on or after
  to: string; // YYYY-MM-DD, created on or before
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
  sort: DEFAULT_SORT,
  page: 1,
};
const LISTS = ["status", "account", "region"] as const;

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
    sort: search.get("sort") || DEFAULT_SORT,
    page: Number.isInteger(page) && page > 0 ? page : 1,
  };
}

/** The URL form: only non-default values, so links stay short. */
export function toSearch(f: Filters): URLSearchParams {
  const s = new URLSearchParams();
  if (f.q) s.set("q", f.q);
  for (const key of LISTS) if (f[key].length) s.set(key, f[key].join(","));
  if (f.tag) s.set("tag", f.tag);
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
  for (const key of LISTS) if (f[key].length) s.set(key, f[key].join(","));
  if (f.tag) s.set("tag", f.tag);
  if (f.from) s.set("created_from", f.from);
  if (f.to) s.set("created_to", f.to);
  return s;
}

export function hasFilters(f: Filters): boolean {
  return Boolean(f.q || f.tag || f.from || f.to || LISTS.some((key) => f[key].length));
}

/** Property-filter tokens. Free text is the name or ID search; values within a property are ORed. */
export function toQuery(f: Filters): PropertyFilterProps.Query {
  const tokens: PropertyFilterProps.Token[] = [];
  if (f.q) tokens.push({ operator: ":", value: f.q });
  for (const key of LISTS) for (const value of f[key]) tokens.push({ propertyKey: key, operator: "=", value });
  if (f.tag) tokens.push({ propertyKey: "tag", operator: "=", value: f.tag });
  return { tokens, operation: "and" };
}

export function fromQuery(query: PropertyFilterProps.Query, f: Filters): Filters {
  const values = (key: string) => query.tokens.filter((t) => t.propertyKey === key).map((t) => String(t.value));
  const free = query.tokens.filter((t) => !t.propertyKey).map((t) => String(t.value));
  return {
    ...f,
    q: free.join(" "),
    status: values("status"),
    account: values("account"),
    region: values("region"),
    tag: values("tag")[0] ?? "",
    page: 1,
  };
}

export function toRange(f: Filters): DateRangePickerProps.Value | null {
  return f.from || f.to ? { type: "absolute", startDate: f.from, endDate: f.to } : null;
}

/** Date-range picker value → from/to. A relative range ("last 30 days") is resolved against `today`. */
export function fromRange(value: DateRangePickerProps.Value | null, f: Filters, today = new Date()): Filters {
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
