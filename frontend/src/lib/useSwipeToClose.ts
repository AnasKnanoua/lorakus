import { useRef, type TouchEvent } from "react";

/**
 * Glisser vers la gauche pour fermer un panneau lateral (telephone). Le panneau suit le doigt ;
 * au lacher, il se ferme s'il a ete tire de plus d'un tiers de sa largeur ou d'un geste vif,
 * sinon il revient en place. Un mouvement surtout vertical (defilement) est ignore.
 */
export function useSwipeToClose(onClose: () => void) {
  const start = useRef<{ x: number; y: number; t: number } | null>(null);
  const horizontal = useRef<boolean | null>(null);
  const offset = useRef(0);

  function reset(panel: HTMLElement) {
    panel.style.transform = "";
    panel.dataset.dragging = "false";
    start.current = null;
    horizontal.current = null;
    offset.current = 0;
  }

  return {
    onTouchStart(event: TouchEvent<HTMLElement>) {
      const touch = event.touches[0];
      if (touch) start.current = { x: touch.clientX, y: touch.clientY, t: performance.now() };
    },
    onTouchMove(event: TouchEvent<HTMLElement>) {
      const touch = event.touches[0];
      if (!start.current || !touch) return;
      const dx = touch.clientX - start.current.x;
      const dy = touch.clientY - start.current.y;
      if (horizontal.current === null && Math.abs(dx) + Math.abs(dy) > 8) {
        horizontal.current = Math.abs(dx) > Math.abs(dy);
      }
      if (!horizontal.current) return;
      offset.current = Math.min(0, dx);
      event.currentTarget.dataset.dragging = "true";
      event.currentTarget.style.transform = `translateX(${String(offset.current)}px)`;
    },
    onTouchEnd(event: TouchEvent<HTMLElement>) {
      const panel = event.currentTarget;
      if (!start.current || !horizontal.current) {
        reset(panel);
        return;
      }
      const elapsed = Math.max(1, performance.now() - start.current.t);
      const fast = -offset.current / elapsed > 0.5; // plus de 0,5 px par ms
      const far = -offset.current > panel.offsetWidth / 3;
      reset(panel);
      if (fast || far) onClose();
    },
  };
}

/**
 * Glisser vers la droite sur la zone principale pour ouvrir le panneau lateral (telephone), comme
 * dans Gemini. Ignore : grand ecran, geste plutot vertical, geste lent, et les zones qui defilent
 * horizontalement elles-memes (code, tableaux, filtres).
 */
export function useSwipeToOpen(onOpen: () => void) {
  const start = useRef<{ x: number; y: number; t: number } | null>(null);
  return {
    onTouchStart(event: TouchEvent<HTMLElement>) {
      const touch = event.touches[0];
      const target = event.target as Element;
      const ignored = target.closest("pre, table, input, textarea, [data-swipe-ignore]") !== null;
      const wide = window.matchMedia("(min-width: 1024px)").matches;
      start.current = touch && !ignored && !wide ? { x: touch.clientX, y: touch.clientY, t: performance.now() } : null;
    },
    onTouchEnd(event: TouchEvent<HTMLElement>) {
      const touch = event.changedTouches[0];
      const from = start.current;
      start.current = null;
      if (!from || !touch) return;
      const dx = touch.clientX - from.x;
      const dy = Math.abs(touch.clientY - from.y);
      if (dx > 64 && dy < dx * 0.6 && performance.now() - from.t < 700) onOpen();
    },
  };
}
