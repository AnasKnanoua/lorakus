import { useEffect, useRef, useState } from "react";

import { prefersReducedMotion } from "./motion";

/**
 * Affichage fluide d'un texte qui arrive par morceaux (reponse en cours d'ecriture).
 *
 * Le serveur envoie des morceaux irreguliers : les afficher tels quels fait sauter le texte
 * par paquets. Ici, le texte visible rattrape le texte recu a chaque image (requestAnimationFrame),
 * d'autant plus vite que le retard est grand : l'ecriture parait continue sans jamais prendre
 * plus d'une fraction de seconde de retard.
 *
 * - Inactif (reponse terminee, ou historique) : le texte complet, tout de suite.
 * - « Reduire les animations » : le texte recu, sans lissage.
 */
export function useSmoothText(target: string, active: boolean): string {
  const [shown, setShown] = useState(active ? "" : target);
  const latest = useRef(target);
  useEffect(() => {
    latest.current = target;
  }, [target]);

  useEffect(() => {
    if (!active || prefersReducedMotion()) {
      return undefined;
    }
    let frame = requestAnimationFrame(function tick() {
      setShown((current) => {
        const goal = latest.current;
        // Texte remplace (et non prolonge) : on repart du nouveau texte, sans animation.
        if (!goal.startsWith(current)) {
          return goal;
        }
        return goal.slice(0, nextLength(current.length, goal.length));
      });
      frame = requestAnimationFrame(tick);
    });
    return () => {
      cancelAnimationFrame(frame);
    };
  }, [active]);

  if (!active || prefersReducedMotion()) {
    return target;
  }
  return shown;
}

/** Caracteres a afficher a l'image suivante : au moins 2, et 15 % du retard (rattrapage). */
export function nextLength(shown: number, target: number): number {
  if (shown >= target) {
    return target;
  }
  const backlog = target - shown;
  return Math.min(target, shown + Math.max(2, Math.ceil(backlog * 0.15)));
}
