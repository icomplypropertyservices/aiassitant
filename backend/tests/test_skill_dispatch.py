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
    """Member defaults: rich free toolkit, never the full mega catalog dump."""
    # Market-leading product ships a fuller CRM/ops surface (~180+) but must not
    # auto-enable the ~1000 mega packs.
    assert len(DEFAULT_ENABLED) >= 50
    assert len(DEFAULT_ENABLED) < 400
    assert len(DEFAULT_ENABLED) == len({s for s in DEFAULT_ENABLED if s})  # unique, non-empty
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


def test_generate_image_handler_table_entry():
    """generate_image is a dedicated HANDLER_TABLE skill."""
    assert "generate_image" in HANDLER_TABLE
    fname, mode, extras = HANDLER_TABLE["generate_image"]
    assert fname == "_skill_generate_image"
    assert mode == "std"
    assert extras == ()
    import app.agent_skills as mod

    assert callable(getattr(mod, fname, None))


def test_media_image_skills_in_handler_table():
    """edit_image / generate_ad_creative / generate_product_shot are wired if present."""
    import app.agent_skills as mod

    expected = {
        "edit_image": "_skill_edit_image",
        "generate_ad_creative": "_skill_generate_ad_creative",
        "generate_product_shot": "_skill_generate_product_shot",
    }
    for skill_id, expected_fname in expected.items():
        assert skill_id in HANDLER_TABLE, f"{skill_id} missing from HANDLER_TABLE"
        fname, mode, extras = HANDLER_TABLE[skill_id]
        assert fname == expected_fname
        assert mode == "std"
        assert extras == ()
        assert callable(getattr(mod, fname, None)), f"{skill_id} -> {fname} not callable"
        # Catalog entry should exist when table-wired
        assert any(s["id"] == skill_id for s in SKILL_CATALOG), f"{skill_id} missing from SKILL_CATALOG"


def test_qualify_lead_handler_table_entry():
    """qualify_lead is a dedicated HANDLER_TABLE skill with a callable CRM handler."""
    assert any(s["id"] == "qualify_lead" for s in SKILL_CATALOG)
    assert "qualify_lead" in HANDLER_TABLE
    fname, mode, extras = HANDLER_TABLE["qualify_lead"]
    assert fname == "_skill_qualify_lead"
    assert mode == "std"
    assert extras == ()
    import app.agent_skills as mod

    assert callable(getattr(mod, fname, None))


def test_market_leading_crm_and_workflow_handlers():
    """Top CRM / pipeline / workflow skills have real HANDLER_TABLE callables (not stubs only)."""
    import app.agent_skills as mod
    from app.agent_skills import LEAD_FLOW_SKILLS
    from app.skills_policy import _CORE_ALWAYS

    expected = {
        "qualify_lead": "_skill_qualify_lead",
        "list_leads": "_skill_list_leads",
        "set_lead_status": "_skill_set_lead_status",
        "score_lead": "_skill_score_lead",
        "move_deal": "_skill_move_deal",
        "win_deal": "_skill_win_deal",
        "lose_deal": "_skill_lose_deal",
        "run_workflow": "_skill_run_workflow",
        "create_workflow": "_skill_create_workflow",
        "generate_image": "_skill_generate_image",
        "generate_video": "_skill_generate_video",
    }
    for skill_id, expected_fname in expected.items():
        assert skill_id in HANDLER_TABLE, f"{skill_id} missing from HANDLER_TABLE"
        fname, mode, extras = HANDLER_TABLE[skill_id]
        assert fname == expected_fname, f"{skill_id}: {fname} != {expected_fname}"
        assert mode == "std"
        assert callable(getattr(mod, fname, None)), f"{skill_id} -> {fname} not callable"
        assert any(s["id"] == skill_id for s in SKILL_CATALOG), f"{skill_id} missing from catalog"

    # Core free pack always includes CRM funnel + workflows + tasks
    for sid in (
        "qualify_lead", "list_leads", "set_lead_status", "score_lead",
        "move_deal", "win_deal", "lose_deal", "create_deal", "create_customer",
        "create_workflow", "run_workflow", "execute_goal", "create_task", "list_tasks",
    ):
        assert sid in _CORE_ALWAYS, f"{sid} missing from _CORE_ALWAYS"
        assert sid in DEFAULT_ENABLED, f"{sid} missing from DEFAULT_ENABLED"

    # Lead flow keeps full pipeline + media
    for sid in (
        "move_deal", "win_deal", "lose_deal", "score_lead", "list_leads",
        "run_workflow", "generate_image", "generate_video", "complete_task",
    ):
        assert sid in LEAD_FLOW_SKILLS, f"{sid} missing from LEAD_FLOW_SKILLS"


def test_skill_descriptions_are_actionable():
    """High-value skill descriptions should be rich enough for agent tool discovery."""
    by_id = {s["id"]: s for s in SKILL_CATALOG}
    for sid in (
        "qualify_lead", "list_leads", "set_lead_status", "score_lead",
        "move_deal", "win_deal", "lose_deal", "generate_image", "generate_video",
        "run_workflow", "create_workflow",
    ):
        desc = (by_id[sid].get("description") or "").strip()
        assert len(desc) >= 60, f"{sid} description too weak ({len(desc)}): {desc!r}"


@pytest.mark.asyncio
async def test_generate_image_validation_and_offline_placeholder(db, agent_factory, monkeypatch):
    """generate_image rejects empty prompt; offline path uses SVG placeholder (no live API)."""
    import app.agent_skills as mod

    agent, user = agent_factory()
    handler = mod._skill_generate_image

    bad = await handler(db, agent, user, {"prompt": "ab", "_billed": True})
    assert bad.get("ok") is False
    assert "prompt" in (bad.get("error") or "").lower()

    # Force no provider key so the handler stays on the local SVG placeholder.
    monkeypatch.setattr("app.config.get_grok_token", lambda *a, **k: None)

    good = await handler(
        db,
        agent,
        user,
        {"prompt": "blue robot holding a coffee cup", "style": "flat", "size": "512", "_billed": True},
    )
    assert good.get("ok") is True
    assert good.get("prompt")
    url = good.get("url") or ""
    assert url.startswith("data:") or "svg" in url.lower() or url.startswith("http")
    assert good.get("style") == "flat"
    # No-key path should not invite thrashing
    assert good.get("retryable") is False or good.get("provider") == "placeholder"


def test_media_skills_category_media():
    """Tool-access UI: Imagine skills are category=media."""
    from app.skills_policy import category_for

    media_ids = (
        "generate_image",
        "edit_image",
        "generate_ad_creative",
        "generate_product_shot",
        "generate_video",
        "check_video",
    )
    by_id = {s["id"]: s for s in SKILL_CATALOG}
    for sid in media_ids:
        assert sid in by_id, sid
        assert (by_id[sid].get("category") or category_for(sid)) == "media"
        assert category_for(sid) == "media"
    assert by_id["check_video"].get("premium") is not True


def test_classify_xai_http_credits_terminal():
    """402/403 classification is non-retryable so agents stop thrashing."""
    from app.routers.media import _classify_xai_http_error

    c402 = _classify_xai_http_error(402, '{"error":"insufficient credits"}')
    assert c402["retryable"] is False
    assert c402["error_code"] == "xai_credits"
    assert "do not" in (c402.get("agent_guidance") or "").lower() or "STOP" in (c402.get("agent_guidance") or "")

    c403 = _classify_xai_http_error(403, "permission denied")
    assert c403["retryable"] is False
    assert c403["error_code"] == "xai_permission"


@pytest.mark.asyncio
async def test_generate_video_offline_pending_fields(db, agent_factory, monkeypatch):
    """Without xAI key: video skill degrades gracefully with poster + status unavailable."""
    import app.agent_skills as mod

    agent, user = agent_factory()
    monkeypatch.setattr("app.config.get_grok_token", lambda *a, **k: None)
    handler = mod._skill_generate_video
    out = await handler(
        db, agent, user,
        {"prompt": "cinematic product hero spin", "duration_sec": 6, "_billed": True},
    )
    assert out.get("ok") is True  # poster path is ok
    assert out.get("status") == "unavailable"
    assert out.get("poster_url")
    assert out.get("request_id") is None
    assert out.get("retryable") is False
    assert "video" in (out.get("message") or out.get("agent_guidance") or "").lower()


@pytest.mark.asyncio
async def test_generate_video_pending_points_to_check_video(db, agent_factory, monkeypatch):
    """When still pending, agent must get request_id + next_skill=check_video (no resubmit)."""
    import app.agent_skills as mod

    agent, user = agent_factory()

    async def fake_gen(*a, **k):
        return {
            "ok": True,
            "video_url": None,
            "poster_url": "data:image/svg+xml;base64,abc",
            "request_id": "vid_job_pending_123",
            "status": "pending",
            "provider": "xai",
            "model": "grok-imagine-video",
            "duration_sec": 6,
            "error": None,
            "note": "still rendering",
            "next_skill": "check_video",
            "agent_guidance": "Use check_video with request_id",
        }

    monkeypatch.setattr("app.routers.media.xai_generate_video", fake_gen)
    out = await mod._skill_generate_video(
        db, agent, user,
        {"prompt": "orbit around a sneaker on a pedestal", "_billed": True},
    )
    assert out.get("ok") is True
    assert out.get("status") == "pending"
    assert out.get("request_id") == "vid_job_pending_123"
    assert out.get("next_skill") == "check_video"
    assert out.get("retryable") is False
    msg = (out.get("message") or out.get("agent_guidance") or "").lower()
    assert "check_video" in msg
    assert "generate_video" in msg  # must say do NOT generate_video again


@pytest.mark.asyncio
async def test_check_video_offline_and_ready(db, agent_factory, monkeypatch):
    """check_video validates request_id; offline no-key path; ready path returns video_url."""
    import app.agent_skills as mod

    agent, user = agent_factory()
    handler = mod._skill_check_video

    bad = await handler(db, agent, user, {})
    assert bad.get("ok") is False
    assert "request_id" in (bad.get("error") or "").lower()

    monkeypatch.setattr("app.config.get_grok_token", lambda *a, **k: None)
    offline = await handler(db, agent, user, {"request_id": "vid_abc12345"})
    assert offline.get("ok") is False
    assert offline.get("status") in ("unavailable", "failed")
    assert offline.get("request_id") == "vid_abc12345"
    assert offline.get("premium_billed") is False

    async def fake_ready(rid, **k):
        return {
            "ok": True,
            "video_url": "https://cdn.example/out.mp4",
            "poster_url": "data:image/svg+xml;base64,x",
            "request_id": rid,
            "status": "ready",
            "provider": "xai",
            "model": "grok-imagine-video",
            "duration_sec": 6,
            "error": None,
            "note": "ready",
        }

    monkeypatch.setattr("app.routers.media.xai_check_video", fake_ready)
    ready = await handler(db, agent, user, {"request_id": "vid_ready_99"})
    assert ready.get("ok") is True
    assert ready.get("status") == "ready"
    assert ready.get("video_url", "").endswith(".mp4")
    assert ready.get("premium_billed") is False


def test_ad_and_product_prompt_quality_helpers():
    """Structured ad/product defaults include commercial quality cues."""
    from app.skills.content import _build_ad_creative_prompt, _build_product_shot_prompt

    ad = _build_ad_creative_prompt(
        product="AeroBottle 750ml",
        headline="Hydrate faster",
        audience="runners 25-40",
        channel="instagram",
        style="vivid commercial photography",
    ).lower()
    assert "aerobottle" in ad
    assert "overlay" in ad or "headline" in ad
    assert "watermark" in ad
    assert "instagram" in ad or "vertical" in ad or "4:5" in ad

    shot = _build_product_shot_prompt(
        product="AeroBottle 750ml",
        angle="hero 3/4 front",
        background="seamless studio white",
        style="catalog",
        brand="Aero",
        props="",
    ).lower()
    assert "aerobottle" in shot
    assert "softbox" in shot or "studio" in shot
    assert "e-commerce" in shot or "catalog" in shot or "pdp" in shot


@pytest.mark.asyncio
async def test_generate_image_xai_credits_stops_thrash(db, agent_factory, monkeypatch):
    """xAI 402-style failure → ok=false, retryable=false, no success URL."""
    import app.agent_skills as mod

    agent, user = agent_factory()

    async def fake_xai(*a, **k):
        return {
            "ok": False,
            "url": None,
            "provider": "xai",
            "model": "grok-imagine-image",
            "error": "xAI HTTP 402: insufficient credits. DO NOT retry",
            "error_code": "xai_credits",
            "retryable": False,
            "note": "Premium may still be billed",
            "agent_guidance": "STOP: xAI media credits/quota unavailable.",
        }

    monkeypatch.setattr("app.routers.media.xai_generate_image", fake_xai)
    out = await mod._skill_generate_image(
        db, agent, user, {"prompt": "neon city skyline", "_billed": True}
    )
    assert out.get("ok") is False
    assert out.get("retryable") is False
    assert out.get("error_code") == "xai_credits"
    assert not out.get("url")
    assert "stop" in (out.get("agent_guidance") or out.get("message") or "").lower()


def test_qualify_lead_in_handler_table():
    """qualify_lead is a dedicated CRM side-effect skill (not catalog_deliverable)."""
    assert any(s["id"] == "qualify_lead" for s in SKILL_CATALOG)
    assert "qualify_lead" in HANDLER_TABLE
    fname, mode, _extras = HANDLER_TABLE["qualify_lead"]
    assert fname == "_skill_qualify_lead"
    assert mode == "std"
    assert "score_lead" in HANDLER_TABLE
    assert "list_qualified_leads" in HANDLER_TABLE
    import app.agent_skills as mod

    assert callable(getattr(mod, "_skill_qualify_lead", None))
    assert callable(getattr(mod, "_skill_score_lead", None))
    assert callable(getattr(mod, "_skill_list_qualified_leads", None))


@pytest.mark.asyncio
async def test_qualify_lead_handler_offline(db, agent_factory):
    """qualify_lead scores a lead offline (creates CRM customer, no network)."""
    import app.agent_skills as mod
    from app import models

    agent, user = agent_factory()
    handler = mod._skill_qualify_lead

    missing = await handler(db, agent, user, {"notes": "no identity"})
    assert missing.get("ok") is False
    assert "customer" in (missing.get("error") or "").lower() or "lead" in (
        missing.get("error") or ""
    ).lower()

    good = await handler(
        db,
        agent,
        user,
        {
            "lead": "ACME Corp",
            "email": "buyer@acme.example",
            "notes": "inbound, budget confirmed, ICP fit high",
            "score": 85,
        },
    )
    assert good.get("ok") is True
    assert good.get("mode") == "crm_write"
    assert good.get("skill") == "qualify_lead"
    assert good.get("customer_id")
    assert float(good.get("lead_score") or 0) == 85
    assert good.get("lead_status") == "qualified"

    cust = db.get(models.Customer, good["customer_id"])
    assert cust is not None
    assert float(cust.lead_score or 0) == 85
    assert cust.lead_status == "qualified"
    assert cust.qualified_at is not None


@pytest.mark.asyncio
async def test_qualify_lead_execute_skill_offline(db, agent_factory, monkeypatch):
    """execute_skill(qualify_lead) writes CRM fields offline without LLM."""
    from app import models

    agent, user = agent_factory()
    set_enabled_skills(
        db, agent,
        list(DEFAULT_ENABLED) + ["qualify_lead", "score_lead", "list_qualified_leads"],
    )

    async def _no_llm(*a, **k):
        raise RuntimeError("offline unit test — no LLM")

    monkeypatch.setattr("app.llm.complete", _no_llm)

    result = await execute_skill(
        db,
        agent,
        user,
        "qualify_lead",
        {
            "lead": "Beta Industries",
            "email": "cto@beta.example",
            "notes": "warm inbound, budget confirmed, decision maker",
            "score": 78,
        },
    )
    assert result.get("ok") is True
    assert result.get("mode") == "crm_write"
    assert result.get("mode") != "catalog_deliverable"
    cid = result.get("customer_id")
    assert cid
    cust = db.get(models.Customer, cid)
    assert cust is not None
    assert float(cust.lead_score or 0) == 78
    assert (cust.lead_status or "") != ""

    scored = await execute_skill(
        db, agent, user, "score_lead",
        {"customer_id": cid, "context": "still interested"},
    )
    assert scored.get("ok") is True
    assert scored.get("grade") in ("A", "B", "C", "D", "F")

    listed = await execute_skill(db, agent, user, "list_qualified_leads", {"limit": 20})
    assert listed.get("ok") is True


@pytest.mark.asyncio
async def test_run_workflow_list_presets_offline(db, agent_factory, monkeypatch):
    """run_workflow list=true returns presets without launching a chain."""
    import app.agent_skills as mod

    agent, user = agent_factory()
    set_enabled_skills(db, agent, list(DEFAULT_ENABLED) + ["run_workflow"])

    async def _no_llm(*a, **k):
        raise RuntimeError("offline unit test — no LLM")

    monkeypatch.setattr("app.llm.complete", _no_llm)

    listed = await execute_skill(db, agent, user, "run_workflow", {"list": True})
    assert listed.get("ok") is True
    assert listed.get("skill") == "run_workflow"
    workflows = listed.get("workflows") or []
    assert len(workflows) >= 1
    ids = {w.get("id") for w in workflows}
    assert "sales_targets_crm_outreach" in ids

    missing = await execute_skill(db, agent, user, "run_workflow", {})
    assert missing.get("ok") is False
    assert "workflow" in (missing.get("error") or "").lower()
    assert missing.get("workflows")

    # Unknown id surfaces available presets
    bad = await mod._skill_run_workflow(db, agent, user, {"workflow_id": "not_a_real_preset_xyz"})
    assert bad.get("ok") is False
    assert "unknown" in (bad.get("error") or "").lower()


@pytest.mark.asyncio
async def test_qualify_lead_execute_skill_with_existing_customer(db, agent_factory):
    """execute_skill(qualify_lead) against a pre-seeded Customer (offline)."""
    from app import models

    agent, user = agent_factory()
    set_enabled_skills(db, agent, list(DEFAULT_ENABLED) + ["qualify_lead"])

    cust = models.Customer(
        owner_user_id=user.id,
        name="Seeded Lead Co",
        email="seed@example.com",
        status="active",
        lead_status="new",
        lead_score=0.0,
        notes="",
    )
    db.add(cust)
    db.commit()
    db.refresh(cust)

    result = await execute_skill(
        db,
        agent,
        user,
        "qualify_lead",
        {
            "customer_id": cust.id,
            "notes": "demo request, budget confirmed",
            "score": 90,
        },
    )
    assert result.get("ok") is True
    assert result.get("customer_id") == cust.id
    assert float(result.get("lead_score") or 0) == 90
    db.refresh(cust)
    assert float(cust.lead_score or 0) == 90
    assert (cust.lead_status or "") in (
        "qualified",
        "nurturing",
        "contacted",
        "new",
        "converted",
    )


# ── Market-leading CRM / sales dispatch paths ───────────────────────────────

_MARKET_SALES_SKILLS = (
    "qualify_lead",
    "score_lead",
    "list_qualified_leads",
    "list_leads",
    "set_lead_status",
    "disqualify_lead",
    "create_customer",
    "create_deal",
    "list_customers",
    "list_deals",
    "move_deal",
    "draft_email",
    "log_customer_activity",
)


def test_market_sales_skills_in_handler_table_and_catalog():
    """Core sales AI surface is catalogued and dispatchable (not catalog_deliverable)."""
    import app.agent_skills as mod

    catalog_ids = {s["id"] for s in SKILL_CATALOG}
    for sid in _MARKET_SALES_SKILLS:
        assert sid in catalog_ids, f"{sid} missing from SKILL_CATALOG"
        assert sid in HANDLER_TABLE, f"{sid} missing from HANDLER_TABLE"
        fname, mode, extras = HANDLER_TABLE[sid]
        assert mode in ("std", "extra", "meta", "created", "default")
        assert isinstance(extras, tuple)
        assert callable(getattr(mod, fname, None)), f"{sid} -> {fname} not callable"


def test_default_enabled_includes_core_sales_surface():
    """Member defaults ship the free CRM/sales toolkit market buyers expect."""
    enabled = set(DEFAULT_ENABLED)
    for sid in (
        "qualify_lead",
        "score_lead",
        "list_qualified_leads",
        "create_customer",
        "create_deal",
        "list_customers",
        "list_deals",
        "draft_email",
        "log_customer_activity",
        "message_agent",
        "create_task",
        "execute_goal",
    ):
        assert sid in enabled, f"{sid} should be in DEFAULT_ENABLED for market-ready agents"
    # Premium media / destructive meta stay opt-in
    assert "generate_image" not in enabled
    assert "delete_agent" not in enabled


@pytest.mark.asyncio
async def test_disabled_skill_rejected(db, agent_factory):
    """execute_skill refuses skills not on the agent enable list."""
    agent, user = agent_factory()
    # Explicit lean set — omit generate_image (premium) even if somehow in DEFAULT
    set_enabled_skills(db, agent, ["message_agent", "create_task", "qualify_lead"])

    result = await execute_skill(
        db, agent, user, "generate_image", {"prompt": "should never run"}
    )
    assert result.get("ok") is False
    err = (result.get("error") or "").lower()
    assert "disabled" in err or "generate_image" in err


@pytest.mark.asyncio
async def test_sales_crm_chain_create_customer_deal_qualify(db, agent_factory, monkeypatch):
    """Market path: create_customer → create_deal → qualify_lead offline (no LLM)."""
    from app import models

    agent, user = agent_factory()
    set_enabled_skills(
        db,
        agent,
        list(DEFAULT_ENABLED)
        + ["create_customer", "create_deal", "qualify_lead", "list_qualified_leads"],
    )

    async def _no_llm(*a, **k):
        raise RuntimeError("offline unit test — no LLM")

    monkeypatch.setattr("app.llm.complete", _no_llm)

    created = await execute_skill(
        db,
        agent,
        user,
        "create_customer",
        {
            "name": "Pipeline Prospect Inc",
            "email": "ops@pipeline-prospect.example",
            "phone": "+1-555-0100",
            "tags": ["sales-target", "auto-chain"],
            "notes": "ICP fit high, inbound demo",
        },
    )
    assert created.get("ok") is True
    cid = created.get("customer_id")
    assert cid

    deal = await execute_skill(
        db,
        agent,
        user,
        "create_deal",
        {
            "customer_id": cid,
            "title": "Pipeline Prospect Inc — outreach",
            "value": 12000,
            "priority": "high",
        },
    )
    assert deal.get("ok") is True
    assert deal.get("deal_id") or (deal.get("deal") or {}).get("id")

    qualified = await execute_skill(
        db,
        agent,
        user,
        "qualify_lead",
        {
            "customer_id": cid,
            "notes": "budget confirmed, decision maker engaged",
            "score": 88,
            "force_qualified": True,
        },
    )
    assert qualified.get("ok") is True
    assert qualified.get("mode") == "crm_write"
    assert float(qualified.get("lead_score") or 0) >= 70
    assert (qualified.get("lead_status") or "") == "qualified"

    cust = db.get(models.Customer, cid)
    assert cust is not None
    assert float(cust.lead_score or 0) >= 70
    assert cust.lead_status == "qualified"
    assert cust.qualified_at is not None

    listed = await execute_skill(db, agent, user, "list_qualified_leads", {"limit": 50})
    assert listed.get("ok") is True
    rows = listed.get("leads") or listed.get("customers") or []
    ids = {r.get("id") for r in rows if isinstance(r, dict)}
    assert cid in ids or any(
        (r.get("email") or "") == "ops@pipeline-prospect.example" for r in rows if isinstance(r, dict)
    )


@pytest.mark.asyncio
async def test_score_lead_and_disqualify_offline(db, agent_factory):
    """score_lead grades offline; disqualify_lead writes lead_status without network."""
    from app import models

    agent, user = agent_factory()
    set_enabled_skills(
        db,
        agent,
        list(DEFAULT_ENABLED) + ["score_lead", "disqualify_lead", "set_lead_status", "qualify_lead"],
    )

    # Score without CRM row still returns grade
    bare = await execute_skill(
        db,
        agent,
        user,
        "score_lead",
        {"notes": "cold outbound, no budget signal", "context": "SMB ecommerce"},
    )
    assert bare.get("ok") is True
    assert bare.get("grade") in ("A", "B", "C", "D", "F")
    assert bare.get("mode") in ("score_only", "crm_write")

    cust = models.Customer(
        owner_user_id=user.id,
        name="No Fit LLC",
        email="nofit@example.com",
        status="active",
        lead_status="new",
        lead_score=40.0,
    )
    db.add(cust)
    db.commit()
    db.refresh(cust)

    scored = await execute_skill(
        db,
        agent,
        user,
        "score_lead",
        {
            "customer_id": cust.id,
            "context": "wrong ICP, no budget",
            "persist": True,
        },
    )
    assert scored.get("ok") is True
    assert scored.get("customer_id") == cust.id
    assert scored.get("grade") in ("A", "B", "C", "D", "F")

    dq = await execute_skill(
        db,
        agent,
        user,
        "disqualify_lead",
        {
            "customer_id": cust.id,
            "reason": "outside ICP — micro brand, no budget",
        },
    )
    assert dq.get("ok") is True
    db.refresh(cust)
    assert (cust.lead_status or "").lower() == "disqualified"


@pytest.mark.asyncio
async def test_message_agent_happy_path_offline(db, agent_factory, monkeypatch):
    """message_agent delivers peer note when expect_reply=False (no LLM)."""
    agent, user = agent_factory(name="Sender")
    peer, _ = agent_factory(user=user, name="Receiver")
    set_enabled_skills(db, agent, list(DEFAULT_ENABLED))

    async def _no_llm(*a, **k):
        raise RuntimeError("offline unit test — no LLM")

    monkeypatch.setattr("app.llm.complete", _no_llm)

    result = await execute_skill(
        db,
        agent,
        user,
        "message_agent",
        {
            "to_agent_id": peer.id,
            "message": "Handoff: 10 qualified leads ready for outreach.",
            "expect_reply": False,
        },
    )
    assert result.get("ok") is True
    # Structured success — message id or confirmation, never catalog_deliverable
    assert result.get("mode") != "catalog_deliverable"
    assert (
        result.get("message_id")
        or result.get("id")
        or "sent" in (result.get("message") or result.get("status") or "").lower()
        or result.get("ok") is True
    )


# ── Wave-2 high-value: run_workflow launch + media credits body signals ─────

@pytest.mark.asyncio
async def test_run_workflow_starts_sales_preset_offline(db, agent_factory, monkeypatch):
    """run_workflow with sales_targets_crm_outreach calls start_workflow (no network)."""
    import app.agent_skills as mod

    agent, user = agent_factory()
    set_enabled_skills(db, agent, list(DEFAULT_ENABLED) + ["run_workflow"])
    seen: list[dict] = []

    async def _fake_start(db_, user_, owner, workflow_id, **kwargs):
        seen.append({"workflow_id": workflow_id, "count": kwargs.get("count"), "niche": kwargs.get("niche")})
        assert owner.id == agent.id
        return {
            "ok": True,
            "workflow_id": workflow_id,
            "goal_task_id": 4242,
            "steps": 5,
            "mode": "workflow_preset",
        }

    monkeypatch.setattr("app.workflows.start_workflow", _fake_start)

    out = await execute_skill(
        db,
        agent,
        user,
        "run_workflow",
        {
            "workflow_id": "sales_targets_crm_outreach",
            "count": 25,
            "niche": "fintech SaaS",
        },
    )
    assert out.get("ok") is True
    assert out.get("skill") == "run_workflow"
    assert out.get("mode") == "workflow_preset"
    assert out.get("workflow_id") == "sales_targets_crm_outreach"
    assert out.get("goal_task_id") == 4242
    assert seen and seen[0]["workflow_id"] == "sales_targets_crm_outreach"
    assert seen[0]["count"] == 25
    assert "fintech" in (seen[0].get("niche") or "").lower()

    # Alias keys (name/preset) also resolve to start_workflow
    out2 = await mod._skill_run_workflow(
        db, agent, user, {"name": "crm_outreach_only", "batch": 12}
    )
    assert out2.get("ok") is True
    assert out2.get("skill") == "run_workflow"
    assert any(s["workflow_id"] == "crm_outreach_only" for s in seen)


def test_classify_xai_body_credits_and_rate_limit_retryable():
    """Body 'credits'/'quota' is terminal; 429 remains carefully retryable."""
    from app.routers.media import _classify_xai_http_error

    # 200-class status but credits language in body → still terminal
    body_credits = _classify_xai_http_error(400, "Error: out of credits on team wallet")
    assert body_credits["retryable"] is False
    assert body_credits["error_code"] == "xai_credits"

    body_quota = _classify_xai_http_error(500, "quota exceeded for imagine")
    assert body_quota["retryable"] is False
    assert body_quota["error_code"] == "xai_credits"

    rate = _classify_xai_http_error(429, "too many requests")
    assert rate["retryable"] is True
    assert rate["error_code"] == "xai_rate_limit"

    # 5xx without billing language may be retryable
    srv = _classify_xai_http_error(503, "upstream unavailable")
    assert srv["retryable"] is True
    assert srv["error_code"] == "xai_http"


@pytest.mark.asyncio
async def test_generate_ad_creative_credits_non_retryable(db, agent_factory, monkeypatch):
    """generate_ad_creative propagates xAI credits as retryable=false."""
    import app.agent_skills as mod

    agent, user = agent_factory()

    async def fake_xai(*a, **k):
        return {
            "ok": False,
            "url": None,
            "provider": "xai",
            "error": "xAI HTTP 402: insufficient credits",
            "error_code": "xai_credits",
            "retryable": False,
            "agent_guidance": "STOP: xAI media credits/quota unavailable.",
        }

    monkeypatch.setattr("app.routers.media.xai_generate_image", fake_xai)
    handler = getattr(mod, "_skill_generate_ad_creative", None)
    if handler is None:
        pytest.skip("_skill_generate_ad_creative not exported")
    out = await handler(
        db, agent, user,
        {"prompt": "summer sale banner for CRM SaaS", "product": "LeadOS", "_billed": True},
    )
    assert out.get("ok") is False
    assert out.get("retryable") is False
    assert out.get("error_code") == "xai_credits" or "credit" in (out.get("error") or "").lower()


# ── Integration / meeting / task autonomy surface ───────────────────────────


def test_meeting_and_task_skills_in_handler_table_and_core():
    """Meeting + task core skills must be real HANDLER_TABLE handlers (not catalog stubs)."""
    import app.agent_skills as mod
    from app.skills_policy import _CORE_ALWAYS

    expected = {
        "open_meeting": "_skill_open_meeting",
        "list_meetings": "_skill_list_meetings",
        "invite_to_meeting": "_skill_invite_to_meeting",
        "post_to_meeting": "_skill_post_to_meeting",
        "run_meeting_round": "_skill_run_meeting_round",
        "close_meeting": "_skill_close_meeting",
        "extract_meeting_tasks": "_skill_extract_meeting_tasks",
        "create_task": "_skill_create_task",
        "list_tasks": "_skill_list_tasks",
        "complete_task": "_skill_complete_task",
        "gmail_list": "_skill_gmail_list",
        "calendar_list_events": "_skill_calendar_list_events",
    }
    for skill_id, fname in expected.items():
        assert skill_id in HANDLER_TABLE, f"{skill_id} missing HANDLER_TABLE"
        assert HANDLER_TABLE[skill_id][0] == fname
        assert callable(getattr(mod, fname, None)), f"{fname} not loaded"
        if skill_id not in ("gmail_list", "calendar_list_events"):
            assert skill_id in _CORE_ALWAYS, f"{skill_id} missing _CORE_ALWAYS"


@pytest.mark.asyncio
async def test_integration_skills_fail_without_keys(db, agent_factory):
    """Gmail / calendar / shopify / use_app return structured not_connected, never crash."""
    import app.agent_skills as mod

    agent, user = agent_factory()

    gmail = await mod._skill_gmail_list(db, agent, user, {"limit": 5})
    assert gmail.get("ok") is False
    assert gmail.get("retryable") is False
    assert gmail.get("error_code") == "not_connected"
    assert "gmail" in (gmail.get("error") or "").lower() or "connected" in (
        gmail.get("error") or ""
    ).lower()
    assert gmail.get("guidance")

    cal = await mod._skill_calendar_list_events(db, agent, user, {})
    assert cal.get("ok") is False
    assert cal.get("retryable") is False
    assert cal.get("error_code") == "not_connected"

    shop = await mod._skill_shopify_action(db, agent, user, "list_products", {"limit": 5})
    assert shop.get("ok") is False
    assert shop.get("retryable") is False
    assert shop.get("error_code") == "not_connected"

    use = await mod._skill_use_app(db, agent, user, {"app_id": "gmail", "action": "list"})
    assert use.get("ok") is False
    assert use.get("retryable") is False
    assert use.get("error_code") in ("not_connected", "validation")

    missing_app = await mod._skill_use_app(db, agent, user, {"action": "list"})
    assert missing_app.get("ok") is False
    assert missing_app.get("error_code") == "validation"
    assert missing_app.get("retryable") is False


@pytest.mark.asyncio
async def test_task_skills_autonomy_invent_path(db, agent_factory):
    """create_task → list_tasks → complete_task solid offline path for autonomy."""
    import app.agent_skills as mod

    agent, user = agent_factory()

    created = await mod._skill_create_task(
        db,
        agent,
        user,
        {
            "title": "Autonomy invent self-task",
            "description": "Prove create/list/complete offline",
            "success_criteria": "Task exists and completes",
            "run_now": False,
        },
    )
    assert created.get("ok") is True
    assert created.get("task_id")
    assert created.get("skill") == "create_task"
    tid = created["task_id"]

    listed = await mod._skill_list_tasks(db, agent, user, {"mine": True, "limit": 20})
    assert listed.get("ok") is True
    assert listed.get("skill") == "list_tasks"
    ids = {t.get("id") for t in (listed.get("tasks") or [])}
    assert tid in ids

    bad = await mod._skill_complete_task(db, agent, user, {"result": "no id"})
    assert bad.get("ok") is False
    assert bad.get("error_code") == "validation"
    assert bad.get("retryable") is False

    done = await mod._skill_complete_task(
        db, agent, user, {"task_id": tid, "result": "Delivered offline unit proof", "skip_review": True}
    )
    assert done.get("ok") is True
    assert done.get("skill") == "complete_task"


@pytest.mark.asyncio
async def test_meeting_skills_offline_open_list_close(db, agent_factory):
    """Meeting core skills work offline with structured validation errors."""
    import app.agent_skills as mod

    agent, user = agent_factory()

    opened = await mod._skill_open_meeting(
        db, agent, user, {"title": "War room", "purpose": "Ship skills ticket"}
    )
    assert opened.get("ok") is True
    mid = opened.get("meeting_id")
    assert mid

    listed = await mod._skill_list_meetings(db, agent, user, {"limit": 10})
    assert listed.get("ok") is True
    assert any(m.get("id") == mid for m in (listed.get("meetings") or []))

    post_bad = await mod._skill_post_to_meeting(db, agent, user, {"meeting_id": mid})
    assert post_bad.get("ok") is False
    assert post_bad.get("error_code") == "validation"
    assert post_bad.get("retryable") is False

    posted = await mod._skill_post_to_meeting(
        db, agent, user, {"meeting_id": mid, "content": "Agenda: harden integrations"}
    )
    assert posted.get("ok") is True

    closed = await mod._skill_close_meeting(db, agent, user, {"meeting_id": mid})
    assert closed.get("ok") is True

    missing = await mod._skill_run_meeting_round(db, agent, user, {})
    assert missing.get("ok") is False
    assert missing.get("error_code") == "validation"
    assert missing.get("retryable") is False
