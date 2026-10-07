import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Meta } from "../api";
import { EMPTY } from "../filters";
import FilterBar from "./FilterBar";

const meta = {
  owner: { account: "111111111111", regions: ["us-east-1"] },
  accounts: [
    { id: "111111111111", name: "tools", owns: [], regions: ["us-east-1"] },
    { id: "333333333333", name: "prd", owns: [], regions: ["us-east-1", "eu-west-1"] },
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
});
