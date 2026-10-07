import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Meta } from "../api";
import StatusBadge from "./StatusBadge";

const meta = {
  definitions: {
    statuses: {
      orphaned: { label: "Orphaned", blocks: false, meaning: "Nothing uses it.", what_to_do: "Check its rules." },
      in_use: { label: "In use", blocks: true, meaning: "Something uses it.", what_to_do: "Stop using it first." },
    },
    by_type: { volume: {} },
  },
} as unknown as Meta;

describe("StatusBadge", () => {
  it("doesn't promise deletion for a status that doesn't block", () => {
    render(<StatusBadge meta={meta} type="volume" status="orphaned" reason="Not attached." />);
    fireEvent.click(screen.getByText("Orphaned"));
    expect(screen.getByText("Doesn't block deletion")).toBeTruthy();
    expect(screen.queryByText("Can be deleted")).toBeNull();
    expect(screen.getByText("Not attached.")).toBeTruthy();
  });

  it("says a blocking status blocks deletion", () => {
    render(<StatusBadge meta={meta} type="volume" status="in_use" />);
    fireEvent.click(screen.getByText("In use"));
    expect(screen.getByText("Blocks deletion")).toBeTruthy();
  });
});
