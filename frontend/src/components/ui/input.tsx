import type { InputHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "h-12 w-full rounded-xl border border-line bg-surface px-4 text-base text-ink placeholder:text-ink-muted focus-visible:border-accent",
        className,
      )}
      {...props}
    />
  );
}
