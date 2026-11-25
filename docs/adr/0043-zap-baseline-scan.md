# ADR-0043 — Scan passif OWASP ZAP sur le staging de la CI

- **Statut** : Accepté (2026-11-25, PR 57)
- **Date** : 2026-11-25
- **Revue prévue** : phase 16 (agent Red Team, scans actifs) ; à chaque changement de version majeure de ZAP

## Contexte

La P6 demande un « ZAP baseline » : un scan passif d'OWASP ZAP (aucune attaque, seulement l'observation des réponses) qui vérifie en continu les en-têtes de sécurité, les cookies, les fuites d'information et la configuration HTTP de Lorakus. `SECURITY.md` §9 le prévoyait chaque nuit sur un staging qui n'existe pas la nuit : le staging de l'ADR 0037 ne vit que pendant un déploiement.

Contraintes : jamais de test offensif sur la production (instructions du projet), image épinglée publiée depuis au moins 14 jours, et une interface à page unique dont l'API n'est visible que par du JavaScript.

## Décision

1. **Cible** : la pile complète montée sur un runner par `staging-test.sh` (mêmes images que la production, Caddy et son `Caddyfile` compris), avec la version de `main` (sur une PR : sa base, car les images d'une PR ne sont pas publiées ; seul l'outillage du scan vient de la PR). Jamais la production. Le nom du staging passe de `localhost` à `lorakus.localhost` : Java (donc ZAP) n'envoie pas de SNI pour un nom sans point, et Caddy refuse alors la poignée de main TLS. curl résout seul les noms en `.localhost`, rien d'autre ne change.
2. **Fréquence** : workflow `zap.yml` chaque lundi, à la demande, et sur toute PR qui touche son outillage (`infra/zap/`, `infra/staging/`, le workflow). Il ne bloque pas les déploiements : un scan raté ne doit pas empêcher une correction urgente. Une alerte bloquante se traite comme une vulnérabilité trouvée (`SECURITY.md` §9) : correction, ou exception justifiée dans le plan.
3. **Plan versionné** (`infra/zap/baseline.yaml`, Automation Framework) plutôt que `zap-baseline.py` et ses options : exclusions, exceptions et requêtes lisibles et relues en PR, identiques en local et en CI.
   - Robot classique sur l'interface, puis job `requestor` sur **toutes les routes GET de l'API sans paramètre**, avec la session d'un compte de test créé pour le scan, et quelques-unes sans session. `/api/v1/auth/me` vérifie la session dans les deux sens (401 sans, 200 avec) : un cookie perdu ferait échouer le plan au lieu de rendre le scan silencieusement anonyme. Un test (`backend/tests/unit/test_zap_plan.py`) compare la liste au contrat OpenAPI : toute nouvelle route GET doit y entrer.
   - Exclus : `/api/docs` et `/api/openapi.json` (publiés hors production seulement), `/api/v1/auth/logout` (fermerait la session du scan).
   - Le robot « AJAX » (vrai navigateur) est écarté : il cliquerait au hasard, y compris sur des actions destructrices, sa couverture n'est pas reproductible, et il ne voyait pas plus d'API que la liste explicite.
4. **Barrière** (`infra/zap/zap_gate.py`) sur le rapport JSON : échec sur toute alerte de risque Low ou plus, sauf celles que le plan accepte (job `alertFilter`, une justification par exception). Les alertes Informational sont listées sans bloquer. Le job `exitStatus` de ZAP est écarté : avec ZAP 2.17, il laissait passer `script-src 'unsafe-inline'` (10055-5) dès que `style-src 'unsafe-inline'` (10055-6) était acceptée.
5. **Exception acceptée aujourd'hui** : 10055-6, `style-src 'unsafe-inline'` (Radix, ADR 0038). Les autres variantes de la règle CSP restent bloquantes.
6. **Image** : `zaproxy/zap-stable:20261103` (ZAP 2.17.0) épinglée par empreinte, hors Dependabot ; revue mensuelle des versions épinglées à la main (`SECURITY.md` §9).
7. **Session du scan** : jeton d'un compte jetable du staging, masqué dans les journaux. ZAP 2.17 ne remplace pas les variables dans les en-têtes : le workflow rend le plan juste avant le scan et efface la copie rendue après.

## Conséquences

- Un défaut d'en-tête, de cookie ou de CSP introduit par une PR est vu dans la semaine, avec un tableau dans le résumé du run et les rapports JSON et HTML en artefact (14 jours).
- Mesuré en local contre une pile équivalente (même `Caddyfile`, même Caddy, API et interface de `main`) : aucune alerte bloquante ; Informational : cache de l'enveloppe (`no-cache` voulu), commentaire suspect (faux positif dans le code minifié), application moderne.
- Limites : passif seulement (aucune injection, aucun contrôle d'accès entre comptes : phase 16) ; routes à paramètre et méthodes d'écriture non couvertes ; staging avec données vides.

## Alternatives écartées

- Scan de la production : interdit par les règles du projet, même passif (trafic et journaux réels).
- Scan dans `deploy.yml` après le staging : chaque déploiement plus long, et une mise à jour de ZAP pourrait bloquer une correction urgente.
- `zap-baseline.py` : options en ligne de commande, configuration persistante de ZAP entre deux exécutions locales (vu pendant la mise au point : une ancienne règle de remplacement réécrivait les cookies).
