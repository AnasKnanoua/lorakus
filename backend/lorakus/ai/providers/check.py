"""Verifie et mesure le modele d'embeddings de l'image : python -m lorakus.ai.providers.check

Lance par le test de fumee de l'image (infra/ci/smoke-image.sh), sur amd64 et arm64, et a la
main sur le serveur pour mesurer (DEPLOYMENT.md). N'a besoin ni de la base ni d'une cle.

Affiche : identifiant du modele, temps de chargement, memoire du processus avant et apres,
latence d'une question (mediane et 95e centile), temps d'un lot de 32 faits, et un controle
de sens en francais. Code de sortie 1 si le modele manque ou classe mal un cas evident.
"""

import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path

from lorakus.ai.embeddings import EmbeddingError, cosine
from lorakus.ai.providers.onnx_embedder import OnnxEmbedder
from lorakus.settings import get_settings

# Question, fait attendu en premier, autres faits. Cas sans mot commun avec le fait attendu
# pour verifier le sens, pas seulement les mots.
SANITY_CASES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "Comment s'appelle mon chien ?",
        "Mon labrador s'appelle Rex",
        ("Étudie à METU, à Ankara", "Préfère les réponses courtes"),
    ),
    (
        "Dans quelle ville je vis en ce moment ?",
        "Habite à Ankara jusqu'à fin décembre",
        ("Joue aux échecs sur Chess.com", "Mon labrador s'appelle Rex"),
    ),
    (
        "Quel sport je pratique ?",
        "Fait de la course à pied trois fois par semaine",
        ("Habite à Ankara jusqu'à fin décembre", "Préfère les réponses courtes"),
    ),
)


def rss_mib() -> float:
    """Memoire residente actuelle du processus, en Mio (Linux)."""
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024
    return float("nan")


async def _measure(embedder: OnnxEmbedder) -> bool:
    latencies: list[float] = []
    for i in range(30):
        started = time.perf_counter()
        await embedder.embed_query(f"Qu'est-ce que je dois faire aujourd'hui ? ({i})")
        latencies.append((time.perf_counter() - started) * 1000)
    latencies.sort()
    p95 = latencies[int(len(latencies) * 0.95) - 1]
    print(f"Question : mediane {statistics.median(latencies):.1f} ms, p95 {p95:.1f} ms")

    started = time.perf_counter()
    await embedder.embed_passages([f"Fait numero {i} sur mes habitudes" for i in range(32)])
    print(f"Lot de 32 faits : {(time.perf_counter() - started) * 1000:.0f} ms")

    ok = True
    for question, expected, others in SANITY_CASES:
        query = await embedder.embed_query(question)
        passages = await embedder.embed_passages([expected, *others])
        scores = [cosine(query, p) for p in passages]
        best = scores.index(max(scores))
        verdict = "OK" if best == 0 else "ECHEC"
        ok = ok and best == 0
        print(f"Sens [{verdict}] {question!r} -> {[round(s, 3) for s in scores]}")
    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lorakus.ai.providers.check", description=__doc__)
    parser.add_argument("--model-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    settings = get_settings()
    model_dir: Path = args.model_dir or settings.embedding_model_dir

    before = rss_mib()
    started = time.perf_counter()
    try:
        embedder = OnnxEmbedder.load(model_dir, threads=settings.embedding_threads)
    except EmbeddingError as error:
        print(f"ECHEC : {error}", file=sys.stderr)
        return 1
    print(f"Modele : {embedder.model_id} ({embedder.dimensions} dimensions)")
    print(f"Chargement : {time.perf_counter() - started:.2f} s")
    print(f"Memoire : {before:.0f} Mio avant, {rss_mib():.0f} Mio apres chargement")
    ok = asyncio.run(_measure(embedder))
    print(f"Memoire apres mesures : {rss_mib():.0f} Mio")
    if not ok:
        print("ECHEC : le modele classe mal un cas evident", file=sys.stderr)
        return 1
    print("Modele d'embeddings : verifications reussies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
