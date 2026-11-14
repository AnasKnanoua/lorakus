"""Reponse IA en JSON valide par un modele Pydantic (sorties structurees, PR 36).

Le modele recoit le schema attendu dans son prompt ; sa reponse est lue en entier puis
validee. Une reponse invalide n'est jamais reparee a la main : StructuredOutputError, et
l'appelant fait sans (aucune ecriture). Les refus du ModelRouter (budget, coupure, rythme...)
remontent tels quels.
"""

import uuid
from typing import Final

from pydantic import BaseModel, ValidationError

from lorakus.ai.port import ChatRequest, DataClass, TextDelta
from lorakus.ai.router import ChatResult, ModelRouter

# Une reponse plus longue est anormale pour une sortie structuree : on arrete de lire.
MAX_STRUCTURED_CHARS: Final = 20_000


class StructuredOutputError(Exception):
    """Le modele n'a pas rendu un JSON conforme au schema demande."""


def _strip_fences(text: str) -> str:
    """Retire un eventuel bloc ```json ... ``` autour de la reponse."""
    body = text.strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[1] if "\n" in body else ""
        if body.rstrip().endswith("```"):
            body = body.rstrip()[:-3]
    return body.strip()


async def complete_structured[T: BaseModel](
    router: ModelRouter,
    user_id: uuid.UUID,
    *,
    task: str,
    data_class: DataClass,
    request: ChatRequest,
    schema: type[T],
) -> tuple[T, ChatResult]:
    """Appel complet (non diffuse) dont la reponse doit valider `schema`."""
    parts: list[str] = []
    size = 0
    result: ChatResult | None = None
    stream = router.chat_stream(user_id, task=task, data_class=data_class, request=request)
    try:
        async for event in stream:
            if isinstance(event, TextDelta):
                parts.append(event.text)
                size += len(event.text)
                if size > MAX_STRUCTURED_CHARS:
                    raise StructuredOutputError("reponse trop longue")
            elif isinstance(event, ChatResult):
                result = event
            # Un appel d'outil est impossible ici : la requete n'en decrit aucun.
    finally:
        await stream.aclose()
    if result is None:
        raise StructuredOutputError("reponse incomplete")
    try:
        return schema.model_validate_json(_strip_fences("".join(parts))), result
    except ValidationError as error:
        raise StructuredOutputError(f"{error.error_count()} erreur(s) de schema") from None
