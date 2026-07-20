"""Sales multi-agent workflow presets, goal decomposition, and CRM path."""
from __future__ import annotations

from app.task_chain import (
    looks_like_sales_pipeline,
    decompose_goal,
    decompose_sales_pipeline,
    _extract_count,
)
from app.workflows import list_workflow_presets, build_workflow_prompt, get_preset
from app.agent_scaffold import apply_create_defaults, recommended_model


def test_extract_count():
    assert _extract_count("get 50 sales targets") == 50
    assert _extract_count("find 25 leads") == 25
    assert _extract_count("no number here", default=40) == 40


def test_looks_like_sales_pipeline():
    assert looks_like_sales_pipeline(
        "Get 50 sales targets and save in CRM then email and call them"
    )
    assert not looks_like_sales_pipeline("hello")


def test_decompose_sales_steps():
    steps = decompose_goal(
        "Get 50 sales targets and save them in the CRM, then send emails and calls and update pipelines"
    )
    titles = " ".join(s["title"].lower() for s in steps)
    assert "target" in titles or "generate" in titles
    assert any("crm" in s["title"].lower() or "crm" in s["description"].lower() for s in steps)
    assert any("email" in s["description"].lower() or "outreach" in s["title"].lower() for s in steps)
    assert any(s.get("role_hint") == "outreach" for s in steps)
    blob = " ".join(s.get("description", "") for s in steps).lower()
    assert "qualify_lead" in blob


def test_decompose_sales_pipeline_mentions_qualify_lead():
    steps = decompose_sales_pipeline("Get 40 sales targets, save in CRM, outreach, update pipeline")
    assert len(steps) >= 4
    blob = " ".join(
        f"{s.get('title', '')} {s.get('description', '')} {s.get('done_when', '')}"
        for s in steps
    ).lower()
    assert "qualify_lead" in blob
    # CRM import step must instruct the skill explicitly
    crm_steps = [
        s for s in steps
        if "crm" in (s.get("title") or "").lower() or "qualify" in (s.get("title") or "").lower()
    ]
    assert crm_steps
    assert any("qualify_lead" in (s.get("description") or "").lower() for s in crm_steps)


def test_workflow_preset_build():
    presets = list_workflow_presets()
    assert any(p["id"] == "sales_targets_crm_outreach" for p in presets)
    pr = get_preset("sales_targets_crm_outreach")
    prompt, steps = build_workflow_prompt(pr, count=30, niche="fintech")
    assert "30" in prompt
    assert "fintech" in prompt.lower() or "niche" in prompt.lower() or "ICP" in prompt or "fintech" in prompt
    assert len(steps) >= 4
    blob = " ".join(s.get("description", "") for s in steps).lower()
    assert "qualify_lead" in blob


def test_support_ticket_triage_mentions_draft_email_and_log_activity():
    pr = get_preset("support_ticket_triage")
    assert pr is not None
    assert pr.get("category") == "support"
    prompt, steps = build_workflow_prompt(pr)
    assert "triage" in prompt.lower() or "support" in prompt.lower()
    assert len(steps) >= 3
    blob = " ".join(
        f"{s.get('title', '')} {s.get('description', '')} {s.get('done_when', '')}"
        for s in steps
    ).lower()
    assert "draft_email" in blob
    assert "log_customer_activity" in blob
    # Resolve step must require both skills
    resolve = next(
        (s for s in steps if "reply" in (s.get("title") or "").lower()
         or "draft" in (s.get("title") or "").lower()),
        steps[1],
    )
    desc = (resolve.get("description") or "").lower()
    assert "draft_email" in desc
    assert "log_customer_activity" in desc


def test_workflows_coverage_by_category():
    from collections import Counter
    from app.workflows import workflows_for_template, WORKFLOW_PRESETS

    presets = list_workflow_presets()
    assert len(presets) >= 24
    assert len(presets) <= 26  # preferred ceiling for catalog focus
    cats = Counter(p.get("category") for p in presets)
    for need in ("sales", "support", "marketing", "coding", "ops", "product"):
        assert cats.get(need, 0) >= 3, f"expected ≥3 {need} workflows, got {cats.get(need)}"
    assert cats.get("research", 0) >= 2, "expected research/finance presets"
    # every preset has agent_types + buildable steps (no empty stubs)
    for p in WORKFLOW_PRESETS:
        assert p.get("agent_types"), p["id"]
        _, steps = build_workflow_prompt(p)
        assert len(steps) >= 3, p["id"]
        for s in steps:
            assert (s.get("title") or "").strip(), p["id"]
            assert (s.get("description") or "").strip(), p["id"]
            assert s.get("role_hint"), p["id"]
    sales = workflows_for_template("sales")
    assert all(
        w.get("category") in ("sales", "product", "support")
        or "sales" in (w.get("agent_types") or [])
        for w in sales
    )
    assert any(w["id"] == "sales_targets_crm_outreach" for w in sales)
    coding = workflows_for_template("coding")
    assert any(w.get("category") == "coding" for w in coding)
    assert all(w.get("category") == "coding" for w in coding) or len(coding) >= 4
    support = workflows_for_template("support")
    assert any(w["id"] == "support_ticket_triage" for w in support)
    marketing = workflows_for_template("marketing")
    assert any(w.get("category") == "marketing" for w in marketing)
    ops = workflows_for_template("ops")
    assert any(w.get("category") == "ops" for w in ops)
    product = workflows_for_template("product")
    assert any(w.get("category") == "product" for w in product)
    booking = workflows_for_template("booking")
    assert any(w.get("category") == "sales" for w in booking)
    research = workflows_for_template("research")
    assert len(research) >= 4
    # research should not be sales-only dump of the first catalog rows
    assert not all(w.get("category") == "sales" for w in research)
    lead = workflows_for_template("orchestrator", hierarchy_role="orchestrator")
    assert len(lead) == len(presets)


def test_coding_feature_ship_not_stub():
    pr = get_preset("coding_feature_ship")
    assert pr is not None
    assert pr.get("category") == "coding"
    prompt, steps = build_workflow_prompt(pr, niche="webhook retry queue")
    assert "webhook" in prompt.lower() or "feature" in prompt.lower()
    assert len(steps) >= 4
    blob = " ".join(
        f"{s.get('title', '')} {s.get('description', '')} {s.get('done_when', '')}"
        for s in steps
    ).lower()
    assert "write_api_endpoint" in blob
    assert "write_tests" in blob
    assert "code_review" in blob
    assert any(s.get("role_hint") in ("coding", "lead", "orchestrator") for s in steps)


def test_coding_api_scaffold_skills():
    pr = get_preset("coding_api_scaffold")
    _, steps = build_workflow_prompt(pr, niche="billing webhooks v2")
    assert len(steps) >= 4
    blob = " ".join(s.get("description", "") for s in steps).lower()
    assert "write_api_endpoint" in blob
    assert "write_tests" in blob


def test_specialist_default_model_is_quality():
    d = apply_create_defaults(None, "sales", "member")
    assert d["model"] == "quality"
    assert recommended_model("research", "member") == "reasoning"


# ── CRM service path (pipeline · leads · deals) ───────────────────────────

def test_default_stages_include_qualified():
    from app.crm_service import DEFAULT_STAGES

    names = [n for n, *_ in DEFAULT_STAGES]
    assert "Qualified" in names
    assert "Won" in names
    assert "Lost" in names
    assert any(t == "won" for _, t, *_ in DEFAULT_STAGES)
    assert any(t == "lost" for _, t, *_ in DEFAULT_STAGES)


def test_ensure_sales_pipeline_has_qualified(db, user_factory):
    from app import crm_service

    user = user_factory()
    result = crm_service.ensure_sales_pipeline(db, user)
    assert result["ok"] is True
    assert result["has_qualified_stage"] is True
    assert result["has_won_stage"] is True
    assert result["has_lost_stage"] is True
    assert result["stage_count"] >= 5
    names_l = [n.lower() for n in result["stage_names"]]
    assert any("qualif" in n for n in names_l)

    # Idempotent + repairs empty stages
    p = result["pipeline"]
    for s in list(crm_service.list_pipeline_stages(db, p.id)):
        db.delete(s)
    db.commit()
    result2 = crm_service.ensure_sales_pipeline(db, user)
    assert result2["has_qualified_stage"] is True
    assert result2["stage_count"] >= 5


def test_ensure_pipeline_adds_missing_qualified(db, user_factory):
    from app import models, crm_service

    user = user_factory()
    p = models.Pipeline(
        owner_user_id=user.id,
        name="Custom board",
        kind="sales",
        is_default=True,
    )
    db.add(p)
    db.flush()
    db.add(models.PipelineStage(
        pipeline_id=p.id, name="New lead", stage_type="open",
        color="#8c8c8c", position=0, probability=10,
    ))
    db.add(models.PipelineStage(
        pipeline_id=p.id, name="Won", stage_type="won",
        color="#52c41a", position=5, probability=100,
    ))
    db.commit()

    stages, added = crm_service.ensure_pipeline_stages(db, p)
    assert any("qualif" in (s.name or "").lower() for s in stages)
    assert any("Qualified" == a or "qualif" in a.lower() for a in added) or any(
        "qualif" in (s.name or "").lower() for s in stages
    )


def test_list_customers_lead_status_filter(db, user_factory):
    from app import models, crm_service

    user = user_factory()
    for name, ls in (
        ("A Co", "qualified"),
        ("B Co", "new"),
        ("C Co", "qualified"),
        ("D Co", ""),
    ):
        db.add(models.Customer(
            owner_user_id=user.id, name=name, status="active", lead_status=ls,
        ))
    db.commit()

    rows, total = crm_service.list_customers(db, user, lead_status="qualified")
    assert total == 2
    assert all((c.lead_status or "") == "qualified" for c in rows)

    leads, ltotal = crm_service.list_leads(db, user, lead_status="new")
    assert ltotal == 1
    assert leads[0].name == "B Co"

    funnel, ftotal = crm_service.list_leads(db, user, has_lead_status=True, limit=50)
    assert ftotal == 3  # empty lead_status excluded


def test_qualify_set_score_disqualify_service(db, user_factory):
    from app import crm_service

    user = user_factory()
    cust = crm_service.create_customer(
        db, user, name="ICP Fit Inc", email="buyer@icp.example",
        account_name="ICP Fit", notes="inbound demo request",
    )
    out = crm_service.qualify_lead(
        db, user, cust,
        args={"score": 88, "notes": "budget confirmed, decision maker"},
    )
    assert out["ok"] is True
    assert out["lead_status"] == "qualified"
    assert float(out["lead_score"]) == 88
    assert out["grade"] == "A"
    db.refresh(cust)
    assert cust.qualified_at is not None

    cust = crm_service.set_lead_status(
        db, user, cust, lead_status="nurturing", lead_score=55,
    )
    assert cust.lead_status == "nurturing"
    assert float(cust.lead_score) == 55

    # Negative notes reduce score; customer email/account still contribute baseline signals
    score_bad, reasons_bad = crm_service.score_lead_signals(
        {"notes": "no budget, not interested, tire kicker"}, cust,
    )
    score_good, reasons_good = crm_service.score_lead_signals(
        {"notes": "budget confirmed, decision maker, urgent demo"}, cust,
    )
    assert reasons_bad
    assert any("risk" in r.lower() for r in reasons_bad)
    assert score_bad < score_good
    assert score_bad < 70  # not auto-qualified on pure risk notes
    assert score_good >= 70 or any("positive" in r.lower() for r in reasons_good)

    cust = crm_service.disqualify_lead(
        db, user, cust, reason="No budget this year",
    )
    assert cust.lead_status == "disqualified"
    assert "budget" in (cust.disqualified_reason or "").lower()


def test_move_win_lose_deal_service(db, user_factory):
    from app import crm_service

    user = user_factory()
    pipe_info = crm_service.ensure_sales_pipeline(db, user)
    p = pipe_info["pipeline"]
    qualified = next(s for s in pipe_info["stages"] if "qualif" in (s.name or "").lower())

    cust = crm_service.create_customer(db, user, name="Deal Co", email="d@deal.example")
    deal = crm_service.create_deal_for_customer(
        db, user, cust,
        title="Deal Co opportunity",
        value=12000,
        pipeline_id=p.id,
    )
    assert deal.status == "open"

    deal, stage = crm_service.move_deal(
        db, user, deal, stage_name="Qualified",
    )
    assert stage.id == qualified.id
    assert deal.stage_id == qualified.id
    assert deal.status == "open"

    deal = crm_service.win_deal(db, user, deal, value=15000, notes="signed")
    assert deal.status == "won"
    assert float(deal.value) == 15000
    assert deal.closed_at is not None
    won_stage = next(s for s in pipe_info["stages"] if (s.stage_type or "") == "won")
    assert deal.stage_id == won_stage.id

    # Fresh open deal to lose
    deal2 = crm_service.create_deal_for_customer(
        db, user, cust, title="Lost opp", value=500, pipeline_id=p.id,
    )
    deal2 = crm_service.lose_deal(db, user, deal2, lost_reason="chose competitor")
    assert deal2.status == "lost"
    assert "competitor" in (deal2.lost_reason or "").lower()
    assert deal2.closed_at is not None


def test_sales_crm_skill_path_offline(db, agent_factory):
    """Full agent skill path: pipeline → qualify → deal → move → win (no network)."""
    import asyncio
    from app import models, crm_service
    from app.agent_skills import execute_skill, set_enabled_skills, DEFAULT_ENABLED, HANDLER_TABLE

    agent, user = agent_factory()
    skills = [
        "ensure_sales_pipeline", "qualify_lead", "score_lead", "list_leads",
        "set_lead_status", "disqualify_lead", "create_customer", "create_deal",
        "move_deal", "win_deal", "lose_deal",
    ]
    for sid in skills:
        assert sid in HANDLER_TABLE, f"{sid} missing from HANDLER_TABLE"
    set_enabled_skills(db, agent, list(DEFAULT_ENABLED) + skills)

    async def _run():
        pipe = await execute_skill(db, agent, user, "ensure_sales_pipeline", {})
        assert pipe.get("ok") is True
        assert pipe.get("has_qualified_stage") is True
        assert pipe.get("pipeline_id")

        q = await execute_skill(
            db, agent, user, "qualify_lead",
            {
                "lead": "Sales Path Co",
                "email": "path@sales.example",
                "notes": "inbound, budget confirmed, hot lead",
                "score": 92,
            },
        )
        assert q.get("ok") is True
        assert q.get("mode") == "crm_write"
        assert q.get("lead_status") == "qualified"
        cid = q["customer_id"]

        listed = await execute_skill(
            db, agent, user, "list_leads", {"lead_status": "qualified", "limit": 20},
        )
        assert listed.get("ok") is True
        assert listed.get("count", 0) >= 1
        assert any(L.get("id") == cid for L in (listed.get("leads") or []))

        scored = await execute_skill(
            db, agent, user, "score_lead",
            {"customer_id": cid, "context": "still warm", "persist": True},
        )
        assert scored.get("ok") is True
        assert scored.get("grade") in ("A", "B", "C", "D", "F")

        deal_res = await execute_skill(
            db, agent, user, "create_deal",
            {
                "customer_id": cid,
                "title": "Sales Path opp",
                "value": 25000,
                "stage_name": "Qualified",
            },
        )
        assert deal_res.get("ok") is True
        did = deal_res["deal_id"]

        moved = await execute_skill(
            db, agent, user, "move_deal",
            {"deal_id": did, "stage_name": "Proposal"},
        )
        assert moved.get("ok") is True
        assert moved.get("status") == "open"
        assert "proposal" in (moved.get("stage_name") or "").lower()

        won = await execute_skill(
            db, agent, user, "win_deal",
            {"deal_id": did, "value": 26000, "notes": "closed-won"},
        )
        assert won.get("ok") is True
        assert won.get("status") == "won"
        assert won.get("deal_id") == did

        created = await execute_skill(
            db, agent, user, "create_customer",
            {"name": "Tire Kicker LLC", "email": "tk@example.com"},
        )
        assert created.get("ok") is True
        dq = await execute_skill(
            db, agent, user, "disqualify_lead",
            {
                "customer_id": created["customer_id"],
                "reason": "student / no budget",
            },
        )
        assert dq.get("ok") is True
        assert dq.get("lead_status") == "disqualified"

        cust = db.get(models.Customer, dq["customer_id"])
        assert cust is not None
        assert cust.lead_status == "disqualified"
        assert "budget" in (cust.disqualified_reason or "").lower() or "student" in (
            cust.disqualified_reason or ""
        ).lower()

        deal2 = crm_service.create_deal_for_customer(
            db, user, db.get(models.Customer, cid),
            title="Secondary", value=1000,
        )
        lost = await execute_skill(
            db, agent, user, "lose_deal",
            {"deal_id": deal2.id, "lost_reason": "timing"},
        )
        assert lost.get("ok") is True
        assert lost.get("status") == "lost"
        assert lost.get("mode") == "crm_write"

    asyncio.run(_run())


# ── Market-leading multi-agent sales paths ──────────────────────────────────

def test_extract_count_bounds_and_defaults():
    """Count extraction clamps to [5, 100] for chain fan-out safety."""
    # Four-digit numbers fall through regex (\\d{1,3}) → default
    assert _extract_count("get 9999 leads") == 50
    assert _extract_count("pipeline only", default=50) == 50
    assert _extract_count("source 12 prospects for CRM") == 12
    assert _extract_count("get 3 leads") == 5  # clamped to lo
    assert _extract_count("get 200 leads") == 100  # clamped to hi


def test_looks_like_sales_pipeline_edge_cases():
    """Detector fires on ICP/CRM language; ignores non-sales prose."""
    positives = [
        "Find 25 leads and add them to the CRM",
        "Build a prospect list and outreach with cold email",
        "Fill the sales board with 40 targets",
        "Run outreach on open CRM deals",
        "source 12 prospects for CRM",
    ]
    for p in positives:
        assert looks_like_sales_pipeline(p), p
    negatives = [
        "hello world",
        "refactor the backend API",
        "write a blog post about dogs",
        "",
    ]
    for n in negatives:
        assert not looks_like_sales_pipeline(n), n


def test_sales_pipeline_role_hints_and_checklist():
    """Handoff steps use sales → outreach → orchestrator with CRM checklist."""
    steps = decompose_sales_pipeline(
        "Get 50 sales targets, save in CRM, outreach, update pipeline",
        max_steps=6,
    )
    assert len(steps) == 5
    roles = [s.get("role_hint") for s in steps]
    assert "sales" in roles
    assert "outreach" in roles
    assert "orchestrator" in roles
    crm = next(
        s for s in steps
        if "crm" in (s.get("title") or "").lower() or "qualify" in (s.get("title") or "").lower()
    )
    checklist = crm.get("checklist") or []
    assert any("create_customer" in c for c in checklist)
    assert any("create_deal" in c for c in checklist)
    assert any("qualify_lead" in c for c in checklist)
    blob = " ".join(s.get("description", "") for s in steps).lower()
    for skill in (
        "create_customer",
        "create_deal",
        "qualify_lead",
        "draft_email",
        "log_customer_activity",
        "list_qualified_leads",
        "move_deal",
        "pipeline_summary",
        "status_update",
    ):
        assert skill in blob, f"sales pipeline missing skill cue: {skill}"


def test_decompose_sales_respects_max_steps():
    steps = decompose_sales_pipeline("Get 20 sales targets and CRM outreach", max_steps=3)
    assert len(steps) == 3
    titles = " ".join(s["title"].lower() for s in steps)
    assert "target" in titles or "generate" in titles


def test_numbered_user_steps_bypass_sales_playbook():
    """Explicit numbered plans win over auto sales decomposition."""
    prompt = (
        "1) Research competitors\n"
        "2) Draft pricing table\n"
        "3) Send to finance\n"
    )
    steps = decompose_goal(prompt)
    assert len(steps) == 3
    assert "competitor" in steps[0]["title"].lower()
    assert not any(s.get("role_hint") == "outreach" for s in steps)


def test_crm_outreach_only_preset():
    """Existing-CRM outreach preset builds email/call steps without lead gen."""
    pr = get_preset("crm_outreach_only")
    assert pr is not None
    assert pr.get("category") == "sales"
    prompt, steps = build_workflow_prompt(pr, params={"batch": 15})
    assert "15" in prompt or "outreach" in prompt.lower()
    assert len(steps) >= 3
    blob = " ".join(
        f"{s.get('title', '')} {s.get('description', '')}" for s in steps
    ).lower()
    assert "draft_email" in blob or "email" in blob
    assert "pipeline" in blob or "crm" in blob
    assert "generate 15 sales targets" not in blob


def test_sales_pipeline_review_preset():
    """Pipeline review unstick path is buildable and sales-categorised."""
    pr = get_preset("sales_pipeline_review")
    assert pr is not None
    assert pr.get("category") == "sales"
    prompt, steps = build_workflow_prompt(pr, params={"batch": 25})
    assert len(steps) >= 3
    blob = " ".join(s.get("description", "") for s in steps).lower()
    assert "pipeline" in blob
    assert any(
        k in blob for k in ("stall", "stuck", "unstick", "forecast", "deal", "re-engage", "outreach")
    )


def test_sales_preset_steps_preview_matches_qualify_story():
    """UI steps_preview for flagship sales workflow mentions qualify path."""
    pr = get_preset("sales_targets_crm_outreach")
    preview = " ".join(pr.get("steps_preview") or []).lower()
    assert "qualify_lead" in preview  # exact skill name for UI + tests
    assert "customer" in preview or "deal" in preview or "crm" in preview
    assert "outreach" in preview or "qualified" in preview
    # description also tells the qualify story
    desc = (pr.get("description") or "").lower()
    assert "qualify" in desc
    types = set(pr.get("agent_types") or [])
    assert "sales" in types
    assert "outreach" in types
    # built steps still carry qualify_lead skill cues
    _, steps = build_workflow_prompt(pr, count=20)
    blob = " ".join(s.get("description", "") for s in steps).lower()
    assert "qualify_lead" in blob


def test_validate_workflow_params_and_start_errors():
    """start_workflow / validate_workflow_params return clear errors on bad input."""
    from app.workflows import validate_workflow_params, get_preset

    pr = get_preset("sales_targets_crm_outreach")
    assert pr is not None

    ok = validate_workflow_params(pr, count=30, niche="fintech", priority="high")
    assert ok["ok"] is True
    assert ok["count"] == 30
    assert ok["niche"] == "fintech"

    # below min
    bad_lo = validate_workflow_params(pr, count=2)
    assert bad_lo["ok"] is False
    assert "≥" in bad_lo["error"] or "min" in bad_lo["error"].lower() or "2" in bad_lo["error"]

    # above max
    bad_hi = validate_workflow_params(pr, count=500)
    assert bad_hi["ok"] is False
    assert "≤" in bad_hi["error"] or "500" in bad_hi["error"]

    # non-int
    bad_type = validate_workflow_params(pr, count="many")  # type: ignore[arg-type]
    assert bad_type["ok"] is False
    assert "whole number" in bad_type["error"]

    # bad priority
    bad_pri = validate_workflow_params(pr, priority="super-urgent")
    assert bad_pri["ok"] is False
    assert "priority" in bad_pri["error"].lower()

    # params.batch for crm_outreach_only
    crm = get_preset("crm_outreach_only")
    bad_batch = validate_workflow_params(crm, params={"batch": 1})
    assert bad_batch["ok"] is False


def test_research_and_finance_presets():
    """Research/finance high-value presets are buildable and template-mapped."""
    from app.workflows import workflows_for_template

    comp = get_preset("research_competitor_brief")
    assert comp is not None
    assert comp.get("category") == "research"
    prompt, steps = build_workflow_prompt(comp, count=4, niche="UK property SaaS")
    assert len(steps) >= 3
    assert "4" in prompt or "competitor" in prompt.lower()
    blob = " ".join(s.get("description", "") for s in steps).lower()
    assert "research" in blob or "battlecard" in blob

    fin = get_preset("finance_cashflow_forecast")
    assert fin is not None
    assert fin.get("category") == "research"
    prompt2, steps2 = build_workflow_prompt(fin, params={"batch": 20})
    assert len(steps2) >= 3
    blob2 = " ".join(s.get("description", "") for s in steps2).lower()
    assert "pipeline" in blob2 or "forecast" in blob2

    research = workflows_for_template("research")
    ids = [w["id"] for w in research]
    assert "research_competitor_brief" in ids
    finance = workflows_for_template("finance")
    ids_f = [w["id"] for w in finance]
    assert "finance_cashflow_forecast" in ids_f
    # research pack leads with dedicated research/finance presets
    assert ids[0] in ("research_competitor_brief", "finance_cashflow_forecast")


def test_sales_scaffold_models_by_role():
    """Sales members default quality; orchestrator gets a capable default model."""
    sales_member = apply_create_defaults(None, "sales", "member")
    assert sales_member["model"] == "quality"
    assert recommended_model("sales", "member") in ("quality", "vps-fast", "reasoning", "fast")
    orch = apply_create_defaults(None, "orchestrator", "orchestrator")
    assert orch.get("model")


# ── Activity / diary / products (CRM #2) ───────────────────────────────────

def test_log_customer_activity_service(db, user_factory):
    from app import crm_service

    user = user_factory()
    cust = crm_service.create_customer(
        db, user, name="Activity Co", email="act@example.com",
    )
    a = crm_service.log_customer_activity(
        db, user, cust,
        kind="call", title="Discovery call", body="Interested in Pro plan",
    )
    assert a.id
    assert a.customer_id == cust.id
    assert a.kind == "call"
    db.refresh(cust)
    assert cust.last_contacted_at is not None

    acts = crm_service.list_customer_activities(db, user, cust, limit=10)
    assert any(x.id == a.id for x in acts)
    out = crm_service.activity_out(a)
    assert out["title"] == "Discovery call"
    assert out["kind"] == "call"


def test_schedule_and_list_diary_service(db, user_factory):
    from app import crm_service

    user = user_factory()
    cust = crm_service.create_customer(
        db, user, name="Diary Co", email="diary@example.com",
    )
    d = crm_service.schedule_meeting(
        db, user, cust,
        title="Demo call",
        start_at="2030-06-01T15:00:00",
        location="Zoom",
        notes="Show pricing",
    )
    assert d.id
    assert d.customer_id == cust.id
    assert d.status == "scheduled"
    assert d.location == "Zoom"

    rows = crm_service.list_diary(db, user, customer_id=cust.id)
    assert len(rows) >= 1
    assert any(r.id == d.id for r in rows)

    brief = crm_service.diary_out(d, db)
    assert brief["customer_name"] == "Diary Co"
    assert brief["title"] == "Demo call"

    # Activity was logged as meeting
    acts = crm_service.list_customer_activities(db, user, cust, kind="meeting")
    assert any("Demo" in (x.title or "") or "Scheduled" in (x.title or "") for x in acts)


def test_list_qualified_leads_forces_qualified(db, user_factory):
    """list_qualified_leads path never returns non-qualified rows."""
    from app import models, crm_service

    user = user_factory()
    for name, ls in (
        ("Q1", "qualified"),
        ("Q2", "qualified"),
        ("N1", "new"),
        ("D1", "disqualified"),
    ):
        db.add(models.Customer(
            owner_user_id=user.id, name=name, status="active", lead_status=ls,
        ))
    db.commit()

    rows, total = crm_service.list_leads(db, user, lead_status="qualified")
    assert total == 2
    assert all((c.lead_status or "") == "qualified" for c in rows)
    # Conflicting status must not bleed into qualified query when skill forces it
    rows2, _ = crm_service.list_leads(db, user, lead_status="new")
    assert all((c.lead_status or "") == "new" for c in rows2)


def test_list_qualified_leads_skill_offline(db, agent_factory):
    import asyncio
    from app import models
    from app.agent_skills import execute_skill, set_enabled_skills, DEFAULT_ENABLED, HANDLER_TABLE

    assert "list_qualified_leads" in HANDLER_TABLE
    assert "list_leads" in HANDLER_TABLE
    agent, user = agent_factory()
    set_enabled_skills(
        db, agent,
        list(DEFAULT_ENABLED) + ["list_qualified_leads", "list_leads", "create_customer", "set_lead_status"],
    )
    for name, ls in (("Qual A", "qualified"), ("New B", "new")):
        db.add(models.Customer(
            owner_user_id=user.id, name=name, status="active", lead_status=ls,
        ))
    db.commit()

    async def _run():
        # Even if agent passes status=new, skill forces qualified
        out = await execute_skill(
            db, agent, user, "list_qualified_leads",
            {"status": "new", "limit": 50},
        )
        assert out.get("ok") is True
        assert out.get("skill") == "list_qualified_leads"
        assert out.get("lead_status") == "qualified"
        leads = out.get("leads") or []
        assert len(leads) >= 1
        assert all((L.get("lead_status") or "") == "qualified" for L in leads)
        # customers alias present
        assert "customers" in out
        assert len(out["customers"]) == len(leads)

    asyncio.run(_run())


def test_product_catalogue_owner_scoped(db, user_factory):
    from app import models, crm_service
    from fastapi import HTTPException

    owner = user_factory(email="owner-prod@example.com")
    other = user_factory(email="other-prod@example.com")
    co = models.Company(owner_user_id=owner.id, name="Owner Co")
    db.add(co)
    db.commit()
    db.refresh(co)

    p = crm_service.create_product(
        db, owner,
        name="Pro Plan",
        company_id=co.id,
        price=99,
        offer="20% off first month",
        tags="saas,core",
    )
    assert p.owner_user_id == owner.id
    assert p.company_id == co.id

    owned = crm_service.list_products(db, owner)
    assert any(x.id == p.id for x in owned)

    # Other user must not see owner's product
    other_list = crm_service.list_products(db, other)
    assert all(x.id != p.id for x in other_list)

    try:
        crm_service.get_owned_product(db, other, p.id)
        assert False, "expected ownership failure"
    except HTTPException as e:
        assert e.status_code in (403, 404)

    # Other user cannot create without their own company
    try:
        crm_service.create_product(db, other, name="Hijack")
        assert False, "expected missing company error"
    except HTTPException as e:
        assert e.status_code == 400

    # Foreign company_id rejected → falls through to no company for other
    try:
        crm_service.create_product(db, other, name="Steal", company_id=co.id)
        assert False, "expected no company / ownership fail"
    except HTTPException as e:
        assert e.status_code == 400


def test_activity_diary_product_skill_path_offline(db, agent_factory):
    """Skills: log activity → schedule meeting → list diary → create/list products."""
    import asyncio
    from app import models, crm_service
    from app.agent_skills import execute_skill, set_enabled_skills, DEFAULT_ENABLED, HANDLER_TABLE

    skills = [
        "log_customer_activity", "schedule_meeting", "list_diary",
        "create_customer", "list_products", "create_product", "get_product",
        "list_qualified_leads",
    ]
    for sid in skills:
        assert sid in HANDLER_TABLE, f"{sid} missing HANDLER_TABLE"

    agent, user = agent_factory()
    set_enabled_skills(db, agent, list(DEFAULT_ENABLED) + skills)
    co = models.Company(owner_user_id=user.id, name="Skill Co")
    db.add(co)
    db.commit()

    async def _run():
        created = await execute_skill(
            db, agent, user, "create_customer",
            {"name": "Meet Me Inc", "email": "meet@example.com"},
        )
        assert created.get("ok") is True
        cid = created["customer_id"]

        act = await execute_skill(
            db, agent, user, "log_customer_activity",
            {
                "customer_id": cid,
                "kind": "note",
                "title": "Intro",
                "body": "Warm inbound from website",
            },
        )
        assert act.get("ok") is True
        assert act.get("mode") == "crm_write"
        assert act.get("activity_id")
        assert act.get("activity")

        meet = await execute_skill(
            db, agent, user, "schedule_meeting",
            {
                "customer_id": cid,
                "title": "Discovery",
                "start_at": "2030-07-04T10:00:00",
                "location": "Google Meet",
            },
        )
        assert meet.get("ok") is True
        assert meet.get("diary_id")
        assert meet.get("mode") == "crm_write"

        diary = await execute_skill(
            db, agent, user, "list_diary",
            {"customer_id": cid},
        )
        assert diary.get("ok") is True
        assert diary.get("count", 0) >= 1

        prod = await execute_skill(
            db, agent, user, "create_product",
            {
                "name": "Enterprise Suite",
                "price": 499,
                "offer": "Pilot pilot",
                "tags": "enterprise",
            },
        )
        assert prod.get("ok") is True
        assert prod.get("product_id")
        assert prod["product"]["owner_user_id"] if "owner_user_id" in prod.get("product", {}) else True
        # Ownership: product belongs to agent workspace user
        p = db.get(models.Product, prod["product_id"])
        assert p is not None
        assert p.owner_user_id == user.id

        listed = await execute_skill(
            db, agent, user, "list_products", {"q": "Enterprise"},
        )
        assert listed.get("ok") is True
        assert listed.get("count", 0) >= 1
        assert any(x.get("id") == prod["product_id"] for x in (listed.get("products") or []))

        got = await execute_skill(
            db, agent, user, "get_product",
            {"product_id": prod["product_id"]},
        )
        assert got.get("ok") is True
        assert got["product"]["name"] == "Enterprise Suite"

    asyncio.run(_run())
