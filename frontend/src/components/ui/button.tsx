import { cva, type VariantProps } from "class-variance-authority";
import type { ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 font-medium transition-[background-color,color,transform,opacity] duration-150 active:scale-[0.97] disabled:pointer-events-none disabled:opacity-45 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary: "bg-accent text-accent-ink hover:brightness-110",
        quiet: "text-ink-muted hover:bg-hover hover:text-ink",
        outline: "border border-line bg-raised text-ink hover:bg-hover",
        danger: "bg-danger text-background hover:brightness-110",
      },
      size: {
        md: "h-11 rounded-xl px-5 text-[0.9375rem] [&_svg]:size-[18px]",
        sm: "h-9 rounded-lg px-3 text-sm [&_svg]:size-4",
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
