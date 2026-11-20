import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useId, useState, type ReactNode } from "react";

import {
  removePreference,
  type AgendaEntry,
  type Meal,
  type PlanBlock,
  type PlannedTask,
  type Preference,
  type Today,
} from "@/api/planning";
import { Collapsible } from "@/components/Collapsible";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/features/chat/ConfirmDialog";
import { TopBar } from "@/features/chat/layout";
import { cn } from "@/lib/cn";
import { clockTime, duration, longDate, relativeDay } from "@/lib/format";
import { preferencesQuery, todayQuery } from "@/lib/queries";
import { NAV_ITEMS } from "@/navigation";

/**
 * Page « Ma journée » (PR 47, docs/frontend.md) : l'agenda du jour et le plan proposé sur une
 * seule ligne de temps, puis ce qui ne tient pas, les retards et les échéances de la semaine.
 * Lecture seule : le plan est une proposition du serveur, recalculée à chaque lecture et
 * jamais écrite dans l'agenda. Jour, heures et retards viennent du serveur (fuseau du compte).
 */
export function TodayScreen() {
  const today = useQuery(todayQuery);
  return (
    <>
      <TopBar />
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
        <div className="page-enter mx-auto flex max-w-2xl flex-col px-5 pb-16 sm:px-6">
          <header className="pt-2 pb-6">
            <h1 className="text-2xl font-semibold">Ma journée</h1>
            <p className="mt-1 text-sm text-ink-faint first-letter:uppercase">
              {today.data ? longDate(today.data.day) : " "}
            </p>
          </header>
          {today.isPending ? (
            <p className="text-sm text-ink-faint" aria-busy="true">
              Chargement…
            </p>
          ) : today.isError ? (
            <p role="alert" className="text-danger">
              Impossible de charger ta journée. Réessaie dans un instant.
            </p>
          ) : (
            <Day data={today.data} />
          )}
        </div>
      </div>
    </>
  );
}

type Moment =
  | { kind: "event"; at: string; end: string; entry: AgendaEntry }
  | { kind: "meal"; at: string; meal: Meal }
  | { kind: "block"; at: string; block: PlanBlock };

function Day({ data }: { data: Today }) {
  const allDay = data.agenda.filter((e) => e.all_day);
  const moments: Moment[] = [
    ...data.agenda.flatMap((entry): Moment[] =>
      // Une journee entiere n'a pas d'heures : elle est au-dessus, pas dans le deroule.
      entry.starts_at && entry.ends_at
        ? [{ kind: "event", at: entry.starts_at, end: entry.ends_at, entry }]
        : [],
    ),
    ...data.meals.map((meal): Moment => ({ kind: "meal", at: meal.starts_at, meal })),
    ...data.plan.map((block): Moment => ({ kind: "block", at: block.starts_at, block })),
  ].sort((a, b) => new Date(a.at).getTime() - new Date(b.at).getTime());

  return (
    <div className="flex flex-col gap-7">
      <Section title="Déroulé">
        {allDay.length > 0 && (
          <ul aria-label="Toute la journée" className="flex flex-wrap gap-2 px-3 pb-2">
            {allDay.map((entry) => (
              <li key={entry.title} className="rounded-full bg-raised px-3 py-1 text-sm text-ink-muted">
                {entry.title}
              </li>
            ))}
          </ul>
        )}
        {moments.length === 0 ? (
          <p className="px-3 text-base text-ink-muted">
            {data.rest_day
              ? "Jour sans travail : rien n'est proposé aujourd'hui."
              : data.work_ends_at === null && data.unplanned.length > 0
                ? "La journée de travail est finie : le plan reprendra demain matin."
                : "Rien de prévu aujourd'hui."}
          </p>
        ) : (
          <ol aria-label="Déroulé de la journée" className="flex flex-col gap-0.5">
            {moments.map((moment) =>
              moment.kind === "event" ? (
                <EventLine
                  key={`e-${moment.at}-${moment.entry.title}`}
                  entry={moment.entry}
                  start={moment.at}
                  end={moment.end}
                  data={data}
                />
              ) : moment.kind === "meal" ? (
                <MealLine key={`m-${moment.meal.name}`} meal={moment.meal} timeZone={data.timezone} />
              ) : (
                <BlockLine key={`b-${moment.at}`} block={moment.block} timeZone={data.timezone} />
              ),
            )}
          </ol>
        )}
        {data.rest_day && moments.length > 0 && (
          <p className="px-3 pt-3 text-sm text-ink-faint">
            Jour sans travail : rien n'est proposé aujourd'hui.
          </p>
        )}
        {data.plan.length > 0 && (
          <p className="px-3 pt-3 text-sm text-ink-faint">
            Travail proposé : {duration(data.planned_minutes)}. Rien n'est ajouté à ton agenda.
          </p>
        )}
      </Section>

      {data.unplanned.length > 0 && (
        <Section title="Pas de place aujourd'hui">
          <TaskList
            label="Pas de place aujourd'hui"
            items={data.unplanned.map((left) => ({
              task: left.task,
              detail: `reste ${duration(left.minutes)}`,
            }))}
          />
        </Section>
      )}

      {data.overdue.length > 0 && (
        <Section title="En retard">
          <TaskList
            label="En retard"
            items={data.overdue.map((task) => ({ task, detail: dueText(task), danger: true }))}
          />
        </Section>
      )}

      <Section title="Échéances des 7 prochains jours">
        {data.upcoming.length === 0 ? (
          <p className="px-3 text-base text-ink-muted">Aucune échéance cette semaine.</p>
        ) : (
          <TaskList
            label="Échéances des 7 prochains jours"
            items={data.upcoming.map((task) => ({ task, detail: dueText(task) }))}
          />
        )}
      </Section>
      <Preferences />
    </div>
  );
}

/**
 * Ce que le planificateur sait de toi (PR 48) : horaires de travail, repas, jours sans travail,
 * maximum par jour. On les RÈGLE en le disant à Lorakus (une carte demande confirmation) ; ici
 * on les lit et on peut en retirer une.
 */
function Preferences() {
  const queryClient = useQueryClient();
  const preferences = useQuery(preferencesQuery);
  const [removing, setRemoving] = useState<Preference | null>(null);
  if (!preferences.data) return null;
  return (
    <Collapsible title="Mes préférences" defaultOpen={false} headerClassName="px-3">
      <ul aria-label="Mes préférences" className="flex flex-col gap-0.5 pb-2">
        {preferences.data.map((preference) => (
          <li key={preference.key} className="flex min-h-12 items-center gap-3 rounded-xl px-3 py-1.5">
            <span className="min-w-0 flex-1">
              <span className="block truncate text-base text-ink">{preference.label}</span>
              <span className="block truncate text-sm text-ink-muted">
                {preference.value}
                {preference.is_default && <span className="text-ink-faint"> · par défaut</span>}
              </span>
            </span>
            {!preference.is_default && (
              <Button
                variant="quiet"
                size="sm"
                aria-label={`Retirer la préférence ${preference.label}`}
                onClick={() => {
                  setRemoving(preference);
                }}
              >
                Retirer
              </Button>
            )}
          </li>
        ))}
      </ul>
      <p className="px-3 pb-3 text-sm text-ink-faint">
        Pour en changer, dis-le à Lorakus dans une conversation, par exemple : « je déjeune de 12 h 30 à 13 h 30 »
        ou « pas de travail après 21 h ». Une carte te demandera de confirmer.
      </p>
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(isOpen) => {
          if (!isOpen) setRemoving(null);
        }}
        tone="plain"
        title={`Retirer « ${removing?.label ?? ""} » ?`}
        description="La valeur par défaut s'appliquera de nouveau. Tu pourras la redire à Lorakus."
        confirmLabel="Retirer"
        failure="Impossible de retirer cette préférence. Réessaie."
        onConfirm={async () => {
          if (removing) await removePreference(removing.key);
          setRemoving(null);
          await queryClient.invalidateQueries({ queryKey: ["planning"] });
        }}
      />
    </Collapsible>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  const id = useId();
  return (
    <section aria-labelledby={id}>
      <h2 id={id} className="px-3 pb-1 text-sm font-medium text-ink-faint">
        {title}
      </h2>
      {children}
    </section>
  );
}

function dueText(task: PlannedTask): string {
  if (task.due_on == null || task.days_left == null) return "";
  return `${longDate(task.due_on)} (${relativeDay(task.days_left)})`;
}

function Hours({ start, end, timeZone }: { start: string; end: string; timeZone: string }) {
  return (
    <span className="w-[5.75rem] shrink-0 pt-0.5 text-sm text-ink-faint tabular-nums">
      {clockTime(start, timeZone)} – {clockTime(end, timeZone)}
    </span>
  );
}

function EventLine({ entry, start, end, data }: { entry: AgendaEntry; start: string; end: string; data: Today }) {
  // Deja fini a l'heure ou le serveur a calcule la page : en retrait, sans disparaitre.
  const over = new Date(end).getTime() <= new Date(data.generated_at).getTime();
  return (
    <li className={cn("flex min-h-12 items-start gap-3 rounded-xl px-3 py-2.5", over && "opacity-50")}>
      <Hours start={start} end={end} timeZone={data.timezone} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-base text-ink">{entry.title}</span>
        {entry.location && <span className="block truncate text-sm text-ink-faint">{entry.location}</span>}
      </span>
    </li>
  );
}

function MealLine({ meal, timeZone }: { meal: Meal; timeZone: string }) {
  return (
    // Un repas (preference) : ni un creneau de l'agenda, ni du travail ; en retrait.
    <li className="flex min-h-10 items-center gap-3 rounded-xl px-3 py-2 text-ink-faint">
      <Hours start={meal.starts_at} end={meal.ends_at} timeZone={timeZone} />
      <span className="min-w-0 flex-1 truncate text-base">{meal.label}</span>
    </li>
  );
}

function BlockLine({ block, timeZone }: { block: PlanBlock; timeZone: string }) {
  const due = dueText(block.task);
  return (
    // Proposition : fond teinte d'accent, pour ne pas la confondre avec un creneau de l'agenda.
    <li className="flex min-h-12 items-start gap-3 rounded-xl bg-accent-soft px-3 py-2.5">
      <Hours start={block.starts_at} end={block.ends_at} timeZone={timeZone} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-base text-ink">{block.task.title}</span>
        {/* Sur deux lignes au besoin : l'echeance ne doit pas etre coupee sur un telephone. */}
        <span className={cn("block text-sm", block.task.overdue ? "text-danger" : "text-ink-muted")}>
          Proposé · {duration(block.minutes)}
          {block.assumed_duration ? " (durée supposée)" : ""}
          {due ? ` · pour ${due}` : ""}
        </span>
      </span>
    </li>
  );
}

interface TaskItem {
  task: PlannedTask;
  detail: string;
  danger?: boolean;
}

function TaskList({ label, items }: { label: string; items: TaskItem[] }) {
  return (
    <ul aria-label={label} className="flex flex-col gap-0.5">
      {items.map(({ task, detail, danger }) => {
        // Une tache d'un module mene a sa page (ex. Cours), ou elle se corrige et se termine.
        const page = NAV_ITEMS.find((item) => item.id === task.module);
        const body = (
          <>
            <span className="block truncate text-base text-ink">{task.title}</span>
            {detail && (
              <span className={cn("block truncate text-sm", danger ? "text-danger" : "text-ink-muted")}>
                {detail}
              </span>
            )}
          </>
        );
        return (
          <li key={task.id}>
            {page ? (
              <Link
                to={page.to}
                className="block min-h-12 rounded-xl px-3 py-2.5 hover:bg-hover"
                aria-label={`${task.title}, ouvrir ${page.label}`}
              >
                {body}
              </Link>
            ) : (
              <div className="min-h-12 rounded-xl px-3 py-2.5">{body}</div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
