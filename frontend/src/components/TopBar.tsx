import { Moon, RefreshCw, Sun } from "lucide-react";
import { Link } from "react-router";
import type { Meta } from "../api";
import type { Theme } from "../theme";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { cn } from "../ui/cn";

interface Props {
  meta: Meta | null;
  title: string;
  theme: Theme;
  scanning: boolean;
  onScan: () => void;
  onToggleTheme: () => void;
}

export default function TopBar({ meta, title, theme, scanning, onScan, onToggleTheme }: Props) {
  const source = !meta ? "Connecting" : meta.provider === "mock" ? "Mock data" : "AWS · read-only";
  return (
    <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center justify-between gap-4 border-b border-line bg-page/80 px-8 backdrop-blur">
      <div className="flex min-w-0 items-center gap-3">
        <h1 className="truncate text-[15px] font-semibold tracking-tight">{title}</h1>
        <Link to="/how-it-works" className="hidden sm:block">
          <Badge tone={meta?.provider === "mock" ? "accent" : "success"}>
            <span className="size-1.5 rounded-full bg-current" aria-hidden />
            {source}
          </Badge>
        </Link>
      </div>
      <div className="flex items-center gap-2">
        <Button variant="primary" size="sm" onClick={onScan} disabled={scanning}>
          <RefreshCw className={cn("size-3.5", scanning && "animate-spin")} aria-hidden />
          {scanning ? "Scanning" : "Scan now"}
        </Button>
        <Button variant="ghost" size="icon" onClick={onToggleTheme} aria-label={theme === "dark" ? "Use light mode" : "Use dark mode"}>
          {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
        </Button>
      </div>
    </header>
  );
}
