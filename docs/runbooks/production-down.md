# Production disparue

Alertes : le message de healthchecks.io « lorakus-prod is DOWN » sur Discord ; `LorakusHeartbeatFailing` (avertissement, envoyé par la production elle-même).

## Symptôme

- **Message healthchecks.io** : la production n'a envoyé aucun signal de vie depuis plus de 7 minutes. Le serveur, Docker, Prometheus ou Alertmanager est arrêté, ou le serveur n'atteint plus Internet. Les alertes internes ne peuvent alors plus partir : c'est la seule alerte que tu recevras.
- **`LorakusHeartbeatFailing`** : la production tourne mais n'arrive plus à joindre healthchecks.io. Si rien n'est fait, le message ci-dessus suivra.

## Vérifications

Depuis le Dell :

```bash
ssh -o ConnectTimeout=10 lorakus-prod 'uptime && df -h / && free -m && systemctl is-active docker' ; echo "ssh=$?"
```

| Résultat | Conclusion |
| --- | --- |
| `ssh=255`, délai dépassé | Serveur arrêté ou réseau Oracle coupé |
| Connexion OK, `docker` inactif | Docker arrêté |
| Tout répond | Un service de la chaîne d'alerte est arrêté, ou la sortie vers Internet est bloquée |

Puis sur le serveur ([session](README.md#session)) :

```bash
dc ps prometheus alertmanager && dc logs --tail 30 alertmanager && curl -sS -o /dev/null -w "healthchecks=%{http_code}\n" https://hc-ping.com
```

## Causes probables

- Instance arrêtée ou redémarrée par Oracle (maintenance, récupération de ressources Always Free inactives).
- Disque plein : Docker ou PostgreSQL arrêtés ([disk-full](disk-full.md)).
- Prometheus ou Alertmanager arrêtés ou tués par leur limite de mémoire.
- `HEALTHCHECKS_PING_URL` absente ou fausse dans `/opt/lorakus/.env` (cas de `LorakusHeartbeatFailing` juste après une installation).
- Panne de healthchecks.io : sa page d'état le dira ; la production n'y est pour rien.

## Actions

1. **Serveur injoignable** : console Oracle → Instances → `oracleworker`. S'il est arrêté, « Démarrer ». Sinon, « Console Connection » pour voir l'écran de démarrage. Après redémarrage : `ssh lorakus-prod`, puis [session](README.md#session) et `dc ps`. Docker relance seul les services (`restart: unless-stopped`).
2. **Docker arrêté** : `sudo systemctl start docker && sleep 20 && dc ps`.
3. **Prometheus ou Alertmanager arrêté** : `dc up -d prometheus alertmanager`.
4. **Adresse de ping fausse** : la remplacer, puis recréer Alertmanager :

   ```bash
   sed -i '/^HEALTHCHECKS_PING_URL=/d' /opt/lorakus/.env && /opt/lorakus/app/infra/deploy/init-env.sh && dc up -d --force-recreate alertmanager
   ```

5. Vérifier le retour : healthchecks.io doit afficher « up » en moins de 3 minutes, et Discord recevoir « lorakus-prod is UP ».

## Retour arrière

Aucune de ces actions ne change la version en service. Si la panne suit un déploiement : [deploy-failed](deploy-failed.md).

## Tester la sentinelle (après chaque changement de la chaîne d'alerte)

```bash
ssh lorakus-prod 'sudo -iu deploy /opt/lorakus/app/infra/deploy/deploy.sh compose stop alertmanager' && echo "Arrete a $(date -u +%H:%M) UTC : attendre le message DOWN (8 min mesurees le 2026-11-11, 10 au plus)"
```

Quand le message est arrivé :

```bash
ssh lorakus-prod 'sudo -iu deploy /opt/lorakus/app/infra/deploy/deploy.sh compose up -d alertmanager'
```
