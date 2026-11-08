# ADR-0001 — Monolithe modulaire

- **Statut** : Validé
- **Date** : 2026-11-08
- **Revue prévue** : Si > 3 contributeurs ou extraction d'un module nécessaire

## Contexte

Un seul développeur, un VPS de 6 Go, des domaines nombreux mais faiblement chargés. Les microservices ajouteraient réseau, déploiements et observabilité distribués sans bénéfice.

## Décision

Un seul déploiement (image unique, rôles api/worker/migrate), modules en packages Python avec frontières vérifiées par import-linter, communication par événements, ports du Core et outils.

## Alternatives rejetées

Microservices (complexité opérationnelle) ; monolithe non structuré (couplage, réécriture inévitable).

## Conséquences

Un module peut être extrait plus tard car il ne partage ni tables ni imports. Discipline de frontières vérifiée en CI.
