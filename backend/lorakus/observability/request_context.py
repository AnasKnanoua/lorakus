"""Middleware : identifiant de requete, journal d'acces et metriques HTTP."""

import re
import time
import uuid
from typing import Final

import structlog
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match

from lorakus.observability.metrics import HTTP_REQUEST_DURATION, HTTP_REQUESTS

REQUEST_ID_HEADER: Final = "X-Request-ID"
UNMATCHED_ROUTE: Final = "unmatched"
HEALTH_ROUTE: Final = "/api/health"

# Un identifiant envoye par le client n'est conserve que s'il est court et sans
# caractere special : sinon il pourrait servir a injecter de fausses lignes de journal.
_VALID_REQUEST_ID: Final = re.compile(r"[A-Za-z0-9-]{8,64}")

# Methodes HTTP connues ; toute autre est regroupee sous "OTHER".
_KNOWN_METHODS: Final = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})

logger = structlog.stdlib.get_logger("lorakus.http")


def _request_id(request: Request) -> str:
    candidate = request.headers.get(REQUEST_ID_HEADER)
    if candidate is not None and _VALID_REQUEST_ID.fullmatch(candidate):
        return candidate
    return uuid.uuid4().hex


def _route_template(request: Request) -> str:
    """Modele de la route (ex. /api/users/{user_id}), jamais le chemin brut.

    Pour une route FastAPI, le modele connu est relatif au routeur qui l'inclut
    (/users/{user_id}) : on reconstitue le prefixe (/api) en retirant du chemin
    reel la partie qui correspond a la route, valeurs des parametres comprises.
    """
    route = request.scope.get("route")
    path_format = getattr(route, "path_format", None)
    if isinstance(path_format, str):
        params = {name: str(value) for name, value in request.path_params.items()}
        try:
            concrete = path_format.format(**params)
        except (KeyError, IndexError, ValueError):
            return UNMATCHED_ROUTE
        path = request.scope.get("path")
        if isinstance(path, str) and path.endswith(concrete):
            return path[: len(path) - len(concrete)] + path_format
        return UNMATCHED_ROUTE

    # Routes Starlette classiques (ex. /api/docs) : correspondance directe.
    app: Starlette = request.app
    for candidate in app.routes:
        match, _ = candidate.matches(request.scope)
        if match == Match.FULL:
            candidate_path = getattr(candidate, "path", None)
            if isinstance(candidate_path, str):
                return candidate_path
    return UNMATCHED_ROUTE


def _method_label(method: str) -> str:
    return method if method in _KNOWN_METHODS else "OTHER"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Associe un identifiant a chaque requete, la journalise et la mesure."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = _request_id(request)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        finally:
            duration = time.perf_counter() - start
            route = _route_template(request)
            method = _method_label(request.method)
            HTTP_REQUESTS.labels(method=method, route=route, status=str(status_code)).inc()
            HTTP_REQUEST_DURATION.labels(method=method, route=route).observe(duration)
            # Les sondes de sante arrivent toutes les 30 s : niveau DEBUG
            # pour ne pas noyer les journaux.
            log = logger.debug if route == HEALTH_ROUTE else logger.info
            log(
                "http_request",
                method=method,
                route=route,
                status=status_code,
                duration_ms=round(duration * 1000, 1),
            )

        response.headers[REQUEST_ID_HEADER] = request_id
        return response
