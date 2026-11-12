import { describe, expect, it } from "vitest";

import { type LiveTurn, withoutLiveTurn } from "./replies";

const m = (role: "user" | "assistant", content: string) => ({ role, content });
const history = [m("user", "ok"), m("assistant", "Parfait.")];

describe("messages enregistres affiches a cote du tour en direct", () => {
  it("sans tour en direct, tout est affiche", () => {
    expect(withoutLiveTurn(history, null)).toEqual(history);
  });

  it("pendant l'ecriture, retire le message deja enregistre par le serveur", () => {
    const live: LiveTurn = { user: "Et demain ?", assistant: "Dem", status: "streaming" };
    expect(withoutLiveTurn([...history, m("user", "Et demain ?")], live)).toEqual(history);
  });

  it("pendant l'ecriture, ne retire pas une ancienne paire identique", () => {
    const live: LiveTurn = { user: "ok", assistant: "", status: "streaming" };
    expect(withoutLiveTurn(history, live)).toEqual(history);
  });

  it("reponse terminee, retire la paire enregistree", () => {
    const live: LiveTurn = { user: "Et demain ?", assistant: "Demain, repos.", status: "ok" };
    const saved = [...history, m("user", "Et demain ?"), m("assistant", "Demain, repos.")];
    expect(withoutLiveTurn(saved, live)).toEqual(history);
  });

  it("en cas d'erreur, la liste enregistree fait foi", () => {
    const live: LiveTurn = { user: "", assistant: "", status: "error" };
    const saved = [...history, m("user", "Et demain ?")];
    expect(withoutLiveTurn(saved, live)).toEqual(saved);
  });
});
