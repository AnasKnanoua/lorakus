/**
 * Cartes de confirmation et indications d'outils dans le chat (PR 38), contre le faux backend.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { afterEach, describe, expect, it, vi } from "vitest";

import { installFakeApi, type FakeAction } from "@/test/fakeApi";
import { renderApp } from "@/test/renderApp";

afterEach(() => {
  vi.unstubAllGlobals();
});

const LATER = "2099-01-01T00:00:00Z";

function card(overrides: Partial<FakeAction> = {}): FakeAction {
  return {
    kind: "card",
    tool: "assistant.remember",
    confirmation_id: "card-1",
    risk: "write",
    summary: "Retenir : « Révise le matin » (habitude)",
    expires_at: LATER,
    status: "pending",
    ...overrides,
  };
}

async function ask(actions: FakeAction[], chunks = ["Je te propose de le retenir."]) {
  const api = installFakeApi({ loggedIn: true, nextReply: { chunks, status: "ok", actions } });
  renderApp("/");
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("Message à Lorakus"), "Retiens que je révise le matin");
  await user.click(screen.getByRole("button", { name: "Envoyer" }));
  return { api, user };
}

async function findCard(name = "Action à confirmer"): Promise<HTMLElement> {
  return screen.findByRole("region", { name });
}

describe("cartes de confirmation", () => {
  it("affiche le texte de la carte et ne fait rien avant le clic", async () => {
    const { api } = await ask([card()]);

    const region = await findCard();
    expect(region).toHaveTextContent("Retenir : « Révise le matin » (habitude)");
    expect(within(region).getByRole("button", { name: "Confirmer" })).toBeVisible();
    expect(api.requests.some((r) => r.path.startsWith("/api/v1/tools/"))).toBe(false);
  });

  it("confirmer envoie la confirmation puis affiche « Confirmé », meme apres rechargement", async () => {
    const { api, user } = await ask([card()]);

    const region = await findCard();
    await user.click(within(region).getByRole("button", { name: "Confirmer" }));

    expect(await within(region).findByRole("status")).toHaveTextContent("Confirmé");
    expect(api.requests.map((r) => `${r.method} ${r.path}`)).toContain(
      "POST /api/v1/tools/confirmations/card-1",
    );
    await waitFor(() => {
      expect(api.cards.get("card-1")?.status).toBe("confirmed");
    });
    expect(within(await findCard()).queryByRole("button", { name: "Confirmer" })).toBeNull();
  });

  it("refuser annule l'action", async () => {
    const { api, user } = await ask([card()]);

    const region = await findCard();
    await user.click(within(region).getByRole("button", { name: "Refuser" }));

    expect(await within(region).findByRole("status")).toHaveTextContent("Refusé");
    expect(api.requests.map((r) => r.path)).toContain("/api/v1/tools/confirmations/card-1/cancel");
  });

  it("une action sensible demande l'identite, puis s'execute", async () => {
    const forget = card({
      tool: "assistant.forget_memory",
      risk: "sensitive",
      summary: "Oublier : « Habite à Clichy »",
    });
    const { api, user } = await ask([forget], ["Je te propose de l'oublier."]);
    api.reauthStale = true;

    const region = await findCard("Action sensible à confirmer");
    await user.click(within(region).getByRole("button", { name: "Confirmer" }));
    await user.type(await within(region).findByLabelText("Mot de passe"), "mauvais");
    await user.click(within(region).getByRole("button", { name: "Confirmer mon identité" }));
    expect(await within(region).findByRole("alert")).toHaveTextContent("Mot de passe ou code incorrect.");
    expect(api.cards.get("card-1")?.status).toBe("pending");

    await user.clear(within(region).getByLabelText("Mot de passe"));
    await user.type(within(region).getByLabelText("Mot de passe"), "un mot de passe assez long");
    await user.click(within(region).getByRole("button", { name: "Confirmer mon identité" }));

    expect(await within(region).findByRole("status")).toHaveTextContent("Confirmé");
  });

  it("explique un refus du serveur sans changer la carte", async () => {
    const { api, user } = await ask([card()]);
    const region = await findCard();
    api.cards.set("card-1", { ...card(), status: "expired" }); // expiree entre-temps cote serveur

    await user.click(within(region).getByRole("button", { name: "Confirmer" }));

    expect(await within(region).findByRole("alert")).toHaveTextContent("n'est plus disponible");
  });

  it("une carte dont l'echeance est passee est marquee expiree", async () => {
    await ask([card({ expires_at: "2020-01-01T00:00:00Z" })]);

    const region = await findCard();
    expect(await within(region).findByRole("status")).toHaveTextContent("Expiré");
    expect(within(region).queryByRole("button", { name: "Confirmer" })).toBeNull();
  });

  it("affiche discretement qu'un outil de lecture a servi", async () => {
    await ask(
      [{ kind: "activity", tool: "assistant.search_memory", label: "A consulté ta mémoire", ok: true }],
      ["Tu révises le matin."],
    );

    const log = await screen.findByRole("log");
    await waitFor(() => {
      expect(log).toHaveTextContent("A consulté ta mémoire");
    });
    expect(screen.queryByRole("region", { name: "Action à confirmer" })).toBeNull();
  });

  it("le texte de la carte est affiche brut, sans balisage interprete", async () => {
    await ask([card({ summary: "Retenir : « **gras** <b>html</b> [lien](https://exemple.fr) »" })]);

    const region = await findCard();
    expect(region).toHaveTextContent("**gras** <b>html</b> [lien](https://exemple.fr)");
    expect(within(region).queryByRole("link")).toBeNull();
    expect(region.querySelector("b, strong")).toBeNull();
  });

  it("la carte n'a pas de defaut d'accessibilite detectable", async () => {
    await ask([card()]);
    const region = await findCard();
    const results = await axe.run(region, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations.map((v) => `${v.id} : ${v.help}`)).toEqual([]);
  });
});
