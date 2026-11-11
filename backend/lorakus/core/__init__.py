"""Core platform : services communs a tous les modules.

Services prevus en phase 2 (ARCHITECTURE.md, section 3) : identity, modules, events, jobs,
tools, audit, agents. Les modules n'en utilisent que les ports publics.

Regle de dependance (verifiee par import-linter, voir pyproject.toml) : le Core n'importe
JAMAIS un module. Il les decouvre a l'execution par leurs entry points ``lorakus.modules``.
"""
