/**
 * Client de l'API, type depuis le contrat OpenAPI du backend (schema.d.ts, genere).
 * Seul fichier autorise a toucher a fetch (regle ESLint du projet).
 */
import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

export type Schemas = components["schemas"];

export const api = createClient<paths>({
  // Origine de la page, explicite : identique a une adresse relative dans le navigateur, et
  // indispensable hors navigateur (tests), ou fetch refuse une adresse sans origine.
  baseUrl: globalThis.location.origin,
  // Cookie de session __Host- : meme origine uniquement.
  credentials: "same-origin",
  // Resolu a chaque appel (et non capture a l'import) : les tests peuvent le remplacer.
  fetch: (request: Request) => globalThis.fetch(request),
});

/** Erreur HTTP de l'API, avec le detail renvoye par le serveur. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown) {
    super(`API ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

/** Champ `code` d'un detail d'erreur structure ({ code, message }), s'il existe. */
export function errorCode(body: unknown): string | undefined {
  if (typeof body !== "object" || body === null || !("detail" in body)) {
    return undefined;
  }
  const inner = body.detail;
  if (typeof inner !== "object" || inner === null || !("code" in inner)) {
    return undefined;
  }
  return typeof inner.code === "string" ? inner.code : undefined;
}
