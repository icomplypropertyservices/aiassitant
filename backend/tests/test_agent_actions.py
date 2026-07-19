"""Tests for full agent field action skillset."""
from __future__ import annotations

from app.skills.agent_actions import (
    AGENT_WRITABLE_FIELDS,
    AGENT_FIELD_SPEC,
    build_agent_action_catalog,
    parse_agent_field_skill,
    agent_action_skill_ids,
)


def test_every_writable_field_has_add_and_change():
    cat_ids = {s["id"] for s in build_agent_action_catalog()}
    for field in AGENT_WRITABLE_FIELDS:
        assert f"add_agent_{field}" in cat_ids, field
        assert f"change_agent_{field}" in cat_ids, field
        if AGENT_FIELD_SPEC[field].get("clearable", True):
            assert f"delete_agent_{field}" in cat_ids, field
        else:
            assert f"delete_agent_{field}" not in cat_ids, field


def test_entity_skills_present():
    ids = agent_action_skill_ids()
    for sid in (
        "get_agent",
        "add_agent",
        "create_agent",
        "change_agent",
        "update_agent",
        "reparent_agent",
        "demote_agent",
        "rename_agent",
        "set_agent_field",
        "list_agent_fields",
        "agent_field_ops",
        "list_agent_custom_fields",
        "get_agent_custom_field",
        "set_agent_custom_field",
        "delete_agent_custom_field",
        "set_agent_custom_fields",
    ):
        assert sid in ids


def test_parse_field_skills():
    p = parse_agent_field_skill("change_agent_personality")
    assert p and p["action"] == "change" and p["field"] == "personality"
    p = parse_agent_field_skill("delete_agent_config")
    assert p and p["action"] == "delete" and p["field"] == "config"
    p = parse_agent_field_skill("add_agent_name")
    assert p and p["action"] == "add" and p["field"] == "name"
    assert parse_agent_field_skill("delete_agent_name") is None  # name not clearable
    assert parse_agent_field_skill("not_a_skill") is None
    assert parse_agent_field_skill("change_agent")["action"] == "update"


def test_catalog_merged_into_skill_catalog():
    from app.agent_skills import SKILL_CATALOG

    ids = {s["id"] for s in SKILL_CATALOG}
    assert "change_agent_model" in ids
    assert "agent_field_ops" in ids
    assert "get_agent" in ids


def test_handlers_exported():
    import app.agent_skills as m

    assert callable(m._skill_change_agent)
    assert callable(m._skill_get_agent)
    assert callable(m._skill_agent_field_dispatch)
    assert callable(m._skill_configure_agent)
    assert callable(m._skill_list_agent_custom_fields)
    assert callable(m._skill_set_agent_custom_field)
    assert callable(m._skill_get_agent_custom_field)
    assert callable(m._skill_delete_agent_custom_field)
    assert callable(m._skill_set_agent_custom_fields)


def test_custom_fields_helpers():
    from app.skills.agent_actions import (
        get_custom_fields,
        set_custom_fields_map,
        upsert_custom_field,
        remove_custom_field,
        _normalize_field_key,
    )
    from types import SimpleNamespace
    import json

    assert _normalize_field_key(" territory ") == "territory"
    assert _normalize_field_key("autonomy") is None  # reserved

    a = SimpleNamespace(config="{}")
    assert get_custom_fields(a) == {}
    res = upsert_custom_field(a, "territory", "UK North")
    assert res["ok"] and res["key"] == "territory"
    assert get_custom_fields(a)["territory"] == "UK North"
    cfg = json.loads(a.config)
    assert cfg["custom_fields"]["territory"] == "UK North"

    upsert_custom_field(a, "quota", "100k")
    assert set_custom_fields_map(a, {"only": "one"}) == {"only": "one"}
    assert get_custom_fields(a) == {"only": "one"}

    a.config = json.dumps({"autonomy": "full", "legacy_note": "hi", "custom_fields": {"x": 1}})
    fields = get_custom_fields(a, include_legacy=True)
    assert fields.get("x") == 1
    assert fields.get("legacy_note") == "hi"

    res = remove_custom_field(a, "x")
    assert res["ok"]
    assert "x" not in res["custom_fields"]
