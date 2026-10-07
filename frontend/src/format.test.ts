import { describe, expect, it } from "vitest";
import type { SimulateResult } from "./api";
import { formatMoney, formatRate, plural, simulationSummary } from "./format";

describe("plural", () => {
  it("uses the singular for one", () => {
    expect(plural(1, "resource")).toBe("1 resource");
  });

  it("uses the plural for zero and many", () => {
    expect(plural(0, "resource")).toBe("0 resources");
    expect(plural(1200, "backing snapshot")).toBe("1,200 backing snapshots");
  });
});

describe("money", () => {
  it("shows rates to six places and amounts to cents", () => {
    expect(formatRate(0.03185)).toBe("$0.03185");
    expect(formatMoney(2080)).toBe("$2,080.00");
  });
});

describe("simulationSummary", () => {
  const totals = { count: 3, size_gib: 40, est_monthly_usd: 2 };

  it("names each skip reason once", () => {
    const result: SimulateResult = {
      would_delete: [],
      failed: [],
      totals,
      skipped: [
        { id: "a", name: "a", rule: "In use", reason: "" },
        { id: "b", name: "b", rule: "In use", reason: "" },
        { id: "c", name: "c", rule: "Protected tag", reason: "" },
      ],
    };
    expect(simulationSummary(result)).toBe(
      "Simulated: 3 would be deleted (40 GiB, ~$2.00/month), 3 skipped (in use, protected tag).",
    );
  });

  it("leaves out skipped when nothing was skipped", () => {
    const result: SimulateResult = { would_delete: [], failed: [], totals, skipped: [] };
    expect(simulationSummary(result)).toBe("Simulated: 3 would be deleted (40 GiB, ~$2.00/month).");
  });
});
