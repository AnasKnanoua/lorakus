"""Outils du chat sur les preferences de planification (PR 48, ADR 0018 et 0040).

« Je dejeune de 12 h 30 a 13 h 30 », « pas de travail apres 21 h », « rien le dimanche » :
le modele comprend la phrase et appelle l'outil ; le code valide la valeur contre un catalogue
FERME (preferences.py du Core), ecrit la carte, et rien n'est enregistre avant le clic. Le
planificateur ne lit que des preferences confirmees.

Lister (read) s'execute tout de suite. Regler et retirer (write) affichent une carte qui
donne la valeur proposee ET la valeur actuelle : on voit ce qui change avant de confirmer.
"""

from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from lorakus.core.planning.preferences import (
    DEFAULTS,
    KEYS,
    LABEL,
    WEEKDAYS,
    InvalidPreferenceError,
    Key,
    clear_preference,
    current_value,
    load,
    preview,
    set_preference,
    stored,
    value_text,
)
from lorakus.core.tools.spec import ToolCall, ToolError, ToolSpec

Name = Literal[
    "debut_travail", "fin_travail", "dejeuner", "diner", "jours_sans_travail", "travail_par_jour"
]
KEY: Final[dict[str, Key]] = {
    "debut_travail": "work_start",
    "fin_travail": "work_end",
    "dejeuner": "lunch",
    "diner": "dinner",
    "jours_sans_travail": "rest_days",
    "travail_par_jour": "daily_cap",
}
NAME: Final[dict[Key, str]] = {key: name for name, key in KEY.items()}
Weekday = Literal["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
HOUR: Final = r"^([01]\d|2[0-3]):[0-5]\d$"
WHICH: Final = (
    "debut_travail et fin_travail (bornes de la journée de travail), dejeuner et diner "
    "(plages de repas), jours_sans_travail, travail_par_jour (maximum proposé)."
)


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preference: Name = Field(description=f"Laquelle : {WHICH}")
    time: str | None = Field(
        default=None, pattern=HOUR, description="HH:MM, pour debut_travail et fin_travail."
    )
    start: str | None = Field(
        default=None, pattern=HOUR, description="HH:MM, début du repas (dejeuner, diner)."
    )
    end: str | None = Field(
        default=None, pattern=HOUR, description="HH:MM, fin du repas (dejeuner, diner)."
    )
    days: list[Weekday] | None = Field(
        default=None, min_length=1, max_length=7, description="Pour jours_sans_travail."
    )
    minutes: int | None = Field(
        default=None, ge=1, le=24 * 60, description="Pour travail_par_jour, en minutes."
    )


class ClearIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preference: Name = Field(description=f"Laquelle retirer : {WHICH}")


def _raw(args: SetIn) -> dict[str, Any]:
    """L'objet JSON de la preference, avec seulement les champs que sa cle attend."""
    key = KEY[args.preference]
    if key in ("work_start", "work_end"):
        needed: dict[str, Any] = {"time": args.time}
    elif key in ("lunch", "dinner"):
        needed = {"start": args.start, "end": args.end}
    elif key == "rest_days":
        needed = {"days": None if args.days is None else [WEEKDAYS.index(d) for d in args.days]}
    else:
        needed = {"minutes": args.minutes}
    missing = [name for name, value in needed.items() if value is None]
    if missing:
        raise ToolError(
            f"Pour « {LABEL[key]} », il manque : {', '.join(missing)}. "
            "Demande-le à l'utilisateur plutôt que de l'inventer."
        )
    return needed


async def _list(call: ToolCall, _: NoArgs) -> dict[str, Any]:
    prefs = await load(call.session)
    confirmed = {item.key for item in await stored(call.session)}
    return {
        "preferences": [
            {
                "preference": NAME[key],
                "nom": LABEL[key],
                "valeur": value_text(key, current_value(prefs, key)),
                "origine": "confirmée par l'utilisateur"
                if key in confirmed
                else "valeur par défaut",
            }
            for key in KEYS
        ]
    }


async def _set_summary(call: ToolCall, args: SetIn) -> str:
    key = KEY[args.preference]
    try:
        value, before = await preview(call.session, key, _raw(args))
    except InvalidPreferenceError as error:
        raise ToolError(str(error)) from None
    if value == before:
        raise ToolError(f"C'est déjà le cas : {LABEL[key]} = {value_text(key, value)}.")
    return "\n".join(
        [
            "Préférence de planification",
            f"{LABEL[key]} : {value_text(key, value)}",
            f"Actuellement : {value_text(key, before)}",
        ]
    )


async def _set(call: ToolCall, args: SetIn) -> dict[str, Any]:
    key = KEY[args.preference]
    try:
        await set_preference(call.session, call.user_id, key, _raw(args), source_ref=call.origin)
    except InvalidPreferenceError as error:
        raise ToolError(str(error)) from None
    return {"message": "Préférence enregistrée : le plan de la journée en tient compte."}


async def _clear_summary(call: ToolCall, args: ClearIn) -> str:
    key = KEY[args.preference]
    if key not in {item.key for item in await stored(call.session)}:
        raise ToolError(f"Aucune préférence enregistrée pour « {LABEL[key]} ».")
    prefs = await load(call.session)
    return "\n".join(
        [
            f"Retirer la préférence « {LABEL[key]} »",
            f"Actuellement : {value_text(key, current_value(prefs, key))}",
            f"Après : {value_text(key, current_value(DEFAULTS, key))} (valeur par défaut)",
        ]
    )


async def _clear(call: ToolCall, args: ClearIn) -> dict[str, Any]:
    try:
        removed = await clear_preference(call.session, call.user_id, KEY[args.preference])
    except InvalidPreferenceError as error:
        raise ToolError(str(error)) from None
    if not removed:
        raise ToolError("Cette préférence n'existe plus.")
    return {"message": "Préférence retirée."}


PREFERENCE_TOOLS: Final = [
    ToolSpec(
        "assistant.list_preferences",
        "Lit les préférences de planification de l'utilisateur (horaires de travail, repas, "
        "jours sans travail, maximum par jour), confirmées ou par défaut.",
        "read",
        NoArgs,
        _list,
    ),
    ToolSpec(
        "assistant.set_preference",
        "Propose d'enregistrer une préférence de planification quand l'utilisateur dit ses "
        "horaires ou ses habitudes (« je déjeune de 12 h 30 à 13 h 30 », « pas de travail "
        "après 21 h », « rien le dimanche », « 4 h de travail par jour au plus »). Une carte "
        "s'affiche : rien n'est enregistré tant que l'utilisateur ne l'a pas confirmée. Un "
        "appel par préférence.",
        "write",
        SetIn,
        _set,
        summary=_set_summary,
    ),
    ToolSpec(
        "assistant.clear_preference",
        "Propose de retirer une préférence de planification pour revenir à la valeur par "
        "défaut. Une carte s'affiche : rien ne change avant la confirmation.",
        "write",
        ClearIn,
        _clear,
        summary=_clear_summary,
    ),
]
