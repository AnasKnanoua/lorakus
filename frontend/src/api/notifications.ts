/**
 * Notifications (P5, ADR 0042) : les cartes « À noter » de Ma journée (niveau 1), leur
 * explication (« Pourquoi ? »), et les appareils qui reçoivent les notifications (niveau 2,
 * Web Push). Tout est décidé par le serveur ; ici, on lit et on répond aux cartes.
 */
import { ApiError, api, type Schemas } from "./client";

export type Reminder = Schemas["ReminderOut"];
export type ReminderWhy = Schemas["ReminderWhyOut"];
export type PushInfo = Schemas["PushInfoOut"];
export type PushDevice = Schemas["PushDeviceOut"];
export type CardAction = "seen" | "close" | "later";

export async function listReminders(): Promise<Reminder[]> {
  const { data, response, error } = await api.GET("/api/v1/notifications/cards");
  if (data === undefined) {
    throw new ApiError(response.status, error);
  }
  return data;
}

/** « seen » : affichée ; « close » : OK ; « later » : cachée 3 heures. Toute réponse met fin
 * aux rappels pour cette cause : aucune notification ne suivra. */
export async function answerReminder(id: string, action: CardAction): Promise<void> {
  const { response, error } = await api.POST("/api/v1/notifications/cards/{card_id}/{action}", {
    params: { path: { card_id: id, action } },
  });
  if (!response.ok) {
    throw new ApiError(response.status, error);
  }
}

export async function explainReminder(id: string): Promise<ReminderWhy> {
  const { data, response, error } = await api.GET("/api/v1/notifications/cards/{card_id}/why", {
    params: { path: { card_id: id } },
  });
  if (data === undefined) {
    throw new ApiError(response.status, error);
  }
  return data;
}

export async function getPushInfo(): Promise<PushInfo> {
  const { data, response, error } = await api.GET("/api/v1/notifications/push");
  if (data === undefined) {
    throw new ApiError(response.status, error);
  }
  return data;
}

/** Abonnement rendu par le navigateur (PushSubscription.toJSON()). */
export interface BrowserSubscription {
  endpoint: string;
  keys: { p256dh: string; auth: string };
}

export async function registerDevice(subscription: BrowserSubscription, label: string): Promise<PushDevice> {
  const { data, response, error } = await api.POST("/api/v1/notifications/push/devices", {
    body: { endpoint: subscription.endpoint, keys: subscription.keys, label },
  });
  if (data === undefined) {
    throw new ApiError(response.status, error);
  }
  return data;
}

export async function removeDevice(id: string): Promise<void> {
  const { response, error } = await api.DELETE("/api/v1/notifications/push/devices/{device_id}", {
    params: { path: { device_id: id } },
  });
  if (!response.ok && response.status !== 404) {
    throw new ApiError(response.status, error);
  }
}

export async function sendTestNotification(): Promise<void> {
  const { response, error } = await api.POST("/api/v1/notifications/push/test");
  if (!response.ok) {
    throw new ApiError(response.status, error);
  }
}
