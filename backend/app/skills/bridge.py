"""Late-bind helpers so handlers can use catalog without circular import."""
from __future__ import annotations

from typing import Any


def get_skill_catalog():
    from ..agent_skills import SKILL_CATALOG
    return SKILL_CATALOG


def charge_premium(db, user, skill_meta, default_cost=0.02, text: str = "", *, already_billed: bool = False):
    from ..agent_skills import _charge_premium
    return _charge_premium(db, user, skill_meta, default_cost, text=text, already_billed=already_billed)


def get_enabled_skill_ids(agent, db):
    from ..agent_skills import enabled_skill_ids
    return enabled_skill_ids(agent, db)


def set_enabled_skills(db, agent, skill_ids: list[str]) -> list[str]:
    """Lazy import — agent_skills imports handlers_all at module end."""
    from ..agent_skills import set_enabled_skills as _set
    return _set(db, agent, skill_ids)


def skills_for_template(template_type: str | None, catalog=None, *, role: str | None = None) -> list[str]:
    from ..skills_policy import skills_for_template as _fn
    return _fn(template_type, catalog if catalog is not None else get_skill_catalog(), role=role)


def skill_pack_for_template(template_type: str | None) -> str:
    from ..skills_policy import skill_pack_for_template as _fn
    return _fn(template_type) or ""


def skills_for_pack(pack: str, catalog=None, *, role: str | None = None) -> list[str]:
    from ..skills_policy import skills_for_pack as _fn
    return _fn(pack, catalog if catalog is not None else get_skill_catalog(), role=role)
