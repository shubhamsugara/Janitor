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
      terms: [
        { term: "Column", definition: "An AWS account and region." },
        { term: "EC2 deployment", definition: "An Auto Scaling group with the `deploy-state` tag." },
      ],
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
    expect(screen.getByText("Column")).toBeTruthy();
    expect(screen.getByText("An AWS account and region.")).toBeTruthy();
    expect(screen.getByText("deploy-state").tagName).toBe("CODE");
  });
});
