import { useMutation, useQueryClient } from "@tanstack/react-query";

import { enableAssistant } from "@/api/assistant";
import { Orb } from "@/components/Orb";
import { Button } from "@/components/ui/button";

/** Affiche quand le module assistant n'est pas encore active pour ce compte. */
export function EnableAssistant() {
  const queryClient = useQueryClient();
  const enable = useMutation({
    mutationFn: enableAssistant,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["assistant"] }),
  });
  return (
    <div className="relative flex flex-1 flex-col items-center justify-center overflow-hidden px-6 pb-[10vh]">
      <div className="aurora" aria-hidden="true" />
      <div className="relative flex max-w-md animate-fade-up flex-col items-center gap-4 text-center">
        <Orb thinking={enable.isPending} className="size-11" />
        <h1 className="text-[1.5rem] font-semibold tracking-[-0.02em]">Active ton assistant</h1>
        <p className="text-ink-muted">
          Une seule fois, pour discuter avec Lorakus. Tes conversations restent privées, et tu
          peux le désactiver à tout moment.
        </p>
        <Button
          className="mt-2"
          onClick={() => {
            enable.mutate();
          }}
          disabled={enable.isPending}
        >
          Activer l'assistant
        </Button>
        {enable.isError && (
          <p role="alert" className="text-sm text-danger">
            L'activation a échoué. Réessaie dans un instant.
          </p>
        )}
      </div>
    </div>
  );
}
