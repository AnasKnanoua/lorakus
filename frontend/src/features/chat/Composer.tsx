import { ArrowUp } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

import { cn } from "@/lib/cn";

export const MAX_MESSAGE_CHARS = 8000;

/** Sur un ecran tactile, Entree va a la ligne ; on envoie avec le bouton. */
function enterSends(): boolean {
  return !window.matchMedia("(pointer: coarse)").matches;
}

/**
 * Zone de saisie flottante.
 *
 * - variant « hero » : au centre de l'accueil ; « docked » : en bas de la conversation, sur un
 *   fondu qui laisse deviner les messages qui defilent derriere (aucune ligne de separation).
 * - Les deux portent le nom de transition « composer » : en passant de l'accueil a la
 *   conversation, le navigateur fait glisser le champ du centre vers le bas.
 * - leading / trailing : emplacements reserves aux futurs outils (piece jointe, micro, choix
 *   du modele). Rien n'y est affiche tant que la fonction n'existe pas.
 */
export function Composer({
  onSend,
  disabled = false,
  busy = false,
  autoFocus = false,
  variant = "docked",
  leading,
  trailing,
  footer,
}: {
  onSend: (text: string) => void;
  disabled?: boolean;
  /** Une reponse s'ecrit : on peut preparer la suite, mais pas l'envoyer. */
  busy?: boolean;
  autoFocus?: boolean;
  variant?: "hero" | "docked";
  leading?: ReactNode;
  trailing?: ReactNode;
  footer?: ReactNode;
}) {
  const [text, setText] = useState("");
  const area = useRef<HTMLTextAreaElement>(null);
  const labelId = useId();
  const errorId = useId();
  const trimmed = text.trim();
  const tooLong = text.length > MAX_MESSAGE_CHARS;
  const canSend = !disabled && !busy && trimmed.length > 0 && !tooLong;

  // Hauteur ajustee au texte, jusqu'a environ huit lignes.
  useEffect(() => {
    const el = area.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = `${String(Math.min(el.scrollHeight, 224))}px`;
    }
  }, [text]);

  function send() {
    if (canSend) {
      onSend(trimmed);
      setText("");
      area.current?.focus();
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && enterSends()) {
      event.preventDefault();
      send();
    }
  }

  const field = (
    <div
      style={{ viewTransitionName: "composer" }}
      className={cn(
        "group/composer flex items-end gap-1 rounded-[26px] border border-line bg-raised p-2 pl-4 shadow-float",
        "transition-[border-color,box-shadow] duration-200",
        "focus-within:border-[color-mix(in_srgb,var(--accent)_45%,var(--line))]",
        "focus-within:shadow-[var(--elevation-float),0_0_0_4px_color-mix(in_srgb,var(--accent)_12%,transparent)]",
        tooLong && "border-danger",
      )}
    >
      {leading}
      <label id={labelId} className="sr-only">
        Message à Lorakus
      </label>
      <textarea
        ref={area}
        aria-labelledby={labelId}
        aria-invalid={tooLong}
        aria-describedby={tooLong ? errorId : undefined}
        rows={1}
        value={text}
        autoFocus={autoFocus}
        disabled={disabled}
        placeholder="Demande à Lorakus"
        onChange={(e) => {
          setText(e.target.value);
        }}
        onKeyDown={onKeyDown}
        className="max-h-56 min-h-10 flex-1 resize-none bg-transparent py-2 text-reading leading-6 text-ink outline-none placeholder:text-ink-faint disabled:opacity-60"
      />
      {trailing}
      <button
        type="button"
        aria-label="Envoyer"
        onClick={send}
        disabled={!canSend}
        className={cn(
          "grid size-10 shrink-0 place-items-center rounded-full transition-[background-color,color,transform] duration-200",
          "active:scale-95 disabled:cursor-not-allowed",
          canSend ? "bg-accent text-accent-ink hover:brightness-110" : "bg-hover text-ink-faint",
        )}
      >
        <ArrowUp aria-hidden="true" className="size-5" strokeWidth={2.25} />
      </button>
    </div>
  );

  const error = tooLong && (
    <p id={errorId} role="alert" className="mt-2 px-4 text-sm text-danger">
      Message trop long : {text.length} caractères sur {MAX_MESSAGE_CHARS} au maximum.
    </p>
  );

  if (variant === "hero") {
    return (
      <div className="w-full">
        {field}
        {error}
        {footer}
      </div>
    );
  }

  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10">
      {/* Fondu : les messages s'effacent sous le champ au lieu d'etre coupes par une ligne. */}
      <div className="h-8 bg-gradient-to-t from-background to-transparent" />
      <div className="pointer-events-auto bg-background px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:px-6">
        <div className="mx-auto max-w-3xl">
          {field}
          {error}
          {footer}
        </div>
      </div>
    </div>
  );
}
