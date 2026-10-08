import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { api, type Meta, type Resource } from "../api";
import Resources from "./Resources";

vi.mock("../api", () => ({
  api: { resources: vi.fn(), plan: vi.fn(), planMatching: vi.fn() },
  exportCsvUrl: () => "",
}));

const meta = {
  provider: "mock",
  owner: { account: "111111111111", regions: ["us-east-1"] },
  accounts: [{ id: "111111111111", name: "tools", regions: ["us-east-1"] }],
  definitions: {
    statuses: Object.fromEntries(["in_use", "managed", "unknown", "orphaned", "idle"].map((s) => [s, { label: s, meaning: "" }])),
    by_type: {},
    rules: [],
  },
} as unknown as Meta;

const row = (id: string) =>
  ({ id, type: "volume", account: "111111111111", region: "us-east-1", name: id, created_at: "2026-01-01T00:00:00Z", tags: {}, status: "orphaned", status_reason: "", outcome: "pass", size_gb: 1, est_monthly_cost: 0.1 }) as unknown as Resource;

let goto: (to: string) => void = () => {};
function Nav() {
  goto = useNavigate();
  return null;
}

function renderPage() {
  render(
    <MemoryRouter initialEntries={["/volumes?region=us-east-1"]}>
      <Nav />
      <Routes>
        <Route path="/volumes" element={<Resources meta={meta} notify={() => {}} type="volume" title="EBS volumes" />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(api.resources).mockResolvedValue({ items: [row("vol-1"), row("vol-2")], total: 120, stats: null, scan_id: 1 });
  vi.mocked(api.planMatching).mockResolvedValue(new Promise(() => {}) as never);
});

async function selectPage() {
  fireEvent.click(await screen.findByLabelText("Select all on this page"));
}

describe("Select all matching", () => {
  it("offers every match once the whole page is selected", async () => {
    renderPage();
    await selectPage();
    fireEvent.click(screen.getByRole("button", { name: "Select all 120 matching" }));
    expect(screen.getByText("All 120 matching selected")).toBeTruthy();
    fireEvent.click(screen.getAllByRole("button", { name: /Plan delete/ })[0]);
    await waitFor(() => expect(api.planMatching).toHaveBeenCalled());
    const [type, filter, exclude] = vi.mocked(api.planMatching).mock.calls[0];
    expect(type).toBe("volume");
    expect(filter).toMatchObject({ region: "us-east-1" });
    expect(exclude).toEqual([]);
  });

  it("unchecking a row excludes it", async () => {
    renderPage();
    await selectPage();
    fireEvent.click(screen.getByRole("button", { name: "Select all 120 matching" }));
    fireEvent.click(screen.getByLabelText("Select vol-2"));
    expect(screen.getByText("119 of 120 matching selected")).toBeTruthy();
    fireEvent.click(screen.getAllByRole("button", { name: /Plan delete/ })[0]);
    await waitFor(() => expect(api.planMatching).toHaveBeenCalled());
    expect(vi.mocked(api.planMatching).mock.calls.at(-1)?.[2]).toEqual(["vol-2"]);
  });

  it("changing a filter clears the all-matching selection, not just the mode", async () => {
    renderPage();
    await selectPage();
    fireEvent.click(screen.getByRole("button", { name: "Select all 120 matching" }));
    fireEvent.click(screen.getByLabelText("Select vol-2"));
    goto("/volumes?region=eu-west-1");
    await waitFor(() => expect(screen.queryByText(/selected/)).toBeNull());
  });

  it("clear leaves all-matching mode", async () => {
    renderPage();
    await selectPage();
    fireEvent.click(screen.getByRole("button", { name: "Select all 120 matching" }));
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.queryByText(/selected/)).toBeNull();
  });

  it("doesn't offer it when the page holds every match", async () => {
    vi.mocked(api.resources).mockResolvedValue({ items: [row("vol-1"), row("vol-2")], total: 2, stats: null, scan_id: 1 });
    renderPage();
    await selectPage();
    expect(screen.queryByRole("button", { name: /Select all .* matching/ })).toBeNull();
  });
});
