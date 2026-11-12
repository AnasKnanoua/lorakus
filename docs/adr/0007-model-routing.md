# ADR-0007 — Routing par tâche, classe de données et licence

- **Statut** : Accepté (amendé 2026-11-08)
- **Date** : 2026-11-08
- **Revue prévue** : À chaque changement de tarif majeur

## Contexte

Le free tier Gemini réutilise les données ; Claude Pro n'inclut pas de crédits API ; certaines sources interdisent l'usage IA (Strava).

## Décision

routing.yaml : personnel → Claude Haiku 5.5 (payant) ; public → Gemini Flash-Lite free tier ; sensitive ou no_ai → modèle local ou refus. Embeddings des données personnelles calculés localement (fastembed). pricing.yaml daté, budget et mode dégradé.

## Alternatives rejetées

Un seul fournisseur ; embeddings via API pour les données personnelles.

## Conséquences

Coût de quelques dollars par mois ; aucune donnée personnelle sur un free tier.

## Amendement du 2026-11-12 (PR 32, décision D-D)

- **Budget (D-D, validé)** : 10 $ prépayés sur la console Anthropic, rechargement automatique désactivé (plafond global matériel) ; plafond applicatif de **3 $ par utilisateur et par mois civil UTC** (`LORAKUS_AI_MONTHLY_BUDGET_USD`), avertissement dans la réponse à 80 %, plus aucun appel à 100 %. Le plafond passe de 5 à 3 $ : au prix vérifié le 2026-11-12 (Haiku 5.5, 0,10 $ et 0,50 $ par million de tokens en entrée et en sortie), l'usage estimé est d'environ 1,50 $ par mois.
- **Fournisseur de la phase 3** : Claude Haiku 5.5 seul pour les conversations (classe `personal`). Gemini (offre gratuite : données réutilisées) et NVIDIA NIM (conditions d'essai : pas de production) sont écartés pour cette classe. L'adaptateur Gemini arrivera avec le premier usage de données `public`.
- **Repli** : en phase 3, le repli d'une panne ou d'un budget atteint est la réponse par gabarit (scénario 8), pas un second fournisseur payant.
- **Format** : `routing.toml` et `pricing.toml` (dans `backend/lorakus/ai/config/`) plutôt que YAML : lus par la bibliothèque standard, aucune dépendance de plus. Prix en `Decimal`, palier long de Haiku 5.5 (au-delà de 100 000 tokens de prompt) pris en compte ; la tâche `chat` refuse tout prompt estimé au-delà de 50 000 tokens.
- **Refus structurels** dans `ModelRouter`, avant tout appel et indépendamment de la configuration : `no_ai`, coupure générale (`LORAKUS_AI_KILL_SWITCH`), `sensitive` vers un fournisseur externe, prompt trop long, plafond atteint.
- **Disjoncteur** : 3 échecs consécutifs écartent un fournisseur 2 minutes, puis une seule requête d'essai.
- **Cache de réponses** : aucun pour l'instant (chaque message de conversation est unique) ; il arrivera avec les tâches `structured` qui en profitent.
- **Port** : `chat` (streaming) et `capabilities` en PR 32 ; `structured` et `embed` arrivent avec la mémoire (PR 36 et 37).
