/**
 * Page « Calendriers » (PR 45), contre le faux backend : activation, ajout (l'adresse secrète
 * ne reste pas affichée), refus lisible, synchronisation, suppression, navigation, accessibilité.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { describe, expect, it } from "vitest";

import { installFakeApi, type FakeSubscription } from "@/test/fakeApi";
import { renderApp } from "@/test/renderApp";

import { ago } from "./CalendarsScreen";

const ICAL_ADDRESS = "https://calendar.google.com/calendar/ical/a%40example.com/private-calendrier-de-test/basic.ics";

function synced(overrides: Partial<FakeSubscription> = {}): FakeSubscription {
  return {
    id: "s1",
    name: "Cours METU",
    hint: "calendar.google.com/…",
    status: "ok",
    error: null,
    entries_count: 112,
    skipped_count: 0,
    truncated: false,
    last_attempt_at: new Date(Date.now() - 5 * 60_000).toISOString(),
    last_success_at: new Date(Date.now() - 5 * 60_000).toISOString(),
    next_sync_at: new Date().toISOString(),
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

describe("calendriers", () => {
  it("écrit le temps écoulé en français", () => {
    const now = new Date("2026-11-18T12:00:00Z");
    expect(ago("2026-11-18T11:59:50Z", now)).toBe("à l'instant");
    expect(ago("2026-11-18T11:55:00Z", now)).toBe("il y a 5 min");
    expect(ago("2026-11-18T10:00:00Z", now)).toBe("il y a 2 h");
    expect(ago("2026-11-16T12:00:00Z", now)).toBe("il y a 2 jours");
  });

  it("propose d'activer le module, puis affiche la page", async () => {
    const state = installFakeApi({ loggedIn: true, calendarsEnabled: false });
    renderApp("/calendriers");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Activer" }));

    expect(await screen.findByText("Aucun calendrier pour l'instant.")).toBeVisible();
    expect(state.calendarsEnabled).toBe(true);
  });

  it("ajoute un calendrier sans jamais réafficher son adresse secrète", async () => {
    const state = installFakeApi({ loggedIn: true });
    renderApp("/calendriers");
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("Nom"), "Cours METU");
    await user.type(screen.getByLabelText("Adresse secrète au format iCal"), ICAL_ADDRESS);
    await user.click(screen.getByRole("button", { name: "Ajouter" }));

    const list = await screen.findByRole("list", { name: "Mes calendriers" });
    expect(within(list).getByText("Cours METU")).toBeVisible();
    expect(within(list).getByText(/calendar\.google\.com\/… · .*Première synchronisation en cours/)).toBeVisible();
    expect(screen.getByLabelText("Adresse secrète au format iCal")).toHaveValue("");
    expect(document.body.innerHTML).not.toContain("private-calendrier-de-test");
    expect(state.requests.find((r) => r.method === "POST")?.body).toEqual({ name: "Cours METU", url: ICAL_ADDRESS });
  });

  it("montre le refus du serveur", async () => {
    installFakeApi({ loggedIn: true });
    renderApp("/calendriers");
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("Nom"), "Ancien");
    // Le navigateur accepterait http:// pour un champ url : c'est le serveur qui refuse.
    await user.type(screen.getByLabelText("Adresse secrète au format iCal"), "http://example.org/a.ics");
    await user.click(screen.getByRole("button", { name: "Ajouter" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("l'adresse doit commencer par https://");
  });

  it("affiche l'état, synchronise et supprime", async () => {
    const state = installFakeApi({
      loggedIn: true,
      subscriptions: [
        synced(),
        synced({
          id: "s2",
          name: "Club",
          status: "error",
          error: "Le serveur a refusé la demande (code 404).",
          entries_count: 0,
          last_success_at: null,
        }),
      ],
    });
    renderApp("/calendriers");
    const user = userEvent.setup();

    expect(await screen.findByText(/112 créneaux · synchronisé il y a 5 min/)).toBeVisible();
    expect(screen.getByText("Le serveur a refusé la demande (code 404).")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Synchroniser Club maintenant" }));
    await waitFor(() => {
      expect(state.requests.some((r) => r.path === "/api/v1/calendars/subscriptions/s2/sync")).toBe(true);
    });

    await user.click(screen.getByRole("button", { name: "Supprimer Cours METU" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Supprimer « Cours METU » ?" });
    expect(dialog).toHaveTextContent("Ton calendrier d'origine n'est pas touché.");
    await user.click(within(dialog).getByRole("button", { name: "Supprimer" }));
    await waitFor(() => {
      expect(screen.queryByText("Cours METU")).toBeNull();
    });
    expect(state.subscriptions.map((s) => s.id)).toEqual(["s2"]);
  });

  it("s'ouvre depuis le groupe Outils de la barre latérale", async () => {
    installFakeApi({ loggedIn: true });
    renderApp("/");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /Outils/ }));
    await user.click(await screen.findByRole("link", { name: "Calendriers" }));

    expect(await screen.findByRole("heading", { level: 1, name: "Calendriers" })).toBeVisible();
  });

  it("n'a pas de défaut d'accessibilité détectable", async () => {
    installFakeApi({ loggedIn: true, subscriptions: [synced()] });
    const { container } = renderApp("/calendriers");
    await screen.findByRole("list", { name: "Mes calendriers" });

    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations.map((v) => `${v.id} : ${v.help}`)).toEqual([]);
  });
});
