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

## Amendement du 2026-11-14 (PR 40) : traces et journaux sans collecteur

- **Pas de Grafana Alloy.** L'API et le worker envoient eux-mêmes leurs traces à Tempo et une copie de leurs journaux à Loki, en OTLP/HTTP sur le réseau interne (Loki 3 reçoit l'OTLP nativement). Alloy aurait dû lire le socket Docker pour récupérer les journaux, ce qui lui aurait donné un accès équivalent à root sur l'hôte. Contrepartie : les journaux de Caddy et de PostgreSQL restent dans `docker compose logs`, hors de Loki.
- **OTLP par HTTP, pas gRPC** : exportateur en Python pur, sans la bibliothèque native `grpcio`.
- **Versions** : Tempo 3.1.1, Loki 3.7.9, images épinglées par empreinte, statistiques d'usage vers Grafana Labs coupées, aucun port publié. Rétentions : 3 jours (traces, toutes conservées : volume d'un usage personnel), 7 jours (journaux). Non sauvegardés.
- **Instrumentation** : FastAPI par le paquet officiel (sans les étapes ASGI « receive » et « send », sans les sondes de santé) ; **requêtes SQL par un écouteur maison** sur les événements de SQLAlchemy, car `opentelemetry-instrumentation-sqlalchemy` ne prend pas en charge SQLAlchemy 2.1 et ne faisait rien, sans erreur ; **appels au modèle par des spans maison** (`ai.call`), car le SDK d'Anthropic utilise `httpx2`, que l'instrumentation httpx officielle ne connaît pas. Gestionnaire de journaux du paquet `opentelemetry-instrumentation-logging` (celui du SDK est déprécié).
- **Confidentialité** : attributs nettoyés avant l'export (chaînes de requête, en-têtes, valeurs SQL), journaux de `httpx2` et `httpcore2` limités aux avertissements (ils recopiaient l'adresse complète des requêtes), test « canari » sur tout le parcours.
- **Jamais bloquant** : export en arrière-plan avec un délai de 2 s ; si Tempo ou Loki tombe, l'application ne le voit pas ; alertes `LorakusTempoDown` et `LorakusLokiDown` (avertissements).
