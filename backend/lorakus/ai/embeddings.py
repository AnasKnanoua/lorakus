"""Embeddings : port, erreurs et faux modele (PR 37, ADR 0007).

Un embedding est un vecteur de nombres qui represente le sens d'un texte : deux textes
proches ont des vecteurs proches. Il sert a retrouver les souvenirs pertinents pour un
message, meme sans mot en commun (« mon chien » / « Rex, mon labrador »).

Les embeddings des donnees personnelles sont calcules LOCALEMENT, dans le processus de
l'API : aucun texte ne sort du serveur pour etre vectorise. Ils ne passent donc ni par le
ModelRouter (budget, rythme, fournisseurs externes) ni par un SDK.

Les modeles de type e5 distinguent la question (`query`) du texte cherche (`passage`) :
le port expose les deux usages, chaque adaptateur fait le reste (prefixes, troncature).
"""

import hashlib
import math
import re
import unicodedata
from collections.abc import Sequence
from typing import Final, Protocol

Vector = tuple[float, ...]

# Dimension des vecteurs en base (colonne halfvec(384), migration 0010). Un modele d'une
# autre dimension demande une migration : il ne peut pas etre branche par simple reglage.
EMBEDDING_DIMENSIONS: Final = 384


class EmbeddingError(Exception):
    """Le modele n'a pas pu calculer un embedding (fichier absent, entree refusee...)."""


class Embedder(Protocol):
    """Modele d'embeddings local."""

    @property
    def model_id(self) -> str:
        """Identifiant du modele ET de ses fichiers : change si les fichiers changent.

        Enregistre a cote de chaque vecteur : un vecteur d'un autre modele est recalcule.
        """
        ...

    @property
    def dimensions(self) -> int:
        """Nombre de composantes des vecteurs produits."""
        ...

    async def embed_query(self, text: str) -> Vector:
        """Vecteur normalise d'une question (ce que l'on cherche)."""
        ...

    async def embed_passages(self, texts: Sequence[str]) -> list[Vector]:
        """Vecteurs normalises de textes a retrouver, dans l'ordre recu."""
        ...


def cosine(a: Vector, b: Vector) -> float:
    """Similarite cosinus de deux vecteurs (produit scalaire s'ils sont normalises)."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


_WORD = re.compile(r"\w+", re.UNICODE)


def _words(text: str) -> list[str]:
    plain = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return _WORD.findall(plain)


class FakeEmbedder:
    """Faux modele deterministe : tests et developpement sans fichiers de modele.

    Sac de mots hache dans 384 dimensions : deux textes qui partagent des mots ont des
    vecteurs proches. Aucune comprehension du sens ; jamais en staging ni en production
    (lorakus.ai.providers.build_embedder).
    """

    def __init__(self, dimensions: int = EMBEDDING_DIMENSIONS) -> None:
        self._dimensions = dimensions
        self.calls: list[tuple[str, int]] = []
        self.fail: bool = False

    @property
    def model_id(self) -> str:
        return "fake-bag-of-words"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def _vector(self, text: str) -> Vector:
        values = [0.0] * self._dimensions
        for word in _words(text):
            digest = hashlib.blake2b(word.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self._dimensions
            values[index] += 1.0 if digest[4] % 2 == 0 else -1.0
        norm = math.sqrt(sum(v * v for v in values))
        if norm == 0:
            # Texte sans mot : vecteur fixe plutot qu'un vecteur nul (cosinus indefini).
            values[0] = 1.0
            norm = 1.0
        return tuple(v / norm for v in values)

    async def embed_query(self, text: str) -> Vector:
        self.calls.append(("query", 1))
        if self.fail:
            raise EmbeddingError("panne simulee")
        return self._vector(text)

    async def embed_passages(self, texts: Sequence[str]) -> list[Vector]:
        self.calls.append(("passages", len(texts)))
        if self.fail:
            raise EmbeddingError("panne simulee")
        return [self._vector(t) for t in texts]
