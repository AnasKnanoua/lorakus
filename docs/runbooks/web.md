# Accès public : Caddy, limites, origine

Alertes : `LorakusWebDown` (critique), `LorakusRateLimited`, `LorakusOriginRefused` (avertissements).

Préparer la session : [README](README.md#session).

## Symptôme

- `LorakusWebDown` : Prometheus ne joint plus Caddy (service `web`) depuis 2 minutes. L'interface `https://app.lorakus.app` et l'API ne répondent plus depuis Internet ; l'API peut encore répondre sur `127.0.0.1:8001`.
- `LorakusRateLimited` : plus de 20 requêtes refusées en 15 minutes par les limites par utilisateur (erreur 429, `Retry-After`). Un appel IA refusé pour le rythme reçoit le message de secours « courte pause ».
- `LorakusOriginRefused` : des écritures (POST, PUT, PATCH, DELETE) ont été refusées en 403 `origin_refused` parce qu'elles venaient d'un autre site.
- Sans alerte : le navigateur signale un certificat invalide ou expiré.

## Vérifications

```bash
dc ps web api && dc logs --tail 50 web && curl -sS -o /dev/null -w '%{http_code}\n' -m 5 https://app.lorakus.app/
```

```bash
echo | openssl s_client -connect app.lorakus.app:443 -servername app.lorakus.app 2>/dev/null | openssl x509 -noout -issuer -enddate
```

```bash
dc logs --since 30m api | grep -E 'origin_refused|"status": 429' | tail -20
```

Depuis le Dell, hors du serveur : `curl -sI https://app.lorakus.app/ | head -5` (le serveur peut se joindre lui-même alors que Internet ne le joint pas).

## Causes probables

| Constat | Cause |
| --- | --- |
| `web` arrêté ou en boucle de redémarrage, juste après un déploiement | Version défectueuse : retour arrière |
| `web` absent de `dc ps` | Version déployée sans image web (antérieure à la PR 35), ou `dc` lancé sans `--profile web` |
| Journaux `web` : `obtaining certificate` puis `error` ou `rateLimited` | Let's Encrypt n'arrive pas à valider : DNS de `app.lorakus.app` modifié, port 80 ou 443 fermé (liste de sécurité Oracle, `firewalld`) ou limite de Let's Encrypt (5 échecs par heure) |
| Certificat valide, mais le Dell ne joint pas le site alors que le serveur oui | Réseau : liste de sécurité Oracle, `firewalld`, DNS |
| `LorakusRateLimited` sans action de ta part | Script ou session volée qui insiste : regarder le journal d'audit (`/api/v1/auth/audit`) et les adresses dans `dc logs web` |
| `LorakusRateLimited` pendant ton propre usage | Limite trop basse pour un usage réel : à relever par une PR (`LORAKUS_API_REQUESTS_PER_MINUTE`, `LORAKUS_AI_CALLS_PER_MINUTE`) |
| `LorakusOriginRefused` juste après un changement de nom de domaine | `LORAKUS_PUBLIC_HOST` ne correspond plus à l'adresse utilisée par le navigateur |
| `LorakusOriginRefused` sinon | Un autre site essaie d'agir avec ta session (CSRF). Le cookie `SameSite=Strict` et ce contrôle l'ont bloqué : rien à corriger, mais noter l'origine |

## Actions

1. **Caddy arrêté, sans déploiement récent** : `dc up -d --wait web`, puis revérifier. S'il retombe, lire `dc logs --tail 200 web` avant toute autre action.
2. **Après un déploiement** : retour à la version précédente depuis le Dell, `gh workflow run deploy.yml -f action=rollback`.
3. **Certificat refusé par Let's Encrypt** : corriger d'abord la cause (DNS, ports), puis `dc restart web`. Ne pas redémarrer en boucle : chaque échec compte dans la limite de Let's Encrypt (5 par heure et par nom). Les certificats et le compte ACME sont dans le volume `caddy-data` : **ne jamais le supprimer**.
4. **Session volée suspectée** : changer le mot de passe depuis l'application (toutes les sessions sont fermées) ; si le téléphone est perdu, `python -m lorakus.cli recover-second-factor` puis `enable-second-factor` sur le serveur (DEPLOYMENT.md §5).
5. **Abus de l'IA** : le plafond mensuel borne la dépense ; pour tout couper immédiatement, voir [ai.md](ai.md) (`LORAKUS_AI_KILL_SWITCH`).

## Retour arrière

- `dc up` et `dc restart` ne changent pas la version : rien à annuler.
- Un retour à une version antérieure à la PR 35 retire Caddy : le site redevient injoignable de l'extérieur (accès par tunnel SSH seulement), c'est attendu.

## Fin d'incident

L'alerte passe à « Résolu » dans Discord. Vérifier depuis le téléphone que l'application s'ouvre et que la connexion fonctionne.
