import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import type { Meta } from "../api";
import HowItWorks from "./HowItWorks";

const meta = {
  definitions: {
    statuses: {},
    by_type: { ami: {}, snapshot: {}, volume: {}, rds_snapshot: {} },
    rules: [],
    precedence: [],
    notes: [],
    deployments: {
      summary: "A grid of apps by account and region.",
      sources: [{ title: "Auto Scaling groups", text: "Groups tagged with `deploy-state`." }],
      run: [{ label: "Stopped", meaning: "Scaled to 0." }],
      notes: ["Columns are accounts, not env tags."],
    },
  },
} as unknown as Meta;

describe("HowItWorks", () => {
  it("explains the Deployments page from the server's definitions", () => {
    render(
      <MemoryRouter>
        <HowItWorks meta={meta} notify={() => {}} />
      </MemoryRouter>,
    );
    expect(screen.getByText("A grid of apps by account and region.")).toBeTruthy();
    expect(screen.getByText("Auto Scaling groups")).toBeTruthy();
    expect(screen.getByText("deploy-state").tagName).toBe("CODE");
    expect(screen.getByText("Scaled to 0.")).toBeTruthy();
    expect(screen.getByText("Columns are accounts, not env tags.")).toBeTruthy();
  });
});
