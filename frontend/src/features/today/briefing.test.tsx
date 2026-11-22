/**
 * Briefing (P5, scénario 3) dans Ma journée, contre le faux backend : « Demain » ou
 * « Aujourd'hui », sections, heure de préparation dans le fuseau du compte, « Lu ».
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { describe, expect, it } from "vitest";

import { emptyToday, installFakeApi, type FakePreparation } from "@/test/fakeApi";
import { renderApp } from "@/test/renderApp";

// Ma journée du fake : mercredi 18 novembre 2026, Ankara (UTC+3).
const TOMORROW: FakePreparation = {
  id: "b1",
  module: "focus",
  kind: "briefing",
  day: "2026-11-19",
  title: "Jeudi 19 novembre 2026",
  prepared_at: "2026-11-18T15:15:00Z",
  sections: [
    { heading: "Agenda", lines: ["08:40 - 10:30 · CSEC 507 · A-101"] },
    {
      heading: "Ta journée",
      lines: ["Pas encore décrite : dis-moi dans le chat quand tu travailles, et je placerai tes tâches."],
    },
    { heading: "Échéances", lines: ["Rapport CSEC507 · vendredi 20 novembre 2026 (demain)"] },
  ],
};

describe("briefing", () => {
  it("montre le briefing de demain en tête de la journée", async () => {
    installFakeApi({ loggedIn: true, today: emptyToday(), preparations: [TOMORROW] });
    renderApp("/today");

    const card = within(await screen.findByRole("article", { name: "Jeudi 19 novembre 2026" }));
    expect(card.getByText("Briefing · Demain")).toBeVisible();
    expect(card.getByRole("heading", { level: 3, name: "Agenda" })).toBeVisible();
    expect(card.getByText("08:40 - 10:30 · CSEC 507 · A-101")).toBeVisible();
    expect(card.getByText(/Pas encore décrite/)).toBeVisible();
    // 15:15 UTC = 18:15 à Ankara, le fuseau du compte (pas celui de l'appareil).
    expect(card.getByText(/^Préparé à 18:15, par des règles/)).toBeVisible();
    const results = await axe.run(document.body);
    expect(results.violations).toEqual([]);
  });

  it("dit « Aujourd'hui » le matin et « hier » pour l'heure de préparation", async () => {
    const morning = { ...TOMORROW, day: "2026-11-18", title: "Mercredi 18 novembre 2026", prepared_at: "2026-11-17T19:40:00Z" };
    installFakeApi({ loggedIn: true, today: emptyToday(), preparations: [morning] });
    renderApp("/today");
    const card = within(await screen.findByRole("article", { name: "Mercredi 18 novembre 2026" }));
    expect(card.getByText("Briefing · Aujourd'hui")).toBeVisible();
    expect(card.getByText(/^Préparé hier à 22:40/)).toBeVisible();
  });

  it("compte les jours dans le fuseau du compte, pas dans celui de l'appareil", async () => {
    // 22:30 UTC le 17 = 01:30 le 18 à Ankara : c'est aujourd'hui pour le compte.
    const night = { ...TOMORROW, prepared_at: "2026-11-17T22:30:00Z" };
    installFakeApi({ loggedIn: true, today: emptyToday(), preparations: [night] });
    renderApp("/today");
    const card = within(await screen.findByRole("article", { name: "Jeudi 19 novembre 2026" }));
    expect(card.getByText(/^Préparé à 01:30/)).toBeVisible();
  });

  it("disparaît une fois lu", async () => {
    const state = installFakeApi({ loggedIn: true, today: emptyToday(), preparations: [TOMORROW] });
    renderApp("/today");
    const user = userEvent.setup();
    const card = within(await screen.findByRole("article", { name: "Jeudi 19 novembre 2026" }));
    await user.click(card.getByRole("button", { name: "Lu" }));
    await waitFor(() => {
      expect(screen.queryByRole("article", { name: "Jeudi 19 novembre 2026" })).toBeNull();
    });
    expect(state.requests.map((r) => r.path)).toContain("/api/v1/preparations/b1/consulted");
  });

  it("ne montre rien sans briefing", async () => {
    installFakeApi({ loggedIn: true, today: emptyToday(), preparations: [] });
    renderApp("/today");
    expect(await screen.findByRole("heading", { level: 1, name: "Ma journée" })).toBeVisible();
    expect(screen.queryByText(/^Briefing ·/)).toBeNull();
  });
});
