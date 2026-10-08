import type { ReactNode } from "react";
import { X } from "lucide-react";
import { Dialog as D } from "radix-ui";
import { cn } from "./cn";

interface Props {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  closeLabel?: string;
  className?: string; // e.g. a narrower width, or z-40 to stack over another sheet
}

/** A drawer that slides in from the right: resource details, and help on top of them. */
export function Sheet({ open, onClose, title, children, closeLabel = "Close details", className }: Props) {
  const layer = className?.match(/(?:^|\s)(z-(?:\[\d+\]|\d+))(?=\s|$)/)?.[1] ?? "z-30";
  return (
    <D.Root open={open} onOpenChange={(next) => !next && onClose()}>
      <D.Portal>
        <D.Overlay className={cn("animate-fade-in fixed inset-0 bg-zinc-950/30", layer)} />
        <D.Content
          aria-describedby={undefined}
          className={cn(
            "animate-slide-in fixed inset-y-0 right-0 z-30 flex w-[min(980px,94vw)] flex-col border-l border-line bg-page text-ink shadow-2xl",
            className,
          )}
        >
          <div className="flex items-center justify-between gap-4 border-b border-line bg-card px-6 py-4">
            <D.Title className="min-w-0 text-[13px] font-medium tracking-wide text-muted uppercase">{title}</D.Title>
            <D.Close className="rounded-md p-1.5 text-muted hover:bg-subtle hover:text-ink" aria-label={closeLabel}>
              <X className="size-4" />
            </D.Close>
          </div>
          <div className="flex-1 overflow-y-auto p-6">{children}</div>
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}
