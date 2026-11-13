"""Recherche hybride et choix des souvenirs du prompt (PR 37b), sur PostgreSQL en role app.

Faux modele d'embeddings : ces tests verifient la mecanique (budget, priorites, isolation,
repli), pas la qualite du vrai modele (tests/evals, job de la CI).
"""

import uuid

import pytest
from conftest import migrator_sql

from lorakus.ai.embeddings import FakeEmbedder
from lorakus.core.identity.service import IdentityService
from lorakus.core.memory.search import reciprocal_rank_fusion
from lorakus.core.memory.service import PROMPT_FACTS_TOKENS, MemoryService
from lorakus.db.database import Database

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

PASSWORD = "mot de passe de test assez long"
# Un fait long (pres de 300 caracteres) : une vingtaine suffit a depasser le budget du prompt.
FILLER = "Note de travail numero {n} sur l'organisation des projets, des cours et des sorties, " * 3


async def _owner(identity: IdentityService) -> uuid.UUID:
    return await identity.create_owner("a@example.com", PASSWORD)


async def _overflow(memory: MemoryService, user: uuid.UUID, count: int = 30) -> None:
    for n in range(count):
        await memory.add_fact(user, FILLER.format(n=n)[:290], "other")


async def _age(user: uuid.UUID, content: str) -> None:
    """Vieillit un fait : sans pertinence, il sortirait du budget en premier."""
    await migrator_sql(
        "UPDATE lorakus.core_memory_facts SET updated_at = now() - interval '1 year' "
        "WHERE user_id = :user AND content = :content",
        {"user": user, "content": content},
    )


def test_fusion_rewards_facts_found_by_both_methods() -> None:
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    assert reciprocal_rank_fusion([[a, b], [c, b]]) == [b, a, c]
    assert reciprocal_rank_fusion([[a], []]) == [a]
    assert reciprocal_rank_fusion([]) == []


async def test_everything_fits_so_everything_is_given(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    memory = MemoryService(database, embedder=FakeEmbedder())
    await memory.add_fact(user, "Mon chat s'appelle Mochi", "other")
    await memory.add_fact(user, "Aime le jazz", "preference")

    facts = await memory.verified_for_prompt(user, "Parle-moi de jazz")

    assert sorted(c for _, c in facts) == ["Aime le jazz", "Mon chat s'appelle Mochi"]


async def test_relevant_old_fact_wins_its_place_when_the_budget_is_full(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    memory = MemoryService(database, embedder=FakeEmbedder())
    await memory.add_fact(user, "Mon chat s'appelle Mochi", "other")
    await _age(user, "Mon chat s'appelle Mochi")
    await _overflow(memory, user)

    with_question = [c for _, c in await memory.verified_for_prompt(user, "Comment va Mochi ?")]
    without = [c for _, c in await memory.verified_for_prompt(user)]

    assert "Mon chat s'appelle Mochi" in with_question
    assert "Mon chat s'appelle Mochi" not in without
    assert len(without) < 31  # le budget coupe bien


async def test_identity_is_always_given_even_when_old(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    memory = MemoryService(database, embedder=FakeEmbedder())
    await memory.add_fact(user, "S'appelle Léa", "identity")
    await _age(user, "S'appelle Léa")
    await _overflow(memory, user)

    facts = await memory.verified_for_prompt(user, "Quel temps fait-il ?")

    assert facts[0] == ("identity", "S'appelle Léa")
    assert sum(len(c) // 4 + 4 for _, c in facts) <= PROMPT_FACTS_TOKENS + len(facts)


async def test_sensitive_facts_are_searchable_but_never_sent_to_the_model(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    memory = MemoryService(database, embedder=FakeEmbedder())
    fact = await memory.add_fact(user, "Suit un traitement pour l'asthme", "other")
    await migrator_sql(
        "UPDATE lorakus.core_memory_facts SET data_class = 'sensitive' WHERE id = :id",
        {"id": fact.id},
    )

    found = await memory.search(user, "asthme")
    prompt = await memory.verified_for_prompt(user, "J'ai de l'asthme")

    assert [f.id for f in found] == [fact.id]
    assert prompt == []


async def test_search_matches_without_accents_and_with_word_forms(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    memory = MemoryService(database)  # plein texte seul
    await memory.add_fact(user, "Étudie à l'INSA Lyon", "studies")
    await memory.add_fact(user, "Préfère les réponses courtes", "preference")

    # Accents et casse ignores. (Racines : « étudier » ne rejoint pas « étudie » dans le
    # correcteur francais de PostgreSQL ; les vecteurs couvrent ce cas.)
    assert [f.content for f in await memory.search(user, "ETUDIE")] == ["Étudie à l'INSA Lyon"]
    assert [f.content for f in await memory.search(user, "réponse")] == [
        "Préfère les réponses courtes"
    ]
    assert await memory.search(user, "   ") == []
    assert await memory.search(user, "?!") == []


async def test_search_keeps_working_when_the_model_fails(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    embedder = FakeEmbedder()
    memory = MemoryService(database, embedder=embedder)
    await memory.add_fact(user, "Joue aux échecs le soir", "habit")
    embedder.fail = True

    assert [f.content for f in await memory.search(user, "échecs")] == ["Joue aux échecs le soir"]
    assert await memory.verified_for_prompt(user, "échecs") == [
        ("habit", "Joue aux échecs le soir")
    ]


async def test_search_is_isolated_between_users(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    other = uuid.uuid4()
    await migrator_sql(
        "INSERT INTO lorakus.core_users (id, email, password_hash, role) "
        "VALUES (:id, 'b@example.com', 'x', 'user')",
        {"id": other},
    )
    memory = MemoryService(database, embedder=FakeEmbedder())
    await memory.add_fact(user, "Mon chat s'appelle Mochi", "other")

    assert await memory.search(other, "Mochi") == []
    assert await memory.verified_for_prompt(other, "Mochi") == []


async def test_injection_in_the_question_is_only_data(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    memory = MemoryService(database, embedder=FakeEmbedder())
    await memory.add_fact(user, "Aime le thé", "preference")

    for question in ["'); DROP TABLE lorakus.core_memory_facts; --", "a & | ! <-> :*", "\\x00"]:
        await memory.search(user, question)

    assert [f.content for f in await memory.search(user, "thé")] == ["Aime le thé"]
