/**
 * Bandeau du fuseau horaire (PR 44), contre le faux backend : proposition quand l'appareil
 * n'est pas sur le fuseau du compte, changement seulement apres un clic, refus retenu.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { deviceTimezone } from "@/api/account";
import { installFakeApi } from "@/test/fakeApi";
import { renderApp } from "@/test/renderApp";

/** L'appareil de test se croit a Ankara. */
function deviceAt(timezone: string) {
  const base = new Intl.DateTimeFormat().resolvedOptions();
  vi.spyOn(Intl.DateTimeFormat.prototype, "resolvedOptions").mockReturnValue({ ...base, timeZone: timezone });
}

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("fuseau horaire", () => {
  it("lit le fuseau de l'appareil", () => {
    deviceAt("Europe/Istanbul");
    expect(deviceTimezone()).toBe("Europe/Istanbul");
  });

  it("propose le fuseau de l'appareil et ne change rien sans clic", async () => {
    deviceAt("Europe/Istanbul");
    const state = installFakeApi({ loggedIn: true, timezone: "Europe/Paris" });
    renderApp("/");
    const user = userEvent.setup();

    const banner = await screen.findByRole("region", {
      name: "Fuseau horaire",
    });
    expect(banner).toHaveTextContent("Europe/Istanbul");
    expect(banner).toHaveTextContent("Europe/Paris");
    expect(state.requests.some((r) => r.method === "PUT")).toBe(false);
    const results = await axe.run(banner, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((v) => `${v.id} : ${v.help}`)).toEqual([]);

    await user.click(
      within(banner).getByRole("button", { name: "Utiliser ce fuseau" }),
    );
    await waitFor(() => {
      expect(
        screen.queryByRole("region", { name: "Fuseau horaire" }),
      ).not.toBeInTheDocument();
    });
    expect(state.timezone).toBe("Europe/Istanbul");
    expect(
      state.requests.filter((r) => r.path === "/api/v1/account/timezone"),
    ).toEqual([
      {
        method: "PUT",
        path: "/api/v1/account/timezone",
        body: { timezone: "Europe/Istanbul" },
      },
    ]);
  });

  it("retient le refus pour ce fuseau sur cet appareil", async () => {
    deviceAt("Europe/Istanbul");
    const state = installFakeApi({ loggedIn: true, timezone: "Europe/Paris" });
    const first = renderApp("/");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Garder" }));
    expect(
      screen.queryByRole("region", { name: "Fuseau horaire" }),
    ).not.toBeInTheDocument();
    expect(state.timezone).toBe("Europe/Paris");
    first.unmount();

    // Rechargement : pas de nouvelle question pour le meme fuseau...
    renderApp("/");
    await screen.findByRole("textbox");
    expect(
      screen.queryByRole("region", { name: "Fuseau horaire" }),
    ).not.toBeInTheDocument();
  });

  it("ne montre rien quand l'appareil et le compte sont d'accord", async () => {
    deviceAt("Europe/Paris");
    installFakeApi({ loggedIn: true, timezone: "Europe/Paris" });
    renderApp("/");
    await screen.findByRole("textbox");
    expect(
      screen.queryByRole("region", { name: "Fuseau horaire" }),
    ).not.toBeInTheDocument();
  });
});
