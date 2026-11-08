"""Configuration de Lorakus, lue depuis les variables d'environnement."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "staging", "production"]


class Settings(BaseSettings):
    """Parametres de l'application.

    Chaque champ peut etre fourni par une variable d'environnement prefixee
    par LORAKUS_, par exemple LORAKUS_ENVIRONMENT=production.
    """

    model_config = SettingsConfigDict(env_prefix="LORAKUS_", env_file=".env", extra="ignore")

    app_display_name: str = "Lorakus"
    environment: Environment = "development"


@lru_cache
def get_settings() -> Settings:
    """Retourne une instance unique des parametres (calculee une seule fois)."""
    return Settings()
