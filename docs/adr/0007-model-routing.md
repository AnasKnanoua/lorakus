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

## Amendement du 2026-11-13 (PR 37, embeddings locaux)

- **Modèle** : `multilingual-e5-small` quantifié en int8 (export ONNX de Xenova, `tokenizer.json` du dépôt officiel `intfloat`), 118 Mo, 384 dimensions, 512 tokens, licence MIT. Entraîné pour la recherche « question → passage » (préfixes `query:` et `passage:`), couvre le français.
- **Écartés** : `paraphrase-multilingual-MiniLM-L12-v2` (entraîné pour la similarité de phrases, pas pour la recherche ; 128 tokens) ; `embeddinggemma-300m` (environ 1,2 Go, licence Gemma à examiner avant toute vente) ; `Qwen3-Embedding-0.6B` (1,1 à 2,4 Go, hors de portée d'un serveur de 5,6 Go partagé avec la base).
- **Exécution** : ONNX Runtime et `tokenizers` directement, **sans `fastembed`**. `fastembed` 0.9.1 ne propose pas ce modèle, télécharge les fichiers au premier usage (conteneur en lecture seule, sans sortie voulue vers Internet) et ajouterait `pillow`, `loguru`, `requests` et `tqdm` pour environ 80 lignes de code (tokenisation, moyenne des jetons, normalisation).
- **Fichiers** : intégrés à l'image pendant sa construction (`backend/Dockerfile`, étape `model`), vérifiés par SHA-256 ; rien n'est téléchargé à l'exécution. L'identifiant du modèle (`model_id`) est dérivé de l'empreinte du fichier : un modèle changé rend les vecteurs périmés, qui sont recalculés.
- **Port séparé** : `Embedder` (`embed_query`, `embed_passages`) plutôt qu'une méthode `embed` de `AIProvider`. Un calcul local n'a ni budget, ni rythme, ni fournisseur externe : le faire passer par le `ModelRouter` l'aurait soumis aux limites de 6 appels IA par minute (ADR 0038).
- **Où** : dans le processus de l'API seulement (une copie en mémoire, une inférence à la fois dans un thread, 2 threads ONNX) ; ni le worker ni les migrations ne chargent ONNX Runtime. Limite mémoire de l'API portée de 384 à 768 Mo et alerte de 300 à 600 Mo, à resserrer après mesure en production.
- **Repli** : `FakeEmbedder` (sac de mots) en développement et en test seulement ; sans modèle, l'API refuse de démarrer en staging et en production.
