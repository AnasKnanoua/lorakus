# Scan ZAP en échec

Alerte : le run `ZAP baseline` (`.github/workflows/zap.yml`) est rouge, chaque lundi ou sur une PR qui touche `infra/zap/` ou `infra/staging/`. GitHub l'envoie par e-mail. Rien ne se passe en production : le scan vise le staging monté sur le runner (ADR 0043).

## Symptôme

L'étape en échec dit où chercher :

| Étape | Signification |
| --- | --- |
| Trouver les images de cette version | Images absentes pour ce commit de `main` (workflow `Publish` en échec) ; sur une PR, c'est la base de la PR qui est montée |
| Monter le staging | Même échec qu'un staging de déploiement : [deploy-failed](deploy-failed.md) |
| Créer le compte de test et ouvrir une session | `create-owner` refusé, connexion qui ne répond pas 204, ou cookie absent |
| Scanner avec ZAP | Le plan a échoué : réponse inattendue d'une requête (`Difference in response code values`), exclusion ou syntaxe du plan |
| Décider | Au moins une alerte bloquante : le tableau du résumé du run la nomme |

## Vérifications

Depuis le Dell :

```bash
gh run list --workflow zap.yml -L 3 && gh run view "$(gh run list --workflow zap.yml -L 1 --json databaseId --jq '.[0].databaseId')" --log-failed | tail -40
```

Le résumé du run contient le tableau des alertes (statut, règle, risque, confiance). Le rapport HTML complet (requêtes, réponses, preuves) est dans l'artefact `zap-baseline` :

```bash
gh run download "$(gh run list --workflow zap.yml -L 1 --json databaseId --jq '.[0].databaseId')" -n zap-baseline -D /tmp/zap && xdg-open /tmp/zap/zap-baseline.html
```

## Causes probables

| Message | Cause |
| --- | --- |
| `BLOQUANTE` avec une règle d'en-tête (10020, 10021, 10035, 10038, 10055-x, 10063…) | En-tête de sécurité retiré ou affaibli dans `infra/web/Caddyfile` |
| `BLOQUANTE` avec une règle de cookie (10010, 10011, 10054…) | Attribut retiré du cookie de session (`lorakus/api/auth.py`) |
| `BLOQUANTE` sur une réponse de l'API | En-tête manquant ou erroné sur une nouvelle route (type de contenu, cache, divulgation d'information) |
| `Difference in response code values` sur `/api/v1/auth/me` (attendu 200) | Session perdue : nom du cookie changé, connexion modifiée, ou route supprimée |
| `Difference …` sur une route sans session (attendu 401) | Une route de l'API répond sans authentification : **vulnérabilité**, à traiter avant tout |
| `Difference …` sur une autre route | Route renommée ou supprimée : le test `test_zap_plan.py` aurait dû échouer avant |
| `test_zap_plan.py` rouge dans la CI | Nouvelle route GET de l'API absente du plan : l'ajouter à `infra/zap/baseline.yaml` |

## Actions

1. **Alerte bloquante** : la corriger dans le code (cas normal). Si elle est sans objet pour Lorakus, l'accepter dans le job `alertFilter` du plan, avec sa référence la plus étroite (ex. `10055-6`, pas `10055`) et une ligne de justification ; un ADR si c'est un choix de sécurité.
2. **Route sans authentification** : ouvrir un rapport `security-finding` (`SECURITY.md` §9), corriger, puis vérifier que le scan repasse.
3. **Nouvelle route GET** : l'ajouter au job `requestor`, avec l'en-tête de session.
4. Rejouer : `gh workflow run zap.yml`, ou pousser la correction sur la PR.

Reproduire en local (Docker, pile du staging) : monter le staging comme le workflow, puis lancer la même image avec le même plan (voir les étapes de `zap.yml`). Ne jamais viser `app.lorakus.app`.

## Retour arrière

Le scan ne change rien. Si l'alerte vient d'une version déjà en production, la corriger par une PR ; un retour arrière ([deploy-failed](deploy-failed.md)) seulement pour une vulnérabilité `high`.
