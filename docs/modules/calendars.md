# Module Calendriers (`calendars`)

Abonnements ICS en lecture : les événements d'un calendrier externe (Google Agenda, Outlook, plus tard l'ICS de TSP) arrivent dans l'agenda du Core, que l'assistant lit pour répondre et que le planificateur utilisera (PR 47). Décisions et choix de bibliothèque : ADR 0041.

## Ce que fait le module

- **Abonnements** (page `/calendriers`) : un nom et l'« adresse secrète au format iCal ». L'adresse est validée sans réseau (HTTPS, vrai nom de domaine, pas d'adresse IP ni de nom local), chiffrée, puis **plus jamais renvoyée** : la page n'en montre que le domaine (`calendar.google.com/…`). 20 abonnements au plus ; une même adresse une seule fois.
- **Synchronisation** : un seul job, `calendars.sync`, chaque minute, pour tous les utilisateurs. Un abonnement est dû à sa création, après « Synchroniser maintenant », 30 minutes après une réussite, ou après l'attente qui suit un échec (30 min, puis le double, 24 h au plus). Un échec garde les créneaux déjà connus.
- **Dépliage** : les récurrences (RRULE, RDATE, EXDATE, occurrences déplacées ou annulées par RECURRENCE-ID) sont dépliées sur une fenêtre glissante, de 7 jours avant à 120 jours après la synchronisation. L'agenda du Core ne reçoit que des créneaux concrets (ADR 0018) : horaires en UTC, journées entières en dates (fin exclue).
- **Fuseaux** : `TZID` et `VTIMEZONE` du fichier (noms Windows d'Outlook compris), `X-WR-TIMEZONE` de Google ; une heure « flottante » (sans fuseau) prend le fuseau du compte. Un événement horaire sans fin dure une minute (une échéance reste visible).
- **Suppression** d'un abonnement : ses créneaux quittent l'agenda ; le calendrier d'origine n'est pas touché.

## Approche (programmation classique, ML ou LLM)

| Besoin | Choix | Pourquoi |
| --- | --- | --- |
| Lire un fichier ICS, déplier les récurrences | Bibliothèque (`icalendar`, `recurring-ical-events`) | Format normalisé ; les cas limites (fuseaux, exceptions) sont le risque nommé de la phase : une bibliothèque mûre et testée vaut mieux qu'un dépliage maison |
| Valider une adresse, choisir quand synchroniser | Règles | Sécurité (SSRF) et coût déterministes |
| Comprendre « qu'est-ce que j'ai demain ? » | LLM du chat, qui appelle l'outil d'agenda | Les heures sont calculées par le code ; le modèle ne fait que les relayer |

## Sécurité

- Téléchargement par le client sortant du Core (`lorakus/core/outbound/`) : HTTPS seul, résolution unique et adresses publiques seulement (métadonnées du cloud, réseau Docker et réseaux privés refusés, IPv4 déguisées comprises), redirections revérifiées, 4 Mio et 25 s au plus. Le module n'importe aucune bibliothèque réseau (contrat import-linter).
- Le fichier est une donnée non fiable : 5 000 événements au plus, récurrences plus denses que la journée ignorées, lecture bornée à 30 s dans un fil à part, 2 000 créneaux par abonnement. Titres et lieux ramenés à une ligne visible ; ils n'atteignent le modèle que par l'outil d'agenda, passés par `inert()`.
- Adresse chiffrée par `LORAKUS_CONNECTOR_ENCRYPTION_KEY` (API et worker, jamais la clé des secrets TOTP), liée à l'utilisateur et à l'abonnement ; absente des réponses, des journaux, du journal d'audit et de l'export.
- RLS forcée ; le job ne voit que des identifiants (`cal_claim_due`), puis travaille sous la RLS de chaque utilisateur, et seulement pour ceux qui ont activé le module.

## Données

| Table | Classe | Contenu |
| --- | --- | --- |
| `cal_subscriptions` | `personal` | Nom, adresse chiffrée, empreinte (anti-doublon), domaine affiché, état de la dernière synchronisation (code d'erreur dans une liste fermée), compteurs, prochaine synchronisation, réservation du job |

Les créneaux sont dans `core_agenda_entries` (Core, `owner_module = 'calendars'`, `source_key` = identifiant de l'abonnement). Export « Mes données » : les abonnements sans adresse ; les créneaux avec l'agenda du Core.

## API (`/api/v1/calendars`, session exigée, module activé)

| Route | Effet |
| --- | --- |
| `GET /subscriptions` | Abonnements, sans adresse |
| `POST /subscriptions` | `{name, url}` ; 422 avec un message lisible si l'adresse est refusée, en double, ou au-delà de 20 |
| `POST /subscriptions/{id}/sync` | Synchronisation à la minute suivante (202) |
| `DELETE /subscriptions/{id}` | Supprime l'abonnement et ses créneaux (204) |

## Job

| Nom | Fréquence | Effet |
| --- | --- | --- |
| `calendars.sync` | Chaque minute | Réserve jusqu'à 10 abonnements dus et les synchronise ; un échec n'arrête pas les suivants |

## Tests

`tests/unit/test_outbound.py` (chaque contournement SSRF, contre un serveur HTTPS local), `tests/unit/test_calendars_ics.py` (emploi du temps hebdomadaire calqué sur celui de METU, EXDATE, RECURRENCE-ID, journées entières, fuseau Windows et changement d'heure américain, récurrences dangereuses), `tests/integration/test_calendars.py` (API, chiffrement, synchronisation, isolation à deux utilisateurs, module désactivé), `tests/integration/test_agenda_tool.py` (outil du chat), corpus d'injections (position 5). Fichiers de test synthétiques, au format des exports de Google et d'Outlook ; aucun fichier réel anonymisé pour l'instant.
