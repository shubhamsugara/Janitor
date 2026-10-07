/** One color per status, shared by the charts, the diagram CSS, and the legend. */
export const STATUS_COLORS: Record<string, string> = {
  in_use: "#00802f",
  managed: "#006ce0",
  unknown: "#b38600", // #855900 failed CVD separation from orphaned red
  orphaned: "#db0000",
  idle: "#8c8c94",
};
