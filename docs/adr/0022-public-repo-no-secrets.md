# ADR-0022 — Dépôt public, aucun secret dans le dépôt

- **Statut** : Validé (décision D-B, 2026-11-08)
- **Date** : 2026-11-08
- **Revue prévue** : avant toute ouverture commerciale

## Contexte

Le dépôt sert aussi de vitrine (architecture, CI, sécurité). Un dépôt public rend toute erreur de secret immédiatement exploitable, mais donne accès gratuitement à CodeQL et à la protection des secrets au push.

## Décision

Dépôt GitHub public. Aucun secret dans le dépôt, même chiffré : secrets dans les environnements GitHub (`staging`, `production` avec approbation) et dans des fichiers `.env` 600 sur les serveurs. Aucune donnée personnelle dans les fixtures (données synthétiques uniquement). Gitleaks en pre-commit et en CI, protection des secrets au push activée, CodeQL activé. Licence : aucune dans un premier temps (tous droits réservés), à décider avant toute ouverture commerciale.

## Alternatives rejetées

Dépôt privé (moins de valeur portfolio, pas de CodeQL gratuit) ; secrets chiffrés avec SOPS dans un dépôt public (historique exposé si la clé fuit).

## Conséquences

SOPS sort de la stack. `infra/env.example` documente les variables sans valeurs. Les captures d'écran et exemples de la documentation ne contiennent aucune donnée réelle.
