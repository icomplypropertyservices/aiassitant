"""Unit-level fail-smart / invent-cap helpers (no full async runner)."""
from __future__ import annotations

from types import SimpleNamespace

from app.autonomy import (
    _is_terminal_provider_task,
    _is_self_run_labels,
    _is_claimable_board_task,
    _invent_self_run_spec,
    _self_run_soft_skip_state,
    _wallet_hard_blocked,
    _claim_unassigned_board_task,
    _attach_cycle_health,
)
from app.llm import is_terminal_llm_failure, classify_terminal_llm_failure


def _task(**kwargs):
    return SimpleNamespace(
        id=kwargs.get("id", 1),
        user_id=kwargs.get("user_id", 1),
        agent_id=kwargs.get("agent_id"),
        status=kwargs.get("status", "todo"),
        labels=kwargs.get("labels", ""),
        result=kwargs.get("result", ""),
        title=kwargs.get("title", "T"),
        description=kwargs.get("description", ""),
        completed_at=kwargs.get("completed_at"),
        updated_at=kwargs.get("updated_at"),
        assignee_type=kwargs.get("assignee_type"),
    )


def test_terminal_provider_labels_and_results():
    assert _is_terminal_provider_task(_task(labels="foo,credits_exhausted"))
    assert _is_terminal_provider_task(_task(labels="spending_limit"))
    assert _is_terminal_provider_task(_task(labels="", result="[CREDITS_EXHAUSTED] empty"))
    assert _is_terminal_provider_task(_task(result="xAI spending limit reached"))
    assert _is_terminal_provider_task(_task(result="permission-denied from provider"))
    assert not _is_terminal_provider_task(_task(labels="auto-chain,step", result="saved 3 customers"))


def test_llm_classify_fail_smart():
    assert is_terminal_llm_failure("xAI HTTP 403: nope")
    assert classify_terminal_llm_failure("spending limit exceeded") == "spending_limit"
    assert classify_terminal_llm_failure("[CREDITS_EXHAUSTED] x") == "credits"
    assert classify_terminal_llm_failure("permission denied / 403") == "permission_denied"
    assert not is_terminal_llm_failure("CRM pulse complete with 2 updates")


def test_self_run_labels():
    assert _is_self_run_labels("autonomy,self-run,self-assigned")
    assert _is_self_run_labels("autonomy,self-assigned")  # invent fluff
    assert not _is_self_run_labels("auto-chain,step,1")
    assert not _is_self_run_labels("goal,auto-chain,monitor")


def test_claimable_board_skips_chain_wait_and_terminal():
    assert _is_claimable_board_task(
        _task(agent_id=None, status="todo", labels="skill-created")
    )
    assert not _is_claimable_board_task(
        _task(agent_id=None, status="todo", labels="auto-chain,step,2")
    )
    assert not _is_claimable_board_task(
        _task(agent_id=None, status="todo", labels="llm_unavailable")
    )
    assert not _is_claimable_board_task(
        _task(agent_id=5, status="todo", labels="")
    )
    assert not _is_claimable_board_task(
        _task(agent_id=None, status="completed", labels="")
    )


def test_invent_spec_crm_for_sales():
    agent = SimpleNamespace(
        name="Sales Lead",
        template_type="sales",
        hierarchy_role="lead",
    )
    title, desc, labels = _invent_self_run_spec(agent, role="lead")
    assert "CRM" in title or "crm" in labels
    assert "complete_task" in desc
    assert "self-run" in labels
    assert "send_email" in desc or "Do NOT" in desc  # guardrails present


def test_invent_spec_workflow_for_orchestrator():
    agent = SimpleNamespace(
        name="Main Orchestrator",
        template_type="orchestrator",
        hierarchy_role="orchestrator",
    )
    title, desc, labels = _invent_self_run_spec(agent, role="orchestrator")
    assert "workflow" in labels or "Workflow" in title
    assert "complete_task" in desc


def test_wallet_hard_blocked_admin_never(db, user_factory):
    admin = user_factory(email="admin@example.com", role="admin")
    assert _wallet_hard_blocked(db, admin) is False


def test_self_run_soft_skip_open_cap_without_meter(db, user_factory):
    """open_self_run_cap alone is enough to skip invent (no meter needed)."""
    u = user_factory(email="cap@example.com", role="user")
    state = _self_run_soft_skip_state(db, u, open_self_runs=2, max_feeds=1)
    assert state["skip_invent"] is True
    assert "open_self_run_cap" in state["reasons"]
    assert state["primary"] == "open_self_run_cap"
    # Cap alone does not soft-skip real queue board work
    assert state["skip_queue_self_run"] is False


def test_self_run_soft_skip_wallet_primary(db, user_factory, monkeypatch):
    u = user_factory(email="broke@example.com", role="user")

    def _fake_meter(db_sess, user):
        return {"hard_block": True}

    monkeypatch.setattr("app.usage_billing.meter_snapshot", _fake_meter)
    # Also force no llm dominate
    monkeypatch.setattr(
        "app.autonomy._recent_llm_failures_dominate",
        lambda *a, **k: False,
    )
    state = _self_run_soft_skip_state(db, u, open_self_runs=0, max_feeds=2)
    assert state["wallet_hard_block"] is True
    assert state["skip_invent"] is True
    assert state["skip_queue_self_run"] is True
    assert state["primary"] == "credits_hard_block"
    assert "credits_hard_block" in state["reasons"]


def test_claim_prefers_board_skips_terminal(db, user_factory, agent_factory):
    u = user_factory(email="claim@example.com")
    agent, _owner = agent_factory(user=u, name="Claimer", template_type="sales")
    from app import models

    # Terminal unassigned first — must not claim, must not block next
    bad = models.Task(
        user_id=u.id,
        agent_id=None,
        title="Dead LLM",
        description="x",
        status="todo",
        labels="llm_unavailable",
        result="[CREDITS_EXHAUSTED] empty",
        assignee_type=None,
    )
    good = models.Task(
        user_id=u.id,
        agent_id=None,
        title="Real board work",
        description="Do CRM update",
        status="todo",
        labels="skill-created",
        result="",
        assignee_type=None,
    )
    db.add_all([bad, good])
    db.commit()

    claimed = _claim_unassigned_board_task(db, u, agent)
    assert claimed is not None
    assert claimed.id == good.id
    assert claimed.agent_id == agent.id
    assert claimed.status == "queued"
    db.refresh(bad)
    assert bad.status == "failed"


def test_attach_cycle_health_fields(db, user_factory):
    u = user_factory(email="health@example.com")
    summary = {
        "user_id": u.id,
        "tasks_started": 1,
        "escalated": 0,
        "board_claimed": 1,
        "self_runs_created": 0,
        "self_run_skipped": "credits_hard_block",
        "soft_skip_reasons": ["credits_hard_block"],
        "wallet_hard_block": True,
        "stalled_terminal_failed": 2,
    }
    out = _attach_cycle_health(db, u, summary)
    h = out["health"]
    assert h["wallet_hard_block"] is True
    assert "credits_hard_block" in h["soft_skip_reasons"]
    assert h["board_claimed"] == 1
    assert h["prefer_board"] is True
    assert h["stalled_terminal_failed"] == 2
    assert "unassigned_open" in h
