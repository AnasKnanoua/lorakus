import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Assemble des classes Tailwind ; en cas de conflit, la derniere l'emporte. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
