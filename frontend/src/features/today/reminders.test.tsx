/**
 * Rappels « À noter » de Ma journée (P5), contre le faux backend : affichés = vus, « OK »,
 * « Plus tard », « Pourquoi ? », rien quand il n'y en a pas.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { describe, expect, it } from "vitest";

import { installFakeApi, type FakeReminder, type FakeReminderWhy } from "@/test/fakeApi";
import { renderApp } from "@/test/renderApp";

const HOMEWORK: FakeReminder = {
  id: "r1",
  module: "focus",
  title: "À rendre dans 3 jours",
  body: "CSEC507 : rapport · jeudi 26 novembre 2026. Pas encore commencé.",
  url: "/today",
  created_at: "2026-11-23T05:00:00Z",
};
const EXAM: FakeReminder = { ...HOMEWORK, id: "r2", title: "À rendre demain", body: "Partiel · mardi" };

const WHY: FakeReminderWhy = {
  module: "focus",
  rule: "Sergent : une tâche à rendre dans 3 jours ou moins, sans étape terminée, donne un seul rappel.",
  facts: [
    { label: "Tâche", value: "CSEC507 : rapport", source: "Cours", measured: true },
    { label: "Durée estimée", value: "3 h", source: "Planning", measured: false },
  ],
  status: "done",
  outcome: "ignored_24h",
  created_at: "2026-11-23T05:00:00Z",
  interventions: [
    { level: 1, channel: "app", reason: "new", at: "2026-11-23T05:01:00Z", delivered: 0, failed: 0 },
    { level: 2, channel: "push", reason: "ignored_24h", at: "2026-11-24T06:00:00Z", delivered: 2, failed: 0 },
  ],
};

describe("à noter", () => {
  it("affiche les rappels en tête de la journée et les marque comme vus", async () => {
    const state = installFakeApi({ loggedIn: true, reminders: [HOMEWORK, EXAM] });
    renderApp("/today");

    const list = within(await screen.findByRole("list", { name: "À noter" }));
    const items = list.getAllByRole("listitem");
    expect(items.map((li) => li.firstElementChild?.textContent)).toEqual(["À rendre dans 3 jours", "À rendre demain"]);
    expect(list.getByText(HOMEWORK.body)).toBeVisible();
    // Affichée = vue : aucune notification ne suivra. Une seule fois par carte.
    await waitFor(() => {
      expect(state.requests.filter((r) => r.path.endsWith("/seen")).map((r) => r.path)).toEqual([
        "/api/v1/notifications/cards/r1/seen",
        "/api/v1/notifications/cards/r2/seen",
      ]);
    });
    const results = await axe.run(document.body);
    expect(results.violations).toEqual([]);
  });

  it("OK ferme la carte, Plus tard la cache", async () => {
    const state = installFakeApi({ loggedIn: true, reminders: [HOMEWORK, EXAM] });
    renderApp("/today");
    const user = userEvent.setup();

    const cards = within(await screen.findByRole("list", { name: "À noter" })).getAllByRole("listitem");
    const first = within(cards[0] as HTMLElement);
    expect(cards[0]).toHaveTextContent("CSEC507");
    await user.click(first.getByRole("button", { name: "OK" }));
    await waitFor(() => {
      expect(screen.queryByText(HOMEWORK.body)).toBeNull();
    });
    const second = within(screen.getByRole("list", { name: "À noter" }));
    await user.click(second.getByRole("button", { name: "Plus tard" }));
    await waitFor(() => {
      expect(screen.queryByRole("list", { name: "À noter" })).toBeNull();
    });
    expect(state.requests.map((r) => r.path)).toEqual(
      expect.arrayContaining(["/api/v1/notifications/cards/r1/close", "/api/v1/notifications/cards/r2/later"]),
    );
    // Une carte n'est marquée vue qu'une fois, même relue après chaque réponse.
    expect(state.requests.filter((r) => r.path.endsWith("/seen"))).toHaveLength(2);
  });

  it("explique un rappel : règle, faits, décisions, sans modèle de langage", async () => {
    installFakeApi({ loggedIn: true, reminders: [HOMEWORK], reminderWhy: new Map([["r1", WHY]]) });
    renderApp("/today");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Pourquoi ce rappel : À rendre dans 3 jours ?" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Pourquoi ce rappel ?" }));
    expect(await dialog.findByText(WHY.rule)).toBeVisible();
    expect(dialog.getByText("Durée estimée")).toBeVisible();
    expect(dialog.getByText(/· Planning, estimé/)).toBeVisible();
    expect(dialog.getByText(/notification, reçue par 2 appareils/)).toBeVisible();
    // Heures dans le fuseau du compte (Ankara, UTC+3), pas dans celui de l'appareil.
    expect(dialog.getByText("lundi 08:01")).toBeVisible();
    expect(dialog.getByText("mardi 09:00")).toBeVisible();
    expect(dialog.getByText("Une notification est partie ; il n'y en aura pas d'autre.")).toBeVisible();
    expect(dialog.getByText(/aucun modèle de langage/)).toBeVisible();
    const results = await axe.run(document.body);
    expect(results.violations).toEqual([]);
  });

  it("ne montre rien quand il n'y a rien à noter", async () => {
    installFakeApi({ loggedIn: true, reminders: [] });
    renderApp("/today");
    expect(await screen.findByRole("heading", { level: 1, name: "Ma journée" })).toBeVisible();
    await screen.findByRole("list", { name: "Échéances des 7 prochains jours" }).catch(() => undefined);
    expect(screen.queryByRole("list", { name: "À noter" })).toBeNull();
    expect(screen.queryByText("À noter")).toBeNull();
  });
});
