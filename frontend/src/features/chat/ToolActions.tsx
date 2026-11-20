/**
 * Outils d'une reponse (PR 38) : une ligne discrete quand Lorakus a consulte quelque chose,
 * et une carte pour chaque action qu'il propose. Rien ne change tant que l'utilisateur n'a
 * pas confirme la carte ; une action sensible demande en plus sa preuve d'identite.
 *
 * Le texte de la carte vient du serveur, ecrit par l'outil (jamais par le modele) ; il est
 * affiche en texte brut, sans Markdown ni lien.
 */
import { useQueryClient } from "@tanstack/react-query";
import { Check, CircleAlert, Clock, Search, ShieldCheck, X } from "lucide-react";
import { useEffect, useId, useState } from "react";

import { reauthenticate } from "@/api/memory";
import { cancelCard, confirmCard, type CardOutcome, type CardStatus, type ToolAction } from "@/api/tools";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/**
 * Ce que Lorakus a consulte, sur une seule ligne discrete au-dessus de la reponse (comme
 * « Recherche effectuee » chez les assistants de reference) : une etiquette par outil, sans
 * doublon, dans l'ordre d'utilisation. Un echec est signale a part, en clair.
 */
export function ToolActivity({ actions }: { actions: readonly ToolAction[] }) {
  const labels: string[] = [];
  const failures: string[] = [];
  for (const action of actions) {
    if (action.kind !== "activity") {
      continue;
    }
    const label = action.label ?? "Outil";
    const target = action.ok === false ? failures : labels;
    if (!target.includes(label)) {
      target.push(label);
    }
  }
  if (labels.length === 0 && failures.length === 0) {
    return null;
  }
  return (
    <div className="mb-2 flex flex-col gap-1 text-sm text-ink-faint">
      {labels.length > 0 && (
        <p className="flex items-center gap-1.5">
          <Search aria-hidden="true" className="size-3.5 shrink-0" />
          <span>{joinLabels(labels)}</span>
        </p>
      )}
      {failures.map((label) => (
        <p key={label} className="flex items-center gap-1.5">
          <CircleAlert aria-hidden="true" className="size-3.5 shrink-0" />
          <span>{label} : échec</span>
        </p>
      ))}
    </div>
  );
}

/** « A consulté ton agenda », « A consulté ton agenda et ta mémoire »… : phrase lisible. */
export function joinLabels(labels: readonly string[]): string {
  const [first, ...rest] = labels;
  if (first === undefined) {
    return "";
  }
  // Les etiquettes suivantes perdent leur majuscule : elles prolongent la meme phrase.
  const tail = rest.map((label) => label.charAt(0).toLowerCase() + label.slice(1));
  if (tail.length === 0) {
    return first;
  }
  const last = tail.pop() ?? "";
  return [first, ...tail].join(", ") + " et " + last;
}

/** Cartes de confirmation de la reponse, sous le texte. */
export function ToolActions({ actions, conversationId }: { actions: readonly ToolAction[]; conversationId: string }) {
  const cards = actions.filter((action) => action.kind !== "activity");
  if (cards.length === 0) {
    return null;
  }
  return (
    <div className="mt-4 flex flex-col gap-3">
      {cards.map((action, index) => (
        <ActionCard key={action.confirmation_id ?? String(index)} action={action} conversationId={conversationId} />
      ))}
    </div>
  );
}

/** Plus grand delai accepte par setTimeout (environ 24 jours). */
const MAX_TIMEOUT_MS = 2 ** 31 - 1;

/** Vrai une fois l'echeance d'une carte en attente passee (minuteur, rendu pur). */
function useExpired(action: ToolAction): boolean {
  const [expired, setExpired] = useState(false);
  const pending = (action.status ?? "pending") === "pending";
  const deadline = action.expires_at;
  useEffect(() => {
    if (!pending || !deadline) {
      return undefined;
    }
    const delay = Math.min(Math.max(Date.parse(deadline) - Date.now(), 0), MAX_TIMEOUT_MS);
    const timer = setTimeout(() => {
      setExpired(true);
    }, delay);
    return () => {
      clearTimeout(timer);
    };
  }, [pending, deadline]);
  return expired;
}

const DONE_TEXT: Record<Exclude<CardStatus, "pending">, string> = {
  confirmed: "Confirmé",
  cancelled: "Refusé",
  expired: "Expiré : redemande-le si besoin",
};

function ActionCard({ action, conversationId }: { action: ToolAction; conversationId: string }) {
  const queryClient = useQueryClient();
  const [local, setLocal] = useState<CardStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needsProof, setNeedsProof] = useState(false);
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const id = useId();
  const sensitive = action.risk === "sensitive";
  const expired = useExpired(action);
  const status: CardStatus = local ?? (expired ? "expired" : (action.status ?? "pending"));
  const confirmationId = action.confirmation_id ?? "";

  async function settle(outcome: CardOutcome, done: CardStatus) {
    if (outcome.kind === "done") {
      setLocal(done);
      setNeedsProof(false);
      // La conversation rechargee porte l'etat enregistre ; la memoire a peut-etre change.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["assistant", "conversation", conversationId] }),
        queryClient.invalidateQueries({ queryKey: ["memory"] }),
      ]);
    } else if (outcome.kind === "reauth") {
      setNeedsProof(true);
    } else {
      setError(outcome.message);
    }
  }

  async function run(task: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await task();
    } catch {
      setError("L'action a échoué. Vérifie ta connexion et réessaie.");
    } finally {
      setBusy(false);
    }
  }

  function confirm() {
    void run(async () => {
      if (needsProof && !(await reauthenticate(password, code))) {
        setError("Mot de passe ou code incorrect.");
        return;
      }
      await settle(await confirmCard(confirmationId), "confirmed");
    });
  }

  function refuse() {
    void run(async () => {
      await settle(await cancelCard(confirmationId), "cancelled");
    });
  }

  const titleId = `${id}-title`;
  return (
    <section aria-labelledby={titleId} className="rounded-2xl bg-raised p-4">
      <h2 id={titleId} className="flex items-center gap-2 text-sm font-medium text-ink-faint">
        {sensitive && <ShieldCheck aria-hidden="true" className="size-4" />}
        {sensitive ? "Action sensible à confirmer" : "Action à confirmer"}
      </h2>
      <p className="mt-2 text-md whitespace-pre-line [overflow-wrap:anywhere]">{action.summary}</p>

      {status === "pending" ? (
        <form
          className="mt-4 flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            confirm();
          }}
        >
          {needsProof && (
            <>
              <p className="text-sm text-ink-muted">Confirme d'abord ton identité.</p>
              <label htmlFor={`${id}-password`} className="text-sm font-medium">
                Mot de passe
              </label>
              <Input
                id={`${id}-password`}
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => {
                  setPassword(event.target.value);
                }}
              />
              <label htmlFor={`${id}-code`} className="text-sm font-medium">
                Code de double authentification
              </label>
              <Input
                id={`${id}-code`}
                inputMode="numeric"
                autoComplete="one-time-code"
                value={code}
                onChange={(event) => {
                  setCode(event.target.value);
                }}
              />
            </>
          )}
          {error && (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          )}
          <div className="flex gap-2">
            <Button type="submit" size="sm" disabled={busy}>
              <Check aria-hidden="true" />
              {needsProof ? "Confirmer mon identité" : "Confirmer"}
            </Button>
            <Button variant="quiet" size="sm" disabled={busy} onClick={refuse}>
              <X aria-hidden="true" />
              Refuser
            </Button>
          </div>
        </form>
      ) : (
        <p role="status" className="mt-3 flex items-center gap-2 text-sm text-ink-muted">
          {status === "confirmed" ? (
            <Check aria-hidden="true" className="size-4 text-accent" />
          ) : status === "expired" ? (
            <Clock aria-hidden="true" className="size-4" />
          ) : (
            <X aria-hidden="true" className="size-4" />
          )}
          {DONE_TEXT[status]}
        </p>
      )}
    </section>
  );
}
