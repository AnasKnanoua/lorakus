# Sécurité

## 1. Signaler une vulnérabilité

Contact : adresse dédiée à créer en phase 0 (`security@<domaine>`). Réponse sous 7 jours. Ne pas ouvrir d'issue publique pour une vulnérabilité ; utiliser les GitHub Security Advisories privées du dépôt.

## 2. Modèle de menace (résumé)

| Adversaire / menace | Contrôles principaux |
| --- | --- |
| Attaquant Internet opportuniste | Ports 22/80/443 seuls, SSH par clé, fail2ban, rate limit, mises à jour de sécurité, Trivy + Dependabot |
| Vol de session ou de jeton | Cookies HttpOnly/Secure/SameSite, CSP stricte, sessions serveur révocables, TOTP, clés à portée unique |
| Accès aux données d'un autre utilisateur | RLS PostgreSQL + tests d'isolation à deux utilisateurs sur chaque table |
| Prompt injection indirecte | Profil `ingest` sans outils, contenu encapsulé et marqué non fiable, outils à permissions, confirmation des écritures |
| Fuite vers un fournisseur IA | Classes de données et contraintes de licence appliquées par le `ModelRouter` ; embeddings personnels locaux |
| Compromission du serveur | Secrets hors dépôt, fichiers `.env` en 600, sauvegardes chiffrées hors Oracle, champs sensibles chiffrés |
| Chaîne d'approvisionnement | Lockfiles (`uv.lock`, `pnpm-lock.yaml`, Gradle), pip-audit, Dependabot groupé, images épinglées ; modèle d'embeddings téléchargé à la construction de l'image et vérifié par SHA-256, au format ONNX (un graphe : le charger n'exécute pas de code, contrairement à un fichier pickle) |
| Téléphone perdu (phase 7+) | Clé d'appareil dans Android Keystore, révocable depuis `/settings/devices`, tampon local chiffré |
| Lot d'appareil falsifié (phase 7+) | Clé par appareil à portée limitée, schéma strict, horodatages bornés, idempotence, rate limit |
| Outil de test offensif hors périmètre | Cibles en liste blanche, réseau Docker isolé, identifiants de staging uniquement |

## 3. Classification des données

| Classe | Exemples | LLM externe | Chiffrement |
| --- | --- | --- | --- |
| `public` | Articles RSS, pages publiques | Oui, y compris free tier | Transit |
| `personal` | Tâches, cours, mémoire, conversations, sessions d'apps, séances de sport | Fournisseur payant uniquement, minimisé ; agrégats pour l'usage numérique | Transit + volume |
| `sensitive` | Finances, fréquence cardiaque, sommeil, secrets | **Jamais** | Transit + volume + champs chiffrés |

Contraintes de licence (par ligne) : `no_ai` (aucun LLM ni entraînement — ex. données Strava), `owner_display_only`.

## 4. Authentification et autorisation

- MVP : mot de passe Argon2id + TOTP, sessions serveur révocables, ré-authentification pour les actions `sensitive`. Passkeys en phase 7.
- Clés API et clés d'appareil : hachées en base, affichées une fois, à portée (`inbox:write`, `usage:write`, `health:write`), révocables.
- Rôles `owner` et `admin` ; permissions `module:action` déclarées dans les manifestes, vérifiées par l'API et le Tool Runtime.

### 4.1 Mise en œuvre (PR 23, 2026-11-11)

| Point | Choix |
| --- | --- |
| Mots de passe | Argon2id, paramètres par défaut d'argon2-cffi (temps 3, mémoire 64 Mio, parallélisme 4), au-dessus du minimum OWASP (2, 19 Mio, 1) ; re-hachage automatique à la connexion si les paramètres changent ; 12 à 1024 caractères, sans règle de composition (NIST) |
| Sessions | Jeton aléatoire de 256 bits ; seule son empreinte SHA-256 est en base ; expiration après 7 jours sans activité et 30 jours au plus ; toutes révoquées au changement de mot de passe |
| Cookie | `__Host-lorakus_session`, `HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/`, sans `Domain` |
| Connexion | Même message et même chemin (un hachage vérifié, éventuellement factice) que le compte existe ou non ; limitation dans PostgreSQL : 5 échecs par compte et 20 par adresse IP sur 15 minutes ; tentatives conservées 24 heures |
| Isolation | Utilisateur courant posé par `set_config('lorakus.user_id', …, true)` en début de transaction (jamais de `SET` de session : le pool réutilise les connexions) ; RLS activée et **forcée** sur chaque table ; politiques explicites par rôle (`lorakus_app` : ses lignes seulement ; `lorakus_migrator`, propriétaire : tout) |
| Avant authentification | Fonctions `auth_*` en `SECURITY DEFINER`, appartenant à `lorakus_migrator`, au `search_path` figé, fermées à `PUBLIC` ; `lorakus_app` n'a aucun accès direct aux tentatives de connexion et ne peut pas modifier le rôle d'un compte |
| Création du propriétaire | `python -m lorakus.cli create-owner` sur le serveur ; mot de passe lu par `getpass`, jamais en argument ; un seul propriétaire |
| Vérifications | Tests d'isolation exécutés en `lorakus_app` (`tests/isolation/`), `make db-check` (RLS forcée partout, droits des fonctions) |
| Adresse IP | Celle de la connexion TCP ; aucun en-tête `X-Forwarded-For` n'est cru avant l'arrivée du proxy (P3) |
| Double authentification (PR 25) | TOTP (RFC 6238, compatible avec les applications courantes) ; secret chiffré en AES-256-GCM avec une clé hors base (`LORAKUS_FIELD_ENCRYPTION_KEY`), lié à l'utilisateur ; un pas de 30 s déjà utilisé est refusé (anti-rejeu, y compris pour deux requêtes simultanées) ; 10 codes de secours de 64 bits, hachés, à usage unique ; un code faux compte comme un échec de connexion |
| Actions sensibles | Preuve d'identité de moins de 10 minutes (connexion ou `POST /api/v1/auth/reauth`) pour activer ou désactiver la double authentification, régénérer les codes, créer ou révoquer une clé d'API |
| Clés d'API | `lk_<8 caractères visibles>_<secret de 256 bits>` ; affichées une seule fois, empreinte SHA-256 en base, comparaison en temps constant ; portées fermées (`inbox:write`, `usage:write`, `health:write`), expiration obligatoire (365 jours au plus), révocation définitive |
| Empreintes rapides | Jetons de session (256 bits), clés d'API (256 bits) et codes de secours (64 bits) sont **aléatoires** : leur empreinte SHA-256 suffit, car aucune liste de mots ne permet de les deviner. Seuls les mots de passe, choisis par un humain, exigent un hachage lent (Argon2id). L'alerte CodeQL `py/weak-sensitive-data-hashing` sur ces empreintes est un faux positif (le nom « api key » est classé « mot de passe » par son heuristique) : rejetée avec cette justification le 2026-11-11. Toute nouvelle alerte de ce type sur un **mot de passe** reste bloquante |
| Journal d'audit | `core_audit_events` : connexions (réussies, échouées, refusées), déconnexions, changements de mot de passe, double authentification, clés d'API. `lorakus_app` n'y écrit que par `audit_record()` et n'a ni `INSERT` direct, ni `UPDATE`, ni `DELETE`, ni `TRUNCATE` (`make db-check`) ; chacun ne lit que ses événements ; aucun secret dans les détails |
| Événements et jobs (PR 29) | Outbox `core_outbox` : publication dans la transaction de l'appelant, pour l'utilisateur courant seulement (RLS) ; le worker livre chaque événement dans une transaction liée à son utilisateur ; l'application ne modifie la file que par les fonctions `outbox_*`. Charges utiles : des identifiants, jamais de données personnelles. **Exception à la RLS forcée** : les quatre tables `procrastinate_*` (file de jobs, sans colonne utilisateur), car la RLS masque le détail d'erreur dont Procrastinate a besoin pour son verrou anti-doublon ; un test vérifie qu'aucune autre table n'y échappe |
| Outils et spécialistes (PR 30) | Toute action passe par `ToolRuntime` : arguments validés par schéma, `write` et `sensitive` en attente d'une confirmation à usage unique (10 minutes, arguments figés), `sensitive` avec ré-authentification de moins de 10 minutes, chaque demande et exécution auditée. Un spécialiste ne fait que suggérer des actions ; son rapport est refusé s'il contient une donnée plus sensible que sa classe maximale ; trace `core_agent_runs` en ajout seul |
| Outils dans le chat (PR 38, ADR 0040) | Le modèle ne fait que demander : tout passe par `ToolRuntime`. `read` rend une donnée ; `write` et `sensitive` deviennent une carte dont le texte est écrit par l'outil (`summary`, obligatoire), affiché brut. Le modèle ne reçoit jamais l'identifiant de la carte et aucun outil ne confirme : confirmation et refus seulement par `POST /api/v1/tools/confirmations/{id}` (et `/cancel`) avec la session, plus une preuve d'identité récente pour `sensitive`. Liste explicite des outils du chat (`CHAT_TOOLS`). Par message : 4 appels au modèle (le dernier sans outil), 6 appels d'outils, 3 cartes. Confirmation atomique (verrou, exécution, audit) ; arguments effacés après décision, et un déclencheur n'autorise à `lorakus_app` que cet effacement (arguments d'une action en attente toujours figés). Conversation supprimée : cartes annulées, arguments effacés. Testé, y compris par un souvenir piégé et par mutation (`tests/integration/test_chat_tools.py`) |
| Moteur IA (PR 32) | Seul `ModelRouter` appelle un fournisseur ; le SDK n'est importé que par son adaptateur (import-linter et test). Avant tout appel : refus de `no_ai`, de `sensitive` vers un fournisseur externe (dans le code, quelle que soit la configuration), d'un prompt trop long, coupure générale `LORAKUS_AI_KILL_SWITCH`, plafond mensuel par utilisateur. Journal `core_ai_usage` en ajout seul (ni `UPDATE`, ni `DELETE`, ni `TRUNCATE` pour `lorakus_app`) ; aucun contenu de conversation dans les journaux ni dans les métriques. Erreurs du fournisseur traduites sans leur cause (aucune requête ni en-tête, donc aucune clé, ne remonte). Le faux fournisseur n'est jamais enregistré en staging ni en production (test). Clé Anthropic : au seul service `api` (PR 33) ; plafond global matériel : crédit prépayé sans rechargement automatique (D-D) |
| Module assistant (PR 33) | Tables `asst_*` en RLS forcée, clé étrangère composée (conversation, utilisateur) contre l'accès par identifiant connu ; classe `personal` ; messages limités à 8 000 caractères ; historique borné envoyé au modèle ; prompt système versionné, sans aucun outil ni action ; nom affiché validé (une ligne, sans balisage) avant d'entrer dans le prompt ; réponses `no-store` ; messages de secours fixes, sans détail technique |
| Frontend (PR 34) | Réponses du modèle rendues sans HTML brut, liens `http`/`https`/`mailto` seulement (sans référent), aucune image distante (fuite par adresse d'image) ; session par cookie `__Host-` uniquement, aucun jeton en `localStorage`, cache vidé à la déconnexion ; service worker sans aucun cache de `/api/` ; `fetch` interdit hors du client généré (ESLint) ; dépendances npm de 14 jours minimum (pnpm `minimumReleaseAge`) ; `docs/frontend.md` |
| Secours | `python -m lorakus.cli recover-second-factor` sur le serveur : désactive la double authentification d'un compte et ferme ses sessions (téléphone et codes perdus) |

## 5. Secrets

- **Aucun secret dans le dépôt, même chiffré** (dépôt public, ADR 0022) : les secrets d'exécution sont générés **sur le serveur** par un script, dans `/opt/lorakus/.env` (600, utilisateur `deploy`), et n'en sortent pas ; GitHub ne détient que la clé SSH de déploiement, dans l'environnement `production` soumis à approbation.
- Gitleaks en pre-commit et en CI ; protection des secrets au push GitHub et CodeQL activés.
- Rotation trimestrielle (clés IA, Telegram, base), annuelle pour la clé de chiffrement des champs (re-chiffrement par job).
- `structlog` masque `authorization`, `cookie`, `api_key`, `token`, IBAN, numéros de carte.

## 6. Protection de l'API

Validation Pydantic `extra="forbid"`, 10 Mo par upload (phase 9), corps de requête limité à 1 Mo par Caddy. Pas de CORS : interface et API à la même origine.

Mis en œuvre à la PR 35 (ADR 0038) :

| Mesure | Détail |
| --- | --- |
| Exposition | Seul Caddy (non root, lecture seule, sans capacité) publie 80 et 443 ; tout le reste écoute sur `127.0.0.1` ou le réseau Docker interne |
| En-têtes | HSTS un an, CSP `script-src 'self'` (aucun script en ligne), `frame-ancestors 'none'`, `nosniff`, `no-referrer`, `Permissions-Policy`, sans en-tête `Server`. `style-src 'unsafe-inline'` admis pour Radix |
| Origine | Écritures sous `/api/` refusées (403) si `Origin` ou `Sec-Fetch-Site` désignent un autre site, sous-domaines compris ; seconde barrière derrière `SameSite=Strict` |
| Adresse réelle | Caddy réécrit `X-Forwarded-For` ; uvicorn ne le croit que venant de l'adresse fixe de Caddy. Les limites de connexion par IP voient donc les vrais visiteurs |
| Limites par utilisateur | 300 requêtes par minute dont 60 écritures (429, `Retry-After`), compteurs dans PostgreSQL. Appels IA : 6 par minute, 200 par jour, 2 simultanés, dans le `ModelRouter` ; au-delà, gabarit sans appel payant |
| Coût de l'IA | Perte maximale bornée par le crédit prépayé sans rechargement (10 $), puis par le plafond mensuel par utilisateur (3 $), le rythme ci-dessus et la coupure générale (`LORAKUS_AI_KILL_SWITCH`). Alertes `LorakusAiSpendHigh` et `LorakusRateLimited` |
| Double authentification | Obligatoire en production : aucune session sans second facteur confirmé, sessions antérieures refusées, désactivation impossible depuis l'application. Activation et récupération uniquement sur le serveur (`enable-second-factor`, `recover-second-factor`) |

Non couvert à ce stade, prévu : limite par adresse IP des routes sans session autres que la connexion, surveillance externe de l'adresse publique et de l'expiration du certificat (P6), revue de sécurité complète avant toute vente (ROADMAP, Idées). Anti-SSRF pour tout téléchargement d'URL : résolution DNS, refus des IP privées, 5 Mo, 10 s.

## 7. Sécurité des agents IA

1. System prompt fixe et versionné ; contenu externe dans un bloc séparé marqué « donnée non fiable ».
2. Profil `ingest` sans outil, sortie validée par schéma ; profil `assistant` sans contenu externe brut.
3. Outils `read` exécutés, `write` et `sensitive` confirmés par l'utilisateur ; aucun outil n'accède au shell, au système de fichiers ou au réseau libre.
4. Au plus 8 itérations d'outils par tour (chat : 4 appels au modèle, 6 appels d'outils, 3 cartes par message, ADR 0040) ; budgets de tokens et de coût ; chaque appel au modèle compte dans la limite du jour et le budget.
5. Contenus suspects marqués et signalés, jamais bloqués silencieusement.
6. Corpus d'injections Promptfoo exécuté en CI.
7. Mémoire (ADR 0039) : seuls les messages de l'utilisateur sont analysés ; chaque fait proposé doit citer un extrait retrouvé mot pour mot ; rien n'est retenu sans sa confirmation ; les faits entrent dans le prompt comme des données, une ligne chacun, dans un bloc qu'un fait ne peut pas refermer.
8. Outils du chat (ADR 0040) : liste explicite ; résultats d'outils et rappels de cartes transmis au modèle comme des données ; texte des cartes écrit par le code ; le modèle ne voit jamais l'identifiant d'une carte et ne peut pas la confirmer.

## 8. Audit

Table append-only `core_audit_events`. Obligatoire : connexions et échecs, changements de permissions et de configuration, outils `write`/`sensitive`, accès aux données `sensitive`, exports, suppressions, révocations d'appareils, actions admin. Rétention 12 mois ; le rôle applicatif n'a ni `UPDATE` ni `DELETE` sur cette table.

## 9. Sécurité continue

| Niveau | Contenu | Fréquence |
| --- | --- | --- |
| Chaque PR | Ruff, pyright, Bandit, Semgrep (règles maison : `user_id` obligatoire, pas d'import de SDK IA hors providers), Gitleaks, pip-audit, tests d'isolation, Promptfoo (profil `ingest`), import-linter, CodeQL | Continu |
| Chaque image | Trivy : vulnérabilités (échec sur `critical` corrigeable), secrets (échec dès `high`, exceptions étroites dans `infra/ci/trivy-secret.yaml`) | Chaque build |
| Nightly staging | OWASP ZAP baseline, E2E | Chaque nuit |
| Mensuel | ZAP complet, Promptfoo étendu, revue manuelle (Burp), revue des permissions d'outils, checklist OWASP ASVS niveau 2 et OWASP LLM Top 10 | 1er week-end du mois |
| Phase 16 | Agent Red Team isolé qui planifie et exécute les campagnes et ouvre des issues | Déclenché |

Format de rapport (template d'issue `security-finding`) : description, preuve reproductible, sévérité CVSS 4.0, impact, reproduction, recommandation, statut (`open`, `fixed`, `accepted-risk`). Une vulnérabilité `high` ou plus bloque la promotion vers la production.

### 9.1 Alertes de dépendances acceptées

Une alerte n'est fermée sans correctif que si la faille est inatteignable chez nous, avec la preuve, et réexaminée à la mise à jour suivante de la dépendance.

| Date | Alerte | Pourquoi elle est acceptée | Fin prévue |
| --- | --- | --- | --- |
| 2026-11-12 | Dependabot n°1, `minimatch` 10.2.6 et 5.1.9 (npm, gravité moyenne) : déni de service par des motifs de fichiers construits pour exploser | Outils de développement seulement (ESLint, typescript-eslint, `@redocly/openapi-core` pour générer le client). Ils ne lisent que les motifs de nos propres fichiers de configuration, jamais une donnée d'un visiteur ; `minimatch` n'est ni dans l'application livrée (vérifié dans `dist/`) ni dans aucune image. Aucune version corrigée dans les branches 10 et 5 ; forcer la branche 11 sous ces outils risquerait de les casser pour un gain nul. Fermée avec le motif `tolerable_risk` | Dès que Dependabot propose ESLint ou typescript-eslint avec `minimatch` 11 |

## 10. Vie privée et contrôle

- Export JSON et suppression par période depuis `/settings/data`.
- Mémoire (`/memoire`) : chaque souvenir se modifie ou se supprime ; « Tout oublier » efface tout après ré-authentification ; un souvenir supprimé ne laisse aucune trace de son contenu (le journal d'audit ne garde que son identifiant) ; les propositions se désactivent, et les messages écrits pendant ce temps ne sont jamais analysés.
- Vecteurs des souvenirs (PR 37) : un vecteur permet de reconstituer en partie le texte dont il vient ; il est donc traité comme le souvenir lui-même (même classe, RLS forcée, clé étrangère composée vers le fait de son propriétaire) et supprimé avec lui, y compris par « Tout oublier ». Calculés sur le serveur, jamais envoyés à un fournisseur ; la recherche de la page Mémoire (PR 37b) est locale elle aussi, et sa question passe toujours en paramètre lié (jamais concaténée dans le SQL, testé avec des tentatives d'injection).
- Rétention par défaut : conversations brutes 12 mois (résumés conservés), sessions d'apps 90 jours (agrégats 2 ans), santé 2 ans, audit 12 mois.
- Pause globale de la collecte et des interventions (PWA, puis tuile Android).
- Ouverture à d'autres utilisateurs : consentement explicite pour la santé (RGPD art. 9), analyse d'impact, déclarations Google Play — à traiter avant toute ouverture.

## 11. Incidents

1. **Détecter** : alerte Prometheus sur Discord, sentinelle healthchecks.io, rapport ou anomalie.
2. **Contenir** : révoquer sessions et clés, couper tout appel IA (`LORAKUS_AI_KILL_SWITCH=true` dans `/opt/lorakus/.env`, puis redémarrage de l'API), mettre en maintenance.
3. **Diagnostiquer** : traces, logs, audit.
4. **Corriger** : correctif via PR, revue, déploiement.
5. **Restaurer** : sauvegarde si nécessaire ([`docs/runbooks/restore.md`](docs/runbooks/restore.md)).
6. **Post-mortem** : `docs/incidents/AAAA-MM-JJ-titre.md` sous 7 jours.

Runbooks à rédiger en phase 6 : `restore.md`, `rotate-secrets.md`, `block-ai-provider.md`, `revoke-device.md`, `incident.md`.

## 12. Agents et spécialistes (Mission 3)

- **Cloisonnement** : chaque spécialiste ne lit que ses tables (`data_scopes`, vérifié en CI) et les ports déclarés ; le Majordome ne lit aucune table, il reçoit des rapports. Rôles PostgreSQL distincts par spécialiste sensible envisagés en phase 17 (défense en profondeur).
- **LLM** : filtre de confidentialité (ADR 0027) ; test de CI qui intercepte les requêtes sortantes et échoue si une valeur `sensitive` y figure ; classes transmises tracées dans `core_agent_runs`.
- **Actions** : file d'approbation (ADR 0028) ; actions `sensitive` approuvées uniquement dans la PWA avec ré-authentification récente ; expiration à 24 h ; aucune action financière en V1.
- **Friction** : niveau 3 uniquement par pactes préconfigurés, bornés, journalisés, avec sortie de secours (ADR 0029).
- **Veilleur** : sondes en lecture seule qui poussent un inventaire (clé `host:report`) ; Lorakus ne détient aucune clé SSH ni accès entrant ; aucun test intrusif ; uniquement les hôtes déclarés (ADR 0031). Distinct de l'agent Red Team.
- **Traçabilité** : toute question, préparation, intervention et approbation laisse une trace consultable (« pourquoi m'as-tu dit ça ? »).
- **Canaux de notification** : les messages de bot Telegram ne sont pas chiffrés de bout en bout ; une notification issue d'un fait `sensitive` ne contient jamais la valeur (« Nouvelle alerte finance, ouvrez Lorakus »). Les notifications Web Push sont chiffrées de bout en bout et peuvent porter le détail.
- **Exposition** : l'API reste publique (décision D-K du 2026-11-08 : accès privé par réseau chiffré non retenu, en vue d'une éventuelle commercialisation) ; authentification, limitation du débit, en-têtes de sécurité et ZAP sont donc obligatoires dès la première route authentifiée.
