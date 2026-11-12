"""Disjoncteur par fournisseur d'IA.

Apres `threshold` echecs consecutifs, le fournisseur est ecarte pendant `cooldown_s` : les
questions suivantes passent directement au repli (fournisseur suivant ou reponse par
gabarit) au lieu d'attendre un delai d'expiration a chaque message. A la fin du delai, une
seule requete d'essai est laissee passer ; si elle reussit, le circuit se referme.

Etat en memoire, propre a chaque processus : l'API n'a qu'un processus, et un
redemarrage remet simplement le compteur a zero.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class _State:
    failures: int = 0
    opened_at: float | None = None
    probing: bool = False


@dataclass
class CircuitBreaker:
    threshold: int = 3
    cooldown_s: float = 120.0
    clock: Callable[[], float] = time.monotonic
    _states: dict[str, _State] = field(default_factory=dict[str, _State])

    def allows(self, provider: str) -> bool:
        """Vrai si on peut appeler ce fournisseur maintenant."""
        state = self._states.get(provider)
        if state is None or state.opened_at is None:
            return True
        if state.probing:
            return False  # une requete d'essai est deja en cours
        if self.clock() - state.opened_at >= self.cooldown_s:
            state.probing = True
            return True
        return False

    def success(self, provider: str) -> None:
        self._states[provider] = _State()

    def failure(self, provider: str) -> None:
        state = self._states.setdefault(provider, _State())
        state.failures += 1
        if state.probing or state.failures >= self.threshold:
            state.opened_at = self.clock()
            state.probing = False

    def abandoned(self, provider: str) -> None:
        """Requete interrompue sans verdict (client parti) : un nouvel essai reste possible."""
        state = self._states.get(provider)
        if state is not None:
            state.probing = False

    def is_open(self, provider: str) -> bool:
        state = self._states.get(provider)
        return state is not None and state.opened_at is not None
