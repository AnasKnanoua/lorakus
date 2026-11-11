"""Configuration du module Template, validee a l'activation et a chaque modification."""

from pydantic import BaseModel, Field


class TemplateConfig(BaseModel):
    """Exemple : remplacer par les reglages reels du module."""

    greeting: str = Field(default="Bonjour", max_length=40)
