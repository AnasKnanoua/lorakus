import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import { createConversation } from "@/api/assistant";

import { startReply } from "./replies";

/**
 * Démarre une conversation avec un premier message, puis ouvre-la : depuis l'accueil, ou
 * depuis une page qui propose d'en parler à Lorakus (« Organiser ma journée », PR 49). La
 * réponse démarre ici et continue pendant le changement d'écran.
 */
export function useStartConversation() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);

  async function start(text: string) {
    setBusy(true);
    setError(false);
    try {
      const conversation = await createConversation();
      void startReply(queryClient, conversation.id, text);
      await navigate({
        to: "/c/$conversationId",
        params: { conversationId: conversation.id },
        viewTransition: true,
      });
    } catch {
      setError(true);
      setBusy(false);
    }
  }

  return { start, busy, error };
}
