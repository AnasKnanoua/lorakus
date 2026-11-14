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
  actions?: FakeAction[];
}

/** Outil d'une reponse (PR 38), au format de l'API (ActionOut). */
export interface FakeAction {
  kind: "activity" | "card";
  tool: string;
  label?: string;
  ok?: boolean;
  confirmation_id?: string;
  risk?: "write" | "sensitive";
  summary?: string;
  expires_at?: string;
  status?: "pending" | "confirmed" | "cancelled" | "expired";
}

export interface FakeFact {
  id: string;
  content: string;
  category: "identity" | "preference" | "project" | "habit" | "studies" | "other";
  status: "proposed" | "verified";
  source_kind: "manual" | "conversation";
  evidence: string | null;
  from_conversation: string | null;
  created_at: string;
  confirmed_at: string | null;
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
  nextReply: {
    chunks: string[];
    status: "ok" | "interrupted" | "fallback";
    budgetWarning?: boolean;
    /** Outils et cartes envoyes apres le texte, comme les evenements tool et card du serveur. */
    actions?: FakeAction[];
  };
  /** Simule une coupure reseau a l'envoi du prochain message. */
  failNextSend: boolean;
  /** Si defini, le flux s'arrete apres les morceaux de texte jusqu'a ce que la promesse aboutisse. */
  holdReply: Promise<void> | null;
  requests: { method: string; path: string; body: unknown }[];
  facts: FakeFact[];
  /** Recherche par le sens (PR 37b) : question -> identifiants des faits renvoyes, dans l'ordre. */
  semantic: Record<string, string[]>;
  proposalsEnabled: boolean;
  /** Derniere preuve d'identite trop ancienne : « tout oublier » repond 403. */
  reauthStale: boolean;
  /** Cartes de confirmation, par identifiant (PR 38). */
  cards: Map<string, FakeAction>;
  /** Explications des reponses (PR 39), par identifiant de message ; absente : 404. */
  traces: Map<string, unknown>;
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
    facts: [],
    semantic: {},
    proposalsEnabled: true,
    reauthStale: false,
    cards: new Map(),
    traces: new Map(),
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
    const traceMatch = /^\/api\/v1\/assistant\/conversations\/([^/]+)\/messages\/([^/]+)\/trace$/.exec(path);
    if (traceMatch && request.method === "GET") {
      const trace = state.traces.get(traceMatch[2] ?? "");
      return trace === undefined
        ? json(404, { detail: "Aucune explication pour cette réponse." })
        : json(200, trace);
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
      const actions = (reply.actions ?? []).map((a) => ({ ...a }));
      const saved = { ...message("assistant", reply.chunks.join(""), reply.status), actions };
      for (const action of actions) {
        if (action.kind === "card" && action.confirmation_id) {
          state.cards.set(action.confirmation_id, action); // meme objet : son etat suit les clics
        }
      }
      return sse(
        [
          ...reply.chunks.map((t) => ({ event: "delta", data: { text: t } })),
          ...actions.map((a) => ({ event: a.kind === "card" ? "card" : "tool", data: { ...a } })),
        ],
        {
          event: "done",
          data: { message_id: saved.id, status: reply.status, budget_warning: reply.budgetWarning ?? false },
        },
        state.holdReply,
        () => conversation.messages.push(saved),
      );
    }
    // --- memoire (PR 36)
    if (path === "/api/v1/memory/search" && request.method === "GET") {
      const ids = state.semantic[url.searchParams.get("q") ?? ""] ?? [];
      return json(
        200,
        ids.map((id) => state.facts.find((f) => f.id === id)).filter((f) => f !== undefined),
      );
    }
    if (path === "/api/v1/memory/facts" && request.method === "GET") {
      return json(200, state.facts);
    }
    if (path === "/api/v1/memory/facts" && request.method === "POST") {
      const b = body as { content: string; category: FakeFact["category"] };
      if (state.facts.some((f) => f.content.toLowerCase() === b.content.toLowerCase())) {
        return json(409, { detail: { code: "duplicate", message: "Ce fait existe deja." } });
      }
      const created: FakeFact = {
        id: nextId(),
        content: b.content,
        category: b.category,
        status: "verified",
        source_kind: "manual",
        evidence: null,
        from_conversation: null,
        created_at: NOW,
        confirmed_at: NOW,
      };
      state.facts.unshift(created);
      return json(201, created);
    }
    const factMatch = /^\/api\/v1\/memory\/facts\/([^/]+)(\/confirm|\/reject)?$/.exec(path);
    if (factMatch) {
      const fact = state.facts.find((f) => f.id === factMatch[1]);
      if (!fact) {
        return json(404, { detail: "Fait introuvable." });
      }
      const edit = (body ?? {}) as { content?: string | null; category?: FakeFact["category"] | null };
      if (factMatch[2] === "/confirm") {
        fact.content = edit.content ?? fact.content;
        fact.category = edit.category ?? fact.category;
        fact.status = "verified";
        fact.confirmed_at = NOW;
        return json(200, fact);
      }
      if (factMatch[2] === "/reject" || request.method === "DELETE") {
        state.facts = state.facts.filter((f) => f.id !== fact.id);
        return new Response(null, { status: 204 });
      }
      if (request.method === "PATCH") {
        fact.content = edit.content ?? fact.content;
        fact.category = edit.category ?? fact.category;
        return json(200, fact);
      }
    }
    if (path === "/api/v1/memory/settings") {
      if (request.method === "PUT") {
        state.proposalsEnabled = (body as { propose_after_conversations: boolean }).propose_after_conversations;
      }
      return json(200, { propose_after_conversations: state.proposalsEnabled });
    }
    if (path === "/api/v1/memory/forget-all") {
      if (state.reauthStale) {
        return json(403, { detail: "Confirmez votre identite." });
      }
      const deleted = state.facts.length;
      state.facts = [];
      return json(200, { deleted });
    }
    const cardMatch = /^\/api\/v1\/tools\/confirmations\/([^/]+)(\/cancel)?$/.exec(path);
    if (cardMatch && request.method === "POST") {
      const card = state.cards.get(cardMatch[1] ?? "");
      if (!card || card.status !== "pending") {
        return json(409, { detail: "Cette action n'est plus disponible (déjà traitée ou expirée)." });
      }
      if (cardMatch[2] === "/cancel") {
        card.status = "cancelled";
        return new Response(null, { status: 204 });
      }
      if (card.risk === "sensitive" && state.reauthStale) {
        return json(403, { detail: { code: "reauth_required", message: "Confirmez votre identite." } });
      }
      card.status = "confirmed";
      return json(200, { tool: card.tool, risk: card.risk, result: { message: "Fait." } });
    }
    if (path === "/api/v1/auth/reauth") {
      const ok = (body as { password: string }).password === state.password;
      if (ok) {
        state.reauthStale = false;
      }
      return new Response(null, { status: ok ? 204 : 401 });
    }
    return json(404, { detail: `route inconnue du faux backend : ${request.method} ${path}` });
  };

  vi.stubGlobal("fetch", vi.fn(handler));
  return state;
}
