"""skills_policy default packs — offline role sizing (no network)."""
from __future__ import annotations

from app.agent_skills import HANDLER_TABLE, LEAD_FLOW_SKILLS, SKILL_CATALOG
from app.skills_policy import (
    CATEGORY_LABELS,
    CATEGORY_ORDER,
    _CORE_ALWAYS,
    category_for,
    default_enabled_for_role,
    group_skills_by_category,
    is_auto_field_skill,
    is_mega_catalog_skill,
    premium_skill_ids,
    required_app_for_skill,
    role_matches_skill,
    skills_for_pack,
    skills_for_template,
)


def test_default_packs_orchestrator_has_more_than_member():
    """Orchestrator pack is a full enable surface; member stays leaner."""
    member = default_enabled_for_role("member", SKILL_CATALOG)
    specialist = default_enabled_for_role("specialist", SKILL_CATALOG)
    lead = default_enabled_for_role("lead", SKILL_CATALOG)
    orch = default_enabled_for_role("orchestrator", SKILL_CATALOG)

    assert len(member) > 20
    assert len(specialist) == len(member)  # specialist ≡ member defaults
    assert len(lead) > len(member)
    assert len(orch) > len(lead)
    # Orchestrator intentionally includes mega surface
    assert len(orch) > 500


def test_member_defaults_exclude_mega_and_premium_image():
    """Member pack: no mega catalog; premium generate_image stays opt-in; core sales qualify on."""
    member = set(default_enabled_for_role("member", SKILL_CATALOG))
    by_id = {s["id"]: s for s in SKILL_CATALOG}

    mega = [i for i in member if is_mega_catalog_skill(by_id.get(i) or i)]
    assert mega == [], f"mega leaked into member defaults: {mega[:10]}"

    assert "generate_image" not in member  # premium image — opt-in
    assert "qualify_lead" in member  # free CRM scoring — core sales surface
    # Market-leading free CRM + workflow surface always on
    for sid in (
        "move_deal", "win_deal", "lose_deal", "score_lead", "list_leads",
        "set_lead_status", "run_workflow", "create_workflow", "create_task",
    ):
        assert sid in member, f"member defaults missing core skill {sid}"

    orch = set(default_enabled_for_role("orchestrator", SKILL_CATALOG))
    assert "generate_image" in orch
    assert "qualify_lead" in orch
    assert "run_workflow" in orch


def test_lead_excludes_delete_agent_orchestrator_includes():
    lead = set(default_enabled_for_role("lead", SKILL_CATALOG))
    orch = set(default_enabled_for_role("orchestrator", SKILL_CATALOG))
    assert "delete_agent" not in lead
    assert "delete_agent" in orch


def test_orchestrator_pack_matches_role_defaults():
    """skills_for_pack('orchestrator') is a superset-style full surface."""
    via_pack = skills_for_pack("orchestrator", SKILL_CATALOG, role="orchestrator")
    via_role = default_enabled_for_role("orchestrator", SKILL_CATALOG)
    assert len(via_pack) > len(default_enabled_for_role("member", SKILL_CATALOG))
    # Same order-independent membership (both full-catalog style)
    assert set(via_pack) == set(via_role) or len(via_pack) >= len(via_role) * 0.9


def test_handler_table_callables_for_known_skills():
    """qualify_lead / generate_image / run_workflow must be in HANDLER_TABLE with callables."""
    import app.agent_skills as mod

    expected = {
        "generate_image": "_skill_generate_image",
        "qualify_lead": "_skill_qualify_lead",
        "run_workflow": "_skill_run_workflow",
        "move_deal": "_skill_move_deal",
        "win_deal": "_skill_win_deal",
        "lose_deal": "_skill_lose_deal",
    }
    for skill_id, expected_fname in expected.items():
        assert skill_id in HANDLER_TABLE, f"{skill_id} missing from HANDLER_TABLE"
        fname, mode, extras = HANDLER_TABLE[skill_id]
        assert fname == expected_fname
        fn = getattr(mod, fname, None)
        assert callable(fn), f"{skill_id} -> {fname} missing/not callable"
        assert mode in ("std", "extra", "meta", "created", "default")
        assert isinstance(extras, tuple)


def test_skills_for_template_always_attaches_crm_workflow_core():
    """Template packs never drop market-leading CRM + workflow core."""
    for tpl, role in (
        (None, "member"),
        ("sales", "member"),
        ("marketing", "member"),
        ("sales", "lead"),
        ("general", "lead"),
        (None, "orchestrator"),
    ):
        enabled = set(skills_for_template(tpl, SKILL_CATALOG, role=role))
        for sid in (
            "create_customer", "qualify_lead", "create_deal", "move_deal",
            "win_deal", "lose_deal", "create_task", "execute_goal",
            "create_workflow", "run_workflow", "list_tasks",
        ):
            assert sid in enabled, f"{role}/{tpl} missing core {sid}"


def test_lead_flow_skills_cover_pipeline():
    """LEAD_FLOW_SKILLS includes full CRM board + workflows for lead re-attach."""
    for sid in (
        "run_workflow", "move_deal", "win_deal", "lose_deal", "score_lead",
        "list_leads", "set_lead_status", "pipeline_summary", "complete_task",
        "generate_image", "generate_video",
    ):
        assert sid in LEAD_FLOW_SKILLS


def test_core_always_includes_run_workflow_and_pipeline():
    """_CORE_ALWAYS is the non-strippable free work surface."""
    for sid in (
        "run_workflow", "qualify_lead", "move_deal", "win_deal", "lose_deal",
        "score_lead", "list_leads", "set_lead_status", "create_task", "execute_goal",
    ):
        assert sid in _CORE_ALWAYS


# ── Market-leading policy paths ─────────────────────────────────────────────

_CORE_SALES = (
    "qualify_lead",
    "score_lead",
    "list_qualified_leads",
    "create_customer",
    "create_deal",
    "list_customers",
    "list_deals",
    "draft_email",
    "log_customer_activity",
    "move_deal",
    "win_deal",
    "lose_deal",
    "run_workflow",
)


def test_member_and_lead_include_core_sales_surface():
    """Market-ready sales toolkit is on for member + lead (not mega-only)."""
    member = set(default_enabled_for_role("member", SKILL_CATALOG))
    lead = set(default_enabled_for_role("lead", SKILL_CATALOG))
    for sid in _CORE_SALES:
        assert sid in member, f"member defaults missing {sid}"
        assert sid in lead, f"lead defaults missing {sid}"


def test_member_excludes_meta_dangerous():
    """Destructive factory skills stay off for member/specialist defaults."""
    member = set(default_enabled_for_role("member", SKILL_CATALOG))
    specialist = set(default_enabled_for_role("specialist", SKILL_CATALOG))
    for sid in (
        "delete_agent",
        "spawn_team",
        "bulk_enable_skills",
        "promote_to_lead",
        "demote_agent",
        "reparent_agent",
    ):
        assert sid not in member, f"member must not default-enable {sid}"
        assert sid not in specialist, f"specialist must not default-enable {sid}"


def test_role_matches_skill_matrix():
    """specialist inherits member; orchestrator matches all; lead does not match member-only."""
    assert role_matches_skill("orchestrator", ["member"]) is True
    assert role_matches_skill("orchestrator", ["lead"]) is True
    assert role_matches_skill("orchestrator", []) is True
    assert role_matches_skill("specialist", ["member"]) is True
    assert role_matches_skill("specialist", ["specialist"]) is True
    assert role_matches_skill("member", ["member"]) is True
    assert role_matches_skill("member", ["lead"]) is False
    assert role_matches_skill("lead", ["lead"]) is True
    assert role_matches_skill("lead", ["member"]) is False


def test_sales_pack_and_template_include_qualify_lead():
    """skills_for_pack/template('sales') always retain CRM qualify surface."""
    pack_member = set(skills_for_pack("sales", SKILL_CATALOG, role="member"))
    pack_lead = set(skills_for_pack("sales", SKILL_CATALOG, role="lead"))
    tpl_member = set(skills_for_template("sales", SKILL_CATALOG, role="member"))
    tpl_lead = set(skills_for_template("sales", SKILL_CATALOG, role="lead"))

    for surface in (pack_member, pack_lead, tpl_member, tpl_lead):
        assert "qualify_lead" in surface
        assert "create_customer" in surface
        assert "create_deal" in surface
        assert "draft_email" in surface
        assert "move_deal" in surface
        assert "win_deal" in surface
        assert "lose_deal" in surface
        assert "run_workflow" in surface

    # Lead sales template is richer than member (premium + lead ops)
    assert len(tpl_lead) > len(tpl_member)
    # Domain packs stay well under full mega dump
    assert len(pack_member) < 800
    assert len(tpl_lead) < 1200


def test_category_for_market_skills():
    """Category router labels CRM lead skills + comms/media for UI grouping."""
    # Lead qualification lives under CRM in product taxonomy
    assert category_for("qualify_lead") == "crm"
    assert category_for("score_lead") == "crm"
    assert category_for("list_qualified_leads") == "crm"
    assert category_for("list_leads") == "crm"
    assert category_for("set_lead_status") == "crm"
    assert category_for("move_deal") == "crm"
    assert category_for("win_deal") == "crm"
    assert category_for("lose_deal") == "crm"
    assert category_for("create_customer") == "crm"
    assert category_for("create_deal") == "crm"
    assert category_for("draft_email") == "comms"
    assert category_for("generate_image") == "media"
    assert category_for("generate_video") == "media"
    assert category_for("message_agent") == "core"
    assert category_for("run_workflow") == "core"
    assert category_for("spawn_agent") == "meta"


def test_mega_and_auto_field_skills_identified():
    """Mega packs + auto field flood are classified so defaults can exclude them."""
    by_id = {s["id"]: s for s in SKILL_CATALOG}
    # Known mega-style prefix ids from 1000-skill packs
    mega_hits = [s for s in SKILL_CATALOG if is_mega_catalog_skill(s)]
    assert len(mega_hits) > 100, "expected large mega catalog surface"
    # Auto field skills exist and are not in member defaults
    auto_hits = [s for s in SKILL_CATALOG if is_auto_field_skill(s)]
    assert len(auto_hits) > 10
    member = set(default_enabled_for_role("member", SKILL_CATALOG))
    leaked_auto = [i for i in member if is_auto_field_skill(by_id.get(i) or {"id": i})]
    # list_db_fields / gate skills may appear; bulk add_customer_name flood must not
    flood = [i for i in leaked_auto if i.startswith(("add_customer_", "change_customer_", "delete_customer_"))]
    assert flood == [], f"field flood in member defaults: {flood[:10]}"


def test_premium_ids_exclude_free_sales():
    """Premium set includes media; free sales CRM skills are not premium."""
    premium = premium_skill_ids(SKILL_CATALOG)
    assert "generate_image" in premium
    assert "generate_ad_creative" in premium or "edit_image" in premium
    for sid in ("qualify_lead", "create_customer", "create_deal", "score_lead", "draft_email"):
        assert sid not in premium, f"{sid} must stay free (not premium-gated)"


def test_required_app_for_skill_mapping():
    """Integration skills map to catalog app keys; internal CRM does not."""
    assert required_app_for_skill("qualify_lead") is None
    assert required_app_for_skill("create_customer") is None
    assert required_app_for_skill("gmail_send") == "gmail"
    assert required_app_for_skill("slack_post") == "slack"
    assert required_app_for_skill("shopify_list_products") == "shopify"
    # use_app resolves from args
    assert required_app_for_skill("use_app", {"app_id": "hubspot"}) == "hubspot"


def test_group_skills_by_category_structure():
    """Admin/Settings grouping preserves CATEGORY_ORDER and labels."""
    groups = group_skills_by_category(SKILL_CATALOG)
    assert groups
    cats = [g["category"] for g in groups]
    # Relative order matches CATEGORY_ORDER (subset)
    order_idx = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    for a, b in zip(cats, cats[1:]):
        assert order_idx.get(a, 999) <= order_idx.get(b, 999)
    for g in groups:
        assert g["label"] == CATEGORY_LABELS.get(g["category"], g["category"])
        assert g["count"] == len(g["skills"])
        assert g["count"] > 0


def test_lead_pack_includes_spawn_not_delete():
    """Lead pack can spawn/configure team but still cannot delete agents by default."""
    lead_pack = set(skills_for_pack("lead", SKILL_CATALOG, role="lead"))
    lead_role = set(default_enabled_for_role("lead", SKILL_CATALOG))
    for surface in (lead_pack, lead_role):
        assert "spawn_agent" in surface or "hire_agent" in surface
        assert "delete_agent" not in surface
