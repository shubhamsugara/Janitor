export type Theme = "light" | "dark";
const KEY = "janitor:theme";

export function savedTheme(): Theme {
  try {
    return localStorage.getItem(KEY) === "dark" ? "dark" : "light";
  } catch {
    return "light"; // storage blocked (private window)
  }
}

/** The theme is a `dark` class on <html>; index.html sets it before first paint too. */
export function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle("dark", theme === "dark");
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // the choice just isn't remembered
  }
}
