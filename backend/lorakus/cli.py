"""Commandes d'administration, a lancer sur le serveur.

    python -m lorakus.cli create-owner

Le mot de passe est lu au clavier (getpass), jamais en argument : un argument finirait
dans l'historique du shell et serait visible par tous dans la liste des processus (ps).
"""

import argparse
import asyncio
import getpass
import sys

from lorakus.core.identity.passwords import WeakPasswordError, check_policy
from lorakus.core.identity.service import IdentityService, OwnerAlreadyExistsError
from lorakus.db.database import Database
from lorakus.settings import get_settings


def _read_password() -> str:
    first = getpass.getpass("Mot de passe (12 caracteres au moins) : ")
    check_policy(first)
    if getpass.getpass("Confirmation : ") != first:
        raise WeakPasswordError("Les deux saisies different.")
    return first


async def _create_owner(email: str, password: str) -> None:
    settings = get_settings()
    database = Database.connect(settings)
    try:
        user_id = await IdentityService(database, settings).create_owner(email, password)
    finally:
        await database.close()
    print(f"Proprietaire cree : {user_id}")


def main(argv: list[str] | None = None) -> int:
    """Point d'entree. Renvoie le code de sortie."""
    parser = argparse.ArgumentParser(prog="lorakus.cli", description="Administration de Lorakus")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("create-owner", help="Cree le compte proprietaire (une seule fois)")
    parser.parse_args(argv)

    email = input("Adresse e-mail : ")
    try:
        password = _read_password()
        asyncio.run(_create_owner(email, password))
    except (WeakPasswordError, ValueError) as error:
        print(f"Refuse : {error}", file=sys.stderr)
        return 1
    except OwnerAlreadyExistsError:
        print("Refuse : un proprietaire existe deja.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
