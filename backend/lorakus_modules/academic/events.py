"""Evenements consommes par academic (PR 46 et 49).

`planning.task_completed` : l'utilisateur a termine, depuis le chat, la tache d'un module.
Si c'est celle d'une evaluation, l'evaluation est terminee a son tour. Le handler tourne dans
le worker, dans une transaction liee a l'utilisateur de l'evenement (RLS), et la trace de sa
reussite est ecrite dans la meme transaction : il n'est pas rejoue apres une reussite, et le
rejouer serait sans effet.

`planning.task_estimated` (PR 49) : l'utilisateur a donne, depuis le chat, la duree de la
tache d'une evaluation. L'evaluation prend la meme : sa page et sa tache ne divergent pas.

Ils agissent meme si le module est desactive pour l'utilisateur : desactiver ne supprime pas les
donnees (comme pour l'export), et une evaluation restee ouverte alors que sa tache est
terminee serait fausse au retour.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from lorakus.core.events.bus import Event, on
from lorakus.core.planning.service import TASK_COMPLETED, TASK_ESTIMATED
from lorakus_modules.academic.service import MODULE_ID, on_task_completed, on_task_estimated


@on(TASK_COMPLETED, name="academic.task_completed")
async def task_completed(event: Event, session: AsyncSession) -> None:
    ref = event.payload.get("owner_ref")
    if event.payload.get("owner_module") != MODULE_ID or not isinstance(ref, str):
        return  # tache d'un autre module : rien a faire ici
    await on_task_completed(session, ref)


@on(TASK_ESTIMATED, name="academic.task_estimated")
async def task_estimated(event: Event, session: AsyncSession) -> None:
    ref = event.payload.get("owner_ref")
    if event.payload.get("owner_module") != MODULE_ID or not isinstance(ref, str):
        return
    await on_task_estimated(session, ref)
