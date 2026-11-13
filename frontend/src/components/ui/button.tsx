import { cva, type VariantProps } from "class-variance-authority";
import type { ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

/**
 * Boutons de Lorakus (docs/frontend.md, « Système de design »).
 * Une seule action principale (primary, jade) par zone ; le reste est secondary ou quiet.
 * Hauteurs : md 40 px (formulaires), sm 32 px (actions dans une liste), icones 40 et 32 px.
 */
export const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 font-medium whitespace-nowrap transition-[background-color,color,opacity,transform] duration-150 active:scale-[0.98] disabled:pointer-events-none disabled:opacity-45 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary: "bg-accent text-accent-ink hover:brightness-110",
        secondary: "bg-raised text-ink hover:bg-hover",
        quiet: "text-ink-muted hover:bg-hover hover:text-ink",
        outline: "border border-line bg-transparent text-ink hover:bg-hover",
        danger: "bg-danger text-background hover:brightness-110",
        "danger-quiet": "text-danger hover:bg-danger-soft",
      },
      size: {
        md: "h-10 rounded-xl px-4 text-base [&_svg]:size-[18px]",
        sm: "h-8 rounded-lg px-3 text-sm [&_svg]:size-4",
        icon: "size-10 rounded-xl [&_svg]:size-5",
        "icon-sm": "size-8 rounded-lg [&_svg]:size-4",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

export function Button({ className, variant, size, type = "button", ...props }: ButtonProps) {
  return <button type={type} className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}
