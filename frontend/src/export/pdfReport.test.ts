import { describe, expect, it } from "vitest";
import type { ExportData, Meta } from "../api";
import { buildReport } from "./pdfReport";

const meta = {
  accounts: [{ id: "333333333333", name: "prd", owns: [], regions: [] }],
  definitions: { statuses: { orphaned: { label: "Orphaned" } } },
} as unknown as Meta;
const stats = { total: 7000, orphaned: 10, orphaned_gib: 100, orphaned_usd: 5, blocked: 2 } as unknown as ExportData["stats"];

function data(overrides: Partial<ExportData> = {}): ExportData {
  return {
    items: [
      {
        name: "v1",
        id: "vol-1",
        status: "orphaned",
        delete_check: "block",
        account_name: "prd",
        region: "us-east-1",
        created_at: "2026-01-02T03:04:05Z",
        size_gib: 10,
        est_monthly_usd: 1.5,
      },
    ],
    total: 1,
    truncated: false,
    limit: 5000,
    stats,
    filters: { type: "volume", account: "333333333333", status: "orphaned" },
    generated_at: "2026-10-01T00:00:00Z",
    provider: "mock",
    ...overrides,
  };
}

describe("buildReport", () => {
  it("names the file by type and date", () => {
    expect(buildReport(data(), meta, "volume", "EBS volumes").filename).toBe("janitor-volume-20261001.pdf");
  });

  it("lists the filters with account names and leaves out the type", () => {
    expect(buildReport(data(), meta, "volume", "EBS volumes").lines).toContain("Filters: account=prd; status=orphaned");
  });

  it("formats each cell for reading", () => {
    const [row] = buildReport(data(), meta, "volume", "EBS volumes").rows;
    expect(row).toEqual(["v1", "vol-1", "Orphaned", "Blocked", "prd", "us-east-1", "2026-01-02", "10", "1.50"]);
  });

  it("says when rows were cut", () => {
    const report = buildReport(data({ total: 7000, truncated: true }), meta, "volume", "EBS volumes");
    expect(report.note).toBe("Showing 1 of 7,000; export CSV for all rows.");
  });
});
