"""Client de l'API des bots Telegram (P5, PR 54) : relever les messages, repondre.

- Releve par `getUpdates` (attente longue) depuis le worker : aucune route publique, donc
  aucune surface d'attaque entrante (decision D4). Seuls les messages sont demandes.
- Tout passe par le client sortant du Core (OutboundHttp.post : HTTPS, adresses publiques,
  aucune redirection). Le jeton est dans le chemin de l'adresse : il n'apparait jamais dans
  un journal ni dans une erreur (seul le nom d'hote est journalise).
- Les reponses de Telegram sont des donnees externes : lues par un schema strict, ce qui n'y
  correspond pas est ignore.
"""

import json
import re
from dataclasses import dataclass
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lorakus.core.outbound import FetchLimits, OutboundError, OutboundHttp

API: Final = "https://api.telegram.org"
TOKEN: Final = re.compile(r"^[0-9]{5,15}:[A-Za-z0-9_-]{30,60}$")
MAX_TEXT: Final = 4096  # limite de Telegram pour un message
BATCH: Final = 20
SEND_LIMITS: Final = FetchLimits(
    max_bytes=64 * 1024, connect_timeout_s=5.0, read_timeout_s=10.0, total_timeout_s=15.0
)

Failure = Literal["unauthorized", "conflict", "rejected", "unreadable"]


class TelegramError(Exception):
    """Refus ou reponse illisible de Telegram ; `reason` est stable (journaux, metriques).
    Jamais le jeton, jamais l'adresse."""

    def __init__(self, reason: Failure, status: int = 0) -> None:
        super().__init__(f"{reason} ({status})")
        self.reason: Failure = reason
        self.status = status


class _Strict(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class _Chat(_Strict):
    id: int
    type: str


class _From(_Strict):
    is_bot: bool = False


class _Message(_Strict):
    chat: _Chat
    text: str | None = None
    sender: _From | None = Field(default=None, alias="from")


@dataclass(frozen=True)
class Update:
    """Un message recu. `chat_id` None : ce n'etait pas un message lisible (ignore)."""

    update_id: int
    chat_id: int | None = None
    private: bool = False
    from_bot: bool = False
    text: str | None = None


class _Envelope(_Strict):
    ok: bool
    result: list[Any] = Field(default_factory=list[Any])


class _Item(_Strict):
    update_id: int
    message: Any = None


def read_updates(body: bytes) -> list[Update]:
    """Les messages d'une reponse de getUpdates ; ce qui est mal forme est ignore, mais son
    numero compte (il faut l'acquitter pour ne plus le recevoir)."""
    try:
        envelope = _Envelope.model_validate_json(body)
    except ValidationError:
        raise TelegramError("unreadable") from None
    if not envelope.ok:
        raise TelegramError("unreadable")
    updates: list[Update] = []
    for raw in envelope.result:
        try:
            item = _Item.model_validate(raw)
        except ValidationError:
            continue  # sans numero : rien a acquitter
        try:
            message = _Message.model_validate(item.message)
        except ValidationError:
            updates.append(Update(item.update_id))
            continue
        updates.append(
            Update(
                update_id=item.update_id,
                chat_id=message.chat.id,
                private=message.chat.type == "private",
                from_bot=message.sender is not None and message.sender.is_bot,
                text=message.text,
            )
        )
    return updates


class TelegramBot:
    """Le bot de Lorakus. Une instance par processus (le worker)."""

    def __init__(self, token: str, http: OutboundHttp) -> None:
        if not TOKEN.fullmatch(token):
            raise ValueError("jeton Telegram invalide (format de BotFather attendu)")
        self._base = f"{API}/bot{token}/"
        self._http = http

    async def _call(self, method: str, payload: dict[str, Any], limits: FetchLimits) -> bytes:
        try:
            result = await self._http.post(
                self._base + method,
                json.dumps(payload, ensure_ascii=False).encode(),
                [("Content-Type", "application/json")],
                limits=limits,
                keep_body=True,
            )
        except OutboundError as error:
            raise OutboundError(error.reason) from None  # sans detail : il contiendrait l'adresse
        if result.status == 401 or result.status == 404:
            raise TelegramError("unauthorized", result.status)  # jeton refuse
        if result.status == 409:
            raise TelegramError("conflict", result.status)  # webhook actif, ou autre releve
        if result.status != 200:
            raise TelegramError("rejected", result.status)
        return result.body

    async def updates(self, offset: int | None, wait_s: int) -> list[Update]:
        """Messages en attente a partir de `offset` (ceux d'avant sont acquittes), en
        attendant au plus `wait_s` secondes qu'il en arrive."""
        payload: dict[str, Any] = {
            "timeout": wait_s,
            "limit": BATCH,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            payload["offset"] = offset
        limits = FetchLimits(
            max_bytes=1024 * 1024,
            connect_timeout_s=5.0,
            read_timeout_s=wait_s + 10.0,
            total_timeout_s=wait_s + 15.0,
        )
        return read_updates(await self._call("getUpdates", payload, limits))

    async def send(self, chat_id: int, message: str) -> None:
        """Message texte brut (aucune mise en forme interpretee, aucun apercu de lien)."""
        await self._call(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": message[:MAX_TEXT],
                "link_preview_options": {"is_disabled": True},
            },
            SEND_LIMITS,
        )
