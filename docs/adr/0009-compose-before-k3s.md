# ADR-0009 — Docker Compose avant k3s

- **Statut** : Validé (décision D-A, 2026-11-08) ; hébergement amendé par l'ADR 0036 (2026-11-09)
- **Date** : 2026-11-08
- **Revue prévue** : Changement d'hébergeur

## Contexte

Quota Oracle Always Free réduit à 2 OCPU / 12 Go ; le control plane k3s consommerait une part importante.

## Décision

Docker Compose identique en dev, staging et prod. Kubernetes se pratique sur le poste de dev (k3d) hors de l'infrastructure LORAKUS.

## Alternatives rejetées

k3s à deux nœuds Oracle.

## Conséquences

Hébergement validé : Oracle Always Free, `OracleWorker` (1 OCPU / 6 Go) en production, une seconde instance A1 (1 OCPU / 6 Go) en staging, soit l'intégralité du quota gratuit. Sortie documentée vers Hetzner. Portabilité par images multi-architectures ; k3s réévalué avec un hébergeur payant.

**Amendement du 2026-11-09 (ADR 0036)** : la seconde instance A1 héberge Anime Notif et n'est pas utilisée ; le staging et une sentinelle externe sont placés sur Azure for Students. Le reste de cette décision est inchangé.
