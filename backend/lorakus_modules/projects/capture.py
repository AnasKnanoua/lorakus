"""Capture rapide vers la boite a idees (P5, scenario 5) : un texte envoye au bot Telegram.

Le Core appelle cette fonction (manifeste : `capture`) sous la RLS de l'utilisateur. Memes
regles qu'une idee notee dans la page : une ligne, 500 caracteres, pas de doublon, boite
limitee. Provenance `telegram`. Aucune carte de confirmation : c'est l'utilisateur lui-meme qui
envoie son texte, aucun modele n'intervient (decision D6, ADR 0042).
"""

from typing import Final

from lorakus.core.capture import CaptureRefusedError, CaptureRequest
from lorakus_modules.projects.service import ProjectsError, add_idea

ECHO: Final = 80  # longueur du rappel de l'idee dans la reponse du bot


async def capture_idea(request: CaptureRequest) -> str:
    try:
        idea = await add_idea(request.session, request.user_id, request.text, channel="telegram")
    except ProjectsError as error:
        raise CaptureRefusedError(str(error)) from None
    text = idea.text if len(idea.text) <= ECHO else idea.text[: ECHO - 1] + "…"
    return f"Idée notée dans ta boîte : « {text} »"
