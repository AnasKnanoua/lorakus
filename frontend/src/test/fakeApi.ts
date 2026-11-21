/**
 * Faux backend pour les tests d'ecrans : memes routes, codes et formats que l'API reelle
 * (verifies par ses propres tests, cote backend). Remplace globalThis.fetch.
 */
import { vi } from "vitest";

import type { Schemas } from "@/api/client";

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
  /** La prochaine creation de conversation echoue comme une coupure reseau. */
  failNextCreate: boolean;
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
  /** Exports telecharges (PR 41) : contenu renvoye par GET /api/v1/data/export. */
  exportBody: unknown;
  /** Fuseau du compte (PR 44) ; par defaut celui de l'appareil de test (aucun bandeau). */
  timezone: string;
  /** Module calendars (PR 45) et ses abonnements ; l'adresse n'est jamais renvoyee. */
  calendarsEnabled: boolean;
  subscriptions: FakeSubscription[];
  /** Module academic (PR 46) : cours, evaluations, et le jour qu'il est « chez l'utilisateur ». */
  academicEnabled: boolean;
  courses: FakeCourse[];
  assessments: FakeAssessment[];
  academicToday: string;
  /** Ma journee (PR 47) : ce que rend GET /planning/today, tel quel ; null : refus definitif (403, sans nouvel essai). */
  today: FakeToday | null;
  /** Jours dont le cadre a ete efface par DELETE /planning/days/{day} (PR 49). */
  clearedDays: string[];
  /** Module projects (PR 51) : idees et projets (taches comprises), tels que l'API les rend. */
  projectsEnabled: boolean;
  ideas: FakeIdea[];
  projects: FakeProject[];
}

export type FakeIdea = Schemas["IdeaOut"];
export type FakeProject = Schemas["ProjectOut"];

export type FakeToday = Schemas["TodayOut"];

export function emptyToday(overrides: Partial<FakeToday> = {}): FakeToday {
  return {
    day: "2026-11-18",
    timezone: "Europe/Istanbul",
    generated_at: "2026-11-18T04:30:00Z",
    frame: null,
    agenda: [],
    plan: [],
    planned_minutes: 0,
    unplanned: [],
    unestimated: [],
    overdue: [],
    upcoming: [],
    ...overrides,
  };
}

export interface FakeCourse {
  id: string;
  name: string;
}

export interface FakeAssessment {
  id: string;
  course_id: string;
  kind: "assignment" | "exam";
  title: string;
  due_on: string;
  weight: number | null;
  estimate_minutes: number | null;
  status: "open" | "done";
  completed_at: string | null;
  /** Temps passe envoye a la fin (PR 49) ; absent tant que l'evaluation est ouverte. */
  actual_minutes?: number | null;
}

export interface FakeSubscription {
  id: string;
  name: string;
  hint: string;
  status: "pending" | "ok" | "error";
  error: string | null;
  entries_count: number;
  skipped_count: number;
  truncated: boolean;
  last_attempt_at: string | null;
  last_success_at: string | null;
  next_sync_at: string;
  created_at: string;
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
    failNextCreate: false,
    holdReply: null,
    requests: [],
    facts: [],
    semantic: {},
    proposalsEnabled: true,
    reauthStale: false,
    cards: new Map(),
    traces: new Map(),
    exportBody: { format: 1, account: { email: "anas@example.com" } },
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    calendarsEnabled: true,
    subscriptions: [],
    academicEnabled: true,
    courses: [],
    assessments: [],
    academicToday: "2026-11-18",
    today: emptyToday(),
    clearedDays: [],
    projectsEnabled: true,
    ideas: [],
    projects: [],
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
    if (path === "/api/v1/account/settings" && request.method === "GET") {
      return json(200, { timezone: state.timezone, default_timezone: "Europe/Paris" });
    }
    if (path === "/api/v1/account/timezone" && request.method === "PUT") {
      state.timezone = (body as { timezone: string }).timezone;
      return json(200, { timezone: state.timezone, default_timezone: "Europe/Paris" });
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
      if (state.failNextCreate) {
        state.failNextCreate = false;
        throw new TypeError("Failed to fetch");
      }
      const id = nextId();
      state.conversations.set(id, { id, title: "Nouvelle conversation", messages: [] });
      return json(201, { id, title: "Nouvelle conversation", created_at: NOW, updated_at: NOW });
    }
    // Toutes les conversations (PR 41) : avant la route generale /conversations/{id}.
    if (path === "/api/v1/assistant/conversations" && request.method === "DELETE") {
      if (state.reauthStale) {
        return json(403, { detail: { code: "reauth_required", message: "Confirmez votre identite." } });
      }
      const deleted = state.conversations.size;
      state.conversations.clear();
      for (const card of state.cards.values()) {
        if (card.status === "pending") card.status = "cancelled";
      }
      return json(200, { deleted });
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
    // --- mes donnees (PR 41)
    if (path === "/api/v1/data/export" && request.method === "GET") {
      if (state.reauthStale) {
        return json(403, { detail: { code: "reauth_required", message: "Confirmez votre identite." } });
      }
      return new Response(JSON.stringify(state.exportBody), {
        status: 200,
        headers: {
          "content-type": "application/json",
          "content-disposition": 'attachment; filename="lorakus-export-2026-11-18.json"',
          "cache-control": "no-store",
        },
      });
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
    if (path === "/api/v1/modules/calendars" && request.method === "PUT") {
      state.calendarsEnabled = true;
      return json(200, { id: "calendars", enabled: true, config: {} });
    }
    if (path.startsWith("/api/v1/calendars/") && !state.calendarsEnabled) {
      return json(404, { detail: "Module indisponible." });
    }
    if (path === "/api/v1/calendars/subscriptions" && request.method === "GET") {
      return json(200, state.subscriptions);
    }
    if (path === "/api/v1/calendars/subscriptions" && request.method === "POST") {
      const b = body as { name: string; url: string };
      if (!b.url.startsWith("https://")) {
        return json(422, { detail: "Adresse refusée : l'adresse doit commencer par https://." });
      }
      const created: FakeSubscription = {
        id: nextId(),
        name: b.name,
        hint: `${new URL(b.url).host}/…`,
        status: "pending",
        error: null,
        entries_count: 0,
        skipped_count: 0,
        truncated: false,
        last_attempt_at: null,
        last_success_at: null,
        next_sync_at: NOW,
        created_at: NOW,
      };
      state.subscriptions.push(created);
      return json(201, created);
    }
    const subscription = /^\/api\/v1\/calendars\/subscriptions\/([^/]+)(\/sync)?$/.exec(path);
    if (subscription) {
      const found = state.subscriptions.find((s) => s.id === subscription[1]);
      if (!found) return json(404, { detail: "Calendrier introuvable." });
      if (subscription[2] && request.method === "POST") {
        found.status = "pending";
        return json(202, found);
      }
      if (request.method === "DELETE") {
        state.subscriptions = state.subscriptions.filter((s) => s !== found);
        return new Response(null, { status: 204 });
      }
    }
    if (path === "/api/v1/modules/academic" && request.method === "PUT") {
      state.academicEnabled = true;
      return json(200, { id: "academic", enabled: true, config: {} });
    }
    const day = /^\/api\/v1\/planning\/days\/([0-9-]+)$/.exec(path);
    if (day && request.method === "DELETE") {
      const [, wanted = ""] = day;
      const today = state.today;
      if (today === null || today.day !== wanted || today.frame === null) {
        return json(404, { detail: "Aucun cadre pour ce jour." });
      }
      state.today = { ...today, frame: null, plan: [], planned_minutes: 0 };
      state.clearedDays.push(wanted);
      return new Response(null, { status: 204 });
    }
    if (path === "/api/v1/planning/today" && request.method === "GET") {
      return state.today ? json(200, state.today) : json(403, { detail: "Refusé." });
    }
    if (path === "/api/v1/modules/projects" && request.method === "PUT") {
      state.projectsEnabled = true;
      return json(200, { id: "projects", enabled: true, config: {} });
    }
    if (path.startsWith("/api/v1/projects/")) {
      return projects(request.method, path, url.searchParams, body);
    }
    if (path.startsWith("/api/v1/academic/")) {
      return academic(request.method, path, url.searchParams, body);
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

  // Module academic : memes regles que le serveur pour ce que la page affiche (retard et jours
  // restants calcules ici, doublons refuses, cours emportant ses evaluations).
  const daysLeft = (due: string) =>
    Math.round((Date.parse(`${due}T00:00:00Z`) - Date.parse(`${state.academicToday}T00:00:00Z`)) / 86_400_000);
  const assessmentOut = (a: FakeAssessment) => ({
    ...a,
    course_name: state.courses.find((c) => c.id === a.course_id)?.name ?? "",
    overdue: a.status === "open" && daysLeft(a.due_on) < 0,
    days_left: daysLeft(a.due_on),
  });
  const duplicate = (courseId: string, title: string, due: string, except?: string) =>
    state.assessments.some(
      (a) =>
        a.id !== except &&
        a.status === "open" &&
        a.course_id === courseId &&
        a.due_on === due &&
        a.title.toLowerCase() === title.toLowerCase(),
    );
  const DUPLICATE = { detail: "Cette évaluation existe déjà, avec la même échéance." };

  function academic(method: string, path: string, query: URLSearchParams, body: unknown): Response {
    if (!state.academicEnabled) {
      return json(404, { detail: "Module indisponible." });
    }
    if (path === "/api/v1/academic/courses" && method === "GET") {
      const sorted = [...state.courses].sort((a, b) => a.name.localeCompare(b.name, "fr"));
      return json(
        200,
        sorted.map((c) => ({
          ...c,
          open_assessments: state.assessments.filter((a) => a.course_id === c.id && a.status === "open").length,
        })),
      );
    }
    if (path === "/api/v1/academic/courses" && method === "POST") {
      const name = (body as { name: string }).name.trim();
      if (state.courses.some((c) => c.name.toLowerCase() === name.toLowerCase())) {
        return json(422, { detail: "Tu as déjà un cours de ce nom." });
      }
      const created: FakeCourse = { id: nextId(), name };
      state.courses.push(created);
      return json(201, { ...created, open_assessments: 0 });
    }
    const course = /^\/api\/v1\/academic\/courses\/([^/]+)$/.exec(path);
    if (course && method === "DELETE") {
      if (!state.courses.some((c) => c.id === course[1])) return json(404, { detail: "Cours introuvable." });
      state.courses = state.courses.filter((c) => c.id !== course[1]);
      state.assessments = state.assessments.filter((a) => a.course_id !== course[1]);
      return new Response(null, { status: 204 });
    }
    if (path === "/api/v1/academic/assessments" && method === "GET") {
      const wanted = query.get("state") ?? "open";
      const rows = state.assessments.filter((a) => a.status === wanted);
      rows.sort((a, b) =>
        wanted === "open"
          ? a.due_on.localeCompare(b.due_on)
          : (b.completed_at ?? "").localeCompare(a.completed_at ?? ""),
      );
      return json(200, rows.map(assessmentOut));
    }
    if (path === "/api/v1/academic/assessments" && method === "POST") {
      const b = body as Omit<FakeAssessment, "id" | "status" | "completed_at">;
      if (!state.courses.some((c) => c.id === b.course_id)) return json(404, { detail: "Cours introuvable." });
      if (duplicate(b.course_id, b.title, b.due_on)) return json(422, DUPLICATE);
      const created: FakeAssessment = { ...b, id: nextId(), status: "open", completed_at: null };
      state.assessments.push(created);
      return json(201, assessmentOut(created));
    }
    const one = /^\/api\/v1\/academic\/assessments\/([^/]+)(\/complete)?$/.exec(path);
    const found = one ? state.assessments.find((a) => a.id === one[1]) : undefined;
    if (one && !found) return json(404, { detail: "Évaluation introuvable." });
    if (one && found) {
      if (one[2] && method === "POST") {
        if (found.status === "done") return json(422, { detail: "Cette évaluation est déjà terminée." });
        const sent = body as { actual_minutes?: number } | null;
        found.status = "done";
        found.completed_at = `${state.academicToday}T12:00:00Z`;
        found.actual_minutes = sent?.actual_minutes ?? null;
        return json(200, assessmentOut(found));
      }
      if (method === "PUT") {
        const b = body as Pick<FakeAssessment, "kind" | "title" | "due_on" | "weight" | "estimate_minutes">;
        if (duplicate(found.course_id, b.title, b.due_on, found.id)) return json(422, DUPLICATE);
        Object.assign(found, b);
        return json(200, assessmentOut(found));
      }
      if (method === "DELETE") {
        state.assessments = state.assessments.filter((a) => a !== found);
        return new Response(null, { status: 204 });
      }
    }
    return json(404, { detail: `route inconnue du faux backend : ${method} ${path}` });
  }

  // Module projects (PR 51) : memes regles que le serveur pour ce que la page affiche.
  const NOW_ISO = "2026-11-18T12:00:00Z";
  function counted(project: FakeProject): FakeProject {
    return {
      ...project,
      open_tasks: project.tasks.filter((t) => t.status === "open").length,
      done_tasks: project.tasks.filter((t) => t.status === "done").length,
    };
  }
  function projects(method: string, path: string, query: URLSearchParams, body: unknown): Response {
    if (!state.projectsEnabled) return json(404, { detail: "Module indisponible." });
    if (path === "/api/v1/projects/ideas" && method === "GET") {
      return json(200, state.ideas.filter((i) => i.status === (query.get("state") ?? "inbox")));
    }
    if (path === "/api/v1/projects/ideas" && method === "POST") {
      const text = (body as { text: string }).text.trim();
      if (state.ideas.some((i) => i.status === "inbox" && i.text.toLowerCase() === text.toLowerCase())) {
        return json(422, { detail: "Cette idée est déjà dans ta boîte." });
      }
      const created: FakeIdea = { id: nextId(), text, status: "inbox", created_at: NOW_ISO };
      state.ideas.unshift(created);
      return json(201, created);
    }
    const idea = /^\/api\/v1\/projects\/ideas\/([^/]+)\/archive$/.exec(path);
    if (idea && method === "POST") {
      const found = state.ideas.find((i) => i.id === idea[1]);
      if (!found) return json(404, { detail: "Idée introuvable." });
      found.status = "archived";
      return json(200, found);
    }
    const oneIdea = /^\/api\/v1\/projects\/ideas\/([^/]+)$/.exec(path);
    if (oneIdea && method === "DELETE") {
      if (!state.ideas.some((i) => i.id === oneIdea[1])) return json(404, { detail: "Idée introuvable." });
      state.ideas = state.ideas.filter((i) => i.id !== oneIdea[1]);
      return new Response(null, { status: 204 });
    }
    if (path === "/api/v1/projects/projects" && method === "GET") {
      return json(200, state.projects.filter((p) => p.status === (query.get("state") ?? "active")).map(counted));
    }
    if (path === "/api/v1/projects/projects" && method === "POST") {
      const b = body as { name: string; description?: string | null; idea_id?: string | null };
      const name = b.name.trim();
      if (state.projects.some((p) => p.name.toLowerCase() === name.toLowerCase())) {
        return json(422, { detail: "Tu as déjà un projet de ce nom." });
      }
      const fromIdea = b.idea_id ? state.ideas.find((i) => i.id === b.idea_id) : undefined;
      if (b.idea_id && !fromIdea) return json(404, { detail: "Idée introuvable." });
      state.ideas = state.ideas.filter((i) => i !== fromIdea);
      const created: FakeProject = {
        id: nextId(),
        name,
        description: b.description ?? fromIdea?.text ?? null,
        status: "active",
        open_tasks: 0,
        done_tasks: 0,
        idle_days: null,
        last_activity_at: NOW_ISO,
        finished_at: null,
        tasks: [],
      };
      state.projects.push(created);
      return json(201, created);
    }
    const one = /^\/api\/v1\/projects\/projects\/([^/]+)(\/finish|\/tasks)?$/.exec(path);
    const project = one ? state.projects.find((p) => p.id === one[1]) : undefined;
    if (one && !project) return json(404, { detail: "Projet introuvable." });
    if (one && project) {
      if (one[2] === "/finish" && method === "POST") {
        project.status = "done";
        project.finished_at = NOW_ISO;
        project.idle_days = null;
        for (const t of project.tasks) t.status = "done";
        return json(200, counted(project));
      }
      if (one[2] === "/tasks" && method === "POST") {
        const b = body as { title: string; due_on: string | null; estimate_minutes: number | null };
        const title = b.title.trim();
        if (project.tasks.some((t) => t.status === "open" && t.title.toLowerCase() === title.toLowerCase())) {
          return json(422, { detail: "Cette tâche est déjà ouverte dans ce projet." });
        }
        project.tasks.push({
          id: nextId(),
          title,
          status: "open",
          due_on: b.due_on,
          overdue: b.due_on !== null && b.due_on < "2026-11-18",
          estimate_minutes: b.estimate_minutes,
          completed_at: null,
        });
        project.idle_days = null;
        return json(201, counted(project));
      }
      if (!one[2] && method === "DELETE") {
        state.projects = state.projects.filter((p) => p !== project);
        return new Response(null, { status: 204 });
      }
    }
    const task = /^\/api\/v1\/projects\/tasks\/([^/]+)\/complete$/.exec(path);
    if (task && method === "POST") {
      const owner = state.projects.find((p) => p.tasks.some((t) => t.id === task[1]));
      const found = owner?.tasks.find((t) => t.id === task[1]);
      if (!owner || !found) return json(404, { detail: "Tâche introuvable." });
      found.status = "done";
      found.completed_at = NOW_ISO;
      owner.idle_days = null;
      return json(200, counted(owner));
    }
    const oneTask = /^\/api\/v1\/projects\/tasks\/([^/]+)$/.exec(path);
    if (oneTask && method === "DELETE") {
      const owner = state.projects.find((p) => p.tasks.some((t) => t.id === oneTask[1]));
      if (!owner) return json(404, { detail: "Tâche introuvable." });
      owner.tasks = owner.tasks.filter((t) => t.id !== oneTask[1]);
      return new Response(null, { status: 204 });
    }
    return json(404, { detail: `route inconnue du faux backend : ${method} ${path}` });
  }

  vi.stubGlobal("fetch", vi.fn(handler));
  return state;
}
