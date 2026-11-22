/**
 * Bot Telegram (P5, PR 54) : lier son compte par un code, recevoir aussi les rappels (sans
 * détail), délier. Le jeton du bot n'est jamais connu de l'API ni de la page.
 */
import { ApiError, api, type Schemas } from "./client";

export type TelegramStatus = Schemas["TelegramOut"];
export type TelegramCode = Schemas["TelegramCodeOut"];

export async function getTelegram(): Promise<TelegramStatus> {
  const { data, response, error } = await api.GET("/api/v1/telegram");
  if (data === undefined) {
    throw new ApiError(response.status, error);
  }
  return data;
}

export async function newTelegramCode(): Promise<TelegramCode> {
  const { data, response, error } = await api.POST("/api/v1/telegram/code");
  if (data === undefined) {
    throw new ApiError(response.status, error);
  }
  return data;
}

export async function setTelegramNotify(notify: boolean): Promise<TelegramStatus> {
  const { data, response, error } = await api.PUT("/api/v1/telegram", { body: { notify } });
  if (data === undefined) {
    throw new ApiError(response.status, error);
  }
  return data;
}

export async function unlinkTelegram(): Promise<void> {
  const { response, error } = await api.DELETE("/api/v1/telegram");
  if (!response.ok && response.status !== 404) {
    throw new ApiError(response.status, error);
  }
}
