"""Sales multi-agent workflow presets and goal decomposition."""
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


def test_workflow_preset_build():
    presets = list_workflow_presets()
    assert any(p["id"] == "sales_targets_crm_outreach" for p in presets)
    pr = get_preset("sales_targets_crm_outreach")
    prompt, steps = build_workflow_prompt(pr, count=30, niche="fintech")
    assert "30" in prompt
    assert "fintech" in prompt.lower() or "niche" in prompt.lower() or "ICP" in prompt or "fintech" in prompt
    assert len(steps) >= 4


def test_specialist_default_model_is_quality():
    d = apply_create_defaults(None, "sales", "member")
    assert d["model"] == "quality"
    assert recommended_model("research", "member") == "reasoning"
