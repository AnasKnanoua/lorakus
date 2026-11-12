/**
 * Le texte des reponses vient d'un modele : il est rendu comme une donnee non fiable.
 */
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Markdown } from "./Markdown";

function html(text: string): HTMLElement {
  return render(<Markdown text={text} />).container;
}

describe("rendu des reponses", () => {
  it("met en forme le Markdown courant", () => {
    const view = html("**gras**, une liste :\n\n- un\n- deux\n\n| a | b |\n|---|---|\n| 1 | 2 |");
    expect(view.querySelector("strong")?.textContent).toBe("gras");
    expect(view.querySelectorAll("li")).toHaveLength(2);
    expect(view.querySelector("table")).not.toBeNull();
  });

  it("n'interprete jamais de HTML brut", () => {
    const view = html('<script>alert(1)</script><img src="x" onerror="alert(1)"><b>gras</b>');
    expect(view.querySelector("script")).toBeNull();
    expect(view.querySelector("img")).toBeNull();
    expect(view.querySelector("b")).toBeNull();
  });

  it("ne charge aucune image distante (pas de fuite par l'adresse de l'image)", () => {
    const view = html("![photo](https://exemple.com/pixel.png?donnee=secrete)");
    expect(view.querySelector("img")).toBeNull();
    expect(view.textContent).toContain("[image : photo]");
  });

  it("neutralise les liens dangereux et ouvre les autres sans referent", () => {
    const view = html("[a](javascript:alert(1)) [b](data:text/html,x) [c](https://exemple.com)");
    const links = [...view.querySelectorAll("a")];
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["https://exemple.com"]);
    expect(links[0]?.getAttribute("rel")).toBe("noopener noreferrer");
    expect(links[0]?.getAttribute("target")).toBe("_blank");
  });
});
