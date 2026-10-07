import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { applyTheme } from "../theme";
import { cn } from "./cn";
import { StatusPill } from "./pills";

describe("ui kit", () => {
  it("merges conflicting Tailwind classes, last one wins", () => {
    expect(cn("p-2 text-sm", false && "hidden", "p-4")).toBe("text-sm p-4");
  });

  it("puts the theme on <html> as a class", () => {
    applyTheme("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    applyTheme("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("shows a status as a dot and its label", () => {
    render(<StatusPill status="orphaned" label="Orphaned" />);
    expect(screen.getByText("Orphaned")).toBeTruthy();
  });
});
