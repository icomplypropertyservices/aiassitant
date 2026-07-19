"""Field-level DB skill engine.

Generates add/change/delete skills per entity and per writable field from
entity specs (entities_crm / entities_workspace / entities_knowledge).

Wire FIELD_SKILL_HANDLER into agent_skills HANDLER_TABLE (meta mode) separately.
"""
from __future__ import annotations

from .crud import (
    _skill_db_field_dispatch,
    _skill_list_entity_fields,
    execute_field_skill,
)
from .registry import (
    all_field_skill_ids,
    build_catalog_entries,
    build_field_skill_catalog,
    get_all_entity_specs,
    get_entity,
    list_entities,
    parse_skill_id,
    resolve_field_skill,
)

FIELD_SKILL_HANDLER = "_skill_db_field_dispatch"

__all__ = [
    "get_all_entity_specs",
    "build_field_skill_catalog",
    "resolve_field_skill",
    "execute_field_skill",
    "FIELD_SKILL_HANDLER",
    # extras used by wiring / tests
    "parse_skill_id",
    "build_catalog_entries",
    "all_field_skill_ids",
    "get_entity",
    "list_entities",
    "_skill_db_field_dispatch",
    "_skill_list_entity_fields",
]
