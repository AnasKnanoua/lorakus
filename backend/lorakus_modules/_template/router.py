"""Routes du module Template, montees sous /api/v1/template.

Le Core ajoute lui-meme la verification de session et d'activation du module ; la
dependance current_user donne l'utilisateur, et ses donnees se lisent par une transaction
liee a lui (RLS).
"""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import insert, select

from lorakus.api.auth import current_user
from lorakus.core.identity.service import CurrentUser
from lorakus.db.database import Database
from lorakus_modules._template.models import TemplateItem

router = APIRouter()
User = Annotated[CurrentUser, Depends(current_user)]


def _database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


class ItemIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ItemOut(BaseModel):
    title: str


@router.get("/items")
async def list_items(request: Request, user: User) -> list[ItemOut]:
    async with _database(request).transaction(user.id) as session:
        titles = (await session.execute(select(TemplateItem.title))).scalars().all()
    return [ItemOut(title=title) for title in titles]


@router.post("/items", status_code=201)
async def add_item(body: ItemIn, request: Request, user: User) -> ItemOut:
    async with _database(request).transaction(user.id) as session:
        await session.execute(insert(TemplateItem).values(user_id=user.id, title=body.title))
    return ItemOut(title=body.title)
