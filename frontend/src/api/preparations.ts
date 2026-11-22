/**
 * Préparations (P5, ADR 0028) : ce que Lorakus a préparé pour toi sans que tu le demandes,
 * aujourd'hui le briefing du lendemain. Lu, il disparaît.
 */
import { ApiError, api, type Schemas } from "./client";

export type Preparation = Schemas["PreparationOut"];

export async function listPreparations(): Promise<Preparation[]> {
  const { data, response, error } = await api.GET("/api/v1/preparations");
  if (data === undefined) {
    throw new ApiError(response.status, error);
  }
  return data;
}

export async function markConsulted(id: string): Promise<void> {
  const { response, error } = await api.POST("/api/v1/preparations/{preparation_id}/consulted", {
    params: { path: { preparation_id: id } },
  });
  if (!response.ok) {
    throw new ApiError(response.status, error);
  }
}
