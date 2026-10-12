/** One color per status, shared by the charts, the diagram CSS, and the legend. */
export const STATUS_COLORS: Record<string, string> = {
  in_use: "#00802f",
  managed: "#006ce0",
  unknown: "#b38600", // #855900 failed CVD separation from orphaned red
  orphaned: "#db0000",
  idle: "#8c8c94",
};

/** Categorical series, in fixed order; the dark steps are the same hues for the dark surface.
 * Validated (dataviz validate_palette.js) against the card surface in both modes. Light slots 3-5
 * are below 3:1 contrast, so every series also carries a text label. */
export const SERIES_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"];
export const SERIES_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];
export const OTHER_COLOR = "#a1a1aa";
