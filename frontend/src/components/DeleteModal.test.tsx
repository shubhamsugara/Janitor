import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Meta, Plan, PlanItem } from "../api";
import DeleteModal from "./DeleteModal";

const meta = { policy: { orphan_after_days: 90, min_age_days: 30, typed_confirm_min_items: 25 } } as unknown as Meta;
const noop = () => {};

function item(id: string, parent: string | null = null, outcome: "block" | "warn" | null = null): PlanItem {
  return {
    id,
    type: parent ? "snapshot" : "ami",
    name: id,
    account: "111111111111",
    region: "us-east-1",
    status: "orphaned",
    status_reason: "",
    size_gb: 8,
    est_monthly_cost: null,
    tags: {},
    parent,
    rules: outcome ? [{ rule_id: outcome === "block" ? "R1" : "W4", title: "T", outcome, message: `${id} ${outcome}` }] : [],
  };
}

function plan(overrides: Partial<Plan>): Plan {
  return {
    plan_id: "p1",
    variant: "none_blocked",
    blocked: [],
    deletable: [],
    missing: [],
    totals: { count: 0, size_gib: 0, est_monthly_usd: 0 },
    share_impact: [],
    requires_typed_confirmation: false,
    ...overrides,
  };
}

function show(p: Plan) {
  render(<DeleteModal plan={p} meta={meta} onClose={noop} onSimulated={noop} />);
}

describe("DeleteModal", () => {
  it("is always headed as a simulation", () => {
    show(plan({ deletable: [item("ami-1")] }));
    expect(screen.getByText("Simulation — nothing will be deleted.")).toBeTruthy();
  });

  it("offers only Close when everything is blocked", () => {
    show(plan({ variant: "all_blocked", blocked: [item("ami-1", null, "block")] }));
    expect(screen.getByText("Can't delete these resources")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Close" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Simulate/ })).toBeNull();
  });

  it("counts resources and backing snapshots separately when mixed", () => {
    show(
      plan({
        variant: "mixed",
        blocked: [item("ami-1", null, "block")],
        deletable: [item("ami-2"), item("ami-3"), item("snap-2", "ami-2"), item("snap-3", "ami-3")],
      }),
    );
    expect(screen.getByText("1 blocked will be skipped")).toBeTruthy();
    expect(screen.getByText("Simulate deleting the other 2 resources and 2 backing snapshots?")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Simulate 2" })).toBeTruthy();
  });

  it("uses the singular for one resource", () => {
    show(plan({ deletable: [item("ami-1"), item("snap-1", "ami-1")] }));
    expect(screen.getByText("Simulate deleting 1 resource and 1 backing snapshot?")).toBeTruthy();
  });

  it("asks for typed confirmation using the configured threshold", () => {
    show(plan({ deletable: [item("ami-1")], requires_typed_confirmation: true }));
    expect(screen.getByText(/Required for 25 or more items/)).toBeTruthy();
    const simulate = () => screen.getByRole("button", { name: "Simulate" }) as HTMLButtonElement;
    expect(simulate().disabled).toBe(true);
    fireEvent.change(screen.getByPlaceholderText("delete"), { target: { value: "delete" } });
    expect(simulate().disabled).toBe(false);
  });

  it("says what to do about resources missing from the scan", () => {
    show(plan({ deletable: [item("ami-1")], missing: ["ami-gone"] }));
    expect(
      screen.getByText(
        "1 selected resource isn't in the latest scan, so it was left out. Reload the list to see the current resources.",
      ),
    ).toBeTruthy();
  });

  it("closes on Cancel without simulating", () => {
    const onClose = vi.fn();
    render(<DeleteModal plan={plan({ deletable: [item("ami-1")] })} meta={meta} onClose={onClose} onSimulated={noop} />);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
