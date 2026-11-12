# ADR-0038 — Exposition publique par Caddy, limites par utilisateur dans l'application

- **Statut** : Validé (2026-11-12)
- **Date** : 2026-11-12
- **Revue prévue** : avant toute ouverture commerciale (revue de sécurité complète), ou si l'API passe à plusieurs processus

## Contexte

La PR 35 rend Lorakus utilisable depuis le téléphone sur `https://app.lorakus.app` (D-G, D-K : pas de réseau privé). Il faut un reverse proxy TLS, l'interface servie à la même origine que l'API, des en-têtes de sécurité, l'adresse réelle des visiteurs, et une protection contre l'abus d'une session ou d'une clé, en particulier de l'API d'IA payante.

## Décision

**Image `lorakus-web`** : Caddy officiel (épinglé par empreinte, publié depuis plus de 14 jours) et l'interface construite. Construite et analysée par `publish.yml` comme les deux autres images, déployée par empreinte. Caddy est le seul service publié sur Internet (80 et 443) ; l'API reste sur `127.0.0.1:8001`.

- Caddy tourne sous un utilisateur non root (uid 10002), sans capacité, système de fichiers en lecture seule ; il écoute 8080 et 8443 dans le conteneur. Redirection HTTP vers HTTPS écrite à la main (308), HTTP/3 désactivé, administration désactivée.
- Certificat Let's Encrypt automatique en production (`LORAKUS_TLS=acme`), CA locale au staging (`internal`). Certificats dans le volume `caddy-data`, jamais supprimé.
- En-têtes : HSTS un an, CSP `script-src 'self'` sans script en ligne, `frame-ancestors 'none'`, `nosniff`, `no-referrer`, `Permissions-Policy` restrictive, en-tête `Server` retiré. `style-src` admet `'unsafe-inline'` : Radix injecte une balise `<style>` pour bloquer le défilement des fenêtres de dialogue ; le risque d'une injection de style est faible tant que les scripts restent stricts.
- Corps de requête limité à 1 Mo.

**Adresse réelle** : Caddy remplace `X-Forwarded-For` par l'adresse du visiteur. Caddy a une adresse fixe (`172.31.250.2`) sur un réseau Docker dédié (`edge`, `172.31.250.0/24`), hors de la plage d'attribution automatique (`ip_range` `.128/25`) pour qu'aucun autre conteneur ne la prenne ; uvicorn ne croit l'en-tête que venant d'elle (`FORWARDED_ALLOW_IPS`).

**Origine** : toute écriture (POST, PUT, PATCH, DELETE) sous `/api/` qui porte `Origin` ou `Sec-Fetch-Site` doit venir de `LORAKUS_PUBLIC_ORIGIN` ; sinon 403 `origin_refused`. Les clients sans navigateur n'envoient pas ces en-têtes et passent : ils ne peuvent pas utiliser le cookie d'un autre. Seconde barrière derrière `SameSite=Strict`.

**Limites par utilisateur**, comptées dans PostgreSQL (table `core_rate_limits`, RLS forcée), fenêtres fixes :

- toute requête authentifiée : 300 par minute, dont 60 écritures ; au-delà 429 avec `Retry-After` ;
- appels d'IA (dans le `ModelRouter`, seul passage vers un fournisseur) : 6 par minute, 200 par jour, 2 réponses simultanées ; au-delà, réponse par gabarit sans appel payant.

Elles s'ajoutent au plafond mensuel (3 $) et au crédit prépayé sans rechargement (10 $), qui bornent la perte maximale.

**Double authentification obligatoire en production** : sans second facteur confirmé, aucune session ne s'ouvre (403 `second_factor_setup_required`) et les sessions existantes sont refusées ; elle ne peut pas être désactivée depuis l'application. Activation sur le serveur : `python -m lorakus.cli enable-second-factor`.

**Déploiement** : `deploy.sh` accepte une quatrième empreinte (image web) et annonce `LORAKUS_DEPLOY_PROTOCOL=2` dans `status`. Pour un serveur dont le script est antérieur, `deploy.yml` déploie d'abord sans l'image web (ce qui installe le nouveau script), puis avec elle. Le staging rejoue ce passage et vérifie HTTPS, CSP, origine et redirection.

## Alternatives rejetées

- Limite par adresse IP dans Caddy : demande un module tiers, donc une image Caddy recompilée ; les routes publiques sans session se limitent à la connexion, déjà limitée par compte et par IP dans PostgreSQL.
- Limites en mémoire du processus : perdues à chaque redémarrage, fausses dès deux processus.
- Caddy en root avec `NET_BIND_SERVICE` : root dans le conteneur sans nécessité.
- Nginx + Certbot : deux composants et un renouvellement à surveiller, pour le même résultat.
- Jeton CSRF : redondant avec `SameSite=Strict` et le contrôle d'origine pour une interface à la même origine.

## Conséquences

- Docker publie ses ports en contournant `firewalld` : seul `web` publie un port sur toutes les interfaces, tout le reste est lié à `127.0.0.1` (vérifié dans les fichiers Compose).
- L'expiration du certificat n'est pas encore surveillée (Caddy renouvelle 30 jours avant ; un échec se voit dans ses journaux) : surveillance externe de l'adresse publique prévue en P6.
- Les compteurs de simultanéité IA sont propres au processus : à revoir si l'API tourne un jour dans plusieurs processus.
