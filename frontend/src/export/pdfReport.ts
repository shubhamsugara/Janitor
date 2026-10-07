import type { ExportData, Meta, ResourceType, Status } from "../api";
import { accountName, formatGiB, formatUsd } from "../format";

export interface Report {
  filename: string;
  title: string;
  lines: string[];
  columns: string[];
  rows: string[][];
  note: string | null;
}

const COLUMNS: [string, string][] = [
  ["name", "Name"],
  ["id", "ID"],
  ["status", "Status"],
  ["delete_check", "Delete check"],
  ["account_name", "Account"],
  ["region", "Region"],
  ["created_at", "Created"],
  ["size_gib", "Size (GiB)"],
  ["est_monthly_usd", "Est. $/month"],
];

function cell(value: string | number | null | undefined, key: string, meta: Meta): string {
  if (value === null || value === undefined) return "";
  if (key === "status") return meta.definitions.statuses[value as Status]?.label ?? String(value);
  if (key === "delete_check") return value === "block" ? "Blocked" : value === "warn" ? "Review" : "Deletable";
  if (key === "created_at") return String(value).slice(0, 10);
  if (key === "est_monthly_usd") return Number(value).toFixed(2);
  return String(value);
}

/** Everything the PDF shows, as plain data, so it can be tested without drawing anything. */
export function buildReport(data: ExportData, meta: Meta, type: ResourceType, title: string): Report {
  const filters = Object.entries(data.filters)
    .filter(([key]) => key !== "type")
    .map(([key, value]) => `${key}=${key === "account" ? value.split(",").map((a) => accountName(meta, a)).join(",") : value}`);
  const s = data.stats;
  return {
    filename: `janitor-${type}-${data.generated_at.slice(0, 10).replaceAll("-", "")}.pdf`,
    title: `Janitor · ${title}`,
    lines: [
      `Data source: ${data.provider === "mock" ? "Mock data" : "AWS (read-only)"} · Generated ${data.generated_at}`,
      `Filters: ${filters.length ? filters.join("; ") : "none"}`,
      `${s.total.toLocaleString()} matching · ${s.orphaned.toLocaleString()} orphaned (${formatGiB(s.orphaned_gib)}, ${formatUsd(s.orphaned_usd)}) · ${s.blocked.toLocaleString()} blocked`,
      "Costs are monthly estimates from the AWS price list. Nothing was deleted.",
    ],
    columns: COLUMNS.map(([, label]) => label),
    rows: data.items.map((item) => COLUMNS.map(([key]) => cell(item[key], key, meta))),
    note: data.truncated
      ? `Showing ${data.items.length.toLocaleString()} of ${data.total.toLocaleString()}; export CSV for all rows.`
      : null,
  };
}

/** Draw the report and download it. jsPDF loads only now, so it doesn't grow the main bundle. */
export async function downloadPdf(report: Report): Promise<void> {
  const [{ jsPDF }, { autoTable }] = await Promise.all([import("jspdf"), import("jspdf-autotable")]);
  const doc = new jsPDF({ orientation: "landscape", unit: "pt", format: "a4" });
  doc.setFontSize(16);
  doc.text(report.title, 40, 40);
  doc.setFontSize(9);
  report.lines.forEach((line, i) => doc.text(line, 40, 60 + i * 13));
  autoTable(doc, {
    head: [report.columns],
    body: report.rows,
    startY: 60 + report.lines.length * 13 + 8,
    styles: { fontSize: 7 },
    headStyles: { fillColor: [35, 47, 62] },
  });
  if (report.note) doc.text(report.note, 40, doc.internal.pageSize.getHeight() - 20);
  doc.save(report.filename);
}
