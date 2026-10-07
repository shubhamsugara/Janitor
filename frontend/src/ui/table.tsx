import type { HTMLAttributes, ReactNode, TdHTMLAttributes, ThHTMLAttributes } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { cn } from "./cn";

export function Table({ className, ...rest }: HTMLAttributes<HTMLTableElement>) {
  return (
    <div className="overflow-x-auto">
      <table className={cn("w-full border-separate border-spacing-0 text-sm", className)} {...rest} />
    </div>
  );
}

export function THead({ children }: { children: ReactNode }) {
  return <thead className="sticky top-0 z-10 bg-card">{children}</thead>;
}

export function TBody({ children }: { children: ReactNode }) {
  return <tbody>{children}</tbody>;
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
