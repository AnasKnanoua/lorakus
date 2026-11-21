"""Appels HTTP sortants du Core, proteges contre la SSRF (PR 45, ADR 0041)."""

from lorakus.core.outbound.client import (
    FetchLimits,
    FetchResult,
    OutboundError,
    OutboundHttp,
    PostResult,
    system_resolver,
)
from lorakus.core.outbound.policy import (
    InvalidUrlError,
    SafeUrl,
    display_hint,
    is_public_address,
    parse_public_url,
)

__all__ = [
    "FetchLimits",
    "FetchResult",
    "InvalidUrlError",
    "OutboundError",
    "OutboundHttp",
    "PostResult",
    "SafeUrl",
    "display_hint",
    "is_public_address",
    "parse_public_url",
    "system_resolver",
]
