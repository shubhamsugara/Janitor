import { describe, expect, it } from "vitest";

// Every UI source file, as text. Test files are excluded: they quote the banned words.
const sources = import.meta.glob<string>(["./**/*.{ts,tsx}", "!./**/*.test.{ts,tsx}"], {
  query: "?raw",
  import: "default",
  eager: true,
});

describe("UI copy rules (spec §12)", () => {
  it("finds the source files", () => {
    expect(Object.keys(sources).length).toBeGreaterThan(10);
  });

  it.each(Object.entries(sources))("%s has no 'successfully', 'please', or exclamation marks", (_, text) => {
    expect(text).not.toMatch(/\bsuccessfully\b|\bplease\b/i);
    expect(text).not.toMatch(/[A-Za-z.]!["'`<]/); // "Done!" or >Done!< — not code like `x!.y` or `!ok`
  });
});
