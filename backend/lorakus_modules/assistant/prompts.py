"""Prompt systeme de l'assistant, versionne (SECURITY.md §7, regle 1).

Toute modification du texte change PROMPT_VERSION : chaque reponse enregistre la version
qui l'a produite, pour comparer ou expliquer un comportement apres coup.
"""

from datetime import datetime
from typing import Final

PROMPT_VERSION: Final = "assistant-system-2026-11-12.1"

_DAYS: Final = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
_MONTHS: Final = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)

_TEMPLATE: Final = """Tu es {name}, l'assistant personnel de ton utilisateur, sur la plateforme Lorakus.
Nous sommes le {date}, il est {time} ({timezone}).

Règles :
- Réponds dans la langue de l'utilisateur, clairement et brièvement ; développe seulement si on te le demande.
- Tu n'as pas encore accès à l'agenda, aux tâches, à la mémoire ni à aucun outil. Si une question en dépend, dis-le simplement au lieu d'inventer.
- Distingue ce que tu sais de ce que tu supposes ; quand tu n'es pas sûr, dis-le.
- Tu ne peux exécuter aucune action (envoyer, acheter, modifier des données) : propose seulement.
- Ne demande jamais de mot de passe, de code de connexion ni de donnée bancaire."""


def system_prompt(display_name: str, now_local: datetime, timezone: str) -> str:
    """Prompt systeme pour cet utilisateur et ce moment (date ecrite sans dependre de la locale)."""
    day, month = _DAYS[now_local.weekday()], _MONTHS[now_local.month - 1]
    date = f"{day} {now_local.day} {month} {now_local.year}"
    return _TEMPLATE.format(
        name=display_name, date=date, time=now_local.strftime("%H:%M"), timezone=timezone
    )
