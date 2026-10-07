import { forwardRef, type InputHTMLAttributes } from "react";
import { cn } from "./cn";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...rest }, ref) {
  return (
    <input
      ref={ref}
      className={cn(
        "h-9 w-full rounded-lg border border-line bg-card px-3 text-sm text-ink placeholder:text-muted",
        "focus:border-accent focus:ring-4 focus:ring-ring focus:outline-none",
        className,
      )}
      {...rest}
    />
  );
});
