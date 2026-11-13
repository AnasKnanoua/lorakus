import * as Dialog from "@radix-ui/react-dialog";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Check, Pencil, Trash2, X } from "lucide-react";
import { useId, useState } from "react";

import {
  CATEGORIES,
  CATEGORY_LABELS,
  addFact,
  confirmFact,
  deleteFact,
  forgetAll,
  reauthenticate,
  rejectFact,
  setProposalsEnabled,
  updateFact,
  type Fact,
} from "@/api/memory";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ConfirmDialog } from "@/features/chat/ConfirmDialog";
import { TopBar } from "@/features/chat/layout";
import { factsQuery, memorySettingsQuery } from "@/lib/queries";

import { FactEditor, messageFor } from "./FactEditor";

/**
 * Page Memoire : ce que Lorakus sait de l'utilisateur. Rien n'y entre sans son accord :
 * les propositions issues des conversations attendent sa decision.
 */
export function MemoryScreen() {
  const facts = useQuery(factsQuery);
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["memory"] });
  const pending = facts.data?.filter((f) => f.status === "proposed") ?? [];
  const known = facts.data?.filter((f) => f.status === "verified") ?? [];

  return (
    <>
      <TopBar>
        <h1 className="truncate text-[0.9375rem] font-semibold">Mémoire</h1>
      </TopBar>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-2xl flex-col gap-10 px-4 pt-4 pb-16 sm:px-6">
          <p className="text-ink-muted">
            Lorakus ne retient rien sans ton accord. Après tes conversations, il te propose ce qu'il a compris de toi :
            tu confirmes, corriges ou refuses. Seuls les souvenirs confirmés lui servent.
          </p>

          <ProposalsSetting />

          {facts.isError && (
            <p role="alert" className="text-danger">
              Impossible de charger la mémoire. Réessaie plus tard.
            </p>
          )}

          <section aria-labelledby="pending-title" className="flex flex-col gap-3">
            <h2 id="pending-title" className="text-lg font-semibold">
              À confirmer {pending.length > 0 && <span className="text-accent">({pending.length})</span>}
            </h2>
            {pending.length === 0 ? (
              <p className="text-ink-faint">Aucune proposition en attente.</p>
            ) : (
              <ul className="flex flex-col gap-3">
                {pending.map((fact) => (
                  <ProposalCard key={fact.id} fact={fact} onDone={refresh} />
                ))}
              </ul>
            )}
          </section>

          <section aria-labelledby="known-title" className="flex flex-col gap-4">
            <h2 id="known-title" className="text-lg font-semibold">
              Ce que Lorakus sait de toi
            </h2>
            {known.length === 0 && <p className="text-ink-faint">Rien pour l'instant.</p>}
            {CATEGORIES.map((category) => {
              const items = known.filter((f) => f.category === category);
              if (items.length === 0) {
                return null;
              }
              return (
                <div key={category}>
                  <h3 className="pb-1.5 text-xs font-medium tracking-wide text-ink-faint uppercase">
                    {CATEGORY_LABELS[category]}
                  </h3>
                  <ul className="divide-y divide-line rounded-2xl border border-line bg-surface">
                    {items.map((fact) => (
                      <KnownFact key={fact.id} fact={fact} onDone={refresh} />
                    ))}
                  </ul>
                </div>
              );
            })}
            <div className="rounded-2xl border border-dashed border-line p-4">
              <h3 className="pb-2 text-sm font-medium">Ajouter un souvenir</h3>
              <FactEditor
                key={known.length}
                submitLabel="Ajouter"
                onSubmit={async (content, category) => {
                  await addFact(content, category);
                  await refresh();
                }}
              />
            </div>
          </section>

          <ForgetAll disabled={(facts.data?.length ?? 0) === 0} onDone={refresh} />
        </div>
      </div>
    </>
  );
}

function ProposalsSetting() {
  const setting = useQuery(memorySettingsQuery);
  const queryClient = useQueryClient();
  const [failed, setFailed] = useState(false);
  const enabled = setting.data ?? true;
  return (
    <div className="flex items-start gap-4 rounded-2xl border border-line bg-surface p-4">
      <div className="flex-1">
        <p id="proposals-label" className="font-medium">
          Proposer des souvenirs après mes conversations
        </p>
        <p className="mt-1 text-sm text-ink-muted">
          Quelques minutes après ton dernier message, Lorakus relit tes messages (jamais ses réponses) et te propose au
          plus cinq souvenirs.
        </p>
        {failed && (
          <p role="alert" className="mt-1 text-sm text-danger">
            Le réglage n'a pas été enregistré.
          </p>
        )}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={enabled}
        aria-labelledby="proposals-label"
        disabled={setting.isPending}
        onClick={() => {
          setFailed(false);
          setProposalsEnabled(!enabled)
            .then(() =>
              queryClient.invalidateQueries({
                queryKey: ["memory", "settings"],
              }),
            )
            .catch(() => {
              setFailed(true);
            });
        }}
        className={`relative mt-1 h-7 w-12 shrink-0 rounded-full transition-colors ${enabled ? "bg-accent" : "bg-line"}`}
      >
        <span
          aria-hidden="true"
          className={`absolute top-1 left-1 size-5 rounded-full bg-background transition-transform ${enabled ? "translate-x-5" : ""}`}
        />
      </button>
    </div>
  );
}

function ProposalCard({ fact, onDone }: { fact: Fact; onDone: () => Promise<void> }) {
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = (action: () => Promise<void>) => {
    setError(null);
    action()
      .then(onDone)
      .catch((cause: unknown) => {
        setError(messageFor(cause));
      });
  };
  return (
    <li className="rounded-2xl border border-line bg-raised p-4">
      {editing ? (
        <FactEditor
          initialContent={fact.content}
          initialCategory={fact.category}
          submitLabel="Confirmer"
          onCancel={() => {
            setEditing(false);
          }}
          onSubmit={async (content, category) => {
            await confirmFact(fact.id, content, category);
            await onDone();
          }}
        />
      ) : (
        <>
          <p className="font-medium">{fact.content}</p>
          <p className="mt-1 text-sm text-ink-faint">
            {CATEGORY_LABELS[fact.category]}
            {fact.evidence && <> · Tu as dit : « {fact.evidence} »</>}
            {fact.from_conversation && (
              <>
                {" · "}
                <Link
                  to="/c/$conversationId"
                  params={{ conversationId: fact.from_conversation }}
                  className="underline underline-offset-2 hover:text-ink"
                >
                  voir la conversation
                </Link>
              </>
            )}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button
              size="sm"
              onClick={() => {
                run(() => confirmFact(fact.id));
              }}
            >
              <Check aria-hidden="true" />
              Confirmer
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setEditing(true);
              }}
            >
              <Pencil aria-hidden="true" />
              Corriger
            </Button>
            <Button
              size="sm"
              variant="quiet"
              onClick={() => {
                run(() => rejectFact(fact.id));
              }}
            >
              <X aria-hidden="true" />
              Refuser
            </Button>
          </div>
          {error && (
            <p role="alert" className="mt-2 text-sm text-danger">
              {error}
            </p>
          )}
        </>
      )}
    </li>
  );
}

function KnownFact({ fact, onDone }: { fact: Fact; onDone: () => Promise<void> }) {
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  return (
    <li className="px-4 py-3">
      {editing ? (
        <FactEditor
          initialContent={fact.content}
          initialCategory={fact.category}
          submitLabel="Enregistrer"
          onCancel={() => {
            setEditing(false);
          }}
          onSubmit={async (content, category) => {
            await updateFact(fact.id, content, category);
            setEditing(false);
            await onDone();
          }}
        />
      ) : (
        <div className="flex items-center gap-2">
          <p className="min-w-0 flex-1">{fact.content}</p>
          <Button
            variant="quiet"
            size="icon-sm"
            aria-label={`Modifier : ${fact.content}`}
            onClick={() => {
              setEditing(true);
            }}
          >
            <Pencil aria-hidden="true" />
          </Button>
          <Button
            variant="quiet"
            size="icon-sm"
            aria-label={`Supprimer : ${fact.content}`}
            onClick={() => {
              setDeleting(true);
            }}
          >
            <Trash2 aria-hidden="true" />
          </Button>
        </div>
      )}
      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title="Supprimer ce souvenir ?"
        description={`« ${fact.content} » sera effacé définitivement.`}
        confirmLabel="Supprimer"
        onConfirm={async () => {
          await deleteFact(fact.id);
          await onDone();
        }}
      />
    </li>
  );
}

/** Tout oublier : confirmation, puis preuve d'identite si la derniere date de plus de 10 min. */
function ForgetAll({ disabled, onDone }: { disabled: boolean; onDone: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [needsProof, setNeedsProof] = useState(false);
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const id = useId();

  async function attempt() {
    setBusy(true);
    setError(null);
    try {
      if (needsProof && !(await reauthenticate(password, code))) {
        setError("Mot de passe ou code incorrect.");
        return;
      }
      if ((await forgetAll()) === "reauth") {
        setNeedsProof(true);
        return;
      }
      setOpen(false);
      await onDone();
    } catch {
      setError("L'opération a échoué. Réessaie.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="border-t border-line pt-6">
      <Button
        variant="outline"
        disabled={disabled}
        onClick={() => {
          setNeedsProof(false);
          setPassword("");
          setCode("");
          setError(null);
          setOpen(true);
        }}
        className="text-danger"
      >
        <Trash2 aria-hidden="true" />
        Tout oublier
      </Button>
      <Dialog.Root open={open} onOpenChange={setOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="scrim fixed inset-0 z-40 bg-[var(--scrim)] backdrop-blur-[2px]" />
          <Dialog.Content
            role="alertdialog"
            className="fixed inset-x-4 bottom-4 z-50 mx-auto max-w-md animate-fade-up rounded-3xl border border-line bg-raised p-6 shadow-float sm:top-1/3 sm:bottom-auto"
          >
            <Dialog.Title className="text-lg font-semibold">Tout oublier ?</Dialog.Title>
            <Dialog.Description className="mt-2 text-ink-muted">
              Tous les souvenirs, confirmés ou proposés, seront effacés définitivement.
            </Dialog.Description>
            <form
              className="mt-4 flex flex-col gap-3"
              onSubmit={(event) => {
                event.preventDefault();
                void attempt();
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
              <div className="mt-2 flex justify-end gap-2">
                <Dialog.Close asChild>
                  <Button variant="outline">Annuler</Button>
                </Dialog.Close>
                <Button type="submit" variant="danger" disabled={busy || (needsProof && !password)}>
                  Tout oublier
                </Button>
              </div>
            </form>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </section>
  );
}
