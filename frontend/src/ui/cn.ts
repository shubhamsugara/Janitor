import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Join class names; when two Tailwind classes conflict, the later one wins. */
export function cn(...classes: ClassValue[]): string {
  return twMerge(clsx(classes));
}
