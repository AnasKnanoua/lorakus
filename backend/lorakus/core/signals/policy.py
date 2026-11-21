"""InterventionPolicy (ADR 0014, 0019, 0029 et 0042) : le seul composant qui decide
d'interrompre l'utilisateur.

Des fonctions pures : elles recoivent l'etat d'un signal, le cadre du jour et l'instant, et
rendent une decision. Aucune base, aucun reseau, aucun LLM : la decision est reproductible et
se teste scenario par scenario (budget, heures calmes, escalade), avec une horloge fixe.

Deux niveaux en P5 (le niveau 3, les pactes, arrive en P12) :

- **Niveau 1, discret** : une carte dans l'application (« Ma journee »). Aucune notification,
  donc ni heures calmes ni budget : elle attend que l'utilisateur ouvre l'application.
- **Niveau 2, ferme** : une notification sur les appareils abonnes. Seulement si la carte du
  niveau 1 n'a ete ni vue, ni fermee, ni repoussee pendant 24 h ; une fois par cause ;
  pendant la plage de travail que l'utilisateur a donnee pour le jour en cours, hors de ses
  pauses ; au plus 3 par jour local.

Heures calmes sans rien supposer (decision D1) : les horaires de l'utilisateur changent tous
les jours. Une notification n'est donc envoyee que DANS le cadre du jour qu'il a lui-meme
donne. Sans cadre, ou un jour sans travail, aucune notification : la carte suffit.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Literal

from lorakus.core.planning.days import DayFrame

LEVEL1_IGNORED_AFTER: Final = timedelta(hours=24)
DAILY_PUSH_BUDGET: Final = 3
# Sans cadre connu, on regarde de nouveau un peu plus tard : l'utilisateur peut le donner.
RECHECK: Final = timedelta(minutes=15)
TEST_SIGNAL: Final = "core.push_test"

Action = Literal["app", "push", "wait", "done", "expire"]


@dataclass(frozen=True)
class SignalState:
    """Ce que la politique sait d'un signal."""

    name: str
    data_class: str
    not_before: datetime
    expires_at: datetime
    seen_at: datetime | None = None
    closed_at: datetime | None = None
    snoozed_until: datetime | None = None
    level1_at: datetime | None = None  # carte creee (niveau 1)
    level2_done: bool = False  # notification deja decidee (niveau 2)


@dataclass(frozen=True)
class Surroundings:
    """Ce qui entoure la decision : le cadre du jour en cours, le budget, les appareils."""

    frame: DayFrame | None
    next_day_start: datetime  # debut du jour local suivant (instant UTC)
    pushes_today: int
    devices: int


@dataclass(frozen=True)
class Decision:
    action: Action
    reason: str
    next_check: datetime | None = None  # pour « wait » : quand regarder de nouveau


def _wait(reason: str, at: datetime, signal: SignalState) -> Decision:
    # Jamais au-dela de l'expiration : a cet instant, le signal expire.
    return Decision("wait", reason, min(at, signal.expires_at))


def quiet(frame: DayFrame | None, now: datetime) -> tuple[str, datetime | None] | None:
    """None si une notification peut partir maintenant ; sinon la raison, et l'instant ou ce
    ne sera plus vrai (None : inconnu, regarder plus tard)."""
    if frame is None:
        return "no_frame", None
    if frame.off or frame.start is None or frame.end is None:
        return "day_off", None
    if now < frame.start:
        return "before_work", frame.start
    if now >= frame.end:
        return "after_work", None
    for pause in frame.breaks:
        if pause.start <= now < pause.end:
            return "break", pause.end
    return None


def decide(signal: SignalState, around: Surroundings, now: datetime) -> Decision:
    """La decision pour ce signal, a l'instant `now`. Les regles, dans l'ordre :"""
    # 1. Une cause passee ne merite plus rien (la carte disparait aussi).
    if now >= signal.expires_at:
        return Decision("expire", "expired")
    # 2. Trop tot.
    if now < signal.not_before:
        return _wait("not_yet", signal.not_before, signal)
    # 3. Notification de test, demandee par l'utilisateur depuis la page Notifications :
    #    tout de suite, hors budget et hors heures calmes (il vient de cliquer).
    if signal.name == TEST_SIGNAL:
        if signal.level2_done:
            return Decision("done", "tested")
        return Decision("push", "test") if around.devices else Decision("done", "no_device")
    # 4. Niveau 1 : la carte, des que la cause existe.
    if signal.level1_at is None:
        return Decision("app", "new")
    # 5. L'utilisateur a reagi a la carte : jamais d'escalade.
    if signal.closed_at is not None:
        return Decision("done", "closed")
    if signal.snoozed_until is not None:
        return Decision("done", "postponed")
    if signal.seen_at is not None:
        return Decision("done", "seen")
    # 6. Une notification par cause, jamais deux.
    if signal.level2_done:
        return Decision("done", "escalated")
    # 7. La carte a 24 h pour etre vue.
    deadline = signal.level1_at + LEVEL1_IGNORED_AFTER
    if now < deadline:
        return _wait("level1_pending", deadline, signal)
    # 8. Rien de sensible hors de l'application, et rien sans appareil abonne.
    if signal.data_class == "sensitive":
        return Decision("done", "sensitive")
    if around.devices == 0:
        return Decision("done", "no_device")
    # 9. Heures calmes : seulement pendant la plage de travail du jour, hors pauses.
    silence = quiet(around.frame, now)
    if silence is not None:
        reason, until = silence
        if reason == "day_off":
            return _wait(reason, around.next_day_start, signal)
        return _wait(reason, until or now + RECHECK, signal)
    # 10. Budget du jour.
    if around.pushes_today >= DAILY_PUSH_BUDGET:
        return _wait("budget", around.next_day_start, signal)
    return Decision("push", "ignored_24h")
