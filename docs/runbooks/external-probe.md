# Accès public vu d'Internet : UptimeRobot et sonde externe

Deux surveillances regardent `https://app.lorakus.app` depuis l'extérieur du serveur (ADR 0037, amendement de la P6, sa correction et la décision D-L du 2026-11-25). Aucune ne vient de la production : elles voient ce que les alertes internes ne voient pas (DNS, liste de sécurité Oracle, `firewalld`, certificat, routage de Caddy).

| Surveillance | Ce qu'elle vérifie | Fréquence | Alerte |
| --- | --- | --- | --- |
| **UptimeRobot** (disponibilité) | `https://app.lorakus.app/api/health/ready` répond normalement (sonde de type HTTP, sur le code de la réponse) | Toutes les 5 minutes | UptimeRobot, sur Discord et par e-mail |
| **Sonde externe** (configuration publique) | Redirection HTTP vers HTTPS (port 80), certificat (autorité, nom, au moins un sixième de sa durée de vie), `/api/health/ready` (200 et `{"status": "ok"}`), HSTS | Quatre passages demandés par jour à GitHub, de 4 à 12 heures d'écart mesurées | healthchecks.io « lorakus-public is DOWN » sur Discord |

UptimeRobot dit vite que le site ne répond plus (5 min 10 s après l'arrêt de Caddy, mesuré une fois à l'[exercice du 2026-11-27](../incidents/2026-11-27-exercice-web-arrete.md)) ; la sonde dit pourquoi une configuration casse et reste cassée (certificat qui ne se renouvelle plus, port 80 fermé, `/api` mal routé, Caddy remplacé). UptimeRobot ne lit pas le corps de la réponse : une page HTML servie avec un code 200 à la place de l'API passe pour lui, pas pour la sonde.

Préparer la session : [README](README.md#session).

## Alerte UptimeRobot

### Symptôme

UptimeRobot n'obtient plus de réponse normale de `/api/health/ready` : délai dépassé, connexion refusée, erreur TLS, 502 (Caddy sans API) ou 503 (API sans base). Le retour se lit sur son tableau de bord, et dans un message de retour si l'alerte le prévoit.

### Vérifications

D'abord les alertes internes reçues en même temps, qui disent où chercher :

| Alertes internes | Conclusion |
| --- | --- |
| `LorakusWebDown` | Caddy arrêté : [web](web.md) |
| `LorakusApiDown` | API arrêtée : [api-down](api-down.md) |
| healthchecks.io « lorakus-prod is DOWN » | Serveur disparu : [production-down](production-down.md) |
| Aucune | La production tourne, Internet ne la joint pas : suite ci-dessous |

Puis, depuis le Dell (hors du serveur, qui peut se joindre lui-même quand Internet ne le joint pas) :

```bash
curl -sS -o /dev/null -m 10 -w 'code=%{http_code} temps=%{time_total}s\n' https://app.lorakus.app/api/health/ready ; python3 infra/probe/external_probe.py app.lorakus.app
```

La sonde donne la raison en une ligne (table « Causes probables » de la section suivante).

### Actions

Partir de la cause, comme pour la sonde : [web](web.md) (Caddy, DNS, ports, certificat), [api-down](api-down.md) (API ou base), [production-down](production-down.md) (serveur muet). Si tout répond depuis le Dell et depuis le téléphone (données mobiles), la panne est chez UptimeRobot ou sur le chemin réseau de ses sondes : sa page d'état le dira ; rien à faire chez nous.

## Alerte de la sonde externe

### Symptôme

Deux cas, à distinguer d'abord :

- **La sonde a vu une panne** : un passage a échoué trois fois de suite, à 20 secondes d'intervalle, et a envoyé un signal d'échec. Le message arrive au passage qui la constate, donc parfois plusieurs heures après le début du problème : pour une panne franche, UptimeRobot a normalement prévenu avant. Le site est probablement inaccessible depuis Internet, ou le sera bientôt (certificat).
- **La sonde se tait** : aucun signal depuis plus de deux jours (période 1 jour, tolérance 1 jour, pour absorber les irrégularités de GitHub). Le site va peut-être très bien ; c'est la sonde qui ne tourne plus.

### Vérifications

Depuis le Dell, le dernier passage et sa raison :

```bash
gh run list --workflow external-probe.yml -L 5 && gh run view "$(gh run list --workflow external-probe.yml -L 1 --json databaseId --jq '.[0].databaseId')" --log | grep -E 'OK app|ÉCHEC app|::error|::warning'
```

Le même compte rendu est gardé par healthchecks.io avec chaque signal (check `lorakus-public`, onglet des événements).

Refaire la sonde depuis le Dell, en une minute au plus :

```bash
python3 infra/probe/external_probe.py app.lorakus.app
```

Sonde muette : `gh workflow view external-probe.yml` (état « disabled » ?) et la page d'état de GitHub Actions.

### Causes probables

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

### Actions

1. **Panne vue par la sonde** : partir de la cause.
   - Réseau, DNS, port, Caddy, certificat : [web](web.md) (le certificat se lit dans `dc logs web | grep -i certif`).
   - API ou base : [api-down](api-down.md).
   - Serveur muet : [production-down](production-down.md).
2. **Workflow désactivé** : `gh workflow enable external-probe.yml && gh workflow run external-probe.yml`.
3. **Secret absent ou adresse fausse** : refaire la section 4.7 de `DEPLOYMENT.md` (copier l'adresse de ping du check `lorakus-public`, puis `gh secret set`).
4. Vérifier le retour : `gh workflow run external-probe.yml`, puis healthchecks.io affiche « up » et Discord reçoit « lorakus-public is UP ».

## Limites connues

- Personne ne surveille UptimeRobot lui-même : s'il cesse de sonder (compte suspendu, sonde mise en pause), rien ne le signale. Le tableau de bord d'UptimeRobot montre la dernière vérification ; y jeter un œil à chaque revue mensuelle des outils (`SECURITY.md` §9).
- UptimeRobot ne voit que le code HTTP et la réponse `{"status": "ok"}` de `/api/health/ready` : aucune donnée personnelle, aucun identifiant, aucune version.

## Retour arrière

Ni UptimeRobot ni la sonde ne changent quoi que ce soit en production. Si la panne suit un déploiement : [deploy-failed](deploy-failed.md).
