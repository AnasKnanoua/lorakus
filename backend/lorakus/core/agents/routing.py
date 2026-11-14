"""Routage des questions vers les specialistes (ADR 0025, PR 39), sans appel a un LLM.

- Palier 1, regles : mots-cles declares par chaque intention (profil du specialiste). Une
  question peut toucher plusieurs specialistes ; chacun recoit son intention.
- Palier 2, sens : la question est comparee aux phrases d'exemple de chaque intention avec
  le modele d'embeddings LOCAL (rien ne sort du serveur), et a des phrases « sans
  specialiste » (bavardage, culture generale, memoire...). Le modele donne des similarites
  tassees (0,80 a 0,88 mesures en PR 37a) : aucun seuil absolu n'est fiable. On retient donc
  la meilleure intention seulement si elle devance de `margin` a la fois la meilleure autre
  intention et la classe « sans specialiste ».
- Palier 3 (petit appel LLM quand c'est ambigu) : reporte a la P4, faute de vrais
  specialistes a departager (decision du 2026-11-14). Une question ambigue ne consulte
  personne : le Majordome repond avec ce qu'il a.

La marge se regle sur le jeu de REGLAGE de tests/evals/intent_routing.json, jamais sur
celui de mesure.
"""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final, Literal

import structlog

from lorakus.ai.embeddings import Embedder, EmbeddingError, Vector, cosine
from lorakus.core.agents.contract import SpecialistProfile
from lorakus.core.agents.orchestrator import Target

log = structlog.get_logger("lorakus.agents")

# Marge entre la meilleure intention et la suivante (ou « sans specialiste »). Choisie sur le
# jeu de REGLAGE avec le vrai modele (CI, 2026-11-14) : 0 donne 80 % de bonnes decisions,
# toute marge positive fait baisser le score (0,03 : 35 %). Les ecarts entre intentions sont
# trop petits avec ce modele (0,001 a 0,02) pour qu'une marge aide. La classe « sans
# specialiste » reste le seul filtre des questions hors sujet.
DEFAULT_MARGIN: Final = 0.0
NONE: Final = "_none"

# Classe « sans specialiste » : ce qui ne demande les donnees d'aucun specialiste.
NONE_EXAMPLES: Final = (
    "Bonjour, comment ça va ?",
    "Merci beaucoup",
    "Raconte-moi une blague",
    "Explique-moi ce qu'est un réseau de neurones",
    "Écris un mail pour mon professeur",
    "Traduis cette phrase en anglais",
    "Retiens que je préfère réviser le matin",
    "Qu'est-ce que tu sais de moi ?",
    "Corrige le code Python suivant",
    "Quelle est la capitale du Japon ?",
)

Tier = Literal["rules", "embeddings", "none"]


@dataclass(frozen=True)
class Routing:
    """Decision de routage, avec de quoi l'expliquer (trace « Pourquoi ? »)."""

    targets: tuple[Target, ...]
    tier: Tier
    best: str | None = None  # "specialiste.intention" ou NONE
    score: float | None = None
    runner_up: float | None = None
    reason: str = ""


def fold(text: str) -> str:
    """Minuscules, sans accents, espaces reduits : base des regles de mots-cles."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w']+", " ", plain).split())


def _contains(text: str, phrase: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(fold(phrase))}(?!\w)", text) is not None


@dataclass
class IntentRouter:
    embedder: Embedder | None = None
    margin: float = DEFAULT_MARGIN
    # Vecteurs des exemples, calcules une fois par modele et par phrase.
    _vectors: dict[tuple[str, str], Vector] = field(default_factory=dict[tuple[str, str], Vector])

    async def route(self, question: str, profiles: Sequence[SpecialistProfile]) -> Routing:
        """Specialistes a consulter pour cette question (aucun si rien ne s'impose)."""
        if not profiles or not question.strip():
            return Routing((), "none", reason="aucun specialiste actif")
        by_rules = self._rules(question, profiles)
        if by_rules:
            return Routing(tuple(by_rules), "rules", reason="mots-cles")
        return await self._meaning(question, profiles)

    # ----------------------------------------------------------------- palier 1
    @staticmethod
    def _rules(question: str, profiles: Sequence[SpecialistProfile]) -> list[Target]:
        text = fold(question)
        targets: list[Target] = []
        for profile in profiles:
            for intent in profile.intents:  # ordre du profil : la premiere intention gagne
                if any(_contains(text, k) for k in profile.keywords.get(intent, [])):
                    targets.append(Target(profile.name, intent))
                    break
        return targets

    # ----------------------------------------------------------------- palier 2
    async def _meaning(self, question: str, profiles: Sequence[SpecialistProfile]) -> Routing:
        candidates = {
            f"{p.name}.{intent}": phrases
            for p in profiles
            for intent, phrases in p.examples.items()
        }
        embedder = self.embedder
        if embedder is None or not candidates:
            return Routing((), "none", reason="pas d'exemple a comparer")
        try:
            asked = await embedder.embed_query(question)
            scores = {
                label: await self._best(embedder, asked, phrases)
                for label, phrases in candidates.items()
            }
            none_score = await self._best(embedder, asked, NONE_EXAMPLES)
        except EmbeddingError as error:
            log.warning("routing_embedding_failed", error=type(error).__name__)
            return Routing((), "none", reason="modele d'embeddings indisponible")

        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        best_label, best = ranked[0]
        rivals = [score for _, score in ranked[1:]] + [none_score]
        runner_up = max(rivals)
        if none_score >= best:
            return Routing((), "none", NONE, round(none_score, 4), round(best, 4), "hors sujet")
        if best - runner_up < self.margin:
            return Routing((), "none", best_label, round(best, 4), round(runner_up, 4), "ambigu")
        specialist, intent = best_label.split(".", 1)
        return Routing(
            (Target(specialist, intent),),
            "embeddings",
            best_label,
            round(best, 4),
            round(runner_up, 4),
            "sens",
        )

    async def _best(self, embedder: Embedder, asked: Vector, phrases: Sequence[str]) -> float:
        best = -1.0
        for phrase in phrases:
            best = max(best, cosine(asked, await self._vector(embedder, phrase)))
        return best

    async def _vector(self, embedder: Embedder, phrase: str) -> Vector:
        key = (embedder.model_id, phrase)
        if key not in self._vectors:
            # Meme prefixe que la question : comparaison symetrique (phrase contre phrase).
            self._vectors[key] = await embedder.embed_query(phrase)
        return self._vectors[key]
