"""Field-level DB skill registry: entity specs → skill ids, catalog, parsers.

Entity specs are loaded from sibling modules (entities_crm / entities_workspace /
entities_knowledge). Each module exports ENTITY_SPECS: dict[slug, spec].

Expected entity spec shape (all optional keys have safe defaults):

{
  "slug": "customer",
  "model": "Customer",                 # models.<name>
  "label": "Customer",
  "category": "crm",
  "id_arg": "customer_id",             # primary id arg for change/delete
  "owner_col": "owner_user_id",        # direct ownership column (preferred)
  "owner_via": {                       # OR parent-chain ownership
      "model": "Customer",
      "fk": "customer_id",
      "owner_col": "owner_user_id",
  },
  "writable": ["name", "email", ...],
  "create_required": ["name"],
  "field_types": {"tags": "tags", "annual_value": "float"},  # optional
  "aliases": {
      "add": ["create_customer"],
      "change": ["update_customer"],
      "delete": [],
  },
  "description": "optional entity blurb",
}
"""
from __future__ import annotations

from typing import Any

# ── Load entity packs (graceful if parallel agents haven't landed files yet) ─

def _load_entity_pack(module_name: str) -> dict[str, dict]:
    try:
        mod = __import__(
            f"backend.app.skills.db_fields.{module_name}",
            fromlist=["ENTITY_SPECS"],
        )
        specs = getattr(mod, "ENTITY_SPECS", None)
        if isinstance(specs, dict):
            return dict(specs)
    except Exception:
        pass
    # Relative package import (preferred when running as app.skills.db_fields)
    try:
        from importlib import import_module

        mod = import_module(f".{module_name}", package=__package__)
        specs = getattr(mod, "ENTITY_SPECS", None)
        if isinstance(specs, dict):
            return dict(specs)
    except Exception:
        pass
    return {}


def _merge_specs(*packs: dict[str, dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for pack in packs:
        for slug, spec in (pack or {}).items():
            if not isinstance(spec, dict):
                continue
            s = dict(spec)
            s.setdefault("slug", slug)
            s["slug"] = str(s.get("slug") or slug).strip().lower()
            if not s["slug"]:
                continue
            s.setdefault("model", s["slug"].title().replace("_", ""))
            s.setdefault("label", s["slug"].replace("_", " ").title())
            s.setdefault("category", "database")
            s.setdefault("id_arg", f"{s['slug']}_id")
            s.setdefault("owner_col", "owner_user_id")
            s.setdefault("owner_via", None)
            s.setdefault("writable", [])
            s.setdefault("create_required", [])
            s.setdefault("field_types", {})
            s.setdefault("aliases", {})
            s.setdefault("description", "")
            # Normalize lists
            s["writable"] = [str(f).strip() for f in (s["writable"] or []) if str(f).strip()]
            s["create_required"] = [
                str(f).strip() for f in (s["create_required"] or []) if str(f).strip()
            ]
            aliases = s.get("aliases") or {}
            if not isinstance(aliases, dict):
                aliases = {}
            norm_aliases: dict[str, list[str]] = {}
            for action in ("add", "change", "delete"):
                raw = aliases.get(action) or aliases.get(
                    {"add": "create", "change": "update", "delete": "delete"}.get(action, action)
                ) or []
                if isinstance(raw, str):
                    raw = [raw]
                norm_aliases[action] = [str(a).strip() for a in raw if str(a).strip()]
            s["aliases"] = norm_aliases
            out[s["slug"]] = s
    return out


ALL_ENTITY_SPECS: dict[str, dict] = _merge_specs(
    _load_entity_pack("entities_crm"),
    _load_entity_pack("entities_workspace"),
    _load_entity_pack("entities_knowledge"),
)

_FIELD_ROLES = ["orchestrator", "lead", "member", "specialist"]
_ENTITY_DELETE_ROLES = ["orchestrator", "lead", "member"]  # no specialist for destructive delete

_FORBIDDEN_EXACT = frozenset(
    {
        "password_hash",
        "token_hash",
        "api_key_hash",
        "jwt_secret",
        "jwt_secrets",
        "secret",
        "secrets",
        "id",
        "created_at",
    }
)
_FORBIDDEN_PREFIXES = ("encrypted_", "password", "token_hash", "api_key", "jwt_")
_FORBIDDEN_SUBSTRINGS = (
    "password_hash",
    "encrypted_",
    "token_hash",
    "api_key_hash",
    "jwt_secret",
)


def _is_forbidden_field(name: str) -> bool:
    n = (name or "").strip().lower()
    if not n or n in _FORBIDDEN_EXACT:
        return True
    if any(n.startswith(p) for p in _FORBIDDEN_PREFIXES):
        return True
    if any(s in n for s in _FORBIDDEN_SUBSTRINGS):
        return True
    return False


def _safe_writable(spec: dict) -> list[str]:
    return [f for f in (spec.get("writable") or []) if not _is_forbidden_field(f)]


def get_entity(slug: str) -> dict | None:
    if not slug:
        return None
    return ALL_ENTITY_SPECS.get(str(slug).strip().lower())


def list_entities() -> list[dict]:
    return [dict(s) for s in ALL_ENTITY_SPECS.values()]


def get_all_entity_specs() -> dict[str, dict]:
    """Public snapshot of merged entity specs."""
    return {k: dict(v) for k, v in ALL_ENTITY_SPECS.items()}


def _alias_index() -> dict[str, dict]:
    """Map alias skill_id → parsed action dict."""
    idx: dict[str, dict] = {}
    for slug, spec in ALL_ENTITY_SPECS.items():
        aliases = spec.get("aliases") or {}
        for action, names in aliases.items():
            for name in names or []:
                key = str(name).strip()
                if not key:
                    continue
                idx[key] = {
                    "action": action,
                    "entity": slug,
                    "field": None,
                    "raw": key,
                    "via_alias": True,
                }
    return idx


def _canonical_skill_id(action: str, entity: str, field: str | None = None) -> str:
    if field:
        return f"{action}_{entity}_{field}"
    return f"{action}_{entity}"


def parse_skill_id(skill_id: str) -> dict | None:
    """Parse a field/entity skill id.

    Returns {action, entity, field, raw} or None if not a known field skill.
    Also resolves create_*/update_* aliases listed on entity specs.
    """
    if not skill_id or not isinstance(skill_id, str):
        return None
    raw = skill_id.strip()
    if not raw:
        return None

    # Explicit discovery skill is not a field op
    if raw == "list_db_fields":
        return {
            "action": "list",
            "entity": None,
            "field": None,
            "raw": raw,
        }

    # Alias first (create_customer → add customer)
    alias = _alias_index().get(raw)
    if alias:
        return dict(alias)

    # Canonical: add|change|delete_<entity>[_<field...>]
    for action in ("add", "change", "delete"):
        prefix = f"{action}_"
        if not raw.startswith(prefix):
            continue
        rest = raw[len(prefix) :]
        if not rest:
            return None
        # Prefer longest entity slug match so "customer_activity" wins over "customer"
        candidates = sorted(ALL_ENTITY_SPECS.keys(), key=len, reverse=True)
        for slug in candidates:
            if rest == slug:
                return {
                    "action": action,
                    "entity": slug,
                    "field": None,
                    "raw": raw,
                }
            if rest.startswith(slug + "_"):
                field = rest[len(slug) + 1 :]
                if field:
                    return {
                        "action": action,
                        "entity": slug,
                        "field": field,
                        "raw": raw,
                    }
        return None

    return None


def build_catalog_entries() -> list[dict]:
    """Build catalog dicts for all entity + field skills (+ list_db_fields)."""
    entries: list[dict] = []
    # Discovery
    entries.append(
        {
            "id": "list_db_fields",
            "name": "List DB field skills",
            "description": (
                "Discover all field-level database entities and writable fields "
                "available as add/change/delete skills."
            ),
            "args": [],
            "roles": list(_FIELD_ROLES),
            "category": "database",
            "premium": False,
            "field_skill": True,
        }
    )

    for slug, spec in ALL_ENTITY_SPECS.items():
        label = spec.get("label") or slug.replace("_", " ").title()
        category = spec.get("category") or "database"
        id_arg = spec.get("id_arg") or f"{slug}_id"
        writable: list[str] = _safe_writable(spec)
        create_required: list[str] = [
            f for f in (spec.get("create_required") or []) if not _is_forbidden_field(f)
        ]
        ent_desc = (spec.get("description") or "").strip()

        # Entity-level add
        add_args = list(dict.fromkeys([*create_required, *writable]))
        entries.append(
            {
                "id": f"add_{slug}",
                "name": f"Add {label}",
                "description": ent_desc or f"Create a new {label} record.",
                "args": add_args,
                "roles": list(_FIELD_ROLES),
                "category": category,
                "premium": False,
                "field_skill": True,
            }
        )
        # Entity-level change
        entries.append(
            {
                "id": f"change_{slug}",
                "name": f"Change {label}",
                "description": f"Update one or more fields on a {label} record.",
                "args": [id_arg, *writable],
                "roles": list(_FIELD_ROLES),
                "category": category,
                "premium": False,
                "field_skill": True,
            }
        )
        # Entity-level delete
        entries.append(
            {
                "id": f"delete_{slug}",
                "name": f"Delete {label}",
                "description": f"Permanently delete a {label} record.",
                "args": [id_arg],
                "roles": list(_ENTITY_DELETE_ROLES),
                "category": category,
                "premium": False,
                "field_skill": True,
            }
        )

        # Aliases as catalog entries (same semantics)
        aliases = spec.get("aliases") or {}
        for action, names in aliases.items():
            for name in names or []:
                if not name or name in {e["id"] for e in entries}:
                    continue
                base = next(
                    (e for e in entries if e["id"] == _canonical_skill_id(action, slug)),
                    None,
                )
                if not base:
                    continue
                alias_entry = dict(base)
                alias_entry["id"] = name
                alias_entry["name"] = f"{base['name']} ({name})"
                alias_entry["description"] = (
                    f"Alias for {base['id']}. " + (base.get("description") or "")
                )
                entries.append(alias_entry)

        # Field-level skills
        for field in writable:
            flabel = field.replace("_", " ")
            entries.append(
                {
                    "id": f"add_{slug}_{field}",
                    "name": f"Add {label} {flabel}",
                    "description": (
                        f"Set or append the '{field}' field on a {label} "
                        f"(tags-like fields append; others set)."
                    ),
                    "args": [id_arg, "value"],
                    "roles": list(_FIELD_ROLES),
                    "category": category,
                    "premium": False,
                    "field_skill": True,
                }
            )
            entries.append(
                {
                    "id": f"change_{slug}_{field}",
                    "name": f"Change {label} {flabel}",
                    "description": f"Replace the '{field}' field on a {label}.",
                    "args": [id_arg, "value"],
                    "roles": list(_FIELD_ROLES),
                    "category": category,
                    "premium": False,
                    "field_skill": True,
                }
            )
            entries.append(
                {
                    "id": f"delete_{slug}_{field}",
                    "name": f"Clear {label} {flabel}",
                    "description": f"Clear/reset the '{field}' field on a {label}.",
                    "args": [id_arg],
                    "roles": list(_FIELD_ROLES),
                    "category": category,
                    "premium": False,
                    "field_skill": True,
                }
            )

    return entries


def build_field_skill_catalog() -> list[dict]:
    """Alias used by package public API."""
    return build_catalog_entries()


def all_field_skill_ids() -> set[str]:
    return {e["id"] for e in build_catalog_entries()}


def resolve_field_skill(skill_id: str) -> dict | None:
    """Return parsed action if skill_id is a registered field skill, else None.

    Unknown/unregistered skill ids return None even if they look like add_x_y.
    list_db_fields is included as a discovery skill.
    """
    if not skill_id:
        return None
    sid = str(skill_id).strip()
    if sid == "list_db_fields":
        return {"action": "list", "entity": None, "field": None, "raw": sid}

    ids = all_field_skill_ids()
    if sid not in ids:
        # Still try parse against known entities (aliases already in ids)
        parsed = parse_skill_id(sid)
        if not parsed or parsed.get("action") == "list":
            return None
        # Only accept if entity is registered
        if parsed.get("entity") not in ALL_ENTITY_SPECS:
            return None
        # Field must be writable when present
        if parsed.get("field"):
            spec = ALL_ENTITY_SPECS[parsed["entity"]]
            if parsed["field"] not in _safe_writable(spec):
                return None
        return parsed
    return parse_skill_id(sid)


def reload_entity_specs() -> dict[str, dict]:
    """Re-import entity packs (useful in tests after creating modules)."""
    global ALL_ENTITY_SPECS
    ALL_ENTITY_SPECS = _merge_specs(
        _load_entity_pack("entities_crm"),
        _load_entity_pack("entities_workspace"),
        _load_entity_pack("entities_knowledge"),
    )
    return get_all_entity_specs()


__all__ = [
    "ALL_ENTITY_SPECS",
    "get_entity",
    "list_entities",
    "get_all_entity_specs",
    "parse_skill_id",
    "build_catalog_entries",
    "build_field_skill_catalog",
    "all_field_skill_ids",
    "resolve_field_skill",
    "reload_entity_specs",
]
