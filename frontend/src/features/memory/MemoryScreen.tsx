import * as Dialog from "@radix-ui/react-dialog";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Check, Pencil, Plus, Search, Trash2, X } from "lucide-react";
import { useDeferredValue, useId, useState } from "react";

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
  type Category,
  type Fact,
} from "@/api/memory";
import { Collapsible } from "@/components/Collapsible";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ConfirmDialog } from "@/features/chat/ConfirmDialog";
import { TopBar } from "@/features/chat/layout";
import { cn } from "@/lib/cn";
import { withViewTransition } from "@/lib/motion";
import { factsQuery, memorySearchQuery, memorySettingsQuery } from "@/lib/queries";
import { useDebouncedValue } from "@/lib/useDebouncedValue";

import { FactEditor, messageFor } from "./FactEditor";

// Souvenirs « proches par le sens » affiches au plus sous les resultats exacts : la recherche
// classe sans seuil (similarites tassees, ADR 0007), on ne montre donc que la tete.
const RELATED_MAX = 3;

type Filter = Category | "all";

/** Normalise pour la recherche : casse et accents ignores (« etudes » trouve « Études »). */
function fold(text: string): string {
  return text.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
}

/**
 * Page Memoire (docs/frontend.md, « Mémoire »). Pensee pour 3 comme pour 200 souvenirs :
 * propositions en tete seulement s'il y en a ; puis une barre de recherche et de filtres qui
 * reste en haut ; des lignes discretes groupees par categorie repliable ; les reglages et
 * « Tout oublier » ranges en bas, replies.
 */
export function MemoryScreen() {
  const facts = useQuery(factsQuery);
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [adding, setAdding] = useState(false);
  const search = fold(useDeferredValue(query).trim());
  // Recherche par le sens (PR 37b) : au serveur seulement apres une pause de frappe, des
  // 3 caracteres. Elle complete la recherche exacte, instantanee, faite ici.
  const settled = useDebouncedValue(query.trim());
  const semantic = useQuery({ ...memorySearchQuery(settled), enabled: settled.length >= 3 });

  // Chaque changement fait glisser les lignes vers leur nouvelle place (View Transitions).
  const refresh = () => withViewTransition(() => queryClient.invalidateQueries({ queryKey: ["memory"] }));
  const pending = facts.data?.filter((f) => f.status === "proposed") ?? [];
  const known = facts.data?.filter((f) => f.status === "verified") ?? [];
  const counts = new Map<Category, number>();
  for (const fact of known) counts.set(fact.category, (counts.get(fact.category) ?? 0) + 1);
  const visible = known.filter(
    (f) => (filter === "all" || f.category === filter) && (!search || fold(f.content).includes(search)),
  );
  const narrowed = filter !== "all" || search !== "";
  const shown = new Set(visible.map((f) => f.id));
  const related =
    search.length >= 3 && fold(settled) === search
      ? (semantic.data ?? [])
          .filter((f) => !shown.has(f.id) && (filter === "all" || f.category === filter))
          .slice(0, RELATED_MAX)
      : [];

  return (
    <>
      <TopBar />
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
        <div className="page-enter mx-auto flex max-w-2xl flex-col px-5 pb-16 sm:px-6">
          {/* Titre de page dans le contenu, comme sur toutes les pages : grand, serre, une phrase. */}
          <header className="pt-2 pb-6">
            <h1 className="text-2xl font-semibold">Mémoire</h1>
            <p className="mt-1 text-sm text-ink-faint">
              Seuls les souvenirs que tu confirmes servent à Lorakus.
              {known.length > 0 && " Touche-en un pour le modifier."}
            </p>
          </header>

          {facts.isError && (
            <p role="alert" className="pb-4 text-danger">
              Impossible de charger la mémoire. Réessaie plus tard.
            </p>
          )}

          {pending.length > 0 && (
            <section aria-labelledby="pending-title" className="pb-6">
              <h2 id="pending-title" className="flex h-9 items-center gap-2 text-sm font-medium text-ink">
                À confirmer <span className="font-normal text-accent tabular-nums">{pending.length}</span>
              </h2>
              <ul className="flex flex-col gap-2">
                {pending.map((fact) => (
                  <ProposalRow key={fact.id} fact={fact} onDone={refresh} />
                ))}
              </ul>
            </section>
          )}

          <section aria-labelledby="known-title">
            <h2 id="known-title" className="sr-only">
              Ce que Lorakus sait de toi
            </h2>
            {/* Barre d'outils collee en haut pendant le defilement : recherche, ajout, filtres. */}
            <div className="sticky top-0 z-10 -mx-1 bg-background px-1 pt-1 pb-3">
              <div className="flex items-center gap-2">
                <label className="relative min-w-0 flex-1">
                  <span className="sr-only">Rechercher dans la mémoire</span>
                  <Search
                    aria-hidden="true"
                    className="pointer-events-none absolute top-1/2 left-3.5 size-[18px] -translate-y-1/2 text-ink-faint"
                  />
                  <Input
                    type="search"
                    value={query}
                    placeholder="Rechercher"
                    onChange={(event) => {
                      setQuery(event.target.value);
                    }}
                    className="h-10 border-transparent pl-10 text-base"
                  />
                </label>
                <Button
                  size="icon"
                  variant="secondary"
                  aria-expanded={adding}
                  aria-label={adding ? "Fermer l'ajout" : "Ajouter un souvenir"}
                  title={adding ? "Fermer" : "Ajouter un souvenir"}
                  onClick={() => {
                    setAdding((value) => !value);
                  }}
                >
                  <Plus aria-hidden="true" className={cn("transition-transform duration-200", adding && "rotate-45")} />
                </Button>
              </div>
              {counts.size > 1 && (
                <div role="group" aria-label="Filtrer par catégorie" className="mt-3 flex flex-wrap gap-1.5">
                  <Chip
                    active={filter === "all"}
                    onClick={() => {
                      setFilter("all");
                    }}
                    label="Tout"
                  />
                  {CATEGORIES.filter((c) => counts.has(c)).map((c) => (
                    <Chip
                      key={c}
                      active={filter === c}
                      onClick={() => {
                        setFilter(filter === c ? "all" : c);
                      }}
                      label={CATEGORY_LABELS[c]}
                    />
                  ))}
                </div>
              )}
            </div>

            <div className="collapsible" data-open={adding} inert={!adding}>
              <div className="min-h-0">
                <div className="mb-4 rounded-2xl bg-raised p-3">
                  <FactEditor
                    key={known.length}
                    submitLabel="Ajouter"
                    initialCategory={filter === "all" ? "preference" : filter}
                    onSubmit={async (content, category) => {
                      await addFact(content, category);
                      await refresh();
                    }}
                  />
                </div>
              </div>
            </div>

            {known.length === 0 ? (
              <p className="py-6 text-center text-sm text-ink-faint">
                Aucun souvenir pour l'instant. Parle de toi à Lorakus, ou ajoute-en un.
              </p>
            ) : narrowed ? (
              <>
                {visible.length === 0 && related.length === 0 ? (
                  <p className="py-6 text-center text-sm text-ink-faint">Aucun souvenir ne correspond.</p>
                ) : (
                  <ul className="pt-1">
                    {visible.map((fact) => (
                      <FactRow key={fact.id} fact={fact} onDone={refresh} showCategory={filter === "all"} />
                    ))}
                  </ul>
                )}
                {related.length > 0 && (
                  <section aria-label="Proches par le sens" className="pt-4">
                    <h3 className="flex h-9 items-center text-sm font-medium text-ink-faint">Proches par le sens</h3>
                    <ul>
                      {related.map((fact) => (
                        <FactRow key={fact.id} fact={fact} onDone={refresh} showCategory={filter === "all"} />
                      ))}
                    </ul>
                  </section>
                )}
              </>
            ) : (
              CATEGORIES.filter((c) => counts.has(c)).map((category) => (
                <Collapsible key={category} title={CATEGORY_LABELS[category]} count={counts.get(category)} className="pt-3">
                  <ul>
                    {known
                      .filter((f) => f.category === category)
                      .map((fact) => (
                        <FactRow key={fact.id} fact={fact} onDone={refresh} />
                      ))}
                  </ul>
                </Collapsible>
              ))
            )}
          </section>

          <Collapsible title="Réglages de la mémoire" defaultOpen={false} className="mt-12">
            <div className="flex flex-col gap-4 pt-2 pb-1">
              <ProposalsSetting />
              <ForgetAll disabled={(facts.data?.length ?? 0) === 0} onDone={refresh} />
            </div>
          </Collapsible>
        </div>
      </div>
    </>
  );
}

/** Filtre : texte seul, fond plein uniquement pour le filtre actif (pas de compteur repete). */
function Chip({ active, label, onClick }: { active: boolean; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "h-8 rounded-full px-3 text-sm transition-colors duration-150",
        active ? "bg-ink font-medium text-background" : "bg-raised text-ink-muted hover:bg-hover hover:text-ink",
      )}
    >
      {label}
    </button>
  );
}

function ProposalsSetting() {
  const setting = useQuery(memorySettingsQuery);
  const queryClient = useQueryClient();
  const [failed, setFailed] = useState(false);
  const enabled = setting.data ?? true;
  return (
    <div className="flex items-start gap-4">
      <div className="flex-1">
        <p id="proposals-label" className="text-base font-medium">
          Proposer des souvenirs après mes conversations
        </p>
        <p className="mt-0.5 text-sm text-ink-faint">
          Quelques minutes après ton dernier message, Lorakus relit tes messages (jamais ses réponses) et te propose
          au plus cinq souvenirs.
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
            .then(() => queryClient.invalidateQueries({ queryKey: ["memory", "settings"] }))
            .catch(() => {
              setFailed(true);
            });
        }}
        className={cn(
          "relative mt-0.5 h-6 w-10 shrink-0 rounded-full transition-colors duration-200",
          enabled ? "bg-accent" : "bg-line",
        )}
      >
        <span
          aria-hidden="true"
          className={cn(
            "absolute top-0.5 left-0.5 size-5 rounded-full bg-background shadow-sm transition-transform duration-200 ease-[var(--ease-out-soft)]",
            enabled && "translate-x-4",
          )}
        />
      </button>
    </div>
  );
}

/** Proposition : seul element mis en avant de la page, avec ce que l'utilisateur a dit. */
function ProposalRow({ fact, onDone }: { fact: Fact; onDone: () => Promise<void> }) {
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
    <li
      style={{ viewTransitionName: `fact-${fact.id}` }}
      className="vt-fact rounded-2xl bg-raised p-4"
    >
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
          <p className="text-md">{fact.content}</p>
          <p className="mt-1 line-clamp-2 text-sm text-ink-faint">
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
          <div className="mt-3 flex flex-wrap gap-1.5">
            <Button size="sm" onClick={() => { run(() => confirmFact(fact.id)); }}>
              <Check aria-hidden="true" />
              Confirmer
            </Button>
            <Button size="sm" variant="quiet" onClick={() => { setEditing(true); }}>
              <Pencil aria-hidden="true" />
              Corriger
            </Button>
            <Button size="sm" variant="quiet" onClick={() => { run(() => rejectFact(fact.id)); }}>
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

/**
 * Souvenir confirme : une ligne de texte, sans cadre ni icones permanentes. Toucher la ligne
 * l'ouvre en edition (modifier, supprimer) ; sur ordinateur, un crayon apparait au survol.
 */
function FactRow({
  fact,
  onDone,
  showCategory = false,
}: {
  fact: Fact;
  onDone: () => Promise<void>;
  showCategory?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  return (
    <li style={{ viewTransitionName: `fact-${fact.id}` }} className="vt-fact">
      {editing ? (
        <div className="my-1 rounded-2xl bg-raised p-3">
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
            extraAction={
              <Button
                variant="danger-quiet"
                size="sm"
                aria-label={`Supprimer : ${fact.content}`}
                onClick={() => {
                  setDeleting(true);
                }}
              >
                <Trash2 aria-hidden="true" />
                Supprimer
              </Button>
            }
          />
        </div>
      ) : (
        <button
          type="button"
          aria-label={`Modifier : ${fact.content}`}
          onClick={() => {
            setEditing(true);
          }}
          className="group/row -mx-3 flex min-h-12 w-[calc(100%+1.5rem)] items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors duration-150 hover:bg-hover/70"
        >
          <span className="min-w-0 flex-1 text-md text-ink">
            {fact.content}
            {showCategory && <span className="ml-2 text-sm text-ink-faint">{CATEGORY_LABELS[fact.category]}</span>}
          </span>
          <Pencil aria-hidden="true" className="row-actions size-4 shrink-0 text-ink-faint" />
        </button>
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
    <div className="flex items-center gap-4">
      <div className="flex-1">
        <p className="text-base font-medium">Tout oublier</p>
        <p className="mt-0.5 text-sm text-ink-faint">Efface définitivement tous les souvenirs et propositions.</p>
      </div>
      <Button
        variant="outline"
        size="sm"
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
            className="sheet fixed inset-x-4 bottom-4 z-50 mx-auto max-w-md rounded-3xl border border-line bg-raised p-6 shadow-float sm:top-1/3 sm:bottom-auto"
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
    </div>
  );
}
