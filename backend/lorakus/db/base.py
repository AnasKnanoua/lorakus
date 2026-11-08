"""Base des modeles SQLAlchemy : schema et conventions de nommage."""

from typing import Final

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

SCHEMA: Final = "lorakus"

# Noms de contraintes deterministes : indispensables pour que les migrations
# retrouvent et suppriment une contrainte de facon fiable.
NAMING_CONVENTION: Final = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Classe mere de tous les modeles de Lorakus.

    Le schema est explicite : les requetes ne dependent pas du search_path,
    qui pourrait etre detourne pour substituer une table piegee.
    """

    metadata = MetaData(schema=SCHEMA, naming_convention=NAMING_CONVENTION)
