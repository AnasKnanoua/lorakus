"""Requetes SQL des runbooks, executees sur une base migree (P6, PR 58).

Pendant un incident, on colle sur le serveur les commandes `psql ... -c "..."` des runbooks : une
colonne renommee, une table supprimee ou une contrainte oubliee ne s'y decouvrirait qu'au pire
moment. Trouve ainsi a l'ecriture de ce test : le retrait a la main d'un signal
(`notifications.md`) gardait son echeance, ce que la contrainte `status` de `core_signals` refuse.

Chaque requete est extraite des blocs ```bash de `docs/runbooks/`, puis executee en
lorakus_migrator dans une transaction toujours annulee, sur une base qui contient ce qu'elle vise
(un signal actif, un evenement abandonne) : une lecture doit s'executer, une modification doit
toucher au moins une ligne. En production, ces requetes tournent en lorakus_admin
(superutilisateur) : il a au moins les droits de lorakus_migrator, a qui sa politique RLS laisse
tout lire et tout modifier.
"""

import re
import shlex
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import migrator_engine, migrator_sql

from lorakus.core.events.bus import publish
from lorakus.core.identity.service import IdentityService
from lorakus.core.signals.service import SignalDraft, emit
from lorakus.db.database import Database

RUNBOOKS = Path(__file__).resolve().parents[3] / "docs" / "runbooks"
FENCE = re.compile(r"^[ \t]*```bash\n(.*?)^[ \t]*```", re.MULTILINE | re.DOTALL)
PSQL = re.compile(r"(?<![\w./-])psql(?![\w-])")
PLACEHOLDER = re.compile(r"<([a-z_]+)>")
WRITE = re.compile(r"^\s*(update|delete|insert)\b", re.IGNORECASE)
END_OF_COMMAND = {"&&", "||", ";", "|"}
PASSWORD = "mot de passe de test assez long"

# Requetes volontairement non executees ici, avec ce qui les verifie a la place.
NOT_RUN: dict[tuple[str, str], str] = {
    ("restore.md", "DROP SCHEMA IF EXISTS lorakus CASCADE"): (
        "destructive : rejouee sur PostgreSQL 18 par le staging de chaque deploiement "
        "(infra/staging/staging-test.sh, etape 5/6)"
    ),
}


@dataclass(frozen=True)
class RunbookQuery:
    runbook: str
    sql: str


def bash_blocks(text: str) -> list[str]:
    """Contenu des blocs ```bash, lignes coupees par une barre oblique inverse rejointes."""
    return [block.replace("\\\n", " ") for block in FENCE.findall(text)]


def psql_calls(block: str) -> list[list[str]]:
    """Arguments de chaque appel a psql d'un bloc, jusqu'a la fin de la commande."""
    calls: list[list[str]] = []
    for line in block.splitlines():
        if not PSQL.search(line):
            continue
        words = shlex.split(line)
        for index, word in enumerate(words):
            if word != "psql":
                continue
            arguments: list[str] = []
            for argument in words[index + 1 :]:
                if argument in END_OF_COMMAND or argument.startswith(("<", ">")):
                    break
                arguments.append(argument)
            calls.append(arguments)
    return calls


def queries_of(arguments: list[str]) -> list[str]:
    """Les requetes passees par -c, dans l'ordre."""
    return [arguments[i + 1] for i, word in enumerate(arguments[:-1]) if word == "-c"]


def runbook_queries() -> list[RunbookQuery]:
    """Toutes les requetes des runbooks, y compris celles qui ne sont pas executees ici."""
    found: list[RunbookQuery] = []
    for path in sorted(RUNBOOKS.glob("*.md")):
        for block in bash_blocks(path.read_text(encoding="utf-8")):
            for call in psql_calls(block):
                found.extend(RunbookQuery(path.name, sql) for sql in queries_of(call))
    return found


ALL_QUERIES = runbook_queries()
QUERIES = [q for q in ALL_QUERIES if (q.runbook, q.sql) not in NOT_RUN]


def fill(sql: str, values: dict[str, str]) -> str:
    """Remplace les valeurs a saisir (`<id>`) par celles de la base de test."""

    def value(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            pytest.fail(f"valeur a saisir inconnue du test : <{name}> dans {sql!r}")
        return values[name]

    return PLACEHOLDER.sub(value, sql)


# ----------------------------------------------------------------- extraction (sans base)
def test_every_psql_call_of_the_runbooks_is_read() -> None:
    """Autant d'appels lus que de `psql` ecrits dans tout le fichier : rien n'echappe au test.

    Un `psql` hors d'un bloc ```bash (autre langage, code dans le texte) fait echouer ce test :
    le mettre dans un bloc ```bash, ou il sera execute comme les autres."""
    for path in RUNBOOKS.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        written = len(PSQL.findall(text))
        read = sum(len(psql_calls(block)) for block in bash_blocks(text))
        assert written == read, f"{path.name} : {written} psql ecrits, {read} lus"
    assert len(ALL_QUERIES) >= 10, "les runbooks donnent au moins dix requetes"


def test_every_psql_call_carries_a_query() -> None:
    for path in RUNBOOKS.glob("*.md"):
        for block in bash_blocks(path.read_text(encoding="utf-8")):
            for call in psql_calls(block):
                assert queries_of(call), f"{path.name} : psql sans -c : {call}"


def test_the_queries_come_from_the_expected_runbooks() -> None:
    """Garde-fou de l'extraction : les runbooks qui donnent du SQL aujourd'hui sont lus."""
    assert {"ai.md", "disk-full.md", "notifications.md", "worker.md"} <= {
        q.runbook for q in QUERIES
    }


def test_queries_left_out_are_still_in_the_runbooks() -> None:
    """Une exception sans objet doit disparaitre, pas cacher une future requete."""
    present = {(q.runbook, q.sql) for q in ALL_QUERIES}
    assert set(NOT_RUN) <= present


def test_a_query_is_read_with_its_quotes_and_without_what_follows() -> None:
    block = bash_blocks(
        "```bash\n"
        "dc exec -T postgres psql -U a -d b -c \"select 1 where 'x' = 'x'\" \\\n"
        "  -c 'select 2' </dev/null && psql -c \"select 3\" | tail\n"
        'psql -c "select 4" && bash -c "echo pas du SQL"\n'
        "```\n"
    )
    calls = [queries_of(call) for call in psql_calls(block[0])]
    assert calls == [["select 1 where 'x' = 'x'", "select 2"], ["select 3"], ["select 4"]]


def test_a_value_to_type_is_replaced_and_an_unknown_one_fails() -> None:
    assert fill("where id = '<id>'", {"id": "42"}) == "where id = '42'"
    with pytest.raises(pytest.fail.Exception):
        fill("where id = '<autre>'", {"id": "42"})


# ----------------------------------------------------------------- execution (PostgreSQL)
@pytest.fixture
async def seeded(database: Database, identity: IdentityService) -> dict[str, str]:
    """Ce que visent les modifications des runbooks : un signal actif, un evenement abandonne."""
    user = await identity.create_owner("runbooks@example.com", PASSWORD)
    now = datetime.now(UTC)
    draft = SignalDraft(
        name="focus.runbook_check",
        kind="scheduled",
        strength=0.5,
        data_class="personal",
        dedup_key="runbook-check",
        title="Rappel de test",
        body="Texte du rappel de test",
        rule="Regle de test",
        url="/today",
        not_before=now,
        expires_at=now + timedelta(days=1),
    )
    async with database.transaction(user) as session:
        assert await emit(session, user, "focus", draft)
        await publish(session, "test.runbook_check", {}, user_id=user)
    await migrator_sql(
        "UPDATE lorakus.core_outbox SET dead_at = now(), attempts = 8, last_error = 'test' "
        "WHERE event_type = 'test.runbook_check'"
    )
    rows = await migrator_sql(
        "SELECT id FROM lorakus.core_signals "
        "WHERE dedup_key = 'runbook-check' AND status = 'active'"
    )
    signal_id = rows[0][0]
    assert isinstance(signal_id, uuid.UUID)
    return {"id": str(signal_id)}


@pytest.mark.integration
@pytest.mark.anyio
@pytest.mark.parametrize(
    "query", QUERIES, ids=[f"{q.runbook}-{i}" for i, q in enumerate(QUERIES, start=1)]
)
async def test_the_runbook_query_runs_on_a_migrated_database(
    query: RunbookQuery, seeded: dict[str, str]
) -> None:
    sql = fill(query.sql, seeded)
    engine = migrator_engine()
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                result = await connection.exec_driver_sql(sql)
                if WRITE.match(sql):
                    assert result.rowcount >= 1, f"{query.runbook} : aucune ligne modifiee : {sql}"
                elif result.returns_rows:
                    result.fetchall()
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
