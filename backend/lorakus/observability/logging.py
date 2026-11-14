"""Journaux structures (une ligne JSON par evenement) avec masquage des secrets."""

import logging
import re
import sys
from typing import Final

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

from lorakus.observability.telemetry import add_trace_ids
from lorakus.settings import LogFormat

# Valeur qui remplace toute donnee sensible dans les journaux.
REDACTED: Final = "[MASQUE]"

# Toute cle dont le nom contient l'un de ces mots voit sa valeur masquee.
_SENSITIVE_KEY_PARTS: Final = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
)

# Mot de passe dans une URL de connexion : postgresql://utilisateur:MOTDEPASSE@hote
_URL_CREDENTIALS: Final = re.compile(r"(://[^:/@\s]+:)[^@\s]+@")


def redact_sensitive(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    """Masque les valeurs sensibles avant qu'elles n'atteignent les journaux."""
    for key, value in event_dict.items():
        if any(part in key.lower() for part in _SENSITIVE_KEY_PARTS):
            event_dict[key] = REDACTED
        elif isinstance(value, str):
            event_dict[key] = _URL_CREDENTIALS.sub(r"\1***@", value)
    return event_dict


def configure_logging(*, log_format: LogFormat, level: str = "INFO") -> logging.Formatter:
    """Configure structlog et la journalisation standard (uvicorn compris).

    Renvoie le formateur de la sortie standard : la copie des journaux envoyee a Loki
    (PR 40) utilise le meme rendu, avec trace_id et span_id quand une trace est en cours.
    """
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        add_trace_ids,
        redact_sensitive,
    ]

    final: list[Processor] = [structlog.stdlib.ProcessorFormatter.remove_processors_meta]
    if log_format == "json":
        final += [structlog.processors.format_exc_info, structlog.processors.JSONRenderer()]
    else:
        final.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )

    formatter = structlog.stdlib.ProcessorFormatter(foreign_pre_chain=shared, processors=final)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # Les messages d'uvicorn passent par le meme format. Son journal d'acces est
    # remplace par le notre, qui porte l'identifiant de requete et jamais la query string.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
    # httpx2 et httpcore2 (client HTTP du SDK d'Anthropic) journalisent chaque requete avec
    # son adresse COMPLETE (chaine de requete comprise) : doublon de notre ligne `ai_call`, et
    # risque de fuite si une adresse portait une donnee (trouve par le test canari, PR 40).
    # Avertissements seulement. Les anciens noms restent couverts.
    for name in ("httpx2", "httpcore2", "httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    return formatter
