import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { markConsulted, type Preparation } from "@/api/preparations";
import { Button } from "@/components/ui/button";
import { clockTime, longDate } from "@/lib/format";
import { preparationsQuery } from "@/lib/queries";

/** Nombre de jours entre deux dates AAAA-MM-JJ (calcul en UTC : aucun décalage horaire). */
function daysBetween(from: string, to: string): number {
  const utc = (iso: string) => {
    const [y = 0, m = 1, d = 1] = iso.split("-").map(Number);
    return Date.UTC(y, m - 1, d);
  };
  return Math.round((utc(to) - utc(from)) / 86_400_000);
}

/** Jour (AAAA-MM-JJ) d'un instant dans le fuseau du compte. */
function dayIn(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).format(
    new Date(iso),
  );
}

/** « à 18:15 », « hier à 22:40 », « lundi 23 novembre à 08:00 ». */
function preparedAt(iso: string, today: string, timeZone: string): string {
  const day = dayIn(iso, timeZone);
  const hour = clockTime(iso, timeZone);
  const offset = daysBetween(day, today);
  if (offset === 0) return `à ${hour}`;
  if (offset === 1) return `hier à ${hour}`;
  return `${longDate(day)} à ${hour}`;
}

function when(day: string, today: string): string {
  const offset = daysBetween(today, day);
  if (offset === 0) return "Aujourd'hui";
  if (offset === 1) return "Demain";
  const text = longDate(day);
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function BriefingCard({
  briefing,
  today,
  timeZone,
  onRead,
}: {
  briefing: Preparation;
  today: string;
  timeZone: string;
  onRead: () => void;
}) {
  const titleId = useId();
  return (
    <article aria-labelledby={titleId} className="rounded-2xl border border-line px-4 py-3">
      <p className="text-sm font-medium text-ink-faint">Briefing · {when(briefing.day, today)}</p>
      <h2 id={titleId} className="text-base font-medium text-ink">
        {briefing.title}
      </h2>
      <div className="mt-2 flex flex-col gap-3">
        {briefing.sections.map((section) => (
          <section key={section.heading}>
            <h3 className="text-sm text-ink-faint">{section.heading}</h3>
            <ul className="mt-0.5 flex flex-col gap-0.5 text-sm text-ink-muted">
              {section.lines.map((line, index) => (
                <li key={`${String(index)}-${line}`} className="[overflow-wrap:anywhere]">
                  {line}
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2">
        <Button variant="outline" size="sm" onClick={onRead}>
          Lu
        </Button>
        <p className="text-xs text-ink-faint">
          Préparé {preparedAt(briefing.prepared_at, today, timeZone)}, par des règles, à partir de ton agenda et de tes
          tâches ; il suit tes changements jusqu'à ce que tu le lises.
        </p>
      </div>
    </article>
  );
}

/**
 * Briefing (P5, scénario 3) : préparé par le Sergent dès que ta journée est finie (celui du
 * lendemain), ou à minuit sans journée décrite. En tête de Ma journée jusqu'à ce que tu le
 * lises ; il ne sonne pas.
 */
export function Briefing({ today, timeZone }: { today: string; timeZone: string }) {
  const preparations = useQuery(preparationsQuery);
  const queryClient = useQueryClient();
  const [failed, setFailed] = useState(false);
  const briefings = (preparations.data ?? []).filter((p) => p.kind === "briefing");
  if (briefings.length === 0) return null;

  async function read(id: string) {
    setFailed(false);
    try {
      await markConsulted(id);
      await queryClient.invalidateQueries({ queryKey: ["preparations"] });
    } catch {
      setFailed(true);
    }
  }

  return (
    <div className="flex flex-col gap-2">
      {briefings.map((briefing) => (
        <BriefingCard
          key={briefing.id}
          briefing={briefing}
          today={today}
          timeZone={timeZone}
          onRead={() => void read(briefing.id)}
        />
      ))}
      {failed && (
        <p role="alert" className="px-3 text-sm text-danger">
          Le briefing n'a pas pu être marqué comme lu. Réessaie.
        </p>
      )}
    </div>
  );
}
