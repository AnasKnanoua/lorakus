import { Orb } from "@/components/Orb";

import { Composer } from "./Composer";
import { TopBar } from "./layout";
import { useStartConversation } from "./startConversation";

/**
 * Accueil : la question et le champ de saisie au centre de la zone principale (barre
 * laterale exclue), sur une lumiere d'aurore. Au premier envoi, le navigateur fait glisser le
 * champ vers le bas de la conversation (transition « composer », voir Composer).
 */
export function NewConversationScreen() {
  const { start, busy, error } = useStartConversation();

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
          {/* Rien sous le champ hors erreur : l'accueil se limite a la question et au champ. */}
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
              ) : null
            }
          />
        </div>
      </div>
    </div>
  );
}
