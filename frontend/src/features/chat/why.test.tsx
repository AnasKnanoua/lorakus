/**
 * « Pourquoi m'as-tu dit ça ? » (PR 39) : l'explication d'une réponse, contre le faux backend.
 */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { afterEach, describe, expect, it, vi } from "vitest";

import { installFakeApi, type FakeMessage } from "@/test/fakeApi";
import { renderApp } from "@/test/renderApp";

afterEach(() => {
  vi.unstubAllGlobals();
});

const AT = "2026-11-14T09:00:00Z";
const REPLY = "00000000-0000-4000-8000-0000000000aa";

const TRACE = {
  message_id: REPLY,
  prompt_version: "assistant-system-2026-11-14.2",
  model: "claude-haiku-5-5",
  model_calls: 2,
  cost_usd: "0.000560",
  data_classes_sent: ["personal"],
  memory_facts: [{ id: "f1", content: "Révise le matin", category: "habit" }],
  memory_facts_removed: 1,
  tools: [{ tool: "assistant.remember", kind: "card", text: "Retenir : « Aime le thé »", status: "confirmed" }],
  routing: { tier: "rules", best: null, score: null, runner_up: null, reason: "mots-cles" },
  specialists: [
    {
      specialist: "focus",
      display_name: "Sergent",
      intent: "day_plan",
      status: "ok",
      duration_ms: 310,
      cached: false,
      skipped: null,
      data_classes: ["personal"],
    },
    {
      specialist: "slow",
      display_name: "Lent",
      intent: "x",
      status: "timeout",
      duration_ms: 3000,
      cached: false,
      skipped: null,
      data_classes: [],
    },
  ],
};

function conversationWithReply(trace: unknown) {
  const messages: FakeMessage[] = [
    { id: "u1", role: "user", content: "Ma journée ?", status: "ok", model: null, cost_usd: null, created_at: AT },
    {
      id: REPLY,
      role: "assistant",
      content: "Trois cours aujourd'hui.",
      status: "ok",
      model: "claude-haiku-5-5",
      cost_usd: "0.000560",
      created_at: AT,
      actions: [],
    },
  ];
  const api = installFakeApi({
    loggedIn: true,
    conversations: new Map([["c1", { id: "c1", title: "Ma journée ?", messages }]]),
  });
  if (trace !== undefined) {
    api.traces.set(REPLY, trace);
  }
  return api;
}

async function openWhy() {
  const { router } = renderApp("/");
  await router.navigate({ to: "/c/$conversationId", params: { conversationId: "c1" } });
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Pourquoi cette réponse ?" }));
  return screen.findByRole("dialog", { name: "Pourquoi cette réponse ?" });
}

describe("pourquoi cette réponse", () => {
  it("explique en clair les souvenirs, outils, spécialistes et le coût", async () => {
    conversationWithReply(TRACE);
    const dialog = await openWhy();

    expect(await within(dialog).findByText("Révise le matin")).toBeVisible();
    expect(dialog).toHaveTextContent("1 souvenir supprimé depuis.");
    expect(dialog).toHaveTextContent("Retenir : « Aime le thé » : confirmée");
    expect(dialog).toHaveTextContent("choisis par mots-clés");
    expect(dialog).toHaveTextContent("Sergent : a répondu, 310 ms");
    expect(dialog).toHaveTextContent("Lent : trop lent, ignoré");
    expect(dialog).toHaveTextContent("claude-haiku-5-5");
    expect(dialog).toHaveTextContent("0.0006 $");
    expect(dialog).toHaveTextContent("personnelles");
  });

  it("dit simplement qu'une ancienne réponse n'a pas d'explication", async () => {
    conversationWithReply(undefined);
    const dialog = await openWhy();
    expect(await within(dialog).findByText(/elle date d'avant cette fonction/u)).toBeVisible();
  });

  it("n'a pas de défaut d'accessibilité détectable", async () => {
    conversationWithReply(TRACE);
    const dialog = await openWhy();
    await within(dialog).findByText("Révise le matin");
    const results = await axe.run(dialog, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations.map((v) => `${v.id} : ${v.help}`)).toEqual([]);
  });
});
