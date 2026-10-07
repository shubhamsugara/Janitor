import type { ReactNode } from "react";
import { X } from "lucide-react";
import { Dialog as D } from "radix-ui";

interface Props {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
}

/** A drawer that slides in from the right, for resource details. */
export function Sheet({ open, onClose, title, children }: Props) {
  return (
    <D.Root open={open} onOpenChange={(next) => !next && onClose()}>
      <D.Portal>
        <D.Overlay className="animate-fade-in fixed inset-0 z-30 bg-zinc-950/30" />
        <D.Content
          aria-describedby={undefined}
          className="animate-slide-in fixed inset-y-0 right-0 z-30 flex w-[min(980px,94vw)] flex-col border-l border-line bg-page text-ink shadow-2xl"
        >
          <div className="flex items-center justify-between gap-4 border-b border-line bg-card px-6 py-4">
            <D.Title className="min-w-0 text-[13px] font-medium tracking-wide text-muted uppercase">{title}</D.Title>
            <D.Close className="rounded-md p-1.5 text-muted hover:bg-subtle hover:text-ink" aria-label="Close details">
              <X className="size-4" />
            </D.Close>
          </div>
          <div className="flex-1 overflow-y-auto p-6">{children}</div>
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}
