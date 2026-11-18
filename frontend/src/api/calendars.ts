/**
 * Abonnements aux calendriers ICS (PR 45, ADR 0041). L'adresse d'un calendrier n'est envoyee
 * qu'a la creation : le serveur ne la renvoie jamais (seulement son domaine, `hint`).
 */
import { ApiError, ModuleDisabledError, api, type Schemas } from "./client";

export type Subscription = Schemas["SubscriptionOut"];

/** Le module calendars n'est pas active pour cet utilisateur (l'API repond 404). */
export class CalendarsDisabledError extends ModuleDisabledError {
  constructor() {
    super("calendars");
    this.name = "CalendarsDisabledError";
  }
}

/** Refus lisible renvoye par le serveur (adresse refusee, doublon, limite...). */
export class SubscriptionRefusedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SubscriptionRefusedError";
  }
}

function refusal(error: unknown): string | null {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  return typeof detail === "string" ? detail : null;
}

export async function listSubscriptions(): Promise<Subscription[]> {
  const { data, response, error } = await api.GET("/api/v1/calendars/subscriptions");
  if (response.status === 404) {
    throw new CalendarsDisabledError();
  }
  if (data === undefined) {
    throw new ApiError(response.status, error);
  }
  return data;
}

export async function enableCalendars(): Promise<void> {
  const { response, error } = await api.PUT("/api/v1/modules/{module_id}", {
    params: { path: { module_id: "calendars" } },
    body: { enabled: true },
  });
  if (!response.ok) {
    throw new ApiError(response.status, error);
  }
}

export async function addSubscription(name: string, url: string): Promise<Subscription> {
  const { data, response, error } = await api.POST("/api/v1/calendars/subscriptions", {
    body: { name, url },
  });
  if (response.status === 422) {
    throw new SubscriptionRefusedError(refusal(error) ?? "Adresse refusée.");
  }
  if (data === undefined) {
    throw new ApiError(response.status, error);
  }
  return data;
}

export async function syncSubscription(id: string): Promise<Subscription> {
  const { data, response, error } = await api.POST("/api/v1/calendars/subscriptions/{subscription_id}/sync", {
    params: { path: { subscription_id: id } },
  });
  if (data === undefined) {
    throw new ApiError(response.status, error);
  }
  return data;
}

export async function removeSubscription(id: string): Promise<void> {
  const { response, error } = await api.DELETE("/api/v1/calendars/subscriptions/{subscription_id}", {
    params: { path: { subscription_id: id } },
  });
  if (!response.ok) {
    throw new ApiError(response.status, error);
  }
}
