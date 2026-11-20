/**
 * Cours et evaluations (PR 46, module academic). Le retard et le nombre de jours restants
 * viennent du serveur, calcules dans le fuseau du compte : la page ne devine pas quel jour il
 * est chez l'utilisateur.
 */
import { ApiError, ModuleDisabledError, api, type Schemas } from "./client";

export type Course = Schemas["CourseOut"];
export type Assessment = Schemas["AssessmentOut"];
export type AssessmentKind = Assessment["kind"];

/** Ce que le formulaire envoie pour creer ou corriger une evaluation. */
export interface AssessmentDraft {
  kind: AssessmentKind;
  title: string;
  due_on: string;
  weight: number | null;
  estimate_minutes: number | null;
}

/** Le module academic n'est pas active pour cet utilisateur (l'API repond 404). */
export class AcademicDisabledError extends ModuleDisabledError {
  constructor() {
    super("academic");
    this.name = "AcademicDisabledError";
  }
}

/** Refus lisible renvoye par le serveur (doublon, date invraisemblable, limite...). */
export class AcademicRefusedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AcademicRefusedError";
  }
}

function refused(status: number, error: unknown): Error {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  if (status === 422) {
    return new AcademicRefusedError(typeof detail === "string" ? detail : "Saisie refusée : vérifie les champs.");
  }
  return new ApiError(status, error);
}

export async function listCourses(): Promise<Course[]> {
  const { data, response, error } = await api.GET("/api/v1/academic/courses");
  if (response.status === 404) {
    throw new AcademicDisabledError();
  }
  if (data === undefined) {
    throw new ApiError(response.status, error);
  }
  return data;
}

export async function enableAcademic(): Promise<void> {
  const { response, error } = await api.PUT("/api/v1/modules/{module_id}", {
    params: { path: { module_id: "academic" } },
    body: { enabled: true },
  });
  if (!response.ok) {
    throw new ApiError(response.status, error);
  }
}

export async function addCourse(name: string): Promise<Course> {
  const { data, response, error } = await api.POST("/api/v1/academic/courses", { body: { name } });
  if (data === undefined) {
    throw refused(response.status, error);
  }
  return data;
}

export async function removeCourse(id: string): Promise<void> {
  const { response, error } = await api.DELETE("/api/v1/academic/courses/{course_id}", {
    params: { path: { course_id: id } },
  });
  if (!response.ok) {
    throw new ApiError(response.status, error);
  }
}

export async function listAssessments(state: "open" | "done"): Promise<Assessment[]> {
  const { data, response, error } = await api.GET("/api/v1/academic/assessments", {
    params: { query: { state } },
  });
  if (response.status === 404) {
    throw new AcademicDisabledError();
  }
  if (data === undefined) {
    throw new ApiError(response.status, error);
  }
  return data;
}

export async function addAssessment(courseId: string, draft: AssessmentDraft): Promise<Assessment> {
  const { data, response, error } = await api.POST("/api/v1/academic/assessments", {
    body: { course_id: courseId, ...draft },
  });
  if (data === undefined) {
    throw refused(response.status, error);
  }
  return data;
}

export async function updateAssessment(id: string, draft: AssessmentDraft): Promise<Assessment> {
  const { data, response, error } = await api.PUT("/api/v1/academic/assessments/{assessment_id}", {
    params: { path: { assessment_id: id } },
    body: draft,
  });
  if (data === undefined) {
    throw refused(response.status, error);
  }
  return data;
}

export async function completeAssessment(id: string): Promise<Assessment> {
  const { data, response, error } = await api.POST("/api/v1/academic/assessments/{assessment_id}/complete", {
    params: { path: { assessment_id: id } },
  });
  if (data === undefined) {
    throw refused(response.status, error);
  }
  return data;
}

export async function removeAssessment(id: string): Promise<void> {
  const { response, error } = await api.DELETE("/api/v1/academic/assessments/{assessment_id}", {
    params: { path: { assessment_id: id } },
  });
  if (!response.ok) {
    throw new ApiError(response.status, error);
  }
}
