import type { ReactNode } from "react";
import { X } from "lucide-react";
import { Dialog as D } from "radix-ui";
import { cn } from "./cn";

interface Props {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  size?: "md" | "lg";
}

/** A centered dialog. Focus is trapped inside; Esc and the overlay close it. */
export function Dialog({ open, onClose, title, children, footer, size = "md" }: Props) {
  return (
    <D.Root open={open} onOpenChange={(next) => !next && onClose()}>
      <D.Portal>
        <D.Overlay className="animate-fade-in fixed inset-0 z-40 bg-zinc-950/40 backdrop-blur-[2px]" />
        <D.Content
          aria-describedby={undefined}
          className={cn(
            "animate-pop-in fixed top-1/2 left-1/2 z-50 flex max-h-[88vh] w-[94vw] -translate-x-1/2 -translate-y-1/2 flex-col",
            "rounded-2xl border border-line bg-card text-ink shadow-2xl",
            size === "lg" ? "max-w-3xl" : "max-w-lg",
          )}
        >
          <div className="flex items-center justify-between border-b border-line px-6 py-4">
            <D.Title className="text-base font-semibold tracking-tight">{title}</D.Title>
            <D.Close className="rounded-md p-1 text-muted hover:bg-subtle hover:text-ink" aria-label="Close dialog">
              <X className="size-4" />
            </D.Close>
          </div>
          <div className="overflow-y-auto px-6 py-5">{children}</div>
          {footer && <div className="flex justify-end gap-2 border-t border-line px-6 py-4">{footer}</div>}
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}
