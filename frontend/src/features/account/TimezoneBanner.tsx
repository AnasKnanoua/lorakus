import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { deviceTimezone, setTimezone } from "@/api/account";
import { Button } from "@/components/ui/button";
import { accountSettingsQuery } from "@/lib/queries";

const DISMISSED_KEY = "lorakus.timezone.dismissed";

/** Fuseau pour lequel l'utilisateur a deja dit « non » sur cet appareil (preference d'affichage). */
function readDismissed(): string | null {
  try {
    return window.localStorage.getItem(DISMISSED_KEY);
  } catch {
    return null;
  }
}

/**
 * Propose d'utiliser le fuseau de l'appareil quand il differe de celui du compte (PR 44).
 * Jamais de changement silencieux : les rappels de nuit lisent le reglage du compte, et un
 * voyage de quelques heures ne doit pas les deplacer sans accord.
 */
export function TimezoneBanner() {
  const settings = useQuery(accountSettingsQuery);
  const queryClient = useQueryClient();
  const [dismissed, setDismissed] = useState(readDismissed);
  const device = deviceTimezone();
  const update = useMutation({
    mutationFn: setTimezone,
    onSuccess: (data) => {
      queryClient.setQueryData(accountSettingsQuery.queryKey, data);
    },
  });

  const current = settings.data?.timezone;
  if (!device || !current || device === current || dismissed === device) {
    return null;
  }

  return (
    <section
      aria-label="Fuseau horaire"
      className="mx-auto mt-2 mb-1 flex w-[min(100%-2rem,42rem)] flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl bg-notice-soft px-4 py-2.5 text-sm text-notice"
    >
      <p className="min-w-0 flex-1">
        Ton appareil est à l'heure de{" "}
        <strong className="font-medium">{device}</strong>, Lorakus utilise{" "}
        <strong className="font-medium">{current}</strong>.
        {update.isError && " Le changement a échoué, réessaie."}
      </p>
      <div className="flex gap-2">
        <Button
          size="sm"
          variant="quiet"
          onClick={() => {
            try {
              window.localStorage.setItem(DISMISSED_KEY, device);
            } catch {
              // Stockage indisponible : la question reviendra au prochain chargement.
            }
            setDismissed(device);
          }}
        >
          Garder
        </Button>
        <Button
          size="sm"
          disabled={update.isPending}
          onClick={() => {
            update.mutate(device);
          }}
        >
          Utiliser ce fuseau
        </Button>
      </div>
    </section>
  );
}
