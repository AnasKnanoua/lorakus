import { queryOptions } from "@tanstack/react-query";

import { getAccountSettings } from "@/api/account";
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
