"""Adaptateurs des fournisseurs d'IA. Importe uniquement par la racine de composition (api).

Le Core et les modules n'importent jamais ce paquet (import-linter) : ils passent par le
ModelRouter, qui ne connait que le port AIProvider.
"""

from lorakus.ai.port import AIProvider
from lorakus.ai.providers.anthropic import AnthropicProvider
from lorakus.ai.testing import FakeProvider
from lorakus.settings import Settings

# Environnements ou le faux fournisseur peut repondre. Jamais staging ni production :
# une reponse inventee y passerait pour une vraie.
FAKE_ALLOWED = frozenset({"development", "test"})


def build_providers(settings: Settings) -> dict[str, AIProvider]:
    """Fournisseurs configures pour cet environnement, indexes par nom."""
    providers: dict[str, AIProvider] = {}
    key = settings.anthropic_api_key.get_secret_value()
    if key:
        providers["anthropic"] = AnthropicProvider(key)
    if settings.environment in FAKE_ALLOWED:
        providers["fake"] = FakeProvider()
    return providers
