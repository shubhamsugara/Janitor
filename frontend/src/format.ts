import type { Meta, SimulateResult } from "./api";

export function formatGiB(gib: number | null | undefined): string {
  if (gib == null) return "—";
  return gib >= 1024 ? `${(gib / 1024).toFixed(1)} TiB` : `${gib.toLocaleString()} GiB`;
}

export function formatUsd(usd: number | null | undefined): string {
  if (usd == null) return "—";
  return `~$${usd.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}/month`;
}

/** A unit price, e.g. "$0.03185". */
export function formatRate(rate: number): string {
  return `$${rate.toLocaleString(undefined, { maximumFractionDigits: 6 })}`;
}

/** An amount in dollars and cents, e.g. "$2,080.00". */
export function formatMoney(amount: number): string {
  return `$${amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function formatDate(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : "—";
}

export function accountName(meta: Meta, id: string): string {
  return meta.accounts.find((a) => a.id === id)?.name ?? id;
}

/** "1 resource", "2 resources". */
export function plural(count: number, singular: string, pluralForm = `${singular}s`): string {
  return `${count.toLocaleString()} ${count === 1 ? singular : pluralForm}`;
}

/** The result bar (base spec §9.5), e.g. "Simulated: 3 would be deleted (40 GiB, ~$2.00/month), 2 skipped (in use)." */
export function simulationSummary(result: SimulateResult): string {
  const { count, size_gib, est_monthly_usd } = result.totals;
  let text = `Simulated: ${count.toLocaleString()} would be deleted (${formatGiB(size_gib)}, ${formatUsd(est_monthly_usd)})`;
  if (result.skipped.length) {
    const rules = [...new Set(result.skipped.map((s) => s.rule.toLowerCase()))];
    text += `, ${result.skipped.length.toLocaleString()} skipped (${rules.join(", ")})`;
  }
  return `${text}.`;
}
