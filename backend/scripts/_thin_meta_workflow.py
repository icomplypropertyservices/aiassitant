"""One-shot: replace bloated workflow/review skill bodies with orchestration wrappers."""
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "app" / "skills" / "meta_agents.py"
text = p.read_text(encoding="utf-8")
start = text.index("async def _skill_create_workflow")
end = text.index("async def _skill_announce_plan")
replacement = r'''async def _skill_create_workflow(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Lead/orchestrator multi-step workflow — canonical path in orchestration.workflow_run."""
    from ..orchestration.workflow_run import start_workflow
    from ..patterns import normalize_checklist

    title = (args.get("title") or args.get("name") or args.get("goal") or "Workflow")[:160]
    steps_in = args.get("steps") or args.get("tasks") or []
    if isinstance(steps_in, str):
        steps_in = [s.strip() for s in steps_in.split("\n") if s.strip()]
    if not isinstance(steps_in, list) or not steps_in:
        return {
            "ok": False,
            "error": "steps required — list of {title, description, agent_id|role, checklist, done_when}",
        }
    save_pat = args.get("save_as_pattern") or args.get("save_pattern")
    if isinstance(save_pat, str):
        save_pat = save_pat.strip().lower() in ("1", "true", "yes", "on")
    return await start_workflow(
        db,
        user,
        agent,
        title=title,
        description=str(args.get("description") or args.get("goal") or title),
        steps=steps_in,
        checklist=normalize_checklist(
            args.get("checklist") or args.get("checks") or args.get("must_check")
        ),
        priority=str(args.get("priority") or "high"),
        company_id=args.get("company_id") or agent.company_id,
        project_id=args.get("project_id") or agent.project_id,
        require_review=True,
        save_as_pattern=bool(save_pat) or bool(args.get("pattern_name")),
        pattern_name=str(args.get("pattern_name") or ""),
        category=str(args.get("category") or "custom"),
    )


async def _skill_run_pattern(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Instantiate a saved pattern as a live multi-agent workflow."""
    from ..orchestration.workflow_run import run_pattern

    pid = args.get("pattern_id") or args.get("id") or args.get("name") or args.get("slug")
    if pid in (None, ""):
        return {"ok": False, "error": "pattern_id or name required"}
    return await run_pattern(
        db,
        user,
        agent,
        pid,
        title=str(args.get("title") or ""),
        priority=str(args.get("priority") or "high"),
        company_id=args.get("company_id"),
        project_id=args.get("project_id"),
    )


async def _skill_review_task(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Lead review / reject — canonical path in orchestration.review."""
    from ..orchestration.review import review_task as do_review

    try:
        tid = int(args.get("task_id") or args.get("id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "task_id required"}
    feedback = str(
        args.get("feedback")
        or args.get("whats_wrong")
        or args.get("reason")
        or args.get("message")
        or args.get("details")
        or ""
    ).strip()
    return await do_review(
        db,
        agent,
        user,
        task_id=tid,
        action=args.get("action") or args.get("verdict") or args.get("decision"),
        feedback=feedback,
        checks_failed=(
            args.get("checks_failed")
            or args.get("failed_checks")
            or args.get("checklist_failed")
            or args.get("missing")
        ),
        message_fn=_skill_message,
    )


'''
p.write_text(text[:start] + replacement + text[end:], encoding="utf-8")
print("ok lines", len(p.read_text(encoding="utf-8").splitlines()))
