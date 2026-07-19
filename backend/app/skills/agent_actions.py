"""Full agent action skillset: entity CRUD + per-field add/change/delete.

Every writable column on models.Agent gets three skills:
  add_agent_<field>    — set value (append for tags-like strings when append=true)
  change_agent_<field> — replace value
  delete_agent_<field> — clear value (empty string / null / false / 0 by type)

Entity-level skills:
  add_agent / create_agent / get_agent / change_agent / update_agent / delete_agent
  reparent_agent / demote_agent / rename_agent / set_agent_field (generic)
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from ..agent_roles import is_orchestrator, normalize_role

# Writable Agent columns (exclude id, user_id, created_at — ownership/system).
AGENT_FIELD_SPEC: dict[str, dict[str, Any]] = {
    "name": {
        "type": "str",
        "clearable": False,
        "required_on_create": True,
        "description": "Display name",
    },
    "template_type": {
        "type": "str",
        "clearable": True,
        "description": "Role template (sales, support, custom, …)",
    },
    "personality": {
        "type": "str",
        "clearable": True,
        "description": "System personality / tone",
    },
    "model": {
        "type": "str",
        "clearable": False,
        "description": "LLM model / tier id",
    },
    "status": {
        "type": "str",
        "clearable": False,
        "description": "active | paused | offline",
    },
    "idle_mode": {
        "type": "str",
        "clearable": False,
        "description": "never_idle | allow_idle | always_idle",
    },
    "hierarchy_role": {
        "type": "str",
        "clearable": False,
        "description": "orchestrator | lead | member | specialist",
    },
    "is_lead": {
        "type": "bool",
        "clearable": True,
        "description": "Whether agent is a lead",
    },
    "permission_level": {
        "type": "str",
        "clearable": False,
        "description": "viewer | operator | lead | admin",
    },
    "company_id": {
        "type": "int",
        "clearable": True,
        "description": "Linked company id",
    },
    "project_id": {
        "type": "int",
        "clearable": True,
        "description": "Linked project id",
    },
    "parent_id": {
        "type": "int",
        "clearable": True,
        "description": "Reports-to agent id",
    },
    "escalate_when": {
        "type": "str",
        "clearable": True,
        "description": "Escalation trigger rule",
    },
    "escalate_reason": {
        "type": "str",
        "clearable": True,
        "description": "Custom escalation notes",
    },
    "escalate_to": {
        "type": "str",
        "clearable": True,
        "description": "parent | orchestrator | human | owner",
    },
    "escalate_human_id": {
        "type": "int",
        "clearable": True,
        "description": "Human id for escalate_to=human",
    },
    "config": {
        "type": "str",
        "clearable": True,
        "description": "JSON config blob (string)",
    },
}

AGENT_WRITABLE_FIELDS: tuple[str, ...] = tuple(AGENT_FIELD_SPEC.keys())

_ROLES_ALL = ["orchestrator", "lead", "member", "specialist"]
_ROLES_LEAD = ["orchestrator", "lead"]
_ROLES_ORCH = ["orchestrator"]

_PROTECTED_HIERARCHY = frozenset({"hierarchy_role", "is_lead", "parent_id", "permission_level"})


def _empty_for(field: str) -> Any:
    t = AGENT_FIELD_SPEC[field]["type"]
    if t == "bool":
        return False
    if t == "int":
        return None
    if t == "float":
        return 0.0
    if field == "config":
        return "{}"
    return ""


def _coerce(field: str, value: Any) -> Any:
    if value is None:
        return _empty_for(field)
    t = AGENT_FIELD_SPEC[field]["type"]
    if t == "int":
        if value in ("", "null", "none", "None"):
            return None
        return int(value)
    if t == "float":
        return float(value)
    if t == "bool":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on", "y")
    if t == "str":
        if field == "config" and isinstance(value, (dict, list)):
            return json.dumps(value)
        return str(value)
    return value


def _resolve_target(
    db: Session,
    actor: models.Agent,
    user: models.User,
    args: dict,
    *,
    allow_self: bool = True,
) -> models.Agent | dict:
    raw = (
        args.get("target_agent_id")
        or args.get("agent_id")
        or args.get("id")
    )
    if raw in (None, "", "self", "me") and allow_self:
        return actor
    try:
        aid = int(raw)
    except (TypeError, ValueError):
        return {"ok": False, "error": "target_agent_id or agent_id required"}
    tgt = db.get(models.Agent, aid)
    if not tgt or tgt.user_id != user.id:
        return {"ok": False, "error": "Agent not found or not owned"}
    return tgt


def _can_mutate_target(actor: models.Agent, tgt: models.Agent) -> str | None:
    """Return error string if actor may not mutate target."""
    if tgt.id == actor.id:
        return None
    if is_orchestrator(actor):
        return None
    role = normalize_role(actor)
    if role == "lead":
        # Lead may edit self + direct reports
        if tgt.parent_id == actor.id or tgt.id == actor.id:
            return None
        return "Leads may only change themselves or direct reports"
    if role in ("member", "specialist"):
        if tgt.id == actor.id:
            return None
        return "Members may only change their own agent fields"
    return "Not allowed to change this agent"


# Keys that live on agent.config but are not free-form custom fields
_CONFIG_RESERVED_KEYS = frozenset({
    "autonomy",
    "custom_fields",
    "skills",
    "enabled_skills",
    "integrations",
    "model_override",
    "system",
})


def _parse_agent_config(a: models.Agent) -> dict[str, Any]:
    raw = a.config or "{}"
    try:
        cfg = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception:
        cfg = {}
    return dict(cfg) if isinstance(cfg, dict) else {}


def _normalize_field_key(key: Any) -> str | None:
    if key is None:
        return None
    k = str(key).strip()
    if not k:
        return None
    # Allow letters, digits, underscore, hyphen, spaces → normalize spaces to _
    safe = []
    for ch in k:
        if ch.isalnum() or ch in ("_", "-", "."):
            safe.append(ch)
        elif ch in (" ", "\t"):
            safe.append("_")
    out = "".join(safe).strip("._-")
    if not out or out.lower() in _CONFIG_RESERVED_KEYS:
        return None
    if len(out) > 64:
        out = out[:64]
    return out


def get_custom_fields(a: models.Agent, *, include_legacy: bool = True) -> dict[str, Any]:
    """Return agent custom fields map from config.custom_fields (+ legacy top-level keys)."""
    cfg = _parse_agent_config(a)
    fields: dict[str, Any] = {}
    nested = cfg.get("custom_fields")
    if isinstance(nested, dict):
        for k, v in nested.items():
            nk = _normalize_field_key(k)
            if nk:
                fields[nk] = v
    if include_legacy:
        for k, v in cfg.items():
            if k in _CONFIG_RESERVED_KEYS or k == "custom_fields":
                continue
            nk = _normalize_field_key(k)
            if nk and nk not in fields:
                fields[nk] = v
    return fields


def set_custom_fields_map(a: models.Agent, fields: dict[str, Any]) -> dict[str, Any]:
    """Replace config.custom_fields with the given map. Preserves other config keys."""
    cfg = _parse_agent_config(a)
    clean: dict[str, Any] = {}
    for k, v in (fields or {}).items():
        nk = _normalize_field_key(k)
        if not nk:
            continue
        clean[nk] = v
    cfg["custom_fields"] = clean
    a.config = json.dumps(cfg)
    return clean


def upsert_custom_field(a: models.Agent, key: str, value: Any) -> dict[str, Any]:
    nk = _normalize_field_key(key)
    if not nk:
        return {"ok": False, "error": f"Invalid custom field key '{key}'"}
    fields = get_custom_fields(a, include_legacy=True)
    fields[nk] = value
    set_custom_fields_map(a, fields)
    return {"ok": True, "key": nk, "value": value, "custom_fields": fields}


def remove_custom_field(a: models.Agent, key: str) -> dict[str, Any]:
    nk = _normalize_field_key(key)
    if not nk:
        return {"ok": False, "error": f"Invalid custom field key '{key}'"}
    cfg = _parse_agent_config(a)
    fields = get_custom_fields(a, include_legacy=True)
    if nk not in fields:
        return {"ok": False, "error": f"Custom field '{nk}' not found", "custom_fields": fields}
    del fields[nk]
    # Also drop legacy top-level key if present
    if nk in cfg and nk not in _CONFIG_RESERVED_KEYS:
        cfg.pop(nk, None)
    cfg["custom_fields"] = fields
    a.config = json.dumps(cfg)
    return {"ok": True, "key": nk, "deleted": True, "custom_fields": fields}


def _agent_out(a: models.Agent) -> dict[str, Any]:
    cf = get_custom_fields(a)
    return {
        "id": a.id,
        "name": a.name,
        "template_type": a.template_type,
        "hierarchy_role": a.hierarchy_role,
        "is_lead": bool(a.is_lead),
        "status": a.status,
        "idle_mode": a.idle_mode,
        "model": a.model,
        "permission_level": a.permission_level,
        "company_id": a.company_id,
        "project_id": a.project_id,
        "parent_id": a.parent_id,
        "personality": (a.personality or "")[:500],
        "escalate_when": a.escalate_when,
        "escalate_reason": a.escalate_reason,
        "escalate_to": a.escalate_to,
        "escalate_human_id": a.escalate_human_id,
        "config": (a.config or "")[:2000],
        "custom_fields": cf,
    }


def _apply_field(
    tgt: models.Agent,
    field: str,
    value: Any,
    *,
    action: str,
    append: bool = False,
) -> dict[str, Any]:
    if field not in AGENT_FIELD_SPEC:
        return {"ok": False, "error": f"Unknown agent field '{field}'"}
    spec = AGENT_FIELD_SPEC[field]

    # Protect orchestrator identity
    if is_orchestrator(tgt) and field in ("hierarchy_role", "status") and action == "change":
        if field == "hierarchy_role" and str(value).lower() not in ("orchestrator",):
            return {"ok": False, "error": "Cannot change orchestrator hierarchy_role"}
        if field == "status" and str(value).lower() in ("deleted",):
            return {"ok": False, "error": "Cannot delete orchestrator via status"}

    if action == "delete":
        if not spec.get("clearable", True):
            return {"ok": False, "error": f"Field '{field}' cannot be cleared"}
        if is_orchestrator(tgt) and field in _PROTECTED_HIERARCHY:
            return {"ok": False, "error": f"Cannot clear '{field}' on orchestrator"}
        setattr(tgt, field, _empty_for(field))
        if field == "hierarchy_role":
            tgt.is_lead = False
        return {"ok": True, "field": field, "value": getattr(tgt, field), "action": "delete"}

    coerced = _coerce(field, value)
    if action == "add":
        cur = getattr(tgt, field, None)
        empty = cur in (None, "", "{}", 0, False)
        if not empty and append and isinstance(cur, str) and isinstance(coerced, str):
            sep = ", " if cur and not cur.endswith((",", " ")) else ""
            coerced = f"{cur}{sep}{coerced}" if cur else coerced
        elif not empty and not append:
            # add = set only when empty; otherwise require change_
            return {
                "ok": False,
                "error": f"Field '{field}' already set; use change_agent_{field}",
                "current": cur,
            }
    setattr(tgt, field, coerced)
    if field == "hierarchy_role":
        role = str(coerced or "").lower()
        tgt.is_lead = role == "lead"
        if role == "orchestrator" and not is_orchestrator(tgt):
            # Disallow promoting anyone to orchestrator via field skill
            return {"ok": False, "error": "Cannot set hierarchy_role=orchestrator via skills"}
    if field == "is_lead" and coerced:
        if (tgt.hierarchy_role or "") not in ("lead", "orchestrator"):
            tgt.hierarchy_role = "lead"
    return {"ok": True, "field": field, "value": getattr(tgt, field), "action": action}


def build_agent_action_catalog() -> list[dict[str, Any]]:
    """Catalog entries: entity ops + 3 skills per writable field."""
    cat: list[dict[str, Any]] = [
        {
            "id": "get_agent",
            "name": "Get agent",
            "description": "Fetch full agent record (all fields) by id (or self).",
            "args": ["target_agent_id", "agent_id"],
            "roles": list(_ROLES_ALL),
            "category": "meta",
            "agent_action": True,
        },
        {
            "id": "add_agent",
            "name": "Add agent",
            "description": "Create a new agent (same as spawn_agent). Requires name.",
            "args": [
                "name", "template_type", "personality", "hierarchy_role", "parent_id",
                "model", "company_id", "project_id", "idle_mode", "permission_level",
            ],
            "roles": list(_ROLES_ALL),
            "category": "meta",
            "agent_action": True,
        },
        {
            "id": "create_agent",
            "name": "Create agent",
            "description": "Alias of add_agent / spawn_agent.",
            "args": [
                "name", "template_type", "personality", "hierarchy_role", "parent_id",
                "model", "company_id", "project_id",
            ],
            "roles": list(_ROLES_ALL),
            "category": "meta",
            "agent_action": True,
        },
        {
            "id": "change_agent",
            "name": "Change agent",
            "description": (
                "Update any writable agent fields in one call. "
                f"Fields: {', '.join(AGENT_WRITABLE_FIELDS)}"
            ),
            "args": ["target_agent_id", "agent_id", *AGENT_WRITABLE_FIELDS],
            "roles": list(_ROLES_LEAD) + ["member"],
            "category": "meta",
            "agent_action": True,
        },
        {
            "id": "update_agent",
            "name": "Update agent",
            "description": "Alias of change_agent / configure_agent with all fields.",
            "args": ["target_agent_id", "agent_id", *AGENT_WRITABLE_FIELDS],
            "roles": list(_ROLES_LEAD) + ["member"],
            "category": "meta",
            "agent_action": True,
        },
        {
            "id": "reparent_agent",
            "name": "Reparent agent",
            "description": "Set parent_id (who the agent reports to).",
            "args": ["target_agent_id", "parent_id"],
            "roles": list(_ROLES_LEAD),
            "category": "meta",
            "agent_action": True,
        },
        {
            "id": "demote_agent",
            "name": "Demote agent",
            "description": "Demote a lead to member (clears is_lead).",
            "args": ["target_agent_id", "agent_id"],
            "roles": list(_ROLES_ORCH),
            "category": "meta",
            "agent_action": True,
        },
        {
            "id": "rename_agent",
            "name": "Rename agent",
            "description": "Change agent display name.",
            "args": ["target_agent_id", "name"],
            "roles": list(_ROLES_LEAD) + ["member"],
            "category": "meta",
            "agent_action": True,
        },
        {
            "id": "set_agent_field",
            "name": "Set agent field",
            "description": (
                "Generic setter: field + value on an agent. "
                f"Allowed fields: {', '.join(AGENT_WRITABLE_FIELDS)}"
            ),
            "args": ["target_agent_id", "field", "value", "action"],
            "roles": list(_ROLES_LEAD) + ["member"],
            "category": "meta",
            "agent_action": True,
        },
        {
            "id": "list_agent_fields",
            "name": "List agent fields",
            "description": "List all agent DB fields with add/change/delete skill ids.",
            "args": [],
            "roles": list(_ROLES_ALL),
            "category": "meta",
            "agent_action": True,
        },
        {
            "id": "agent_field_ops",
            "name": "Agent field operations",
            "description": (
                "Meta flag: when enabled, agent may run add_agent_*, change_agent_*, "
                "delete_agent_* field skills for every Agent column."
            ),
            "args": [],
            "roles": list(_ROLES_ALL),
            "category": "meta",
            "agent_action": True,
        },
        # ── Free-form custom fields (stored on agent.config.custom_fields) ──
        {
            "id": "list_agent_custom_fields",
            "name": "List agent custom fields",
            "description": (
                "List free-form key/value custom fields on an agent "
                "(territory, quota, notes, CRM tags, etc.). Defaults to self."
            ),
            "args": ["target_agent_id", "agent_id"],
            "roles": list(_ROLES_ALL),
            "category": "meta",
            "agent_action": True,
            "custom_fields": True,
        },
        {
            "id": "get_agent_custom_field",
            "name": "Get agent custom field",
            "description": "Read one custom field by key from an agent (or self).",
            "args": ["key", "field", "target_agent_id", "agent_id"],
            "roles": list(_ROLES_ALL),
            "category": "meta",
            "agent_action": True,
            "custom_fields": True,
        },
        {
            "id": "set_agent_custom_field",
            "name": "Set agent custom field",
            "description": (
                "Create or update a free-form custom field on an agent. "
                "Args: key (or field) + value. Example: territory=UK North."
            ),
            "args": ["key", "field", "value", "target_agent_id", "agent_id"],
            "roles": list(_ROLES_LEAD) + ["member"],
            "category": "meta",
            "agent_action": True,
            "custom_fields": True,
        },
        {
            "id": "delete_agent_custom_field",
            "name": "Delete agent custom field",
            "description": "Remove a custom field key from an agent.",
            "args": ["key", "field", "target_agent_id", "agent_id"],
            "roles": list(_ROLES_LEAD) + ["member"],
            "category": "meta",
            "agent_action": True,
            "custom_fields": True,
        },
        {
            "id": "set_agent_custom_fields",
            "name": "Set agent custom fields (bulk)",
            "description": (
                "Set multiple custom fields at once. Pass fields={key:value,...} "
                "or a list of {key,value}. merge=true (default) keeps existing keys."
            ),
            "args": ["fields", "merge", "target_agent_id", "agent_id"],
            "roles": list(_ROLES_LEAD) + ["member"],
            "category": "meta",
            "agent_action": True,
            "custom_fields": True,
        },
    ]

    for field, spec in AGENT_FIELD_SPEC.items():
        desc = spec.get("description") or field
        cat.append({
            "id": f"add_agent_{field}",
            "name": f"Add agent {field}",
            "description": f"Set agent.{field} if empty ({desc}). Pass value=…; optional append=true for strings.",
            "args": ["target_agent_id", "agent_id", "value", "append"],
            "roles": list(_ROLES_LEAD) + ["member"],
            "category": "meta",
            "agent_action": True,
            "field": field,
            "field_action": "add",
        })
        cat.append({
            "id": f"change_agent_{field}",
            "name": f"Change agent {field}",
            "description": f"Replace agent.{field} ({desc}).",
            "args": ["target_agent_id", "agent_id", "value"],
            "roles": list(_ROLES_LEAD) + ["member"],
            "category": "meta",
            "agent_action": True,
            "field": field,
            "field_action": "change",
        })
        if spec.get("clearable", True):
            cat.append({
                "id": f"delete_agent_{field}",
                "name": f"Delete agent {field}",
                "description": f"Clear agent.{field} ({desc}).",
                "args": ["target_agent_id", "agent_id"],
                "roles": list(_ROLES_LEAD) + ["member"],
                "category": "meta",
                "agent_action": True,
                "field": field,
                "field_action": "delete",
            })

    return cat


def parse_agent_field_skill(skill_id: str) -> dict[str, Any] | None:
    """Parse add_agent_<field> | change_agent_<field> | delete_agent_<field>."""
    sid = (skill_id or "").strip()
    for action in ("add", "change", "delete"):
        prefix = f"{action}_agent_"
        if sid.startswith(prefix):
            field = sid[len(prefix):]
            if field in AGENT_FIELD_SPEC:
                if action == "delete" and not AGENT_FIELD_SPEC[field].get("clearable", True):
                    return None
                return {"action": action, "field": field, "entity": "agent", "raw": sid}
    # Entity-level aliases handled as named skills
    entity_map = {
        "add_agent": {"action": "create", "field": None},
        "create_agent": {"action": "create", "field": None},
        "change_agent": {"action": "update", "field": None},
        "update_agent": {"action": "update", "field": None},
        "get_agent": {"action": "get", "field": None},
        "reparent_agent": {"action": "reparent", "field": None},
        "demote_agent": {"action": "demote", "field": None},
        "rename_agent": {"action": "rename", "field": None},
        "set_agent_field": {"action": "set_field", "field": None},
        "list_agent_fields": {"action": "list_fields", "field": None},
        "agent_field_ops": {"action": "noop_meta", "field": None},
        "list_agent_custom_fields": {"action": "list_custom_fields", "field": None},
        "get_agent_custom_field": {"action": "get_custom_field", "field": None},
        "set_agent_custom_field": {"action": "set_custom_field", "field": None},
        "delete_agent_custom_field": {"action": "delete_custom_field", "field": None},
        "set_agent_custom_fields": {"action": "set_custom_fields_bulk", "field": None},
    }
    if sid in entity_map:
        return {**entity_map[sid], "entity": "agent", "raw": sid}
    return None


def is_agent_action_skill(skill_id: str) -> bool:
    return parse_agent_field_skill(skill_id) is not None


def agent_action_skill_ids() -> set[str]:
    return {s["id"] for s in build_agent_action_catalog()}


# ── Handlers ───────────────────────────────────────────────────────────────


async def _skill_get_agent(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    tgt = _resolve_target(db, agent, user, args, allow_self=True)
    if isinstance(tgt, dict):
        return tgt
    return {"ok": True, "agent": _agent_out(tgt)}


async def _skill_change_agent(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Multi-field update covering every writable Agent column."""
    tgt = _resolve_target(db, agent, user, args, allow_self=True)
    if isinstance(tgt, dict):
        return tgt
    err = _can_mutate_target(agent, tgt)
    if err:
        return {"ok": False, "error": err}

    updated: list[str] = []
    errors: list[str] = []
    for field in AGENT_WRITABLE_FIELDS:
        if field not in args or args.get(field) is None:
            # allow explicit null clear via clear_<field> or value "" for strings
            continue
        # hierarchy protection for non-orchestrator actors
        if field in _PROTECTED_HIERARCHY and not is_orchestrator(agent) and tgt.id != agent.id:
            if normalize_role(agent) != "lead":
                errors.append(f"{field}: lead/orchestrator only")
                continue
        res = _apply_field(tgt, field, args[field], action="change")
        if res.get("ok"):
            updated.append(field)
        else:
            errors.append(f"{field}: {res.get('error')}")

    # Also accept nested fields={} map
    nested = args.get("fields")
    if isinstance(nested, dict):
        for field, val in nested.items():
            if field not in AGENT_FIELD_SPEC:
                errors.append(f"{field}: unknown")
                continue
            res = _apply_field(tgt, field, val, action="change")
            if res.get("ok"):
                updated.append(field)
            else:
                errors.append(f"{field}: {res.get('error')}")

    if not updated and not errors:
        return {"ok": False, "error": "No fields to update", "writable": list(AGENT_WRITABLE_FIELDS)}

    if updated:
        db.commit()
        db.refresh(tgt)
    return {
        "ok": bool(updated),
        "updated": updated,
        "errors": errors or None,
        "agent": _agent_out(tgt),
        "message": f"Updated {', '.join(updated)}" if updated else "No fields updated",
    }


async def _skill_reparent_agent(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    tgt = _resolve_target(db, agent, user, args, allow_self=False)
    if isinstance(tgt, dict):
        return tgt
    if is_orchestrator(tgt):
        return {"ok": False, "error": "Cannot reparent the orchestrator"}
    err = _can_mutate_target(agent, tgt)
    if err and not is_orchestrator(agent):
        return {"ok": False, "error": err}
    raw_parent = args.get("parent_id")
    if raw_parent in (None, "", "null"):
        parent_id = None
    else:
        try:
            parent_id = int(raw_parent)
        except (TypeError, ValueError):
            return {"ok": False, "error": "parent_id must be int or null"}
        parent = db.get(models.Agent, parent_id)
        if not parent or parent.user_id != user.id:
            return {"ok": False, "error": "parent agent not found"}
        if parent_id == tgt.id:
            return {"ok": False, "error": "agent cannot parent itself"}
    tgt.parent_id = parent_id
    db.commit()
    return {"ok": True, "agent_id": tgt.id, "parent_id": tgt.parent_id, "agent": _agent_out(tgt)}


async def _skill_demote_agent(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    if not is_orchestrator(agent):
        return {"ok": False, "error": "Only orchestrator can demote"}
    tgt = _resolve_target(db, agent, user, args, allow_self=False)
    if isinstance(tgt, dict):
        return tgt
    if is_orchestrator(tgt):
        return {"ok": False, "error": "Cannot demote the orchestrator"}
    tgt.hierarchy_role = "member"
    tgt.is_lead = False
    if (tgt.permission_level or "") == "lead":
        tgt.permission_level = "operator"
    db.commit()
    return {"ok": True, "demoted": tgt.id, "agent": _agent_out(tgt)}


async def _skill_rename_agent(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    name = (args.get("name") or args.get("value") or "").strip()
    if not name:
        return {"ok": False, "error": "name is required"}
    return await _skill_agent_field_dispatch(
        db, agent, user, "change_agent_name", {"target_agent_id": args.get("target_agent_id") or args.get("agent_id") or agent.id, "value": name}
    )


async def _skill_set_agent_field(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    field = (args.get("field") or "").strip()
    if field not in AGENT_FIELD_SPEC:
        return {
            "ok": False,
            "error": f"Unknown field '{field}'",
            "writable": list(AGENT_WRITABLE_FIELDS),
        }
    action = (args.get("action") or "change").strip().lower()
    if action not in ("add", "change", "delete"):
        action = "change"
    return await _skill_agent_field_dispatch(
        db, agent, user, f"{action}_agent_{field}", args
    )


async def _skill_list_agent_fields(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    fields = []
    for field, spec in AGENT_FIELD_SPEC.items():
        entry = {
            "field": field,
            "type": spec["type"],
            "clearable": bool(spec.get("clearable", True)),
            "description": spec.get("description"),
            "skills": {
                "add": f"add_agent_{field}",
                "change": f"change_agent_{field}",
            },
        }
        if spec.get("clearable", True):
            entry["skills"]["delete"] = f"delete_agent_{field}"
        fields.append(entry)
    return {
        "ok": True,
        "entity": "agent",
        "count": len(fields),
        "fields": fields,
        "entity_skills": {
            "add": "add_agent",
            "create": "create_agent",
            "get": "get_agent",
            "change": "change_agent",
            "update": "update_agent",
            "delete": "delete_agent",
            "reparent": "reparent_agent",
            "demote": "demote_agent",
            "rename": "rename_agent",
        },
        "custom_field_skills": {
            "list": "list_agent_custom_fields",
            "get": "get_agent_custom_field",
            "set": "set_agent_custom_field",
            "delete": "delete_agent_custom_field",
            "set_bulk": "set_agent_custom_fields",
            "storage": "agent.config.custom_fields",
        },
    }


async def _skill_agent_field_ops(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Discovery / no-op meta skill — documents that field ops are enabled."""
    return await _skill_list_agent_fields(db, agent, user, args)


async def _skill_list_agent_custom_fields(
    db: Session, agent: models.Agent, user: models.User, args: dict
) -> dict:
    tgt = _resolve_target(db, agent, user, args, allow_self=True)
    if isinstance(tgt, dict):
        return tgt
    fields = get_custom_fields(tgt)
    items = [{"key": k, "value": v} for k, v in fields.items()]
    return {
        "ok": True,
        "agent_id": tgt.id,
        "agent_name": tgt.name,
        "count": len(items),
        "custom_fields": fields,
        "items": items,
        "message": (
            f"{tgt.name} has {len(items)} custom field(s): "
            + (", ".join(f"{k}={v!r}" for k, v in list(fields.items())[:12]) or "none")
        ),
    }


async def _skill_get_agent_custom_field(
    db: Session, agent: models.Agent, user: models.User, args: dict
) -> dict:
    tgt = _resolve_target(db, agent, user, args, allow_self=True)
    if isinstance(tgt, dict):
        return tgt
    key = args.get("key") or args.get("field") or args.get("name")
    nk = _normalize_field_key(key)
    if not nk:
        return {"ok": False, "error": "key (or field) is required"}
    fields = get_custom_fields(tgt)
    if nk not in fields:
        return {
            "ok": False,
            "error": f"Custom field '{nk}' not set",
            "agent_id": tgt.id,
            "custom_fields": fields,
        }
    return {
        "ok": True,
        "agent_id": tgt.id,
        "agent_name": tgt.name,
        "key": nk,
        "value": fields[nk],
        "message": f"{tgt.name}.{nk} = {fields[nk]!r}",
    }


async def _skill_set_agent_custom_field(
    db: Session, agent: models.Agent, user: models.User, args: dict
) -> dict:
    tgt = _resolve_target(db, agent, user, args, allow_self=True)
    if isinstance(tgt, dict):
        return tgt
    err = _can_mutate_target(agent, tgt)
    if err:
        return {"ok": False, "error": err}
    key = args.get("key") or args.get("field") or args.get("name")
    if "value" not in args:
        return {"ok": False, "error": "value is required"}
    res = upsert_custom_field(tgt, key, args.get("value"))
    if not res.get("ok"):
        return res
    db.commit()
    db.refresh(tgt)
    return {
        "ok": True,
        "agent_id": tgt.id,
        "agent_name": tgt.name,
        "key": res["key"],
        "value": res["value"],
        "custom_fields": res["custom_fields"],
        "message": f"Set custom field {res['key']}={res['value']!r} on {tgt.name}",
    }


async def _skill_delete_agent_custom_field(
    db: Session, agent: models.Agent, user: models.User, args: dict
) -> dict:
    tgt = _resolve_target(db, agent, user, args, allow_self=True)
    if isinstance(tgt, dict):
        return tgt
    err = _can_mutate_target(agent, tgt)
    if err:
        return {"ok": False, "error": err}
    key = args.get("key") or args.get("field") or args.get("name")
    res = remove_custom_field(tgt, key)
    if not res.get("ok"):
        return res
    db.commit()
    db.refresh(tgt)
    return {
        "ok": True,
        "agent_id": tgt.id,
        "agent_name": tgt.name,
        "key": res["key"],
        "deleted": True,
        "custom_fields": res["custom_fields"],
        "message": f"Deleted custom field '{res['key']}' on {tgt.name}",
    }


async def _skill_set_agent_custom_fields(
    db: Session, agent: models.Agent, user: models.User, args: dict
) -> dict:
    """Bulk set: fields dict or list of {key,value}."""
    tgt = _resolve_target(db, agent, user, args, allow_self=True)
    if isinstance(tgt, dict):
        return tgt
    err = _can_mutate_target(agent, tgt)
    if err:
        return {"ok": False, "error": err}

    merge = args.get("merge", True)
    if isinstance(merge, str):
        merge = merge.strip().lower() not in ("0", "false", "no", "replace")

    incoming: dict[str, Any] = {}
    raw_fields = args.get("fields") or args.get("custom_fields") or args.get("items")
    if isinstance(raw_fields, dict):
        incoming = dict(raw_fields)
    elif isinstance(raw_fields, list):
        for item in raw_fields:
            if not isinstance(item, dict):
                continue
            k = item.get("key") or item.get("field") or item.get("name")
            if k is None or "value" not in item:
                continue
            incoming[str(k)] = item.get("value")
    else:
        # Accept flat extra keys that are not target selectors
        skip = {
            "target_agent_id", "agent_id", "id", "merge", "fields",
            "custom_fields", "items", "action",
        }
        for k, v in args.items():
            if k in skip:
                continue
            incoming[k] = v

    if not incoming:
        return {"ok": False, "error": "fields map/list required"}

    current = get_custom_fields(tgt) if merge else {}
    for k, v in incoming.items():
        nk = _normalize_field_key(k)
        if not nk:
            continue
        current[nk] = v
    clean = set_custom_fields_map(tgt, current)
    db.commit()
    db.refresh(tgt)
    return {
        "ok": True,
        "agent_id": tgt.id,
        "agent_name": tgt.name,
        "custom_fields": clean,
        "count": len(clean),
        "message": f"Set {len(incoming)} custom field(s) on {tgt.name} (total {len(clean)})",
    }


async def _skill_agent_field_dispatch(
    db: Session,
    agent: models.Agent,
    user: models.User,
    skill_id: str,
    args: dict,
) -> dict:
    """Dispatch add_agent_<field> / change_agent_<field> / delete_agent_<field>."""
    parsed = parse_agent_field_skill(skill_id)
    if not parsed:
        return {"ok": False, "error": f"Not an agent field skill: {skill_id}"}

    action = parsed["action"]
    field = parsed.get("field")

    if action == "list_fields" or action == "noop_meta":
        return await _skill_list_agent_fields(db, agent, user, args)
    if action == "get":
        return await _skill_get_agent(db, agent, user, args)
    if action == "create":
        from .meta_agents import _skill_spawn
        return await _skill_spawn(db, agent, user, args)
    if action == "update":
        return await _skill_change_agent(db, agent, user, args)
    if action == "reparent":
        return await _skill_reparent_agent(db, agent, user, args)
    if action == "demote":
        return await _skill_demote_agent(db, agent, user, args)
    if action == "rename":
        return await _skill_rename_agent(db, agent, user, args)
    if action == "set_field":
        return await _skill_set_agent_field(db, agent, user, args)
    if action == "list_custom_fields":
        return await _skill_list_agent_custom_fields(db, agent, user, args)
    if action == "get_custom_field":
        return await _skill_get_agent_custom_field(db, agent, user, args)
    if action == "set_custom_field":
        return await _skill_set_agent_custom_field(db, agent, user, args)
    if action == "delete_custom_field":
        return await _skill_delete_agent_custom_field(db, agent, user, args)
    if action == "set_custom_fields_bulk":
        return await _skill_set_agent_custom_fields(db, agent, user, args)

    # Field-level add/change/delete
    if not field:
        return {"ok": False, "error": "field required"}

    tgt = _resolve_target(db, agent, user, args, allow_self=True)
    if isinstance(tgt, dict):
        return tgt
    err = _can_mutate_target(agent, tgt)
    if err:
        return {"ok": False, "error": err}

    if field in _PROTECTED_HIERARCHY and not is_orchestrator(agent):
        if normalize_role(agent) not in ("lead", "orchestrator") and tgt.id != agent.id:
            return {"ok": False, "error": f"Only lead/orchestrator can change {field}"}

    value = args.get("value") if "value" in args else args.get(field)
    if action in ("add", "change") and value is None and field not in args:
        return {"ok": False, "error": "value is required"}

    append = bool(args.get("append"))
    if isinstance(args.get("append"), str):
        append = args.get("append", "").lower() in ("1", "true", "yes")

    res = _apply_field(tgt, field, value, action=action, append=append)
    if not res.get("ok"):
        return res
    db.commit()
    db.refresh(tgt)
    return {
        "ok": True,
        "skill": skill_id,
        "action": action,
        "field": field,
        "agent_id": tgt.id,
        "value": getattr(tgt, field),
        "agent": _agent_out(tgt),
        "message": f"{action} agent.{field} on {tgt.name} (#{tgt.id})",
    }


# Expand configure_agent to all fields (backward compatible wrapper)
async def _skill_configure_agent_full(
    db: Session, agent: models.Agent, user: models.User, args: dict
) -> dict:
    return await _skill_change_agent(db, agent, user, args)


__all__ = [
    "AGENT_FIELD_SPEC",
    "AGENT_WRITABLE_FIELDS",
    "build_agent_action_catalog",
    "parse_agent_field_skill",
    "is_agent_action_skill",
    "agent_action_skill_ids",
    "get_custom_fields",
    "set_custom_fields_map",
    "upsert_custom_field",
    "remove_custom_field",
    "_skill_get_agent",
    "_skill_change_agent",
    "_skill_reparent_agent",
    "_skill_demote_agent",
    "_skill_rename_agent",
    "_skill_set_agent_field",
    "_skill_list_agent_fields",
    "_skill_agent_field_ops",
    "_skill_list_agent_custom_fields",
    "_skill_get_agent_custom_field",
    "_skill_set_agent_custom_field",
    "_skill_delete_agent_custom_field",
    "_skill_set_agent_custom_fields",
    "_skill_agent_field_dispatch",
    "_skill_configure_agent_full",
    "_skill_add_agent",
    "_skill_create_agent",
    "_skill_update_agent",
]


async def _skill_add_agent(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    from .meta_agents import _skill_spawn
    return await _skill_spawn(db, agent, user, args)


async def _skill_create_agent(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    return await _skill_add_agent(db, agent, user, args)


async def _skill_update_agent(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    return await _skill_change_agent(db, agent, user, args)
