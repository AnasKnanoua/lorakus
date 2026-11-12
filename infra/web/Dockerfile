# Image lorakus-web : Caddy officiel et l'interface construite (PR 35, ADR 0038).
# Construite depuis la racine du depot : docker build -f infra/web/Dockerfile .
# Images de base epinglees par empreinte, publiees depuis plus de 14 jours (DEVELOPMENT.md).

# ---------------------------------------------------------------- construction
# Plateforme de la machine qui construit : le resultat (HTML, JS, CSS) ne depend pas de
# l'architecture, inutile de lancer Node en emulation.
FROM --platform=$BUILDPLATFORM node:22.23.4-alpine@sha256:fe4f6d74e20370acb04ad889077d14d0f64a9c8ea6a42bc60cddf1e844699914 AS build

WORKDIR /frontend
# Version de pnpm figee dans package.json (champ packageManager), comme dans la CI.
COPY frontend/package.json ./
RUN npm install --global --ignore-scripts "pnpm@$(node -p 'require("./package.json").packageManager.split("@")[1]')"
COPY frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

# ---------------------------------------------------------------- execution
FROM caddy:2.11.7-alpine@sha256:eb4d35b7452d1ab6171fbdbe8d9275b2301dad6dad92115d91e19fb9b24d510f

# L'image officielle donne a /usr/bin/caddy la capacite de fichier cap_net_bind_service
# (setcap). Avec cap_drop: ALL et no-new-privileges, le noyau refuse alors de lancer le
# programme (« exec /usr/bin/caddy: operation not permitted »). Caddy ecoute sur 8080 et
# 8443 et n'en a pas besoin : on le recopie sans cette capacite (install ne copie pas les
# attributs etendus) et on supprime l'original.
RUN install -m 0755 /usr/bin/caddy /usr/local/bin/caddy && rm /usr/bin/caddy

# Correctifs de securite Alpine plus recents que l'image de base (epinglee a plus de 14 jours).
# Exception assumee a la regle des 14 jours : un correctif d'une vulnerabilite critique venant
# du depot officiel d'Alpine. Version minimale exigee : la construction echoue si elle manque.
# A retirer quand Dependabot proposera une image de base qui l'inclut.
# - brotli-libs : CVE-2026-111497 (critique, ecriture hors limites dans le decodeur).
RUN apk add --no-cache --upgrade 'brotli-libs>=1.2.1-r0'

# Utilisateur dedie, sans shell. /data (certificats) et /config lui appartiennent : un volume
# neuf monte sur /data herite de ces droits.
RUN addgroup -S -g 10002 caddy-web \
 && adduser -S -D -H -u 10002 -G caddy-web -s /sbin/nologin caddy-web \
 && mkdir -p /data/caddy /config/caddy \
 && chown -R caddy-web:caddy-web /data /config

# Fichiers appartenant a root, lisibles par tous : Caddy ne peut pas les modifier.
COPY --chown=root:root infra/web/Caddyfile /etc/caddy/Caddyfile
COPY --from=build --chown=root:root /frontend/dist /srv

USER caddy-web
EXPOSE 8080 8443 8081

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --start-interval=2s --retries=3 \
  CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8081/healthz"]

CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
