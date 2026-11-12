import { cn } from "@/lib/cn";

/**
 * Monogramme de Lorakus : un L dans un carre arrondi vert-de-gris. Il « respire » tant que
 * l'assistant ecrit (seul mouvement de l'interface, coupe si le systeme reduit les animations).
 */
export function Monogram({ writing = false, className }: { writing?: boolean; className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      aria-hidden="true"
      className={cn("size-7 shrink-0", writing && "monogram-writing", className)}
    >
      <rect width="32" height="32" rx="9" fill="var(--accent)" />
      <path d="M11 8.5h3.6v12.2H22V24H11z" fill="var(--accent-ink)" />
    </svg>
  );
}
