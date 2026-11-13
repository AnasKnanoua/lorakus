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
    expect(await screen.findByText("Aucune proposition en attente.")).toBeVisible();
    expect(
      screen.getByRole("button", {
        name: "Supprimer : Préfère réviser le soir",
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

    await user.type(await screen.findByLabelText("Texte du souvenir"), "joue aux échecs");
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

    await user.click(await screen.findByRole("button", { name: "Tout oublier" }));
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
