# ADR-0036 — Environnements : production sur Oracle, staging et sentinelle sur Azure

- **Statut** : Validé (2026-11-09)
- **Date** : 2026-11-09
- **Revue prévue** : expiration du crédit Azure for Students, ou changement d'hébergeur

## Contexte

L'ADR 0009 prévoyait deux instances Oracle Always Free : `oracleworker` en production et une seconde instance A1 en staging. Or la seconde instance du compte, `oraclevps`, héberge Anime Notif et ne doit pas être modifiée, et le quota gratuit ne laisse aucune place pour une troisième. Par ailleurs, une surveillance installée sur le même hôte ou chez le même fournisseur que la production ne peut pas signaler la disparition de cet hôte.

Un crédit Azure for Students est disponible (100 $ sur 12 mois, sans carte bancaire, avec une petite VM ARM incluse), réservé à un usage non commercial.

## Décision

| Environnement | Hôte | Rôle |
| --- | --- | --- |
| Production | `oracleworker` (Oracle Always Free, ARM, 1 OCPU, 6 Go, Oracle Linux 9), nom d'hôte et alias SSH `lorakus-prod`, dédié à Lorakus | Pile complète et données réelles |
| Staging | VM ARM Azure for Students | Pré-production **légère** : pile réduite, données synthétiques, dimensionnée à la création de la VM |
| Sentinelle externe | Même VM Azure | Vérifie de l'extérieur que la production répond et alerte si elle disparaît |
| Développement | Dell (Ubuntu) | Inchangé |

- `oraclevps` reste hors du périmètre de Lorakus : aucun conteneur, aucun accès, aucune sonde.
- Pas de second compte Oracle pour contourner le quota.
- Azure n'est **pas critique** : si l'offre disparaît, la pré-production repasse dans la CI (pile Compose lancée dans GitHub Actions) et la sentinelle est déplacée vers un autre fournisseur. Aucune donnée réelle n'y est stockée. Alerte de budget à 5 $.
- Domaine `lorakus.app` (décision D-G) : `app.lorakus.app` (PWA et API à la même origine) et `staging.lorakus.app`, créés au début de la phase 3. Avant cela, aucune exposition publique : accès par tunnel SSH.

## Alternatives rejetées

- Staging sur `oraclevps` : risque pour Anime Notif, écarté par principe.
- Staging sur l'hôte de production : aucune isolation, mémoire partagée, tests offensifs impossibles.
- Second compte Oracle : contournement du quota, risque de fermeture des comptes.
- Aucun staging, CI seule : pas de répétition du déploiement sur un vrai hôte, et aucune surveillance externe.
- VPS payant dès maintenant : dépense sans utilisateur ; reste la sortie documentée (ADR 0009).

## Conséquences

- Amende l'ADR 0009 pour l'hébergement ; Docker Compose reste identique partout.
- Les images doivent rester multi-architectures (arm64 et amd64) pour ne dépendre d'aucun hôte.
- Les alertes portent un label d'environnement pour distinguer production, staging et développement dans Discord.
- La « sentinelle externe » (surveillance de disponibilité) n'est pas le module `sentinel` du Veilleur (ADR 0031) : ce dernier arrive en phase 7 et pourra s'appuyer sur elle.
- L'environnement Red Team, prévu sur l'hôte de staging, est à redimensionner en phase 17 selon la mémoire réellement disponible.
- Usage non commercial : avant toute vente, le staging et la sentinelle quittent Azure for Students.
