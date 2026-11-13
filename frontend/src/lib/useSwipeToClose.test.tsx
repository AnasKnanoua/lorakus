/** Glisser pour fermer : la sortie continue le geste au lieu de revenir en place d'abord. */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useSwipeToClose } from "./useSwipeToClose";

function Panel({ onClose }: { onClose: () => void }) {
  const swipe = useSwipeToClose(onClose);
  return (
    <div>
      <div className="scrim" data-testid="scrim" />
      <div data-testid="panel" {...swipe} />
    </div>
  );
}

function drag(panel: HTMLElement, toX: number) {
  Object.defineProperty(panel, "offsetWidth", { value: 300, configurable: true });
  fireEvent.touchStart(panel, { touches: [{ clientX: 280, clientY: 300 }] });
  fireEvent.touchMove(panel, { touches: [{ clientX: 270, clientY: 301 }] });
  fireEvent.touchMove(panel, { touches: [{ clientX: toX, clientY: 302 }] });
}

describe("glisser pour fermer", () => {
  it("ferme en gardant la position du doigt (pas de retour en arriere)", () => {
    const onClose = vi.fn();
    render(<Panel onClose={onClose} />);
    const panel = screen.getByTestId("panel");

    drag(panel, 100); // 180 px vers la gauche, plus d'un tiers de 300 px
    expect(screen.getByTestId("scrim").style.opacity).toBe("0.4");
    fireEvent.touchEnd(panel, { changedTouches: [{ clientX: 100, clientY: 302 }] });

    expect(onClose).toHaveBeenCalledOnce();
    expect(panel.style.transform).toBe("translateX(-180px)");
    expect(panel.dataset.dragging).toBe("false");
  });

  it("revient en place si le geste est trop court et lent", async () => {
    const onClose = vi.fn();
    render(<Panel onClose={onClose} />);
    const panel = screen.getByTestId("panel");

    drag(panel, 240);
    await new Promise((resolve) => setTimeout(resolve, 150)); // geste lent : pas un « coup » de doigt
    fireEvent.touchEnd(panel, { changedTouches: [{ clientX: 240, clientY: 302 }] });

    expect(onClose).not.toHaveBeenCalled();
    expect(panel.style.transform).toBe("");
    expect(screen.getByTestId("scrim").style.opacity).toBe("");
  });

  it("ignore un mouvement vertical (defilement de la liste)", () => {
    const onClose = vi.fn();
    render(<Panel onClose={onClose} />);
    const panel = screen.getByTestId("panel");

    fireEvent.touchStart(panel, { touches: [{ clientX: 200, clientY: 100 }] });
    fireEvent.touchMove(panel, { touches: [{ clientX: 150, clientY: 400 }] });
    fireEvent.touchEnd(panel, { changedTouches: [{ clientX: 150, clientY: 400 }] });

    expect(onClose).not.toHaveBeenCalled();
    expect(panel.style.transform).toBe("");
  });
});
