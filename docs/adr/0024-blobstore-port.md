# ADR-0024 — Stockage de fichiers derrière le port BlobStore

- **Statut** : Accepté
- **Date** : 2026-11-08
- **Revue prévue** : au passage à un hébergeur payant ou à plusieurs utilisateurs

## Contexte

Plusieurs modules manipuleront des fichiers : pièces jointes du chat, médias de motivation, imports bancaires, exports. Écrire directement sur un volume Docker lierait chaque module au disque du serveur et rendrait coûteux un passage à un stockage objet.

## Décision

Service `storage` du Core exposant un port `BlobStore` (`put`, `get`, `delete`, `presign` optionnel). Implémentation initiale : disque local dans un volume dédié ; implémentation future : stockage compatible S3 (Cloudflare R2, Backblaze B2, MinIO). Les métadonnées (propriétaire, type, taille, empreinte SHA-256, classe de données) sont en base ; les clés sont préfixées par l'identifiant utilisateur ; les fichiers `sensitive` sont chiffrés avant écriture. Aucun module n'accède directement au système de fichiers.

## Alternatives rejetées

Écriture directe sur volume par chaque module ; stockage dans PostgreSQL en `bytea` (base qui grossit, sauvegardes lourdes).

## Conséquences

Passage au stockage objet = un adaptateur + une copie des fichiers, sans toucher aux modules. Les sauvegardes couvrent le volume de fichiers séparément de la base (`restic`, déjà prévu).
