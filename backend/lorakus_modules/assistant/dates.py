"""Dates et durees ecrites en francais, sans dependre de la locale du serveur.

Utilisees par le prompt (la date du jour) et par les cartes de confirmation : la carte
montre toujours la date ABSOLUE (« vendredi 20 novembre 2026 »), calculee par le code, pour
que l'utilisateur voie si le modele a mal compris « vendredi ».
"""

from datetime import date
from typing import Final

DAYS: Final = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
MONTHS: Final = (
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


def french_date(day: date) -> str:
    """« vendredi 20 novembre 2026 »."""
    return f"{DAYS[day.weekday()]} {day.day} {MONTHS[day.month - 1]} {day.year}"


def relative_day(day: date, today: date) -> str:
    """Position du jour par rapport a aujourd'hui : « aujourd'hui », « dans 3 jours »..."""
    delta = (day - today).days
    if delta == 0:
        return "aujourd'hui"
    if delta == 1:
        return "demain"
    if delta == -1:
        return "hier"
    if delta > 1:
        return f"dans {delta} jours"
    return f"il y a {-delta} jours"


def duration(minutes: int) -> str:
    """« 45 min », « 3 h », « 1 h 30 »."""
    hours, rest = divmod(minutes, 60)
    if hours == 0:
        return f"{rest} min"
    return f"{hours} h" if rest == 0 else f"{hours} h {rest:02d}"
