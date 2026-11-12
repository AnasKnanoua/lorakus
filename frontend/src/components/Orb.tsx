import { cn } from "@/lib/cn";

/**
 * L'orbe, emblème de Lorakus (styles.css, .orb). « thinking » : le halo tourne et l'orbe
 * respire pendant que l'assistant prépare sa réponse. Purement décorative pour les lecteurs
 * d'écran : l'état est annoncé par le texte qui l'accompagne.
 */
export function Orb({ thinking = false, className }: { thinking?: boolean; className?: string }) {
  return (
    <span
      aria-hidden="true"
      data-state={thinking ? "thinking" : "idle"}
      className={cn("orb isolate size-6", className)}
    />
  );
}
