/**
 * Ma journee (PR 47) : agenda du jour, plan propose, retards, echeances. Tout est calcule par
 * le serveur dans le fuseau du compte ; le plan est une proposition, jamais ecrite a l'agenda.
 */
import { ApiError, api, type Schemas } from "./client";

export type Today = Schemas["TodayOut"];
export type AgendaEntry = Schemas["AgendaEntryOut"];
export type PlanBlock = Schemas["PlanBlockOut"];
export type PlannedTask = Schemas["TaskOut"];

export async function getToday(): Promise<Today> {
  const { data, response, error } = await api.GET("/api/v1/planning/today");
  if (data === undefined) {
    throw new ApiError(response.status, error);
  }
  return data;
}
