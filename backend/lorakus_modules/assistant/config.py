"""Configuration du module Assistant, validee a l'activation et a chaque modification."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator


class AssistantConfig(BaseModel):
    """Reglages de l'assistant pour un utilisateur."""

    # Nom sous lequel l'assistant se presente (ADR 0025 : nom affiche configurable).
    display_name: str = Field(default="Lorakus", min_length=1, max_length=40)
    # Fuseau de l'utilisateur : la date du jour donnee au modele en depend.
    timezone: str = Field(default="Europe/Paris", max_length=64)

    @field_validator("display_name")
    @classmethod
    def _plain_name(cls, value: str) -> str:
        # Le nom entre dans le prompt systeme : une seule ligne, pas de balisage.
        if any(c in value for c in "\n\r<>{}`"):
            raise ValueError("nom affiche : une seule ligne, sans < > { } `")
        return value.strip()

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"fuseau horaire inconnu : {value}") from None
        return value
