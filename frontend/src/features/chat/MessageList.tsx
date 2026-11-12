import { useEffect, useRef, type ReactNode } from "react";

/**
 * Fil des messages. Defile vers le bas quand du contenu arrive, sauf si l'utilisateur est
 * remonte lire plus haut. role="log" : les lecteurs d'ecran annoncent les ajouts, mais pas
 * chaque morceau pendant l'ecriture (aria-busy).
 */
export function MessageList({ children, busy }: { children: ReactNode; busy: boolean }) {
  const scroller = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);

  useEffect(() => {
    const el = scroller.current;
    if (el && pinned.current) {
      el.scrollTop = el.scrollHeight;
    }
  });

  return (
    <div
      ref={scroller}
      onScroll={(e) => {
        const el = e.currentTarget;
        pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
      }}
      className="min-h-0 flex-1 overflow-y-auto"
    >
      <div role="log" aria-live="polite" aria-busy={busy} className="mx-auto max-w-3xl space-y-6 px-4 py-6 sm:px-6">
        {children}
      </div>
    </div>
  );
}
