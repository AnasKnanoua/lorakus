import { Info } from "lucide-react";

import type { ReplyStatus } from "@/api/assistant";
import type { ToolAction } from "@/api/tools";
import { CopyButton } from "@/components/CopyButton";
import { Markdown } from "@/components/Markdown";
import { Orb } from "@/components/Orb";

import { ToolActions } from "./ToolActions";

export function UserMessage({ text }: { text: string }) {
  return (
    <div className="flex animate-fade-up justify-end">
      <p className="max-w-[85%] rounded-[22px] rounded-br-lg bg-raised px-4 py-2.5 text-reading whitespace-pre-wrap [overflow-wrap:anywhere] sm:max-w-[75%]">
        {text}
      </p>
    </div>
  );
}

/**
 * Reponse de Lorakus : texte integre a la page (pas de bulle), precede de l'orbe.
 * Pendant l'ecriture, l'orbe s'anime ; avant le premier mot, « Lorakus réfléchit ».
 */
export function AssistantMessage({
  text,
  status,
  writing = false,
  actions = [],
  conversationId = "",
}: {
  text: string;
  status: ReplyStatus | "streaming";
  writing?: boolean;
  /** Outils utilises et cartes de confirmation de la reponse (PR 38). */
  actions?: readonly ToolAction[];
  conversationId?: string;
}) {
  const done = !writing && status !== "fallback" && text.length > 0;
  const thinking = !text && actions.length === 0;
  return (
    <div className="group/answer flex animate-fade-up gap-3.5 sm:gap-4">
      <Orb thinking={writing} className="mt-1 size-[22px]" />
      <div className="min-w-0 flex-1">
        {status === "fallback" ? (
          <p className="flex gap-2 text-reading text-ink-muted">
            <Info className="mt-1.5 size-4 shrink-0" aria-hidden="true" />
            <span>{text}</span>
          </p>
        ) : text ? (
          <Markdown text={text} />
        ) : thinking ? (
          <p className="text-reading">
            <span className="shimmer-text">Lorakus réfléchit…</span>
          </p>
        ) : null}
        <ToolActions actions={actions} conversationId={conversationId} />
        {status === "interrupted" && (
          <p className="mt-2 text-sm text-ink-muted">Réponse interrompue.</p>
        )}
        {done && (
          <div className="mt-2 -ml-1.5 flex gap-1 transition-opacity duration-200 [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-focus-within/answer:opacity-100 [@media(hover:hover)]:group-hover/answer:opacity-100">
            <CopyButton text={text} label="Copier la réponse" />
          </div>
        )}
      </div>
    </div>
  );
}
