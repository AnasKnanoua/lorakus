"""Configuration de Lorakus, lue depuis les variables d'environnement."""

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

Environment = Literal["development", "test", "staging", "production"]
LogFormat = Literal["json", "console"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]

# backend/lorakus/settings.py -> racine du depot (ou se trouve .env en local).
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Parametres de l'application.

    Chaque champ peut etre fourni par une variable d'environnement prefixee
    par LORAKUS_, par exemple LORAKUS_ENVIRONMENT=production. En local, le
    fichier .env a la racine du depot est lu automatiquement ; en production
    il n'existe pas et seules les variables d'environnement comptent.
    """

    model_config = SettingsConfigDict(
        env_prefix="LORAKUS_", env_file=REPO_ROOT / ".env", extra="ignore"
    )

    app_display_name: str = "Lorakus"
    environment: Environment = "development"

    # --- Observabilite ---
    log_format: LogFormat = "json"
    log_level: LogLevel = "INFO"
    # Port des metriques Prometheus ; None = pas de serveur de metriques (tests, dev).
    metrics_port: int | None = Field(default=None, ge=1024, le=65535)

    # --- PostgreSQL ---
    db_host: str = "127.0.0.1"
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = "lorakus"
    app_db_user: str = "lorakus_app"
    app_db_password: SecretStr = SecretStr("")
    migrator_db_user: str = "lorakus_migrator"
    migrator_db_password: SecretStr = SecretStr("")

    # --- Sessions et connexion (PR 23) ---
    # Une session expire apres une periode sans activite ET apres une duree maximale.
    session_idle_timeout_minutes: int = Field(default=7 * 24 * 60, ge=5)
    session_max_age_hours: int = Field(default=30 * 24, ge=1)
    # Limitation des tentatives de connexion echouees, sur une fenetre glissante.
    login_window_minutes: int = Field(default=15, ge=1)
    login_max_failures_per_account: int = Field(default=5, ge=1)
    login_max_failures_per_ip: int = Field(default=20, ge=1)

    # Re-authentification exigee pour une action sensible si la derniere preuve d'identite
    # (connexion ou /auth/reauth) date de plus de cette duree.
    reauth_window_minutes: int = Field(default=10, ge=1)
    # Cle de chiffrement des champs sensibles en base (secrets TOTP) : 32 octets en
    # hexadecimal (64 caracteres). Obligatoire en staging et en production. Elle n'est
    # PAS dans les sauvegardes : la perdre rend les secrets TOTP illisibles.
    field_encryption_key: SecretStr = SecretStr("")

    # Double authentification exigee pour ouvrir une session (decision du 2026-11-12).
    # Toujours vraie en production, quoi que dise la variable (voir _production_rules).
    require_second_factor: bool = False

    # --- Exposition publique (PR 35) ---
    # Adresse publique de l'interface, sans chemin : https://app.lorakus.app. Les requetes
    # qui modifient des donnees doivent venir de cette origine (en-tete Origin). Exigee par
    # l'API en staging et en production (create_app) ; en developpement, le serveur Vite
    # (localhost:5173) est aussi admis. Le worker et les migrations n'en ont pas besoin.
    public_origin: str = Field(default="", pattern=r"^(https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?)?$")
    # Limites par utilisateur (session ou cle d'API), par minute. Les ecritures comptent aussi
    # dans la limite generale. Au-dela : 429 avec Retry-After.
    api_requests_per_minute: int = Field(default=300, ge=1)
    api_writes_per_minute: int = Field(default=60, ge=1)

    # --- Moteur IA (PR 32, ADR 0007) ---
    # Cle de l'API Anthropic ; vide = fournisseur absent (reponses par gabarit). Fournie au
    # seul service api, comme toute cle d'IA.
    anthropic_api_key: SecretStr = SecretStr("")
    # Coupe tout appel IA sortant (incident, SECURITY.md §11) : reponses par gabarit.
    ai_kill_switch: bool = False
    # Plafond de depense IA par utilisateur et par mois civil (UTC), en dollars (D-D).
    # Alerte dans la reponse a 80 %, plus aucun appel a 100 %.
    ai_monthly_budget_usd: Decimal = Field(default=Decimal("3.00"), ge=0, le=100)
    # Rythme des appels IA par utilisateur (PR 35) : protege le budget contre une rafale
    # (script, session volee, boucle d'un client). Au-dela : reponse par gabarit.
    ai_calls_per_minute: int = Field(default=6, ge=1)
    ai_calls_per_day: int = Field(default=200, ge=1)
    # Reponses IA simultanees par utilisateur (dans ce processus).
    ai_concurrent_calls: int = Field(default=2, ge=1)

    # --- Memoire (PR 36) ---
    # Delai entre le dernier message d'une conversation et l'analyse qui propose des faits :
    # plusieurs messages proches ne coutent qu'une analyse.
    memory_proposal_delay_seconds: float = Field(default=180, ge=0, le=3600)

    # --- Embeddings locaux (PR 37, ADR 0007) ---
    # Dossier du modele (model.onnx et tokenizer.json), integre a l'image de l'API. Absent :
    # faux modele en developpement et en test, refus de demarrer en staging et en production.
    embedding_model_dir: Path = Path("/app/models/multilingual-e5-small")
    # Threads de calcul d'une inference : borne le processeur pris aux autres services.
    embedding_threads: int = Field(default=2, ge=1, le=8)

    @model_validator(mode="after")
    def _production_rules(self) -> "Settings":
        """Regles qu'aucune variable ne peut assouplir hors developpement."""
        if self.environment == "production":
            self.require_second_factor = True
        return self

    def allowed_origins(self) -> frozenset[str]:
        """Origines admises pour les requetes qui modifient des donnees."""
        origins = {self.public_origin} if self.public_origin else set[str]()
        if self.environment in ("development", "test"):
            origins |= {"http://localhost:5173", "http://127.0.0.1:5173"}
        return frozenset(origins)

    def app_database_url(self) -> URL:
        """URL de connexion de l'application (role lorakus_app)."""
        return self._database_url(self.app_db_user, self.app_db_password)

    def migrator_database_url(self) -> URL:
        """URL de connexion des migrations (role lorakus_migrator)."""
        return self._database_url(self.migrator_db_user, self.migrator_db_password)

    def _database_url(self, user: str, password: SecretStr) -> URL:
        # Chaque conteneur ne recoit que le mot de passe du role qu'il utilise :
        # le controle se fait donc role par role, au moment ou l'URL est demandee.
        if self.environment in ("staging", "production") and not password.get_secret_value():
            raise ValueError(f"Mot de passe manquant pour le role {user} en {self.environment}")
        # URL.create echappe les caracteres speciaux et masque le mot de passe
        # quand l'URL est affichee ou journalisee.
        return URL.create(
            drivername="postgresql+psycopg",
            username=user,
            password=password.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )


@lru_cache
def get_settings() -> Settings:
    """Retourne une instance unique des parametres (calculee une seule fois)."""
    return Settings()
