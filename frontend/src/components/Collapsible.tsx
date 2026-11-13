import { ChevronRight } from "lucide-react";
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
          "group flex w-full items-center gap-1.5 rounded-lg py-1.5 text-left text-xs font-medium text-ink-faint transition-colors hover:text-ink",
          headerClassName,
        )}
      >
        <ChevronRight
          aria-hidden="true"
          className={cn("size-3.5 shrink-0 transition-transform duration-200", open && "rotate-90")}
        />
        <span className="flex-1">{title}</span>
        {count !== undefined && <span className="tabular-nums">{count}</span>}
      </button>
      <div id={id} className="collapsible" data-open={open} inert={!open}>
        <div className="min-h-0">{children}</div>
      </div>
    </div>
  );
}
