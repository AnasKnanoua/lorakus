"""Evenement consomme par projects (PR 51).

`planning.task_completed` : l'utilisateur a termine, depuis le chat, la tache du planning
d'une tache de projet. Elle est terminee ici aussi, et le projet a bouge (il ne « dort »
plus). Le handler tourne dans le worker, sous la RLS de l'utilisateur de l'evenement ; il
agit meme si le module est desactive (les donnees doivent rester justes au retour).

`planning.task_estimated` n'est pas consomme : une tache de projet ne garde pas de duree
a elle, celle du planning fait foi.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from lorakus.core.events.bus import Event, on
from lorakus.core.planning.service import TASK_COMPLETED
from lorakus_modules.projects.service import MODULE_ID, on_task_completed


@on(TASK_COMPLETED, name="projects.task_completed")
async def task_completed(event: Event, session: AsyncSession) -> None:
    ref = event.payload.get("owner_ref")
    if event.payload.get("owner_module") != MODULE_ID or not isinstance(ref, str):
        return  # tache d'un autre module : rien a faire ici
    await on_task_completed(session, ref)
