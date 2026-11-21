/**
 * Page « Projets » (PR 51), contre le faux backend : activation, boîte d'idées (noter,
 * archiver, supprimer, en faire un projet), projets (création, refus lisibles, tâches,
 * avancement, inactivité, fin, suppression), navigation, accessibilité.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { describe, expect, it } from "vitest";

import { installFakeApi, type FakeIdea, type FakeProject } from "@/test/fakeApi";
import { renderApp } from "@/test/renderApp";

type FakeTask = FakeProject["tasks"][number];

function idea(overrides: Partial<FakeIdea> = {}): FakeIdea {
  return { id: "i1", text: "Une appli pour suivre mes parties d'échecs", status: "inbox", created_at: "2026-11-17T10:00:00Z", ...overrides };
}

function task(overrides: Partial<FakeTask> = {}): FakeTask {
  return {
    id: "t1",
    title: "Écrire le README",
    status: "open",
    due_on: null,
    overdue: false,
    estimate_minutes: null,
    completed_at: null,
    ...overrides,
  };
}

function project(overrides: Partial<FakeProject> = {}): FakeProject {
  const tasks = overrides.tasks ?? [];
  return {
    id: "p1",
    name: "Portfolio",
    description: "Montrer mes projets",
    status: "active",
    open_tasks: tasks.filter((t) => t.status === "open").length,
    done_tasks: tasks.filter((t) => t.status === "done").length,
    idle_days: null,
    last_activity_at: "2026-11-17T10:00:00Z",
    finished_at: null,
    tasks,
    ...overrides,
  };
}

describe("boîte d'idées", () => {
  it("propose d'activer le module, puis note une idée et vide le champ", async () => {
    const state = installFakeApi({ loggedIn: true, projectsEnabled: false });
    renderApp("/projets");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Activer" }));
    expect(state.projectsEnabled).toBe(true);

    const field = await screen.findByLabelText("Nouvelle idée");
    await user.type(field, "  Apprendre Rust  ");
    await user.click(screen.getByRole("button", { name: "Noter" }));

    const box = await screen.findByRole("list", { name: "Boîte d'idées" });
    expect(within(box).getByText("Apprendre Rust")).toBeVisible();
    expect(field).toHaveValue("");
    expect(state.requests.find((r) => r.method === "POST")?.body).toEqual({ text: "  Apprendre Rust  " });
    expect(screen.getByText("Aucun projet en cours.")).toBeVisible();
  });

  it("dit le refus du serveur pour une idée déjà notée", async () => {
    installFakeApi({ loggedIn: true, ideas: [idea({ text: "Apprendre Rust" })] });
    renderApp("/projets");
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("Nouvelle idée"), "apprendre rust");
    await user.click(screen.getByRole("button", { name: "Noter" }));

    expect(await screen.findByText("Cette idée est déjà dans ta boîte.")).toBeVisible();
    expect(screen.getByLabelText("Nouvelle idée")).toHaveValue("apprendre rust");
  });

  it("archive une idée d'un geste, et la garde dans les idées archivées", async () => {
    const state = installFakeApi({ loggedIn: true, ideas: [idea()] });
    renderApp("/projets");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /^Archiver l'idée/ }));

    expect(await screen.findByText(/Rien en attente/)).toBeVisible();
    expect(state.ideas[0]?.status).toBe("archived");
    await user.click(await screen.findByRole("button", { name: /Idées archivées/ }));
    expect(within(screen.getByRole("list", { name: "Idées archivées" })).getByText(idea().text)).toBeVisible();
  });

  it("ne supprime une idée qu'après confirmation", async () => {
    const state = installFakeApi({ loggedIn: true, ideas: [idea()] });
    renderApp("/projets");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /^Supprimer l'idée/ }));
    const dialog = await screen.findByRole("alertdialog", { name: "Supprimer cette idée ?" });
    expect(dialog).toHaveTextContent("archive-la");
    expect(state.ideas).toHaveLength(1); // rien avant la confirmation
    await user.click(within(dialog).getByRole("button", { name: "Supprimer" }));

    expect(await screen.findByText(/Rien en attente/)).toBeVisible();
    expect(state.ideas).toEqual([]);
  });

  it("fait d'une idée un projet : l'idée quitte la boîte et devient sa description", async () => {
    const state = installFakeApi({ loggedIn: true, ideas: [idea()] });
    renderApp("/projets");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /^Faire un projet de l'idée/ }));
    const form = within(screen.getByRole("form", { name: "En faire un projet" }));
    expect(form.getByText(`« ${idea().text} »`)).toBeVisible();
    expect(form.queryByLabelText(/Description/)).toBeNull(); // le texte de l'idée en tient lieu
    await user.type(form.getByLabelText("Nom du projet"), "Échecs");
    await user.click(form.getByRole("button", { name: "Créer le projet" }));

    const card = await screen.findByRole("listitem", { name: "Échecs" });
    expect(within(card).getByText(idea().text)).toBeVisible();
    expect(state.ideas).toEqual([]);
    expect(state.requests.find((r) => r.path === "/api/v1/projects/projects" && r.method === "POST")?.body).toEqual({
      name: "Échecs",
      description: null,
      idea_id: "i1",
    });
    expect(screen.queryByRole("form", { name: "En faire un projet" })).toBeNull();
  });

  it("annule la transformation sans rien envoyer", async () => {
    const state = installFakeApi({ loggedIn: true, ideas: [idea()] });
    renderApp("/projets");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /^Faire un projet de l'idée/ }));
    await user.click(screen.getByRole("button", { name: "Annuler" }));

    expect(await screen.findByRole("button", { name: /^Faire un projet de l'idée/ })).toBeVisible();
    expect(state.requests.some((r) => r.method === "POST")).toBe(false);
  });
});

describe("projets", () => {
  it("crée un projet avec sa description, et refuse un nom déjà pris", async () => {
    const state = installFakeApi({ loggedIn: true, projects: [project()] });
    renderApp("/projets");
    const user = userEvent.setup();

    const form = within(await screen.findByRole("form", { name: "Nouveau projet" }));
    await user.type(form.getByLabelText("Nom du projet"), "portfolio");
    await user.click(form.getByRole("button", { name: "Créer le projet" }));
    expect(await screen.findByText("Tu as déjà un projet de ce nom.")).toBeVisible();

    await user.clear(form.getByLabelText("Nom du projet"));
    await user.type(form.getByLabelText("Nom du projet"), "Lorakus");
    await user.type(form.getByLabelText("Description (facultatif)"), "Mon assistant");
    await user.click(form.getByRole("button", { name: "Créer le projet" }));

    const card = await screen.findByRole("listitem", { name: "Lorakus" });
    expect(within(card).getByText("Mon assistant")).toBeVisible();
    expect(within(card).getByText("Aucune tâche")).toBeVisible();
    expect(form.getByLabelText("Nom du projet")).toHaveValue("");
    expect(state.projects.map((p) => p.name)).toEqual(["Portfolio", "Lorakus"]);
  });

  it("montre l'avancement, les retards et l'inactivité dits par le serveur", async () => {
    installFakeApi({
      loggedIn: true,
      projects: [
        project({
          idle_days: 16,
          tasks: [
            task({ id: "t0", title: "Choisir le thème", status: "done", completed_at: "2026-11-01T09:00:00Z" }),
            task({ due_on: "2026-11-15", overdue: true, estimate_minutes: 90 }),
            task({ id: "t2", title: "Mettre en ligne", due_on: "2026-11-20", estimate_minutes: 60 }),
          ],
        }),
      ],
    });
    renderApp("/projets");

    const card = await screen.findByRole("listitem", { name: "Portfolio" });
    expect(within(card).getByText("Sans activité depuis 16 jours")).toBeVisible();
    const bar = within(card).getByRole("progressbar", { name: "Avancement de Portfolio" });
    expect(bar).toHaveAttribute("aria-valuenow", "1");
    expect(bar).toHaveAttribute("aria-valuemax", "3");
    expect(within(card).getByText("1 / 3")).toBeVisible();
    const open = within(within(card).getByRole("list", { name: "Tâches ouvertes de Portfolio" }));
    expect(open.getAllByRole("listitem")).toHaveLength(2); // la tâche terminée n'est que comptée
    expect(open.getByText(/^En retard · pour le dimanche 15 novembre · 1 h 30$/)).toHaveClass("text-danger");
    expect(open.getByText(/^pour le vendredi 20 novembre · 1 h$/)).toHaveClass("text-ink-faint");
  });

  it("ajoute une tâche avec échéance et durée, ou sans rien de plus", async () => {
    const state = installFakeApi({ loggedIn: true, projects: [project()] });
    renderApp("/projets");
    const user = userEvent.setup();

    expect(screen.queryByLabelText("Nouvelle tâche")).toBeNull(); // replié par défaut
    await user.click(await screen.findByRole("button", { name: "Ajouter une tâche à Portfolio" }));
    const form = within(await screen.findByRole("form", { name: "Ajouter une tâche à Portfolio" }));
    expect(form.getByLabelText("Nouvelle tâche")).toHaveFocus();
    await user.type(form.getByLabelText("Nouvelle tâche"), "Écrire le README");
    await user.type(form.getByLabelText("Pour le (facultatif)"), "2026-11-25");
    await user.type(form.getByLabelText("Durée, en heures"), "1,5");
    await user.click(form.getByRole("button", { name: "Ajouter" }));

    expect(await screen.findByText("Écrire le README")).toBeVisible();
    expect(form.getByLabelText("Nouvelle tâche")).toHaveValue("");
    expect(form.getByLabelText("Durée, en heures")).toHaveValue("");

    await user.type(form.getByLabelText("Nouvelle tâche"), "Acheter le domaine");
    await user.click(form.getByRole("button", { name: "Ajouter" }));
    expect(await screen.findByText("Acheter le domaine")).toBeVisible();

    await user.click(form.getByRole("button", { name: "Fermer" }));
    expect(screen.queryByRole("form", { name: "Ajouter une tâche à Portfolio" })).toBeNull();

    const sent = state.requests.filter((r) => r.path.endsWith("/tasks") && r.method === "POST").map((r) => r.body);
    expect(sent).toEqual([
      { title: "Écrire le README", due_on: "2026-11-25", estimate_minutes: 90 },
      { title: "Acheter le domaine", due_on: null, estimate_minutes: null },
    ]);
  });

  it("termine une tâche après confirmation, avec le temps passé s'il est donné", async () => {
    const state = installFakeApi({ loggedIn: true, projects: [project({ tasks: [task()] })] });
    renderApp("/projets");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Marquer « Écrire le README » comme terminée" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Terminer « Écrire le README » ?" });
    expect(state.projects[0]?.tasks[0]?.status).toBe("open"); // rien avant la confirmation
    await user.type(within(dialog).getByLabelText("Temps passé, en heures (facultatif)"), "2");
    await user.click(within(dialog).getByRole("button", { name: "Terminer" }));

    await waitFor(() => {
      expect(screen.queryByRole("list", { name: "Tâches ouvertes de Portfolio" })).toBeNull();
    });
    expect(screen.getByText("1 / 1")).toBeVisible();
    expect(state.requests.find((r) => r.path.endsWith("/complete"))?.body).toEqual({ actual_minutes: 120 });
  });

  it("termine une tâche sans temps passé : le corps est vide", async () => {
    const state = installFakeApi({ loggedIn: true, projects: [project({ tasks: [task()] })] });
    renderApp("/projets");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Marquer « Écrire le README » comme terminée" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Terminer « Écrire le README » ?" });
    await user.click(within(dialog).getByRole("button", { name: "Terminer" }));

    await waitFor(() => {
      expect(state.projects[0]?.tasks[0]?.status).toBe("done");
    });
    expect(state.requests.find((r) => r.path.endsWith("/complete"))?.body).toBeNull();
  });

  it("supprime une tâche après confirmation", async () => {
    const state = installFakeApi({ loggedIn: true, projects: [project({ tasks: [task()] })] });
    renderApp("/projets");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Supprimer la tâche « Écrire le README »" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Supprimer « Écrire le README » ?" });
    expect(dialog).toHaveTextContent("Elle disparaît aussi de ta journée.");
    await user.click(within(dialog).getByRole("button", { name: "Supprimer" }));

    await waitFor(() => {
      expect(screen.queryByText("Écrire le README")).toBeNull();
    });
    expect(state.projects[0]?.tasks).toEqual([]);
  });

  it("termine un projet après confirmation : ses tâches ouvertes avec lui", async () => {
    const state = installFakeApi({
      loggedIn: true,
      projects: [project({ tasks: [task(), task({ id: "t2", title: "Mettre en ligne" })] })],
    });
    renderApp("/projets");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Terminer le projet" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Terminer « Portfolio » ?" });
    expect(dialog).toHaveTextContent("2 tâches ouvertes seront terminées aussi");
    expect(state.projects[0]?.status).toBe("active");
    await user.click(within(dialog).getByRole("button", { name: "Terminer" }));

    expect(await screen.findByText("Aucun projet en cours.")).toBeVisible();
    await user.click(screen.getByRole("button", { name: /Projets terminés/ }));
    const done = within(await screen.findByRole("list", { name: "Projets terminés" }));
    expect(done.getByText("Portfolio")).toBeVisible();
    expect(done.getByText("2 tâches · terminé le mercredi 18 novembre")).toBeVisible();
  });

  it("dit qu'un projet sans tâche ouverte rejoint simplement les terminés", async () => {
    installFakeApi({ loggedIn: true, projects: [project({ tasks: [task({ status: "done" })] })] });
    renderApp("/projets");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Terminer le projet" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Terminer « Portfolio » ?" });
    expect(dialog).toHaveTextContent("Il rejoint tes projets terminés.");
  });

  it("ne supprime un projet qu'après confirmation, tâches comprises", async () => {
    const state = installFakeApi({ loggedIn: true, projects: [project({ tasks: [task()] })] });
    renderApp("/projets");
    const user = userEvent.setup();

    const card = await screen.findByRole("listitem", { name: "Portfolio" });
    await user.click(within(card).getByRole("button", { name: "Supprimer" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Supprimer « Portfolio » ?" });
    expect(dialog).toHaveTextContent("Ses tâches sont supprimées aussi");
    expect(state.projects).toHaveLength(1);
    await user.click(within(dialog).getByRole("button", { name: "Supprimer" }));

    expect(await screen.findByText("Aucun projet en cours.")).toBeVisible();
    expect(state.projects).toEqual([]);
  });

  it("s'ouvre depuis la barre latérale", async () => {
    installFakeApi({ loggedIn: true });
    renderApp("/");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("link", { name: "Projets" }));

    expect(await screen.findByRole("heading", { level: 1, name: "Projets" })).toBeVisible();
  });

  it("n'a pas de défaut d'accessibilité détectable", async () => {
    installFakeApi({
      loggedIn: true,
      ideas: [idea(), idea({ id: "i2", text: "Lire SICP" })],
      projects: [project({ idle_days: 20, tasks: [task({ due_on: "2026-11-10", overdue: true })] })],
    });
    const { container } = renderApp("/projets");
    const user = userEvent.setup();
    await screen.findByRole("listitem", { name: "Portfolio" });
    await user.click(screen.getByRole("button", { name: "Ajouter une tâche à Portfolio" }));
    await user.click(screen.getAllByRole("button", { name: /^Faire un projet de l'idée/ })[0] as HTMLElement);

    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations.map((v) => `${v.id} : ${v.help}`)).toEqual([]);
  });
});
