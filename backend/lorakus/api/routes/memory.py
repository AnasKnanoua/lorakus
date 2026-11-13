"""Routes de la memoire : /api/v1/memory/... (PR 36).

L'utilisateur voit, confirme, corrige, refuse et supprime ses faits. Tout passe par sa
session (RLS) ; « tout oublier » exige une re-authentification recente.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field

from lorakus.api.auth import current_user, recent_user
from lorakus.api.memory import get_memory
from lorakus.core.identity.service import CurrentUser
from lorakus.core.memory.service import (
    MAX_FACT_CHARS,
    Category,
    DuplicateFactError,
    FactLimitError,
    FactNotFoundError,
    FactView,
    InvalidFactError,
    MemoryService,
)

router = APIRouter(prefix="/v1/memory", tags=["memoire"])

User = Annotated[CurrentUser, Depends(current_user)]
RecentUser = Annotated[CurrentUser, Depends(recent_user)]
Memory = Annotated[MemoryService, Depends(get_memory)]

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Fait introuvable.")
DUPLICATE = HTTPException(
    status.HTTP_409_CONFLICT, {"code": "duplicate", "message": "Ce fait existe deja."}
)
LIMIT = HTTPException(
    status.HTTP_409_CONFLICT,
    {"code": "limit", "message": "Nombre maximal de faits atteint : supprimez-en d'abord."},
)


class FactOut(BaseModel):
    id: uuid.UUID
    content: str
    category: Category
    status: str
    source_kind: str
    evidence: str | None
    from_conversation: uuid.UUID | None
    created_at: datetime
    confirmed_at: datetime | None


class FactIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=MAX_FACT_CHARS + 50)
    category: Category


class FactEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str | None = Field(default=None, min_length=1, max_length=MAX_FACT_CHARS + 50)
    category: Category | None = None


class SettingsOut(BaseModel):
    propose_after_conversations: bool


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    propose_after_conversations: bool


class ForgetOut(BaseModel):
    deleted: int


def _conversation_of(source_ref: str | None) -> uuid.UUID | None:
    # source_ref = "conversation:<id>#<message>" : seul l'identifiant de conversation sort.
    if source_ref is None or not source_ref.startswith("conversation:"):
        return None
    try:
        return uuid.UUID(source_ref.removeprefix("conversation:").split("#", 1)[0])
    except ValueError:
        return None


def _out(fact: FactView) -> FactOut:
    return FactOut(
        id=fact.id,
        content=fact.content,
        category=fact.category,  # type: ignore[arg-type]  # garanti par la contrainte CHECK
        status=fact.status,
        source_kind=fact.source_kind,
        evidence=fact.evidence,
        from_conversation=_conversation_of(fact.source_ref),
        created_at=fact.created_at,
        confirmed_at=fact.confirmed_at,
    )


@router.get("/facts")
async def list_facts(user: User, memory: Memory) -> list[FactOut]:
    """Tous les faits : propositions en attente et faits confirmes, les plus recents d'abord."""
    return [_out(f) for f in await memory.list_facts(user.id)]


@router.get("/search")
async def search_facts(
    user: User,
    memory: Memory,
    q: Annotated[str, Query(min_length=1, max_length=200)],
) -> list[FactOut]:
    """Faits confirmes les plus proches de `q`, par les mots ET par le sens (PR 37b).

    Recherche hybride locale (plein texte et embeddings calcules sur le serveur) : la question
    ne part chez aucun fournisseur.
    """
    return [_out(f) for f in await memory.search(user.id, q)]


@router.post("/facts", status_code=status.HTTP_201_CREATED)
async def add_fact(body: FactIn, user: User, memory: Memory) -> FactOut:
    """Ajoute un fait saisi a la main (confirme d'emblee)."""
    try:
        return _out(await memory.add_fact(user.id, body.content, body.category))
    except InvalidFactError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    except DuplicateFactError:
        raise DUPLICATE from None
    except FactLimitError:
        raise LIMIT from None


@router.patch("/facts/{fact_id}")
async def update_fact(fact_id: uuid.UUID, body: FactEdit, user: User, memory: Memory) -> FactOut:
    """Corrige le texte ou la categorie d'un fait, sans changer son statut."""
    try:
        return _out(await memory.update(user.id, fact_id, body.content, body.category))
    except FactNotFoundError:
        raise NOT_FOUND from None
    except InvalidFactError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    except DuplicateFactError:
        raise DUPLICATE from None


@router.post("/facts/{fact_id}/confirm")
async def confirm_fact(
    fact_id: uuid.UUID, user: User, memory: Memory, body: FactEdit | None = None
) -> FactOut:
    """Confirme une proposition, avec une correction facultative."""
    edit = body or FactEdit()
    try:
        return _out(await memory.confirm(user.id, fact_id, edit.content, edit.category))
    except FactNotFoundError:
        raise NOT_FOUND from None
    except InvalidFactError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    except DuplicateFactError:
        raise DUPLICATE from None
    except FactLimitError:
        raise LIMIT from None


@router.post("/facts/{fact_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
async def reject_fact(fact_id: uuid.UUID, user: User, memory: Memory) -> Response:
    """Refuse une proposition : effacee, et jamais reproposee."""
    try:
        await memory.reject(user.id, fact_id)
    except FactNotFoundError:
        raise NOT_FOUND from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/facts/{fact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_fact(fact_id: uuid.UUID, user: User, memory: Memory) -> Response:
    """Supprime un fait (sans trace de son contenu)."""
    try:
        await memory.delete(user.id, fact_id)
    except FactNotFoundError:
        raise NOT_FOUND from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/forget-all")
async def forget_all(user: RecentUser, memory: Memory) -> ForgetOut:
    """Efface toute la memoire (re-authentification de moins de 10 minutes exigee)."""
    return ForgetOut(deleted=await memory.forget_all(user.id))


@router.get("/settings")
async def get_settings_route(user: User, memory: Memory) -> SettingsOut:
    return SettingsOut(propose_after_conversations=await memory.proposals_enabled(user.id))


@router.put("/settings")
async def put_settings(body: SettingsIn, user: User, memory: Memory) -> SettingsOut:
    await memory.set_proposals_enabled(user.id, body.propose_after_conversations)
    return SettingsOut(propose_after_conversations=body.propose_after_conversations)
