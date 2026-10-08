import { Info } from "lucide-react";
import { useHelp, type HelpTopic } from "../help";
import { cn } from "../ui/cn";

/** A small "i" button that opens the help panel on one topic. */
export default function InfoLink({ topic, label, className }: { topic: HelpTopic; label: string; className?: string }) {
  const { open } = useHelp();
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        open(topic);
      }}
      aria-label={`About ${label}`}
      className={cn("inline-flex rounded p-0.5 align-middle text-muted hover:text-accent", className)}
    >
      <Info className="size-3.5" aria-hidden />
    </button>
  );
}
