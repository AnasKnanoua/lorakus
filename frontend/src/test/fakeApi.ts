/**
 * Faux backend pour les tests d'ecrans : memes routes, codes et formats que l'API reelle
 * (verifies par ses propres tests, cote backend). Remplace globalThis.fetch.
 */
import { vi } from "vitest";

export interface FakeMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: "ok" | "interrupted" | "fallback";
  model: string | null;
  cost_usd: string | null;
  created_at: string;
}

export interface FakeState {
  loggedIn: boolean;
  password: string;
  secondFactor: string | null;
  /** Production : la double authentification doit etre activee avant toute connexion. */
  secondFactorSetupRequired: boolean;
  assistantEnabled: boolean;
  conversations: Map<string, { id: string; title: string; messages: FakeMessage[] }>;
  /** Reponse que le prochain message recevra, decoupee en morceaux de flux. */
  nextReply: { chunks: string[]; status: "ok" | "interrupted" | "fallback"; budgetWarning?: boolean };
  /** Simule une coupure reseau a l'envoi du prochain message. */
  failNextSend: boolean;
  /** Si defini, le flux s'arrete apres les morceaux de texte jusqu'a ce que la promesse aboutisse. */
  holdReply: Promise<void> | null;
  requests: { method: string; path: string; body: unknown }[];
}

const NOW = "2026-11-12T12:00:00Z";

function json(status: number, body: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function sse(
  deltas: { event: string; data: unknown }[],
  done: { event: string; data: unknown },
  hold: Promise<void> | null,
  onDone: () => void,
): Response {
  const encoder = new TextEncoder();
  const send = (controller: ReadableStreamDefaultController<Uint8Array>, e: { event: string; data: unknown }) => {
    // Chaque evenement dans son propre morceau, comme sur le reseau.
    controller.enqueue(encoder.encode(`event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`));
  };
  const body = new ReadableStream<Uint8Array>({
    async start(controller) {
      for (const e of deltas) send(controller, e);
      if (hold) await hold;
      onDone(); // comme le serveur : la reponse n'est enregistree qu'a la fin du flux
      send(controller, done);
      controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
}

export function installFakeApi(overrides: Partial<FakeState> = {}): FakeState {
  const state: FakeState = {
    loggedIn: false,
    password: "un mot de passe assez long",
    secondFactor: null,
    secondFactorSetupRequired: false,
    assistantEnabled: true,
    conversations: new Map(),
    nextReply: { chunks: ["Bonjour", " Anas."], status: "ok" },
    failNextSend: false,
    holdReply: null,
    requests: [],
    ...overrides,
  };
  let counter = 0;
  const nextId = () => `00000000-0000-4000-8000-${String(++counter).padStart(12, "0")}`;

  const handler = async (input: RequestInfo | URL): Promise<Response> => {
    const request = input instanceof Request ? input : new Request(input);
    const url = new URL(request.url, "http://localhost");
    const text = request.method === "GET" || request.method === "DELETE" ? "" : await request.text();
    const body: unknown = text ? JSON.parse(text) : undefined;
    state.requests.push({ method: request.method, path: url.pathname, body });
    const path = url.pathname;

    if (path === "/api/v1/auth/login" && request.method === "POST") {
      const b = body as { password: string; second_factor?: string };
      if (b.password !== state.password) {
        return json(401, { detail: "Identifiants invalides." });
      }
      if (state.secondFactorSetupRequired) {
        return json(403, { detail: { code: "second_factor_setup_required", message: "A activer." } });
      }
      if (state.secondFactor && b.second_factor !== state.secondFactor) {
        return json(401, { detail: { code: "second_factor_required", message: "Code requis." } });
      }
      state.loggedIn = true;
      return new Response(null, { status: 204 });
    }
    if (!state.loggedIn) {
      return json(401, { detail: "Session absente ou expiree." });
    }
    if (path === "/api/v1/auth/me") {
      return json(200, { id: "u1", email: "anas@example.com", role: "owner", totp_enabled: false });
    }
    if (path === "/api/v1/auth/logout") {
      state.loggedIn = false;
      return new Response(null, { status: 204 });
    }
    if (path === "/api/v1/modules/assistant" && request.method === "PUT") {
      state.assistantEnabled = true;
      return json(200, { id: "assistant", enabled: true, config: {} });
    }
    if (path.startsWith("/api/v1/assistant/") && !state.assistantEnabled) {
      return json(404, { detail: "Module indisponible." });
    }
    if (path === "/api/v1/assistant/conversations" && request.method === "GET") {
      return json(
        200,
        [...state.conversations.values()].reverse().map((c) => ({
          id: c.id,
          title: c.title,
          created_at: NOW,
          updated_at: NOW,
        })),
      );
    }
    if (path === "/api/v1/assistant/conversations" && request.method === "POST") {
      const id = nextId();
      state.conversations.set(id, { id, title: "Nouvelle conversation", messages: [] });
      return json(201, { id, title: "Nouvelle conversation", created_at: NOW, updated_at: NOW });
    }
    const match = /^\/api\/v1\/assistant\/conversations\/([^/]+)(\/messages)?$/.exec(path);
    const conversation = match?.[1] ? state.conversations.get(match[1]) : undefined;
    if (match && !conversation) {
      return json(404, { detail: "Conversation introuvable." });
    }
    if (conversation && !match?.[2] && request.method === "GET") {
      return json(200, { ...conversation, created_at: NOW, updated_at: NOW });
    }
    if (conversation && !match?.[2] && request.method === "DELETE") {
      state.conversations.delete(conversation.id);
      return new Response(null, { status: 204 });
    }
    if (conversation && match?.[2] && request.method === "POST") {
      if (state.failNextSend) {
        state.failNextSend = false;
        throw new TypeError("Failed to fetch");
      }
      const content = (body as { content: string }).content;
      if (conversation.messages.length === 0) {
        conversation.title = content.slice(0, 60);
      }
      const message = (role: "user" | "assistant", text: string, status: FakeMessage["status"]) => ({
        id: nextId(),
        role,
        content: text,
        status,
        model: role === "assistant" ? "claude-haiku-5-5" : null,
        cost_usd: null,
        created_at: NOW,
      });
      const reply = state.nextReply;
      // Comme le serveur : le message de l'utilisateur est enregistre des le debut du tour.
      conversation.messages.push(message("user", content, "ok"));
      const saved = message("assistant", reply.chunks.join(""), reply.status);
      return sse(
        reply.chunks.map((t) => ({ event: "delta", data: { text: t } })),
        {
          event: "done",
          data: { message_id: saved.id, status: reply.status, budget_warning: reply.budgetWarning ?? false },
        },
        state.holdReply,
        () => conversation.messages.push(saved),
      );
    }
    return json(404, { detail: `route inconnue du faux backend : ${request.method} ${path}` });
  };

  vi.stubGlobal("fetch", vi.fn(handler));
  return state;
}
