"""Tests des parametres : chaque role exige son propre mot de passe hors developpement."""

import pytest

from lorakus.settings import Settings


def test_each_role_requires_its_own_password_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LORAKUS_ENVIRONMENT", "production")
    monkeypatch.setenv("LORAKUS_APP_DB_PASSWORD", "app-only")
    monkeypatch.setenv("LORAKUS_MIGRATOR_DB_PASSWORD", "")

    settings = Settings()

    settings.app_database_url()  # le role de l'API a son mot de passe : aucune erreur
    with pytest.raises(ValueError, match="lorakus_migrator"):
        settings.migrator_database_url()


def test_password_never_appears_when_url_is_displayed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LORAKUS_APP_DB_PASSWORD", "tres-secret-123")

    url = Settings().app_database_url()

    assert "tres-secret-123" not in str(url)
    assert "tres-secret-123" not in repr(url)


def test_production_always_requires_a_second_factor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LORAKUS_ENVIRONMENT", "production")
    monkeypatch.setenv("LORAKUS_REQUIRE_SECOND_FACTOR", "false")
    assert Settings().require_second_factor is True


def test_public_origin_is_an_origin_without_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LORAKUS_PUBLIC_ORIGIN", "https://app.lorakus.app/chemin")
    with pytest.raises(ValueError, match="public_origin"):
        Settings()
    monkeypatch.setenv("LORAKUS_PUBLIC_ORIGIN", "https://app.lorakus.app")
    assert Settings().allowed_origins() >= {"https://app.lorakus.app"}
