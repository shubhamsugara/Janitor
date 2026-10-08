import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import type { Meta } from "../api";
import Sidebar from "./Sidebar";
import TopBar from "./TopBar";

const meta = { provider: "mock" } as unknown as Meta;

describe("shell", () => {
  it("marks the current page in the sidebar", () => {
    render(
      <MemoryRouter initialEntries={["/volumes"]}>
        <Sidebar collapsed={false} onToggle={() => {}} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: /EBS volumes/ }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("link", { name: /Overview/ }).getAttribute("aria-current")).toBeNull();
  });

  it("offers the other theme and names the data source", () => {
    render(
      <MemoryRouter>
        <TopBar meta={meta} title="Overview" theme="light" scanning={false} onScan={() => {}} onToggleTheme={() => {}} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("button", { name: "Use dark mode" })).toBeTruthy();
    expect(screen.getByText("Mock data")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Scan now/ })).toBeTruthy();
  });

  it("flags a partial scan and shows scan progress", () => {
    render(
      <MemoryRouter>
        <TopBar meta={meta} title="Overview" theme="light" scanning progress={12} partial onScan={() => {}} onToggleTheme={() => {}} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: /Partial scan/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Scanning · 12 checks done/ })).toBeTruthy();
  });
});

