"""core: recherche plein texte des faits (francais, sans accents)

Revision ID: 0011_core_memory_search
Revises: 0010_core_memory_embeddings
Create Date: 2026-11-13

- lorakus.fold_fr(text) : minuscules et accents retires, en SQL pur. L'extension `unaccent`
  aurait demande des droits de superutilisateur que le role de migration n'a pas (elle
  devrait passer par infra/postgres/init, qui ne s'execute qu'a la creation du volume).
- core_memory_facts.search_vector : colonne GENEREE par PostgreSQL (configuration `french`,
  racines : « s'appelle » -> « appel »). Toujours a jour, quel que soit le chemin d'ecriture.
- Pas d'index GIN : au plus 200 faits par utilisateur, deja filtres par la RLS.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011_core_memory_search"
down_revision: str | Sequence[str] | None = "0010_core_memory_embeddings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCENTED = "àâäáãåçéèêëíìîïñóòôöõúùûüýÿ"
PLAIN = "aaaaaaceeeeiiiinooooouuuuyy"


def upgrade() -> None:
    if len(ACCENTED) != len(PLAIN):
        raise ValueError("table de translitteration incoherente")
    op.execute(
        "CREATE FUNCTION lorakus.fold_fr(value text) RETURNS text "
        "LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE "
        "RETURN replace(replace(translate(lower(value), "
        f"'{ACCENTED}', '{PLAIN}'), 'œ', 'oe'), 'æ', 'ae')"
    )
    op.execute(
        "ALTER TABLE lorakus.core_memory_facts ADD COLUMN search_vector tsvector "
        "GENERATED ALWAYS AS (to_tsvector('french'::regconfig, lorakus.fold_fr(content))) STORED"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE lorakus.core_memory_facts DROP COLUMN search_vector")
    op.execute("DROP FUNCTION lorakus.fold_fr(text)")
