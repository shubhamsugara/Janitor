import { BookOpen, Camera, Database, Disc3, HardDrive, LayoutDashboard, PanelLeftClose, PanelLeftOpen, ScrollText, Sparkles, type LucideIcon } from "lucide-react";
import { NavLink } from "react-router";
import type { ResourceType } from "../api";
import { TYPE_PAGES } from "../nav";
import { cn } from "../ui/cn";

const TYPE_ICONS: Record<ResourceType, LucideIcon> = { ami: Disc3, snapshot: Camera, volume: HardDrive, rds_snapshot: Database };

function Item({ to, icon: Icon, label, collapsed }: { to: string; icon: LucideIcon; label: string; collapsed: boolean }) {
  return (
    <NavLink
      to={to}
      end={to === "/"}
      title={collapsed ? label : undefined}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-3 rounded-lg px-3 py-2 text-[13px] font-medium transition-colors",
          isActive ? "bg-accent-soft text-accent" : "text-muted hover:bg-subtle hover:text-ink",
          collapsed && "justify-center px-0",
        )
      }
    >
      <Icon className="size-4 shrink-0" aria-hidden />
      {collapsed ? <span className="sr-only">{label}</span> : label}
    </NavLink>
  );
}

function Section({ label, collapsed }: { label: string; collapsed: boolean }) {
  if (collapsed) return <div className="mx-3 my-3 border-t border-line" />;
  return <div className="px-3 pt-5 pb-1.5 text-[11px] font-semibold tracking-wider text-muted uppercase">{label}</div>;
}

export default function Sidebar({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  return (
    <aside className={cn("flex h-full shrink-0 flex-col border-r border-line bg-card transition-[width]", collapsed ? "w-16" : "w-60")}>
      <div className={cn("flex h-14 items-center gap-2.5 border-b border-line px-4", collapsed && "justify-center px-0")}>
        <div className="flex size-7 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-violet-500 text-white shadow-sm">
          <Sparkles className="size-4" aria-hidden />
        </div>
        {!collapsed && <span className="text-[15px] font-semibold tracking-tight">Janitor</span>}
      </div>
      <nav aria-label="Main" className="flex-1 overflow-y-auto px-2 py-3">
        <Item to="/" icon={LayoutDashboard} label="Overview" collapsed={collapsed} />
        <Section label="Resources" collapsed={collapsed} />
        {TYPE_PAGES.map((p) => (
          <Item key={p.type} to={p.path} icon={TYPE_ICONS[p.type]} label={p.title} collapsed={collapsed} />
        ))}
        <Section label="Activity" collapsed={collapsed} />
        <Item to="/audit" icon={ScrollText} label="Audit" collapsed={collapsed} />
        <Item to="/how-it-works" icon={BookOpen} label="How Janitor decides" collapsed={collapsed} />
      </nav>
      <button
        type="button"
        onClick={onToggle}
        className="m-2 flex items-center justify-center gap-2 rounded-lg py-2 text-[13px] text-muted hover:bg-subtle hover:text-ink"
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
      >
        {collapsed ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
        {!collapsed && "Collapse"}
      </button>
    </aside>
  );
}
