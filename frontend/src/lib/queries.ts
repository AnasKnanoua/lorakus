import { queryOptions } from "@tanstack/react-query";

import { listAssessments, listCourses } from "@/api/academic";
import { listIdeas, listProjects } from "@/api/projects";
import { getAccountSettings } from "@/api/account";
import { getToday } from "@/api/planning";
import { getConversation, listConversations } from "@/api/assistant";
import { listSubscriptions } from "@/api/calendars";
import { fetchMe } from "@/api/auth";
import { getProposalsEnabled, listFacts, searchFacts } from "@/api/memory";

export const meQuery = queryOptions({
  queryKey: ["me"],
  queryFn: fetchMe,
  staleTime: 5 * 60_000,
});

export const conversationsQuery = queryOptions({
  queryKey: ["assistant", "conversations"],
  queryFn: listConversations,
});

export const conversationQuery = (id: string) =>
  queryOptions({
    queryKey: ["assistant", "conversation", id],
    queryFn: () => getConversation(id),
  });

/** Faits de la memoire ; relus regulierement pour signaler les propositions en attente. */
export const factsQuery = queryOptions({
  queryKey: ["memory", "facts"],
  queryFn: listFacts,
  staleTime: 30_000,
  refetchInterval: 120_000,
});

export const memorySettingsQuery = queryOptions({
  queryKey: ["memory", "settings"],
  queryFn: getProposalsEnabled,
});

/** Recherche par le sens dans la memoire (PR 37b) ; question deja stabilisee par l'appelant. */
export const memorySearchQuery = (q: string) =>
  queryOptions({
    queryKey: ["memory", "search", q],
    queryFn: () => searchFacts(q),
    staleTime: 30_000,
  });

export const accountSettingsQuery = queryOptions({
  queryKey: ["account", "settings"],
  queryFn: getAccountSettings,
  staleTime: 5 * 60_000,
});

/** Abonnements aux calendriers (PR 45) : relus souvent tant qu'une synchronisation attend. */
export const subscriptionsQuery = queryOptions({
  queryKey: ["calendars", "subscriptions"],
  queryFn: listSubscriptions,
  refetchInterval: (query) => (query.state.data?.some((s) => s.status === "pending") ? 5_000 : 60_000),
});

/** Cours (PR 46). */
export const coursesQuery = queryOptions({
  queryKey: ["academic", "courses"],
  queryFn: listCourses,
});

/** Evaluations ouvertes ou terminees (PR 46) ; relues chaque minute : une tache terminee dans
 * le chat termine son evaluation quelques secondes plus tard, par un evenement. */
export const assessmentsQuery = (state: "open" | "done") =>
  queryOptions({
    queryKey: ["academic", "assessments", state],
    queryFn: () => listAssessments(state),
    refetchInterval: 60_000,
  });

/** Ma journee (PR 47) ; relue chaque minute : le plan part de « maintenant ». */
export const todayQuery = queryOptions({
  queryKey: ["planning", "today"],
  queryFn: getToday,
  refetchInterval: 60_000,
});

/** Projets (PR 51) : actifs (le moins avancé d'abord) ou terminés ; relus chaque minute : une
 * tâche terminée dans le chat termine sa tâche de projet quelques secondes plus tard. */
export const projectsQuery = (state: "active" | "done") =>
  queryOptions({
    queryKey: ["projects", "projects", state],
    queryFn: () => listProjects(state),
    refetchInterval: 60_000,
  });

/** Boîte d'idées (PR 51) : dans la boîte, ou archivées. */
export const ideasQuery = (state: "inbox" | "archived") =>
  queryOptions({
    queryKey: ["projects", "ideas", state],
    queryFn: () => listIdeas(state),
  });
