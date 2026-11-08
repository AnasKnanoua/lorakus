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
