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
