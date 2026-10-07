import { Cell, Pie, PieChart, Tooltip } from "recharts";
import type { Bucket, Meta, Status } from "../api";
import { STATUS_COLORS } from "../colors";

interface Props {
  buckets: Bucket[];
  meta: Meta;
  total: number;
  size?: number;
  legend?: boolean;
}

/** Status donut with a 2px surface gap between slices and a legend that names every slice. */
export default function StatusDonut({ buckets, meta, total, size = 148, legend = true }: Props) {
  const label = (key: string) => meta.definitions.statuses[key as Status]?.label ?? key;
  const data = buckets.map((b) => ({ name: label(b.key), key: b.key, value: b.count }));
  return (
    <div className="flex items-center gap-4">
      <div className="relative shrink-0" style={{ width: size, height: size }}>
        <PieChart width={size} height={size}>
          <Pie data={data} dataKey="value" nameKey="name" innerRadius={size * 0.34} outerRadius={size / 2 - 2} stroke="var(--card)" strokeWidth={2} isAnimationActive={false}>
            {data.map((d) => (
              <Cell key={d.key} fill={STATUS_COLORS[d.key]} />
            ))}
          </Pie>
          <Tooltip
            contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, color: "var(--ink)", fontSize: 12 }}
            itemStyle={{ color: "var(--ink)" }}
          />
        </PieChart>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-xl font-semibold tracking-tight tabular-nums">{total.toLocaleString()}</span>
          <span className="text-[11px] text-muted">total</span>
        </div>
      </div>
      {legend && (
        <ul className="min-w-0 flex-1 space-y-1.5 text-[13px]">
          {data.map((d) => (
            <li key={d.key} className="flex items-center gap-2">
              <span className="size-2.5 shrink-0 rounded-full" style={{ background: STATUS_COLORS[d.key] }} aria-hidden />
              <span className="whitespace-nowrap">{d.name}</span>
              <span className="ml-auto pl-3 text-muted tabular-nums">{d.value.toLocaleString()}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
