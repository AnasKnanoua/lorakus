/**
 * Mouvement de l'interface (docs/frontend.md, « Mouvement »).
 *
 * withViewTransition : applique un changement d'etat dans une View Transition, pour que les
 * elements nommes (view-transition-name) glissent vers leur nouvelle place au lieu de sauter.
 * Sans prise en charge du navigateur, ou avec « reduire les animations », le changement est
 * applique directement.
 */
export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export async function withViewTransition(update: () => Promise<unknown>): Promise<void> {
  // Absent des navigateurs anciens, meme si les types du DOM le declarent.
  const support: Partial<Pick<Document, "startViewTransition">> = document;
  if (support.startViewTransition === undefined || prefersReducedMotion()) {
    await update();
    return;
  }
  const transition = document.startViewTransition(async () => {
    await update();
    // React applique les donnees de React Query de facon synchrone ; une image d'attente
    // garantit que le nouvel etat est peint avant la capture.
    await new Promise((resolve) => requestAnimationFrame(resolve));
  });
  await transition.finished.catch(() => undefined);
}
