"""Report fixes: finalize gate, acceptance, review, workflow labels."""
from app.orchestration.acceptance import (
    pack_acceptance,
    unpack_acceptance,
    embed_acceptance,
    extract_acceptance_blob,
    merge_labels,
    evaluate_skill_evidence,
    task_requires_review,
)
from app.orchestration.review import normalize_review_action, can_review
from app.patterns import normalize_checklist


class _T:
    def __init__(self, labels="", description="", acceptance_json="{}"):
        self.labels = labels
        self.description = description
        self.acceptance_json = acceptance_json
        self.agent_id = 2


class _A:
    def __init__(self, **kw):
        self.id = kw.get("id", 1)
        self.parent_id = kw.get("parent_id")
        self.hierarchy_role = kw.get("hierarchy_role", "member")
        self.permission_level = kw.get("permission_level", "operator")
        self.is_lead = kw.get("is_lead", False)
        self.template_type = kw.get("template_type", "sales")
        self.name = kw.get("name", "Agent")


def test_pack_unpack_acceptance():
    blob = pack_acceptance(done_when="50 customers", checklist=["create_customer", "email"], require_review=True)
    data = unpack_acceptance(blob)
    assert data["require_review"] is True
    assert "create_customer" in data["checklist"]
    assert len(data["checks"]) == 2


def test_embed_and_extract():
    desc = embed_acceptance("Do the work", pack_acceptance(checklist=["a", "b"], require_review=True))
    assert "ACCEPTANCE_JSON" in desc or "<!--ACCEPTANCE" in desc
    acc = extract_acceptance_blob(desc)
    assert "a" in acc["checklist"]


def test_merge_labels():
    assert "needs-review" in merge_labels("auto-chain", extra=["needs-review", "auto-chain"])


def test_evaluate_skill_evidence_pass_customer():
    t = _T(
        labels="has-checklist,needs-review",
        acceptance_json=pack_acceptance(checklist=["create_customer in CRM"], require_review=True),
    )
    ev = evaluate_skill_evidence(t, [{"skill": "create_customer", "ok": True}])
    assert ev["verdict"] in ("pass", "review")  # require_review → review
    assert any(c["status"] == "pass" for c in ev["checks"])


def test_evaluate_fail_skill():
    t = _T(
        labels="has-checklist",
        acceptance_json=pack_acceptance(checklist=["send_email to prospect"], require_review=False),
    )
    ev = evaluate_skill_evidence(t, [{"skill": "send_email", "ok": False}])
    assert ev["verdict"] in ("fail", "review")
    assert ev["failed"] or ev["pending"]


def test_task_requires_review():
    t = _T(labels="needs-review")
    assert task_requires_review(t) is True
    t2 = _T(labels="")
    assert task_requires_review(t2) is False


def test_review_action_and_can_review():
    assert normalize_review_action("approve", has_feedback=False) == "approve"
    assert normalize_review_action("reject", has_feedback=False) == "reject"
    assert normalize_review_action(None, has_feedback=True) == "reject"
    lead = _A(hierarchy_role="lead", permission_level="lead", is_lead=True)
    member = _A(id=2, hierarchy_role="member")
    t = _T()
    t.agent_id = 2
    assert can_review(lead, t, member) is True
    # self-review blocked for non-orchestrator
    self_a = _A(id=2, hierarchy_role="member")
    t.agent_id = 2
    assert can_review(self_a, t, self_a) is False


def test_stay_busy_without_complete_task():
    """Agents must not be auto-marked completed without complete_task."""
    import asyncio
    from app.orchestration.finalize import (
        finalize_task_after_run,
        skill_closed_task,
        skill_persisted_data,
    )

    assert skill_closed_task([{"skill": "create_customer", "ok": True}]) is False
    assert skill_closed_task([{"skill": "complete_task", "ok": True}]) is True
    assert skill_persisted_data([{"skill": "create_customer", "ok": True}]) is True
    assert skill_persisted_data([{"skill": "list_tasks", "ok": True}]) is False

    class Task:
        def __init__(self):
            self.id = 9
            self.status = "in_progress"
            self.result = ""
            self.completed_at = None
            self.labels = ""
            self.description = "Save 5 customers to CRM"
            self.acceptance_json = "{}"
            self.agent_id = 1
            self.updated_at = None
            self.title = "CRM"

    agent = _A()

    async def _run():
        t = Task()
        fin = await finalize_task_after_run(
            None,
            t,
            agent=agent,
            output="Here are five target names in prose only.",
            skill_results=[{"skill": "list_tasks", "ok": True}],
            require_close_skill=True,
            more_turns_available=False,
        )
        assert fin["status"] == "in_progress"
        assert t.status == "in_progress"
        assert t.completed_at is None

        t2 = Task()
        t2.status = "completed"
        fin2 = await finalize_task_after_run(
            None,
            t2,
            agent=agent,
            output="Saved customers",
            skill_results=[
                {"skill": "create_customer", "ok": True},
                {"skill": "complete_task", "ok": True},
            ],
            require_close_skill=True,
        )
        assert fin2["status"] == "completed"
        assert fin2.get("persisted") is True

        t3 = Task()
        fin3 = await finalize_task_after_run(
            None,
            t3,
            agent=agent,
            output="mid work",
            skill_results=[{"skill": "create_customer", "ok": True}],
            require_close_skill=True,
            more_turns_available=True,
        )
        assert fin3["status"] == "in_progress"
        assert fin3["reason"] == "continue_working"

    asyncio.run(_run())
