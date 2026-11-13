"""Memoire de l'utilisateur : faits proposes, confirmes par lui, puis utilises (PR 36).

Regle de base : rien n'est retenu sans l'accord de l'utilisateur. Une conversation ne cree que
des propositions ; seul l'utilisateur confirme, corrige, refuse ou supprime. Garde-fous des
propositions, tous deterministes (aucun ne depend du modele) :

- seuls les messages de l'utilisateur servent de source, jamais les reponses de l'assistant ;
- chaque fait propose cite un extrait de son message, verifie mot pour mot ici ;
- un fait refuse n'est jamais repropose (empreinte gardee, texte efface) ;
- plafonds : 5 propositions par analyse, 20 en attente, 200 faits confirmes.

Un fait `sensitive` n'est jamais remis a un fournisseur externe (verified_for_prompt).
Le journal d'audit note chaque decision avec l'identifiant du fait, jamais son contenu.

Vecteurs (PR 37) : chaque fait confirme recoit un embedding calcule localement, apres sa
confirmation ou sa correction ; les faits sans vecteur valide (anciens faits, modele change,
calcul echoue) sont rattrapes au message suivant. La vectorisation ne fait jamais echouer une
decision de l'utilisateur : en cas d'erreur, elle est simplement refaite plus tard.
"""

import hashlib
import unicodedata
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal, get_args

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, insert, or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from lorakus.ai.embeddings import Embedder, EmbeddingError
from lorakus.ai.port import ChatMessage, ChatRequest, estimate_tokens
from lorakus.ai.router import AIRefusedError, AIUnavailableError, ModelRouter
from lorakus.ai.structured import StructuredOutputError, complete_structured
from lorakus.core.identity.service import audit
from lorakus.core.memory.models import (
    MemoryEmbedding,
    MemoryFact,
    MemoryRejection,
    MemorySettings,
)
from lorakus.core.memory.prompts import EXTRACT_PROMPT_VERSION, EXTRACT_SYSTEM
from lorakus.db.database import Database
from lorakus.observability.metrics import MEMORY_EMBEDDINGS, MEMORY_PROPOSALS

log = structlog.get_logger("lorakus.memory")

Category = Literal["identity", "preference", "project", "habit", "studies", "other"]
Status = Literal["proposed", "verified", "inferred"]
CATEGORIES: Final[frozenset[str]] = frozenset(get_args(Category))

MAX_FACT_CHARS: Final = 300
MAX_EVIDENCE_CHARS: Final = 300
MAX_PROPOSALS_PER_RUN: Final = 5
MAX_PENDING: Final = 20
MAX_VERIFIED: Final = 200
# Taille du bloc de faits ajoute au prompt systeme de l'assistant.
PROMPT_FACTS_MAX: Final = 60
PROMPT_FACTS_TOKENS: Final = 1500
EXTRACT_TASK: Final = "memory.extract"
# Faits vectorises au plus par passage : borne le temps d'un rattrapage (un message).
EMBED_BATCH_MAX: Final = 64


class InvalidFactError(ValueError):
    """Texte de fait refuse (vide, trop long, sur plusieurs lignes, caracteres de controle)."""


class FactNotFoundError(Exception):
    """Fait absent, ou appartenant a un autre utilisateur (la RLS les confond)."""


class FactLimitError(Exception):
    """Plafond de faits confirmes atteint."""


class DuplicateFactError(Exception):
    """Un fait de meme texte existe deja."""


def normalize(text: str) -> str:
    """Espaces regroupes, forme Unicode canonique : deux ecritures du meme texte se confondent."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def content_hash(text: str) -> bytes:
    """Empreinte du texte normalise, sans casse ni ponctuation finale."""
    key = normalize(text).casefold().rstrip(" .!?;")
    return hashlib.sha256(key.encode()).digest()


def clean_content(text: str) -> str:
    """Texte d'un fait pret a enregistrer : une ligne, 1 a 300 caracteres, sans controle."""
    if any(unicodedata.category(c) == "Cc" and c not in "\n\r\t" for c in text):
        raise InvalidFactError("caracteres de controle interdits")
    if "\n" in text.strip() or "\r" in text.strip():
        raise InvalidFactError("un fait tient sur une ligne")
    value = normalize(text)
    if not value:
        raise InvalidFactError("fait vide")
    if len(value) > MAX_FACT_CHARS:
        raise InvalidFactError(f"{MAX_FACT_CHARS} caracteres au plus")
    return value


@dataclass(frozen=True)
class SourceMessage:
    """Message de l'utilisateur soumis a l'analyse (jamais une reponse de l'assistant)."""

    id: uuid.UUID
    text: str


@dataclass(frozen=True)
class FactView:
    id: uuid.UUID
    content: str
    category: str
    status: str
    source_kind: str
    source_ref: str | None
    evidence: str | None
    created_at: datetime
    confirmed_at: datetime | None


@dataclass(frozen=True)
class ProposalOutcome:
    proposed: int
    reason: str  # ok, disabled, pending_full, ai_unavailable, ai_refused, invalid_output, empty


# ------------------------------------------------------------------ extraction
class _ExtractedFact(BaseModel):
    message: int = Field(ge=1)
    evidence: str = Field(min_length=1, max_length=MAX_EVIDENCE_CHARS)
    content: str = Field(min_length=1, max_length=MAX_FACT_CHARS)
    category: Category


class _Extraction(BaseModel):
    facts: list[_ExtractedFact] = Field(default_factory=list[_ExtractedFact], max_length=20)


def _evidence_found(evidence: str, message: str) -> bool:
    """Extrait present mot pour mot (espaces et casse ignores) dans le message cite."""
    return normalize(evidence).casefold() in normalize(message).casefold()


def _view(fact: MemoryFact) -> FactView:
    return FactView(
        id=fact.id,
        content=fact.content,
        category=fact.category,
        status=fact.status,
        source_kind=fact.source_kind,
        source_ref=fact.source_ref,
        evidence=fact.evidence,
        created_at=fact.created_at,
        confirmed_at=fact.confirmed_at,
    )


class MemoryService:
    """Faits de l'utilisateur. Une instance par application."""

    def __init__(
        self,
        database: Database,
        ai: ModelRouter | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self._db = database
        self._ai = ai
        self._embedder = embedder

    # ------------------------------------------------------------------ lecture
    async def list_facts(self, user_id: uuid.UUID) -> list[FactView]:
        async with self._db.transaction(user_id) as session:
            rows = await session.scalars(
                select(MemoryFact).order_by(MemoryFact.updated_at.desc(), MemoryFact.id)
            )
            return [_view(f) for f in rows]

    async def verified_for_prompt(self, user_id: uuid.UUID) -> list[tuple[str, str]]:
        """(categorie, texte) des faits confirmes a donner au modele, du plus recent au plus ancien.

        Jamais `sensitive` : le seul fournisseur des conversations est externe. Taille bornee.
        Rattrape d'abord les faits sans vecteur (appele a chaque message de l'assistant).
        """
        await self._index_quietly(user_id)
        async with self._db.transaction(user_id) as session:
            rows = await session.execute(
                select(MemoryFact.category, MemoryFact.content)
                .where(MemoryFact.status == "verified", MemoryFact.data_class == "personal")
                .order_by(MemoryFact.updated_at.desc(), MemoryFact.id)
                .limit(PROMPT_FACTS_MAX)
            )
            facts: list[tuple[str, str]] = []
            used = 0
            for category, content in rows:
                cost = estimate_tokens(content) + 4
                if used + cost > PROMPT_FACTS_TOKENS:
                    break
                facts.append((category, content))
                used += cost
            return facts

    async def proposals_enabled(self, user_id: uuid.UUID) -> bool:
        async with self._db.transaction(user_id) as session:
            value = await session.scalar(
                select(MemorySettings.propose_after_conversations).where(
                    MemorySettings.user_id == user_id
                )
            )
        return True if value is None else value

    async def set_proposals_enabled(self, user_id: uuid.UUID, enabled: bool) -> None:
        async with self._db.transaction(user_id) as session:
            statement = pg_insert(MemorySettings).values(
                user_id=user_id, propose_after_conversations=enabled
            )
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[MemorySettings.user_id],
                    set_={"propose_after_conversations": enabled, "updated_at": func.now()},
                )
            )
            await audit(
                session, user_id, "memory.settings_update", "success", None, {"propose": enabled}
            )

    # ------------------------------------------------------------- decisions
    async def add_fact(self, user_id: uuid.UUID, content: str, category: Category) -> FactView:
        """Fait saisi par l'utilisateur lui-meme : confirme d'emblee."""
        text = clean_content(content)
        async with self._db.transaction(user_id) as session:
            await self._check_verified_room(session)
            fact = MemoryFact(
                id=uuid.uuid4(),
                user_id=user_id,
                content=text,
                content_hash=content_hash(text),
                category=category,
                status="verified",
                data_class="personal",
                source_kind="manual",
                confirmed_at=func.now(),
            )
            if await self._hash_exists(session, fact.content_hash):
                raise DuplicateFactError
            session.add(fact)
            await session.flush()
            await session.refresh(fact)
            await audit(
                session, user_id, "memory.fact_add", "success", None, {"fact_id": str(fact.id)}
            )
            view = _view(fact)
        await self._index_quietly(user_id)
        return view

    async def confirm(
        self,
        user_id: uuid.UUID,
        fact_id: uuid.UUID,
        content: str | None = None,
        category: Category | None = None,
    ) -> FactView:
        """Confirme une proposition, eventuellement corrigee avant."""
        async with self._db.transaction(user_id) as session:
            fact = await self._get(session, fact_id)
            if fact.status != "verified":
                await self._check_verified_room(session)
            await self._apply_edit(session, fact, content, category)
            if fact.status != "verified":
                fact.status = "verified"
                fact.confirmed_at = func.now()  # type: ignore[assignment]
            fact.updated_at = func.now()  # type: ignore[assignment]
            await session.flush()
            await session.refresh(fact)
            await audit(
                session, user_id, "memory.fact_confirm", "success", None, {"fact_id": str(fact_id)}
            )
            view = _view(fact)
        await self._index_quietly(user_id)
        return view

    async def update(
        self,
        user_id: uuid.UUID,
        fact_id: uuid.UUID,
        content: str | None = None,
        category: Category | None = None,
    ) -> FactView:
        """Corrige un fait sans changer son statut."""
        async with self._db.transaction(user_id) as session:
            fact = await self._get(session, fact_id)
            await self._apply_edit(session, fact, content, category)
            fact.updated_at = func.now()  # type: ignore[assignment]
            await session.flush()
            await session.refresh(fact)
            await audit(
                session, user_id, "memory.fact_update", "success", None, {"fact_id": str(fact_id)}
            )
            view = _view(fact)
        await self._index_quietly(user_id)
        return view

    async def reject(self, user_id: uuid.UUID, fact_id: uuid.UUID) -> None:
        """Refuse une proposition : effacee, et son empreinte empeche de la reproposer."""
        async with self._db.transaction(user_id) as session:
            fact = await self._get(session, fact_id)
            await session.execute(
                pg_insert(MemoryRejection)
                .values(user_id=user_id, content_hash=fact.content_hash)
                .on_conflict_do_nothing()
            )
            await session.execute(delete(MemoryFact).where(MemoryFact.id == fact_id))
            await audit(
                session, user_id, "memory.fact_reject", "success", None, {"fact_id": str(fact_id)}
            )

    async def delete(self, user_id: uuid.UUID, fact_id: uuid.UUID) -> None:
        """Supprime un fait, sans trace de son contenu."""
        async with self._db.transaction(user_id) as session:
            result = await session.execute(
                delete(MemoryFact).where(MemoryFact.id == fact_id).returning(MemoryFact.id)
            )
            if result.first() is None:
                raise FactNotFoundError
            await audit(
                session, user_id, "memory.fact_delete", "success", None, {"fact_id": str(fact_id)}
            )

    async def forget_all(self, user_id: uuid.UUID) -> int:
        """Efface tous les faits et toutes les empreintes de refus de l'utilisateur."""
        async with self._db.transaction(user_id) as session:
            result = await session.execute(delete(MemoryFact).returning(MemoryFact.id))
            count = len(result.all())
            await session.execute(delete(MemoryRejection))
            await audit(session, user_id, "memory.forget_all", "success", None, {"facts": count})
            return count

    # ------------------------------------------------------------ propositions
    async def propose_from_messages(
        self,
        user_id: uuid.UUID,
        *,
        source_ref: str,
        messages: Sequence[SourceMessage],
    ) -> ProposalOutcome:
        """Analyse des messages de l'utilisateur et enregistre des propositions (jamais plus).

        Ne leve rien pour un refus du moteur IA ou une reponse invalide : l'analyse est
        simplement sautee (la prochaine conversation la refera). Les messages vides sont ignores.
        """
        sources = [m for m in messages if m.text.strip()]
        if not sources:
            return self._outcome(0, "empty")
        if self._ai is None:
            return self._outcome(0, "ai_unavailable")
        if not await self.proposals_enabled(user_id):
            return self._outcome(0, "disabled")

        async with self._db.transaction(user_id) as session:
            pending = await self._count(session, "proposed")
            known = list(
                await session.scalars(
                    select(MemoryFact.content)
                    .where(MemoryFact.data_class == "personal")
                    .order_by(MemoryFact.updated_at.desc())
                    .limit(PROMPT_FACTS_MAX)
                )
            )
        room = min(MAX_PROPOSALS_PER_RUN, MAX_PENDING - pending)
        if room <= 0:
            return self._outcome(0, "pending_full")

        numbered = "\n".join(f"[{i}] {m.text}" for i, m in enumerate(sources, start=1))
        known_block = "\n".join(f"- {k}" for k in known) or "(aucun)"
        request = ChatRequest(
            system=EXTRACT_SYSTEM,
            messages=[
                ChatMessage(
                    role="user",
                    content=(
                        f"Faits déjà connus :\n{known_block}\n\n<messages>\n{numbered}\n</messages>"
                    ),
                )
            ],
            max_output_tokens=600,
        )
        try:
            extraction, _ = await complete_structured(
                self._ai,
                user_id,
                task=EXTRACT_TASK,
                data_class="personal",
                request=request,
                schema=_Extraction,
            )
        except AIUnavailableError as error:
            log.info("memory_extract_skipped", reason=error.reason)
            return self._outcome(0, "ai_unavailable")
        except AIRefusedError as error:
            log.info("memory_extract_refused", reason=error.reason)
            return self._outcome(0, "ai_refused")
        except StructuredOutputError as error:
            log.warning("memory_extract_invalid", detail=str(error))
            return self._outcome(0, "invalid_output")

        return await self._store_proposals(user_id, source_ref, sources, extraction, room)

    async def _store_proposals(
        self,
        user_id: uuid.UUID,
        source_ref: str,
        sources: Sequence[SourceMessage],
        extraction: _Extraction,
        room: int,
    ) -> ProposalOutcome:
        stored = 0
        async with self._db.transaction(user_id) as session:
            rejected = set(await session.scalars(select(MemoryRejection.content_hash)))
            existing = set(await session.scalars(select(MemoryFact.content_hash)))
            for item in extraction.facts:
                if stored >= room:
                    break
                if item.message > len(sources):
                    MEMORY_PROPOSALS.labels(outcome="bad_reference").inc()
                    continue
                source = sources[item.message - 1]
                if not _evidence_found(item.evidence, source.text):
                    # Le modele cite un passage qui n'existe pas : invention probable.
                    MEMORY_PROPOSALS.labels(outcome="no_evidence").inc()
                    continue
                try:
                    text = clean_content(item.content)
                except InvalidFactError:
                    MEMORY_PROPOSALS.labels(outcome="invalid").inc()
                    continue
                digest = content_hash(text)
                if digest in rejected or digest in existing:
                    MEMORY_PROPOSALS.labels(outcome="duplicate").inc()
                    continue
                existing.add(digest)
                await session.execute(
                    insert(MemoryFact).values(
                        id=uuid.uuid4(),
                        user_id=user_id,
                        content=text,
                        content_hash=digest,
                        category=item.category,
                        status="proposed",
                        data_class="personal",
                        source_kind="conversation",
                        source_ref=f"{source_ref}#{source.id}",
                        evidence=normalize(item.evidence),
                    )
                )
                stored += 1
            if stored:
                await audit(
                    session,
                    user_id,
                    "memory.facts_proposed",
                    "success",
                    None,
                    {"count": stored, "prompt_version": EXTRACT_PROMPT_VERSION},
                )
        return self._outcome(stored, "ok")

    # ---------------------------------------------------------------- vecteurs
    async def index_facts(self, user_id: uuid.UUID) -> int:
        """Vectorise les faits confirmes sans vecteur valide. Renvoie le nombre de vecteurs ecrits.

        Valide = meme modele et meme texte. Le calcul se fait hors transaction (aucun verrou
        tenu pendant l'inference) ; a l'ecriture, un fait corrige ou supprime entre-temps est
        ignore, il sera repris au passage suivant. Leve SQLAlchemyError, jamais EmbeddingError.
        """
        if self._embedder is None:
            return 0
        model_id = self._embedder.model_id
        async with self._db.transaction(user_id) as session:
            rows = (
                await session.execute(
                    select(MemoryFact.id, MemoryFact.content, MemoryFact.content_hash)
                    .outerjoin(MemoryEmbedding, MemoryEmbedding.fact_id == MemoryFact.id)
                    .where(
                        MemoryFact.status == "verified",
                        or_(
                            MemoryEmbedding.fact_id.is_(None),
                            MemoryEmbedding.model_id != model_id,
                            MemoryEmbedding.content_hash != MemoryFact.content_hash,
                        ),
                    )
                    .order_by(MemoryFact.updated_at.desc(), MemoryFact.id)
                    .limit(EMBED_BATCH_MAX)
                )
            ).all()
        if not rows:
            return 0
        try:
            vectors = await self._embedder.embed_passages([content for _, content, _ in rows])
        except EmbeddingError as error:
            log.warning("memory_embedding_failed", detail=str(error), facts=len(rows))
            MEMORY_EMBEDDINGS.labels(outcome="failed").inc(len(rows))
            return 0

        async with self._db.transaction(user_id) as session:
            # Verrou partage : un fait ne peut pas etre supprime pendant l'ecriture de son vecteur.
            unchanged = set(
                await session.scalars(
                    select(MemoryFact.id)
                    .where(
                        MemoryFact.status == "verified",
                        tuple_(MemoryFact.id, MemoryFact.content_hash).in_(
                            [(fact_id, digest) for fact_id, _, digest in rows]
                        ),
                    )
                    .with_for_update(read=True)
                )
            )
            indexed = 0
            for (fact_id, _, digest), vector in zip(rows, vectors, strict=True):
                if fact_id not in unchanged:
                    MEMORY_EMBEDDINGS.labels(outcome="stale_skipped").inc()
                    continue
                statement = pg_insert(MemoryEmbedding).values(
                    fact_id=fact_id,
                    user_id=user_id,
                    model_id=model_id,
                    content_hash=digest,
                    embedding=vector,
                )
                await session.execute(
                    statement.on_conflict_do_update(
                        index_elements=[MemoryEmbedding.fact_id],
                        set_={
                            "model_id": statement.excluded.model_id,
                            "content_hash": statement.excluded.content_hash,
                            "embedding": statement.excluded.embedding,
                            "created_at": func.now(),
                        },
                    )
                )
                indexed += 1
        if indexed:
            MEMORY_EMBEDDINGS.labels(outcome="indexed").inc(indexed)
        return indexed

    async def _index_quietly(self, user_id: uuid.UUID) -> None:
        """Vectorisation apres une decision : une erreur ne doit pas annuler la decision."""
        try:
            await self.index_facts(user_id)
        except SQLAlchemyError:
            log.warning("memory_embedding_store_failed", exc_info=True)

    # ------------------------------------------------------------------ interne
    @staticmethod
    def _outcome(proposed: int, reason: str) -> ProposalOutcome:
        if proposed:
            MEMORY_PROPOSALS.labels(outcome="proposed").inc(proposed)
        elif reason != "ok":
            MEMORY_PROPOSALS.labels(outcome=reason).inc()
        return ProposalOutcome(proposed, reason)

    @staticmethod
    async def _get(session: AsyncSession, fact_id: uuid.UUID) -> MemoryFact:
        fact = await session.get(MemoryFact, fact_id, with_for_update=True)
        if fact is None:
            raise FactNotFoundError
        return fact

    @staticmethod
    async def _count(session: AsyncSession, status: Status) -> int:
        return (
            await session.scalar(
                select(func.count()).select_from(MemoryFact).where(MemoryFact.status == status)
            )
            or 0
        )

    async def _check_verified_room(self, session: AsyncSession) -> None:
        if await self._count(session, "verified") >= MAX_VERIFIED:
            raise FactLimitError

    @staticmethod
    async def _hash_exists(session: AsyncSession, digest: bytes) -> bool:
        found = await session.scalar(
            select(MemoryFact.id).where(MemoryFact.content_hash == digest).limit(1)
        )
        return found is not None

    async def _apply_edit(
        self,
        session: AsyncSession,
        fact: MemoryFact,
        content: str | None,
        category: Category | None,
    ) -> None:
        if content is not None:
            text = clean_content(content)
            digest = content_hash(text)
            if digest != fact.content_hash:
                if await self._hash_exists(session, digest):
                    raise DuplicateFactError
                fact.content = text
                fact.content_hash = digest
        if category is not None:
            fact.category = category
