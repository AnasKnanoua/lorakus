import * as Dialog from "@radix-ui/react-dialog";
import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";

/**
 * Confirmation d'une action qu'on ne peut pas defaire (Radix Dialog : focus piege, Echap,
 * annonce). Destructive par defaut (bouton rouge) ; `tone="plain"` pour une action definitive
 * qui ne detruit rien, comme terminer un devoir. `children` : un champ facultatif sous le texte
 * (le temps passe sur un devoir, PR 49).
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  onConfirm,
  tone = "danger",
  failure = "La suppression a échoué. Réessaie.",
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel: string;
  onConfirm: () => Promise<void>;
  tone?: "danger" | "plain";
  /** Message affiche si `onConfirm` echoue. */
  failure?: string;
  children?: ReactNode;
}) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="scrim fixed inset-0 z-40 bg-[var(--scrim)] backdrop-blur-[2px]" />
        {/* alertdialog : confirmation definitive, annoncee comme une alerte qui attend une reponse. */}
        <Dialog.Content
          role="alertdialog"
          className="fixed inset-x-4 bottom-4 z-50 mx-auto max-w-md animate-fade-up rounded-3xl border border-line bg-raised p-6 shadow-float sm:top-1/3 sm:bottom-auto"
        >
          <Dialog.Title className="text-lg font-semibold tracking-[-0.01em]">{title}</Dialog.Title>
          <Dialog.Description className="mt-2 text-ink-muted">{description}</Dialog.Description>
          {children}
          {failed && (
            <p role="alert" className="mt-3 text-sm text-danger">
              {failure}
            </p>
          )}
          <div className="mt-6 flex justify-end gap-2">
            <Dialog.Close asChild>
              <Button variant="outline">Annuler</Button>
            </Dialog.Close>
            <Button
              variant={tone === "danger" ? "danger" : "primary"}
              disabled={busy}
              onClick={() => {
                setBusy(true);
                setFailed(false);
                onConfirm()
                  .then(() => {
                    onOpenChange(false);
                  })
                  .catch(() => {
                    setFailed(true);
                  })
                  .finally(() => {
                    setBusy(false);
                  });
              }}
            >
              {confirmLabel}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
