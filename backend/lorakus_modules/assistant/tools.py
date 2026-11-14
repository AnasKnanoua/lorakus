"""Outils du chat sur la memoire (PR 38) : chercher, retenir, corriger, oublier.

Chercher (read) s'execute tout de suite. Retenir et corriger (write) puis oublier (sensitive)
ne font rien d'eux-memes : le ToolRuntime affiche une carte dont le TEXTE est ecrit ici, a
partir des arguments valides et des donnees de l'utilisateur, jamais par le modele.
L'action n'a lieu qu'apres le clic de l'utilisateur (et sa preuve d'identite pour oublier).

Les erreurs sont levees en ToolError, avec un message court en francais : l'utilisateur le
voit sur sa carte, et le modele le recoit comme resultat d'un appel refuse.
"""

import uuid
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

from lorakus.core.memory.service import (
    MAX_FACT_CHARS,
    Category,
    DuplicateFactError,
    FactLimitError,
    FactNotFoundError,
    InvalidFactError,
    MemoryService,
)
from lorakus.core.tools.spec import ToolCall, ToolError, ToolSpec

SEARCH_LIMIT: Final = 8

CATEGORY_LABELS: Final[dict[str, str]] = {
    "identity": "identité",
    "preference": "préférence",
    "project": "projet",
    "habit": "habitude",
    "studies": "études",
    "other": "autre",
}


def _memory(call: ToolCall) -> MemoryService:
    if call.ports.memory is None:
        raise ToolError("La mémoire est indisponible pour le moment.")
    return call.ports.memory


def _memory_error(error: Exception) -> ToolError:
    if isinstance(error, DuplicateFactError):
        return ToolError("Ce souvenir existe déjà.")
    if isinstance(error, FactLimitError):
        return ToolError("Ta mémoire est pleine : supprime des souvenirs avant d'en ajouter.")
    if isinstance(error, FactNotFoundError):
        return ToolError("Ce souvenir n'existe plus.")
    if isinstance(error, InvalidFactError):
        return ToolError(f"Souvenir refusé : {error}.")
    raise error


class SearchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=200, description="Ce que tu cherches.")


class RememberIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(
        min_length=1,
        max_length=MAX_FACT_CHARS,
        description="Le souvenir, en une phrase courte à la 3e personne (ex. « Révise le matin »).",
    )
    category: Category = Field(default="other", description="Catégorie du souvenir.")


class UpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_id: uuid.UUID = Field(description="Identifiant donné par la recherche dans la mémoire.")
    content: str = Field(min_length=1, max_length=MAX_FACT_CHARS, description="Nouveau texte.")


class ForgetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_id: uuid.UUID = Field(description="Identifiant donné par la recherche dans la mémoire.")


# ------------------------------------------------------------------- chercher
async def _search(call: ToolCall, args: SearchIn) -> dict[str, Any]:
    facts = await _memory(call).search(call.user_id, args.question, limit=SEARCH_LIMIT)
    return {
        "souvenirs": [
            {"id": str(f.id), "texte": f.content, "categorie": CATEGORY_LABELS.get(f.category)}
            for f in facts
            if f.status == "verified"
        ]
    }


# -------------------------------------------------------------------- retenir
async def _remember_summary(_call: ToolCall, args: RememberIn) -> str:
    return f"Retenir : « {' '.join(args.content.split())} » ({CATEGORY_LABELS[args.category]})"


async def _remember(call: ToolCall, args: RememberIn) -> dict[str, Any]:
    try:
        await _memory(call).add_fact(
            call.user_id, args.content, args.category, source_ref=call.origin
        )
    except (DuplicateFactError, FactLimitError, InvalidFactError) as error:
        raise _memory_error(error) from None
    return {"message": "Souvenir enregistré."}


# ------------------------------------------------------------------- corriger
async def _current(call: ToolCall, fact_id: uuid.UUID) -> str:
    try:
        return (await _memory(call).get_fact(call.user_id, fact_id)).content
    except FactNotFoundError as error:
        raise _memory_error(error) from None


async def _update_summary(call: ToolCall, args: UpdateIn) -> str:
    before = await _current(call, args.fact_id)
    after = " ".join(args.content.split())
    return f"Corriger un souvenir\nAvant : « {before} »\nAprès : « {after} »"


async def _update(call: ToolCall, args: UpdateIn) -> dict[str, Any]:
    try:
        await _memory(call).update(call.user_id, args.fact_id, content=args.content)
    except (DuplicateFactError, FactNotFoundError, InvalidFactError) as error:
        raise _memory_error(error) from None
    return {"message": "Souvenir corrigé."}


# -------------------------------------------------------------------- oublier
async def _forget_summary(call: ToolCall, args: ForgetIn) -> str:
    return f"Oublier : « {await _current(call, args.fact_id)} »"


async def _forget(call: ToolCall, args: ForgetIn) -> dict[str, Any]:
    try:
        await _memory(call).delete(call.user_id, args.fact_id)
    except FactNotFoundError as error:
        raise _memory_error(error) from None
    return {"message": "Souvenir oublié."}


TOOLS: Final = [
    ToolSpec(
        "assistant.search_memory",
        "Cherche dans les souvenirs confirmés de l'utilisateur (au-delà de ceux déjà fournis). "
        "Donne aussi l'identifiant d'un souvenir à corriger ou à oublier.",
        "read",
        SearchIn,
        _search,
        activity="A consulté ta mémoire",
    ),
    ToolSpec(
        "assistant.remember",
        "Propose de retenir un souvenir. Une carte s'affiche : rien n'est enregistré tant que "
        "l'utilisateur ne l'a pas confirmée.",
        "write",
        RememberIn,
        _remember,
        summary=_remember_summary,
    ),
    ToolSpec(
        "assistant.update_memory",
        "Propose de corriger un souvenir existant (identifiant obtenu par la recherche). "
        "Une carte s'affiche : rien ne change tant que l'utilisateur ne l'a pas confirmée.",
        "write",
        UpdateIn,
        _update,
        summary=_update_summary,
    ),
    ToolSpec(
        "assistant.forget_memory",
        "Propose d'oublier un souvenir (identifiant obtenu par la recherche). Une carte "
        "s'affiche : rien n'est effacé tant que l'utilisateur ne l'a pas confirmée.",
        "sensitive",
        ForgetIn,
        _forget,
        summary=_forget_summary,
    ),
]
