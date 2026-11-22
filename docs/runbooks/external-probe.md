# Accès public vu d'Internet : sonde externe

Alerte : le message de healthchecks.io « lorakus-public is DOWN » sur Discord. Elle ne vient pas de la production : le workflow `External probe` (`.github/workflows/external-probe.yml`) sonde `https://app.lorakus.app` depuis un runner GitHub toutes les 15 minutes (ADR 0037, amendement de la P6).

Préparer la session : [README](README.md#session).

## Symptôme

Deux cas, à distinguer d'abord :

- **La sonde a vu une panne** : un passage a échoué trois fois de suite, à 20 secondes d'intervalle, et a envoyé un signal d'échec. Le message arrive au passage qui la constate, donc 15 minutes au plus après le début de la panne (plus le retard éventuel de GitHub). Le site est probablement inaccessible depuis Internet, ou le sera bientôt (certificat).
- **La sonde se tait** : aucun signal depuis plus d'une heure et quart (période 15 minutes, tolérance 1 heure). Le site va peut-être très bien ; c'est la sonde qui ne tourne plus.

Les alertes internes (`LorakusWebDown`, [web](web.md)) et la sentinelle ([production-down](production-down.md)) ne voient pas le chemin depuis Internet : DNS, liste de sécurité Oracle, `firewalld`, certificat. Celle-ci, si.

## Vérifications

Depuis le Dell, le dernier passage et sa raison :

```bash
gh run list --workflow external-probe.yml -L 5 && gh run view "$(gh run list --workflow external-probe.yml -L 1 --json databaseId --jq '.[0].databaseId')" --log | grep -E 'OK app|ÉCHEC app|::error|::warning'
```

Le même compte rendu est gardé par healthchecks.io avec chaque signal (check `lorakus-public`, onglet des événements).

Refaire la sonde depuis le Dell (hors du serveur), en une minute au plus :

```bash
python3 infra/probe/external_probe.py app.lorakus.app
```

Sonde muette : `gh workflow view external-probe.yml` (état « disabled » ?) et la page d'état de GitHub Actions.

## Causes probables

| Compte rendu | Cause |
| --- | --- |
| `HTTP (port 80) injoignable` ou `HTTPS injoignable`, avec un nom inconnu | DNS de `app.lorakus.app` modifié ou expiré chez Name.com |
| `HTTP (port 80) injoignable` seul | Port 80 fermé (liste de sécurité Oracle, `firewalld`) : le site marche encore, mais Let's Encrypt ne pourra plus renouveler le certificat |
| `injoignable : délai dépassé` ou connexion refusée, sur les deux ports | Serveur arrêté, Caddy arrêté, ou réseau coupé : voir aussi les alertes internes |
| `TLS : certificat refusé` | Certificat expiré, d'un autre nom, ou autorité inconnue (Caddy sert son certificat interne : `LORAKUS_TLS` n'est plus `acme`) |
| `certificat … : le renouvellement échoue` | Il reste moins d'un sixième de la durée de vie du certificat : Caddy aurait dû le renouveler depuis longtemps |
| `/api/health/ready : 503` | Caddy répond, l'API ou la base non : [api-down](api-down.md) |
| `/api/health/ready : 502` | Caddy répond, l'API est arrêtée : [api-down](api-down.md) |
| `200 mais pas la réponse de l'API` | `/api` ne mène plus à l'API (la page de l'application répond à sa place) : régression du `Caddyfile` |
| `en-tête HSTS absent` | La réponse ne vient pas de notre Caddy (DNS détourné, page d'attente de l'hébergeur ou du registraire) |
| Sonde muette, workflow « disabled » | GitHub coupe les workflows programmés d'un dépôt public sans activité depuis 60 jours |
| Sonde muette, runs rouges `Secret HEALTHCHECKS_PUBLIC_PING_URL absent` | Secret supprimé |
| Sonde muette, runs verts avec `healthchecks.io injoignable` | Panne de healthchecks.io, ou adresse de ping fausse |

## Actions

1. **Panne vue par la sonde** : partir de la cause.
   - Réseau, DNS, port, Caddy, certificat : [web](web.md) (le certificat se lit dans `dc logs web | grep -i certif`).
   - API ou base : [api-down](api-down.md).
   - Serveur muet : [production-down](production-down.md).
2. **Workflow désactivé** : `gh workflow enable external-probe.yml && gh workflow run external-probe.yml`.
3. **Secret absent ou adresse fausse** : refaire la section 4.7 de `DEPLOYMENT.md` (copier l'adresse de ping du check `lorakus-public`, puis `gh secret set`).
4. Vérifier le retour : `gh workflow run external-probe.yml`, puis healthchecks.io affiche « up » et Discord reçoit « lorakus-public is UP ».

## Retour arrière

La sonde ne change rien en production. Si la panne suit un déploiement : [deploy-failed](deploy-failed.md).
