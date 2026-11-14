/**
 * Cartes de confirmation (PR 38) : une action proposee dans le chat n'a lieu qu'apres le clic
 * de l'utilisateur. Ces deux appels sont les seuls moyens de la confirmer ou de la refuser ;
 * le modele n'y a pas acces.
 */
import { api, errorCode, type Schemas } from "./client";

/** Outil d'une reponse : indication (activity) ou carte de confirmation (card). */
export type ToolAction = Schemas["ActionOut"];
export type CardStatus = NonNullable<ToolAction["status"]>;

/** Issue d'un clic : fait, preuve d'identite a redonner, ou refus avec son explication. */
export type CardOutcome = { kind: "done" } | { kind: "reauth" } | { kind: "error"; message: string };

function errorMessage(body: unknown): string {
  if (typeof body === "object" && body !== null && "detail" in body && typeof body.detail === "string") {
    return body.detail;
  }
  return "L'action a échoué. Réessaie.";
}

export async function confirmCard(confirmationId: string): Promise<CardOutcome> {
  const { response, error } = await api.POST("/api/v1/tools/confirmations/{confirmation_id}", {
    params: { path: { confirmation_id: confirmationId } },
  });
  if (response.ok) {
    return { kind: "done" };
  }
  if (response.status === 403 && errorCode(error) === "reauth_required") {
    return { kind: "reauth" };
  }
  return { kind: "error", message: errorMessage(error) };
}

export async function cancelCard(confirmationId: string): Promise<CardOutcome> {
  const { response, error } = await api.POST("/api/v1/tools/confirmations/{confirmation_id}/cancel", {
    params: { path: { confirmation_id: confirmationId } },
  });
  return response.ok ? { kind: "done" } : { kind: "error", message: errorMessage(error) };
}
