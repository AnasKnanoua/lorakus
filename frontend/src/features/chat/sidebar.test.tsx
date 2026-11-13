/** Barre laterale avec beaucoup de conversations : pagination et groupes par anciennete. */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { installFakeApi } from "@/test/fakeApi";
import { renderApp } from "@/test/renderApp";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("barre latérale", () => {
  it("affiche 25 conversations, puis les suivantes sur demande", async () => {
    const conversations = new Map(
      Array.from({ length: 60 }, (_, i) => [`c${String(i)}`, { id: `c${String(i)}`, title: `Sujet ${String(i)}`, messages: [] }]),
    );
    installFakeApi({ loggedIn: true, conversations });
    renderApp("/");
    const nav = (await screen.findAllByRole("navigation", { name: "Navigation principale" }))[0] as HTMLElement;

    await within(nav).findByText("Sujet 59"); // la plus recente en premier
    expect(within(nav).queryByText("Sujet 34")).toBeNull();
    await userEvent.setup().click(within(nav).getByRole("button", { name: "Afficher plus (35)" }));

    expect(within(nav).getByText("Sujet 34")).toBeVisible();
    expect(within(nav).getByRole("button", { name: "Afficher plus (10)" })).toBeVisible();
    expect(within(nav).getByRole("link", { name: "Mémoire" })).toBeVisible();
  });
});
