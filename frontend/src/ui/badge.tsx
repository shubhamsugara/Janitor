import type { ReactNode } from "react";
import { cn } from "./cn";

const TONES = {
  neutral: "bg-subtle text-muted",
  accent: "bg-accent-soft text-accent",
  success: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
  warning: "bg-amber-500/10 text-amber-700 dark:text-amber-400",
  danger: "bg-red-500/10 text-red-700 dark:text-red-400",
};

export function Badge({ tone = "neutral", className, children }: { tone?: keyof typeof TONES; className?: string; children: ReactNode }) {
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium", TONES[tone], className)}>
      {children}
    </span>
  );
}
