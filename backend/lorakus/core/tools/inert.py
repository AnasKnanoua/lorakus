"""Texte inerte pour les blocs de donnees du prompt (PR 41, deplace dans le Core a la PR 51).

Tout texte qui vient de l'utilisateur ou de l'exterieur (souvenir, titre de tache, creneau
d'un calendrier, idee) et qui va au modele comme une DONNEE passe par `inert()` : il ne peut
ni fermer le bloc qui le contient, ni en ouvrir un autre, ni s'etaler sur plusieurs lignes.
Dans le Core pour que chaque module l'utilise sans importer le module `assistant`.
"""

import unicodedata
from typing import Final

# Chevrons de remplacement dans les blocs de donnees (PR 41) : U+2039 et U+203A, lisibles mais
# incapables d'ouvrir ou de fermer une balise. Ecrits en echappements (ruff RUF001).
SAFE_LT: Final = "\u2039"
SAFE_GT: Final = "\u203a"


def _chevron(char: str) -> str:
    """Remplacant d'un caractere qui se lit comme un chevron (« < », pleine chasse...)."""
    folded = unicodedata.normalize("NFKC", char)
    if "<" in folded:
        return SAFE_LT
    if ">" in folded:
        return SAFE_GT
    return char


def inert(text: str) -> str:
    """Texte rendu inerte pour un bloc de donnees du prompt (PR 41).

    Une seule ligne ; caracteres invisibles retires (largeur nulle, inversions de sens,
    controles) ; tout ce qui se lit comme « < » ou « > » (pleine chasse comprise) remplace par
    SAFE_LT et SAFE_GT. Aucune balise, connue ou non, imbriquee ou en majuscules, ne peut donc
    fermer le bloc ni en ouvrir un autre. Retirer seulement les balises connues etait
    contournable (« </fa</faits>its> », « </FAITS> », « </system> »).
    """
    visible = "".join(
        " " if unicodedata.category(c) in ("Cc", "Zl", "Zp") else c
        for c in text
        if unicodedata.category(c) != "Cf"
    )
    return "".join(_chevron(c) for c in " ".join(visible.split()))
