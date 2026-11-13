/**
 * Page Memoire (PR 36), contre le faux backend : propositions, decisions, ajout, tout oublier.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { afterEach, describe, expect, it, vi } from "vitest";

import { type FakeFact, installFakeApi } from "@/test/fakeApi";
import { renderApp } from "@/test/renderApp";

afterEach(() => {
  vi.unstubAllGlobals();
});

const NOW = "2026-11-12T12:00:00Z";

function proposal(id: string, content: string): FakeFact {
  return {
    id,
    content,
    category: "preference",
    status: "proposed",
    source_kind: "conversation",
    evidence: "je préfère réviser le soir",
    from_conversation: "c1",
    created_at: NOW,
    confirmed_at: null,
  };
}

function known(id: string, content: string): FakeFact {
  return {
    ...proposal(id, content),
    status: "verified",
    source_kind: "manual",
    evidence: null,
    from_conversation: null,
    confirmed_at: NOW,
  };
}

describe("mémoire", () => {
  it("filtre par catégorie et recherche sans tenir compte des accents", async () => {
    installFakeApi({
      loggedIn: true,
      facts: [
        known("f1", "Joue aux échecs"),
        { ...known("f2", "Étudie à METU"), category: "studies" },
        known("f3", "Préfère réviser le soir"),
      ],
    });
    renderApp("/memoire");
    const user = userEvent.setup();
    await screen.findByText("Joue aux échecs");

    const filters = within(screen.getByRole("group", { name: "Filtrer par catégorie" }));
    await user.click(filters.getByRole("button", { name: /^Études/ }));
    expect(filters.getByRole("button", { name: /^Études/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByText("Joue aux échecs")).toBeNull();
    expect(screen.getByText("Étudie à METU")).toBeVisible();

    await user.click(filters.getByRole("button", { name: /^Tout/ }));
    const search = screen.getByRole("searchbox", { name: "Rechercher dans la mémoire" });
    await user.type(search, "echecs");
    await waitFor(() => {
      expect(screen.queryByText("Étudie à METU")).toBeNull();
    });
    expect(screen.getByText("Joue aux échecs")).toBeVisible();

    await user.clear(search);
    await user.type(search, "introuvable");
    expect(await screen.findByText("Aucun souvenir ne correspond.")).toBeVisible();
  });

  it("ajoute les souvenirs proches par le sens sous les résultats exacts", async () => {
    const state = installFakeApi({
      loggedIn: true,
      facts: [known("f1", "Mon chat s'appelle Mochi"), known("f2", "Mochi adore les croquettes"), known("f3", "Aime le jazz")],
      semantic: { animal: ["f1", "f3"], Mochi: ["f1", "f2"] },
    });
    renderApp("/memoire");
    const user = userEvent.setup();
    await screen.findByText("Aime le jazz");
    const search = screen.getByRole("searchbox", { name: "Rechercher dans la mémoire" });

    // Aucun mot commun : seule la recherche du serveur trouve, dans sa section.
    await user.type(search, "animal");
    const related = await screen.findByRole("region", { name: "Proches par le sens" });
    expect(within(related).getByText("Mon chat s'appelle Mochi")).toBeVisible();
    expect(within(related).getByText("Aime le jazz")).toBeVisible();
    expect(screen.queryByText("Aucun souvenir ne correspond.")).toBeNull();

    // Les résultats exacts ne sont jamais répétés dans la section.
    await user.clear(search);
    await user.type(search, "Mochi");
    const searches = state.requests.filter((r) => r.path === "/api/v1/memory/search").length;
    await waitFor(() => {
      expect(state.requests.filter((r) => r.path === "/api/v1/memory/search").length).toBe(searches + 1);
    });
    await new Promise((resolve) => setTimeout(resolve, 100)); // reponse affichee
    expect(screen.queryByRole("region", { name: "Proches par le sens" })).toBeNull();
    expect(screen.getAllByText("Mon chat s'appelle Mochi")).toHaveLength(1);

    // Une ou deux lettres : pas de requête au serveur.
    const before = state.requests.filter((r) => r.path === "/api/v1/memory/search").length;
    await user.clear(search);
    await user.type(search, "ja");
    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(state.requests.filter((r) => r.path === "/api/v1/memory/search").length).toBe(before);
  });

  it("supprime un souvenir depuis son édition, après confirmation", async () => {
    const state = installFakeApi({ loggedIn: true, facts: [known("f1", "Joue aux échecs")] });
    renderApp("/memoire");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Modifier : Joue aux échecs" }));
    await user.click(screen.getByRole("button", { name: "Supprimer : Joue aux échecs" }));
    await user.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Supprimer" }));

    await waitFor(() => {
      expect(state.facts).toEqual([]);
    });
  });

  it("n'affiche les filtres qu'à partir de deux catégories, sans compteur répété", async () => {
    installFakeApi({ loggedIn: true, facts: [known("f1", "Joue aux échecs"), known("f2", "Aime le thé")] });
    renderApp("/memoire");
    await screen.findByText("Joue aux échecs");

    expect(screen.queryByRole("group", { name: "Filtrer par catégorie" })).toBeNull();
    expect(screen.getByRole("heading", { name: "Mémoire", level: 1 })).toBeVisible();
  });

  it("replie une catégorie", async () => {
    installFakeApi({ loggedIn: true, facts: [known("f1", "Joue aux échecs")] });
    renderApp("/memoire");
    const user = userEvent.setup();
    const header = await screen.findByRole("button", { name: /^Préférences/, expanded: true });

    await user.click(header);

    expect(header).toHaveAttribute("aria-expanded", "false");
  });

  it("signale les propositions en attente depuis le chat", async () => {
    installFakeApi({
      loggedIn: true,
      facts: [proposal("f1", "Préfère réviser le soir")],
    });
    renderApp("/");

    const chip = await screen.findByRole("link", {
      name: "1 souvenir à confirmer",
    });
    await userEvent.setup().click(chip);

    expect(await screen.findByRole("heading", { name: "Mémoire", level: 1 })).toBeVisible();
    expect(screen.queryByRole("link", { name: /souvenir à confirmer/ })).toBeNull();
  });

  it("confirme une proposition, qui passe dans ce que Lorakus sait", async () => {
    const state = installFakeApi({
      loggedIn: true,
      facts: [proposal("f1", "Préfère réviser le soir")],
    });
    renderApp("/memoire");
    const user = userEvent.setup();

    const card = (await screen.findByText("Préfère réviser le soir")).closest("li") as HTMLElement;
    expect(within(card).getByText(/Tu as dit : « je préfère réviser le soir »/)).toBeVisible();
    await user.click(within(card).getByRole("button", { name: "Confirmer" }));

    await waitFor(() => {
      expect(state.facts[0]?.status).toBe("verified");
    });
    await waitFor(() => {
      expect(screen.queryByRole("heading", { name: /À confirmer/ })).toBeNull();
    });
    expect(
      screen.getByRole("button", {
        name: "Modifier : Préfère réviser le soir",
      }),
    ).toBeVisible();
  });

  it("corrige une proposition avant de la confirmer", async () => {
    const state = installFakeApi({
      loggedIn: true,
      facts: [proposal("f1", "Révise le soir")],
    });
    renderApp("/memoire");
    const user = userEvent.setup();

    const card = (await screen.findByText("Révise le soir")).closest("li") as HTMLElement;
    await user.click(within(card).getByRole("button", { name: "Corriger" }));
    const field = within(card).getByLabelText("Texte du souvenir");
    await user.clear(field);
    await user.type(field, "Révise après 21 h");
    await user.click(within(card).getByRole("button", { name: "Confirmer" }));

    await waitFor(() => {
      expect(state.facts[0]).toMatchObject({
        content: "Révise après 21 h",
        status: "verified",
      });
    });
  });

  it("refuse une proposition", async () => {
    const state = installFakeApi({
      loggedIn: true,
      facts: [proposal("f1", "Adore le football")],
    });
    renderApp("/memoire");

    await userEvent.setup().click(await screen.findByRole("button", { name: "Refuser" }));

    await waitFor(() => {
      expect(state.facts).toEqual([]);
    });
  });

  it("ajoute un souvenir et signale un doublon", async () => {
    const state = installFakeApi({
      loggedIn: true,
      facts: [known("f1", "Joue aux échecs")],
    });
    renderApp("/memoire");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Ajouter un souvenir" }));
    await user.type(screen.getByLabelText("Texte du souvenir"), "joue aux échecs");
    await user.click(screen.getByRole("button", { name: "Ajouter" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Ce souvenir existe déjà.");

    await user.clear(screen.getByLabelText("Texte du souvenir"));
    await user.type(screen.getByLabelText("Texte du souvenir"), "Étudie à METU");
    await user.selectOptions(screen.getByLabelText("Catégorie"), "studies");
    await user.click(screen.getByRole("button", { name: "Ajouter" }));

    await waitFor(() => {
      expect(state.facts.map((f) => [f.content, f.category])).toContainEqual(["Étudie à METU", "studies"]);
    });
  });

  it("désactive les propositions", async () => {
    const state = installFakeApi({ loggedIn: true });
    renderApp("/memoire");

    await userEvent.setup().click(await screen.findByRole("button", { name: "Réglages de la mémoire" }));
    const toggle = await screen.findByRole("switch", {
      name: "Proposer des souvenirs après mes conversations",
    });
    await waitFor(() => {
      expect(toggle).toHaveAttribute("aria-checked", "true");
    });
    await userEvent.setup().click(toggle);

    await waitFor(() => {
      expect(state.proposalsEnabled).toBe(false);
    });
    await waitFor(() => {
      expect(toggle).toHaveAttribute("aria-checked", "false");
    });
  });

  it("demande le mot de passe avant de tout oublier quand la preuve d'identité est ancienne", async () => {
    const state = installFakeApi({
      loggedIn: true,
      reauthStale: true,
      facts: [known("f1", "Joue aux échecs")],
    });
    renderApp("/memoire");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Réglages de la mémoire" }));
    await user.click(screen.getByRole("button", { name: "Tout oublier" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Tout oublier" }));
    await user.type(await within(dialog).findByLabelText("Mot de passe"), state.password);
    await user.click(within(dialog).getByRole("button", { name: "Tout oublier" }));

    await waitFor(() => {
      expect(state.facts).toEqual([]);
    });
  });

  it("n'a pas de défaut d'accessibilité détectable", async () => {
    installFakeApi({
      loggedIn: true,
      facts: [proposal("f1", "Préfère réviser le soir"), known("f2", "Joue aux échecs")],
    });
    const { container } = renderApp("/memoire");
    await screen.findByText("Joue aux échecs");

    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((v) => `${v.id} : ${v.help}`)).toEqual([]);
  });
});
