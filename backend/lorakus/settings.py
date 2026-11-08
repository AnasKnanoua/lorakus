"""Configuration de Lorakus, lue depuis les variables d'environnement."""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

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

    @model_validator(mode="after")
    def require_secrets_outside_development(self) -> Self:
        """Refuse de demarrer en staging/production sans mot de passe de base."""
        if self.environment in ("staging", "production") and not (
            self.app_db_password.get_secret_value()
        ):
            raise ValueError("LORAKUS_APP_DB_PASSWORD est obligatoire en staging et production")
        return self

    def app_database_url(self) -> URL:
        """URL de connexion de l'application (role lorakus_app)."""
        return self._database_url(self.app_db_user, self.app_db_password)

    def migrator_database_url(self) -> URL:
        """URL de connexion des migrations (role lorakus_migrator)."""
        return self._database_url(self.migrator_db_user, self.migrator_db_password)

    def _database_url(self, user: str, password: SecretStr) -> URL:
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
