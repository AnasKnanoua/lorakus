"""Recherche hybride dans les faits confirmes (PR 37b) : plein texte + vecteurs, fusion RRF.

Deux classements complementaires :
- plein texte PostgreSQL (configuration `french`, accents retires, migration 0011) : exact
  sur les noms propres et les sigles (« METU », « Rex »), que les embeddings rendent mal ;
- vecteurs locaux (PR 37a) : retrouvent le sens sans mot commun (« chien » / « labrador »).

Fusion RRF (Reciprocal Rank Fusion) : score = somme de 1 / (60 + rang) sur les classements.
On combine des RANGS, jamais des scores bruts : les similarites cosinus d'e5 sont tassees
entre 0,80 et 0,88 (mesure en production, ADR 0007) et ne se comparent pas a un score de
plein texte. Deterministe, sans parametre a apprendre ; 60 est la valeur de reference de
l'article d'origine (Cormack et al., 2009).

La question est un texte de l'utilisateur : toujours passee en parametre lie, jamais
concatenee dans le SQL.
"""

import uuid
from collections.abc import Sequence
from typing import Final

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from lorakus.ai.embeddings import EMBEDDING_DIMENSIONS, Vector
from lorakus.db.vector import HalfVector

RRF_K: Final = 60
# Candidats retenus par chaque classement avant fusion.
CANDIDATES: Final = 30

# Mots de la question en OU : un fait n'a pas besoin de contenir tous les mots de la question
# (« Comment s'appelle mon chien ? » doit trouver « Mon chien Rex »). La pertinence ordonne.
_LEXICAL = text(
    """
    WITH query AS (
        SELECT CAST(
            replace(plainto_tsquery('french', lorakus.fold_fr(:question))::text, ' & ', ' | ')
            AS tsquery
        ) AS q
    )
    SELECT f.id
    FROM lorakus.core_memory_facts AS f, query
    WHERE f.status = 'verified'
      AND (NOT :personal_only OR f.data_class = 'personal')
      AND f.search_vector @@ query.q
    ORDER BY ts_rank_cd(f.search_vector, query.q) DESC, f.updated_at DESC, f.id
    LIMIT :limit
    """
)

# Seuls les vecteurs encore valides : meme modele, meme texte que le fait.
_VECTOR = text(
    f"""
    SELECT f.id
    FROM lorakus.core_memory_embeddings AS e
    JOIN lorakus.core_memory_facts AS f ON f.id = e.fact_id
    WHERE f.status = 'verified'
      AND (NOT :personal_only OR f.data_class = 'personal')
      AND e.model_id = :model_id
      AND e.content_hash = f.content_hash
    ORDER BY
        e.embedding OPERATOR(lorakus.<=>) CAST(:vector AS lorakus.halfvec({EMBEDDING_DIMENSIONS})),
        f.id
    LIMIT :limit
    """  # noqa: S608 - seule la dimension, une constante, est interpolee
).bindparams(bindparam("vector", type_=HalfVector(EMBEDDING_DIMENSIONS)))


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[uuid.UUID]], k: int = RRF_K
) -> list[uuid.UUID]:
    """Fusionne des classements par leurs rangs. A egalite, l'ordre d'apparition est garde."""
    scores: dict[uuid.UUID, float] = {}
    for ranking in rankings:
        for rank, fact_id in enumerate(ranking, start=1):
            scores[fact_id] = scores.get(fact_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda fact_id: -scores[fact_id])


async def lexical_ranking(
    session: AsyncSession, question: str, *, personal_only: bool, limit: int = CANDIDATES
) -> list[uuid.UUID]:
    rows = await session.scalars(
        _LEXICAL, {"question": question, "personal_only": personal_only, "limit": limit}
    )
    return list(rows)


async def vector_ranking(
    session: AsyncSession,
    vector: Vector,
    model_id: str,
    *,
    personal_only: bool,
    limit: int = CANDIDATES,
) -> list[uuid.UUID]:
    rows = await session.scalars(
        _VECTOR,
        {"vector": vector, "model_id": model_id, "personal_only": personal_only, "limit": limit},
    )
    return list(rows)
