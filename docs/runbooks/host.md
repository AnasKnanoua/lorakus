# Mémoire basse, métriques du serveur absentes

Alertes : `LorakusHostMemoryLow`, `LorakusNodeExporterDown` (avertissements).

Préparer la session : [README](README.md#session).

## Mémoire basse

### Symptôme

Moins de 10 % de mémoire disponible depuis 10 minutes. Repère : environ 1,3 Go utilisés sur 5,6 Go le 2026-11-10.

### Vérifications

```bash
free -m && docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}' && ps -eo rss,comm --sort=-rss | head -8 && sudo dmesg -T | grep -i 'out of memory' | tail -5
```

### Causes probables

- Un conteneur proche de sa limite (chaque service en a une dans les fichiers Compose) : la limite est trop basse ou le service fuit.
- Un processus hors Docker (mise à jour `dnf`, session oubliée).
- La somme des limites dépasse la mémoire du serveur après l'ajout d'un service.

### Actions

1. Identifier le plus gros consommateur ; noter les chiffres.
2. Conteneur en cause : `dc restart <service>`. Pour l'API, voir [api-down](api-down.md).
3. Processus hors Docker : le laisser finir s'il est légitime (`dnf-automatic`), sinon l'arrêter.
4. Si la situation revient : PR qui ajuste les limites, ou changement d'hébergeur (`DEPLOYMENT.md` §9).

### Retour arrière

Un redémarrage de conteneur ne change pas la version : rien à annuler.

## node_exporter injoignable

### Symptôme

Prometheus ne collecte plus les métriques du serveur depuis 5 minutes : disque, mémoire **et sauvegardes** ne sont plus surveillés. Les alertes de sauvegarde peuvent donc se déclencher à tort ensuite.

### Vérifications

```bash
dc ps node-exporter && dc logs --tail 30 node-exporter
```

### Causes probables

Conteneur arrêté ou tué par sa limite de 64 Mo ; réseau Docker recréé sans que Prometheus soit relancé.

### Actions

`dc up -d node-exporter`, puis, si l'alerte persiste deux minutes, `dc restart prometheus`.

### Retour arrière

Rien à annuler.
