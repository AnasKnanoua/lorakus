"""Configuration du module Assistant, validee a l'activation et a chaque modification."""

from pydantic import BaseModel, Field, field_validator


class AssistantConfig(BaseModel):
    """Reglages de l'assistant pour un utilisateur."""

    # Nom sous lequel l'assistant se presente (ADR 0025 : nom affiche configurable).
    display_name: str = Field(default="Lorakus", min_length=1, max_length=40)
    # Le fuseau horaire est un reglage du compte depuis la PR 44 (ADR 0018) : une ancienne
    # cle « timezone » dans une configuration enregistree est ignoree.

    @field_validator("display_name")
    @classmethod
    def _plain_name(cls, value: str) -> str:
        # Le nom entre dans le prompt systeme : une seule ligne, pas de balisage.
        if any(c in value for c in "\n\r<>{}`"):
            raise ValueError("nom affiche : une seule ligne, sans < > { } `")
        return value.strip()
