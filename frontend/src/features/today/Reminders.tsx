import * as Dialog from "@radix-ui/react-dialog";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import { answerReminder, explainReminder, type CardAction, type Reminder, type ReminderWhy } from "@/api/notifications";
import { Button } from "@/components/ui/button";
import { remindersQuery } from "@/lib/queries";

/** Où en est une cause, en clair (raison enregistrée par le serveur). */
export const OUTCOMES: Record<string, string> = {
  level1_pending: "La carte attend d'être vue : une notification ne partira qu'après 24 heures sans réponse.",
  seen: "Tu as vu la carte : aucune notification ne suivra.",
  closed: "Tu as fermé la carte : aucune notification ne suivra.",
  postponed: "Tu l'as repoussée : aucune notification ne suivra.",
  escalated: "Une notification est partie ; il n'y en aura pas d'autre.",
  ignored_24h: "Une notification est partie ; il n'y en aura pas d'autre.",
  no_frame: "Tu n'as pas dit quand tu travailles aujourd'hui : aucune notification en attendant.",
  day_off: "Jour sans travail : aucune notification aujourd'hui.",
  before_work: "Ta plage de travail n'a pas commencé : la notification attend.",
  after_work: "Ta plage de travail est finie : la notification attend.",
  break: "Tu es en pause : la notification attend la fin de la pause.",
  budget: "Trois notifications aujourd'hui : la suivante attend demain.",
  no_device: "Aucun appareil ne reçoit les notifications : la carte suffit.",
  sensitive: "Donnée sensible : elle reste dans l'application, jamais en notification.",
  expired: "L'échéance est passée.",
  subject_gone: "La tâche est terminée ou supprimée.",
  no_longer_due: "La tâche est commencée ou n'est plus à rendre dans les 3 jours.",
  module_disabled: "Le module qui l'avait signalée est désactivé.",
};

const DECISIONS: Record<string, string> = {
  new: "carte ajoutée à Ma journée",
  ignored_24h: "carte non vue pendant 24 heures, pendant ta plage de travail",
  test: "notification de test demandée",
};

/** Jour et heure dans le fuseau du COMPTE (comme le reste de Ma journée), pas de l'appareil. */
function at(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat("fr-FR", { weekday: "long", hour: "2-digit", minute: "2-digit", timeZone }).format(
    new Date(iso),
  );
}

function plural(count: number, one: string, many: string): string {
  return `${String(count)} ${count > 1 ? many : one}`;
}

function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-5">
      <h3 className="text-sm font-medium text-ink-faint">{title}</h3>
      <div className="mt-2 text-base">{children}</div>
    </section>
  );
}

function WhyBody({ why, timeZone }: { why: ReminderWhy; timeZone: string }) {
  return (
    <>
      <Block title="Règle">
        <p className="[overflow-wrap:anywhere]">{why.rule}</p>
      </Block>
      <Block title="Ce qui a été lu">
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
          {why.facts.map((fact) => (
            <div key={fact.label} className="contents">
              <dt className="text-ink-faint">{fact.label}</dt>
              <dd className="[overflow-wrap:anywhere]">
                {fact.value}
                <span className="text-sm text-ink-faint">
                  {" "}
                  · {fact.source}
                  {fact.measured ? "" : ", estimé"}
                </span>
              </dd>
            </div>
          ))}
        </dl>
      </Block>
      <Block title="Décisions">
        <ul className="flex flex-col gap-1">
          {why.interventions.map((step) => (
            <li key={step.level}>
              <span className="first-letter:uppercase">{at(step.at, timeZone)}</span>
              {" : "}
              {step.channel === "app"
                ? "carte dans Ma journée"
                : `notification, reçue par ${plural(step.delivered, "appareil", "appareils")}`}
              <span className="text-ink-faint"> ({DECISIONS[step.reason] ?? step.reason})</span>
            </li>
          ))}
        </ul>
        {why.outcome && OUTCOMES[why.outcome] && <p className="mt-2 text-sm text-ink-muted">{OUTCOMES[why.outcome]}</p>}
      </Block>
      <p className="mt-5 text-xs text-ink-faint">Calculé par des règles : aucun modèle de langage n'a décidé de ce rappel.</p>
    </>
  );
}

function WhyContent({ id, timeZone }: { id: string; timeZone: string }) {
  const why = useQuery({ queryKey: ["notifications", "why", id], queryFn: () => explainReminder(id) });
  if (why.isPending) return <p className="mt-4 text-ink-muted">Chargement…</p>;
  if (why.isError) {
    return (
      <p role="alert" className="mt-4 text-sm text-danger">
        L'explication n'a pas pu être chargée. Réessaie plus tard.
      </p>
    );
  }
  return <WhyBody why={why.data} timeZone={timeZone} />;
}

function WhyDialog({ reminder, timeZone }: { reminder: Reminder; timeZone: string }) {
  const [open, setOpen] = useState(false);
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <Button variant="quiet" size="sm" aria-label={`Pourquoi ce rappel : ${reminder.title} ?`}>
          Pourquoi ?
        </Button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="scrim fixed inset-0 z-40 bg-[var(--scrim)] backdrop-blur-[2px]" />
        <Dialog.Content className="fixed inset-x-4 bottom-4 z-50 mx-auto max-h-[80dvh] max-w-md animate-fade-up overflow-y-auto rounded-3xl border border-line bg-raised p-6 shadow-float sm:top-[15%] sm:bottom-auto">
          <div className="flex items-start justify-between gap-4">
            <Dialog.Title className="text-lg font-semibold tracking-[-0.01em]">Pourquoi ce rappel ?</Dialog.Title>
            <Dialog.Close asChild>
              <Button variant="quiet" size="icon-sm" aria-label="Fermer">
                <X aria-hidden="true" />
              </Button>
            </Dialog.Close>
          </div>
          <Dialog.Description className="mt-1 text-sm text-ink-muted">{reminder.title}</Dialog.Description>
          {open && <WhyContent id={reminder.id} timeZone={timeZone} />}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/**
 * « À noter » (P5, ADR 0042) : les rappels de niveau 1, en tête de Ma journée. Une carte
 * affichée compte comme vue : aucune notification ne la suivra. « OK » la ferme, « Plus tard »
 * la cache trois heures. Trois au plus, choisies par le serveur.
 */
export function Reminders({ timeZone }: { timeZone: string }) {
  const reminders = useQuery(remindersQuery);
  const queryClient = useQueryClient();
  const marked = useRef(new Set<string>());
  const [failed, setFailed] = useState(false);
  const titleId = useId();

  useEffect(() => {
    for (const reminder of reminders.data ?? []) {
      if (!marked.current.has(reminder.id)) {
        marked.current.add(reminder.id);
        // Affichée = vue. Un échec ici n'a rien de grave : au pire, une notification suivra.
        void answerReminder(reminder.id, "seen").catch(() => undefined);
      }
    }
  }, [reminders.data]);

  if (!reminders.data || reminders.data.length === 0) return null;

  async function answer(id: string, action: CardAction) {
    setFailed(false);
    try {
      await answerReminder(id, action);
      await queryClient.invalidateQueries({ queryKey: ["notifications", "cards"] });
    } catch {
      setFailed(true);
    }
  }

  return (
    <section aria-labelledby={titleId}>
      <h2 id={titleId} className="px-3 pb-1 text-sm font-medium text-ink-faint">
        À noter
      </h2>
      <ul aria-label="À noter" className="flex flex-col gap-2">
        {reminders.data.map((reminder) => (
          <li key={reminder.id} className="rounded-2xl border border-line px-4 py-3">
            <p className="text-base font-medium text-ink">{reminder.title}</p>
            <p className="mt-0.5 text-sm text-ink-muted [overflow-wrap:anywhere]">{reminder.body}</p>
            <div className="mt-2 -ml-2 flex flex-wrap items-center gap-1">
              <Button variant="outline" size="sm" className="ml-2" onClick={() => void answer(reminder.id, "close")}>
                OK
              </Button>
              <Button variant="quiet" size="sm" onClick={() => void answer(reminder.id, "later")}>
                Plus tard
              </Button>
              <WhyDialog reminder={reminder} timeZone={timeZone} />
            </div>
          </li>
        ))}
      </ul>
      {failed && (
        <p role="alert" className="px-3 pt-2 text-sm text-danger">
          Ta réponse n'a pas pu être enregistrée. Réessaie.
        </p>
      )}
    </section>
  );
}
