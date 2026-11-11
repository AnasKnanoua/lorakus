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
| Chaîne d'approvisionnement | Lockfiles (`uv.lock`, `pnpm-lock.yaml`, Gradle), pip-audit, Dependabot groupé, images épinglées |
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
| Secours | `python -m lorakus.cli recover-second-factor` sur le serveur : désactive la double authentification d'un compte et ferme ses sessions (téléphone et codes perdus) |

## 5. Secrets

- **Aucun secret dans le dépôt, même chiffré** (dépôt public, ADR 0022) : les secrets d'exécution sont générés **sur le serveur** par un script, dans `/opt/lorakus/.env` (600, utilisateur `deploy`), et n'en sortent pas ; GitHub ne détient que la clé SSH de déploiement, dans l'environnement `production` soumis à approbation.
- Gitleaks en pre-commit et en CI ; protection des secrets au push GitHub et CodeQL activés.
- Rotation trimestrielle (clés IA, Telegram, base), annuelle pour la clé de chiffrement des champs (re-chiffrement par job).
- `structlog` masque `authorization`, `cookie`, `api_key`, `token`, IBAN, numéros de carte.

## 6. Protection de l'API

Validation Pydantic `extra="forbid"`, 10 Mo par upload, 32 ko par JSON, rate limit (Caddy par IP, compteur par utilisateur), CORS fermé au domaine du frontend, HSTS, CSP `default-src 'self'` (embeds listés explicitement en phase 10), `X-Content-Type-Options`, `Referrer-Policy`. Anti-SSRF pour tout téléchargement d'URL : résolution DNS, refus des IP privées, 5 Mo, 10 s.

## 7. Sécurité des agents IA

1. System prompt fixe et versionné ; contenu externe dans un bloc séparé marqué « donnée non fiable ».
2. Profil `ingest` sans outil, sortie validée par schéma ; profil `assistant` sans contenu externe brut.
3. Outils `read` exécutés, `write` et `sensitive` confirmés par l'utilisateur ; aucun outil n'accède au shell, au système de fichiers ou au réseau libre.
4. Au plus 8 itérations d'outils par tour ; budgets de tokens et de coût.
5. Contenus suspects marqués et signalés, jamais bloqués silencieusement.
6. Corpus d'injections Promptfoo exécuté en CI.

## 8. Audit

Table append-only `core_audit_events`. Obligatoire : connexions et échecs, changements de permissions et de configuration, outils `write`/`sensitive`, accès aux données `sensitive`, exports, suppressions, révocations d'appareils, actions admin. Rétention 12 mois ; le rôle applicatif n'a ni `UPDATE` ni `DELETE` sur cette table.

## 9. Sécurité continue

| Niveau | Contenu | Fréquence |
| --- | --- | --- |
| Chaque PR | Ruff, pyright, Bandit, Semgrep (règles maison : `user_id` obligatoire, pas d'import de SDK IA hors providers), Gitleaks, pip-audit, tests d'isolation, Promptfoo (profil `ingest`), import-linter, CodeQL | Continu |
| Chaque image | Trivy (échec sur `critical`) | Chaque build |
| Nightly staging | OWASP ZAP baseline, E2E | Chaque nuit |
| Mensuel | ZAP complet, Promptfoo étendu, revue manuelle (Burp), revue des permissions d'outils, checklist OWASP ASVS niveau 2 et OWASP LLM Top 10 | 1er week-end du mois |
| Phase 16 | Agent Red Team isolé qui planifie et exécute les campagnes et ouvre des issues | Déclenché |

Format de rapport (template d'issue `security-finding`) : description, preuve reproductible, sévérité CVSS 4.0, impact, reproduction, recommandation, statut (`open`, `fixed`, `accepted-risk`). Une vulnérabilité `high` ou plus bloque la promotion vers la production.

## 10. Vie privée et contrôle

- Export JSON et suppression par période depuis `/settings/data`.
- Rétention par défaut : conversations brutes 12 mois (résumés conservés), sessions d'apps 90 jours (agrégats 2 ans), santé 2 ans, audit 12 mois.
- Pause globale de la collecte et des interventions (PWA, puis tuile Android).
- Ouverture à d'autres utilisateurs : consentement explicite pour la santé (RGPD art. 9), analyse d'impact, déclarations Google Play — à traiter avant toute ouverture.

## 11. Incidents

1. **Détecter** : alerte Grafana/Uptime Kuma, rapport ou anomalie.
2. **Contenir** : révoquer sessions et clés, couper l'egress IA (`AI_KILL_SWITCH=1`), mettre en maintenance.
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
