import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { api, runScan, type Meta } from "./api";
import App from "./App";
import { ToastProvider } from "./ui/toast";

vi.mock("./api", () => ({
  api: {
    meta: vi.fn(),
    latestScan: vi.fn().mockResolvedValue({ scan: null, running: false }),
    audit: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  },
  runScan: vi.fn().mockResolvedValue(null),
}));

const meta = { provider: "aws", accounts: [], owner: { account: "111111111111", regions: [] } } as unknown as Meta;

describe("App", () => {
  it("reloads accounts after a scan, so newly discovered ones reach the filters", async () => {
    vi.mocked(api.meta).mockResolvedValue(meta);
    render(
      <ToastProvider>
        <MemoryRouter initialEntries={["/audit"]}>
          <App />
        </MemoryRouter>
      </ToastProvider>,
    );
    await waitFor(() => expect(api.meta).toHaveBeenCalledTimes(1));
    fireEvent.click(await screen.findByRole("button", { name: /Scan now/ }));
    await waitFor(() => expect(runScan).toHaveBeenCalled());
    await waitFor(() => expect(api.meta).toHaveBeenCalledTimes(2));
  });
});
