import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "@tanstack/react-router";
import { Trash2 } from "lucide-react";
import { useState } from "react";

import { deleteConversation, type ReplyStatus } from "@/api/assistant";
import { Button } from "@/components/ui/button";
import { conversationQuery } from "@/lib/queries";

import { Composer } from "./Composer";
import { ConfirmDialog } from "./ConfirmDialog";
import { AssistantMessage, UserMessage } from "./MessageItem";
import { MessageList } from "./MessageList";
import { startReply, useBudgetWarning, useLiveTurn } from "./replies";

function asStatus(value: string): ReplyStatus {
  return value === "interrupted" || value === "fallback" ? value : "ok";
}

export function ConversationScreen() {
  const { conversationId } = useParams({ from: "/app/c/$conversationId" });
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const conversation = useQuery(conversationQuery(conversationId));
  const live = useLiveTurn(conversationId);
  const budgetWarning = useBudgetWarning();
  const busy = live?.status === "streaming";
  const [confirming, setConfirming] = useState(false);

  async function remove() {
    await deleteConversation(conversationId);
    queryClient.removeQueries({ queryKey: ["assistant", "conversation", conversationId] });
    await queryClient.invalidateQueries({ queryKey: ["assistant", "conversations"] });
    await navigate({ to: "/" });
  }

  if (conversation.isError) {
    return (
      <div className="mx-auto max-w-md px-6 py-16">
        <h1 className="text-xl font-bold">Conversation introuvable</h1>
        <p className="mt-2 text-ink-muted">Elle a peut-être été supprimée.</p>
      </div>
    );
  }

  const messages = conversation.data?.messages ?? [];
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex h-14 shrink-0 items-center gap-2 border-b border-line px-4 sm:px-6">
        <h1 className="min-w-0 flex-1 truncate font-medium">{conversation.data?.title ?? ""}</h1>
        <Button
          variant="quiet"
          size="icon"
          aria-label="Supprimer la conversation"
          onClick={() => {
            setConfirming(true);
          }}
        >
          <Trash2 aria-hidden="true" />
        </Button>
      </header>

      {budgetWarning && (
        <p role="status" className="bg-notice-soft px-4 py-2 text-center text-sm text-notice">
          Vous avez utilisé 80 % du budget d'IA de ce mois.
        </p>
      )}

      <MessageList busy={busy}>
        {messages.map((m) =>
          m.role === "user" ? (
            <UserMessage key={m.id} text={m.content} />
          ) : (
            <AssistantMessage key={m.id} text={m.content} status={asStatus(m.status)} />
          ),
        )}
        {live && live.status !== "error" && (
          <>
            <UserMessage text={live.user} />
            <AssistantMessage text={live.assistant} status={live.status} writing={live.status === "streaming"} />
          </>
        )}
        {live?.status === "error" && (
          <p role="alert" className="rounded-xl bg-danger-soft px-4 py-3 text-sm text-danger">
            La réponse n'a pas pu être reçue. Vérifiez votre connexion ; votre message est conservé
            ci-dessus s'il a été enregistré.
          </p>
        )}
      </MessageList>

      <Composer onSend={(text) => void startReply(queryClient, conversationId, text)} disabled={busy} />

      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title="Supprimer cette conversation ?"
        description="Elle sera effacée définitivement, avec tous ses messages."
        confirmLabel="Supprimer la conversation"
        onConfirm={remove}
      />
    </div>
  );
}
