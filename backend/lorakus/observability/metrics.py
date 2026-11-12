"""Metriques Prometheus de l'application, exposees sur un port separe."""

from typing import Final

from prometheus_client import Counter, Histogram, start_http_server

HTTP_REQUESTS: Final = Counter(
    "lorakus_http_requests_total",
    "Requetes HTTP traitees",
    ["method", "route", "status"],
)

HTTP_REQUEST_DURATION: Final = Histogram(
    "lorakus_http_request_duration_seconds",
    "Duree de traitement des requetes HTTP",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# --- Moteur IA (PR 32). Aucune etiquette ne porte d'identifiant d'utilisateur ni de contenu.
AI_REQUESTS: Final = Counter(
    "lorakus_ai_requests_total",
    "Appels aux fournisseurs d'IA (outcome : ok, error, interrupted)",
    ["task", "provider", "model", "outcome"],
)

AI_REFUSALS: Final = Counter(
    "lorakus_ai_refusals_total",
    "Demandes IA refusees avant tout appel (budget, coupure, classe de donnees...)",
    ["task", "reason"],
)

AI_TOKENS: Final = Counter(
    "lorakus_ai_tokens_total",
    "Tokens factures (kind : input, output, cache_read, cache_write)",
    ["provider", "model", "kind"],
)

AI_COST: Final = Counter(
    "lorakus_ai_cost_usd_total",
    "Cout estime des appels IA, en dollars (prix de pricing.toml)",
    ["provider", "model"],
)

AI_FIRST_TOKEN: Final = Histogram(
    "lorakus_ai_first_token_seconds",
    "Delai avant le premier morceau de reponse",
    ["provider", "model"],
    buckets=(0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0, 20.0),
)

AI_USAGE_RECORD_FAILURES: Final = Counter(
    "lorakus_ai_usage_record_failures_total",
    "Consommations IA non enregistrees en base (le plafond mensuel les ignore)",
)


def start_metrics_server(port: int) -> None:
    """Expose /metrics sur un port dedie, qui ne sera jamais publie sur Internet."""
    # 0.0.0.0 a l'interieur du conteneur uniquement : seul Prometheus, sur le
    # reseau interne de Docker, peut joindre ce port.
    start_http_server(port, addr="0.0.0.0")  # noqa: S104


RATE_LIMITED: Final = Counter(
    "lorakus_rate_limited_total",
    "Requetes refusees par une limite de debit par utilisateur (bucket : compteur)",
    ["bucket"],
)

ORIGIN_REFUSED: Final = Counter(
    "lorakus_origin_refused_total",
    "Requetes d'ecriture refusees parce qu'elles venaient d'une autre origine",
)
