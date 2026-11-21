/**
 * Page « Ma journée » (PR 47 et 49), contre le faux backend : cadre du jour, ligne de temps
 * (agenda, pauses et plan proposé), heures dans le fuseau du compte, tâches à estimer,
 * retards, échéances, liens vers les modules.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { describe, expect, it } from "vitest";

import { clockTime } from "@/lib/format";
import { emptyToday, installFakeApi, type FakeToday } from "@/test/fakeApi";

import { ORGANISE_MESSAGE } from "./TodayScreen";
import { renderApp } from "@/test/renderApp";

type Task = FakeToday["overdue"][number];

function task(overrides: Partial<Task> = {}): Task {
  return {
    id: "t1",
    title: "Machine Learning : TP 2",
    due_on: "2026-11-20",
    days_left: 2,
    overdue: false,
    estimate_minutes: 180,
    priority: 2,
    module: "academic",
    ...overrides,
  };
}

const REPORT = task({ id: "t2", title: "Rapport", due_on: "2026-11-16", days_left: -2, overdue: true, module: null });
const ERRAND = task({ id: "t3", title: "Courses", due_on: null, days_left: null, estimate_minutes: null, module: null });

// 07:30 à Ankara (UTC+3). Les heures ci-dessous sont en UTC : 06:00Z = 09:00 à Ankara.
// Cadre du jour : de 8 h à 22 h à Ankara.
const FRAME: FakeToday["frame"] = {
  off: false,
  starts_at: "2026-11-18T05:00:00Z",
  ends_at: "2026-11-18T19:00:00Z",
  breaks: [],
};
const FULL = emptyToday({
  frame: FRAME,
  agenda: [
    { title: "Jour férié", location: null, all_day: true, starts_at: null, ends_at: null, module: "calendars" },
    {
      title: "Machine Learning",
      location: "B-104",
      all_day: false,
      starts_at: "2026-11-18T06:00:00Z",
      ends_at: "2026-11-18T09:00:00Z",
      module: "calendars",
    },
    {
      title: "Réveil musculaire",
      location: null,
      all_day: false,
      starts_at: "2026-11-18T03:00:00Z",
      ends_at: "2026-11-18T04:00:00Z",
      module: "calendars",
    },
    {
      title: "Petit-déjeuner",
      location: null,
      all_day: false,
      starts_at: "2026-11-18T04:00:00Z",
      ends_at: "2026-11-18T04:45:00Z",
      module: "calendars",
    },
  ],
  plan: [
    { task: REPORT, starts_at: "2026-11-18T05:00:00Z", ends_at: "2026-11-18T06:00:00Z", minutes: 60 },
    { task: task(), starts_at: "2026-11-18T09:00:00Z", ends_at: "2026-11-18T10:30:00Z", minutes: 90 },
  ],
  planned_minutes: 150,
  unplanned: [{ task: task(), minutes: 90 }],
  unestimated: [ERRAND],
  overdue: [REPORT],
  upcoming: [task()],
});

describe("ma journée", () => {
  it("écrit les heures dans le fuseau du compte, pas dans celui de l'appareil", () => {
    expect(clockTime("2026-11-18T06:00:00Z", "Europe/Istanbul")).toBe("09:00");
    expect(clockTime("2026-11-18T06:00:00Z", "America/New_York")).toBe("01:00");
    expect(clockTime("2026-11-18T21:30:00Z", "Europe/Istanbul")).toBe("00:30");
  });

  it("déroule l'agenda et le plan proposé dans l'ordre des heures", async () => {
    installFakeApi({ loggedIn: true, today: FULL });
    renderApp("/today");

    expect(await screen.findByRole("heading", { level: 1, name: "Ma journée" })).toBeVisible();
    const lines = within(await screen.findByRole("list", { name: "Déroulé de la journée" })).getAllByRole("listitem");
    expect(screen.getByText("mercredi 18 novembre")).toBeVisible();
    expect(lines.map((li) => li.textContent)).toEqual([
      "06:00 – 07:00Réveil musculaire",
      "07:00 – 07:45Petit-déjeuner",
      "08:00 – 09:00RapportProposé · 1 h · pour lundi 16 novembre (il y a 2 jours)",
      "09:00 – 12:00Machine LearningB-104",
      "12:00 – 13:30Machine Learning : TP 2Proposé · 1 h 30 · pour vendredi 20 novembre (dans 2 jours)",
    ]);
    expect(screen.getByText("Travail de 08:00 à 22:00.")).toBeVisible();
    // Avec un cadre, l'action reste là, plus discrète.
    expect(screen.getByRole("button", { name: "Organiser ma journée avec Lorakus" })).not.toHaveClass("bg-accent");
    // Un créneau déjà fini est en retrait ; celui qui est en cours (07:00 – 07:45, il est
    // 07:30) ne l'est pas. Une proposition se distingue d'un créneau de l'agenda.
    expect(lines[0]).toHaveClass("opacity-50");
    expect(lines[1]).not.toHaveClass("opacity-50");
    expect(lines[3]).not.toHaveClass("opacity-50");
    expect(lines[2]).toHaveClass("bg-accent-soft");
    expect(lines[3]).not.toHaveClass("bg-accent-soft");
    expect(within(lines[2] as HTMLElement).getByText(/Proposé/)).toHaveClass("text-danger"); // tâche en retard
    expect(within(lines[4] as HTMLElement).getByText(/Proposé/)).not.toHaveClass("text-danger");
    const wholeDay = within(screen.getByRole("list", { name: "Toute la journée" })).getAllByRole("listitem");
    expect(wholeDay.map((li) => li.textContent)).toEqual(["Jour férié"]);
    expect(screen.getByText("Travail proposé : 2 h 30. Rien n'est ajouté à ton agenda.")).toBeVisible();
    expect(screen.queryByText(/Pas de travail/)).toBeNull(); // un jour ordinaire
  });

  it("liste ce qui ne tient pas, les retards et les échéances", async () => {
    installFakeApi({ loggedIn: true, today: FULL });
    renderApp("/today");

    const waiting = within(await screen.findByRole("list", { name: "Pas de place aujourd'hui" }));
    expect(waiting.getByText("reste 1 h 30")).toBeVisible();
    const late = within(screen.getByRole("list", { name: "En retard" }));
    expect(late.getByText("Rapport")).toBeVisible();
    expect(late.getByText("lundi 16 novembre (il y a 2 jours)")).toHaveClass("text-danger");
    const coming = within(screen.getByRole("list", { name: "Échéances des 7 prochains jours" }));
    expect(coming.getByText("vendredi 20 novembre (dans 2 jours)")).not.toHaveClass("text-danger");
    // Une tâche personnelle n'est pas un lien ; celle d'un module mène à sa page.
    expect(late.queryByRole("link")).toBeNull();
    const user = userEvent.setup();
    await user.click(coming.getByRole("link", { name: "Machine Learning : TP 2, ouvrir Cours" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Cours" })).toBeVisible();
  });

  it("sans cadre, ne suppose aucune heure et propose d'en parler à Lorakus", async () => {
    installFakeApi({ loggedIn: true });
    renderApp("/today");

    expect(await screen.findByText(/Tu n'as pas encore dit quand tu travailles aujourd'hui/)).toBeVisible();
    expect(screen.getByText("Rien dans ton agenda aujourd'hui.")).toBeVisible();
    expect(screen.getByText("Aucune échéance cette semaine.")).toBeVisible();
    const organise = screen.getByRole("button", { name: "Organiser ma journée avec Lorakus" });
    expect(organise).toBeEnabled();
    expect(organise).toHaveClass("bg-accent"); // l'action principale de la page, sans cadre
    expect(screen.queryByRole("button", { name: "Effacer" })).toBeNull(); // rien à effacer
    for (const name of ["En retard", "Pas de place aujourd'hui", "À estimer"]) {
      expect(screen.queryByRole("heading", { name })).toBeNull();
    }
    expect(screen.queryByText(/Travail proposé/)).toBeNull();
  });

  it("organise la journée en ouvrant une conversation avec Lorakus", async () => {
    const api = installFakeApi({ loggedIn: true });
    renderApp("/today");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Organiser ma journée avec Lorakus" }));

    const log = await screen.findByRole("log");
    await waitFor(() => {
      expect(log).toHaveTextContent(ORGANISE_MESSAGE);
    });
    const sent = api.requests.find((r) => r.path.endsWith("/messages"));
    expect(sent?.body).toEqual({ content: "Organise ma journée." });
  });

  it("dit que la conversation n'a pas pu être créée", async () => {
    const api = installFakeApi({ loggedIn: true });
    api.failNextCreate = true;
    renderApp("/today");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Organiser ma journée avec Lorakus" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("La conversation n'a pas pu être créée.");
    expect(screen.getByRole("heading", { level: 1, name: "Ma journée" })).toBeVisible(); // on reste ici
    expect(screen.getByRole("button", { name: "Organiser ma journée avec Lorakus" })).toBeEnabled();
  });

  it("dit que la plage de travail est finie", async () => {
    installFakeApi({
      loggedIn: true,
      today: emptyToday({
        frame: { ...FRAME, ends_at: "2026-11-18T04:30:00Z" }, // finie à l'heure du calcul
        unplanned: [{ task: task(), minutes: 180 }],
        upcoming: [task()],
      }),
    });
    renderApp("/today");

    expect(await screen.findByText("Ta plage de travail est finie.")).toBeVisible();
    expect(screen.getByText("reste 3 h")).toBeVisible();
  });

  it("ne dit pas que la plage est finie tant qu'elle est ouverte", async () => {
    installFakeApi({
      loggedIn: true,
      today: emptyToday({ frame: FRAME, unplanned: [{ task: task(), minutes: 180 }] }),
    });
    renderApp("/today");

    expect(await screen.findByText("Rien de prévu aujourd'hui.")).toBeVisible();
    expect(screen.queryByText(/plage de travail est finie/)).toBeNull();
  });

  it("dit qu'une nuit de travail finit le lendemain", async () => {
    installFakeApi({
      loggedIn: true,
      today: emptyToday({ frame: { ...FRAME, starts_at: "2026-11-18T12:00:00Z", ends_at: "2026-11-19T00:30:00Z" } }),
    });
    renderApp("/today");

    expect(await screen.findByText("Travail de 15:00 à 03:30 (le lendemain).")).toBeVisible();
  });

  it("montre une erreur si la journée ne se charge pas", async () => {
    installFakeApi({ loggedIn: true, today: null });
    renderApp("/today");

    expect(await screen.findByRole("alert")).toHaveTextContent("Impossible de charger ta journée.");
  });

  it("s'ouvre depuis la barre latérale, au-dessus de la mémoire", async () => {
    installFakeApi({ loggedIn: true });
    renderApp("/");
    const user = userEvent.setup();

    const link = await screen.findByRole("link", { name: "Ma journée" });
    const memory = screen.getByRole("link", { name: "Mémoire" });
    expect(link.compareDocumentPosition(memory) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await user.click(link);

    expect(await screen.findByRole("heading", { level: 1, name: "Ma journée" })).toBeVisible();
  });

  it("montre les pauses du cadre dans le déroulé, sans les confondre avec le reste", async () => {
    installFakeApi({
      loggedIn: true,
      today: emptyToday({
        ...FULL,
        frame: {
          ...FRAME,
          breaks: [
            { kind: "sport", label: "Sport", starts_at: "2026-11-18T16:00:00Z", ends_at: "2026-11-18T17:00:00Z" },
            { kind: "meal", label: "Repas", starts_at: "2026-11-18T10:30:00Z", ends_at: "2026-11-18T10:45:00Z" },
          ],
        },
      }),
    });
    renderApp("/today");

    const lines = within(await screen.findByRole("list", { name: "Déroulé de la journée" })).getAllByRole("listitem");
    expect(lines.map((li) => li.textContent).slice(4)).toEqual([
      "12:00 – 13:30Machine Learning : TP 2Proposé · 1 h 30 · pour vendredi 20 novembre (dans 2 jours)",
      "13:30 – 13:45Repas",
      "19:00 – 20:00Sport",
    ]);
    expect(lines[5]).toHaveClass("text-ink-faint");
    expect(lines[5]).not.toHaveClass("bg-accent-soft");
  });

  it("dit qu'un jour est sans travail, avec ou sans créneaux", async () => {
    const off: FakeToday["frame"] = { off: true, starts_at: null, ends_at: null, breaks: [] };
    const state = installFakeApi({
      loggedIn: true,
      today: emptyToday({ frame: off, unplanned: [{ task: task(), minutes: 180 }] }),
    });
    const view = renderApp("/today");
    expect(await screen.findByText("Pas de travail aujourd'hui : rien n'est proposé.")).toBeVisible();
    expect(screen.getByText("Pas de travail aujourd'hui.")).toBeVisible();
    view.unmount();

    state.today = emptyToday({ frame: off, agenda: FULL.agenda });
    renderApp("/today");
    await screen.findByRole("list", { name: "Déroulé de la journée" });
    expect(screen.getByText("Pas de travail aujourd'hui : rien n'est proposé.")).toBeVisible();
    expect(screen.queryByText("Rien de prévu aujourd'hui.")).toBeNull();
  });

  it("liste les tâches à estimer, jamais placées", async () => {
    installFakeApi({ loggedIn: true, today: FULL });
    renderApp("/today");

    const list = within(await screen.findByRole("list", { name: "À estimer" }));
    expect(list.getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Coursesdurée inconnue"]);
    expect(screen.getByText(/Sans durée, une tâche n'est jamais placée/)).toBeVisible();
    const planned = within(screen.getByRole("list", { name: "Déroulé de la journée" }));
    expect(planned.queryByText("Courses")).toBeNull();
  });

  it("donne l'échéance d'une tâche à estimer", async () => {
    installFakeApi({ loggedIn: true, today: emptyToday({ unestimated: [task({ estimate_minutes: null })] }) });
    renderApp("/today");

    const list = within(await screen.findByRole("list", { name: "À estimer" }));
    expect(list.getByText("durée inconnue · pour vendredi 20 novembre (dans 2 jours)")).toBeVisible();
  });

  it("efface le cadre du jour après confirmation", async () => {
    const state = installFakeApi({ loggedIn: true, today: FULL });
    renderApp("/today");
    const user = userEvent.setup();

    // Annuler n'efface rien.
    await user.click(await screen.findByRole("button", { name: "Effacer" }));
    const asked = await screen.findByRole("alertdialog", { name: "Effacer le cadre d'aujourd'hui ?" });
    await user.click(within(asked).getByRole("button", { name: "Annuler" }));
    await waitFor(() => {
      expect(screen.queryByRole("alertdialog")).toBeNull();
    });
    expect(state.clearedDays).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Effacer" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Effacer le cadre d'aujourd'hui ?" });
    await user.click(within(dialog).getByRole("button", { name: "Effacer" }));

    await waitFor(() => {
      expect(state.clearedDays).toEqual(["2026-11-18"]);
    });
    // La journée est relue : sans cadre, rien n'est placé.
    expect(await screen.findByText(/Tu n'as pas encore dit quand tu travailles/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Effacer" })).toBeNull();
  });

  it("n'a pas de défaut d'accessibilité détectable", async () => {
    installFakeApi({ loggedIn: true, today: FULL });
    const { container } = renderApp("/today");
    await screen.findByRole("list", { name: "Déroulé de la journée" });

    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations.map((v) => `${v.id} : ${v.help}`)).toEqual([]);
  });
});
