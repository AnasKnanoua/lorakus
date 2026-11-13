import { queryOptions } from "@tanstack/react-query";

import { getConversation, listConversations } from "@/api/assistant";
import { fetchMe } from "@/api/auth";
import { getProposalsEnabled, listFacts } from "@/api/memory";

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
