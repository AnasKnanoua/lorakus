/**
 * Page « Mes données » (PR 41), contre le faux backend : export avec preuve d'identité,
 * suppression de toutes les conversations, accès depuis la barre latérale, accessibilité.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { filenameFrom } from "@/api/data";
import { installFakeApi } from "@/test/fakeApi";
import { renderApp } from "@/test/renderApp";

/** Fichiers « enregistres » par saveFile : nom et contenu (jsdom n'a pas de vrai telechargement). */
let saved: { name: string; url: string }[] = [];
let blobs: Blob[] = [];

beforeEach(() => {
  saved = [];
  blobs = [];
  // jsdom ne fournit pas URL.createObjectURL : le faux garde le Blob pour le relire.
  vi.stubGlobal(
    "URL",
    Object.assign(URL, {
      createObjectURL: vi.fn((blob: Blob) => {
        blobs.push(blob);
        return `blob:lorakus/${String(blobs.length)}`;
      }),
      revokeObjectURL: vi.fn(),
    }),
  );
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    saved.push({ name: this.download, url: this.href });
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function conversations(count: number) {
  return new Map(
    Array.from({ length: count }, (_, i) => [`c${String(i)}`, { id: `c${String(i)}`, title: `Sujet ${String(i)}`, messages: [] }]),
  );
}

describe("mes données", () => {
  it("lit le nom du fichier dans l'en-tête du serveur, sans chemin", () => {
    expect(filenameFrom('attachment; filename="lorakus-export-2026-11-18.json"')).toBe("lorakus-export-2026-11-18.json");
    expect(filenameFrom('attachment; filename="../../etc/passwd"')).toBe("lorakus-export.json");
    expect(filenameFrom(null)).toBe("lorakus-export.json");
  });

  it("télécharge l'export, après une preuve d'identité si elle est trop ancienne", async () => {
    const state = installFakeApi({ loggedIn: true, reauthStale: true });
    renderApp("/donnees");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Télécharger" }));
    const proof = await screen.findByRole("form", { name: "Confirme ton identité" });
    expect(saved).toEqual([]);
    await user.type(within(proof).getByLabelText("Mot de passe"), state.password);
    await user.click(within(proof).getByRole("button", { name: "Confirmer" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Export téléchargé : lorakus-export-2026-11-18.json");
    expect(saved).toEqual([{ name: "lorakus-export-2026-11-18.json", url: "blob:lorakus/1" }]);
    expect(JSON.parse(await (blobs[0] as Blob).text())).toEqual(state.exportBody);
    expect(screen.queryByRole("form", { name: "Confirme ton identité" })).toBeNull();
    expect(state.requests.filter((r) => r.path === "/api/v1/data/export")).toHaveLength(2);
  });

  it("refuse un mauvais mot de passe sans rien télécharger", async () => {
    installFakeApi({ loggedIn: true, reauthStale: true });
    renderApp("/donnees");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Télécharger" }));
    const proof = await screen.findByRole("form", { name: "Confirme ton identité" });
    await user.type(within(proof).getByLabelText("Mot de passe"), "pas le bon");
    await user.click(within(proof).getByRole("button", { name: "Confirmer" }));

    expect(await within(proof).findByRole("alert")).toHaveTextContent("Mot de passe ou code incorrect.");
    expect(saved).toEqual([]);
  });

  it("supprime toutes les conversations après confirmation, sans toucher aux souvenirs", async () => {
    const state = installFakeApi({ loggedIn: true, conversations: conversations(2) });
    renderApp("/donnees");
    const user = userEvent.setup();
    expect(await screen.findByText("Sujet 0")).toBeInTheDocument(); // barre laterale

    await user.click(await screen.findByRole("button", { name: "Tout supprimer" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Supprimer toutes les conversations ?" });
    await user.click(within(dialog).getByRole("button", { name: "Supprimer" }));

    expect(await screen.findByRole("status")).toHaveTextContent("2 conversations supprimées.");
    expect(state.conversations.size).toBe(0);
    await waitFor(() => {
      expect(screen.queryByText("Sujet 0")).toBeNull();
    });
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(state.requests.some((r) => r.path.startsWith("/api/v1/memory/") && r.method !== "GET")).toBe(false);
  });

  it("demande une preuve d'identité avant de supprimer si la dernière est trop ancienne", async () => {
    const state = installFakeApi({ loggedIn: true, reauthStale: true, conversations: conversations(1) });
    renderApp("/donnees");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Tout supprimer" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Supprimer" }));
    const proof = await screen.findByRole("form", { name: "Confirme ton identité" });
    expect(state.conversations.size).toBe(1);
    await user.type(within(proof).getByLabelText("Mot de passe"), state.password);
    await user.click(within(proof).getByRole("button", { name: "Confirmer" }));

    expect(await screen.findByRole("status")).toHaveTextContent("1 conversation supprimée.");
    expect(state.conversations.size).toBe(0);
  });

  it("s'ouvre depuis l'icône du pied de la barre latérale", async () => {
    installFakeApi({ loggedIn: true });
    renderApp("/");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("link", { name: "Mes données" }));

    expect(await screen.findByRole("heading", { level: 1, name: "Mes données" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Mes données" })).toHaveAttribute("aria-current", "page");
  });

  it("n'a pas de défaut d'accessibilité détectable", async () => {
    installFakeApi({ loggedIn: true, reauthStale: true });
    const { container } = renderApp("/donnees");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Télécharger" }));
    await screen.findByRole("form", { name: "Confirme ton identité" });

    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations.map((v) => `${v.id} : ${v.help}`)).toEqual([]);
  });
});
