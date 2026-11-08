"""Demontre que les valeurs fournies par l'utilisateur sont envoyees comme parametres."""

from sqlalchemy import column, select, table
from sqlalchemy.dialects import postgresql

MALICIOUS = "x'; DROP TABLE users; --"


def test_user_value_is_sent_as_bound_parameter() -> None:
    users = table("users", column("email"))
    statement = select(users.c.email).where(users.c.email == MALICIOUS)

    compiled = statement.compile(dialect=postgresql.dialect())

    # La valeur n'apparait jamais dans le texte SQL...
    assert MALICIOUS not in str(compiled)
    # ...elle voyage a part, comme parametre.
    assert list(compiled.params.values()) == [MALICIOUS]
