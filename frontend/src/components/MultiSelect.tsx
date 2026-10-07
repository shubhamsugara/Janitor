import { useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "../ui/cn";
import { Popover } from "../ui/popover";

export interface Option {
  value: string;
  label: ReactNode;
  text: string; // plain text for the label and search
}

interface Props {
  label: string;
  options: Option[];
  value: string[];
  onChange: (value: string[]) => void;
}

/** A filter pill that opens a checklist. Values are ORed; an empty list means "any". */
export default function MultiSelect({ label, options, value, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const chosen = options.filter((o) => value.includes(o.value));
  const summary = chosen.length === 0 ? null : chosen.length === 1 ? chosen[0].text : `${chosen.length} selected`;
  const toggle = (v: string) => onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v]);
  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      className="w-60 p-1.5"
      trigger={
        <button
          type="button"
          className={cn(
            "inline-flex h-9 items-center gap-1.5 rounded-lg border px-3 text-[13px] font-medium transition-colors",
            summary ? "border-accent/40 bg-accent-soft text-accent" : "border-dashed border-line bg-card text-ink hover:bg-subtle",
          )}
        >
          <span>
            {label}
            {summary && <span className="font-normal">: {summary}</span>}
          </span>
          <ChevronDown className="size-3.5 opacity-60" aria-hidden />
        </button>
      }
    >
      <ul className="max-h-72 overflow-y-auto">
        {options.map((o) => (
          <li key={o.value}>
            <label className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] hover:bg-subtle">
              <input
                type="checkbox"
                className="size-4 accent-[var(--accent)]"
                checked={value.includes(o.value)}
                onChange={() => toggle(o.value)}
                aria-label={o.text}
              />
              {o.label}
            </label>
          </li>
        ))}
      </ul>
      {value.length > 0 && (
        <button type="button" onClick={() => onChange([])} className="mt-1 w-full rounded-lg px-2.5 py-1.5 text-left text-[13px] text-muted hover:bg-subtle hover:text-ink">
          Clear {label.toLowerCase()}
        </button>
      )}
    </Popover>
  );
}
