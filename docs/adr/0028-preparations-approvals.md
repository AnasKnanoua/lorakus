# ADR-0028 — Préparations en arrière-plan et file d'approbation

- **Statut** : Accepté
- **Date** : 2026-11-08
- **Revue prévue** : Phase 6

## Contexte

Les spécialistes doivent préparer des travaux sans demande explicite (shadow planning), et aucune action à conséquence externe ne doit s'exécuter sans accord.

## Décision

Service `agents` : table des **préparations** (spécialiste, type, titre, priorité, coût, statut `ready`/`consulted`/`expired`, date d'expiration) produites par des jobs `JobQueue` budgétés ; Today en affiche au plus trois ; une préparation ignorée trois fois de suite est suspendue. Table des **demandes d'approbation** (action déclarée dans le profil, aperçu exact, expiration de 24 h, décision journalisée dans l'audit). Les actions `sensitive` exigent une approbation dans la PWA avec ré-authentification récente ; Telegram ne peut approuver que des actions sans conséquence externe. Aucune action financière n'est déclarée en V1.

## Alternatives rejetées

Exécution directe des actions par les spécialistes ; préparations sans budget ni expiration.

## Conséquences

Préparations livrées en phase 5 (briefing du lendemain). File d'approbation livrée avec la **première action à conséquence externe**, pas avant ; d'ici là, les cartes de confirmation du Tool Runtime suffisent.

## Amendement du 2026-11-22 (P5, PR 53) : premières préparations

- Table `core_preparations` dans le Core (pas de service `agents` à part) : une préparation par module, type et jour (contrainte d'unicité : jamais deux briefings pour un jour), sections de texte écrites par le code du module, statut `ready` puis `consulted` (alors figée), expiration. Refaite tant qu'elle n'est pas lue ; Ma journée ne montre que la plus récente de chaque type, trois au plus.
- Première préparation : le briefing du Sergent (`focus.briefing`, toutes les 15 minutes, un seul job pour tous) : le lendemain dès que la plage de travail du jour est finie, sinon le jour en cours dès minuit. Par des règles : coût nul.
- Le budget par préparation et la suspension après trois préparations ignorées attendent la première préparation qui coûte (un appel à un modèle) ou qui interrompt : le briefing ne fait ni l'un ni l'autre.
