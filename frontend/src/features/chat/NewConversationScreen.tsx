import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import { createConversation } from "@/api/assistant";
import { Orb } from "@/components/Orb";

import { Composer } from "./Composer";
import { TopBar } from "./layout";
import { startReply } from "./replies";

/**
 * Accueil : la question et le champ de saisie au centre de la zone principale (barre
 * laterale exclue), sur une lumiere d'aurore. Au premier envoi, le navigateur fait glisser le
 * champ vers le bas de la conversation (transition « composer », voir Composer).
 */
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

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <div className="aurora" aria-hidden="true" />
      <TopBar />
      <div className="relative flex flex-1 flex-col items-center justify-center px-4 pb-[14vh]">
        <div className="flex w-full max-w-[680px] animate-fade-up flex-col items-center">
          <Orb className="mb-6 size-11" thinking={busy} />
          <h1 className="mb-8 text-center text-[1.75rem] leading-tight font-medium tracking-[-0.025em] text-balance sm:text-[2.125rem]">
            Que puis-je faire pour toi aujourd'hui&nbsp;?
          </h1>
          <Composer
            variant="hero"
            onSend={(text) => void start(text)}
            disabled={busy}
            autoFocus
            footer={
              error ? (
                <p role="alert" className="mt-3 text-center text-sm text-danger">
                  La conversation n'a pas pu être créée. Vérifie ta connexion, puis réessaie.
                </p>
              ) : (
                <p className="mt-4 text-center text-[0.8125rem] text-ink-faint">
                  Lorakus n'a pas encore accès à ton agenda ni à tes notes.
                </p>
              )
            }
          />
        </div>
      </div>
    </div>
  );
}
