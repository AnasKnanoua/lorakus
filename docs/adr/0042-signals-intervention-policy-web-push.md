# ADR-0042 — Signaux, politique d'intervention et notifications Web Push

- **Statut** : Validé (2026-11-21, découpage de la P5 et décisions D1 à D11 acceptés par le propriétaire)
- **Date** : 2026-11-22
- **Revue prévue** : fin de la phase 5 (deux semaines sans doublon), puis avant toute ouverture commerciale

## Contexte

La P5 donne l'initiative à Lorakus : rappeler une échéance, préparer le lendemain, prévenir sur le téléphone. Trois risques : l'agacement (trop de messages, à de mauvaises heures), les doublons (le même rappel deux fois), et la fuite (un message lu par un tiers). Les ADR 0014, 0019 et 0029 posaient le principe (un seul point d'entrée, une seule politique, des niveaux) sans le mettre en œuvre. Les horaires du propriétaire changent tous les jours (ADR 0018, amendement de la PR 49) : aucune heure calme fixe ne les décrit.

## Décision

1. **Un module propose, le Core décide.** Un module émet un signal (`lorakus.core.signals.service.emit`) : une cause, avec son texte écrit par le code, sa règle et ses faits (pour « Pourquoi ? »), une fenêtre de validité et une clé unique. Il ne notifie jamais lui-même. Une cause n'existe qu'une fois par utilisateur (contrainte `UNIQUE (user_id, dedup_key)`) : émettre de nouveau ne change rien, un signal retiré ou expiré ne revient pas. Une cause qui n'en est plus une (tâche terminée, commencée, repoussée) est retirée (`withdraw`), et sa carte disparaît.
2. **Une politique pure** (`policy.py`) : des fonctions sans base, sans réseau, sans LLM, testées règle par règle puis sur 40 semaines simulées. Deux niveaux :
   - **niveau 1, discret** : une carte « À noter » en tête de Ma journée. Ni heures calmes ni budget : elle n'interrompt pas. Affichée, elle compte comme vue ;
   - **niveau 2, ferme** : une notification sur les appareils abonnés, seulement si la carte n'a été ni vue, ni fermée, ni repoussée pendant 24 h ; une fois par cause ; jamais pour une cause `sensitive` ; au plus 3 par jour local.
3. **Heures calmes sans rien supposer (D1)** : une notification ne part que pendant la plage de travail que l'utilisateur a donnée pour le jour en cours (cadre du jour, PR 49), hors de ses pauses. Sans cadre, ou un jour sans travail, aucune notification : la carte suffit. Une nuit de travail compte pour le jour où elle a commencé (même règle que la page).
4. **Jamais deux fois** : la décision d'envoyer est enregistrée (`core_interventions`, `UNIQUE (signal_id, level)`) et validée avant l'envoi, qui se fait hors de la transaction. Deux processus qui décideraient en même temps : le second bute sur la contrainte et n'envoie rien (compté par `lorakus_interventions_duplicate_total`, attendu à 0). Un envoi interrompu n'est pas repris : mieux vaut un rappel manqué qu'un rappel en double.
5. **Un seul job pour tous** (`signals.dispatch`, chaque minute, MODULE_SYSTEM §11) : `core_signals_claim_due` (SECURITY DEFINER) rend des identifiants dus, chacun est traité sous la RLS de son utilisateur. Aucun appel à un modèle de langage, vérifié par import-linter : les rappels continuent quand le fournisseur d'IA est coupé (scénario 8).
6. **Web Push en canal principal (D2)** : le message est chiffré de bout en bout (RFC 8291) ; le service de Google, Mozilla ou Apple le transporte sans le lire. Écrit sur `cryptography` (D3), vérifié par les vecteurs de la RFC 8291 et contre-vérifié par `http_ece` et `py-vapid` hors du dépôt. Envoi par le client sortant du Core (`OutboundHttp.post`, ajouté ici) : l'adresse d'un abonnement vient du navigateur, elle n'est acceptée que si elle mène à un service connu (`fcm.googleapis.com`, `updates.push.services.mozilla.com`, `web.push.apple.com`, `*.notify.windows.com`), en HTTPS sur le port 443, puis passe la protection SSRF habituelle. Aucune redirection suivie. Un appareil désabonné (404, 410) est oublié.
7. **Secrets (D5)** : une paire VAPID P-256 générée sur le serveur par `init-env.sh` (OpenSSL), hors sauvegardes. Le worker, qui envoie, reçoit la privée ; l'API ne reçoit que la publique, qu'elle donne aux navigateurs. Une paire incohérente empêche le worker de démarrer. L'adresse d'abonnement et les clés d'un appareil ne sont jamais renvoyées par l'API, ni exportées, ni journalisées (seuls le nom de l'appareil et le domaine du service).
8. **« Pourquoi ? » (scénario 7)** : chaque carte et chaque notification s'expliquent : la règle, les faits lus (source, mesuré ou estimé) et chaque décision (niveau, raison, budget du jour, cadre, appareils), sans aucun texte de l'utilisateur dans la décision enregistrée.
9. **Pas de Context Engine (D10)** : la politique lit directement le planning du Core. Le `PersonalContext` de l'ADR 0014 viendra avec un second consommateur.

Premier producteur : le Sergent (`focus.deadline_watch`, toutes les 10 minutes) : une tâche à rendre dans 3 jours ou moins, sans étape terminée, donne un signal (scénario 4).

## Alternatives rejetées

- **Heures calmes fixes** (23 h – 7 h) : fausses un jour sur deux pour le propriétaire.
- **Notification directe par le module** : contraire à l'ADR 0019 ; budget et dédoublonnage impossibles à garantir.
- **`pywebpush`** : envoie par `requests`, hors du client protégé contre la SSRF.
- **Telegram en canal principal** : les serveurs de Telegram lisent les messages d'un bot. Il reste pour la capture d'idées et comme second canal, sans contenu (PR suivante).
- **Reprendre un envoi interrompu** : risque de doublon (le service a pu l'accepter avant la coupure).
- **Boutons d'action dans la notification** : une action déclenchée depuis l'écran verrouillé, sans la page ; on répond au rappel dans l'application.

## Conséquences

- Tables `core_signals`, `core_interventions`, `core_push_subscriptions` (migration 0017, RLS forcée) ; dans « Mes données », sans secret d'appareil.
- Routes `/api/v1/notifications/...` ; page « Notifications » (pied de la barre latérale) ; cartes « À noter » dans Ma journée ; service worker : `push` et `notificationclick` (une page de l'application seulement).
- Le budget et les heures calmes sont uniques pour toutes les sources : un nouveau module qui émet des signaux n'ajoute pas de bruit sans passer par eux.
- Limite connue : « commencé » ne se voit que par une étape terminée. Une tâche commencée sans découpage garde sa carte ; un geste (« OK ») la ferme pour de bon.
- Amende les ADR 0014 (version minimale sans Context Engine), 0019 (mise en œuvre), 0020 et 0035 (Web Push en principal, secrets au worker) et 0029 (définition des niveaux 1 et 2).

## Amendement du 2026-11-22 (PR 53) : le briefing ne sonne pas

Le briefing du lendemain est une préparation (ADR 0028) montrée en tête de Ma journée, pas un signal : aucune notification. Une notification chaque matin userait un tiers du budget quotidien pour une information que la page donne à la première ouverture (scénario 3 : « présenté au début de la journée déclarée ou à la première ouverture »). Une notification du briefing, réglable, est notée dans les idées de `ROADMAP.md`.

## Amendement du 2026-11-22 (PR 54) : Telegram, capture d'idées et second canal

- **Relève par le worker** (D5) : `telegram.poll` chaque minute, un appel `getUpdates` en attente longue d'au plus 45 secondes au total, puis le worker rend la main. Le décalage est gardé en mémoire ; après un redémarrage, Telegram renvoie les messages non acquittés et le refus des doublons de la boîte d'idées les absorbe. Aucune route publique : rien à authentifier côté Telegram, pas de webhook. Le jeton ne va qu'au worker ; l'API ne reçoit que `LORAKUS_TELEGRAM_AVAILABLE` (vrai si un jeton existe), pour afficher la page.
- **Liaison** : la page donne un code de 8 caractères (alphabet sans 0, O, 1, I, L), valable 10 minutes, usage unique, conservé haché (SHA-256). L'utilisateur l'envoie au bot ; la fonction `core_telegram_link` (SECURITY DEFINER) consomme le code et lie la discussion. Une discussion ne sert qu'un compte : la lier ailleurs la retire du premier. Après 5 mauvais codes en une heure, une discussion n'obtient plus de réponse jusqu'à la fin de l'heure. Discussions privées seulement ; messages de bots, de groupes et sans texte ignorés.
- **Capture** : le Core définit un port `Capture` (`lorakus/core/capture.py`), fourni par un seul module au plus (`manifest.capture`, vérifié au chargement). `projects` le fournit : le texte devient une idée de la boîte (provenance `telegram`), sans carte de confirmation (D7 : une idée n'engage rien, elle s'archive ou se supprime). Le texte reste une donnée : il n'est jamais lu par un modèle à la réception ; il est rendu par `inert()` quand l'outil de liste le montre au modèle (31 attaques du corpus rejouées dans un message). Module désactivé : « Boîte d'idées désactivée », rien n'est écrit.
- **Second canal** : la case « rappels sans détail » ajoute la discussion aux appareils du niveau 2. Le message ne dit jamais la cause (« Lorakus : un rappel t'attend. Ouvre Ma journée : … ») : les serveurs de Telegram lisent les messages d'un bot. Même budget, mêmes heures, même règle « jamais deux fois » : une intervention, plusieurs appareils.
- **Rejeté** : webhook (route publique et secret partagé de plus, pour un seul utilisateur) ; liaison par `/start <jeton>` dans un lien profond (le jeton finirait dans l'historique de Telegram) ; le détail du rappel sur Telegram.
