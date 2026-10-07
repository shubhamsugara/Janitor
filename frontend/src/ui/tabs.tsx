import type { ReactNode } from "react";
import { Tabs as T } from "radix-ui";

export interface TabItem {
  id: string;
  label: ReactNode;
  content: ReactNode;
}

export function Tabs({ tabs, value, onChange }: { tabs: TabItem[]; value: string; onChange: (id: string) => void }) {
  return (
    <T.Root value={value} onValueChange={onChange}>
      <T.List className="inline-flex gap-1 rounded-lg bg-subtle p-1">
        {tabs.map((t) => (
          <T.Trigger
            key={t.id}
            value={t.id}
            className="rounded-md px-3 py-1.5 text-[13px] font-medium text-muted transition-colors hover:text-ink data-[state=active]:bg-card data-[state=active]:text-ink data-[state=active]:shadow-card"
          >
            {t.label}
          </T.Trigger>
        ))}
      </T.List>
      {tabs.map((t) => (
        <T.Content key={t.id} value={t.id} className="mt-4 focus-visible:outline-none">
          {t.content}
        </T.Content>
      ))}
    </T.Root>
  );
}
