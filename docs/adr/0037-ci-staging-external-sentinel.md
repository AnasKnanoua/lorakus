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
