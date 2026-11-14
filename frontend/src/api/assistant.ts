import { ApiError, api, type Schemas } from "./client";
import { readSse } from "./sse";
import type { ToolAction } from "./tools";

export type Conversation = Schemas["ConversationOut"];
export type ConversationDetail = Schemas["ConversationDetail"];
export type Message = Schemas["MessageOut"];
export type ReplyStatus = "ok" | "interrupted" | "fallback";

export interface ReplyDone {
  messageId: string;
  status: ReplyStatus;
  budgetWarning: boolean;
}

/** Le module assistant n'est pas active pour cet utilisateur (l'API repond 404). */
export class AssistantDisabledError extends Error {
  constructor() {
    super("assistant desactive");
    this.name = "AssistantDisabledError";
  }
}

export async function listConversations(): Promise<Conversation[]> {
  const { data, response, error } = await api.GET("/api/v1/assistant/conversations");
  if (response.status === 404) {
    throw new AssistantDisabledError();
  }
  if (data === undefined) {
    throw new ApiError(response.status, error);
  }
  return data;
}

export async function enableAssistant(): Promise<void> {
  const { response, error } = await api.PUT("/api/v1/modules/{module_id}", {
    params: { path: { module_id: "assistant" } },
    body: { enabled: true },
  });
  if (!response.ok) {
    throw new ApiError(response.status, error);
  }
}

export async function createConversation(): Promise<Conversation> {
  const { data, response, error } = await api.POST("/api/v1/assistant/conversations");
  if (data === undefined) {
    throw new ApiError(response.status, error);
  }
  return data;
}

export async function getConversation(id: string): Promise<ConversationDetail> {
  const { data, response, error } = await api.GET(
    "/api/v1/assistant/conversations/{conversation_id}",
    { params: { path: { conversation_id: id } } },
  );
  if (data === undefined) {
    throw new ApiError(response.status, error);
  }
  return data;
}

export async function deleteConversation(id: string): Promise<void> {
  const { response, error } = await api.DELETE(
    "/api/v1/assistant/conversations/{conversation_id}",
    { params: { path: { conversation_id: id } } },
  );
  if (!response.ok) {
    throw new ApiError(response.status, error);
  }
}

function parseJson(data: string): Record<string, unknown> {
  const value: unknown = JSON.parse(data);
  if (typeof value !== "object" || value === null) {
    throw new Error("evenement invalide");
  }
  return value as Record<string, unknown>;
}

function isStatus(value: unknown): value is ReplyStatus {
  return value === "ok" || value === "interrupted" || value === "fallback";
}

/** Evenement d'outil du flux (tool ou card) -> action affichable, ou null s'il est invalide. */
function toAction(event: string, payload: Record<string, unknown>): ToolAction | null {
  if (typeof payload["tool"] !== "string") {
    return null;
  }
  if (event === "tool" && typeof payload["label"] === "string") {
    return { kind: "activity", tool: payload["tool"], label: payload["label"], ok: payload["ok"] !== false };
  }
  if (
    event === "card" &&
    typeof payload["confirmation_id"] === "string" &&
    typeof payload["summary"] === "string" &&
    typeof payload["expires_at"] === "string"
  ) {
    return {
      kind: "card",
      tool: payload["tool"],
      confirmation_id: payload["confirmation_id"],
      risk: payload["risk"] === "sensitive" ? "sensitive" : "write",
      summary: payload["summary"],
      expires_at: payload["expires_at"],
      status: "pending",
    };
  }
  return null;
}

/**
 * Envoie un message et lit la reponse en flux. onDelta recoit chaque morceau de texte,
 * onAction chaque outil utilise ou carte de confirmation (PR 38).
 * Annuler `signal` coupe la connexion ; le serveur garde alors la reponse partielle.
 */
export async function sendMessage(
  conversationId: string,
  content: string,
  onDelta: (text: string) => void,
  signal?: AbortSignal,
  onAction?: (action: ToolAction) => void,
): Promise<ReplyDone> {
  const { data, response, error } = await api.POST(
    "/api/v1/assistant/conversations/{conversation_id}/messages",
    {
      params: { path: { conversation_id: conversationId } },
      body: { content },
      parseAs: "stream",
      ...(signal ? { signal } : {}),
    },
  );
  if (!response.ok || !data) {
    throw new ApiError(response.status, error);
  }
  for await (const event of readSse(data)) {
    const payload = parseJson(event.data);
    if (event.event === "delta" && typeof payload["text"] === "string") {
      onDelta(payload["text"]);
    } else if (event.event === "tool" || event.event === "card") {
      const action = toAction(event.event, payload);
      if (action) {
        onAction?.(action);
      }
    } else if (event.event === "done") {
      const status = payload["status"];
      return {
        messageId: String(payload["message_id"]),
        status: isStatus(status) ? status : "fallback",
        budgetWarning: payload["budget_warning"] === true,
      };
    }
  }
  // Flux ferme sans evenement de fin : connexion coupee en route.
  return { messageId: "", status: "interrupted", budgetWarning: false };
}
