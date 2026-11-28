# Exercice du 2026-11-27 : Caddy (`web`) arrêté en production

- **Type** : exercice, panne provoquée avec l'accord du propriétaire (PR 58, P6). Pas un incident réel.
- **Durée de la coupure** : 5 min 45 s (05:28:54 à 05:34:39 UTC).
- **Impact** : `app.lorakus.app` injoignable depuis Internet. Worker, rappels, Telegram, sentinelle et sauvegardes non touchés. Aucune donnée perdue.
- **Runbook suivi** : [web.md](../runbooks/web.md), version de la PR 58 avant cet exercice.

## But

1. Mesurer, sans les supposer, les délais de `LorakusWebDown` et d'UptimeRobot (décision D-L), à la panne et au retour.
2. Suivre `web.md` à la lettre, comme pendant un vrai incident, et corriger ce qui gêne.

## Chronologie (UTC)

Sources : horloge du serveur (`date -u`), séries Prometheus `up{job="lorakus-web"}` (pas de 15 s) et `ALERTS{alertname="LorakusWebDown"}` (pas de 5 s), heure exacte des messages Discord (tirée de leur identifiant).

| Heure | Événement | Depuis l'arrêt |
| --- | --- | --- |
| 05:28:07 | Dernière vérification réussie d'UptimeRobot (journal d'accès de Caddy) | — |
| 05:28:53 | `T0` : `dc stop web` lancé ; dernière collecte réussie de Prometheus | 0 s |
| 05:28:54 | Caddy arrêté (`SIGTERM`, `exit_code 0`, 0,6 s) | 0 s |
| 05:29:08 | Première collecte en échec, alerte en attente (`pending`) | 14 s |
| 05:31:03 à 05:31:08 | Alerte déclenchée (`firing`), après les 2 minutes de la règle | 2 min 10 s à 2 min 15 s |
| 05:31:37 | **`LorakusWebDown` reçue sur Discord** | **2 min 44 s** |
| 05:34:03 | **Alerte UptimeRobot reçue sur Discord** (« Connection Timeout », sonde d'Ashburn) | **5 min 10 s** |
| 05:34:36 | `R0` : `dc up -d --wait web` | — |
| 05:34:39 | `R1` : Caddy sain, `https://app.lorakus.app/` répond 200 | Remise en service en 3 s |
| 05:34:53 | Première collecte réussie de Prometheus | 14 s après `R1` |
| 05:36:37 | **« Résolu — LorakusWebDown » reçu sur Discord** | **1 min 58 s après `R1`** |
| 05:39:08 | **Retour UptimeRobot reçu sur Discord** (« down for 5 minutes and 4 seconds ») | **4 min 29 s après `R1`** |

L'e-mail d'UptimeRobot n'a pas été horodaté pendant l'exercice.

## Délais retenus

| Mesure | Valeur | Ce qui la compose |
| --- | --- | --- |
| Panne vers `LorakusWebDown` sur Discord | 2 min 44 s | Collecte toutes les 15 s, règle `for: 2m`, attente de groupement d'Alertmanager (30 s) |
| Panne vers UptimeRobot | 5 min 10 s | Intervalle de 5 minutes : la panne est tombée juste après une vérification réussie, cas défavorable |
| Retour vers « Résolu » | 1 min 58 s | Alertmanager n'envoie la suite d'un groupe qu'à son intervalle (`group_interval`, 5 minutes) : « Résolu » est parti à 05:36:37, exactement 5 minutes après le message de panne. Selon la durée de la panne, ce délai va de quelques secondes à 5 minutes |
| Retour vers UptimeRobot « up » | 4 min 29 s | Prochaine vérification d'UptimeRobot |

Une seule mesure de chaque délai. Celui d'UptimeRobot varie selon le moment de la panne dans son cycle de 5 minutes. La durée de panne qu'il affiche (5 min 4 s) compte depuis sa détection, pas depuis le début réel de la panne (5 min 45 s).

## Suivi du runbook

| Étape de `web.md` | Constat | Correction (PR 58) |
| --- | --- | --- |
| Vérifications : `dc ps web api` | `web` n'apparaît pas du tout : `dc ps` ne montre que les services en marche. Le premier constat utile, « Caddy est arrêté », manquait | `dc ps -a` dans tous les runbooks, et la règle rappelée dans le README |
| Vérifications : `dc logs --tail 50 web` | 73 Ko pour 50 lignes : le journal d'accès de Caddy écrit une ligne de plusieurs kilo-octets par requête (en-têtes compris), surtout les passages d'UptimeRobot. Le terminal est rempli, l'information ne se lit pas | Journal d'accès retiré par `grep -v`. Vérifié sur les journaux de l'exercice : il reste 7 lignes, dont l'arrêt par `SIGTERM` |
| Vérifications : `openssl s_client`, `curl` | Connexion refusée : cohérent, mais ne dit pas pourquoi | — |
| Causes probables | Aucune ligne pour « Caddy arrêté proprement sans déploiement » : l'action 1 existait, mais le tableau n'y menait pas | Deux lignes ajoutées : arrêt par `SIGTERM` (code 0), et arrêt avec un autre code ou redémarrages en boucle |
| Action 1 : `dc up -d --wait web` | Caddy sain en 3 s, site à 200, certificats intacts (volume `caddy-data`) | — |

## Autres constats

- **UptimeRobot envoie d'abord un `HEAD`**, auquel l'API répond 405 (seul `GET` est accepté), puis un `GET` 15 secondes plus tard. Les journaux d'accès en sont doublés. Ce n'est pas une erreur 5xx, donc aucune alerte. Accepter `HEAD` sur les routes de santé est noté dans les idées de la ROADMAP, sans urgence.
- **UptimeRobot a vu « Connection Timeout »**, alors que le serveur se voyait lui-même en « Connection refused ». Depuis Internet, sans Caddy pour écouter, la connexion n'est pas refusée mais reste sans réponse : à ne pas lire, pendant un incident, comme un problème de réseau.
- Pendant l'heure précédente, un robot a tenté `POST /` avec un en-tête `Next-Action` (recherche automatique d'une faille de Next.js). Caddy a répondu 405. Lorakus n'utilise pas Next.js ; c'est le bruit habituel d'un site public.

## Suites

- Délais mesurés reportés dans `web.md`, `external-probe.md`, l'ADR 0037 (D-L) et `DEPLOYMENT.md` §4.7.
- À refaire un jour sur un autre runbook critique (`api-down.md`, `restore.md` via le scénario 9).
