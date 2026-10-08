import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { MemoryRouter } from "react-router";
import { Layers } from "lucide-react";
import { describe, expect, it, vi } from "vitest";
import type { Meta } from "../api";
import { HelpContext, type HelpTopic } from "../help";
import { Sheet } from "../ui/sheet";
import HelpPanel from "./HelpPanel";
import { Kpi } from "./StatsHeader";
import StatusBadge from "./StatusBadge";
import TopBar from "./TopBar";

const meta = {
  provider: "mock",
  definitions: {
    statuses: {
      orphaned: { label: "Orphaned", blocks: false, meaning: "Nothing uses it and it is old.", what_to_do: "Plan its deletion." },
    },
    by_type: {},
    rules: [
      { id: "R6", title: "Among the newest in its group", outcome: "block", explanation: "Janitor keeps the 3 newest AMIs in each name group, per region." },
      { id: "W2", title: "Possible last copy", outcome: "warn", explanation: "It may be the last copy." },
    ],
  },
} as unknown as Meta;

function panel(topic: HelpTopic) {
  render(
    <MemoryRouter>
      <HelpPanel topic={topic} meta={meta} onClose={() => {}} />
    </MemoryRouter>,
  );
}

describe("HelpPanel", () => {
  it("explains a rule from the server's definitions", () => {
    panel("rule:R6");
    expect(screen.getByText("R6 · Among the newest in its group")).toBeTruthy();
    expect(screen.getByText("Blocks deletion")).toBeTruthy();
    expect(screen.getByText("Janitor keeps the 3 newest AMIs in each name group, per region.")).toBeTruthy();
  });

  it("says a warning rule asks for typed confirmation", () => {
    panel("rule:W2");
    expect(screen.getByText(/type delete/)).toBeTruthy();
  });

  it("explains a status", () => {
    panel("status:orphaned");
    expect(screen.getByText("Nothing uses it and it is old.")).toBeTruthy();
    expect(screen.getByText("Plan its deletion.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "How Janitor decides" })).toBeTruthy();
  });

  it("handles a topic it doesn't know", () => {
    panel("rule:R99");
    expect(screen.getByText(/no help for this yet/)).toBeTruthy();
  });
});

describe("Info links", () => {
  it("a stat's info link opens its topic", () => {
    const open = vi.fn();
    render(
      <HelpContext.Provider value={{ open }}>
        <Kpi label="Waste" value="$1" detail="d" icon={Layers} help="stat:waste" />
      </HelpContext.Provider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "About waste" }));
    expect(open).toHaveBeenCalledWith("stat:waste");
  });

  it("the status popover links to the status's help", async () => {
    const open = vi.fn();
    render(
      <HelpContext.Provider value={{ open }}>
        <StatusBadge meta={meta} type="ami" status="orphaned" />
      </HelpContext.Provider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Orphaned" }));
    fireEvent.click(await screen.findByRole("button", { name: "Learn more" }));
    expect(open).toHaveBeenCalledWith("status:orphaned");
  });
});

describe("Help menu", () => {
  it("offers the walkthrough", async () => {
    const onHelp = vi.fn();
    render(
      <MemoryRouter>
        <TopBar meta={meta} title="AMIs" theme="light" scanning={false} onScan={() => {}} onToggleTheme={() => {}} onHelp={onHelp} />
      </MemoryRouter>,
    );
    const trigger = screen.getByRole("button", { name: /Help/ });
    fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false });
    fireEvent.click(await screen.findByText("Replay walkthrough"));
    expect(onHelp).toHaveBeenCalledWith("tour");
  });
});

describe("Help over the drawer", () => {
  function Both() {
    const [topic, setTopic] = useState<HelpTopic | null>(null);
    return (
      <MemoryRouter>
        <Sheet open onClose={() => {}} title="Resource details">
          <p>Drawer body</p>
          <button type="button" onClick={() => setTopic("status:orphaned")}>
            Show help
          </button>
        </Sheet>
        {topic && <HelpPanel topic={topic} meta={meta} onClose={() => setTopic(null)} />}
      </MemoryRouter>
    );
  }

  it("closing help keeps the drawer", () => {
    render(<Both />);
    fireEvent.click(screen.getByRole("button", { name: "Show help" }));
    expect(screen.getByText("Nothing uses it and it is old.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Close help" }));
    expect(screen.queryByText("Nothing uses it and it is old.")).toBeNull();
    expect(screen.getByText("Drawer body")).toBeTruthy();
  });
});
