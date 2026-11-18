import { useQueryClient } from "@tanstack/react-query";
import { Download, Trash2 } from "lucide-react";
import { useId, useState } from "react";

import { deleteAllConversations, exportMyData, saveFile } from "@/api/data";
import { reauthenticate } from "@/api/memory";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ConfirmDialog } from "@/features/chat/ConfirmDialog";
import { TopBar } from "@/features/chat/layout";

type Action = "export" | "delete";

interface Notice {
  kind: "status" | "alert";
  text: string;
}

/**
 * Page « Mes données » (PR 41, docs/frontend.md) : emporter tout ce que Lorakus garde sur toi,
 * ou effacer toutes tes conversations. Les deux demandent une preuve d'identité récente : si
 * elle manque, un petit formulaire apparaît dans la page et relance l'action demandée.
 */
export function DataScreen() {
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState<Action | null>(null);
  const [proofFor, setProofFor] = useState<Action | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);

  /** Lance l'action ; renvoie faux si une preuve d'identite est d'abord necessaire. */
  async function run(action: Action): Promise<boolean> {
    setBusy(action);
    setNotice(null);
    try {
      if (action === "export") {
        const file = await exportMyData();
        if (file === "reauth") {
          setProofFor("export");
          return false;
        }
        saveFile(file);
        setNotice({ kind: "status", text: `Export téléchargé : ${file.filename}` });
      } else {
        const deleted = await deleteAllConversations();
        if (deleted === "reauth") {
          setProofFor("delete");
          return false;
        }
        await queryClient.invalidateQueries({ queryKey: ["assistant"] });
        setNotice({
          kind: "status",
          text:
            deleted === 0
              ? "Aucune conversation à supprimer."
              : `${deleted} conversation${deleted > 1 ? "s" : ""} supprimée${deleted > 1 ? "s" : ""}.`,
        });
      }
      setProofFor(null);
      return true;
    } catch {
      setNotice({ kind: "alert", text: "L'opération a échoué. Réessaie." });
      return true;
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <TopBar />
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
        <div className="page-enter mx-auto flex max-w-2xl flex-col px-5 pb-16 sm:px-6">
          <header className="pt-2 pb-6">
            <h1 className="text-2xl font-semibold">Mes données</h1>
            <p className="mt-1 text-sm text-ink-faint">Tout ce que Lorakus garde sur toi, à emporter ou à effacer.</p>
          </header>

          <div aria-live="polite">
            {notice?.kind === "status" && (
              <p role="status" className="mb-4 rounded-xl bg-accent-soft px-4 py-3 text-base text-ink">
                {notice.text}
              </p>
            )}
          </div>
          {notice?.kind === "alert" && (
            <p role="alert" className="mb-4 text-danger">
              {notice.text}
            </p>
          )}

          {proofFor && (
            <IdentityProof
              action={proofFor}
              onCancel={() => {
                setProofFor(null);
              }}
              onProven={() => run(proofFor)}
            />
          )}

          <section aria-labelledby="export-title" className="flex items-center gap-4 py-4">
            <div className="min-w-0 flex-1">
              <h2 id="export-title" className="text-base font-medium">
                Exporter mes données
              </h2>
              <p className="mt-0.5 text-sm text-ink-faint">
                Un fichier JSON : compte, souvenirs, conversations, consommation d'IA et journal de sécurité. Aucun mot de
                passe ni secret.
              </p>
            </div>
            <Button
              variant="secondary"
              size="sm"
              disabled={busy !== null}
              onClick={() => {
                void run("export");
              }}
            >
              <Download aria-hidden="true" />
              Télécharger
            </Button>
          </section>

          <section aria-labelledby="delete-title" className="flex items-center gap-4 py-4">
            <div className="min-w-0 flex-1">
              <h2 id="delete-title" className="text-base font-medium">
                Supprimer toutes les conversations
              </h2>
              <p className="mt-0.5 text-sm text-ink-faint">
                Messages et cartes en attente compris. Tes souvenirs restent : ils se gèrent dans la page Mémoire.
              </p>
            </div>
            <Button
              variant="danger-quiet"
              size="sm"
              disabled={busy !== null}
              onClick={() => {
                setConfirming(true);
              }}
            >
              <Trash2 aria-hidden="true" />
              Tout supprimer
            </Button>
          </section>

          <ConfirmDialog
            open={confirming}
            onOpenChange={setConfirming}
            title="Supprimer toutes les conversations ?"
            description="Toutes tes conversations et leurs messages seront effacés définitivement. Tes souvenirs ne changent pas."
            confirmLabel="Supprimer"
            onConfirm={async () => {
              await run("delete");
            }}
          />
        </div>
      </div>
    </>
  );
}

/** Preuve d'identite dans la page : mot de passe, et code si la double authentification est active. */
function IdentityProof({
  action,
  onCancel,
  onProven,
}: {
  action: Action;
  onCancel: () => void;
  onProven: () => Promise<boolean>;
}) {
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const id = useId();

  return (
    <form
      aria-labelledby={`${id}-title`}
      className="mb-4 flex flex-col gap-3 rounded-2xl bg-raised p-4"
      onSubmit={(event) => {
        event.preventDefault();
        setBusy(true);
        setError(null);
        void reauthenticate(password, code)
          .then(async (ok) => {
            if (!ok) {
              setError("Mot de passe ou code incorrect.");
              return;
            }
            await onProven();
          })
          .catch(() => {
            setError("L'opération a échoué. Réessaie.");
          })
          .finally(() => {
            setBusy(false);
          });
      }}
    >
      <h2 id={`${id}-title`} className="text-base font-medium">
        Confirme ton identité
      </h2>
      <p className="text-sm text-ink-muted">
        {action === "export"
          ? "L'export contient toutes tes données : redonne ton mot de passe pour le télécharger."
          : "Redonne ton mot de passe pour supprimer toutes tes conversations."}
      </p>
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
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
      <div className="mt-1 flex justify-end gap-2">
        <Button variant="outline" onClick={onCancel}>
          Annuler
        </Button>
        <Button type="submit" disabled={busy || !password}>
          Confirmer
        </Button>
      </div>
    </form>
  );
}
