import { queryOptions } from "@tanstack/react-query";

import { getConversation, listConversations } from "@/api/assistant";
import { fetchMe } from "@/api/auth";

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
