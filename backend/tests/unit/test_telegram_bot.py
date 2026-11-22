"""Client du bot Telegram (PR 54) : lecture stricte des reponses, erreurs sans jeton, codes."""

import json
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from structlog.testing import capture_logs

from lorakus.core.outbound import OutboundError, OutboundHttp, PostResult
from lorakus.core.telegram.bot import TOKEN, TelegramBot, TelegramError, Update, read_updates
from lorakus.core.telegram.inbox import CODE, MAX_CODE_ATTEMPTS, Attempts, PollState, poll_round
from lorakus.core.telegram.service import ALPHABET, code_hash, display

CANARY = "123456789:CANARYxSECRETxTOKENxNEVERxLOGGEDx1"


def private(update_id: int, text: str | None, chat: int = 42, **extra: Any) -> dict[str, Any]:
    message: dict[str, Any] = {
        "message_id": 7,
        "chat": {"id": chat, "type": "private"},
        "from": {"id": chat, "is_bot": False},
    }
    if text is not None:
        message["text"] = text
    message.update(extra)
    return {"update_id": update_id, "message": message}


def body(*items: Any, ok: bool = True) -> bytes:
    return json.dumps({"ok": ok, "result": list(items)}).encode()


def test_private_text_messages_are_read() -> None:
    assert read_updates(body(private(10, "Une idée"))) == [
        Update(10, chat_id=42, private=True, from_bot=False, text="Une idée")
    ]


def test_everything_else_is_kept_only_to_be_acknowledged() -> None:
    group = {"update_id": 11, "message": {"chat": {"id": -5, "type": "group"}, "text": "x"}}
    bot = private(12, "x")
    bot["message"]["from"]["is_bot"] = True
    photo = private(13, None, photo=[{"file_id": "a"}])
    edited = {"update_id": 14, "edited_message": {"chat": {"id": 42, "type": "private"}}}
    broken = {"update_id": 15, "message": {"chat": "pas un objet"}}
    nonsense = {"pas": "un update"}
    updates = read_updates(body(group, bot, photo, edited, broken, nonsense))
    assert [u.update_id for u in updates] == [11, 12, 13, 14, 15]
    assert (updates[0].private, updates[1].from_bot, updates[2].text) == (False, True, None)
    assert updates[3] == Update(14) and updates[4] == Update(15)


@pytest.mark.parametrize(
    "raw", [b"pas du json", b"[]", body(ok=False), b'{"ok": true, "result": "x"}', b"{}"]
)
def test_an_unreadable_answer_is_an_error(raw: bytes) -> None:
    with pytest.raises(TelegramError) as error:
        read_updates(raw)
    assert error.value.reason == "unreadable"


class FakeHttp:
    """Telegram vu de l'exterieur : ce que le bot envoie, et la reponse choisie."""

    def __init__(self, status: int = 200, answer: bytes = body(), fail: str | None = None) -> None:
        self.status, self.answer, self.fail = status, answer, fail
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def post(self, url: str, data: bytes, headers: Any, **kwargs: Any) -> PostResult:
        self.calls.append((url, json.loads(data)))
        if self.fail is not None:
            raise OutboundError("timeout", f"sur {url}")  # un detail qui contiendrait l'adresse
        return PostResult(self.status, "api.telegram.org", None, self.answer)


def bot(http: FakeHttp) -> TelegramBot:
    return TelegramBot(CANARY, cast(OutboundHttp, http))


@pytest.mark.anyio
async def test_polling_asks_only_for_messages_from_the_offset() -> None:
    http = FakeHttp(answer=body(private(3, "a")))
    assert [u.update_id for u in await bot(http).updates(3, 20)] == [3]
    [(url, payload)] = http.calls
    assert url == f"https://api.telegram.org/bot{CANARY}/getUpdates"
    assert payload == {"timeout": 20, "limit": 20, "allowed_updates": ["message"], "offset": 3}
    await bot(http).updates(None, 0)
    assert "offset" not in http.calls[1][1]


@pytest.mark.anyio
async def test_replies_are_plain_text_without_link_preview() -> None:
    http = FakeHttp(answer=b'{"ok":true,"result":{}}')
    await bot(http).send(42, "x" * 5000)
    [(url, payload)] = http.calls
    assert url.endswith("/sendMessage")
    assert payload["chat_id"] == 42 and len(payload["text"]) == 4096
    assert payload["link_preview_options"] == {"is_disabled": True}
    assert "parse_mode" not in payload  # rien n'est interprete


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (401, "unauthorized"),
        (404, "unauthorized"),
        (409, "conflict"),
        (429, "rejected"),
        (502, "rejected"),
    ],
)
async def test_refusals_never_carry_the_token(status: int, reason: str) -> None:
    with capture_logs() as logs, pytest.raises(TelegramError) as error:
        await bot(FakeHttp(status=status)).updates(None, 0)
    assert error.value.reason == reason
    assert "CANARY" not in str(error.value) and "CANARY" not in repr(logs)


@pytest.mark.anyio
async def test_a_transport_failure_never_carries_the_token() -> None:
    with pytest.raises(OutboundError) as error:
        await bot(FakeHttp(fail="timeout")).send(42, "x")
    assert error.value.reason == "timeout"
    assert "CANARY" not in str(error.value) and error.value.__cause__ is None
    assert error.value.__suppress_context__


def test_a_malformed_token_is_refused_at_start() -> None:
    assert TOKEN.fullmatch(CANARY)
    for bad in ("", "change-me", "123:court", f"{CANARY} ", "abc:" + "x" * 35):
        with pytest.raises(ValueError):
            TelegramBot(bad, cast(OutboundHttp, FakeHttp()))


# ------------------------------------------------------------------- codes
def test_codes_are_read_in_any_reasonable_form() -> None:
    for text in (
        "K7QM-2XPH",
        "k7qm2xph",
        "/start K7QM-2XPH",
        "/start@LorakusBot K7QM2XPH",
        "K7QM 2XPH",
    ):
        match = CODE.fullmatch(text)
        assert match is not None, text
        assert code_hash(match.group(1) + match.group(2)) == code_hash("K7QM2XPH")
    for text in ("K7QM-2XP", "Une idée de huit", "/start", "K7QM--2XPH", "/aide K7QM2XPH"):
        assert CODE.fullmatch(text) is None, text
    assert code_hash(" k7qm-2xph ") == code_hash("K7QM2XPH")
    assert display("K7QM2XPH") == "K7QM-2XPH"
    assert not set("01ILO") & set(ALPHABET)


def test_five_wrong_codes_an_hour_then_silence() -> None:
    now = [0.0]
    attempts = Attempts(clock=lambda: now[0])
    for _ in range(MAX_CODE_ATTEMPTS):
        assert not attempts.blocked(42)
        attempts.failed(42)
    assert attempts.blocked(42) and not attempts.blocked(43)
    now[0] = 3599.0
    assert attempts.blocked(42)
    now[0] = 3601.0
    assert not attempts.blocked(42)


class RecordingBot:
    """Ce que demande la releve : le numero a partir duquel lire (acquitte les precedents)."""

    def __init__(self, batches: list[list[Update]]) -> None:
        self.batches = batches
        self.offsets: list[int | None] = []
        self.waits: list[int] = []

    async def updates(self, offset: int | None, wait_s: int) -> list[Update]:
        self.offsets.append(offset)
        self.waits.append(wait_s)
        return self.batches.pop(0) if self.batches else []

    async def send(self, chat_id: int, message: str) -> None:
        raise AssertionError("aucune reponse attendue")


@pytest.mark.anyio
async def test_polling_acknowledges_what_it_read_and_stays_within_its_minute() -> None:
    # Messages de groupe : ignores sans base ni reponse, mais acquittes.
    group = [Update(7, chat_id=-1, private=False, text="x"), Update(9, chat_id=-1)]
    bot_ = RecordingBot([group, []])
    ticks = iter([0.0, 0.0, 20.0, 40.0])
    state = PollState()
    counts = await poll_round(
        cast(Any, None),
        bot_,
        cast(Any, None),
        state,
        lambda: datetime(2026, 11, 22, 8, tzinfo=UTC),
        clock=lambda: next(ticks),
    )
    assert counts == {"ignored": 2}
    assert bot_.offsets == [None, 10] and state.offset == 10
    # Jamais plus de 45 s : la derniere attente laisse 10 s de marge.
    assert bot_.waits == [20, 15]


@pytest.mark.anyio
async def test_the_poll_job_says_whether_a_bot_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from prometheus_client import REGISTRY

    from lorakus.core.telegram import jobs

    def configured() -> float | None:
        return REGISTRY.get_sample_value("lorakus_telegram_configured")

    async def no_round(*args: Any, **kwargs: Any) -> dict[str, int]:
        return {}

    monkeypatch.setattr(jobs, "poll_round", no_round)
    monkeypatch.setattr(jobs, "registry", lambda: None)
    ctx = cast(Any, type("Ctx", (), {"database": None})())
    monkeypatch.setattr(jobs, "bot", lambda: None)
    await jobs.poll(ctx, {})
    assert configured() == 0
    monkeypatch.setattr(jobs, "bot", lambda: RecordingBot([]))
    await jobs.poll(ctx, {})
    assert configured() == 1
