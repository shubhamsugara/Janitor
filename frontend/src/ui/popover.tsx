import type { ReactNode } from "react";
import { Popover as P } from "radix-ui";
import { cn } from "./cn";

interface Props {
  trigger: ReactNode;
  children: ReactNode;
  align?: "start" | "center" | "end";
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  className?: string;
}

/** `trigger` must be a single element that accepts a ref (a button). */
export function Popover({ trigger, children, align = "start", open, onOpenChange, className }: Props) {
  return (
    <P.Root open={open} onOpenChange={onOpenChange}>
      <P.Trigger asChild>{trigger}</P.Trigger>
      <P.Portal>
        <P.Content
          align={align}
          sideOffset={6}
          className={cn("animate-pop-in z-50 rounded-xl border border-line bg-card p-3 text-ink shadow-xl", className)}
        >
          {children}
        </P.Content>
      </P.Portal>
    </P.Root>
  );
}
