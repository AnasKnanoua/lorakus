"""Profil du Sergent (PR 50, ADR 0025 et 0026) : la journee et les echeances.

Aucun LLM : les rapports sont des regles (reports.py), calcules en quelques millisecondes
a partir des donnees du planning (Core), sous la RLS de l'utilisateur. Le Majordome les
recoit comme des donnees et repond en un seul appel au modele, sans relire la journee
par un outil : c'est ce qui tient le scenario 1 sous 5 s.

Routage (ADR 0025) : d'abord les mots-cles, ecrits sur la partie `tuning` de
tests/evals/sergent_routing.json ; puis les phrases d'exemple (palier 2). La partie `measure`
de ce jeu ne sert qu'a mesurer.
"""

from typing import Final

from lorakus.core.agents.contract import SpecialistContext, SpecialistProfile, SpecialistReport
from lorakus.core.planning.today import read_today
from lorakus_modules.focus.reports import day_report, deadlines_report

KEYWORDS: Final[dict[str, list[str]]] = {
    "day_plan": [
        "aujourd'hui",
        "aujourdhui",
        "ma journee",
        "programme",
        "planning",
        "planifie",
        "planifier",
        "organise",
        "organiser",
        "ce soir",
        "ce matin",
        "cet apres midi",
        "cet aprem",
        "je fais quoi",
        "par quoi",
        "je commence",
    ],
    "deadlines": [
        "echeance",
        "echeances",
        "deadline",
        "deadlines",
        "a rendre",
        "en retard",
        "examen",
        "examens",
        "partiel",
        "partiels",
        "il me reste combien",
    ],
}
EXAMPLES: Final[dict[str, list[str]]] = {
    "day_plan": [
        "Qu'est-ce que je dois faire aujourd'hui ?",
        "C'est quoi mon programme ?",
        "Organise ma journée",
        "Je fais quoi maintenant ?",
        "Par quoi je commence ?",
        "Qu'est-ce qui m'attend cet après-midi ?",
    ],
    "deadlines": [
        "Quelles sont mes échéances ?",
        "J'ai des trucs à rendre cette semaine ?",
        "Qu'est-ce qui est en retard ?",
        "C'est quand mon prochain examen ?",
        "Il me reste combien de temps pour le devoir ?",
    ],
}


async def handle(ctx: SpecialistContext) -> SpecialistReport:
    async with ctx.open_transaction() as session:
        view = await read_today(session, ctx.now)
    if ctx.request.intent == "day_plan":
        return day_report(view)
    return deadlines_report(view)


PROFILE: Final = SpecialistProfile(
    name="focus",
    display_name="Sergent",
    intents=["day_plan", "deadlines"],
    max_report_class="personal",
    llm_usage="none",
    timeout_s=2.0,
    actions=["focus.split_task"],
    limits=(
        "Ne suppose aucune heure ni aucune durée ; ne place rien sans la journée donnée par "
        "l'utilisateur ; ne modifie rien lui-même (le découpage passe par une carte) ; ne "
        "voit que les tâches, l'agenda et la journée."
    ),
    handler=handle,
    keywords=KEYWORDS,
    examples=EXAMPLES,
)
