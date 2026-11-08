# ADR-0027 — Confidentialité des rapports transmis au LLM

- **Statut** : Proposé (décision D-I)
- **Date** : 2026-11-08
- **Revue prévue** : Après la phase 14 (Trésorier)

## Contexte

Le Majordome synthétise avec un LLM externe ; or les ADR 0007 et 0015 interdisent d'envoyer des données `sensitive` (finance, santé) ou `no_ai` (Strava) à un fournisseur externe.

## Décision

Filtre de confidentialité du service `agents`, appliqué à chaque rapport avant le LLM :

- `public` et `personal` : transmis tels quels (fournisseur payant sans entraînement pour `personal`) ;
- `sensitive` : remplacé par un **marqueur** et un qualificatif (`⟦fin.livraison_mois⟧ (en forte hausse)`), jamais la valeur ;
- `no_ai` : retiré.

Après la rédaction, le serveur vérifie que la réponse ne contient que des marqueurs connus et les remplace localement par les valeurs exactes ; tout marqueur supprimé, modifié ou inventé entraîne le rejet de la réponse et l'utilisation d'un gabarit déterministe. Option future, désactivée par défaut et journalisée : autoriser par spécialiste l'envoi d'agrégats (totaux par catégorie, sans marchand ni date).

## Alternatives rejetées

Envoi d'agrégats par défaut (contraire à la spec) ; synthèse par modèle local uniquement (le VPS ne peut pas l'exécuter).

## Conséquences

Test de CI qui intercepte toute requête sortante vers un fournisseur et échoue si une valeur `sensitive` connue y figure. Les classes transmises sont tracées dans `core_agent_runs`.
