import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Meta, Resource } from "../api";
import ResourceTable from "./ResourceTable";

const meta = {
  accounts: [{ id: "111111111111", name: "tools", owns: [], regions: [] }],
  definitions: { statuses: { orphaned: { label: "Orphaned", blocks: false, meaning: "", what_to_do: "" } }, by_type: { volume: {} } },
} as unknown as Meta;

function vol(id: string): Resource {
  return {
    id, type: "volume", account: "111111111111", region: "us-east-1", name: `name-${id}`, created_at: "2026-01-01T00:00:00Z",
    size_gb: 10, state: "available", tags: {}, snapshot_ids: [], source_ami_id: null, managed_by: null, attached_instance: null,
    volume_type: "gp3", iops: 3000, throughput: 125, encrypted: true, storage_tier: null, est_monthly_cost: 0.8,
    cost_breakdown: null, status: "orphaned", status_reason: "", outcome: "pass",
  } as Resource;
}

function table(onSelect = vi.fn(), onOpen = vi.fn()) {
  render(
    <ResourceTable meta={meta} type="volume" items={[vol("vol-1"), vol("vol-2")]} loading={false} sort="-created_at"
      onSort={() => {}} selected={[]} onSelect={onSelect} onOpen={onOpen} empty={<span>Nothing</span>} />,
  );
  return { onSelect, onOpen };
}

describe("ResourceTable", () => {
  it("select-all selects every row on the page", () => {
    const { onSelect } = table();
    fireEvent.click(screen.getByLabelText("Select all on this page"));
    expect(onSelect.mock.calls[0][0].map((r: Resource) => r.id)).toEqual(["vol-1", "vol-2"]);
  });

  it("clicking a name opens its details", () => {
    const { onOpen } = table();
    fireEvent.click(screen.getByRole("button", { name: "name-vol-2" }));
    expect(onOpen).toHaveBeenCalledWith("vol-2");
  });
});
