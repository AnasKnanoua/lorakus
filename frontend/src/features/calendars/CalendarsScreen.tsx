import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarSync, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useId, useState } from "react";

import {
  CalendarsDisabledError,
  SubscriptionRefusedError,
  addSubscription,
  enableCalendars,
  removeSubscription,
  syncSubscription,
  type Subscription,
} from "@/api/calendars";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ConfirmDialog } from "@/features/chat/ConfirmDialog";
import { TopBar } from "@/features/chat/layout";
import { subscriptionsQuery } from "@/lib/queries";

/** « à l'instant », « il y a 5 min », « il y a 2 h », « il y a 3 jours ». */
export function ago(iso: string, now: Date = new Date()): string {
  const minutes = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 60_000));
  if (minutes < 1) return "à l'instant";
  if (minutes < 60) return `il y a ${String(minutes)} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `il y a ${String(hours)} h`;
  const days = Math.round(hours / 24);
  return `il y a ${String(days)} jour${days > 1 ? "s" : ""}`;
}

function statusLine(s: Subscription): string {
  if (s.status === "pending") return "Première synchronisation en cours…";
  const count = `${String(s.entries_count)} créneau${s.entries_count > 1 ? "x" : ""}`;
  const when = s.last_success_at ? `synchronisé ${ago(s.last_success_at)}` : "jamais synchronisé";
  return `${count} · ${when}`;
}

/**
 * Page « Calendriers » (PR 45, docs/frontend.md) : abonnements ICS en lecture. L'adresse
 * secrète n'est saisie qu'une fois ; ensuite, seul son domaine s'affiche. Les événements
 * arrivent dans l'agenda de Lorakus, que l'assistant lit pour répondre.
 */
export function CalendarsScreen() {
  const list = useQuery(subscriptionsQuery);
  const disabled = list.error instanceof CalendarsDisabledError;
  return (
    <>
      <TopBar />
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
        <div className="page-enter mx-auto flex max-w-2xl flex-col px-5 pb-16 sm:px-6">
          <header className="pt-2 pb-6">
            <h1 className="text-2xl font-semibold">Calendriers</h1>
            <p className="mt-1 text-sm text-ink-faint">
              Tes calendriers en lecture seule : cours, rendez-vous… Lorakus les lit pour répondre.
            </p>
          </header>
          {disabled ? (
            <EnableCalendars />
          ) : list.isPending ? (
            <p className="text-sm text-ink-faint" aria-busy="true">
              Chargement…
            </p>
          ) : list.isError ? (
            <p role="alert" className="text-danger">
              Impossible de charger tes calendriers. Réessaie dans un instant.
            </p>
          ) : (
            <>
              <SubscriptionList items={list.data} />
              <AddSubscription />
            </>
          )}
        </div>
      </div>
    </>
  );
}

function EnableCalendars() {
  const queryClient = useQueryClient();
  const enable = useMutation({
    mutationFn: enableCalendars,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["calendars"] }),
  });
  return (
    <section aria-labelledby="enable-title" className="rounded-2xl bg-raised p-5">
      <h2 id="enable-title" className="text-base font-medium">
        Active les calendriers
      </h2>
      <p className="mt-1 text-sm text-ink-muted">
        Une seule fois. Lorakus ira lire les calendriers que tu ajoutes, environ toutes les
        30 minutes.
      </p>
      <Button
        className="mt-4"
        size="sm"
        disabled={enable.isPending}
        onClick={() => {
          enable.mutate();
        }}
      >
        Activer
      </Button>
      {enable.isError && (
        <p role="alert" className="mt-2 text-sm text-danger">
          L'activation a échoué. Réessaie dans un instant.
        </p>
      )}
    </section>
  );
}

function SubscriptionList({ items }: { items: Subscription[] }) {
  const queryClient = useQueryClient();
  const [removing, setRemoving] = useState<Subscription | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["calendars"] });
  const sync = useMutation({ mutationFn: syncSubscription, onSuccess: refresh });

  if (items.length === 0) {
    return <p className="pb-6 text-base text-ink-muted">Aucun calendrier pour l'instant.</p>;
  }
  return (
    <>
      <ul aria-label="Mes calendriers" className="flex flex-col gap-0.5 pb-6">
        {items.map((s) => (
          <li key={s.id} className="flex min-h-12 items-center gap-3 rounded-xl px-3 py-2.5 hover:bg-hover">
            <CalendarSync aria-hidden="true" className="size-[18px] shrink-0 text-ink-faint" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-base text-ink">{s.name}</p>
              <p className="truncate text-sm text-ink-faint">
                {s.hint} · {statusLine(s)}
              </p>
              {s.status === "error" && s.error && <p className="text-sm text-danger">{s.error}</p>}
              {s.truncated && (
                <p className="text-sm text-ink-faint">Trop d'événements : seuls les premiers sont gardés.</p>
              )}
            </div>
            <Button
              variant="quiet"
              size="icon"
              aria-label={`Synchroniser ${s.name} maintenant`}
              disabled={sync.isPending || s.status === "pending"}
              onClick={() => {
                sync.mutate(s.id);
              }}
            >
              <RefreshCw aria-hidden="true" />
            </Button>
            <Button
              variant="danger-quiet"
              size="icon"
              aria-label={`Supprimer ${s.name}`}
              onClick={() => {
                setRemoving(s);
              }}
            >
              <Trash2 aria-hidden="true" />
            </Button>
          </li>
        ))}
      </ul>
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => {
          if (!open) setRemoving(null);
        }}
        title={`Supprimer « ${removing?.name ?? ""} » ?`}
        description="Ses événements quittent l'agenda de Lorakus. Ton calendrier d'origine n'est pas touché."
        confirmLabel="Supprimer"
        onConfirm={async () => {
          if (removing) await removeSubscription(removing.id);
          setRemoving(null);
          await refresh();
        }}
      />
    </>
  );
}

function AddSubscription() {
  const queryClient = useQueryClient();
  const nameId = useId();
  const urlId = useId();
  const helpId = useId();
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const add = useMutation({
    mutationFn: () => addSubscription(name, url),
    onSuccess: async () => {
      setName("");
      setUrl(""); // l'adresse secrete ne reste pas dans la page
      await queryClient.invalidateQueries({ queryKey: ["calendars"] });
    },
  });
  const error = add.error instanceof SubscriptionRefusedError ? add.error.message : add.error ? "L'ajout a échoué. Réessaie." : null;

  return (
    <form
      aria-labelledby="add-title"
      onSubmit={(event) => {
        event.preventDefault();
        add.mutate();
      }}
      className="flex flex-col gap-3 rounded-2xl bg-raised p-5">
      <h2 id="add-title" className="text-base font-medium">
        Ajouter un calendrier
      </h2>
      <label htmlFor={nameId} className="text-sm text-ink-muted">
        Nom
      </label>
      <Input
        id={nameId}
        value={name}
        maxLength={80}
        required
        autoComplete="off"
        placeholder="Cours METU"
        onChange={(e) => {
          setName(e.target.value);
        }}
      />
      <label htmlFor={urlId} className="text-sm text-ink-muted">
        Adresse secrète au format iCal
      </label>
      <Input
        id={urlId}
        type="url"
        inputMode="url"
        value={url}
        required
        autoComplete="off"
        spellCheck={false}
        placeholder="https://calendar.google.com/calendar/ical/…/basic.ics"
        aria-describedby={helpId}
        onChange={(e) => {
          setUrl(e.target.value);
        }}
      />
      <p id={helpId} className="text-sm text-ink-faint">
        Google Agenda : Paramètres → ton agenda → « Adresse secrète au format iCal ». Elle est
        chiffrée et ne s'affichera plus jamais en entier.
      </p>
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
      <div>
        <Button type="submit" size="sm" disabled={add.isPending}>
          <Plus aria-hidden="true" />
          Ajouter
        </Button>
      </div>
    </form>
  );
}
