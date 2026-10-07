import type { Bucket } from "../api";
import { formatGiB, formatUsd } from "../format";

/** Horizontal bars for a few categories: label, bar, count. One series, so one color and no legend. */
export default function BarList({ title, buckets, label }: { title: string; buckets: Bucket[]; label: (key: string) => string }) {
  const max = Math.max(1, ...buckets.map((b) => b.count));
  return (
    <div className="min-w-0">
      <h3 className="mb-3 text-[13px] font-medium text-muted">{title}</h3>
      {buckets.length === 0 ? (
        <p className="text-[13px] text-muted">No data</p>
      ) : (
        <ul className="space-y-2" aria-label={title}>
          {buckets.map((b) => (
            <li key={b.key} className="group" title={`${label(b.key)}: ${b.count.toLocaleString()} · ${formatGiB(b.gib)} · ${formatUsd(b.usd)}`}>
              <div className="flex items-center justify-between gap-3 text-[13px]">
                <span className="truncate">{label(b.key)}</span>
                <span className="text-muted tabular-nums">{b.count.toLocaleString()}</span>
              </div>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-subtle">
                <div className="h-full rounded-full bg-accent transition-[width] group-hover:opacity-80" style={{ width: `${(b.count / max) * 100}%` }} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
