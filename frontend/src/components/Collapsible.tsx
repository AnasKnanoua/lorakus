import { ChevronDown } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import { cn } from "@/lib/cn";

/**
 * Section repliable : l'entete est un bouton (aria-expanded), le contenu s'ouvre en glissant
 * (grid-template-rows 0fr -> 1fr, sans mesurer la hauteur) et reste hors de la tabulation
 * quand il est ferme.
 */
export function Collapsible({
  title,
  count,
  defaultOpen = true,
  className,
  headerClassName,
  children,
}: {
  title: ReactNode;
  count?: number | undefined;
  defaultOpen?: boolean;
  className?: string;
  headerClassName?: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  return (
    <div className={className}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => {
          setOpen((value) => !value);
        }}
        className={cn(
          "group flex h-9 w-full items-center gap-2 rounded-lg text-left text-sm font-medium text-ink-faint transition-colors hover:text-ink",
          headerClassName,
        )}
      >
        <span>{title}</span>
        {count !== undefined && <span className="font-normal tabular-nums opacity-70">{count}</span>}
        <span className="flex-1" />
        <ChevronDown
          aria-hidden="true"
          className={cn("size-4 shrink-0 transition-transform duration-200", !open && "-rotate-90")}
        />
      </button>
      <div id={id} className="collapsible" data-open={open} inert={!open}>
        <div className="min-h-0">{children}</div>
      </div>
    </div>
  );
}
