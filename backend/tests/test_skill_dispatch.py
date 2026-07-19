"""Skill dispatch registry + execute_skill gates (offline, no network)."""
from __future__ import annotations

import inspect

import pytest

from app.agent_skills import (
    DEFAULT_ENABLED,
    HANDLER_TABLE,
    DEFAULT_SKILL_HANDLER,
    SKILL_CATALOG,
    execute_skill,
    set_enabled_skills,
)
from app.skills_policy import is_mega_catalog_skill


def test_default_enabled_is_lean():
    """Member defaults must not dump the mega catalog."""
    assert len(DEFAULT_ENABLED) < 150
    assert len(DEFAULT_ENABLED) >= len(
        {s for s in DEFAULT_ENABLED if s}  # non-empty
    )
    by_id = {s["id"]: s for s in SKILL_CATALOG}
    mega = [i for i in DEFAULT_ENABLED if is_mega_catalog_skill(by_id.get(i) or i)]
    assert mega == [], f"mega skills leaked into DEFAULT_ENABLED: {mega[:10]}"


def test_handler_table_handlers_exist():
    """Every HANDLER_TABLE entry resolves to a callable on agent_skills (via handlers_all)."""
    import app.agent_skills as mod

    missing = []
    not_callable = []
    for skill_id, (fname, mode, extras) in HANDLER_TABLE.items():
        fn = getattr(mod, fname, None)
        if fn is None:
            missing.append((skill_id, fname))
        elif not callable(fn):
            not_callable.append((skill_id, fname))
        else:
            # Handlers are async
            assert inspect.iscoroutinefunction(fn) or callable(fn)

    assert not missing, f"Missing handlers: {missing[:20]}"
    assert not not_callable, f"Not callable: {not_callable[:20]}"
    assert len(HANDLER_TABLE) > 50
    assert DEFAULT_SKILL_HANDLER == "_skill_catalog_deliverable"
    assert callable(getattr(mod, DEFAULT_SKILL_HANDLER, None))


@pytest.mark.asyncio
async def test_unknown_skill_ok_path(db, agent_factory):
    """Unknown skill id returns structured error, does not raise."""
    agent, user = agent_factory()
    set_enabled_skills(db, agent, list(DEFAULT_ENABLED) + ["totally_fake_skill_xyz"])

    result = await execute_skill(db, agent, user, "totally_fake_skill_xyz", {})
    assert isinstance(result, dict)
    assert result.get("ok") is False
    assert "unknown" in (result.get("error") or "").lower() or "disabled" in (
        result.get("error") or ""
    ).lower() or "skill" in (result.get("error") or "").lower()


@pytest.mark.asyncio
async def test_message_agent_rejects_bad_id(db, agent_factory):
    """message_agent rejects missing / non-int to_agent_id without calling LLM."""
    agent, user = agent_factory()
    set_enabled_skills(db, agent, list(DEFAULT_ENABLED))

    # Missing to_agent_id
    r1 = await execute_skill(db, agent, user, "message_agent", {"message": "hi"})
    assert r1.get("ok") is False
    err1 = (r1.get("error") or "").lower()
    assert "to_agent_id" in err1 or "required" in err1

    # Non-existent target
    r2 = await execute_skill(
        db,
        agent,
        user,
        "message_agent",
        {"to_agent_id": 999999, "message": "hi", "expect_reply": False},
    )
    assert r2.get("ok") is False
    err2 = (r2.get("error") or "").lower()
    assert "not found" in err2 or "target" in err2

    # Empty message
    peer, _ = agent_factory(user=user, name="Peer")
    r3 = await execute_skill(
        db,
        agent,
        user,
        "message_agent",
        {"to_agent_id": peer.id, "message": "  ", "expect_reply": False},
    )
    assert r3.get("ok") is False
    assert "message" in (r3.get("error") or "").lower()
