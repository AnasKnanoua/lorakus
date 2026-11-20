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

  it("montre les outils sans clic de plus, des titres capitalises et le nom du compte", async () => {
    const conversations = new Map([["c1", { id: "c1", title: "qu'est-ce que j'ai mardi ?", messages: [] }]]);
    installFakeApi({ loggedIn: true, conversations });
    renderApp("/c/c1");
    const nav = (await screen.findAllByRole("navigation", { name: "Navigation principale" }))[0] as HTMLElement;

    expect(await screen.findByRole("heading", { level: 1, name: "Qu'est-ce que j'ai mardi ?" })).toBeVisible();
    expect(await within(nav).findByRole("link", { name: "Calendriers" })).toBeVisible();
    expect(within(nav).queryByRole("button", { name: /Outils/ })).toBeNull();
    const link = await within(nav).findByRole("link", { name: "Qu'est-ce que j'ai mardi ?" });
    expect(link).toHaveAttribute("title", "qu'est-ce que j'ai mardi ?");
    const account = await within(nav).findByTitle(/@/);
    expect(account.textContent).not.toContain("@");
    expect(account.textContent).not.toBe("");
  });
});
