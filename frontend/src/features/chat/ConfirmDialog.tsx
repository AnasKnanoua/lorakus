import * as Dialog from "@radix-ui/react-dialog";
import { useState } from "react";

import { Button } from "@/components/ui/button";

/** Confirmation d'une action destructive (Radix Dialog : focus piege, Echap, annonce). */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel: string;
  onConfirm: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-ink/40" />
        {/* alertdialog : confirmation destructive, annoncee comme une alerte qui attend une reponse. */}
        <Dialog.Content
          role="alertdialog"
          className="fixed inset-x-4 bottom-4 mx-auto max-w-md rounded-2xl bg-surface p-6 sm:top-1/3 sm:bottom-auto"
        >
          <Dialog.Title className="text-lg font-bold">{title}</Dialog.Title>
          <Dialog.Description className="mt-2 text-ink-muted">{description}</Dialog.Description>
          {failed && (
            <p role="alert" className="mt-3 text-sm text-danger">
              La suppression a échoué. Réessayez.
            </p>
          )}
          <div className="mt-6 flex justify-end gap-2">
            <Dialog.Close asChild>
              <Button variant="outline">Annuler</Button>
            </Dialog.Close>
            <Button
              variant="danger"
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
