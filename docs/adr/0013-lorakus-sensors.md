# ADR-0013 — Application Android compagnon « Lorakus Sensors »

- **Statut** : Validé (2026-11-08, révisé le 2026-11-08)
- **Date** : 2026-11-08
- **Revue prévue** : phase 7 — conserver deux apps ou intégrer la PWA dans l'app

## Contexte

UsageStatsManager et Health Connect sont inaccessibles à une PWA. Deux architectures ont été comparées : (C) une PWA utilisée dans le navigateur sur PC et Android, plus une app Android séparée pour les capteurs ; (D) une app Android qui affiche la PWA (Trusted Web Activity) et contient les capteurs. L'option D exige une adresse HTTPS stable et contrôlée pour publier `/.well-known/assetlinks.json` ; un sous-domaine gratuit (deSEC) suffit, un domaine payant n'est pas nécessaire.

## Décision

Option C pour démarrer :

- La PWA est l'unique interface utilisateur, sur PC et dans le navigateur Android.
- Une app Android Kotlin séparée, **sans interface métier** (écrans : appairage, permissions, état de la collecte, pause), lit UsageStats et Health Connect, sessionise localement et envoie des **lots HTTPS** toutes les 15 min (WorkManager). **Pas de WebSocket.**
- Notifications : le serveur notifie via Web Push (PWA) et Telegram ; l'app Android n'émet que des notifications **locales**, pendant une session de concentration déclarée. Pas de Firebase Cloud Messaging.
- Appairage par un code affiché dans la PWA ; l'app reçoit une clé d'appareil à portée limitée (`usage:write`, `health:write`).
- Identifiant d'application : `io.github.anasknanoua.lorakus`, conservé si l'option D est adoptée.

## Réévaluation prévue en phase 7

Au démarrage de la phase 7, choisir entre :

- conserver deux apps (la seconde reste un utilitaire rarement ouvert) ;
- passer à l'option D dans la **même** app : ajout d'une Trusted Web Activity pointant vers l'adresse HTTPS choisie en phase 3 (décision D-G). Coût estimé : 2 à 3 jours. Critère : gêne réelle de la double installation ou du double appairage après plusieurs mois d'usage de la PWA.

## Alternatives rejetées

App Android native complète + PWA pour le PC (deux interfaces à maintenir) ; Flutter ou React Native (pont inutile sans interface à partager).

## Conséquences

Deux icônes sur le téléphone tant que l'option D n'est pas adoptée. Développement indépendant de la PWA. L'InterventionPolicy choisit un seul canal par signal (`dedup_key`) pour éviter qu'une alerte arrive deux fois.
