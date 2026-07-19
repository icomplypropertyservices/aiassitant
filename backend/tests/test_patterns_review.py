"""Patterns, checklists, and lead review helpers."""
from app.patterns import (
    normalize_checklist,
    format_checklist_block,
    format_feedback_block,
    pattern_payload,
    save_pattern,
    list_patterns,
    get_pattern,
)
from app.skills.meta_agents import _compose_task_brief


def test_normalize_checklist():
    assert normalize_checklist(["a", "b"]) == ["a", "b"]
    assert "email" in " ".join(normalize_checklist("has email\nhas company")).lower()
    assert len(normalize_checklist("one, two, three")) == 3


def test_format_checklist_and_feedback():
    block = format_checklist_block(["50 targets", "CRM saved"])
    assert "[ ] 50 targets" in block
    fb = format_feedback_block("Missing phones", checks_failed=["phone present"], reviewer="Sales Lead")
    assert "WHAT'S WRONG" in fb
    assert "phone present" in fb
    assert "Sales Lead" in fb


def test_compose_brief_includes_checklist():
    brief = _compose_task_brief(
        "Do outreach",
        title="Emails",
        success_criteria="10 emails sent",
        checklist=["personalized", "logged in CRM"],
        owner_name="Sales Lead",
    )
    assert "DONE WHEN" in brief
    assert "personalized" in brief
    assert "CHECKLIST" in brief.upper() or "[ ]" in brief


def test_pattern_payload_steps():
    p = pattern_payload(
        name="Sales batch",
        description="Targets then CRM",
        steps=[
            {"title": "Gen targets", "role": "sales", "checklist": ["n names"]},
            {"title": "Outreach", "role_hint": "outreach", "done_when": "emails sent"},
        ],
        checklist=["human notified"],
        category="sales",
    )
    assert p["slug"] == "sales-batch"
    assert len(p["steps"]) == 2
    assert p["steps"][0]["checklist"] == ["n names"]
    assert p["checklist"] == ["human notified"]
