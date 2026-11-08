# ADR-0013 — Application Android compagnon « Lorakus Sensors »

- **Statut** : Validé (2026-11-08, remplace la version Mission 1)
- **Date** : 2026-11-08
- **Revue prévue** : quand un domaine stable existe (évolution vers une Trusted Web Activity)

## Contexte

UsageStatsManager et Health Connect sont inaccessibles à une PWA. Deux architectures étaient comparées : (C) une PWA utilisée dans le navigateur sur PC et Android + une app Android séparée pour les capteurs ; (D) une app Android qui enveloppe la PWA (Trusted Web Activity) et contient les capteurs. L'option D suppose un domaine stable et contrôlé (fichier `/.well-known/assetlinks.json`), que le propriétaire ne veut pas acheter pour l'instant.

## Décision

Option C, choisie par le propriétaire :

- La PWA est l'unique interface utilisateur, sur PC et dans le navigateur Android.
- Une app Android Kotlin séparée, **sans interface métier** (écrans : appairage, permissions, état de la collecte, pause), lit UsageStats et Health Connect, sessionise localement et envoie des **lots HTTPS** toutes les 15 min (WorkManager). **Pas de WebSocket** : une connexion permanente coûte de la batterie et n'apporte rien à des lots périodiques.
- Notifications : le serveur notifie via Web Push (PWA) et Telegram ; l'app Android n'émet que des notifications **locales**, uniquement pendant une session de concentration déclarée. Pas de Firebase Cloud Messaging.
- Appairage : l'app reçoit une clé d'appareil à portée limitée (`usage:write`, `health:write`) via un code affiché dans la PWA ; elle ne partage pas la session de la PWA.
- Identifiant d'application : `io.github.anasknanoua.lorakus`, conservé si l'on ajoute plus tard une Trusted Web Activity dans la même app (option D) sans changer d'identité.

## Alternatives rejetées

App Android native complète + PWA pour le PC (deux interfaces à maintenir) ; option D dès maintenant (dépend d'un domaine stable, plus difficile à déboguer) ; Flutter ou React Native (pont inutile sans interface à partager).

## Conséquences

Deux icônes sur le téléphone tant que l'option D n'est pas ajoutée. Développement plus simple et indépendant de la PWA. L'InterventionPolicy choisit un seul canal par signal (`dedup_key`) pour éviter qu'une même alerte arrive par la PWA et par l'app.
