import type { HTMLAttributes, ReactNode, TdHTMLAttributes, ThHTMLAttributes } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { cn } from "./cn";

interface TableProps extends HTMLAttributes<HTMLTableElement> {
  /** Page-level table whose header sticks below the top bar. A scroll wrapper would break that. */
  sticky?: boolean;
}

export function Table({ sticky, className, ...rest }: TableProps) {
  const table = <table className={cn("w-full border-separate border-spacing-0 text-sm", className)} {...rest} />;
  return sticky ? table : <div className="overflow-x-auto">{table}</div>;
}

export function THead({ children, sticky }: { children: ReactNode; sticky?: boolean }) {
  return <thead className={cn("bg-card", sticky && "sticky top-14 z-10")}>{children}</thead>;
}

/** `busy`: rows from the previous request, shown dimmed until the new ones arrive. */
export function TBody({ children, busy }: { children: ReactNode; busy?: boolean }) {
  return <tbody className={cn("transition-opacity", busy && "pointer-events-none opacity-45")}>{children}</tbody>;
}

export function Tr({ className, ...rest }: HTMLAttributes<HTMLTableRowElement>) {
  return <tr className={cn("group transition-colors", className)} {...rest} />;
}

interface ThProps extends ThHTMLAttributes<HTMLTableCellElement> {
  sort?: { active: boolean; descending: boolean; onClick: () => void };
}

export function Th({ sort, className, children, ...rest }: ThProps) {
  const Icon = !sort?.active ? ArrowUpDown : sort.descending ? ArrowDown : ArrowUp;
  return (
    <th
      aria-sort={sort?.active ? (sort.descending ? "descending" : "ascending") : undefined}
      className={cn(
        "border-b border-line px-3 py-2.5 text-left text-xs font-medium tracking-wide whitespace-nowrap text-muted uppercase",
        className,
      )}
      {...rest}
    >
      {sort ? (
        <button type="button" onClick={sort.onClick} className="inline-flex items-center gap-1 uppercase hover:text-ink">
          {children}
          <Icon className={cn("size-3.5", sort.active ? "text-ink" : "opacity-40")} aria-hidden />
        </button>
      ) : (
        children
      )}
    </th>
  );
}

export function Td({ className, ...rest }: TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn("border-b border-line px-3 py-3 align-middle group-hover:bg-subtle/60", className)} {...rest} />;
}
