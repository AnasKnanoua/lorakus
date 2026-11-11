"""Cree un module a partir de lorakus_modules/_template (MODULE_SYSTEM.md §8).

    uv run python scripts/new_module.py ID PREFIXE "Nom affiche"
    ex. : uv run python scripts/new_module.py academic acad "Academic Manager"

Ce que fait le script :
1. copie le gabarit dans lorakus_modules/ID en remplacant les noms ;
2. declare le module (entry point) dans pyproject.toml ;
3. ajoute sa branche de migrations a alembic.ini.
Il refuse d'ecraser un module existant. Ensuite : uv sync, puis make check.
"""

import argparse
import re
import shutil
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
TEMPLATE = BACKEND / "lorakus_modules" / "_template"
ENTRY_SECTION = '[project.entry-points."lorakus.modules"]'


def _camel(module_id: str) -> str:
    return "".join(part.capitalize() for part in module_id.split("_"))


def render(text: str, module_id: str, prefix: str, display_name: str) -> str:
    """Remplace les noms du gabarit (l'ordre compte : du plus precis au plus general)."""
    replacements = [
        ("lorakus_modules._template", f"lorakus_modules.{module_id}"),
        ("Module Template", f"Module {display_name}"),
        ('name="Template"', f'name="{display_name}"'),
        ('label="Template"', f'label="{display_name}"'),
        ("TemplateConfig", f"{_camel(module_id)}Config"),
        ("TemplateItem", f"{_camel(module_id)}Item"),
        ("template_0001", f"{module_id}_0001"),
        ("tpl_", f"{prefix}_"),
        ('route="/template"', f'route="/{module_id.replace("_", "-")}"'),
        ("/api/v1/template", f"/api/v1/{module_id}"),
        ("Template", display_name),
        ("template", module_id),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def add_entry_point(pyproject: Path, module_id: str) -> None:
    content = pyproject.read_text("utf-8")
    line = f'{module_id} = "lorakus_modules.{module_id}.manifest:manifest"'
    if line in content:
        return
    if ENTRY_SECTION not in content:
        content = content.rstrip("\n") + f"\n\n# Modules decouverts par le Core.\n{ENTRY_SECTION}\n"
    content = content.replace(ENTRY_SECTION, f"{ENTRY_SECTION}\n{line}", 1)
    pyproject.write_text(content, "utf-8")


def add_version_location(alembic_ini: Path, module_id: str) -> None:
    content = alembic_ini.read_text("utf-8")
    location = f"%(here)s/lorakus_modules/{module_id}/migrations"
    match = re.search(r"^version_locations = (.*)$", content, flags=re.MULTILINE)
    if match is None:
        raise SystemExit("alembic.ini : ligne version_locations introuvable")
    if location in match.group(1):
        return
    updated = f"version_locations = {match.group(1)}:{location}"
    alembic_ini.write_text(content.replace(match.group(0), updated, 1), "utf-8")


def create(module_id: str, prefix: str, display_name: str, backend: Path = BACKEND) -> Path:
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,30}", module_id) or module_id == "template":
        raise SystemExit(f"id invalide : {module_id}")
    if not re.fullmatch(r"[a-z][a-z0-9]{1,9}", prefix) or prefix == "core":
        raise SystemExit(f"prefixe invalide : {prefix} (2 a 10 minuscules ou chiffres, pas core)")
    target = backend / "lorakus_modules" / module_id
    if target.exists():
        raise SystemExit(f"le module existe deja : {target}")
    shutil.copytree(TEMPLATE, target, ignore=shutil.ignore_patterns("__pycache__", "README.md"))
    for path in sorted(target.rglob("*.py")):
        path.write_text(render(path.read_text("utf-8"), module_id, prefix, display_name), "utf-8")
        renamed = path.with_name(render(path.name, module_id, prefix, display_name))
        if renamed != path:
            path.rename(renamed)
    add_entry_point(backend / "pyproject.toml", module_id)
    add_version_location(backend / "alembic.ini", module_id)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("module_id")
    parser.add_argument("prefix", help="prefixe des tables, sans le _ final (ex. acad)")
    parser.add_argument("display_name")
    args = parser.parse_args(argv)
    target = create(args.module_id, args.prefix, args.display_name)
    print(f"Module cree : {target.relative_to(BACKEND)}")
    print("Ensuite : uv sync (enregistre le module), puis make check.")
    print(f"Documentation a ecrire : docs/modules/{args.module_id}.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
