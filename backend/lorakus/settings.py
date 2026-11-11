"""Configuration de Lorakus, lue depuis les variables d'environnement."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
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
