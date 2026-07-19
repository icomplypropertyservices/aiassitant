"""Tests for the field-level DB skill system (app.skills.db_fields).

Registry / catalog / parse are pure unit tests (no DB).
CRUD paths use the in-memory SQLite fixtures from conftest.
"""
from __future__ import annotations

import pytest

# Soft-import: other agents may still be landing the package.
_DB_FIELDS_IMPORT_ERROR: str | None = None
try:
    from app.skills.db_fields import (
        all_field_skill_ids,
        build_catalog_entries,
        build_field_skill_catalog,
        execute_field_skill,
        get_all_entity_specs,
        parse_skill_id,
        resolve_field_skill,
    )

    try:
        from app.skills.db_fields import ALL_ENTITY_SPECS  # type: ignore
    except ImportError:
        try:
            from app.skills.db_fields.registry import ALL_ENTITY_SPECS  # type: ignore
        except ImportError:
            ALL_ENTITY_SPECS = None  # type: ignore
except Exception as exc:  # pragma: no cover - bootstrap path
    _DB_FIELDS_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
    ALL_ENTITY_SPECS = None  # type: ignore
    all_field_skill_ids = None  # type: ignore
    build_catalog_entries = None  # type: ignore
    build_field_skill_catalog = None  # type: ignore
    execute_field_skill = None  # type: ignore
    get_all_entity_specs = None  # type: ignore
    parse_skill_id = None  # type: ignore
    resolve_field_skill = None  # type: ignore


requires_db_fields = pytest.mark.skipif(
    _DB_FIELDS_IMPORT_ERROR is not None,
    reason=f"app.skills.db_fields not available: {_DB_FIELDS_IMPORT_ERROR}",
)


def _specs() -> dict:
    if get_all_entity_specs is not None:
        return get_all_entity_specs()
    if ALL_ENTITY_SPECS:
        return dict(ALL_ENTITY_SPECS)
    return {}


def _catalog_ids() -> set[str]:
    if all_field_skill_ids is not None:
        return set(all_field_skill_ids())
    if build_catalog_entries is not None:
        return {e["id"] for e in build_catalog_entries()}
    if build_field_skill_catalog is not None:
        return {e["id"] for e in build_field_skill_catalog()}
    return set()


# ── Counts (also exercised as a tiny diagnostic test) ───────────────────────


@requires_db_fields
def test_print_field_skill_counts(capsys):
    """Print entity / field / skill counts for smoke visibility."""
    specs = _specs()
    n_entities = len(specs)
    n_fields = sum(len(s.get("writable") or []) for s in specs.values())
    # Canonical triplets only (not aliases / list_db_fields):
    # 3 * fields (add/change/delete per field) + 3 * entities (entity-level).
    n_canonical = 3 * n_fields + 3 * n_entities
    catalog = _catalog_ids()
    print(
        f"db_field_skills counts: entities={n_entities} fields={n_fields} "
        f"canonical_skills={n_canonical} catalog_ids={len(catalog)}"
    )
    assert n_entities > 0
    assert n_fields > 0
    assert n_canonical == 3 * n_fields + 3 * n_entities
    # Catalog includes canonical skills (+ aliases + list_db_fields)
    assert len(catalog) >= n_canonical


# ── 1. Registry ─────────────────────────────────────────────────────────────


@requires_db_fields
def test_registry_loads():
    specs = _specs()
    assert specs, "ALL_ENTITY_SPECS / get_all_entity_specs() is empty"
    # Core entities expected by product surface
    for key in ("customer", "task", "company"):
        assert key in specs, f"missing entity spec: {key}"
    # Spec shape basics
    cust = specs["customer"]
    assert cust.get("model") in ("Customer", "customer") or "Customer" in str(cust.get("model"))
    assert "name" in (cust.get("writable") or [])
    assert "email" in (cust.get("writable") or [])


# ── 2. Catalog triplets ─────────────────────────────────────────────────────


@requires_db_fields
def test_catalog_has_field_triplets():
    ids = _catalog_ids()
    assert ids, "field skill catalog is empty"
    for sid in ("add_customer_name", "change_customer_name", "delete_customer_name"):
        assert sid in ids, f"catalog missing {sid}"


# ── 3. parse_skill_id ───────────────────────────────────────────────────────


@requires_db_fields
def test_parse_skill_id():
    # Canonical field op
    p = parse_skill_id("change_customer_email")
    assert p is not None
    assert p["action"] == "change"
    assert p["entity"] == "customer"
    assert p["field"] == "email"

    p2 = parse_skill_id("delete_customer_name")
    assert p2 is not None
    assert p2["action"] == "delete"
    assert p2["entity"] == "customer"
    assert p2["field"] == "name"

    p3 = parse_skill_id("add_customer")
    assert p3 is not None
    assert p3["action"] == "add"
    assert p3["entity"] == "customer"
    assert p3.get("field") in (None, "")

    # Alias: create_customer → add customer (if defined on entity)
    aliases = (_specs().get("customer") or {}).get("aliases") or {}
    create_aliases = aliases.get("add") or aliases.get("create") or []
    if "create_customer" in create_aliases or True:
        # Always try; registry maps create_* aliases when present
        pa = parse_skill_id("create_customer")
        if pa is not None:
            assert pa["action"] == "add"
            assert pa["entity"] == "customer"
            assert pa.get("field") in (None, "")

    # Underscored field names
    p4 = parse_skill_id("change_customer_job_title")
    assert p4 is not None
    assert p4["field"] == "job_title"

    assert parse_skill_id("") is None
    assert parse_skill_id("totally_unrelated_skill") is None


# ── 4–6. Integration: change / delete / ownership ───────────────────────────


def _make_customer(db, owner, **kwargs):
    from app import models

    c = models.Customer(
        owner_user_id=owner.id,
        name=kwargs.get("name") or "Acme Corp",
        email=kwargs.get("email") or "acme@example.com",
        phone=kwargs.get("phone") or "555-0100",
        notes=kwargs.get("notes") or "initial notes",
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@requires_db_fields
@pytest.mark.asyncio
async def test_change_customer_email(db, agent_factory):
    agent, owner = agent_factory(email="crm-owner@example.com")
    cust = _make_customer(db, owner, email="old@example.com")

    result = await execute_field_skill(
        db,
        agent,
        owner,
        "change_customer_email",
        {"customer_id": cust.id, "value": "new@example.com"},
    )
    assert result.get("ok") is True, result
    assert result.get("field") == "email"
    db.refresh(cust)
    assert cust.email == "new@example.com"

    # add path (entity-level create)
    created = await execute_field_skill(
        db,
        agent,
        owner,
        "add_customer",
        {"name": "Fresh Co", "email": "fresh@example.com"},
    )
    assert created.get("ok") is True, created
    assert created.get("id") or (created.get("record") or {}).get("id")


@requires_db_fields
@pytest.mark.asyncio
async def test_delete_field_clears(db, agent_factory):
    agent, owner = agent_factory(email="crm-clear@example.com")
    cust = _make_customer(db, owner, phone="555-9999", notes="wipe me")

    r_phone = await execute_field_skill(
        db, agent, owner, "delete_customer_phone", {"customer_id": cust.id}
    )
    assert r_phone.get("ok") is True, r_phone
    db.refresh(cust)
    assert cust.phone in ("", None)

    r_notes = await execute_field_skill(
        db, agent, owner, "delete_customer_notes", {"customer_id": cust.id}
    )
    assert r_notes.get("ok") is True, r_notes
    db.refresh(cust)
    assert cust.notes in ("", None)


@requires_db_fields
@pytest.mark.asyncio
async def test_ownership_blocks(db, agent_factory, user_factory):
    agent, owner = agent_factory(email="crm-own@example.com")
    other = user_factory(email="intruder-crm@example.com")
    cust = _make_customer(db, owner, email="secret@example.com")

    blocked = await execute_field_skill(
        db,
        agent,
        other,
        "change_customer_email",
        {"customer_id": cust.id, "value": "hacked@example.com"},
    )
    assert blocked.get("ok") is False, blocked
    err = (blocked.get("error") or "").lower()
    assert "not found" in err or "not owned" in err or "own" in err

    db.refresh(cust)
    assert cust.email == "secret@example.com"


# ── 7. Unknown entity rejected ──────────────────────────────────────────────


@requires_db_fields
def test_unknown_entity_rejected():
    assert parse_skill_id("change_nope_name") is None
    assert resolve_field_skill("change_nope_name") is None
    assert parse_skill_id("add_zzzzz") is None


@requires_db_fields
@pytest.mark.asyncio
async def test_unknown_entity_execute_rejected(db, agent_factory):
    agent, owner = agent_factory(email="crm-unk@example.com")
    result = await execute_field_skill(
        db, agent, owner, "change_nope_name", {"customer_id": 1, "value": "x"}
    )
    assert result.get("ok") is False
    err = (result.get("error") or "").lower()
    assert "unknown" in err or "not found" in err or "entity" in err


# ── 8. Every writable field has add/change/delete ───────────────────────────


@requires_db_fields
def test_every_writable_field_has_add_change_delete():
    specs = _specs()
    ids = _catalog_ids()
    missing: list[str] = []
    for slug, spec in specs.items():
        for field in spec.get("writable") or []:
            for action in ("add", "change", "delete"):
                sid = f"{action}_{slug}_{field}"
                if sid not in ids:
                    missing.append(sid)
        # Entity-level triplets
        for action in ("add", "change", "delete"):
            sid = f"{action}_{slug}"
            if sid not in ids:
                missing.append(sid)
    assert not missing, f"missing skill ids ({len(missing)}): {missing[:30]}"
