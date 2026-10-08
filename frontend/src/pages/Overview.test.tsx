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

  const awsMeta = {
    provider: "aws",
    accounts: [
      { id: "111111111111", name: "tools" },
      { id: "222222222222", name: "dev" },
    ],
  } as unknown as Meta;
  const expired = (region: string, kind: string) => ({
    account: "222222222222",
    account_name: "dev",
    region,
    kind,
    error_kind: "expired",
    message: "AWS session expired. Refresh your MFA session, then Scan now.",
  });

  function show(data: Partial<OverviewData>) {
    vi.mocked(api.overview).mockResolvedValue({
      last_scan: { ...lastScan, status: "partial" },
      scanning: false,
      types: [],
      segments_failed: [],
      unresolved: [],
      newest_failed: null,
      ...data,
    } as OverviewData);
    render(
      <MemoryRouter>
        <Overview meta={awsMeta} notify={() => {}} />
      </MemoryRouter>,
    );
  }

  it("groups one account's failed checks into one line and says what that means", async () => {
    show({ segments_failed: [expired("us-east-1", "usage"), expired("us-west-2", "volume")] });
    const lines = await screen.findAllByText(/Refresh your MFA session/);
    expect(lines).toHaveLength(1);
    expect(lines[0].textContent).toContain("dev");
    expect(screen.getByText(/show as Unknown/)).toBeTruthy();
  });

  it("says when the newest scan failed and older data is shown", async () => {
    show({ newest_failed: { finished_at: "2026-10-02T00:00:00Z", message: "AWS session expired. Refresh your MFA session, then Scan now." } });
    expect(await screen.findByText(/The last scan failed/)).toBeTruthy();
  });

  it("explains a first scan that failed", async () => {
    show({ last_scan: null, newest_failed: { finished_at: "2026-10-02T00:00:00Z", message: "Janitor isn't allowed to call ec2:DescribeImages in tools · us-east-1. Ask for read access, then Scan now." } });
    expect(await screen.findByText(/The last scan failed/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /Run first scan/ })).toBeTruthy();
  });

  it("lists image references Janitor can't resolve", async () => {
    const ref = (id: string) => ({ account: "222222222222", region: "us-east-1", ref_type: "launch_template", ref_id: id, value: "resolve:ssm:/golden/web" });
    show({ unresolved: [ref("lt-1"), ref("lt-2"), ref("lt-3")] });
    expect(await screen.findByText(/3 launch templates pick their image through an SSM parameter/)).toBeTruthy();
  });
});

