import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Meta } from "../api";
import { EMPTY } from "../filters";
import FilterBar from "./FilterBar";

const meta = {
  owner: { account: "111111111111", regions: ["us-east-1"] },
  accounts: [
    { id: "111111111111", name: "tools", regions: ["us-east-1"] },
    { id: "333333333333", name: "prd", regions: ["us-east-1", "eu-west-1"] },
  ],
  definitions: { statuses: { orphaned: { label: "Orphaned" }, idle: { label: "Idle" }, in_use: { label: "In use" }, managed: { label: "Managed" }, unknown: { label: "Unknown" } } },
} as unknown as Meta;

describe("FilterBar", () => {
  it("picking an account filters by it and goes back to page 1", () => {
    const onChange = vi.fn();
    render(<FilterBar meta={meta} filters={{ ...EMPTY, page: 4 }} onChange={onChange} total={10} />);
    fireEvent.click(screen.getByRole("button", { name: /Account/ }));
    fireEvent.click(screen.getByLabelText("prd"));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ account: ["333333333333"], page: 1 }));
  });

  it("reset clears every filter but keeps the sort", () => {
    const onChange = vi.fn();
    const filters = { ...EMPTY, status: ["orphaned"], q: "web", sort: "name" };
    render(<FilterBar meta={meta} filters={filters} onChange={onChange} total={1} />);
    fireEvent.click(screen.getByRole("button", { name: "Reset filters" }));
    expect(onChange).toHaveBeenLastCalledWith({ ...EMPTY, sort: "name" });
  });

  it("shows no reset button when nothing is filtered", () => {
    render(<FilterBar meta={meta} filters={EMPTY} onChange={() => {}} total={5} />);
    expect(screen.queryByRole("button", { name: "Reset filters" })).toBeNull();
  });

  it("a reset during typing wins over the half-typed search", () => {
    vi.useFakeTimers();
    try {
      const onChange = vi.fn();
      const filters = { ...EMPTY, status: ["orphaned"] };
      const { rerender } = render(<FilterBar meta={meta} filters={filters} onChange={onChange} total={1} />);
      fireEvent.change(screen.getByLabelText("Search name or ID"), { target: { value: "web" } });
      rerender(<FilterBar meta={meta} filters={{ ...EMPTY }} onChange={onChange} total={1} />); // Reset landed
      act(() => vi.advanceTimersByTime(500));
      expect(onChange).not.toHaveBeenCalledWith(expect.objectContaining({ q: "web" }));
      expect((screen.getByLabelText("Search name or ID") as HTMLInputElement).value).toBe("");
    } finally {
      vi.useRealTimers();
    }
  });

  const byType = {
    ...meta,
    accounts: [...meta.accounts, { id: "222222222222", name: "dev", regions: ["us-east-1"] }],
    accounts_by_type: { ami: ["111111111111"], volume: ["222222222222", "333333333333"] },
  } as unknown as Meta;

  it("hides the account filter when one account owns every resource of the type", () => {
    render(<FilterBar meta={byType} type="ami" filters={EMPTY} onChange={() => {}} total={5} />);
    expect(screen.queryByRole("button", { name: /Account/ })).toBeNull();
  });

  it("offers only the accounts that have the type", () => {
    render(<FilterBar meta={byType} type="volume" filters={EMPTY} onChange={() => {}} total={5} />);
    fireEvent.click(screen.getByRole("button", { name: /Account/ }));
    expect(screen.getByLabelText("dev")).toBeTruthy();
    expect(screen.getByLabelText("prd")).toBeTruthy();
    expect(screen.queryByLabelText("tools")).toBeNull();
  });

  it("shows an unnamed account's ID once", () => {
    const unnamed = {
      ...meta,
      accounts: [...meta.accounts, { id: "444444444444", name: "444444444444", regions: ["us-east-1"] }],
    } as unknown as Meta;
    render(<FilterBar meta={unnamed} filters={EMPTY} onChange={() => {}} total={5} />);
    fireEvent.click(screen.getByRole("button", { name: /Account/ }));
    expect(screen.getAllByText("444444444444")).toHaveLength(1);
  });
});


describe("FilterBar name pattern and source filters", () => {
  it("applies a name pattern", () => {
    const onChange = vi.fn();
    render(<FilterBar meta={meta} filters={EMPTY} onChange={onChange} total={5} />);
    fireEvent.click(screen.getByRole("button", { name: /Name pattern/ }));
    fireEvent.change(screen.getByLabelText(/regular expression/), { target: { value: "^web-" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ name: "^web-", page: 1 }));
  });

  it("shows source filters as removable pills", () => {
    const onChange = vi.fn();
    const filters = { ...EMPTY, sourceAmi: "ami-0000aaaa", sourceDb: "orders-db" };
    render(<FilterBar meta={meta} filters={filters} onChange={onChange} total={2} />);
    expect(screen.getByText("Source AMI: ami-0000aaaa")).toBeTruthy();
    expect(screen.getByText("Source database: orders-db")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Remove the source AMI filter" }));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ sourceAmi: "", sourceDb: "orders-db" }));
  });
});
