/**
 * Abonnement de CET appareil aux notifications (Web Push), avec le service worker de
 * l'application. Le navigateur demande l'autorisation ; la clé publique VAPID vient du
 * serveur ; l'abonnement obtenu (adresse et clés) est envoyé au serveur, qui ne le montre
 * plus jamais (seulement le nom de l'appareil et celui du service).
 */
import type { BrowserSubscription } from "@/api/notifications";

export type PushSupport = "supported" | "unsupported" | "denied";

/** Ce que permet ce navigateur, sans rien demander. */
export function pushSupport(): PushSupport {
  if (!("serviceWorker" in navigator) || !("PushManager" in globalThis) || !("Notification" in globalThis)) {
    return "unsupported";
  }
  return Notification.permission === "denied" ? "denied" : "supported";
}

function keyBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const base64 = base64url.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((base64url.length + 3) % 4);
  const raw = atob(base64);
  const bytes = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

/** Abonnement existant de cet appareil, ou null. */
export async function currentSubscription(): Promise<PushSubscription | null> {
  const registration = await navigator.serviceWorker.getRegistration("/");
  return registration ? registration.pushManager.getSubscription() : null;
}

export class PushPermissionError extends Error {
  constructor() {
    super("notifications refusées");
    this.name = "PushPermissionError";
  }
}

/** Demande l'autorisation, puis abonne l'appareil ; rend l'abonnement à envoyer au serveur. */
export async function subscribeThisDevice(publicKey: string): Promise<BrowserSubscription> {
  if ((await Notification.requestPermission()) !== "granted") {
    throw new PushPermissionError();
  }
  const registration = await navigator.serviceWorker.ready;
  const existing = await registration.pushManager.getSubscription();
  const subscription =
    existing ??
    (await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(publicKey) }));
  const json = subscription.toJSON();
  if (!json.endpoint || !json.keys?.["p256dh"] || !json.keys["auth"]) {
    throw new Error("abonnement incomplet");
  }
  return { endpoint: json.endpoint, keys: { p256dh: json.keys["p256dh"], auth: json.keys["auth"] } };
}

/** Nom lisible de l'appareil, tiré du navigateur : « Chrome sur Android ». */
export function deviceLabel(userAgent: string = navigator.userAgent): string {
  const browser = /Edg\//.test(userAgent)
    ? "Edge"
    : /Firefox\//.test(userAgent)
      ? "Firefox"
      : /Chrome\//.test(userAgent)
        ? "Chrome"
        : /Safari\//.test(userAgent)
          ? "Safari"
          : "Navigateur";
  const system = /Android/.test(userAgent)
    ? "Android"
    : /iPhone|iPad/.test(userAgent)
      ? "iOS"
      : /Windows/.test(userAgent)
        ? "Windows"
        : /Mac OS X/.test(userAgent)
          ? "macOS"
          : /Linux/.test(userAgent)
            ? "Linux"
            : null;
  return system ? `${browser} sur ${system}` : browser;
}
