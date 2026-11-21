import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useId, useState, type ReactNode } from "react";

import {
  clearDay,
  type AgendaEntry,
  type DayBreak,
  type DayFrame,
  type PlanBlock,
  type PlannedTask,
  type Today,
} from "@/api/planning";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/features/chat/ConfirmDialog";
import { TopBar } from "@/features/chat/layout";
import { useStartConversation } from "@/features/chat/startConversation";
import { cn } from "@/lib/cn";
import { clockTime, duration, longDate, relativeDay } from "@/lib/format";
import { todayQuery } from "@/lib/queries";
import { NAV_ITEMS } from "@/navigation";

/** Premier message envoyé par « Organiser ma journée avec Lorakus ». */
export const ORGANISE_MESSAGE = "Organise ma journée.";

/**
 * Page « Ma journée » (PR 47 et 49, docs/frontend.md) : le cadre du jour, l'agenda et le plan
 * proposé sur une seule ligne de temps, puis ce qu'il faut estimer, ce qui ne tient pas, les
 * retards et les échéances de la semaine. Le plan est une proposition du serveur, recalculée
 * à chaque lecture et jamais écrite dans l'agenda. Aucune heure n'est supposée : sans cadre,
 * rien n'est placé, et la page propose d'en parler à Lorakus. Jour, heures et retards viennent
 * du serveur (fuseau du compte).
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
  | { kind: "break"; at: string; pause: DayBreak }
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
    ...(data.frame?.breaks ?? []).map((pause): Moment => ({ kind: "break", at: pause.starts_at, pause })),
    ...data.plan.map((block): Moment => ({ kind: "block", at: block.starts_at, block })),
  ].sort((a, b) => new Date(a.at).getTime() - new Date(b.at).getTime());

  const frame = data.frame;
  const over = frame?.ends_at != null && new Date(frame.ends_at).getTime() <= new Date(data.generated_at).getTime();
  return (
    <div className="flex flex-col gap-7">
      <FrameBar data={data} />
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
            {frame?.off
              ? "Pas de travail aujourd'hui : rien n'est proposé."
              : over
                ? "Ta plage de travail est finie."
                : frame === null
                  ? "Rien dans ton agenda aujourd'hui."
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
              ) : moment.kind === "break" ? (
                <BreakLine key={`p-${moment.at}`} pause={moment.pause} timeZone={data.timezone} />
              ) : (
                <BlockLine key={`b-${moment.at}`} block={moment.block} timeZone={data.timezone} />
              ),
            )}
          </ol>
        )}
        {frame?.off && moments.length > 0 && (
          <p className="px-3 pt-3 text-sm text-ink-faint">Pas de travail aujourd'hui : rien n'est proposé.</p>
        )}
        {data.plan.length > 0 && (
          <p className="px-3 pt-3 text-sm text-ink-faint">
            Travail proposé : {duration(data.planned_minutes)}. Rien n'est ajouté à ton agenda.
          </p>
        )}
      </Section>

      {data.unestimated.length > 0 && (
        <Section title="À estimer">
          <TaskList
            label="À estimer"
            items={data.unestimated.map((task) => ({
              task,
              detail: ["durée inconnue", dueText(task)].filter(Boolean).join(" · pour "),
            }))}
          />
          <p className="px-3 pt-2 text-sm text-ink-faint">
            Sans durée, une tâche n'est jamais placée. Dis à Lorakus combien de temps elle te prendra, ou
            demande-lui de l'estimer.
          </p>
        </Section>
      )}

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
    </div>
  );
}

/**
 * Le cadre du jour (PR 49) : ce que tu as dit à Lorakus de ta journée. Il se donne en
 * conversation (une carte demande confirmation) ; ici on le lit, on peut l'effacer, et
 * « Organiser ma journée avec Lorakus » ouvre une conversation qui commence par là.
 */
function FrameBar({ data }: { data: Today }) {
  const queryClient = useQueryClient();
  const conversation = useStartConversation();
  const [clearing, setClearing] = useState(false);
  const frame = data.frame;
  return (
    <div className="flex flex-col gap-3 rounded-2xl bg-raised px-4 py-3.5">
      <div className="flex items-start gap-2">
        <p className={cn("min-w-0 flex-1 pt-1 text-base", frame ? "text-ink" : "text-ink-muted")}>
          {frameText(frame, data)}
        </p>
        {frame && (
          <Button
            variant="quiet"
            size="sm"
            className="-mr-2 shrink-0"
            onClick={() => {
              setClearing(true);
            }}
          >
            Effacer
          </Button>
        )}
      </div>
      <div>
        <Button
          variant={frame ? "outline" : "primary"}
          size="sm"
          disabled={conversation.busy}
          onClick={() => void conversation.start(ORGANISE_MESSAGE)}
        >
          Organiser ma journée avec Lorakus
        </Button>
      </div>
      {conversation.error && (
        <p role="alert" className="text-sm text-danger">
          La conversation n'a pas pu être créée. Vérifie ta connexion, puis réessaie.
        </p>
      )}
      <ConfirmDialog
        open={clearing}
        onOpenChange={setClearing}
        tone="plain"
        title="Effacer le cadre d'aujourd'hui ?"
        description="Plus aucun créneau ne sera proposé aujourd'hui, tant que tu n'auras pas redit à Lorakus quand tu travailles."
        confirmLabel="Effacer"
        failure="Impossible d'effacer le cadre du jour. Réessaie."
        onConfirm={async () => {
          await clearDay(data.day);
          await queryClient.invalidateQueries({ queryKey: ["planning"] });
        }}
      />
    </div>
  );
}

function frameText(frame: DayFrame | null, data: Today): string {
  if (frame === null) {
    return "Tu n'as pas encore dit quand tu travailles aujourd'hui : rien n'est placé, aucune heure n'est supposée.";
  }
  // Un jour sans travail n'a pas d'horaires (contrainte du serveur).
  if (frame.starts_at == null || frame.ends_at == null) return "Pas de travail aujourd'hui.";
  const start = clockTime(frame.starts_at, data.timezone);
  const end = clockTime(frame.ends_at, data.timezone);
  // Une plage qui passe minuit finit « demain » par rapport au jour affiché.
  const endDay = new Intl.DateTimeFormat("en-CA", { timeZone: data.timezone }).format(new Date(frame.ends_at));
  return `Travail de ${start} à ${end}${endDay > data.day ? " (le lendemain)" : ""}.`;
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

function BreakLine({ pause, timeZone }: { pause: DayBreak; timeZone: string }) {
  return (
    // Une pause du cadre (repas, sport...) : ni un créneau de l'agenda, ni du travail ; en retrait.
    <li className="flex min-h-10 items-center gap-3 rounded-xl px-3 py-2 text-ink-faint">
      <Hours start={pause.starts_at} end={pause.ends_at} timeZone={timeZone} />
      <span className="min-w-0 flex-1 truncate text-base">{pause.label}</span>
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
              // Sur deux lignes au besoin : une échéance ne doit pas être coupée sur un téléphone.
              <span className={cn("block text-sm", danger ? "text-danger" : "text-ink-muted")}>
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
