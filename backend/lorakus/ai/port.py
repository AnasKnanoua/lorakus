"""Port AIProvider : le contrat que tout fournisseur d'IA respecte (ADR 0006).

Le reste de Lorakus ne connait que ces types. Un adaptateur (Anthropic aujourd'hui, Gemini
ou un modele local demain) traduit ce contrat vers le SDK de son fournisseur ; changer de
fournisseur ne touche donc ni le Core ni les modules.

Le port complet prevoit aussi `structured` et `embed` : ils arrivent avec leurs premiers
utilisateurs (memoire, PR 36 et 37), pour ne pas ecrire de mecanisme sans consommateur.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Final, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

# Classes de donnees (SECURITY.md §3). Meme definition que lorakus.core.modules.manifest :
# le moteur IA est sous le Core et ne peut pas l'importer ; un test verifie l'egalite.
DataClass = Literal["public", "personal", "sensitive"]
DATA_CLASS_RANK: Final[dict[DataClass, int]] = {"public": 0, "personal": 1, "sensitive": 2}

Role = Literal["user", "assistant"]


class ChatMessage(BaseModel):
    """Un tour de conversation. Le prompt systeme est a part (ChatRequest.system)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Role
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    """Ce qu'on demande au modele, independamment du fournisseur."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    system: str = Field(min_length=1)
    messages: list[ChatMessage] = Field(min_length=1)
    max_output_tokens: int = Field(default=1024, ge=1, le=8192)


class Usage(BaseModel):
    """Tokens factures par le fournisseur pour une requete."""

    model_config = ConfigDict(frozen=True)

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cache_read_tokens: int = Field(default=0, ge=0)
    cache_write_tokens: int = Field(default=0, ge=0)

    @property
    def prompt_tokens(self) -> int:
        """Taille totale du prompt, cache compris (elle decide du palier de prix)."""
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens


@dataclass(frozen=True)
class TextDelta:
    """Morceau de texte genere, a transmettre tout de suite a l'utilisateur."""

    text: str


@dataclass(frozen=True)
class Completion:
    """Fin normale de la reponse : dernier evenement d'un flux."""

    usage: Usage
    stop_reason: str


StreamEvent = TextDelta | Completion


@dataclass(frozen=True)
class Capabilities:
    """Ce que sait faire un fournisseur. `external` : les donnees quittent le serveur."""

    external: bool
    streaming: bool = True
    tools: bool = False
    structured_output: bool = False


class ProviderError(Exception):
    """Echec d'un fournisseur, traduit depuis son SDK.

    kind : `unavailable` (panne, surcharge, delai, reseau), `rate_limited`,
    `rejected` (requete refusee : trop longue, contenu refuse) ou `misconfigured`
    (cle absente ou invalide). Le routeur passe au fournisseur suivant dans tous les cas ;
    `kind` sert aux metriques et au diagnostic.
    """

    def __init__(
        self,
        kind: Literal["unavailable", "rate_limited", "rejected", "misconfigured"],
        message: str,
    ) -> None:
        super().__init__(message)
        self.kind = kind


class AIProvider(Protocol):
    """Port implemente par chaque adaptateur de fournisseur."""

    @property
    def name(self) -> str:
        """Identifiant court, utilise dans routing.toml (ex. `anthropic`)."""
        ...

    def capabilities(self) -> Capabilities:
        """Capacites du fournisseur ; `external` decide des classes de donnees admises."""
        ...

    def chat_stream(self, model: str, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        """Genere la reponse en flux : des TextDelta, puis exactement une Completion.

        Toute erreur du fournisseur est levee sous forme de ProviderError, avant ou pendant
        le flux. Aucune nouvelle tentative ici : le routeur decide.
        """
        ...


def estimate_tokens(text: str) -> int:
    """Estimation prudente (surestimee) du nombre de tokens d'un texte.

    Environ 4 caracteres par token en francais et en anglais ; on compte 3 pour ne jamais
    sous-estimer une limite. Sert a refuser un prompt trop long AVANT de payer.
    """
    return len(text) // 3 + 1
