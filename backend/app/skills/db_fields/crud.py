"""Execute field-level / entity-level DB skills with ownership + type safety."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Session

from ... import models
from .registry import (
    ALL_ENTITY_SPECS,
    get_entity,
    list_entities,
    parse_skill_id,
    resolve_field_skill,
)

# Columns agents must never write via generic field skills
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
_FORBIDDEN_PREFIXES = (
    "encrypted_",
    "password",
    "token_hash",
    "api_key",
    "jwt_",
)
_FORBIDDEN_SUBSTRINGS = (
    "password_hash",
    "encrypted_",
    "token_hash",
    "api_key_hash",
    "jwt_secret",
)

_TAGS_FIELD_NAMES = frozenset({"tags", "skills", "labels", "keywords"})


def _is_forbidden_field(name: str) -> bool:
    n = (name or "").strip().lower()
    if not n:
        return True
    if n in _FORBIDDEN_EXACT:
        return True
    for p in _FORBIDDEN_PREFIXES:
        if n.startswith(p):
            return True
    for s in _FORBIDDEN_SUBSTRINGS:
        if s in n:
            return True
    return False


def _resolve_model(model_name: str):
    """Resolve a SQLAlchemy model class from app.models by class name."""
    if not model_name:
        return None
    name = str(model_name).strip()
    cls = getattr(models, name, None)
    if cls is None:
        # try common casings
        for attr in dir(models):
            if attr.lower() == name.lower() and not attr.startswith("_"):
                cls = getattr(models, attr, None)
                break
    if cls is None or not hasattr(cls, "__table__"):
        return None
    return cls


def _column(model_cls, field: str):
    try:
        return model_cls.__table__.columns.get(field)
    except Exception:
        return None


def _coerce_value(model_cls, field: str, value: Any, *, field_type_hint: str | None = None) -> Any:
    """Coerce inbound skill args to a Python value matching the column type."""
    if value is None:
        return None
    hint = (field_type_hint or "").strip().lower()
    col = _column(model_cls, field)

    if hint == "tags" or field in _TAGS_FIELD_NAMES:
        return _normalize_tags_value(value)

    if hint in ("json", "dict", "object"):
        import json

        if value is None or value == "":
            return "{}"
        if isinstance(value, (dict, list)):
            return json.dumps(value)
        s = str(value).strip()
        # Validate JSON-ish strings; store as-is if already JSON
        try:
            json.loads(s)
            return s
        except Exception:
            return json.dumps(s)

    if hint in ("int", "integer") or (col is not None and isinstance(col.type, Integer)):
        if value == "" or value is None:
            return None
        return int(value)

    if hint in ("float", "number", "double") or (col is not None and isinstance(col.type, Float)):
        if value == "" or value is None:
            return None
        return float(value)

    if hint in ("bool", "boolean") or (col is not None and isinstance(col.type, Boolean)):
        if isinstance(value, bool):
            return value
        s = str(value).strip().lower()
        if s in ("1", "true", "yes", "y", "on"):
            return True
        if s in ("0", "false", "no", "n", "off", ""):
            return False
        return bool(value)

    if hint in ("datetime", "date", "timestamp") or (
        col is not None and isinstance(col.type, DateTime)
    ):
        if isinstance(value, datetime):
            return value
        s = str(value).strip()
        if not s:
            return None
        # ISO-8601 friendly
        s = s.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(s)
        except Exception:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
                try:
                    return datetime.strptime(s, fmt)
                except Exception:
                    continue
            raise ValueError(f"invalid datetime for {field}: {value!r}")

    # String / Text / default
    if isinstance(value, (list, tuple, set)):
        return ",".join(str(x).strip() for x in value if str(x).strip())
    if isinstance(value, dict):
        import json

        return json.dumps(value)
    return str(value) if value is not None else None


def _normalize_tags_value(value: Any) -> str:
    try:
        from ...tags_util import normalize_tags

        return normalize_tags(value)
    except Exception:
        if value is None:
            return ""
        if isinstance(value, (list, tuple, set)):
            parts = [str(t).strip() for t in value if str(t).strip()]
        else:
            raw = str(value).replace(";", ",")
            parts = [t.strip() for t in raw.split(",") if t.strip()]
        return ",".join(parts)


def _append_tags(existing: Any, incoming: Any) -> str:
    try:
        from ...tags_util import normalize_tags, tags_list

        cur = tags_list(existing if isinstance(existing, str) else str(existing or ""))
        add = tags_list(normalize_tags(incoming))
        merged = []
        seen = set()
        for t in cur + add:
            k = t.lower()
            if k in seen:
                continue
            seen.add(k)
            merged.append(t)
        return ",".join(merged)
    except Exception:
        base = str(existing or "").strip()
        add = _normalize_tags_value(incoming)
        if not base:
            return add
        if not add:
            return base
        return _normalize_tags_value(f"{base},{add}")


def _clear_value(model_cls, field: str) -> Any:
    """Default empty value when deleting/clearing a field."""
    col = _column(model_cls, field)
    if col is None:
        return None
    if isinstance(col.type, Boolean):
        return False
    if isinstance(col.type, Float):
        return 0.0 if col.nullable is False else (0.0)
    if isinstance(col.type, Integer):
        return None if col.nullable else 0
    if isinstance(col.type, DateTime):
        return None
    if isinstance(col.type, (String, Text)):
        # CRM convention: clear strings to "" (works for nullable and non-null defaults)
        return ""
    # nullable unknown types
    if col.nullable:
        return None
    return ""


def _get_id_from_args(args: dict, id_arg: str) -> int | None:
    if not args:
        return None
    raw = args.get(id_arg)
    if raw is None:
        raw = args.get("id")
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _check_ownership(db: Session, model_cls, record, spec: dict, user: models.User) -> tuple[bool, str]:
    """Return (ok, error). Always filters by tenant ownership."""
    if record is None:
        return False, "record not found"

    owner_via = spec.get("owner_via")
    if owner_via and isinstance(owner_via, dict):
        parent_model = _resolve_model(owner_via.get("model") or "")
        fk = owner_via.get("fk") or ""
        parent_owner_col = owner_via.get("owner_col") or "owner_user_id"
        if not parent_model or not fk:
            return False, "owner_via misconfigured"
        parent_id = getattr(record, fk, None)
        if parent_id is None:
            return False, "record missing parent reference"
        parent = db.get(parent_model, parent_id)
        if not parent:
            return False, "parent record not found"
        owner = getattr(parent, parent_owner_col, None)
        if owner is None and parent_owner_col == "owner_user_id":
            owner = getattr(parent, "user_id", None)
        if owner != user.id:
            return False, "record not found or not owned"
        return True, ""

    owner_col = spec.get("owner_col") or "owner_user_id"
    owner = getattr(record, owner_col, None)
    if owner is None and owner_col == "owner_user_id":
        owner = getattr(record, "user_id", None)
        owner_col = "user_id" if owner is not None else owner_col
    if owner is None:
        return False, f"ownership column '{owner_col}' missing on model"
    if owner != user.id:
        return False, "record not found or not owned"
    return True, ""


def _get_owned_record(
    db: Session, spec: dict, user: models.User, args: dict
) -> tuple[Any | None, Any | None, str | None]:
    """Return (model_cls, record, error)."""
    model_cls = _resolve_model(spec.get("model") or "")
    if model_cls is None:
        return None, None, f"model '{spec.get('model')}' not found"

    id_arg = spec.get("id_arg") or f"{spec.get('slug', 'entity')}_id"
    rid = _get_id_from_args(args, id_arg)
    if rid is None:
        return model_cls, None, f"{id_arg} is required"

    record = db.get(model_cls, rid)
    ok, err = _check_ownership(db, model_cls, record, spec, user)
    if not ok:
        return model_cls, None, err
    return model_cls, record, None


def _writable_fields(spec: dict) -> list[str]:
    out = []
    for f in spec.get("writable") or []:
        f = str(f).strip()
        if f and not _is_forbidden_field(f):
            out.append(f)
    return out


def _field_type_hint(spec: dict, field: str) -> str | None:
    ft = spec.get("field_types") or {}
    if field in ft:
        return str(ft[field])
    if field in _TAGS_FIELD_NAMES:
        return "tags"
    return None


def _serialize_record(record, fields: list[str] | None = None) -> dict:
    if record is None:
        return {}
    data: dict[str, Any] = {}
    if hasattr(record, "id"):
        data["id"] = record.id
    cols = fields
    if cols is None:
        try:
            cols = [c.name for c in record.__table__.columns]
        except Exception:
            cols = []
    for name in cols:
        if _is_forbidden_field(name):
            continue
        try:
            val = getattr(record, name, None)
        except Exception:
            continue
        if isinstance(val, datetime):
            data[name] = val.isoformat()
        else:
            data[name] = val
    return data


async def _skill_list_entity_fields(
    db: Session, agent: models.Agent, user: models.User, args: dict
) -> dict:
    """Discovery skill: list_db_fields — all entities and writable fields."""
    entities = []
    for spec in list_entities():
        entities.append(
            {
                "slug": spec.get("slug"),
                "label": spec.get("label"),
                "model": spec.get("model"),
                "category": spec.get("category"),
                "id_arg": spec.get("id_arg"),
                "writable": _writable_fields(spec),
                "create_required": list(spec.get("create_required") or []),
                "aliases": dict(spec.get("aliases") or {}),
                "skills": {
                    "add_entity": f"add_{spec.get('slug')}",
                    "change_entity": f"change_{spec.get('slug')}",
                    "delete_entity": f"delete_{spec.get('slug')}",
                    "fields": {
                        f: {
                            "add": f"add_{spec.get('slug')}_{f}",
                            "change": f"change_{spec.get('slug')}_{f}",
                            "delete": f"delete_{spec.get('slug')}_{f}",
                        }
                        for f in _writable_fields(spec)
                    },
                },
            }
        )
    return {
        "ok": True,
        "count": len(entities),
        "entities": entities,
        "message": (
            f"{len(entities)} entity type(s) registered for field-level DB skills."
            if entities
            else "No entity specs loaded yet (entities_crm / entities_workspace / entities_knowledge)."
        ),
    }


async def _op_add_entity(
    db: Session, agent: models.Agent, user: models.User, spec: dict, args: dict
) -> dict:
    model_cls = _resolve_model(spec.get("model") or "")
    if model_cls is None:
        return {"ok": False, "error": f"model '{spec.get('model')}' not found"}

    writable = set(_writable_fields(spec))
    required = [f for f in (spec.get("create_required") or []) if f in writable or f]
    # Filter required through forbidden
    required = [f for f in required if not _is_forbidden_field(f)]

    missing = []
    for f in required:
        if args.get(f) is None or (isinstance(args.get(f), str) and not str(args.get(f)).strip()):
            missing.append(f)
    if missing:
        return {"ok": False, "error": f"missing required fields: {', '.join(missing)}"}

    kwargs: dict[str, Any] = {}
    # Spec create_defaults (non-destructive: only if column exists)
    create_defaults = spec.get("create_defaults") or {}
    if isinstance(create_defaults, dict):
        for dk, dv in create_defaults.items():
            if _is_forbidden_field(str(dk)):
                continue
            if hasattr(model_cls, str(dk)):
                try:
                    kwargs[str(dk)] = _coerce_value(
                        model_cls,
                        str(dk),
                        dv,
                        field_type_hint=_field_type_hint(spec, str(dk)),
                    )
                except Exception:
                    kwargs[str(dk)] = dv

    # Ownership on create
    owner_col = spec.get("owner_col") or "owner_user_id"
    owner_via = spec.get("owner_via")
    if not owner_via:
        # Prefer configured owner_col if present on model
        if hasattr(model_cls, owner_col):
            kwargs[owner_col] = user.id
        elif hasattr(model_cls, "owner_user_id"):
            kwargs["owner_user_id"] = user.id
        elif hasattr(model_cls, "user_id"):
            kwargs["user_id"] = user.id
    else:
        # Child rows: still set owner_col if present; verify parent ownership
        fk = owner_via.get("fk")
        if fk and args.get(fk) is not None:
            parent_model = _resolve_model(owner_via.get("model") or "")
            try:
                parent_id = int(args.get(fk))
            except (TypeError, ValueError):
                return {"ok": False, "error": f"invalid {fk}"}
            parent = db.get(parent_model, parent_id) if parent_model else None
            p_owner_col = owner_via.get("owner_col") or "owner_user_id"
            owner = getattr(parent, p_owner_col, None) if parent else None
            if owner is None and parent is not None:
                owner = getattr(parent, "user_id", None)
            if not parent or owner != user.id:
                return {"ok": False, "error": f"parent {fk}={parent_id} not found or not owned"}
            kwargs[fk] = parent_id
        if hasattr(model_cls, owner_col):
            kwargs[owner_col] = user.id
        elif hasattr(model_cls, "owner_user_id"):
            kwargs["owner_user_id"] = user.id

    # Optional agent attribution
    if hasattr(model_cls, "owner_agent_id") and "owner_agent_id" not in kwargs:
        if args.get("owner_agent_id") is not None:
            try:
                kwargs["owner_agent_id"] = int(args["owner_agent_id"])
            except (TypeError, ValueError):
                kwargs["owner_agent_id"] = agent.id
        else:
            kwargs["owner_agent_id"] = agent.id
    if hasattr(model_cls, "agent_id") and args.get("agent_id") is None:
        # don't force agent_id unless model expects it and column is free
        pass

    # Apply required + provided writable fields from args
    apply_fields = list(
        dict.fromkeys([*required, *[f for f in writable if f in (args or {})]])
    )
    for field in apply_fields:
        if _is_forbidden_field(field):
            continue
        if field not in writable and field not in required:
            continue
        if not hasattr(model_cls, field):
            continue
        # Don't overwrite ownership / parent keys already set unless arg provided
        if field in kwargs and args.get(field) is None:
            continue
        if args.get(field) is None and field not in required:
            continue
        try:
            kwargs[field] = _coerce_value(
                model_cls,
                field,
                args.get(field),
                field_type_hint=_field_type_hint(spec, field),
            )
        except Exception as e:
            return {"ok": False, "error": f"invalid value for {field}: {e}"}

    try:
        row = model_cls(**kwargs)
        db.add(row)
        db.commit()
        db.refresh(row)
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        return {"ok": False, "error": f"create failed: {str(e)[:300]}"}

    slug = spec.get("slug")
    return {
        "ok": True,
        "action": "add",
        "entity": slug,
        "id": getattr(row, "id", None),
        "message": f"Created {spec.get('label') or slug} #{getattr(row, 'id', '?')}",
        "record": _serialize_record(row, fields=["id", *writable]),
    }


async def _op_change_entity(
    db: Session, agent: models.Agent, user: models.User, spec: dict, args: dict
) -> dict:
    model_cls, record, err = _get_owned_record(db, spec, user, args)
    if err:
        return {"ok": False, "error": err}

    writable = _writable_fields(spec)
    updates: dict[str, Any] = {}
    for field in writable:
        if field not in args or args.get(field) is None:
            continue
        if _is_forbidden_field(field):
            continue
        if not hasattr(record, field):
            continue
        try:
            updates[field] = _coerce_value(
                model_cls, field, args.get(field), field_type_hint=_field_type_hint(spec, field)
            )
        except Exception as e:
            return {"ok": False, "error": f"invalid value for {field}: {e}"}

    if not updates:
        return {"ok": False, "error": "no writable fields provided to change"}

    try:
        for k, v in updates.items():
            setattr(record, k, v)
        if hasattr(record, "updated_at"):
            try:
                record.updated_at = datetime.utcnow()
            except Exception:
                pass
        db.commit()
        db.refresh(record)
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        return {"ok": False, "error": f"update failed: {str(e)[:300]}"}

    slug = spec.get("slug")
    return {
        "ok": True,
        "action": "change",
        "entity": slug,
        "id": getattr(record, "id", None),
        "updated_fields": list(updates.keys()),
        "message": f"Updated {spec.get('label') or slug} #{getattr(record, 'id', '?')}",
        "record": _serialize_record(record, fields=["id", *writable]),
    }


async def _op_delete_entity(
    db: Session, agent: models.Agent, user: models.User, spec: dict, args: dict
) -> dict:
    model_cls, record, err = _get_owned_record(db, spec, user, args)
    if err:
        return {"ok": False, "error": err}

    rid = getattr(record, "id", None)
    label = None
    for attr in ("name", "title", "email"):
        if hasattr(record, attr):
            label = getattr(record, attr)
            if label:
                break
    try:
        db.delete(record)
        db.commit()
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        return {"ok": False, "error": f"delete failed: {str(e)[:300]}"}

    slug = spec.get("slug")
    return {
        "ok": True,
        "action": "delete",
        "entity": slug,
        "id": rid,
        "message": f"Deleted {spec.get('label') or slug} #{rid}"
        + (f" ({label})" if label else ""),
    }


async def _op_field(
    db: Session,
    agent: models.Agent,
    user: models.User,
    spec: dict,
    action: str,
    field: str,
    args: dict,
) -> dict:
    if _is_forbidden_field(field):
        return {"ok": False, "error": f"field '{field}' is not writable"}
    writable = _writable_fields(spec)
    if field not in writable:
        return {"ok": False, "error": f"field '{field}' is not writable on {spec.get('slug')}"}

    # Optional clearable allow-list (if provided on the entity spec)
    if action == "delete":
        clearable = spec.get("clearable")
        if isinstance(clearable, (list, tuple, set)) and clearable:
            if field not in set(clearable):
                return {
                    "ok": False,
                    "error": f"field '{field}' is not clearable on {spec.get('slug')}",
                }

    model_cls, record, err = _get_owned_record(db, spec, user, args)
    if err:
        return {"ok": False, "error": err}
    if not hasattr(record, field):
        return {"ok": False, "error": f"model has no column '{field}'"}

    hint = _field_type_hint(spec, field)
    prev = getattr(record, field, None)

    try:
        if action == "delete":
            new_val = _clear_value(model_cls, field)
        elif action == "add":
            if "value" not in args and field not in args:
                return {"ok": False, "error": "value is required"}
            raw = args.get("value") if "value" in args else args.get(field)
            # tags-like: append; others: set
            is_tags = (hint == "tags") or (field in _TAGS_FIELD_NAMES)
            replace = str(args.get("replace") or "").strip().lower() in (
                "1",
                "true",
                "yes",
                "replace",
            )
            if is_tags and not replace:
                new_val = _append_tags(prev, raw)
            else:
                new_val = _coerce_value(model_cls, field, raw, field_type_hint=hint)
        elif action == "change":
            if "value" not in args and field not in args:
                return {"ok": False, "error": "value is required"}
            raw = args.get("value") if "value" in args else args.get(field)
            new_val = _coerce_value(model_cls, field, raw, field_type_hint=hint)
        else:
            return {"ok": False, "error": f"unknown field action '{action}'"}

        setattr(record, field, new_val)
        if hasattr(record, "updated_at"):
            try:
                record.updated_at = datetime.utcnow()
            except Exception:
                pass
        db.commit()
        db.refresh(record)
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        return {"ok": False, "error": f"field {action} failed: {str(e)[:300]}"}

    slug = spec.get("slug")
    return {
        "ok": True,
        "action": action,
        "entity": slug,
        "field": field,
        "id": getattr(record, "id", None),
        "previous": prev if not isinstance(prev, datetime) else prev.isoformat(),
        "value": getattr(record, field, None)
        if not isinstance(getattr(record, field, None), datetime)
        else getattr(record, field).isoformat(),
        "message": f"{action.title()} {slug}.{field} on #{getattr(record, 'id', '?')}",
    }


async def _skill_db_field_dispatch(
    db: Session,
    agent: models.Agent,
    user: models.User,
    skill_id: str,
    meta: dict | None,
    args: dict | None,
) -> dict:
    """Unified handler for all field-level DB skills (HANDLER_TABLE meta mode)."""
    args = args or {}
    sid = (skill_id or "").strip()

    if sid == "list_db_fields":
        return await _skill_list_entity_fields(db, agent, user, args)

    parsed = resolve_field_skill(sid) or parse_skill_id(sid)
    if not parsed:
        return {"ok": False, "error": f"unknown field skill '{sid}'"}

    action = parsed.get("action")
    if action == "list":
        return await _skill_list_entity_fields(db, agent, user, args)

    entity = parsed.get("entity")
    field = parsed.get("field")
    spec = get_entity(entity) if entity else None
    if not spec:
        return {"ok": False, "error": f"unknown entity '{entity}'"}

    # Security: only entities in registry (already via get_entity)
    if field:
        return await _op_field(db, agent, user, spec, action, field, args)

    if action == "add":
        return await _op_add_entity(db, agent, user, spec, args)
    if action == "change":
        return await _op_change_entity(db, agent, user, spec, args)
    if action == "delete":
        return await _op_delete_entity(db, agent, user, spec, args)

    return {"ok": False, "error": f"unsupported action '{action}'"}


async def execute_field_skill(
    db: Session,
    agent: models.Agent,
    user: models.User,
    skill_id: str,
    args: dict | None = None,
) -> dict:
    """Public entry: run a field skill by id (no agent_skills wiring required)."""
    meta = {"id": skill_id, "field_skill": True}
    return await _skill_db_field_dispatch(db, agent, user, skill_id, meta, args or {})


__all__ = [
    "_skill_db_field_dispatch",
    "_skill_list_entity_fields",
    "execute_field_skill",
]
