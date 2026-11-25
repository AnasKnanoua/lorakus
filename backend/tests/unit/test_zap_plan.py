"""Le plan ZAP (infra/zap/baseline.yaml) demande toutes les routes GET de l'API sans parametre.

Sans ce test, une nouvelle route ne serait jamais vue par le scan passif : le robot classique ne
voit pas l'API d'une application a page unique (PR 57).
"""

import re
from functools import cache
from pathlib import Path

from lorakus.api.app import create_app

PLAN = Path(__file__).resolve().parents[3] / "infra" / "zap" / "baseline.yaml"
HOST = "https://lorakus.localhost"
SESSION_HEADER = '"Cookie: __Host-lorakus_session=${LORAKUS_ZAP_SESSION}"'

# Routes GET sans parametre de chemin volontairement absentes du plan, avec la raison.
NOT_SCANNED = {
    # Exige le parametre de requete q (sinon 422) : rien de plus a voir qu'un refus.
    "/api/v1/memory/search",
}


def plan_requests() -> list[tuple[str, bool, str | None]]:
    """(chemin, avec session, code attendu) de chaque requete du job requestor."""
    text = PLAN.read_text(encoding="utf-8")
    entries = re.split(
        r"\n\s+- url: ", text.split("- type: requestor", 1)[1].split("\n  - type:", 1)[0]
    )
    requests: list[tuple[str, bool, str | None]] = []
    for entry in entries[1:]:
        url = entry.split("\n", 1)[0].strip()
        assert url.startswith(HOST), url
        assert "method: GET" in entry, url
        code = re.search(r"responseCode: (\d+)", entry)
        requests.append(
            (url.removeprefix(HOST), SESSION_HEADER in entry, code.group(1) if code else None)
        )
    return requests


@cache
def api_get_routes() -> frozenset[str]:
    """Routes GET sans parametre de chemin, lues dans le contrat OpenAPI de l'application."""
    paths: dict[str, dict[str, object]] = create_app().openapi()["paths"]
    return frozenset(
        path for path, operations in paths.items() if "get" in operations and "{" not in path
    )


def test_the_route_list_is_not_empty() -> None:
    # Garde-fou du test lui-meme : une liste vide le rendrait toujours vert.
    assert {"/api/health", "/api/v1/auth/me", "/api/v1/tools"} <= api_get_routes()
    # Une exception doit designer une route qui existe encore.
    assert NOT_SCANNED.issubset(api_get_routes())


def test_every_parameterless_get_route_is_scanned_with_the_session() -> None:
    with_session = {path for path, session, _ in plan_requests() if session}
    assert api_get_routes() - NOT_SCANNED - with_session == set()


def test_the_plan_only_requests_existing_routes() -> None:
    paths = {path for path, _, _ in plan_requests()}
    assert paths - api_get_routes() == set()
    assert NOT_SCANNED & {path for path, session, _ in plan_requests() if session} == set()


def test_the_session_is_checked_both_ways() -> None:
    requests = plan_requests()
    assert ("/api/v1/auth/me", True, "200") in requests
    assert ("/api/v1/auth/me", False, "401") in requests
    anonymous = [r for r in requests if not r[1]]
    assert anonymous, "au moins une requete sans session"
    assert all(code == "401" for _, _, code in anonymous), anonymous
