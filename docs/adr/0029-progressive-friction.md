# ADR-0029 — Friction progressive et pactes volontaires

- **Statut** : Proposé (décision D-J) — amende l'ADR 0016
- **Date** : 2026-11-08
- **Revue prévue** : Phase 12

## Contexte

La vision demande trois niveaux d'intervention, le troisième activant une contrainte volontaire. L'ADR 0016 excluait tout blocage par Lorakus.

## Décision

Niveaux de l'`InterventionPolicy` : 1 discret (Today, notification silencieuse), 2 ferme et contextualisé (objectif, tâche précise, conséquence), 3 **pacte**. Un pacte est créé par l'utilisateur dans les réglages, hors du moment de tentation ; durée bornée ; sortie de secours toujours disponible avec une petite friction (attente de 60 s ou justification) ; chaque activation et chaque sortie journalisées ; seules des actions préautorisées. Actions possibles en V1 : blocage des domaines choisis par l'extension navigateur pendant une session de concentration (page d'interstitiel) ; activation de « Ne pas déranger » par Lorakus Sensors (permission accordée une fois). Le niveau 3 n'est atteint que si le niveau 2 a été ignoré et qu'un pacte couvre la situation.

## Alternatives rejetées

Blocage d'applications Android (exigerait le service d'accessibilité, rejeté par l'ADR 0016) ; contraintes imposées sans configuration préalable.

## Conséquences

L'ADR 0016 reste valable pour la collecte ; seule la phrase « aucun blocage » est remplacée par « aucun blocage hors pactes volontaires (ADR 0029) ». Livré en phase 12.
