import { ChevronDown } from "lucide-react";
import { DropdownMenu as M } from "radix-ui";
import { Button } from "./button";

interface Props {
  label: string;
  items: { id: string; label: string; description?: string }[];
  onSelect: (id: string) => void;
  loading?: boolean;
}

export function Menu({ label, items, onSelect, loading }: Props) {
  return (
    <M.Root>
      <M.Trigger asChild>
        <Button loading={loading}>
          {label}
          <ChevronDown className="size-4 text-muted" aria-hidden />
        </Button>
      </M.Trigger>
      <M.Portal>
        <M.Content align="end" sideOffset={6} className="animate-pop-in z-50 min-w-56 rounded-xl border border-line bg-card p-1 text-ink shadow-xl">
          {items.map((item) => (
            <M.Item
              key={item.id}
              onSelect={() => onSelect(item.id)}
              className="cursor-pointer rounded-lg px-3 py-2 text-sm outline-none data-[highlighted]:bg-subtle"
            >
              <div className="font-medium">{item.label}</div>
              {item.description && <div className="text-xs text-muted">{item.description}</div>}
            </M.Item>
          ))}
        </M.Content>
      </M.Portal>
    </M.Root>
  );
}
