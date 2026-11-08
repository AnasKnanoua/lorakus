# Déploiement

## 1. Environnements

| Environnement | Hôte | Contenu | Données |
| --- | --- | --- | --- |
| Développement | Dell (Ubuntu) | `compose.yml` + `compose.dev.yml` : Postgres, API (rechargement auto), worker, frontend (Vite), Grafana optionnel ; `FakeProvider` par défaut | Fixtures synthétiques |
| Staging | 2e instance Oracle A1 (1 OCPU / 6 Go), Always Free (ADR 0009) ; préparée en fin de P1 | Même composition que la prod, Basic Auth Caddy devant, budget IA plafonné à 2 $/mois | Copie anonymisée de la prod |
| Production | `OracleWorker` (1 OCPU / 6 Go, Oracle Linux 9), partagé avec Anime Notif | Caddy, API, worker, Postgres, stack d'observabilité ; Uptime Kuma existant | Réelles |
| Red Team | Conteneurs éphémères sur l'hôte de staging, réseau `redteam` | ZAP, Promptfoo | Aucune donnée de production |

Budget mémoire prod [Estimation] : Anime Notif ~0,6 Go, LORAKUS (API, worker, Postgres) ~1,5 Go, observabilité ~1,2 Go, marge ~2,5 Go.

## 2. Prérequis d'un hôte

- Docker Engine + plugin Compose, firewalld (22, 80, 443), fail2ban, mises à jour de sécurité automatiques (`dnf-automatic`, sécurité uniquement).
- Utilisateur `deploy` (membre du groupe `docker`, sans sudo), clé SSH dédiée à GitHub Actions.
- Répertoire `/opt/lorakus` : `compose.yml`, `.env` (600, `deploy`), volumes nommés.
- Enregistrements DNS chez Cloudflare (proxy désactivé : TLS terminé par Caddy).

## 3. Premier déploiement (phase 1)

1. Créer l'utilisateur `deploy` et ajouter la clé publique de déploiement.
2. Copier `infra/compose.yml` et créer `/opt/lorakus/.env` depuis `infra/env.example`.
3. `docker compose pull && docker compose run --rm migrate && docker compose up -d`.
4. Vérifier : `https://<domaine>/api/health`, tableau Grafana « Plateforme » (via tunnel SSH), réception d'une alerte de test sur Telegram.
5. Lancer manuellement le job de sauvegarde puis le test de restauration.

## 4. Mise à jour

| Environnement | Déclencheur | Séquence |
| --- | --- | --- |
| Staging | Fusion sur `main` après CI verte | build multi-arch → Trivy → GHCR → SSH → `pull` → `migrate` → `up -d` → smoke tests → ZAP baseline |
| Production | Tag `vX.Y.Z` + approbation de l'environnement `production` | sauvegarde → même séquence → health check → annonce Telegram ; rollback automatique si le health check échoue 3 fois |

Jamais d'image `latest` en production : tags `sha-<court>` et `vX.Y.Z`.

## 5. Migrations en production

- Le conteneur `migrate` exécute `alembic upgrade heads` avant le redémarrage.
- Expand/contract : la version N fonctionne avec le schéma N+1 ; la contraction arrive au tag suivant, après une semaine sans incident.
- Une migration marquée irréversible exige une sauvegarde vérifiée de moins d'une heure (`make migrate-prod` refuse sinon).

## 6. Rollback

```bash
make rollback TAG=v0.5.2      # redéploie l'image précédente ; le schéma reste compatible
```

Si une migration doit être annulée : `alembic downgrade <révision>` puis redéploiement du tag précédent, documenté dans le runbook `restore.md`.

## 7. Sauvegardes et restauration

| Élément | Méthode | Fréquence | Destination | Rétention |
| --- | --- | --- | --- | --- |
| PostgreSQL | `pg_dump -Fc` chiffré avec `age` | Quotidienne 03:00 + avant chaque migration | Backblaze B2 ou Cloudflare R2 (hors Oracle) | 30 quotidiennes + 12 mensuelles |
| Fichiers utilisateur | `restic` (chiffré, dédupliqué) | Quotidienne | Même bucket | Idem |
| Configuration | Dépôt Git + secrets dans les environnements GitHub | À chaque changement | GitHub | — |

Test de restauration automatique mensuel : restauration dans un conteneur jetable, `alembic check`, comptage par table, résultat publié en métrique ; alerte si échec ou si aucune sauvegarde réussie depuis 26 h.

## 8. Accès d'administration

Grafana, Prometheus et `/admin` ne sont pas exposés publiquement : accès par tunnel SSH (`ssh -L 3000:localhost:3000 OracleWorker`) ou WireGuard.

## 9. Changer d'hébergeur

Déclencheurs : RAM insuffisante, récupération de l'instance par Oracle, ouverture à plusieurs utilisateurs. Cible documentée : Hetzner ARM (≈ 5–9 €/mois).

1. Provisionner l'hôte (section 2).
2. Copier `compose.yml`, recréer `.env` depuis les environnements GitHub.
3. Restaurer la dernière sauvegarde.
4. Basculer le DNS, vérifier, supprimer l'ancien hôte après 7 jours.

Durée cible : une soirée.

## 10. Checklist après déploiement

- [ ] `/api/health` vert, version attendue affichée dans `/admin`
- [ ] Aucune erreur 5xx dans les 10 minutes
- [ ] Jobs périodiques exécutés à l'heure
- [ ] Une notification de test reçue
- [ ] `PROJECT_STATE.md` et `CHANGELOG.md` à jour
