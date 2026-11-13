"""Taches de fond courtes, dans le processus de l'API, regroupees par cle (PR 36).

Usage : regrouper plusieurs evenements proches en un seul travail differe (ex. analyser une
conversation quelques minutes apres le dernier message). Une nouvelle demande pour la meme
cle repousse le travail tant qu'il attend encore ; une fois commence, il va jusqu'au bout et
la nouvelle demande est programmee a la suite.

Pourquoi pas le worker (Procrastinate) : ces travaux appellent le moteur IA, dont la cle n'est
donnee qu'au service api. Ils sont perdus a l'arret de l'API, ce qui est acceptable pour un
travail qui sera refait au prochain evenement (l'appelant garde son propre point de reprise).
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import structlog

log = structlog.get_logger("lorakus.background")


@dataclass
class _Entry:
    task: "asyncio.Task[None] | None" = None
    started: bool = False


class DebouncedTasks:
    """Une tache au plus en attente par cle ; les erreurs sont journalisees, jamais propagees."""

    def __init__(self) -> None:
        self._waiting: dict[str, _Entry] = {}
        self._all: set[asyncio.Task[None]] = set()

    def schedule(self, key: str, delay_s: float, factory: Callable[[], Awaitable[Any]]) -> None:
        """Programme `factory()` dans `delay_s` secondes, en remplacant l'attente en cours."""
        previous = self._waiting.pop(key, None)
        if previous is not None and not previous.started and previous.task is not None:
            previous.task.cancel()
        entry = _Entry()
        entry.task = asyncio.get_running_loop().create_task(self._run(key, delay_s, factory, entry))
        task = entry.task
        self._waiting[key] = entry
        self._all.add(task)
        task.add_done_callback(self._all.discard)

    async def _run(
        self,
        key: str,
        delay_s: float,
        factory: Callable[[], Awaitable[Any]],
        entry: _Entry,
    ) -> None:
        await asyncio.sleep(delay_s)
        entry.started = True
        if self._waiting.get(key) is entry:
            del self._waiting[key]
        try:
            await factory()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("background_task_failed", key=key.split(":", 1)[0])

    async def drain(self) -> None:
        """Attend la fin de tout ce qui est programme (tests, arret propre)."""
        while self._all:
            await asyncio.gather(*list(self._all), return_exceptions=True)

    async def close(self) -> None:
        """Arret de l'API : annule les attentes et les travaux en cours."""
        for task in list(self._all):
            task.cancel()
        await asyncio.gather(*list(self._all), return_exceptions=True)
        self._waiting.clear()
