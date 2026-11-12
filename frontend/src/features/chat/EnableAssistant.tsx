import { useMutation, useQueryClient } from "@tanstack/react-query";

import { enableAssistant } from "@/api/assistant";
import { Monogram } from "@/components/Monogram";
import { Button } from "@/components/ui/button";

/** Affiche quand le module assistant n'est pas encore active pour ce compte. */
export function EnableAssistant() {
  const queryClient = useQueryClient();
  const enable = useMutation({
    mutationFn: enableAssistant,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["assistant"] }),
  });
  return (
    <div className="mx-auto flex max-w-md flex-col items-start gap-4 px-6 py-16">
      <Monogram className="size-10" />
      <h1 className="text-xl font-bold">L'assistant n'est pas encore activé</h1>
      <p className="text-ink-muted">
        Activez-le pour discuter avec Lorakus. Vos conversations restent privées et vous pouvez le
        désactiver à tout moment.
      </p>
      <Button onClick={() => { enable.mutate(); }} disabled={enable.isPending}>
        Activer l'assistant
      </Button>
      {enable.isError && (
        <p role="alert" className="text-sm text-danger">
          L'activation a échoué. Réessayez dans un instant.
        </p>
      )}
    </div>
  );
}
