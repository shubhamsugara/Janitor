import { describe, expect, it } from "vitest";
import { sequencer } from "./sequencer";

describe("sequencer", () => {
  it("test_only_the_newest_request_is_current", () => {
    const next = sequencer();
    const first = next();
    const second = next();
    expect(first()).toBe(false);
    expect(second()).toBe(true);
  });

  it("keeps separate sequences independent", () => {
    const a = sequencer();
    const b = sequencer();
    const fromA = a();
    b();
    expect(fromA()).toBe(true);
  });
});
