import { afterEach, describe, expect, it, vi } from "vitest";
import { runScan } from "./api";

function respond(...bodies: unknown[]) {
  const fetchMock = vi.fn();
  for (const body of bodies) fetchMock.mockResolvedValueOnce({ ok: true, json: async () => body });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const scan = (status: string, notes = {}) => ({ id: 2, started_at: "", finished_at: "", provider: "aws", status, notes });

describe("runScan", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("finishes on a partial scan and reports progress", async () => {
    vi.useFakeTimers();
    respond(
      { started: true },
      { scan: scan("running"), running: true, segments: [], progress: { done: 5, failed: 0 } },
      { scan: scan("partial"), running: false, segments: [], progress: { done: 9, failed: 1 } },
    );
    const progress: number[] = [];
    const done = runScan((n) => progress.push(n));
    await vi.runAllTimersAsync();
    expect((await done)?.status).toBe("partial");
    expect(progress).toEqual([5, 9]);
  });

  it("throws the server's reason when the scan failed", async () => {
    vi.useFakeTimers();
    respond(
      { started: true },
      { scan: scan("failed", { error: "AWS session expired. Refresh your MFA session, then Scan now." }), running: false, segments: [], progress: { done: 1, failed: 1 } },
    );
    const done = runScan();
    const failure = expect(done).rejects.toThrow("Refresh your MFA session");
    await vi.runAllTimersAsync();
    await failure;
  });
});
