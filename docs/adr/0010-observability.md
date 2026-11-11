# ADR-0010 — Observabilité OpenTelemetry → Grafana LGTM

- **Statut** : Validé (exigence) / Accepté (outils)
- **Date** : 2026-11-08
- **Revue prévue** : Phase 6

## Contexte

L'observabilité est une exigence dès la V1, dans un budget d'environ 1,2 Go de RAM.

## Décision

OTel SDK dans l'application, Grafana Alloy, Loki (7 j), Prometheus (15 j), Tempo (3 j), Grafana, Uptime Kuma, alertes vers Telegram.

## Alternatives rejetées

SigNoz (ClickHouse trop lourd) ; Sentry self-hosted.

## Conséquences

Bascule vers un SaaS en changeant l'exporter si la RAM manque.

Amendement du 2026-11-08 (déploiement par paliers, pour limiter la maintenance) : P1 = journaux structurés JSON, métriques Prometheus, Grafana, alertes, Uptime Kuma ; P3 = traces (Tempo), utiles dès que l'orchestrateur appelle plusieurs spécialistes. Le code est instrumenté avec OpenTelemetry dès P1 : ajouter Tempo ne demande aucune modification du code.



Précision du 2026-11-08 (PR n°9) : en P1, les métriques utilisent la bibliothèque officielle `prometheus-client` (format Prometheus natif, bien typée), exposées sur un port séparé (9464) jamais publié. OpenTelemetry est introduit en P3 pour les traces ; un pont vers OpenTelemetry pour les métriques reste possible sans changer les noms des métriques.

Décision du 2026-11-11 : Loki est reporté en P3, avec Tempo. En P1, un seul hôte, des journaux JSON bornés (`docker compose logs`) et aucun besoin de recherche croisée : Loki ajouterait un service à maintenir sans usage. Il devient utile quand les traces de l'orchestrateur (P3) devront être reliées aux journaux.
