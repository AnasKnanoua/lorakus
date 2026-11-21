/*
 * Service worker de Lorakus : rend l'application installable et ouvrable hors connexion.
 *
 * - /api/ : jamais en cache (donnees personnelles), toujours le reseau.
 * - Pages : reseau d'abord (une nouvelle version arrive des qu'on est en ligne) ; hors
 *   connexion, la derniere coquille connue s'affiche et dit que le serveur est injoignable.
 * - /assets/ : fichiers dont le nom contient leur empreinte, donc immuables : cache d'abord.
 * - Notifications (P5, ADR 0042) : le serveur envoie un message chiffre (titre, texte, page) ;
 *   le navigateur le dechiffre et le passe ici. Toucher la notification ouvre la page dite
 *   (meme origine seulement), ou ramene l'onglet deja ouvert. Aucune action depuis la
 *   notification elle-meme : repondre au rappel se fait dans la page.
 */
const CACHE = "lorakus-shell-v1";
const SHELL = ["/", "/manifest.webmanifest", "/icons/icon-192.png", "/icons/icon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin) {
    return;
  }
  if (url.pathname.startsWith("/api/")) {
    return; // reseau uniquement, rien n'est stocke
  }
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            void caches.open(CACHE).then((cache) => cache.put("/", copy));
          }
          return response;
        })
        .catch(() => caches.match("/").then((cached) => cached || Response.error())),
    );
    return;
  }
  if (url.pathname.startsWith("/assets/")) {
    event.respondWith(
      caches.match(request).then(
        (cached) =>
          cached ||
          fetch(request).then((response) => {
            if (response.ok) {
              const copy = response.clone();
              void caches.open(CACHE).then((cache) => cache.put(request, copy));
            }
            return response;
          }),
      ),
    );
  }
});

/** Une page de l'application, jamais une autre origine (« //ailleurs.fr » compris). */
function appPage(raw) {
  try {
    const url = new URL(typeof raw === "string" ? raw : "/today", self.location.origin);
    return url.origin === self.location.origin ? url.href : new URL("/today", self.location.origin).href;
  } catch {
    return new URL("/today", self.location.origin).href;
  }
}

self.addEventListener("push", (event) => {
  let message;
  try {
    message = event.data ? event.data.json() : {};
  } catch {
    message = {};
  }
  const title = typeof message.title === "string" && message.title ? message.title : "Lorakus";
  const body = typeof message.body === "string" ? message.body : "";
  const url = appPage(message.url);
  event.waitUntil(
    self.registration.showNotification(title, {
      body,
      tag: typeof message.tag === "string" ? message.tag : undefined,
      icon: "/icons/icon-192.png",
      badge: "/icons/icon-192.png",
      data: { url },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = appPage(event.notification.data && event.notification.data.url);
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      for (const client of windows) {
        if (new URL(client.url).origin === self.location.origin && "focus" in client) {
          return client.navigate(target).then((opened) => (opened || client).focus());
        }
      }
      return self.clients.openWindow(target);
    }),
  );
});
