import { applyMode, Mode } from "@cloudscape-design/global-styles";

export type Theme = "light" | "dark";
const KEY = "janitor:theme";

export function savedTheme(): Theme {
  try {
    return localStorage.getItem(KEY) === "dark" ? "dark" : "light";
  } catch {
    return "light"; // storage blocked (private window)
  }
}

export function applyTheme(theme: Theme): void {
  applyMode(theme === "dark" ? Mode.Dark : Mode.Light);
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // the choice just isn't remembered
  }
}
