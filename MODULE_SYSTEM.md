# Système de modules

Un module est un package Python autonome qui apporte un domaine métier à LORAKUS sans modifier le Core. Ce document est le contrat ; toute évolution du contrat passe par un ADR.

## 1. Règles non négociables

1. Un module **n'importe jamais** un autre module ni `lorakus.ai.providers` (vérifié par `import-linter` ; la règle sur `lorakus.ai.providers` est ajoutée avec ce package, en P3). Le Core n'importe **jamais** un module : il les découvre par leurs entry points.
2. Un module **ne lit ni n'écrit** les tables d'un autre ; il possède ses tables, préfixées.
3. Un module **n'envoie jamais de notification** : il émet des signaux (`Signals.emit`), l'`InterventionPolicy` décide.
4. Un module **n'appelle jamais un SDK d'IA** : il passe par `ModelRouter` avec une tâche et une classe de données.
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
- Ajoutés ensuite : `tools` (liste de `ToolSpec`, noms préfixés par l'id du module) et `specialist` (`SpecialistProfile`, nommé comme le module, `data_scopes` limités aux tables du module, `actions` limitées à ses outils) en PR 30 ; jobs et handlers d'événements par décorateurs (`@job`, `@periodic`, `@on`) en PR 29. Restent à venir : `provides`, `device_ingest`.
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
| Informer d'un fait passé | Événement (outbox, asynchrone, au moins une fois) | `knowledge.item_ready` |
| Proposer d'interrompre l'utilisateur | Signal → `InterventionPolicy` | `digital.long_session` |
| Lire un état synchrone d'un autre domaine | Port fourni au Core (`provides`), consommé par le Core uniquement | `FitnessStateProvider` lu par `context` |
| Créer une tâche ou un créneau | Port du Core `Tasks` / `Agenda` avec `owner_module` | `academic` crée la tâche d'un devoir |
| Exposer une action à l'assistant | Outil `@tool` | `create_project` |

Événements : nom `module.sujet_au_passe`, charge utile Pydantic avec `schema_version`, jamais de suppression de champ sans nouvelle version.

Signaux : `Signal(name, kind, strength ∈ [0,1], subject_ref, context_hints, dedup_key, expires_at)`. `kind` ∈ `scheduled` (rappel planifié), `contextual` (situation détectée), `proactive` (suggestion). La `dedup_key` empêche deux interventions pour la même cause.

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
