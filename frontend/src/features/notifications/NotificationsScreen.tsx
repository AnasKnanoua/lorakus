import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { ApiError } from "@/api/client";
import { registerDevice, removeDevice, sendTestNotification, type PushDevice } from "@/api/notifications";
import { Button } from "@/components/ui/button";
import { TopBar } from "@/features/chat/layout";
import {
  PushPermissionError,
  currentSubscription,
  deviceLabel,
  pushSupport,
  subscribeThisDevice,
  type PushSupport,
} from "@/lib/push";
import { accountSettingsQuery, pushQuery } from "@/lib/queries";

import { TelegramSection } from "./TelegramSection";

function shortDate(iso: string): string {
  return new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "long" }).format(new Date(iso));
}

interface Notice {
  kind: "status" | "alert";
  text: string;
}

/**
 * Page « Notifications » (P5, ADR 0042), depuis le pied de la barre latérale. Dit en clair
 * quand Lorakus peut te notifier, active les notifications sur CET appareil, liste les
 * appareils abonnés (nom et service, jamais l'adresse d'abonnement) et envoie un test.
 */
export function NotificationsScreen() {
  const push = useQuery(pushQuery);
  const account = useQuery(accountSettingsQuery);
  const queryClient = useQueryClient();
  const [support] = useState<PushSupport>(() => pushSupport());
  const [thisEndpoint, setThisEndpoint] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);

  useEffect(() => {
    if (support !== "supported") return;
    void currentSubscription()
      .then((subscription) => {
        setThisEndpoint(subscription?.endpoint ?? null);
      })
      .catch(() => undefined);
  }, [support]);

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: ["notifications", "push"] });
  }

  async function enable(publicKey: string) {
    setBusy(true);
    setNotice(null);
    try {
      const subscription = await subscribeThisDevice(publicKey);
      await registerDevice(subscription, deviceLabel());
      setThisEndpoint(subscription.endpoint);
      await refresh();
      setNotice({ kind: "status", text: "Notifications activées sur cet appareil." });
    } catch (error) {
      setNotice({
        kind: "alert",
        text:
          error instanceof PushPermissionError
            ? "Tu as refusé les notifications : autorise-les dans les réglages du navigateur pour ce site."
            : error instanceof ApiError && error.status === 409
              ? "Trop d'appareils abonnés : retire-en un avant d'ajouter celui-ci."
              : "L'activation a échoué. Réessaie.",
      });
    } finally {
      setBusy(false);
    }
  }

  async function forget(device: PushDevice) {
    setNotice(null);
    try {
      await removeDevice(device.id);
      await refresh();
    } catch {
      setNotice({ kind: "alert", text: "L'appareil n'a pas pu être retiré. Réessaie." });
    }
  }

  async function test() {
    setNotice(null);
    try {
      await sendTestNotification();
      setNotice({ kind: "status", text: "Notification de test envoyée : elle arrive dans la minute." });
    } catch {
      setNotice({ kind: "alert", text: "Le test n'a pas pu être envoyé. Réessaie." });
    }
  }

  const data = push.data;
  return (
    <>
      <TopBar />
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
        <div className="page-enter mx-auto flex max-w-2xl flex-col gap-7 px-5 pb-16 sm:px-6">
          <header className="pt-2">
            <h1 className="text-2xl font-semibold">Notifications</h1>
          </header>

          <section className="flex flex-col gap-2 text-base text-ink-muted">
            <p>
              Un rappel apparaît d'abord dans <strong className="font-medium text-ink">Ma journée</strong>. Une
              notification ne part que s'il n'a pas été vu pendant 24 heures, une seule fois par rappel.
            </p>
            <p>
              Jamais en dehors de la plage de travail que tu as donnée pour la journée, ni pendant tes pauses, et trois
              par jour au plus. Sans journée donnée, ou un jour sans travail, aucune notification.
            </p>
          </section>

          {push.isPending ? (
            <p className="text-sm text-ink-faint" aria-busy="true">
              Chargement…
            </p>
          ) : push.isError ? (
            <p role="alert" className="text-danger">
              Impossible de charger tes appareils. Réessaie dans un instant.
            </p>
          ) : (
            <>
              <section className="flex flex-col gap-3 rounded-2xl bg-raised px-4 py-3.5">
                {!data?.available || !data.public_key ? (
                  <p className="text-base text-ink-muted">Les notifications ne sont pas disponibles sur ce serveur.</p>
                ) : support === "unsupported" ? (
                  <p className="text-base text-ink-muted">
                    Ce navigateur ne sait pas recevoir de notifications. Sur un iPhone, ajoute d'abord Lorakus à
                    l'écran d'accueil.
                  </p>
                ) : support === "denied" ? (
                  <p className="text-base text-ink-muted">
                    Les notifications sont bloquées pour ce site : autorise-les dans les réglages du navigateur.
                  </p>
                ) : thisEndpoint !== null ? (
                  <div className="flex flex-col items-start gap-2">
                    <p className="text-base text-ink">Cet appareil est abonné aux notifications.</p>
                    {/* Le serveur oublie un abonnement que le navigateur a retiré : le renvoyer. */}
                    <Button
                      variant="quiet"
                      size="sm"
                      className="-ml-2"
                      disabled={busy}
                      onClick={() => {
                        if (data.public_key) void enable(data.public_key);
                      }}
                    >
                      Réenregistrer cet appareil
                    </Button>
                  </div>
                ) : (
                  <div className="flex flex-col items-start gap-2">
                    <p className="text-base text-ink-muted">Cet appareil ne reçoit pas encore les notifications.</p>
                    <Button
                      variant="primary"
                      size="sm"
                      disabled={busy}
                      onClick={() => {
                        if (data.public_key) void enable(data.public_key);
                      }}
                    >
                      <BellRing aria-hidden="true" />
                      Activer sur cet appareil
                    </Button>
                  </div>
                )}
              </section>

              <section aria-labelledby="devices-title">
                <h2 id="devices-title" className="px-3 pb-1 text-sm font-medium text-ink-faint">
                  Appareils
                </h2>
                {data?.devices.length ? (
                  <ul aria-label="Appareils" className="flex flex-col gap-0.5">
                    {data.devices.map((device) => (
                      <li key={device.id} className="flex min-h-12 items-center gap-3 rounded-xl px-3 py-2">
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-base text-ink">{device.label}</span>
                          <span className="block truncate text-sm text-ink-faint">
                            {device.last_success_at
                              ? `Dernière notification le ${shortDate(device.last_success_at)}`
                              : "Aucune notification reçue pour l'instant"}
                          </span>
                        </span>
                        <Button
                          variant="quiet"
                          size="icon-sm"
                          aria-label={`Retirer ${device.label}`}
                          onClick={() => void forget(device)}
                        >
                          <Trash2 aria-hidden="true" />
                        </Button>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="px-3 text-base text-ink-muted">Aucun appareil.</p>
                )}
                {data && data.devices.length > 0 && (
                  <div className="px-3 pt-3">
                    <Button variant="outline" size="sm" onClick={() => void test()}>
                      Envoyer une notification de test
                    </Button>
                  </div>
                )}
              </section>
            </>
          )}
          {account.data && <TelegramSection timeZone={account.data.timezone} />}
          {notice && (
            <p role={notice.kind} className={notice.kind === "alert" ? "text-sm text-danger" : "text-sm text-ink-muted"}>
              {notice.text}
            </p>
          )}
        </div>
      </div>
    </>
  );
}
