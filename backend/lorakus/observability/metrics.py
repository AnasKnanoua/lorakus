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


def start_metrics_server(port: int) -> None:
    """Expose /metrics sur un port dedie, qui ne sera jamais publie sur Internet."""
    # 0.0.0.0 a l'interieur du conteneur uniquement : seul Prometheus, sur le
    # reseau interne de Docker, peut joindre ce port.
    start_http_server(port, addr="0.0.0.0")  # noqa: S104
