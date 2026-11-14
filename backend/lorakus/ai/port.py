"""Port AIProvider : le contrat que tout fournisseur d'IA respecte (ADR 0006).

Le reste de Lorakus ne connait que ces types. Un adaptateur (Anthropic aujourd'hui, Gemini
ou un modele local demain) traduit ce contrat vers le SDK de son fournisseur ; changer de
fournisseur ne touche donc ni le Core ni les modules.

Le port complet prevoit aussi `structured` et `embed` : ils arrivent avec leurs premiers
utilisateurs (memoire, PR 36 et 37), pour ne pas ecrire de mecanisme sans consommateur.

Outils (PR 38) : la requete peut decrire des outils ; le modele repond alors par du texte
et/ou des demandes d'appel (ToolUse). L'appelant execute ce qu'il autorise et renvoie les
resultats (ToolResult) dans le message suivant. Le modele ne fait jamais rien lui-meme.
"""

import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Classes de donnees (SECURITY.md §3). Meme definition que lorakus.core.modules.manifest :
# le moteur IA est sous le Core et ne peut pas l'importer ; un test verifie l'egalite.
DataClass = Literal["public", "personal", "sensitive"]
DATA_CLASS_RANK: Final[dict[DataClass, int]] = {"public": 0, "personal": 1, "sensitive": 2}

Role = Literal["user", "assistant"]


# Nom d'outil vu par un fournisseur : lettres, chiffres, souligne (contrainte commune).
WIRE_TOOL_NAME: Final = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class ToolDefinition(BaseModel):
    """Un outil propose au modele : nom, description et schema JSON de ses arguments."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=WIRE_TOOL_NAME.pattern)
    description: str = Field(min_length=1, max_length=1024)
    input_schema: dict[str, Any]


class ToolUse(BaseModel):
    """Demande d'appel faite par le modele. `input` n'est pas encore valide : a l'appelant."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=64)
    input: dict[str, Any] = Field(default_factory=dict[str, Any])


class ToolResult(BaseModel):
    """Resultat renvoye au modele pour une demande d'appel : une DONNEE, jamais une consigne."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_use_id: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1)
    is_error: bool = False


class ChatMessage(BaseModel):
    """Un tour de conversation. Le prompt systeme est a part (ChatRequest.system).

    Un message de l'assistant peut porter des demandes d'appel (tool_uses) ; le message de
    l'utilisateur qui suit porte leurs resultats (tool_results). Le texte peut alors etre vide.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Role
    content: str = ""
    tool_uses: tuple[ToolUse, ...] = ()
    tool_results: tuple[ToolResult, ...] = ()

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        if self.tool_uses and self.role != "assistant":
            raise ValueError("seul l'assistant demande des appels d'outils")
        if self.tool_results and self.role != "user":
            raise ValueError("les resultats d'outils sont dans un message utilisateur")
        if not self.content and not self.tool_uses and not self.tool_results:
            raise ValueError("message vide")
        return self


class ChatRequest(BaseModel):
    """Ce qu'on demande au modele, independamment du fournisseur.

    tool_choice : `auto` (le modele choisit), `none` (texte seulement, outils decrits pour
    comprendre l'historique : dernier tour d'une boucle d'outils).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    system: str = Field(min_length=1)
    messages: list[ChatMessage] = Field(min_length=1)
    max_output_tokens: int = Field(default=1024, ge=1, le=8192)
    tools: tuple[ToolDefinition, ...] = ()
    tool_choice: Literal["auto", "none"] = "auto"

    @model_validator(mode="after")
    def _unique_tools(self) -> Self:
        names = [t.name for t in self.tools]
        if len(names) != len(set(names)):
            raise ValueError("deux outils portent le meme nom")
        return self


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


@dataclass(frozen=True)
class ToolUseEvent:
    """Le modele demande un appel d'outil (emis quand la demande est complete)."""

    tool_use: ToolUse


StreamEvent = TextDelta | ToolUseEvent | Completion


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
        """Genere la reponse en flux : des TextDelta et ToolUseEvent, puis une Completion.

        Un fournisseur sans la capacite `tools` ne recoit jamais de requete avec des outils
        (le routeur l'ecarte).

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


def message_tokens(message: ChatMessage) -> int:
    """Estimation prudente d'un message, appels et resultats d'outils compris."""
    total = estimate_tokens(message.content) if message.content else 0
    for use in message.tool_uses:
        total += estimate_tokens(use.name + json.dumps(use.input, ensure_ascii=False)) + 10
    for result in message.tool_results:
        total += estimate_tokens(result.content) + 10
    return total


def request_tokens(request: ChatRequest) -> int:
    """Estimation prudente d'une requete entiere : prompt, messages et definitions d'outils."""
    total = estimate_tokens(request.system)
    total += sum(message_tokens(m) for m in request.messages)
    for tool in request.tools:
        schema = json.dumps(tool.input_schema, ensure_ascii=False)
        total += estimate_tokens(tool.name + tool.description + schema) + 20
    return total
