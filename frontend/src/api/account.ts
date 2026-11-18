/**
 * Reglages du compte (PR 44) : le fuseau horaire, seul fuseau utilise par Lorakus pour dire
 * « aujourd'hui » et pour les travaux de nuit (ADR 0018).
 */
import { ApiError, api, type Schemas } from "./client";

export type AccountSettings = Schemas["AccountSettingsOut"];

export async function getAccountSettings(): Promise<AccountSettings> {
  const { data, response, error } = await api.GET("/api/v1/account/settings");
  if (data === undefined) {
    throw new ApiError(response.status, error);
  }
  return data;
}

export async function setTimezone(timezone: string): Promise<AccountSettings> {
  const { data, response, error } = await api.PUT("/api/v1/account/timezone", {
    body: { timezone },
  });
  if (data === undefined) {
    throw new ApiError(response.status, error);
  }
  return data;
}

/** Fuseau de l'appareil (nom IANA), ou null si le navigateur ne le donne pas. */
export function deviceTimezone(): string | null {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
  } catch {
    return null;
  }
}
