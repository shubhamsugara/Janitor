import type { ButtonHTMLAttributes } from "react";
import { LoaderCircle } from "lucide-react";
import { cn } from "./cn";

const VARIANTS = {
  primary: "bg-accent text-accent-ink hover:opacity-90 shadow-sm",
  secondary: "bg-card text-ink border border-line hover:bg-subtle shadow-card",
  ghost: "text-ink hover:bg-subtle",
  danger: "bg-red-600 text-white hover:bg-red-700 shadow-sm",
};
const SIZES = { sm: "h-8 px-3 text-[13px]", md: "h-9 px-4 text-sm", icon: "h-9 w-9 justify-center" };

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: keyof typeof VARIANTS;
  size?: keyof typeof SIZES;
  loading?: boolean;
}

export function Button({ variant = "secondary", size = "md", loading, disabled, className, children, ...rest }: ButtonProps) {
  return (
    <button
      type="button"
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        "inline-flex items-center gap-2 rounded-lg font-medium whitespace-nowrap transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-50",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...rest}
    >
      {loading && <LoaderCircle className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}
