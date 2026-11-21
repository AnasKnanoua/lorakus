/**
 * Ma journee (PR 47 et 49) : cadre du jour, agenda, plan propose, retards, echeances. Tout est
 * calcule par le serveur dans le fuseau du compte ; le plan est une proposition, jamais ecrite
 * a l'agenda. Le cadre du jour se donne en le disant a Lorakus (carte de confirmation) ; ici,
 * on peut seulement l'effacer.
 */
import { ApiError, api, type Schemas } from "./client";

export type Today = Schemas["TodayOut"];
export type AgendaEntry = Schemas["AgendaEntryOut"];
export type PlanBlock = Schemas["PlanBlockOut"];
export type PlannedTask = Schemas["TaskOut"];
export type DayFrame = Schemas["FrameOut"];
export type DayBreak = Schemas["BreakOut"];

export async function getToday(): Promise<Today> {
  const { data, response, error } = await api.GET("/api/v1/planning/today");
  if (data === undefined) {
    throw new ApiError(response.status, error);
  }
  return data;
}

/** Efface le cadre d'un jour (`day` : AAAA-MM-JJ) : plus aucun créneau proposé ce jour-là. */
export async function clearDay(day: string): Promise<void> {
  const { response, error } = await api.DELETE("/api/v1/planning/days/{day}", {
    params: { path: { day } },
  });
  if (!response.ok) {
    throw new ApiError(response.status, error);
  }
}
