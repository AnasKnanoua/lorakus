/**
 * Page « Notifications » (P5), contre le faux backend et un faux navigateur (service worker,
 * PushManager, autorisation) : activer sur cet appareil, refus, navigateur sans notifications,
 * appareils (nom seulement), retrait, test.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { afterEach, describe, expect, it, vi } from "vitest";

import { deviceLabel } from "@/lib/push";
import { installFakeApi, type FakeDevice } from "@/test/fakeApi";
import { renderApp } from "@/test/renderApp";

// Clé publique factice du serveur : 65 octets, le premier vaut 4 (point non compressé).
const SERVER_PUBLIC = "B" + "A".repeat(86);
const ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc";
const PHONE: FakeDevice = {
  id: "d1",
  label: "Chrome sur Android",
  service: "fcm.googleapis.com",
  created_at: "2026-11-20T08:00:00Z",
  last_success_at: "2026-11-22T09:00:00Z",
};

interface FakeBrowser {
  permission: NotificationPermission;
  answer: NotificationPermission;
  subscription: { endpoint: string; toJSON: () => unknown } | null;
  subscribed: unknown[];
}

function fakeBrowser(overrides: Partial<FakeBrowser> = {}): FakeBrowser {
  const browser: FakeBrowser = { permission: "default", answer: "granted", subscription: null, subscribed: [], ...overrides };
  const pushManager = {
    getSubscription: () => Promise.resolve(browser.subscription),
    subscribe: (options: unknown) => {
      browser.subscribed.push(options);
      browser.subscription = {
        endpoint: ENDPOINT,
        toJSON: () => ({ endpoint: ENDPOINT, keys: { p256dh: "cle-appareil", auth: "secret" } }),
      };
      return Promise.resolve(browser.subscription);
    },
  };
  const registration = { pushManager };
  vi.stubGlobal("PushManager", function PushManager() {
    return undefined;
  });
  const notification = {
    get permission() {
      return browser.permission;
    },
    requestPermission: () => {
      browser.permission = browser.answer;
      return Promise.resolve(browser.answer);
    },
  };
  vi.stubGlobal("Notification", notification);
  Object.defineProperty(navigator, "serviceWorker", {
    configurable: true,
    value: { ready: Promise.resolve(registration), getRegistration: () => Promise.resolve(registration) },
  });
  return browser;
}

afterEach(() => {
  vi.unstubAllGlobals();
  Reflect.deleteProperty(navigator, "serviceWorker");
});

describe("notifications", () => {
  it("dit les règles et active les notifications sur cet appareil", async () => {
    const browser = fakeBrowser();
    const state = installFakeApi({ loggedIn: true, pushKey: SERVER_PUBLIC });
    renderApp("/notifications");
    const user = userEvent.setup();

    expect(await screen.findByRole("heading", { level: 1, name: "Notifications" })).toBeVisible();
    expect(screen.getByText(/trois par jour au plus/)).toBeVisible();
    expect(await screen.findByText("Aucun appareil.")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Activer sur cet appareil" }));

    expect(await screen.findByText("Notifications activées sur cet appareil.")).toBeVisible();
    // La clé du serveur est donnée au navigateur en octets ; l'abonnement part au serveur.
    const [options] = browser.subscribed as [{ userVisibleOnly: boolean; applicationServerKey: Uint8Array }];
    expect(options.userVisibleOnly).toBe(true);
    expect(options.applicationServerKey).toHaveLength(65);
    expect(options.applicationServerKey[0]).toBe(4);
    const sent = state.requests.find((r) => r.path === "/api/v1/notifications/push/devices");
    expect(sent?.body).toEqual({
      endpoint: ENDPOINT,
      keys: { p256dh: "cle-appareil", auth: "secret" },
      label: deviceLabel(),
    });
    const devices = within(await screen.findByRole("list", { name: "Appareils" }));
    expect(devices.getByText(deviceLabel())).toBeVisible();
    expect(screen.getByText("Cet appareil est abonné aux notifications.")).toBeVisible();
    expect(document.body.textContent).not.toContain(ENDPOINT); // l'adresse n'est jamais montrée
    const results = await axe.run(document.body);
    expect(results.violations).toEqual([]);
  });

  it("explique un refus du navigateur sans rien envoyer", async () => {
    fakeBrowser({ answer: "denied" });
    const state = installFakeApi({ loggedIn: true, pushKey: SERVER_PUBLIC });
    renderApp("/notifications");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Activer sur cet appareil" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Tu as refusé les notifications");
    expect(state.requests.some((r) => r.path === "/api/v1/notifications/push/devices")).toBe(false);
  });

  it("dit quand ce n'est pas possible : navigateur, blocage, serveur", async () => {
    installFakeApi({ loggedIn: true, pushKey: SERVER_PUBLIC });
    const first = renderApp("/notifications"); // jsdom : ni service worker ni PushManager
    expect(await screen.findByText(/Ce navigateur ne sait pas recevoir de notifications/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Activer sur cet appareil" })).toBeNull();
    first.unmount();

    fakeBrowser({ permission: "denied" });
    const second = renderApp("/notifications");
    expect(await screen.findByText(/Les notifications sont bloquées pour ce site/)).toBeVisible();
    second.unmount();

    installFakeApi({ loggedIn: true, pushKey: null });
    renderApp("/notifications");
    expect(await screen.findByText("Les notifications ne sont pas disponibles sur ce serveur.")).toBeVisible();
  });

  it("liste les appareils, en retire un et envoie un test", async () => {
    fakeBrowser();
    const state = installFakeApi({ loggedIn: true, pushKey: SERVER_PUBLIC, devices: [PHONE] });
    renderApp("/notifications");
    const user = userEvent.setup();

    const devices = within(await screen.findByRole("list", { name: "Appareils" }));
    expect(devices.getByText("Chrome sur Android")).toBeVisible();
    expect(devices.getByText("Dernière notification le 22 novembre")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Envoyer une notification de test" }));
    expect(await screen.findByText(/Notification de test envoyée/)).toBeVisible();
    await user.click(devices.getByRole("button", { name: "Retirer Chrome sur Android" }));
    expect(await screen.findByText("Aucun appareil.")).toBeVisible();
    expect(state.devices).toEqual([]);
  });

  it("nomme l'appareil d'après le navigateur", () => {
    const android = "Mozilla/5.0 (Linux; Android 16) AppleWebKit/537.36 Chrome/142.0 Mobile Safari/537.36";
    expect(deviceLabel(android)).toBe("Chrome sur Android");
    expect(deviceLabel("Mozilla/5.0 (Windows NT 10.0) Gecko/20100101 Firefox/150.0")).toBe("Firefox sur Windows");
    expect(deviceLabel("Mozilla/5.0 (iPhone; CPU iPhone OS 19_0 like Mac OS X) Version/19.0 Safari/605")).toBe(
      "Safari sur iOS",
    );
    expect(deviceLabel("Mozilla/5.0 (X11; Linux x86_64) Chrome/142 Edg/142")).toBe("Edge sur Linux");
    expect(deviceLabel("curl/8")).toBe("Navigateur");
  });

  it("s'ouvre depuis le pied de la barre latérale", async () => {
    installFakeApi({ loggedIn: true, pushKey: SERVER_PUBLIC });
    renderApp("/today");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("link", { name: "Notifications" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Notifications" })).toBeVisible();
    await waitFor(() => {
      expect(screen.getByRole("link", { name: "Notifications" })).toHaveAttribute("aria-current", "page");
    });
  });
});
