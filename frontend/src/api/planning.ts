/**
 * Ma journee (PR 47) : agenda du jour, plan propose, retards, echeances. Tout est calcule par
 * le serveur dans le fuseau du compte ; le plan est une proposition, jamais ecrite a l'agenda.
 */
import { ApiError, api, type Schemas } from "./client";

export type Today = Schemas["TodayOut"];
export type AgendaEntry = Schemas["AgendaEntryOut"];
export type PlanBlock = Schemas["PlanBlockOut"];
export type PlannedTask = Schemas["TaskOut"];
export type Meal = Schemas["MealOut"];
export type Preference = Schemas["PreferenceOut"];

export async function getToday(): Promise<Today> {
  const { data, response, error } = await api.GET("/api/v1/planning/today");
  if (data === undefined) {
    throw new ApiError(response.status, error);
  }
  return data;
}

/** Preferences de planification (PR 48) : le catalogue entier, confirmees ou par defaut. */
export async function getPreferences(): Promise<Preference[]> {
  const { data, response, error } = await api.GET("/api/v1/planning/preferences");
  if (data === undefined) {
    throw new ApiError(response.status, error);
  }
  return data;
}

/** Retire une preference confirmee : sa valeur par defaut s'applique de nouveau. */
export async function removePreference(key: Preference["key"]): Promise<void> {
  const { response, error } = await api.DELETE("/api/v1/planning/preferences/{key}", {
    params: { path: { key } },
  });
  if (!response.ok) {
    throw new ApiError(response.status, error);
  }
}
