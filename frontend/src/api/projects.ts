/**
 * Idées, projets et tâches de projet (PR 51, module projects). Chaque tâche de projet a sa
 * tâche dans le planning : la terminer ici la termine aussi, et la terminer dans le chat la
 * termine ici. Les jours sans activité et les retards viennent du serveur.
 */
import { ApiError, ModuleDisabledError, api, type Schemas } from "./client";

export type Idea = Schemas["IdeaOut"];
export type Project = Schemas["ProjectOut"];
export type ProjectTask = Schemas["ProjectTaskOut"];

/** Le module projects n'est pas activé pour cet utilisateur (l'API répond 404). */
export class ProjectsDisabledError extends ModuleDisabledError {
  constructor() {
    super("projects");
    this.name = "ProjectsDisabledError";
  }
}

/** Refus lisible renvoyé par le serveur (doublon, limite, date invraisemblable...). */
export class ProjectsRefusedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ProjectsRefusedError";
  }
}

function failure(status: number, error: unknown): Error {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  if (status === 422) {
    return new ProjectsRefusedError(typeof detail === "string" ? detail : "Saisie refusée : vérifie les champs.");
  }
  return new ApiError(status, error);
}

export async function listIdeas(state: "inbox" | "archived" = "inbox"): Promise<Idea[]> {
  const { data, response, error } = await api.GET("/api/v1/projects/ideas", { params: { query: { state } } });
  if (response.status === 404) throw new ProjectsDisabledError();
  if (data === undefined) throw new ApiError(response.status, error);
  return data;
}

export async function addIdea(text: string): Promise<Idea> {
  const { data, response, error } = await api.POST("/api/v1/projects/ideas", { body: { text } });
  if (data === undefined) throw failure(response.status, error);
  return data;
}

export async function archiveIdea(id: string): Promise<void> {
  const { response, error } = await api.POST("/api/v1/projects/ideas/{idea_id}/archive", {
    params: { path: { idea_id: id } },
  });
  if (!response.ok) throw failure(response.status, error);
}

export async function removeIdea(id: string): Promise<void> {
  const { response, error } = await api.DELETE("/api/v1/projects/ideas/{idea_id}", {
    params: { path: { idea_id: id } },
  });
  if (!response.ok) throw failure(response.status, error);
}

export async function listProjects(state: "active" | "done" = "active"): Promise<Project[]> {
  const { data, response, error } = await api.GET("/api/v1/projects/projects", { params: { query: { state } } });
  if (response.status === 404) throw new ProjectsDisabledError();
  if (data === undefined) throw new ApiError(response.status, error);
  return data;
}

export async function addProject(draft: {
  name: string;
  description?: string | null;
  idea_id?: string | null;
}): Promise<Project> {
  const { data, response, error } = await api.POST("/api/v1/projects/projects", { body: draft });
  if (data === undefined) throw failure(response.status, error);
  return data;
}

export async function finishProject(id: string): Promise<void> {
  const { response, error } = await api.POST("/api/v1/projects/projects/{project_id}/finish", {
    params: { path: { project_id: id } },
  });
  if (!response.ok) throw failure(response.status, error);
}

export async function removeProject(id: string): Promise<void> {
  const { response, error } = await api.DELETE("/api/v1/projects/projects/{project_id}", {
    params: { path: { project_id: id } },
  });
  if (!response.ok) throw failure(response.status, error);
}

export async function addProjectTask(
  projectId: string,
  draft: { title: string; due_on: string | null; estimate_minutes: number | null },
): Promise<void> {
  const { response, error } = await api.POST("/api/v1/projects/projects/{project_id}/tasks", {
    params: { path: { project_id: projectId } },
    body: draft,
  });
  if (!response.ok) throw failure(response.status, error);
}

/** Termine une tâche de projet ; `actualMinutes` : le temps réellement passé, s'il est donné. */
export async function completeProjectTask(id: string, actualMinutes: number | null = null): Promise<void> {
  const { response, error } = await api.POST("/api/v1/projects/tasks/{task_id}/complete", {
    params: { path: { task_id: id } },
    body: actualMinutes === null ? null : { actual_minutes: actualMinutes },
  });
  if (!response.ok) throw failure(response.status, error);
}

export async function removeProjectTask(id: string): Promise<void> {
  const { response, error } = await api.DELETE("/api/v1/projects/tasks/{task_id}", {
    params: { path: { task_id: id } },
  });
  if (!response.ok) throw failure(response.status, error);
}

export async function enableProjects(): Promise<void> {
  const { response, error } = await api.PUT("/api/v1/modules/{module_id}", {
    params: { path: { module_id: "projects" } },
    body: { enabled: true },
  });
  if (!response.ok) throw new ApiError(response.status, error);
}
