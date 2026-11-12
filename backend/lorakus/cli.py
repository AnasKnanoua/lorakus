"""Commandes d'administration, a lancer sur le serveur.

    python -m lorakus.cli create-owner
    python -m lorakus.cli enable-second-factor    (obligatoire en production, PR 35)
    python -m lorakus.cli recover-second-factor   (telephone et codes de secours perdus)

Le mot de passe est lu au clavier (getpass), jamais en argument : un argument finirait
dans l'historique du shell et serait visible par tous dans la liste des processus (ps).
"""

import argparse
import asyncio
import getpass
import sys

from lorakus.core.identity.passwords import WeakPasswordError, check_policy
from lorakus.core.identity.service import (
    ConflictError,
    IdentityService,
    InvalidCredentialsError,
    OwnerAlreadyExistsError,
)
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


async def _recover(email: str) -> bool:
    settings = get_settings()
    database = Database.connect(settings)
    try:
        done = await IdentityService(database, settings).recover_second_factor(email)
    finally:
        await database.close()
    print(
        "Double authentification desactivee. A reactiver : python -m lorakus.cli "
        "enable-second-factor (obligatoire en production pour se connecter)."
        if done
        else "Refuse : compte inconnu.",
        file=sys.stdout if done else sys.stderr,
    )
    return done


async def _enable_second_factor(email: str) -> bool:
    """Active la double authentification d'un compte depuis le serveur.

    En production, un compte sans double authentification ne peut plus ouvrir de session :
    l'activation se fait donc ici. Le secret s'affiche une seule fois, a saisir dans une
    application d'authentification (Aegis, 2FAS, Google Authenticator...).
    """
    settings = get_settings()
    database = Database.connect(settings)
    try:
        identity = IdentityService(database, settings)
        account = await identity.account_for_admin(email)
        if account is None:
            print("Refuse : compte inconnu ou inactif.", file=sys.stderr)
            return False
        try:
            secret, uri = await identity.totp_setup(account)
        except ConflictError:
            print("Refuse : la double authentification est deja active.", file=sys.stderr)
            return False
        print("Dans ton application d'authentification, ajoute un compte avec cette cle :")
        print(f"  {' '.join(secret[i : i + 4] for i in range(0, len(secret), 4))}")
        print(f"(ou cette adresse : {uri})")
        for _attempt in range(3):
            # Saisie dans un fil a part : la boucle asyncio (connexions a la base) reste libre.
            prompt = "Code a 6 chiffres affiche par l'application : "
            code = (await asyncio.to_thread(input, prompt)).strip()
            try:
                codes = await identity.totp_confirm(account, code, None)
            except InvalidCredentialsError:
                print("Code incorrect.", file=sys.stderr)
                continue
            print("Double authentification active. Codes de secours (usage unique) :")
            for backup in codes:
                print(f"  {backup}")
            print("Range-les dans ton gestionnaire de mots de passe : ils ne seront plus affiches.")
            return True
        print("Refuse : trois codes incorrects. Relance la commande.", file=sys.stderr)
        return False
    finally:
        await database.close()


def main(argv: list[str] | None = None) -> int:
    """Point d'entree. Renvoie le code de sortie."""
    parser = argparse.ArgumentParser(prog="lorakus.cli", description="Administration de Lorakus")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("create-owner", help="Cree le compte proprietaire (une seule fois)")
    commands.add_parser(
        "enable-second-factor",
        help="Active la double authentification d'un compte (obligatoire en production)",
    )
    commands.add_parser(
        "recover-second-factor",
        help="Desactive la double authentification d'un compte et ferme ses sessions",
    )
    args = parser.parse_args(argv)

    email = input("Adresse e-mail : ")
    if args.command == "recover-second-factor":
        return 0 if asyncio.run(_recover(email)) else 1
    if args.command == "enable-second-factor":
        return 0 if asyncio.run(_enable_second_factor(email)) else 1
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
