/**
 * Page « Cours » (PR 46), contre le faux backend : activation, premier cours, ajout d'une
 * évaluation, retards calculés par le serveur, correction, fin, suppression, navigation,
 * accessibilité.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { describe, expect, it } from "vitest";

import { installFakeApi, type FakeAssessment, type FakeCourse } from "@/test/fakeApi";
import { renderApp } from "@/test/renderApp";

import { duration, hoursToMinutes, longDate, minutesToHours, relativeDay, weight } from "./format";

const ML: FakeCourse = { id: "c1", name: "Machine Learning" };
const ALGO: FakeCourse = { id: "c2", name: "Algo" };

function homework(overrides: Partial<FakeAssessment> = {}): FakeAssessment {
  return {
    id: "a1",
    course_id: "c1",
    kind: "assignment",
    title: "TP 2",
    due_on: "2026-11-20",
    weight: null,
    estimate_minutes: null,
    status: "open",
    completed_at: null,
    ...overrides,
  };
}

describe("format des évaluations", () => {
  it("écrit la date en entier, sans dépendre du fuseau de l'appareil", () => {
    const now = new Date(2026, 10, 18);
    expect(longDate("2026-11-20", now)).toBe("vendredi 20 novembre");
    expect(longDate("2026-11-01", now)).toBe("dimanche 1 novembre");
    expect(longDate("2027-01-04", now)).toBe("lundi 4 janvier 2027");
  });

  it("dit la position du jour, les durées et les coefficients en français", () => {
    expect([0, 1, 2, -1, -3].map(relativeDay)).toEqual([
      "aujourd'hui",
      "demain",
      "dans 2 jours",
      "hier",
      "il y a 3 jours",
    ]);
    expect([45, 60, 180, 90, 65].map(duration)).toEqual(["45 min", "1 h", "3 h", "1 h 30", "1 h 05"]);
    expect([2, 0.5, 1.25].map(weight)).toEqual(["2", "0,5", "1,25"]);
  });

  it("convertit les heures saisies en minutes, et inversement", () => {
    expect(["3", "1,5", "1.25", " 0,5 ", "0.01"].map(hoursToMinutes)).toEqual([180, 90, 75, 30, 1]);
    expect(["", "  ", "abc", "0", "-2"].map(hoursToMinutes)).toEqual([null, null, null, null, null]);
    expect([null, 180, 90, 75].map(minutesToHours)).toEqual(["", "3", "1,5", "1,25"]);
  });
});

describe("cours", () => {
  it("propose d'activer le module, puis de créer un premier cours", async () => {
    const state = installFakeApi({ loggedIn: true, academicEnabled: false });
    renderApp("/academic");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Activer" }));
    expect(state.academicEnabled).toBe(true);

    await user.type(await screen.findByLabelText("Nom du cours"), "Machine Learning");
    await user.click(screen.getByRole("button", { name: "Ajouter" }));

    expect(await screen.findByText("Rien à rendre pour l'instant.")).toBeVisible();
    expect(state.courses.map((c) => c.name)).toEqual(["Machine Learning"]);
    expect(screen.getByRole("form", { name: "Ajouter une évaluation" })).toBeVisible();
  });

  it("ajoute une évaluation avec sa durée et son coefficient, puis vide le formulaire", async () => {
    const state = installFakeApi({ loggedIn: true, courses: [ML, ALGO] });
    renderApp("/academic");
    const user = userEvent.setup();

    const form = within(await screen.findByRole("form", { name: "Ajouter une évaluation" }));
    // Les cours sont proposés par ordre alphabétique : Algo est choisi d'office.
    await user.selectOptions(form.getByLabelText("Cours"), "Machine Learning");
    await user.selectOptions(form.getByLabelText("Type"), "Examen");
    await user.type(form.getByLabelText("Titre"), "Partiel");
    await user.type(form.getByLabelText("Date"), "2026-11-20");
    await user.type(form.getByLabelText("Durée (heures)"), "1,5");
    await user.type(form.getByLabelText("Coefficient"), "0,5");
    await user.click(form.getByRole("button", { name: "Ajouter" }));

    const list = await screen.findByRole("list", { name: "À venir" });
    expect(within(list).getByText("Partiel")).toBeVisible();
    expect(within(list).getByText("Machine Learning · Examen · 1 h 30 · coef. 0,5")).toBeVisible();
    expect(within(list).getByText("vendredi 20 novembre (dans 2 jours)")).toBeVisible();
    expect(state.requests.find((r) => r.method === "POST" && r.path.endsWith("/assessments"))?.body).toEqual({
      course_id: "c1",
      kind: "exam",
      title: "Partiel",
      due_on: "2026-11-20",
      weight: 0.5,
      estimate_minutes: 90,
    });
    // Formulaire vidé pour la saisie suivante (le cours choisi, lui, reste).
    const fresh = within(screen.getByRole("form", { name: "Ajouter une évaluation" }));
    await waitFor(() => {
      expect(fresh.getByLabelText("Titre")).toHaveValue("");
    });
    expect(fresh.getByLabelText("Durée (heures)")).toHaveValue("");
    expect(fresh.getByLabelText("Cours")).toHaveDisplayValue("Machine Learning");
  });

  it("montre le refus du serveur et refuse un coefficient impossible avant d'envoyer", async () => {
    const state = installFakeApi({ loggedIn: true, courses: [ML], assessments: [homework()] });
    renderApp("/academic");
    const user = userEvent.setup();

    const form = within(await screen.findByRole("form", { name: "Ajouter une évaluation" }));
    await user.type(form.getByLabelText("Titre"), "tp 2");
    await user.type(form.getByLabelText("Échéance"), "2026-11-20");
    await user.type(form.getByLabelText("Coefficient"), "150");
    await user.click(form.getByRole("button", { name: "Ajouter" }));
    expect(await form.findByRole("alert")).toHaveTextContent("Le coefficient doit être plus grand que 0");
    expect(state.requests.some((r) => r.method === "POST" && r.path.endsWith("/assessments"))).toBe(false);

    await user.clear(form.getByLabelText("Coefficient"));
    await user.click(form.getByRole("button", { name: "Ajouter" }));
    expect(await form.findByRole("alert")).toHaveTextContent(
      "Cette évaluation existe déjà, avec la même échéance.",
    );
    expect(state.assessments).toHaveLength(1);
  });

  it("sépare les retards, d'après le serveur, de ce qui vient", async () => {
    installFakeApi({
      loggedIn: true,
      courses: [ML],
      assessments: [
        homework({ id: "a1", title: "Rapport", due_on: "2026-11-16" }),
        homework({ id: "a2", title: "Quiz", due_on: "2026-11-18" }),
        homework({ id: "a3", title: "TP 2", due_on: "2026-11-25", estimate_minutes: 180 }),
      ],
    });
    renderApp("/academic");

    const late = await screen.findByRole("list", { name: "En retard" });
    expect(within(late).getAllByRole("listitem")).toHaveLength(1);
    expect(within(late).getByText("lundi 16 novembre (il y a 2 jours)")).toHaveClass("text-danger");
    const coming = screen.getByRole("list", { name: "À venir" });
    expect(within(coming).getAllByRole("listitem")).toHaveLength(2); // le retard n'y est pas répété
    // À rendre aujourd'hui : pas encore en retard.
    expect(within(coming).getByText("mercredi 18 novembre (aujourd'hui)")).not.toHaveClass("text-danger");
    expect(within(coming).getByText("Machine Learning · 3 h")).toBeVisible();
  });

  it("termine une évaluation, qui passe dans les terminés", async () => {
    const state = installFakeApi({ loggedIn: true, courses: [ML], assessments: [homework()] });
    renderApp("/academic");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Marquer « TP 2 » comme terminé" }));

    expect(await screen.findByText("Rien à rendre pour l'instant.")).toBeVisible();
    expect(state.assessments[0]?.status).toBe("done");
    await user.click(screen.getByRole("button", { name: /Terminés/ }));
    const done = await screen.findByRole("list", { name: "Terminés" });
    expect(within(done).getByText("TP 2")).toBeVisible();
    expect(within(done).getByText(/Machine Learning · terminé le mercredi 18 novembre/)).toBeVisible();
  });

  it("corrige une évaluation en touchant sa ligne", async () => {
    const state = installFakeApi({
      loggedIn: true,
      courses: [ML],
      assessments: [homework({ estimate_minutes: 90, weight: 0.5 })],
    });
    renderApp("/academic");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Modifier « TP 2 »" }));
    const form = within(screen.getByRole("form", { name: "Modifier « TP 2 »" }));
    expect(form.getByLabelText("Titre")).toHaveValue("TP 2");
    expect(form.getByLabelText("Durée (heures)")).toHaveValue("1,5");
    expect(form.getByLabelText("Coefficient")).toHaveValue("0,5");
    expect(form.queryByLabelText("Cours")).toBeNull(); // une évaluation ne change pas de cours

    await user.clear(form.getByLabelText("Échéance"));
    await user.type(form.getByLabelText("Échéance"), "2026-11-27");
    await user.clear(form.getByLabelText("Durée (heures)"));
    await user.click(form.getByRole("button", { name: "Enregistrer" }));

    expect(await screen.findByText("vendredi 27 novembre (dans 9 jours)")).toBeVisible();
    expect(state.requests.find((r) => r.method === "PUT")?.body).toEqual({
      kind: "assignment",
      title: "TP 2",
      due_on: "2026-11-27",
      weight: 0.5,
      estimate_minutes: null,
    });
    expect(screen.queryByRole("form", { name: "Modifier « TP 2 »" })).toBeNull();
  });

  it("annule une correction sans rien envoyer, et supprime après confirmation", async () => {
    const state = installFakeApi({ loggedIn: true, courses: [ML], assessments: [homework()] });
    renderApp("/academic");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Modifier « TP 2 »" }));
    await user.type(screen.getAllByLabelText("Titre")[0] as HTMLElement, " bis");
    await user.click(screen.getByRole("button", { name: "Annuler" }));
    expect(await screen.findByRole("button", { name: "Modifier « TP 2 »" })).toBeVisible();
    expect(state.requests.some((r) => r.method === "PUT")).toBe(false);

    await user.click(screen.getByRole("button", { name: "Modifier « TP 2 »" }));
    await user.click(screen.getByRole("button", { name: "Supprimer" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Supprimer « TP 2 » ?" });
    expect(dialog).toHaveTextContent("Sa tâche disparaît aussi de ta liste.");
    expect(state.assessments).toHaveLength(1); // rien avant la confirmation
    await user.click(within(dialog).getByRole("button", { name: "Supprimer" }));

    expect(await screen.findByText("Rien à rendre pour l'instant.")).toBeVisible();
    expect(state.assessments).toEqual([]);
  });

  it("supprime un cours et ses évaluations après confirmation, et refuse un doublon", async () => {
    const state = installFakeApi({
      loggedIn: true,
      courses: [ML, ALGO],
      assessments: [homework(), homework({ id: "a2", course_id: "c2", title: "Exos" })],
    });
    renderApp("/academic");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /Mes cours/ }));
    await user.type(screen.getByLabelText("Nouveau cours"), "algo");
    const courses = screen.getByRole("list", { name: "Mes cours" });
    await user.click(within(courses.parentElement as HTMLElement).getByRole("button", { name: "Ajouter" }));
    expect(await screen.findByText("Tu as déjà un cours de ce nom.")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Supprimer le cours Machine Learning" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Supprimer « Machine Learning » ?" });
    expect(dialog).toHaveTextContent("leurs tâches sont supprimés aussi");
    await user.click(within(dialog).getByRole("button", { name: "Supprimer" }));

    await waitFor(() => {
      expect(screen.queryByText("TP 2")).toBeNull();
    });
    expect(screen.getByText("Exos")).toBeVisible();
    expect(state.courses).toEqual([ALGO]);
    expect(state.assessments.map((a) => a.id)).toEqual(["a2"]);
  });

  it("s'ouvre depuis la barre latérale", async () => {
    installFakeApi({ loggedIn: true, courses: [ML] });
    renderApp("/");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("link", { name: "Cours" }));

    expect(await screen.findByRole("heading", { level: 1, name: "Cours" })).toBeVisible();
  });

  it("n'a pas de défaut d'accessibilité détectable", async () => {
    installFakeApi({
      loggedIn: true,
      courses: [ML],
      assessments: [homework(), homework({ id: "a2", title: "Rapport", due_on: "2026-11-10" })],
    });
    const { container } = renderApp("/academic");
    const user = userEvent.setup();
    await screen.findByRole("list", { name: "En retard" });
    await user.click(screen.getByRole("button", { name: /Mes cours/ }));
    await user.click(screen.getByRole("button", { name: "Modifier « TP 2 »" }));

    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations.map((v) => `${v.id} : ${v.help}`)).toEqual([]);
  });
});
