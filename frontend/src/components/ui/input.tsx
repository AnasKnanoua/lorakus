import type { InputHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "h-12 w-full rounded-xl border border-line bg-raised px-4 text-base text-ink transition-[border-color,box-shadow] duration-200 placeholder:text-ink-faint focus-visible:border-[color-mix(in_srgb,var(--accent)_55%,var(--line))] focus-visible:shadow-[0_0_0_4px_color-mix(in_srgb,var(--accent)_12%,transparent)] focus-visible:outline-none",
        className,
      )}
      {...props}
    />
  );
}
