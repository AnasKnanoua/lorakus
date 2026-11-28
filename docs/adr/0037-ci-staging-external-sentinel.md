# ADR-0037 — Staging éphémère dans la CI, sentinelle externe par signal de vie

- **Statut** : Validé (2026-11-11)
- **Date** : 2026-11-11
- **Revue prévue** : phase 17 (environnement Red Team), ou disparition d'un des services gratuits utilisés

## Contexte

L'ADR 0036 plaçait le staging et la sentinelle externe sur une VM Azure for Students. Vérifié le 2026-11-11 : l'abonnement n'autorise que cinq régions (Pologne, France, Belgique, Autriche, Allemagne), et les trois tailles gratuites (B1s, B2pts v2, B2ats v2) n'y sont disponibles dans aucune. La plus petite taille autorisée (D2ls v6, 4 Go) épuiserait le crédit de 90 $ en quelques semaines, pour une machine qui doit tourner toute l'année.

La production n'expose aucun port avant la phase 3 : une sonde entrante est impossible.

## Décision

**Staging** : éphémère, dans le workflow `deploy.yml`, sur un runner GitHub ARM (gratuit pour un dépôt public), avant chaque déploiement en production. `infra/staging/staging-test.sh` rejoue avec le vrai `deploy.sh` : installation de la version en production, mise à jour vers la nouvelle (sauvegarde avant migration, migrations, santé), retour arrière, redéploiement, sauvegarde quotidienne, alerte de test, puis restauration selon `docs/runbooks/restore.md` avec vérification d'une donnée témoin. Données synthétiques ; B2 remplacé par un dossier local (`compose.host.yml`, absent en production) ; aucun secret de production. Si le staging échoue, la production n'est pas touchée et l'approbation n'est même pas demandée.

**Sentinelle** : healthchecks.io (formule gratuite), en « interrupteur d'homme mort ». La règle `LorakusWatchdog` est toujours active ; en production, Alertmanager l'envoie à healthchecks.io environ toutes les 2 minutes (mesuré), jamais à Discord. Si le signal cesse (serveur éteint, Docker, Prometheus ou Alertmanager arrêtés, réseau coupé), healthchecks.io prévient Discord de l'extérieur, en moins de 10 minutes (période 2 min, tolérance 5 min). `LorakusHeartbeatFailing` prévient sur Discord, depuis la production, quand l'envoi échoue (adresse fausse, service injoignable). Le signal ne part jamais du développement ni du staging.

**Azure** : rien n'est créé. Le crédit reste disponible jusqu'au 09/11/2027 (VM ponctuelle pour la phase 17, par exemple).

## Alternatives rejetées

- VM Azure payante en continu : crédit épuisé en quelques semaines.
- Sonde HTTP entrante (Uptime Kuma, etc.) : impossible sans port ouvert, et contraire au principe « aucune exposition avant la P3 ».
- Signal de vie par SSH vers une machine tierce : demande une machine qu'on n'a pas, et une clé de plus.
- Minuteur dédié qui pousse le signal : ne prouve pas que la chaîne d'alerte fonctionne ; le passage par Alertmanager si.
- Staging fixe sur `oraclevps` ou sur l'hôte de production : écartés par l'ADR 0036.

## Conséquences

- Remplace l'ADR 0036 pour le staging et la sentinelle ; le reste de l'ADR 0036 (production, domaine, `oraclevps` hors périmètre) est inchangé.
- Plus aucune dépendance à Azure for Students, donc plus de contrainte « usage non commercial » sur l'exploitation.
- Un déploiement prend quelques minutes de plus (staging avant approbation).
- Le staging n'est pas un environnement permanent : les tests offensifs de la phase 17 demanderont une cible dédiée, à décider à ce moment-là.
- Dépendance à deux services gratuits (runners GitHub, healthchecks.io), remplaçables : un autre service de signal de vie ne demande que de changer `HEALTHCHECKS_PING_URL`.
- Le premier passage du staging compare la nouvelle version à la dernière déployée avec succès (titre de run « Deploy (deploy) ») ; à défaut, au dernier run de déploiement réussi.

## Amendement du 2026-11-22 (P6, PR 56) : sonde externe de l'adresse publique

La sentinelle prouve que la production vit, pas qu'Internet la joint. Depuis la PR 35, `app.lorakus.app` est public : DNS, liste de sécurité Oracle, `firewalld`, Caddy et certificat peuvent casser sans qu'aucune alerte interne le voie.

- **Sonde** : le workflow `external-probe.yml` (runner GitHub, toutes les 15 minutes, `workflow_dispatch` en plus) lance `infra/probe/external_probe.py`, bibliothèque standard de Python seulement. Elle vérifie la redirection HTTP vers HTTPS (le port 80 sert aussi au renouvellement), le certificat (autorité du magasin du système, nom), `/api/health/ready` (200 et `{"status": "ok"}` : une page HTML voudrait dire que `/api` ne mène plus à l'API) et l'en-tête HSTS (la réponse vient de notre Caddy). Trois essais à 20 secondes d'intervalle avant de conclure.
- **Certificat** : il doit rester au moins un sixième de sa durée de vie (15 jours pour 90). Caddy renouvelle à un tiers ; en dessous d'un sixième, le renouvellement échoue depuis la moitié de sa marge. Seuil relatif plutôt qu'un nombre de jours : il reste juste si Let's Encrypt raccourcit ses certificats.
- **Alerte** : chaque passage envoie à un second check healthchecks.io (`lorakus-public`, période 15 minutes, tolérance 1 heure) un signal de réussite ou d'échec, avec le compte rendu d'une ligne. Un échec prévient Discord tout de suite ; une sonde qui se tait (workflow désactivé, panne de GitHub Actions, secret retiré) prévient à la fin de la tolérance, assez longue pour absorber les retards des workflows programmés. Adresse de ping dans le secret GitHub `HEALTHCHECKS_PUBLIC_PING_URL`, saisie par le propriétaire.
- **Rejeté** : UptimeRobot ou Better Stack (un compte et un fournisseur de plus pour la même vérification, alerte d'expiration réservée aux offres payantes chez certains) ; une sonde depuis `oraclevps` (hors périmètre) ou depuis `oracleworker` (le serveur se joint lui-même même quand Internet ne le joint pas) ; un seuil fixe en jours.
- **Limite connue** : GitHub peut retarder ou sauter un workflow programmé aux heures chargées ; une panne du chemin public se voit donc en 15 à 45 minutes, la disparition du serveur reste détectée en moins de 10 minutes par la sentinelle.

## Correction du 2026-11-25 : la sonde externe ne surveille pas la disponibilité

Mesuré du 22 au 25 novembre : programmée toutes les 15 minutes (environ 240 passages attendus), la sonde a tourné 9 fois, à 4 à 12 heures d'intervalle, tous les passages verts. Chaque silence de plus d'une heure et quart déclenchait « DOWN », chaque passage « UP » : deux jours d'alertes sans aucune panne. La « limite connue » écrite plus haut (« une panne du chemin public se voit en 15 à 45 minutes ») était une supposition, pas une mesure : GitHub ne garantit pas la fréquence des workflows programmés.

- La sonde garde son rôle de **contrôle de la configuration publique** : certificat (seuil d'un sixième de sa durée de vie, soit 15 jours sur 90 : quelques passages par jour suffisent), DNS, port 80, routage de `/api`, HSTS. Elle est programmée quatre fois par jour (`17 */6 * * *`), sans compter sur cette fréquence.
- Check `lorakus-public` : période 1 jour, tolérance 1 jour. Un échec vu par la sonde prévient toujours tout de suite ; seul le silence devient tolérant.
- **Disponibilité vue d'Internet** : pas couverte par la sonde. Un service de surveillance dédié (contrôles toutes les quelques minutes) est proposé au propriétaire, ce qui revient sur le rejet ci-dessus d'un fournisseur de plus ; tranché le même jour (D-L, section suivante).

## Décision du 2026-11-25 (D-L) : UptimeRobot pour la disponibilité vue d'Internet

- **Validée par le propriétaire**, qui a créé la sonde le 2026-11-25 sur son propre compte UptimeRobot (formule gratuite) : type HTTP(s), sur le code de la réponse, `https://app.lorakus.app/api/health/ready`, toutes les 5 minutes, alertes sur Discord et par e-mail.
- **Type HTTP plutôt que « mot-clé »** (recommandé à l'origine) : UptimeRobot ne permet pas de changer le type après la création, et le contrôle du corps (`{"status": "ok"}`, donc que `/api` mène bien à l'API) est déjà fait par la sonde externe. Seule conséquence : une page HTML servie en 200 à la place de l'API passe pour UptimeRobot ; la sonde la voit au passage suivant.
- **Partage des rôles** : UptimeRobot dit vite que le site ne répond plus (Caddy, API, base, réseau, DNS, certificat refusé) ; la sonde dit ce qui casse dans la configuration publique ; la sentinelle dit que le serveur a disparu ; `LorakusWebDown` dit, depuis l'intérieur, que Caddy ne répond plus.
- **Ce que reçoit UptimeRobot** : une requête publique sans session ; la réponse ne contient que `{"status": "ok"}` (ou `unavailable`). Aucun secret à gérer, aucune donnée personnelle.
- **Pourquoi revenir sur le rejet du 2026-11-22** : ce rejet supposait que la sonde GitHub tournait toutes les 15 minutes, ce qui était faux (correction ci-dessus). Un fournisseur de plus coûte un compte ; ne pas voir une panne pendant des heures coûte plus.
- **Délais mesurés** (exercice du 2026-11-27, arrêt de `web` en production, une mesure, `docs/incidents/2026-11-27-exercice-web-arrete.md`) : depuis l'arrêt, `LorakusWebDown` sur Discord en 2 min 44 s, UptimeRobot en 5 min 10 s (panne tombée juste après une vérification réussie) ; après la remise en service, « Résolu » en 1 min 58 s et retour d'UptimeRobot en 4 min 29 s.
- **Limite** : personne ne surveille UptimeRobot lui-même ; sa dernière vérification se regarde à la revue mensuelle des outils (`SECURITY.md` §9).
- Runbook : `docs/runbooks/external-probe.md` ; réglages : `DEPLOYMENT.md` §4.7.

## Amendement du 2026-11-25 (PR 57) : nom du staging

Le staging se sert sous `lorakus.localhost` au lieu de `localhost` (`staging-test.sh`) : Java, donc ZAP, n'envoie pas de SNI pour un nom sans point, et Caddy refuse alors la poignée de main TLS. curl résout seul les noms en `.localhost` vers la machine : les vérifications du staging sont inchangées (rejouées en local avec curl 8.5, celui des runners). Le scan ZAP du staging est décrit par l'ADR 0043.
