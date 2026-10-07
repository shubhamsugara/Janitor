import { render, waitFor } from "@testing-library/react";
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
});
