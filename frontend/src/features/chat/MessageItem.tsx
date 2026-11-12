import { Info } from "lucide-react";

import type { ReplyStatus } from "@/api/assistant";
import { Markdown } from "@/components/Markdown";
import { Monogram } from "@/components/Monogram";

export function UserMessage({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <p className="max-w-[85%] rounded-2xl rounded-br-md bg-accent-soft px-4 py-2.5 text-reading whitespace-pre-wrap [overflow-wrap:anywhere]">
        {text}
      </p>
    </div>
  );
}

export function AssistantMessage({
  text,
  status,
  writing = false,
}: {
  text: string;
  status: ReplyStatus | "streaming";
  writing?: boolean;
}) {
  return (
    <div className="flex gap-3">
      <Monogram writing={writing} className="mt-0.5" />
      <div className="min-w-0 flex-1">
        {status === "fallback" ? (
          <p className="flex gap-2 text-reading text-ink-muted">
            <Info className="mt-1 size-4 shrink-0" aria-hidden="true" />
            <span>{text}</span>
          </p>
        ) : text ? (
          <Markdown text={text} />
        ) : (
          <span className="sr-only">L'assistant écrit…</span>
        )}
        {status === "interrupted" && (
          <p className="mt-2 text-sm text-ink-muted">Réponse interrompue.</p>
        )}
      </div>
    </div>
  );
}
