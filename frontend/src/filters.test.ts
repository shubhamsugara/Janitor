import { describe, expect, it } from "vitest";
import { EMPTY, fromRange, hasFilters, parseFilters, toApiParams, toRange, toSearch } from "./filters";

const full = {
  q: "base",
  status: ["orphaned", "idle"],
  account: ["222222222222"],
  region: ["us-east-1"],
  tag: "env=prod",
  from: "2026-01-01",
  to: "2026-03-31",
  sort: "name",
  page: 3,
};

describe("filters in the URL", () => {
  it("round-trips through the query string", () => {
    expect(parseFilters(toSearch(full))).toEqual(full);
  });

  it("leaves defaults out of the URL", () => {
    expect(toSearch(EMPTY).toString()).toBe("");
    expect(hasFilters(EMPTY)).toBe(false);
  });

  it("falls back to page 1 for a bad page", () => {
    expect(parseFilters(new URLSearchParams("page=-2")).page).toBe(1);
  });

  it("uses the server's names for the date filters", () => {
    const params = toApiParams("volume", full, { page: "3" });
    expect(params.get("created_from")).toBe("2026-01-01");
    expect(params.get("created_to")).toBe("2026-03-31");
    expect(params.get("status")).toBe("orphaned,idle");
    expect(params.get("type")).toBe("volume");
    expect(params.get("page")).toBe("3");
  });
});

describe("date range", () => {
  it("round-trips an absolute range", () => {
    const range = toRange(full);
    expect(range).toEqual({ type: "absolute", startDate: "2026-01-01", endDate: "2026-03-31" });
    expect(fromRange(range, EMPTY)).toMatchObject({ from: "2026-01-01", to: "2026-03-31" });
  });

  it("resolves a relative range against today", () => {
    const today = new Date(2026, 9, 1);
    const value = { type: "relative" as const, amount: 30, unit: "day" as const, key: "30d" };
    expect(fromRange(value, EMPTY, today)).toMatchObject({ from: "2026-09-01", to: "2026-10-01" });
  });

  it("clears the range", () => {
    expect(fromRange(null, full)).toMatchObject({ from: "", to: "", page: 1 });
  });
});
