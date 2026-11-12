import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import { createConversation } from "@/api/assistant";
import { Monogram } from "@/components/Monogram";
import { startReply } from "./replies";

import { Composer } from "./Composer";

export function NewConversationScreen() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);

  async function start(text: string) {
    setBusy(true);
    setError(false);
    try {
      const conversation = await createConversation();
      // La reponse demarre ici et continue pendant le changement d'ecran.
      void startReply(queryClient, conversation.id, text);
      await navigate({ to: "/c/$conversationId", params: { conversationId: conversation.id } });
    } catch {
      setError(true);
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-1 flex-col items-start justify-end gap-3 px-6 pb-8 sm:mx-auto sm:w-full sm:max-w-3xl sm:justify-center">
        <Monogram className="size-10" />
        <h1 className="text-2xl font-bold">De quoi avez-vous besoin ?</h1>
        <p className="text-ink-muted">
          Posez une question ou confiez une tâche. Lorakus n'a pas encore accès à votre agenda ni
          à vos notes.
        </p>
        {error && (
          <p role="alert" className="text-sm text-danger">
            La conversation n'a pas pu être créée. Vérifiez votre connexion, puis réessayez.
          </p>
        )}
      </div>
      <Composer onSend={(text) => void start(text)} disabled={busy} autoFocus />
    </div>
  );
}
