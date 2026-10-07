import type { Meta, SimulateResult } from "./api";

export function formatGiB(gib: number | null | undefined): string {
  if (gib == null) return "—";
  return gib >= 1024 ? `${(gib / 1024).toFixed(1)} TiB` : `${gib.toLocaleString()} GiB`;
}

export function formatUsd(usd: number | null | undefined): string {
  if (usd == null) return "—";
  return `~$${usd.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}/month`;
}

export function formatDate(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : "—";
}

export function accountName(meta: Meta, id: string): string {
  return meta.accounts.find((a) => a.id === id)?.name ?? id;
}

export function simulationSummary(result: SimulateResult): string {
  const { count, size_gib, est_monthly_usd } = result.totals;
  let text = `Simulated: ${count} would be deleted (${formatGiB(size_gib)}, ${formatUsd(est_monthly_usd)})`;
  if (result.skipped.length) text += `, ${result.skipped.length} skipped`;
  return `${text}.`;
}
