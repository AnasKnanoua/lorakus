/**
 * « Pourquoi m'as-tu dit ça ? » (PR 39) : sous chaque réponse enregistrée, un bouton discret
 * ouvre ce qui a servi à l'écrire. Tout vient du serveur (trace enregistrée avec la réponse) ;
 * les textes (souvenirs, cartes) sont affichés bruts.
 */
import * as Dialog from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import { CircleHelp, X } from "lucide-react";
import { useState, type ReactNode } from "react";

import { getReplyTrace, type ReplyTrace } from "@/api/assistant";
import { Button } from "@/components/ui/button";

const CARD_STATUS: Record<string, string> = {
  pending: "en attente",
  confirmed: "confirmée",
  cancelled: "refusée",
  expired: "expirée",
  ok: "fait",
  error: "échec",
};

const SPECIALIST_STATUS: Record<string, string> = {
  ok: "a répondu",
  partial: "réponse partielle",
  no_data: "rien à signaler",
  timeout: "trop lent, ignoré",
  error: "en échec",
};

const ROUTING: Record<string, string> = {
  rules: "choisis par mots-clés",
  embeddings: "choisis par le sens de ta question",
  none: "aucun spécialiste consulté",
};

const CLASSES: Record<string, string> = {
  public: "publiques",
  personal: "personnelles",
  sensitive: "sensibles",
};

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-5">
      <h3 className="text-sm font-medium text-ink-faint">{title}</h3>
      <div className="mt-2 text-base">{children}</div>
    </section>
  );
}

function plural(count: number, one: string, many: string): string {
  return `${String(count)} ${count > 1 ? many : one}`;
}

function TraceBody({ trace }: { trace: ReplyTrace }) {
  const cost = trace.cost_usd ? `${Number(trace.cost_usd).toFixed(4)} $` : "aucun";
  const sent = trace.data_classes_sent.map((c) => CLASSES[c] ?? c).join(", ");
  return (
    <>
      <Section title="Souvenirs fournis">
        {trace.memory_facts.length === 0 ? (
          <p className="text-ink-muted">Aucun.</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {trace.memory_facts.map((fact) => (
              <li key={fact.id} className="[overflow-wrap:anywhere]">
                {fact.content}
              </li>
            ))}
          </ul>
        )}
        {trace.memory_facts_removed > 0 && (
          <p className="mt-1 text-sm text-ink-faint">
            {plural(trace.memory_facts_removed, "souvenir supprimé depuis", "souvenirs supprimés depuis")}.
          </p>
        )}
      </Section>

      <Section title="Outils">
        {trace.tools.length === 0 ? (
          <p className="text-ink-muted">Aucun.</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {trace.tools.map((tool, index) => (
              <li key={`${tool.tool}-${String(index)}`} className="whitespace-pre-line [overflow-wrap:anywhere]">
                {tool.text}
                {tool.status && <span className="text-ink-faint"> : {CARD_STATUS[tool.status] ?? tool.status}</span>}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Spécialistes">
        <p className="text-ink-muted">{ROUTING[trace.routing?.tier ?? "none"]}</p>
        {trace.specialists.length > 0 && (
          <ul className="mt-1 flex flex-col gap-1">
            {trace.specialists.map((s) => (
              <li key={s.specialist}>
                {s.display_name}
                <span className="text-ink-faint">
                  {" : "}
                  {s.skipped === "breaker" ? "écarté (pannes récentes)" : (SPECIALIST_STATUS[s.status] ?? s.status)}
                  {s.cached ? ", réponse gardée en mémoire" : `, ${String(s.duration_ms)} ms`}
                  {s.data_classes.length === 0 && s.status === "ok" ? ", rien transmis au modèle" : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Détails">
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
          <dt className="text-ink-faint">Modèle</dt>
          <dd>{trace.model ?? "aucun (message de secours)"}</dd>
          <dt className="text-ink-faint">Appels</dt>
          <dd>{trace.model_calls}</dd>
          <dt className="text-ink-faint">Coût</dt>
          <dd>{cost}</dd>
          <dt className="text-ink-faint">Données transmises</dt>
          <dd>{sent || "aucune"}</dd>
          <dt className="text-ink-faint">Version du prompt</dt>
          <dd className="[overflow-wrap:anywhere]">{trace.prompt_version ?? "inconnue"}</dd>
        </dl>
      </Section>
    </>
  );
}

function TraceContent({ conversationId, messageId }: { conversationId: string; messageId: string }) {
  const trace = useQuery({
    queryKey: ["assistant", "trace", messageId],
    queryFn: () => getReplyTrace(conversationId, messageId),
  });
  if (trace.isPending) {
    return <p className="mt-4 text-ink-muted">Chargement…</p>;
  }
  if (trace.isError) {
    return (
      <p role="alert" className="mt-4 text-sm text-danger">
        L'explication n'a pas pu être chargée. Réessaie plus tard.
      </p>
    );
  }
  if (trace.data === null) {
    return <p className="mt-4 text-ink-muted">Aucune explication pour cette réponse : elle date d'avant cette fonction.</p>;
  }
  return <TraceBody trace={trace.data} />;
}

export function WhyButton({ conversationId, messageId }: { conversationId: string; messageId: string }) {
  const [open, setOpen] = useState(false);
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <Button variant="quiet" size="icon-sm" aria-label="Pourquoi cette réponse ?">
          <CircleHelp aria-hidden="true" />
        </Button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="scrim fixed inset-0 z-40 bg-[var(--scrim)] backdrop-blur-[2px]" />
        <Dialog.Content className="fixed inset-x-4 bottom-4 z-50 mx-auto max-h-[80dvh] max-w-md animate-fade-up overflow-y-auto rounded-3xl border border-line bg-raised p-6 shadow-float sm:top-[15%] sm:bottom-auto">
          <div className="flex items-start justify-between gap-4">
            <Dialog.Title className="text-lg font-semibold tracking-[-0.01em]">Pourquoi cette réponse ?</Dialog.Title>
            <Dialog.Close asChild>
              <Button variant="quiet" size="icon-sm" aria-label="Fermer">
                <X aria-hidden="true" />
              </Button>
            </Dialog.Close>
          </div>
          <Dialog.Description className="mt-1 text-sm text-ink-muted">
            Ce que Lorakus avait sous les yeux pour l'écrire.
          </Dialog.Description>
          {open && <TraceContent conversationId={conversationId} messageId={messageId} />}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
