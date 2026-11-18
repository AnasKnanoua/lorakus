# ADR-0041 — Client HTTP sortant du Core et abonnements ICS

- **Statut** : Accepté (2026-11-18, PR 45)
- **Date** : 2026-11-18
- **Revue prévue** : à chaque nouveau connecteur qui va chercher une adresse donnée par l'utilisateur ; avant toute ouverture commerciale

## Contexte

La PR 45 fait entrer le premier contenu venu d'une adresse **choisie par l'utilisateur** : un calendrier ICS (Google Agenda d'abord, l'ICS de TSP en 2027). Deux risques nouveaux :

1. **SSRF** : une adresse (ou une redirection) qui fait parler le serveur à lui-même, au réseau Docker (PostgreSQL, Prometheus…), au réseau d'Oracle ou à son service de métadonnées (`169.254.169.254`, qui donne les identifiants de la machine). Les contournements connus passent par l'écriture de l'adresse (décimal `2130706433`, hexadécimal `0x7f000001`, octal `0177.0.0.1`, forme courte `127.1`, IPv4 cachée dans de l'IPv6), par un DNS qui change de réponse entre la vérification et la connexion (« DNS rebinding »), ou par une redirection.
2. **Une adresse ICS secrète est un mot de passe** : l'« adresse secrète au format iCal » de Google donne tout le calendrier à qui la connaît.

S'y ajoutent le choix d'une bibliothèque ICS (« Risque : récurrences ICS et fuseaux horaires », ROADMAP P4) et la place de la synchronisation (API ou worker).

## Décision

### 1. Un seul client sortant, dans le Core (`lorakus/core/outbound/`)

- **URL** (`policy.parse_public_url`) : HTTPS seul ; pas d'identifiants (`user@`) ; pas de caractère d'espacement, de contrôle ni de barre oblique inverse (les analyseurs d'URL divergent dessus) ; un vrai nom de domaine : jamais une adresse IP, et le dernier label doit être alphabétique (ou IDN), ce qui refuse toutes les écritures numériques d'une IPv4 ; noms réservés refusés (`localhost`, `.local`, `.internal`, `.test`, `.home.arpa`…).
- **Adresses** (`policy.is_public_address`) : on déballe d'abord les IPv6 qui transportent une IPv4 (mappée `::ffff:`, compatible `::a.b.c.d`, 6to4, NAT64) ; puis liste de réseaux refusés (privés, boucle locale, liaison locale et métadonnées, partagé 100.64/10, documentation, multidiffusion, Teredo, adresses uniques locales IPv6…) **et** `is_global`. Le module `ipaddress` seul ne suffit pas : il juge « globales » `::127.0.0.1`, `64:ff9b::a00:1` (NAT64 de 10.0.0.1) et la multidiffusion (vérifié, tests).
- **Résolution unique** : le nom est résolu une fois par saut ; **toutes** ses adresses doivent être publiques (un nom qui annonce une adresse publique et une adresse privée est refusé) ; la connexion TCP vise l'une de ces adresses vérifiées (back-end réseau d'`httpcore2` qui ignore le nom), et le TLS vérifie le certificat du nom d'origine (SNI). Un second avis du DNS n'est jamais demandé.
- **Redirections** suivies à la main (3 au plus), chacune revalidée de zéro (URL, résolution, adresses) : jamais de retour en HTTP, jamais vers une IP.
- **Bornes** : 4 Mio par défaut, contrôlés sur `Content-Length` puis sur les octets reçus **après décompression** (gzip et deflate décodés par morceaux bornés : une bombe de décompression s'arrête à la limite) ; connexion 5 s, lecture 10 s, total 25 s.
- Aucun proxy ni variable d'environnement lue, aucun cookie ; l'URL complète n'est jamais journalisée (domaine seulement).
- **Les modules ne parlent jamais au réseau eux-mêmes** : contrat import-linter (`httpcore2`, `httpx2`, `socket`, `ssl`, `urllib`, `http` interdits dans `lorakus_modules`).

Pourquoi `httpcore2` directement plutôt que `httpx2` : il est déjà installé (dépendance du SDK Anthropic, déclarée désormais), et il permet de remplacer la connexion TCP (adresse épinglée) sans réimplémenter HTTP ; `httpx2` ajoute redirections automatiques, cookies et lecture de l'environnement, précisément ce qu'on ne veut pas ici.

### 2. Bibliothèque ICS : `icalendar` + `recurring-ical-events`

| Critère | `icalendar` 7.3.0 + `recurring-ical-events` 3.8.2 | `ics` (ics-py) 0.7.3 | `icalendar` seul + `dateutil.rrule` à la main |
| --- | --- | --- | --- |
| Maintenance | `icalendar` : projet collectif (Plone), versions régulières (7.3.0 du 2026-08-19) ; `recurring-ical-events` : même mainteneur principal, 3.8.2 du 2026-04-30 | Peu actif (0.7.2 en 2022, puis 0.7.3 en 2026), 0.8 en développement depuis 2022 | — |
| Récurrences | RRULE multiples, RDATE, EXDATE, RECURRENCE-ID (déplacée, annulée), `X-WR-TIMEZONE` de Google, noms de fuseaux Windows d'Outlook, séries invalides ignorées une à une | Récurrences partielles | Tout à écrire et à tester : c'est le risque nommé de la phase |
| Dépendances ajoutées | `x-wr-timezone` 2.0.1, `six` 1.17.0 ; `python-dateutil` redescend de 4.0.0 à 2.9.0.post0 (contrainte `< 3`) | `arrow`, `tatsu`, `attrs` | aucune |
| Télémétrie | Aucune : pur Python, aucun module réseau, aucune extension compilée (vérifié dans les paquets installés) | — | — |
| Licence | BSD-2 (`icalendar`) ; **LGPL-3.0** (`recurring-ical-events`, `x-wr-timezone`) : usage sans modification, compatible ; à revoir avant toute distribution | Apache-2.0 | — |
| 14 jours | Tous publiés il y a plus de 14 jours (vérifié sur PyPI, versions transitives comprises) | — | — |

Retenu : la première colonne. La redescente de `python-dateutil` est vérifiée par toute la suite de tests (Procrastinate et croniter l'utilisent sans contrainte de version).

### 3. Le fichier est une donnée non fiable

Taille bornée par le client ; 5 000 événements au plus ; une récurrence plus dense que la journée (SECONDLY, MINUTELY, HOURLY) ou qui multiplie les heures (`BYHOUR × BYMINUTE × BYSECOND > 24`) est ignorée en entier, maître et occurrences modifiées compris (elle pourrait produire des millions de dates et bloquer le worker ; un emploi du temps n'en a jamais besoin) ; lecture dans un fil à part avec un délai de 30 s ; 2 000 créneaux par abonnement au plus (au-delà : tronqué, signalé). Titres et lieux ramenés à une ligne visible et bornée ; ils n'atteignent le modèle que par l'outil d'agenda, passés par `inert()` (ADR 0012), et le corpus d'injections les rejoue (position 5).

### 4. Adresse chiffrée, clé des connecteurs distincte

`cal_subscriptions.url_ciphertext` : AES-256-GCM (`FieldCipher`), lié à (utilisateur, abonnement) : une valeur copiée sur une autre ligne ne s'ouvre pas. Clé **`LORAKUS_CONNECTOR_ENCRYPTION_KEY`**, distincte de `LORAKUS_FIELD_ENCRYPTION_KEY` : le worker la reçoit (il déchiffre pour synchroniser), sans pouvoir lire les secrets de double authentification. Générée sur le serveur par `init-env.sh` au déploiement ; obligatoire en staging et en production (l'API et le worker refusent de démarrer sans elle). Hors sauvegardes : la perdre oblige seulement à recopier les adresses. L'API ne renvoie jamais l'adresse : seulement son domaine (`calendar.google.com/…`, aucun morceau du chemin, où se trouve parfois le jeton) ; l'export « Mes données » non plus. Une empreinte SHA-256 de l'adresse (jeton aléatoire long, non devinable) refuse les doublons sans déchiffrer.

### 5. Synchronisation dans le worker, un seul job

`calendars.sync` chaque minute (MODULE_SYSTEM §11) : `cal_claim_due` (SECURITY DEFINER, comme `outbox_claim`) réserve 10 abonnements dus pour 10 minutes et ne rend que des identifiants, seulement pour les utilisateurs qui ont activé le module ; chaque abonnement est ensuite lu et écrit sous la RLS de son utilisateur. Réussite : `ModuleAgenda.replace_source` (idempotent), prochaine synchronisation 30 min plus tard. Échec : les créneaux connus restent, le code de l'erreur est enregistré (liste fermée, contrainte de la table), attente doublée (30 min, 1 h, 2 h… 24 h au plus). Un ajout ou « Synchroniser maintenant » rend l'abonnement dû : le job de la minute suivante s'en charge. **L'API ne télécharge rien** : aucun clic ne déclenche de requête sortante depuis le processus exposé à Internet.

### 6. Outil de lecture de l'agenda dans le chat

`assistant.list_agenda` (`read`, ajouté à `CHAT_TOOLS` après revue) : 1 à 14 jours, heures locales calculées dans le fuseau du compte, 60 créneaux au plus, titres et lieux inertes, aucune adresse ni identifiant d'abonnement. L'agenda ne se modifie pas depuis le chat.

## Alternatives rejetées

- **Vérifier l'adresse puis laisser la bibliothèque HTTP se connecter** : elle refait la résolution ; un DNS qui change d'avis (rebinding) contourne la vérification.
- **Liste d'hôtes autorisés** (seulement `calendar.google.com`…) : trop fermée (ICS de TSP, Outlook, Nextcloud) ; l'adresse publique vérifiée suffit.
- **Télécharger depuis l'API à la création** (retour immédiat) : met une requête sortante choisie par l'utilisateur dans le processus exposé à Internet. Le job de la minute suivante suffit.
- **Donner `LORAKUS_FIELD_ENCRYPTION_KEY` au worker** : il pourrait déchiffrer les secrets TOTP.
- **`ics` (ics-py)** et **dépliage maison** : voir le tableau.

## Conséquences

- Une nouvelle variable sur le serveur, créée seule au déploiement ; la copier dans le gestionnaire de mots de passe est conseillé, pas indispensable.
- Un abonnement nouveau apparaît dans l'agenda une à deux minutes après son ajout.
- Tout futur connecteur qui va chercher une adresse fournie par l'utilisateur passe par `OutboundHttp` (contrat import-linter).
- Hypothèse ajoutée : licence LGPL de `recurring-ical-events` et `x-wr-timezone`, à revoir avant toute distribution.
