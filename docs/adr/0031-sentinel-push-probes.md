# ADR-0031 — Veilleur : surveillance défensive par sondes qui poussent leurs données

- **Statut** : Accepté
- **Date** : 2026-11-08
- **Revue prévue** : Phase 17

## Contexte

Le Veilleur surveille les machines de l'utilisateur. Donner à Lorakus un accès SSH à ces machines ferait de toute compromission de Lorakus une compromission de l'infrastructure.

## Décision

Un script de sonde (minuteur systemd) sur chaque hôte déclaré collecte un inventaire en lecture seule (système, noyau, mises à jour de sécurité en attente, ports en écoute, images Docker et empreintes, réglages SSH et pare-feu, certificats) et l'envoie à Lorakus avec une clé d'appareil de portée `host:report`. Lorakus ne détient aucune clé SSH ni accès entrant. Correspondance avec OSV et les avis Oracle Linux et Ubuntu ; ports comparés à une liste autorisée ; rapport hebdomadaire ; aucune analyse intrusive, aucune modification de configuration ; uniquement les hôtes déclarés.

## Alternatives rejetées

Agent qui se connecte en SSH aux hôtes ; scans réseau automatiques.

## Conséquences

Distinct de l'agent Red Team (offensif, staging uniquement, phase 17). Livré en phase 7.
