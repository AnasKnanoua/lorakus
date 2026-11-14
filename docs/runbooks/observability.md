# Traces et journaux (Tempo, Loki)

Alertes : `LorakusTempoDown`, `LorakusLokiDown` (avertissements).

Préparer la session : [README](README.md#session).

L'application ne dépend pas de Tempo ni de Loki : elle leur envoie traces et journaux en arrière-plan (OTLP/HTTP), et ses journaux restent sur la sortie standard (`dc logs api`). Une panne fait seulement perdre l'historique consultable dans Grafana.

## Retrouver une réponse du chat

1. Dans Lorakus, sous la réponse : **?** → « Détails » → identifiant de trace (32 caractères). Le copier.
2. Ouvrir Grafana par le tunnel SSH (`DEPLOYMENT.md`) → Explore → source **Tempo** → coller l'identifiant.
3. La trace montre la requête HTTP, `assistant.prepare` (souvenirs, outils, spécialistes), chaque `ai.call` (modèle, tokens, coût), `tool.call`, les spécialistes et les requêtes SQL, avec leurs durées.
4. Sur un span : **Logs for this span** ouvre ses journaux dans Loki. Dans Loki, le lien **Voir la trace** d'une ligne fait le chemin inverse.

Requête Loki utile : `{service_name="lorakus-api"} | json | level="error"`.

## Tempo ou Loki injoignable

### Symptôme

Prometheus ne collecte plus le service depuis 10 minutes.

### Vérifications

```bash
dc ps tempo loki && dc logs --tail 50 tempo && dc logs --tail 50 loki && docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}'
```

### Causes probables

- Mémoire : le conteneur a atteint sa limite (256 Mo chacun) et a été arrêté (`OOMKilled` dans `docker inspect`).
- Disque plein (`disk-full`) : Tempo et Loki écrivent dans leurs volumes `tempo-data` et `loki-data`.
- Configuration refusée après une mise à jour d'image : la première ligne d'erreur de `dc logs` le dit (Tempo 3 a déjà changé de format une fois : l'ancien bloc `compactor` est refusé).

### Actions

1. `dc restart tempo` ou `dc restart loki`.
2. Limite mémoire atteinte de façon répétée : noter la mesure, PR qui ajuste la limite dans `compose.observability.yml`.
3. Données corrompues (rare) : les volumes ne contiennent que de l'historique jetable. `dc stop loki && docker volume rm lorakus_loki-data && dc up -d loki` (même chose pour Tempo). Aucune sauvegarde à restaurer.

## Rétention et confidentialité

Traces : 3 jours. Journaux : 7 jours. Ni l'un ni l'autre n'est sauvegardé. Aucun contenu personnel n'y est envoyé : pas de message, de prompt, de texte de souvenir, de chaîne de requête, d'en-tête ni de valeur SQL (test « canari », `backend/tests/integration/test_telemetry_canary.py`).
