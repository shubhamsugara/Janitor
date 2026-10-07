import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { api, type Meta, type OverviewData } from "../api";
import Overview from "./Overview";

vi.mock("../api", () => ({ api: { overview: vi.fn(), stats: vi.fn().mockResolvedValue(null) }, runScan: vi.fn() }));

const lastScan = { id: 1, started_at: "", finished_at: "2026-10-01T00:00:00Z", provider: "mock", status: "ok" };
const meta = { provider: "mock" } as unknown as Meta;

describe("Overview", () => {
  it("keeps checking while a scan started elsewhere is running", async () => {
    const overview = vi.mocked(api.overview);
    overview
      .mockResolvedValueOnce({ last_scan: lastScan, scanning: true, types: [] } as OverviewData)
      .mockResolvedValue({ last_scan: lastScan, scanning: false, types: [] } as OverviewData);
    render(
      <MemoryRouter>
        <Overview meta={meta} notify={() => {}} />
      </MemoryRouter>,
    );
    await waitFor(() => expect(overview).toHaveBeenCalledTimes(2), { timeout: 3000 });
  });

  it("a type without a breakdown says so instead of loading forever", async () => {
    vi.mocked(api.overview).mockResolvedValue({ last_scan: lastScan, scanning: false, types: [] } as OverviewData);
    const { container } = render(
      <MemoryRouter>
        <Overview meta={meta} notify={() => {}} />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getAllByText("No breakdown yet").length).toBe(4));
    expect(container.querySelector(".animate-pulse")).toBeNull();
  });

  it("shows a scan that is already running when there is no scan yet", async () => {
    vi.mocked(api.overview).mockResolvedValue({ last_scan: null, scanning: true, types: [] } as unknown as OverviewData);
    render(
      <MemoryRouter>
        <Overview meta={meta} notify={() => {}} />
      </MemoryRouter>,
    );
    const button = await screen.findByRole("button", { name: /Run first scan/ });
    expect((button as HTMLButtonElement).disabled).toBe(true);
  });
});
