# ADR-0035 — Canaux de notification : exploitation sur Discord, produit sur Telegram

- **Statut** : Accepté
- **Date** : 2026-11-09
- **Revue prévue** : ouverture à d'autres utilisateurs

## Contexte

Lorakus envoie deux natures de messages : des alertes d'exploitation (API injoignable, erreurs, sauvegardes), destinées à l'administrateur, et des notifications produit (rappels, interventions, briefing), destinées à chaque utilisateur. Les mélanger noie l'information et exposerait, à terme, des alertes d'infrastructure aux clients.

## Décision

- **Exploitation** : Alertmanager vers un webhook Discord (salon `#lorakus-infra`), messages encadrés en couleur (rouge déclenchée, vert résolue), modèle versionné dans `infra/observability/alertmanager/templates/`.
- **Produit** : bot Telegram, utilisé par l'API à partir de la phase 5 via l'`InterventionPolicy` (ADR 0014, 0019).
- Secrets distincts : l'URL du webhook n'est connue que d'Alertmanager, le jeton du bot que de l'API.

## Alternatives rejetées

Un seul canal Telegram pour tout (mélange des natures, pas de couleurs) ; deux conversations Telegram du même bot (un seul secret pour deux usages).

## Conséquences

Amende l'ADR 0020 sur un point : les alertes d'exploitation ne passent plus par Telegram.
