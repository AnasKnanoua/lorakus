import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { newTelegramCode, setTelegramNotify, unlinkTelegram, type TelegramCode } from "@/api/telegram";
import { Button } from "@/components/ui/button";
import { clockTime } from "@/lib/format";
import { telegramQuery } from "@/lib/queries";

/**
 * Telegram (P5, PR 54), dans la page Notifications : envoyer ses idées au bot (elles arrivent
 * dans la boîte à idées), et, si on le veut, y recevoir aussi les rappels, sans aucun détail
 * (les serveurs de Telegram lisent les messages d'un bot).
 */
export function TelegramSection({ timeZone }: { timeZone: string }) {
  const [code, setCode] = useState<TelegramCode | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  // Tant qu'un code attend, on regarde toutes les 5 secondes si la liaison est faite ; plus une fois lié.
  const status = useQuery({
    ...telegramQuery,
    refetchInterval: (query) => (code && !query.state.data?.linked ? 5_000 : false),
  });
  const queryClient = useQueryClient();
  const titleId = useId();
  const notifyId = useId();
  const data = status.data;

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: ["telegram"] });
  }

  async function run(action: () => Promise<unknown>, message: string) {
    setFailed(null);
    try {
      await action();
      await refresh();
    } catch {
      setFailed(message);
    }
  }

  if (!data) return null;
  const linked = data.linked;

  return (
    <section aria-labelledby={titleId} className="flex flex-col gap-2">
      <h2 id={titleId} className="px-3 text-sm font-medium text-ink-faint">
        Telegram
      </h2>
      <div className="flex flex-col items-start gap-2 rounded-2xl bg-raised px-4 py-3.5 text-base">
        {!data.available ? (
          <p className="text-ink-muted">Le bot Telegram n'est pas configuré sur ce serveur.</p>
        ) : linked ? (
          <>
            <p className="text-ink">Ton compte Telegram est lié : envoie une idée au bot, elle arrive dans ta boîte.</p>
            <div className="flex items-start gap-3">
              <input
                id={notifyId}
                type="checkbox"
                className="mt-1 size-4 accent-[var(--accent)]"
                checked={data.notify}
                onChange={(event) => {
                  const next = event.target.checked;
                  void run(() => setTelegramNotify(next), "Ton choix n'a pas pu être enregistré. Réessaie.");
                }}
              />
              <label htmlFor={notifyId} className="text-ink-muted">
                Recevoir aussi les rappels sur Telegram, sans aucun détail (« un rappel t'attend ») : les serveurs de
                Telegram lisent les messages d'un bot.
              </label>
            </div>
            <Button
              variant="quiet"
              size="sm"
              className="-ml-2"
              onClick={() => {
                setCode(null);
                void run(unlinkTelegram, "Le compte n'a pas pu être délié. Réessaie.");
              }}
            >
              Délier Telegram
            </Button>
          </>
        ) : code ? (
          <>
            <p className="text-ink-muted">Envoie ce code à ton bot Telegram :</p>
            <p className="font-mono text-2xl tracking-widest text-ink" aria-label={`Code ${code.code}`}>
              {code.code}
            </p>
            <p className="text-sm text-ink-faint">
              Valable jusqu'à {clockTime(code.expires_at, timeZone)}, une seule fois. La page se met à jour dès que
              c'est fait.
            </p>
          </>
        ) : (
          <>
            <p className="text-ink-muted">
              Envoie tes idées à ton bot Telegram, en un message : elles arrivent dans ta boîte à idées.
            </p>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setFailed(null);
                void newTelegramCode()
                  .then(setCode)
                  .catch(() => {
                    setFailed("Le code n'a pas pu être créé. Réessaie.");
                  });
              }}
            >
              Lier Telegram
            </Button>
          </>
        )}
      </div>
      {failed && (
        <p role="alert" className="px-3 text-sm text-danger">
          {failed}
        </p>
      )}
    </section>
  );
}
