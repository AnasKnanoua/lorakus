import { ApiError, api, type Schemas } from "./client";

export type Fact = Schemas["FactOut"];
export type Category = Fact["category"];

export const CATEGORY_LABELS: Record<Category, string> = {
  identity: "Identité",
  preference: "Préférences",
  project: "Projets",
  habit: "Habitudes",
  studies: "Études",
  other: "Autre",
};

export const CATEGORIES = Object.keys(CATEGORY_LABELS) as Category[];

function check(response: Response, error: unknown): void {
  if (!response.ok) {
    throw new ApiError(response.status, error);
  }
}

export async function listFacts(): Promise<Fact[]> {
  const { data, response, error } = await api.GET("/api/v1/memory/facts");
  if (data === undefined) {
    throw new ApiError(response.status, error);
  }
  return data;
}

export async function addFact(content: string, category: Category): Promise<void> {
  const { response, error } = await api.POST("/api/v1/memory/facts", {
    body: { content, category },
  });
  check(response, error);
}

export async function updateFact(id: string, content: string, category: Category): Promise<void> {
  const { response, error } = await api.PATCH("/api/v1/memory/facts/{fact_id}", {
    params: { path: { fact_id: id } },
    body: { content, category },
  });
  check(response, error);
}

/** Confirme une proposition ; content et category corrigent le texte avant confirmation. */
export async function confirmFact(id: string, content?: string, category?: Category): Promise<void> {
  const { response, error } = await api.POST("/api/v1/memory/facts/{fact_id}/confirm", {
    params: { path: { fact_id: id } },
    body: content === undefined ? null : { content, category: category ?? null },
  });
  check(response, error);
}

export async function rejectFact(id: string): Promise<void> {
  const { response, error } = await api.POST("/api/v1/memory/facts/{fact_id}/reject", {
    params: { path: { fact_id: id } },
  });
  check(response, error);
}

export async function deleteFact(id: string): Promise<void> {
  const { response, error } = await api.DELETE("/api/v1/memory/facts/{fact_id}", {
    params: { path: { fact_id: id } },
  });
  check(response, error);
}

export async function getProposalsEnabled(): Promise<boolean> {
  const { data, response, error } = await api.GET("/api/v1/memory/settings");
  if (data === undefined) {
    throw new ApiError(response.status, error);
  }
  return data.propose_after_conversations;
}

export async function setProposalsEnabled(enabled: boolean): Promise<void> {
  const { response, error } = await api.PUT("/api/v1/memory/settings", {
    body: { propose_after_conversations: enabled },
  });
  check(response, error);
}

/** Tout oublier. "reauth" : preuve d'identite trop ancienne, a redonner avant de reessayer. */
export async function forgetAll(): Promise<"ok" | "reauth"> {
  const { response, error } = await api.POST("/api/v1/memory/forget-all");
  if (response.status === 403) {
    return "reauth";
  }
  check(response, error);
  return "ok";
}

/** Re-authentification (mot de passe, et code si la double authentification est active). */
export async function reauthenticate(password: string, secondFactor: string): Promise<boolean> {
  const { response } = await api.POST("/api/v1/auth/reauth", {
    body: { password, second_factor: secondFactor.trim() || null },
  });
  return response.ok;
}
