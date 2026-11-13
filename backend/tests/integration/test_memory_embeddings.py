"""Vecteurs des faits (PR 37) sur PostgreSQL, en role lorakus_app (RLS active).

Faux modele d'embeddings (sac de mots) : ces tests verifient le stockage, la fraicheur et
l'isolation des vecteurs, pas la qualite du vrai modele (test de fumee de l'image).
"""

import hashlib
import uuid
from collections.abc import Sequence

import pytest
from conftest import migrator_sql
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from lorakus.ai.embeddings import EMBEDDING_DIMENSIONS, FakeEmbedder, Vector
from lorakus.core.identity.service import IdentityService
from lorakus.core.memory.models import MemoryEmbedding
from lorakus.core.memory.service import MemoryService, content_hash
from lorakus.db.database import Database

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

PASSWORD = "mot de passe de test assez long"


class OtherModel(FakeEmbedder):
    """Meme calcul, autre identifiant : simule un changement de modele."""

    @property
    def model_id(self) -> str:
        return "fake-bag-of-words-v2"


class EditingEmbedder(FakeEmbedder):
    """Modifie un fait pendant le calcul, comme une correction faite au meme moment."""

    def __init__(self, fact_id: uuid.UUID) -> None:
        super().__init__()
        self.fact_id = fact_id

    async def embed_passages(self, texts: Sequence[str]) -> list[Vector]:
        vectors = await super().embed_passages(texts)
        await migrator_sql(
            "UPDATE lorakus.core_memory_facts SET content = 'Texte corrige entre-temps', "
            "content_hash = :hash WHERE id = :id",
            {"hash": content_hash("Texte corrige entre-temps"), "id": self.fact_id},
        )
        return vectors


async def _two_users(identity: IdentityService) -> tuple[uuid.UUID, uuid.UUID]:
    first = await identity.create_owner("a@example.com", PASSWORD)
    second = uuid.uuid4()
    await migrator_sql(
        "INSERT INTO lorakus.core_users (id, email, password_hash, role) "
        "VALUES (:id, 'b@example.com', 'x', 'user')",
        {"id": second},
    )
    return first, second


async def _vectors(user: uuid.UUID) -> list[tuple[object, ...]]:
    """Vecteurs d'un utilisateur en base (role migrateur : tout voir pour verifier)."""
    return await migrator_sql(
        "SELECT fact_id, user_id, model_id, content_hash, embedding::text "
        "FROM lorakus.core_memory_embeddings WHERE user_id = :user ORDER BY created_at",
        {"user": user},
    )


async def _legacy_fact(user: uuid.UUID, content: str, status: str = "verified") -> uuid.UUID:
    """Fait insere sans passer par le service, comme ceux d'avant la PR 37."""
    fact_id = uuid.uuid4()
    await migrator_sql(
        "INSERT INTO lorakus.core_memory_facts (id, user_id, content, content_hash, category, "
        "status, data_class, source_kind, confirmed_at) VALUES (:id, :user, :content, :hash, "
        "'preference', :status, 'personal', 'manual', "
        "CASE WHEN :status = 'verified' THEN now() END)",
        {
            "id": fact_id,
            "user": user,
            "content": content,
            "hash": content_hash(content),
            "status": status,
        },
    )
    return fact_id


async def test_added_fact_gets_a_vector_of_the_current_model(
    database: Database, identity: IdentityService
) -> None:
    user, _ = await _two_users(identity)
    embedder = FakeEmbedder()
    memory = MemoryService(database, embedder=embedder)

    fact = await memory.add_fact(user, "Mon labrador s'appelle Rex", "identity")

    rows = await _vectors(user)
    assert len(rows) == 1
    fact_id, owner, model_id, digest, vector = rows[0]
    assert (fact_id, owner, model_id) == (fact.id, user, "fake-bag-of-words")
    assert bytes(digest) == content_hash("Mon labrador s'appelle Rex")  # type: ignore[arg-type]
    assert len(str(vector).strip("[]").split(",")) == EMBEDDING_DIMENSIONS
    assert embedder.calls == [("passages", 1)]


async def test_vectors_round_trip_through_the_orm_in_half_precision(
    database: Database, identity: IdentityService
) -> None:
    user, _ = await _two_users(identity)
    embedder = FakeEmbedder()
    memory = MemoryService(database, embedder=embedder)
    fact = await memory.add_fact(user, "Court trois fois par semaine", "habit")
    expected = (await embedder.embed_passages(["Court trois fois par semaine"]))[0]

    async with database.transaction(user) as session:
        stored = await session.scalar(
            select(MemoryEmbedding.embedding).where(MemoryEmbedding.fact_id == fact.id)
        )

    assert stored is not None
    assert stored == pytest.approx(expected, abs=1e-3)  # demi-precision


async def test_proposals_are_not_vectorized_until_confirmed(
    database: Database, identity: IdentityService
) -> None:
    user, _ = await _two_users(identity)
    memory = MemoryService(database, embedder=FakeEmbedder())
    proposal = await _legacy_fact(user, "Préfère réviser le soir", status="proposed")

    assert await memory.index_facts(user) == 0
    await memory.confirm(user, proposal)

    assert [row[0] for row in await _vectors(user)] == [proposal]


async def test_existing_facts_are_caught_up_at_the_next_message(
    database: Database, identity: IdentityService
) -> None:
    user, _ = await _two_users(identity)
    old = await _legacy_fact(user, "Étudie à METU jusqu'en décembre")
    memory = MemoryService(database, embedder=FakeEmbedder())

    facts = await memory.verified_for_prompt(user)

    assert facts == [("preference", "Étudie à METU jusqu'en décembre")]
    assert [row[0] for row in await _vectors(user)] == [old]
    assert await memory.index_facts(user) == 0  # rien a refaire


async def test_corrected_fact_gets_a_fresh_vector(
    database: Database, identity: IdentityService
) -> None:
    user, _ = await _two_users(identity)
    memory = MemoryService(database, embedder=FakeEmbedder())
    fact = await memory.add_fact(user, "Joue aux échecs le soir", "habit")
    before = (await _vectors(user))[0]

    await memory.update(user, fact.id, content="Joue aux échecs le week-end")

    after = (await _vectors(user))[0]
    assert after[0] == fact.id
    assert bytes(after[3]) == content_hash("Joue aux échecs le week-end")  # type: ignore[arg-type]
    assert after[4] != before[4]


async def test_model_change_recomputes_every_vector(
    database: Database, identity: IdentityService
) -> None:
    user, _ = await _two_users(identity)
    await MemoryService(database, embedder=FakeEmbedder()).add_fact(user, "Aime le thé", "other")

    assert await MemoryService(database, embedder=OtherModel()).index_facts(user) == 1

    assert [row[2] for row in await _vectors(user)] == ["fake-bag-of-words-v2"]


async def test_embedder_failure_never_blocks_the_users_decision(
    database: Database, identity: IdentityService
) -> None:
    user, _ = await _two_users(identity)
    embedder = FakeEmbedder()
    embedder.fail = True
    memory = MemoryService(database, embedder=embedder)

    fact = await memory.add_fact(user, "Se lève à 7 h", "habit")

    assert fact.status == "verified"
    assert await _vectors(user) == []
    embedder.fail = False
    assert await memory.index_facts(user) == 1


async def test_fact_changed_during_the_computation_is_not_written(
    database: Database, identity: IdentityService
) -> None:
    user, _ = await _two_users(identity)
    fact_id = await _legacy_fact(user, "Texte d'origine")

    assert await MemoryService(database, embedder=EditingEmbedder(fact_id)).index_facts(user) == 0
    assert await _vectors(user) == []
    # Au passage suivant, le nouveau texte est vectorise.
    assert await MemoryService(database, embedder=FakeEmbedder()).index_facts(user) == 1
    row = (await _vectors(user))[0]
    assert bytes(row[3]) == content_hash("Texte corrige entre-temps")  # type: ignore[arg-type]


async def test_deleting_or_forgetting_removes_the_vectors(
    database: Database, identity: IdentityService
) -> None:
    user, _ = await _two_users(identity)
    memory = MemoryService(database, embedder=FakeEmbedder())
    first = await memory.add_fact(user, "Aime le café", "preference")
    await memory.add_fact(user, "Habite à Ankara", "identity")
    await memory.add_fact(user, "Vit avec un chat", "other")

    await memory.delete(user, first.id)
    assert len(await _vectors(user)) == 2

    await memory.forget_all(user)
    assert await _vectors(user) == []


async def test_vectors_are_isolated_between_users(
    database: Database, identity: IdentityService
) -> None:
    first, second = await _two_users(identity)
    memory = MemoryService(database, embedder=FakeEmbedder())
    fact = await memory.add_fact(first, "Mon labrador s'appelle Rex", "identity")

    assert await memory.index_facts(second) == 0
    async with database.transaction(second) as session:
        visible = await session.scalar(text("SELECT count(*) FROM lorakus.core_memory_embeddings"))
    assert visible == 0

    # Meme en ecrivant directement, un vecteur ne peut pas viser le fait d'un autre : seule la
    # cle etrangere composee l'empeche (vecteur de A retire, aucune cle primaire en conflit).
    await migrator_sql("DELETE FROM lorakus.core_memory_embeddings")
    digest = hashlib.sha256(b"x").digest()
    with pytest.raises(IntegrityError, match="fk_core_memory_embeddings_fact_id_core_memory_facts"):
        async with database.transaction(second) as session:
            session.add(
                MemoryEmbedding(
                    fact_id=fact.id,
                    user_id=second,
                    model_id="pirate",
                    content_hash=digest,
                    embedding=(0.0,) * EMBEDDING_DIMENSIONS,
                )
            )
            await session.flush()


async def test_without_embedder_nothing_is_vectorized(
    database: Database, identity: IdentityService
) -> None:
    user, _ = await _two_users(identity)
    memory = MemoryService(database)

    await memory.add_fact(user, "Aime le café", "preference")

    assert await memory.index_facts(user) == 0
    assert await _vectors(user) == []
