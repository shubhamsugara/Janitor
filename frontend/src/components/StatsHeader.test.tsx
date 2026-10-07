import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Meta, Stats } from "../api";
import StatsHeader from "./StatsHeader";

const meta = { accounts: [], definitions: { statuses: {} } } as unknown as Meta;
const stats: Stats = {
  total: 38,
  orphaned: 14,
  size_gib: 3000,
  est_monthly_usd: 3000,
  orphaned_gib: 2400,
  orphaned_usd: 2842.4,
  blocked: 23,
  deletable: 15,
  by_status: [],
  by_account: [],
  by_region: [],
  by_age: [],
};

describe("StatsHeader", () => {
  it("keeps the waste figure short enough for one line; the unit sits underneath", () => {
    render(<StatsHeader stats={stats} meta={meta} />);
    expect(screen.getByText("~$2,842.40")).toBeTruthy();
    expect(screen.getByText("Orphaned resources, per month")).toBeTruthy();
  });

  it("shows the four headline numbers with their labels", () => {
    render(<StatsHeader stats={stats} meta={meta} />);
    for (const label of ["Matching", "Orphaned", "Waste", "Blocked · deletable"]) expect(screen.getByText(label)).toBeTruthy();
    expect(screen.getByText("23 · 15")).toBeTruthy();
  });
});
