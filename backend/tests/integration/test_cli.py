"""Commande create-owner : mot de passe lu au clavier, jamais en argument."""

import asyncio

import pytest
from conftest import OWNER_EMAIL, OWNER_PASSWORD, migrator_sql, wipe_identity

from lorakus import cli

pytestmark = pytest.mark.integration


def test_password_cannot_be_given_as_an_argument(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["create-owner", "--password", "secret"])
    assert exit_info.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


def test_create_owner_reads_password_with_getpass(monkeypatch: pytest.MonkeyPatch) -> None:
    asyncio.run(wipe_identity())
    prompts: list[str] = []
    monkeypatch.setattr("builtins.input", lambda _prompt: OWNER_EMAIL)

    def fake_getpass(prompt: str) -> str:
        prompts.append(prompt)
        return OWNER_PASSWORD

    monkeypatch.setattr(cli.getpass, "getpass", fake_getpass)

    assert cli.main(["create-owner"]) == 0
    assert len(prompts) == 2
    rows = asyncio.run(migrator_sql("SELECT email, role FROM lorakus.core_users"))
    assert rows == [(OWNER_EMAIL, "owner")]
    # Une seconde fois : refuse.
    assert cli.main(["create-owner"]) == 1


def test_mismatched_confirmation_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    asyncio.run(wipe_identity())
    answers = iter([OWNER_PASSWORD, "autre chose de long"])
    monkeypatch.setattr("builtins.input", lambda _prompt: OWNER_EMAIL)
    monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt: next(answers))

    assert cli.main(["create-owner"]) == 1
    assert asyncio.run(migrator_sql("SELECT count(*) FROM lorakus.core_users")) == [(0,)]
