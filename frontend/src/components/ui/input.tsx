import type { InputHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

/** Champ de saisie : 44 px, texte de 16 px (pas de zoom automatique des navigateurs mobiles). */
export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "h-11 w-full rounded-xl border border-line bg-raised px-3.5 text-md text-ink transition-[border-color,box-shadow] duration-200 placeholder:text-ink-faint focus-visible:border-[color-mix(in_srgb,var(--accent)_55%,var(--line))] focus-visible:shadow-[0_0_0_4px_color-mix(in_srgb,var(--accent)_12%,transparent)] focus-visible:outline-none",
        className,
      )}
      {...props}
    />
  );
}
