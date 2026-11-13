"""Adaptateurs des fournisseurs d'IA. Importe uniquement par la racine de composition (api).

Le Core et les modules n'importent jamais ce paquet (import-linter) : ils passent par le
ModelRouter, qui ne connait que le port AIProvider.
"""

import structlog

from lorakus.ai.embeddings import Embedder, EmbeddingError, FakeEmbedder
from lorakus.ai.port import AIProvider
from lorakus.ai.providers.anthropic import AnthropicProvider
from lorakus.ai.providers.onnx_embedder import MODEL_FILE, OnnxEmbedder
from lorakus.ai.testing import FakeProvider
from lorakus.settings import Settings

log = structlog.get_logger("lorakus.ai")

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


def build_embedder(settings: Settings) -> Embedder:
    """Modele d'embeddings local de cet environnement (appel bloquant : quelques secondes).

    Fichiers du modele presents : le vrai modele. Absents : faux modele en developpement et
    en test ; EmbeddingError en staging et en production, pour que l'API refuse de demarrer
    plutot que de chercher dans la memoire avec de faux vecteurs.
    """
    model_dir = settings.embedding_model_dir
    if (model_dir / MODEL_FILE).is_file():
        embedder = OnnxEmbedder.load(model_dir, threads=settings.embedding_threads)
        log.info("embedding_model_loaded", model=embedder.model_id)
        return embedder
    if settings.environment in FAKE_ALLOWED:
        log.warning("embedding_model_missing_fake_used", model_dir=str(model_dir))
        return FakeEmbedder()
    raise EmbeddingError(f"modele d'embeddings absent ({model_dir}) en {settings.environment}")
