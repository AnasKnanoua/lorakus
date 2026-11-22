# Système de modules

Un module est un package Python autonome qui apporte un domaine métier à LORAKUS sans modifier le Core. Ce document est le contrat ; toute évolution du contrat passe par un ADR.

## 1. Règles non négociables

1. Un module **n'importe jamais** un autre module ni `lorakus.ai.providers` (vérifié par `import-linter` depuis la PR 32 ; aucun SDK d'IA hors des adaptateurs, vérifié aussi par `tests/unit/test_ai_boundaries.py`). Le Core n'importe **jamais** un module : il les découvre par leurs entry points. Un module ne parle **jamais** au réseau lui-même (`httpcore2`, `httpx2`, `socket`, `ssl`, `urllib`, `http` interdits par import-linter depuis la PR 45) : il passe par le client sortant du Core, `OutboundHttp` (ADR 0041).
2. Un module **ne lit ni n'écrit** les tables d'un autre ; il possède ses tables, préfixées.
3. Un module **n'envoie jamais de notification** : il émet des signaux (`Signals.emit`), l'`InterventionPolicy` décide.
4. Un module **n'appelle jamais un SDK d'IA** : il passe par `ModelRouter` avec une tâche et une classe de données. Une route l'obtient par la dépendance `lorakus.api.ai.get_ai`, et lit la configuration de l'utilisateur par `ModuleService.config` (exemple : `lorakus_modules/assistant`). La mémoire (`lorakus.api.memory.get_memory`) et les travaux différés (`get_background`) s'obtiennent de la même façon ; un module ne crée jamais lui-même un fait `verified` (ADR 0039).
5. Toute donnée porte `user_id` ; toute requête passe par la session RLS fournie par le Core.
6. Toute dépendance transversale est **déclarée** dans le manifeste : événements, ports fournis, signaux, outils.

## 2. Le manifeste

```python
from lorakus.core.modules import ModuleManifest, Signal, Port

manifest = ModuleManifest(
    id="academic",
    name="Academic Manager",
    version="0.1.0",                       # SemVer du module
    requires_core=">=0.5,<1.0",            # compatibilité avec le Core
    depends_on=[],                         # autres modules : à justifier par ADR (rare)
    permissions=["academic:read", "academic:write"],
    config_schema=AcademicConfig,          # modèle Pydantic, UI générée depuis son JSON Schema
    events_produced=["academic.assessment_created"],
    events_consumed=["calendars.synced"],
    signals_produced=[
        Signal("academic.deadline_approaching", kind="scheduled",
               description="Échéance à J-3 / J-1 d'un devoir non terminé"),
        Signal("academic.overdue", kind="contextual",
               description="Devoir en retard"),
    ],
    provides=[],                           # ports du Core implémentés (ex. ContextProvider)
    tools=[add_assessment, list_upcoming_assessments],
    scheduled_jobs=[detect_overdue],       # @periodic
    api_router=router,                     # monté sous /api/v1/academic
    migrations="lorakus_modules/academic/migrations",  # branche Alembic « academic »
    data=DataDeclaration(
        tables=["acad_courses", "acad_assessments"],
        classes={"acad_assessments": "personal"},
        license_constraints={},            # ex. {"fit_records.source=strava": ["no_ai"]}
    ),
    device_ingest=[],                      # types de lots acceptés (ex. "usage_batch"), phase 7+
    frontend={"route": "/academic", "label": "Cours", "icon": "graduation-cap",
              "today_widget": "UpcomingAssessments"},
    health=check_health,
)
```

Un test de contrat commun (`tests/contract/test_manifests.py`) vérifie pour chaque module : champs complets, noms d'événements et de signaux préfixés par l'id, tables préfixées, permissions de la forme `module:action`, branche Alembic existante, outils documentés avec un niveau de risque.

### 2.1 Mise en œuvre (PR 26)

- `lorakus/core/modules/` : `ModuleManifest` (validé à la construction : id, SemVer, `requires_core`, préfixes des événements, signaux, permissions et tables, classe de chaque table, branche Alembic obligatoire dès qu'il y a des tables), `ModuleRegistry` (découverte, compatibilité, ordre), `ModuleService` (activation et configuration par utilisateur).
- Ajoutés ensuite : `tools` (liste de `ToolSpec`, noms préfixés par l'id du module) et `specialist` (`SpecialistProfile`, nommé comme le module, `data_scopes` limités aux tables du module, `actions` limitées à ses outils) en PR 30 ; un outil `write` ou `sensitive` décrit sa carte de confirmation (`summary`, PR 38) ; un spécialiste déclare ses mots-clés et phrases d'exemple par intention (`keywords`, `examples`) et la durée de vie de ses rapports en cache (`cache_ttl_s`, PR 39) ; jobs et handlers d'événements par décorateurs (`@job`, `@periodic`, `@on`) en PR 29. `capture` (PR 54) : une fonction `Capture` (`lorakus/core/capture.py`) qui range un texte reçu hors de l'application (aujourd'hui : un message Telegram) ; un seul module au plus la fournit, vérifié au chargement ; un refus lève `CaptureRefusedError` avec un message lisible, avant toute écriture ; aucune carte (le texte n'engage rien). Restent à venir : `provides`, `device_ingest`.
- Routes : `GET /api/v1/modules`, `PUT /api/v1/modules/{id}` (`enabled`, `config`), `GET /api/v1/modules/health` (propriétaire). Les routes d'un module, montées sous `/api/v1/<id>`, exigent une session et répondent 404 si le module n'est pas activé pour l'utilisateur.
- Garde-fous en test : contrat de chaque module (`tests/contract/`), et pour toute table portant `user_id`, présence d'une politique RLS qui filtre sur l'utilisateur courant (`tests/isolation/`).

## 3. Cycle de vie

| Étape | Mécanisme |
| --- | --- |
| Découverte | Entry point `lorakus.modules` dans `pyproject.toml` du module |
| Résolution | Au démarrage : tri topologique de `depends_on`, vérification de `requires_core` ; incompatibilité = échec de démarrage avec message explicite |
| Migrations | Conteneur `migrate` : `alembic upgrade heads` (toutes les branches) avant le démarrage de l'API |
| Activation | Table `core_user_modules(user_id, module_id, enabled, config)`, désactivé par défaut ; un module désactivé ne monte ni routes, ni outils, ni jobs, ni signaux pour cet utilisateur ; on ne peut pas activer un module avant ses dépendances, ni désactiver un module dont dépend un module actif |
| Configuration | Validée par `config_schema` à l'activation et à chaque modification |
| Mise à jour | Nouvelle version du module + migration de sa branche ; compatibilité ascendante des événements (`schema_version`) |
| Santé | `health()` appelé par `/admin` et exposé en métrique |

Exclu volontairement : chargement à chaud, modules tiers signés, marketplace.

## 4. Mécanismes de communication

| Besoin | Mécanisme | Exemple |
| --- | --- | --- |
| Informer d'un fait passé | Événement (outbox, asynchrone, au moins une fois) ; le Core en publie aussi : `planning.task_completed` quand l'utilisateur termine la tâche d'un module (PR 46, ADR 0018) | `academic` termine le devoir dont la tâche vient d'être terminée |
| Proposer d'interrompre l'utilisateur | Signal → `InterventionPolicy` | `digital.long_session` |
| Lire un état synchrone d'un autre domaine | Port fourni au Core (`provides`), consommé par le Core uniquement | `FitnessStateProvider` lu par `context` |
| Créer une tâche ou un créneau | Port du Core : `ModuleTasks("academic").upsert(session, user_id, ref, titre, …)` et `ModuleAgenda("calendars").replace_source(session, user_id, source, créneaux)` (PR 44) ; chaque requête est filtrée sur le module, qui ne voit ni les tâches personnelles ni celles d'un autre module | `academic` crée la tâche d'un devoir |
| Exposer une action à l'assistant | Outil `@tool` | `create_project` |
| Aller chercher une ressource à une adresse donnée par l'utilisateur | `OutboundHttp` du Core (SSRF : adresses publiques seulement, redirections revérifiées, tailles bornées), dans un job du worker ; secret de l'adresse chiffré par `FieldCipher.for_connectors` | `calendars` lit un ICS (PR 45) |

Événements : nom `module.sujet_au_passe`, charge utile Pydantic avec `schema_version`, jamais de suppression de champ sans nouvelle version. Un handler (`@on`, nom stable donné par `name=`) filtre ce qui le concerne, relit l'état avant d'agir (l'événement est un signal, pas une preuve) et reste sans effet s'il est rejoué ; il est importé par le manifeste pour être abonné dans le worker.

Signaux : `Signal(name, kind, strength ∈ [0,1], subject_ref, context_hints, dedup_key, expires_at)`. `kind` ∈ `scheduled` (rappel planifié), `contextual` (situation détectée), `proactive` (suggestion). La `dedup_key` empêche deux interventions pour la même cause. Mise en œuvre (P5, ADR 0042) : `await emit(session, user_id, "focus", SignalDraft(name="focus.deadline_soon", kind="scheduled", strength=0.5, data_class="personal", dedup_key=..., title=..., body=..., firm_body=..., rule=..., facts=(Fact(...),), url="/today", subject_ref="task:<uuid>", not_before=..., expires_at=...))`, dans la transaction du module ; textes écrits par le code du module (jamais par un modèle), une ligne chacun ; `withdraw(session, module, dedup_key, raison)` quand la cause disparaît. Une cause émise une fois ne revient jamais, même retirée. Le signal est déclaré dans `signals_produced` du manifeste. Le module émet depuis **un seul** job périodique (§11) qui parcourt les utilisateurs concernés (fonction `core_users_with_tasks_due` pour les échéances). Préparations (ADR 0028, PR 53) : `await prepare(session, user_id, "focus", "briefing", day, title, [Section(heading, lines)], now, expires_at)` crée ou rafraîchit la préparation du jour tant qu'elle n'est pas lue ; elle est montrée en tête de Ma journée. Pour parcourir les utilisateurs qui ont un module activé : `core_users_with_module('<module>')`.

## 5. Outils IA

```python
@tool(name="add_assessment", permission="academic:write", risk="write",
      description="Ajoute un devoir ou un examen avec son échéance")
async def add_assessment(ctx: ToolContext, args: AddAssessmentArgs) -> AssessmentOut: ...
```

- `risk="read"` : exécuté directement. `write` : proposé à l'utilisateur (carte de confirmation) puis exécuté. `sensitive` : confirmation + ré-authentification récente.
- Arguments et résultats typés ; résultat tronqué à 4 000 tokens, sérialisé en JSON.
- Chaque exécution est auditée et tracée.

## 6. Données, classes et licences

Chaque table déclare sa classe (`public`, `personal`, `sensitive`). Les contraintes de licence (`no_ai`, `owner_display_only`) sont portées par ligne quand elles dépendent de la source. Le `ModelRouter` et le pipeline ML refusent toute donnée `sensitive` vers un fournisseur externe et toute donnée `no_ai` vers un LLM ou un entraînement.

### 6.1 Export des données (PR 41)

Un module qui a des tables déclare `data_exporter` dans son manifeste : une fonction `async (DataExportContext) -> dict` (`lorakus.core.data.export`) qui rend ses données en JSON. Le contexte donne l'utilisateur et une transaction liée à lui (RLS : le module ne lit que ses lignes). Le Core l'appelle pour « Mes données », **que le module soit actif ou non** (désactiver ne supprime pas les données). Jamais de secret, d'empreinte ni de vecteur dans ce qui est rendu. Exemple : `lorakus_modules/assistant/export.py`.

## 7. Ports désactivés

Si un module qui fournit un port est désactivé, le port renvoie `None` et le Core marque la dimension « indisponible » ; aucun autre module ne doit échouer. Exemple : `motivation` désactivé = interventions sans pièce jointe.

## 8. Créer un module

```bash
make new-module ID=academic PREFIX=acad NAME="Academic Manager"
```

La commande copie `lorakus_modules/_template` (tables préfixées avec `user_id`, RLS forcée, configuration validée, routes, santé, branche Alembic initiale), déclare le module (entry point dans `backend/pyproject.toml`) et ajoute sa branche de migrations à `backend/alembic.ini`.

1. Compléter le manifeste et remplacer la table d'exemple.
2. Écrire le domaine et ses tests unitaires d'abord.
3. Adapter la migration initiale du module (`migrations/<id>_0001_init.py`) ; les suivantes : `alembic revision --head=<id>@head -m "..."`.
4. Ajouter routes, outils, jobs, handlers.
5. Rédiger `docs/modules/nom_du_module.md` (rôle, événements, signaux, outils, config, données).
6. Vérifier : `make lint test contract`.

## 9. Checklist de revue d'un module

- [ ] Aucun import d'un autre module ni d'un SDK d'IA
- [ ] Toutes les tables préfixées, avec `user_id` et politique RLS
- [ ] Classes de données et contraintes de licence déclarées
- [ ] `data_exporter` déclaré s'il a des tables (export « Mes données », sans secret)
- [ ] Signaux avec `dedup_key` ; aucune notification directe
- [ ] Outils avec permission et niveau de risque corrects
- [ ] Migration rejouable (up/down/check)
- [ ] Tests unitaires du domaine, test d'isolation RLS, test de contrat
- [ ] Documentation du module à jour

## 10. Profil de spécialiste (proposé, ADR 0026)

Un module devient un spécialiste en ajoutant un `SpecialistProfile` à son manifeste :

```python
specialist=SpecialistProfile(
    name="tresorier",
    display_name="Le Tresorier",
    intents=["spending_summary", "budget_status", "savings_projection"],
    data_scopes=["fin_transactions", "fin_budgets", "fin_goals"],  # tables du module uniquement
    reads_ports=[],
    report_class="sensitive",
    llm_usage="none",                 # none | formulation | analysis
    llm_budget_usd_month=0.0,
    answer_timeout_s=3.0,
    preparations=["weekly_finance_review"],
    actions=[],                       # toujours soumises à la file d'approbation
    limits="Aucune operation bancaire, aucune resiliation, aucun conseil d'investissement.",
)
```

Règles supplémentaires :

1. Le spécialiste répond par un `SpecialistReport` typé (résumé de 1 à 3 phrases, faits avec classe, source et mention mesuré/estimé, confiance motivée, actions suggérées jamais exécutées) ; `no_data` est une réponse normale.
2. Il ne lit que ses `data_scopes` et les ports déclarés ; il n'appelle jamais un autre spécialiste.
3. Il ne notifie jamais : il émet des signaux ; les situations multi-domaines sont construites par le Core.
4. Toute action externe est déclarée dans `actions` et passe par la file d'approbation.
5. Si `llm_usage` n'est pas `none`, un budget mensuel est obligatoire ; à 100 %, le spécialiste bascule sur ses gabarits.

Checklist de revue d'un spécialiste, en plus de la checklist du §9 :

- [ ] Intentions uniques et documentées
- [ ] Classe maximale des rapports correcte ; aucune valeur `sensitive` hors marqueurs (test d'interception)
- [ ] Délai de réponse respecté sur données réelles
- [ ] Limites rédigées et testées (refus des demandes hors périmètre)

## 11. Règle de passage à l'échelle : aucune tâche planifiée par utilisateur

Un rappel ou un traitement récurrent ne crée jamais un minuteur par utilisateur (1 000 utilisateurs ne doivent pas donner 1 000 minuteurs). Un module déclare **un seul** job périodique qui traite, par lots, tout ce qui est dû maintenant (« tâches dont l'échéance tombe dans la prochaine minute »), à partir d'un index sur la date d'échéance. Cette règle garde le coût de planification constant quel que soit le nombre d'utilisateurs.
