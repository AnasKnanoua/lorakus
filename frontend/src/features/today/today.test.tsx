/**
 * Page « Ma journée » (PR 47), contre le faux backend : ligne de temps (agenda et plan
 * proposé), heures dans le fuseau du compte, retards, échéances, liens vers les modules.
 */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { describe, expect, it } from "vitest";

import { clockTime } from "@/lib/format";
import { emptyToday, installFakeApi, type FakeToday } from "@/test/fakeApi";
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
const FULL = emptyToday({
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
    { task: REPORT, starts_at: "2026-11-18T05:00:00Z", ends_at: "2026-11-18T06:00:00Z", minutes: 60, assumed_duration: false },
    { task: task(), starts_at: "2026-11-18T09:00:00Z", ends_at: "2026-11-18T10:30:00Z", minutes: 90, assumed_duration: false },
    { task: ERRAND, starts_at: "2026-11-18T10:45:00Z", ends_at: "2026-11-18T11:15:00Z", minutes: 30, assumed_duration: true },
  ],
  planned_minutes: 180,
  unplanned: [{ task: task(), minutes: 90 }],
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
      "13:45 – 14:15CoursesProposé · 30 min (durée supposée)",
    ]);
    // Un créneau déjà fini est en retrait ; une proposition se distingue d'un créneau.
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
    expect(screen.getByText("Travail proposé : 3 h. Rien n'est ajouté à ton agenda.")).toBeVisible();
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

  it("dit quand la journée est vide, sans sections inutiles", async () => {
    installFakeApi({ loggedIn: true });
    renderApp("/today");

    expect(await screen.findByText("Rien de prévu aujourd'hui.")).toBeVisible();
    expect(screen.getByText("Aucune échéance cette semaine.")).toBeVisible();
    expect(screen.queryByRole("heading", { name: "En retard" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Pas de place aujourd'hui" })).toBeNull();
    expect(screen.queryByText(/Travail proposé/)).toBeNull();
  });

  it("dit que la journée de travail est finie quand il reste du travail", async () => {
    installFakeApi({
      loggedIn: true,
      today: emptyToday({ work_ends_at: null, unplanned: [{ task: task(), minutes: 180 }], upcoming: [task()] }),
    });
    renderApp("/today");

    expect(
      await screen.findByText("La journée de travail est finie : le plan reprendra demain matin."),
    ).toBeVisible();
    expect(screen.getByText("reste 3 h")).toBeVisible();
  });

  it("ne dit pas que la journée est finie tant que la fenêtre de travail est ouverte", async () => {
    // Il reste moins d'un quart d'heure avant 22 h : rien ne se place, mais la journée court.
    installFakeApi({ loggedIn: true, today: emptyToday({ unplanned: [{ task: task(), minutes: 180 }] }) });
    renderApp("/today");

    expect(await screen.findByText("Rien de prévu aujourd'hui.")).toBeVisible();
    expect(screen.queryByText(/journée de travail est finie/)).toBeNull();
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

  it("n'a pas de défaut d'accessibilité détectable", async () => {
    installFakeApi({ loggedIn: true, today: FULL });
    const { container } = renderApp("/today");
    await screen.findByRole("list", { name: "Déroulé de la journée" });

    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations.map((v) => `${v.id} : ${v.help}`)).toEqual([]);
  });
});
