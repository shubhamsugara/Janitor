import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { CircleCheck, CircleX, Info, X } from "lucide-react";
import type { Notify } from "../nav";
import { cn } from "./cn";

interface Toast {
  id: number;
  type: "success" | "error" | "info";
  content: string;
}

const ToastContext = createContext<Notify>(() => {});
export const useToast = () => useContext(ToastContext);

const ICONS = { success: CircleCheck, error: CircleX, info: Info };
const TONES = { success: "text-emerald-600 dark:text-emerald-400", error: "text-red-600 dark:text-red-400", info: "text-accent" };
let nextId = 1;

/** Toasts top-right. Errors stay until dismissed; others hide after 6 seconds. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const dismiss = useCallback((id: number) => setToasts((all) => all.filter((t) => t.id !== id)), []);
  const notify: Notify = useCallback(
    (type, content) => {
      const id = nextId++;
      setToasts((all) => [...all, { id, type, content }]);
      if (type !== "error") setTimeout(() => dismiss(id), 6000);
    },
    [dismiss],
  );
  const value = useMemo(() => notify, [notify]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      <ol aria-label="Notifications" className="pointer-events-none fixed top-4 right-4 z-[60] flex w-[min(420px,92vw)] flex-col gap-2">
        {toasts.map((t) => {
          const Icon = ICONS[t.type];
          return (
            <li
              key={t.id}
              role={t.type === "error" ? "alert" : "status"}
              className="animate-pop-in pointer-events-auto flex items-start gap-3 rounded-xl border border-line bg-card px-4 py-3 text-sm text-ink shadow-xl"
            >
              <Icon className={cn("mt-0.5 size-4 shrink-0", TONES[t.type])} aria-hidden />
              <span className="flex-1">{t.content}</span>
              <button type="button" onClick={() => dismiss(t.id)} className="text-muted hover:text-ink" aria-label="Dismiss notification">
                <X className="size-4" />
              </button>
            </li>
          );
        })}
      </ol>
    </ToastContext.Provider>
  );
}
