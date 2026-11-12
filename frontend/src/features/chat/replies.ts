/**
 * Reponses en cours, hors du cycle de vie des ecrans.
 *
 * Une reponse n'est pas attachee a l'ecran qui l'a demandee : on peut changer de
 * conversation pendant qu'elle s'ecrit, elle se termine et s'enregistre cote serveur.
 * Les ecrans s'abonnent a la conversation affichee (useLiveTurn). Une fois la reponse finie
 * et la conversation rechargee, le tour en direct disparait au profit des messages
 * enregistres : le serveur reste la seule source de verite.
 */
import type { QueryClient } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";

import { sendMessage, type ReplyStatus } from "@/api/assistant";

export interface LiveTurn {
  user: string;
  assistant: string;
  status: ReplyStatus | "streaming" | "error";
}

const turns = new Map<string, LiveTurn>();
const listeners = new Set<() => void>();
let budgetWarning = false;

function update(conversationId: string, turn: LiveTurn | null): void {
  if (turn) {
    turns.set(conversationId, turn);
  } else {
    turns.delete(conversationId);
  }
  listeners.forEach((listener) => {
    listener();
  });
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useLiveTurn(conversationId: string): LiveTurn | null {
  return useSyncExternalStore(subscribe, () => turns.get(conversationId) ?? null);
}

export function useBudgetWarning(): boolean {
  return useSyncExternalStore(subscribe, () => budgetWarning);
}

export function isStreaming(conversationId: string): boolean {
  return turns.get(conversationId)?.status === "streaming";
}

/** Envoie un message et suit sa reponse jusqu'au bout, quel que soit l'ecran affiche. */
export async function startReply(
  queryClient: QueryClient,
  conversationId: string,
  text: string,
): Promise<void> {
  if (isStreaming(conversationId)) {
    return; // une reponse a la fois par conversation
  }
  let assistant = "";
  update(conversationId, { user: text, assistant, status: "streaming" });
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ["assistant", "conversation", conversationId] }),
      queryClient.invalidateQueries({ queryKey: ["assistant", "conversations"] }),
    ]);
  try {
    const done = await sendMessage(conversationId, text, (delta) => {
      assistant += delta;
      update(conversationId, { user: text, assistant, status: "streaming" });
    });
    if (done.budgetWarning && !budgetWarning) {
      budgetWarning = true;
    }
    update(conversationId, { user: text, assistant, status: done.status });
    await refresh();
    update(conversationId, null);
  } catch {
    // Le serveur a peut-etre enregistre le message (et une reponse partielle) : on recharge
    // ce qu'il a, et le tour en direct ne garde que l'avis d'erreur.
    await refresh().catch(() => undefined);
    update(conversationId, { user: "", assistant: "", status: "error" });
  }
}

/**
 * Messages enregistres a afficher a cote du tour en direct, sans doublon.
 *
 * Le serveur enregistre le message de l'utilisateur des le debut du tour, puis la reponse a la
 * fin : selon le moment ou la conversation est rechargee, ils figurent deja dans la liste
 * enregistree alors que le tour en direct les affiche aussi.
 * - Pendant l'ecriture, seul le message de l'utilisateur peut etre enregistre : on le retire
 *   s'il termine la liste.
 * - Une fois la reponse terminee (avant l'effacement du tour en direct), on retire la paire.
 * Pendant l'ecriture, une ancienne paire identique (meme message envoye deux fois) n'est donc
 * jamais retiree a tort.
 */
export function withoutLiveTurn<M extends { role: string; content: string }>(
  messages: readonly M[],
  live: LiveTurn | null,
): readonly M[] {
  if (!live || live.status === "error") return messages;
  const last = messages.at(-1);
  const beforeLast = messages.at(-2);
  if (live.status === "streaming") {
    return last?.role === "user" && last.content === live.user ? messages.slice(0, -1) : messages;
  }
  if (last?.role === "assistant" && beforeLast?.role === "user" && beforeLast.content === live.user) {
    return messages.slice(0, -2);
  }
  return last?.role === "user" && last.content === live.user ? messages.slice(0, -1) : messages;
}

/** Pour les tests : repart d'un etat vide. */
export function resetReplies(): void {
  turns.clear();
  budgetWarning = false;
  listeners.forEach((listener) => {
    listener();
  });
}
