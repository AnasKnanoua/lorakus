import { ArrowUp } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/button";

export const MAX_MESSAGE_CHARS = 8000;

/** Sur un ecran tactile, Entree va a la ligne ; on envoie avec le bouton. */
function enterSends(): boolean {
  return !window.matchMedia("(pointer: coarse)").matches;
}

export function Composer({
  onSend,
  disabled = false,
  autoFocus = false,
}: {
  onSend: (text: string) => void;
  disabled?: boolean;
  autoFocus?: boolean;
}) {
  const [text, setText] = useState("");
  const area = useRef<HTMLTextAreaElement>(null);
  const labelId = useId();
  const trimmed = text.trim();
  const tooLong = text.length > MAX_MESSAGE_CHARS;
  const canSend = !disabled && trimmed.length > 0 && !tooLong;

  // Hauteur ajustee au texte, jusqu'a environ huit lignes.
  useEffect(() => {
    const el = area.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 240)}px`;
    }
  }, [text]);

  function send() {
    if (canSend) {
      onSend(trimmed);
      setText("");
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && enterSends()) {
      event.preventDefault();
      send();
    }
  }

  return (
    <div className="border-t border-line bg-background px-3 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:px-6">
      <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-2xl border border-line bg-surface p-2 focus-within:border-accent">
        <label id={labelId} className="sr-only">
          Votre message
        </label>
        <textarea
          ref={area}
          aria-labelledby={labelId}
          rows={1}
          value={text}
          autoFocus={autoFocus}
          placeholder="Écrire à Lorakus"
          onChange={(e) => {
            setText(e.target.value);
          }}
          onKeyDown={onKeyDown}
          className="max-h-60 min-h-11 flex-1 resize-none bg-transparent px-2 py-2.5 text-reading outline-none placeholder:text-ink-muted"
        />
        <Button size="icon" aria-label="Envoyer" onClick={send} disabled={!canSend} className="rounded-xl">
          <ArrowUp aria-hidden="true" />
        </Button>
      </div>
      {tooLong && (
        <p role="alert" className="mx-auto mt-2 max-w-3xl text-sm text-danger">
          Message trop long : {text.length} caractères sur {MAX_MESSAGE_CHARS} au maximum.
        </p>
      )}
    </div>
  );
}
