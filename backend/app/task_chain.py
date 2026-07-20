"""
Automatic goal → task → delegate → monitor → complete chain.

From one human prompt (chat or skill):
  1. Create parent goal task on orchestrator/lead
  2. Break into concrete subtasks
  3. Assign down the hierarchy (orchestrator → leads → specialists)
  4. Set company/project targets from the agent's scope
  5. Queue active agents so autonomy ticks execute them
  6. On child complete/fail: roll up parent, emit ops, re-queue blockers

Used by chat, skills (execute_goal / create_task / announce_plan), and task_runner.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .agent_roles import find_orchestrator, is_lead_agent, is_orchestrator

log = logging.getLogger("app.task_chain")

# Heuristic: long / action-oriented messages become full goal chains
_GOAL_HINTS = re.compile(
    r"\b(build|create|launch|plan|run|execute|delegate|organise|organize|"
    r"set up|setup|ship|deliver|campaign|hire|research|analyse|analyze|"
    r"implement|fix|grow|scale|automate|coordinate|manage|finish|"
    r"complete|do this|get this done|make sure|ensure)\b",
    re.I,
)


def looks_like_goal(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 24:
        return False
    if len(t) >= 80:
        return True
    return bool(_GOAL_HINTS.search(t))


def _active_team(db: Session, user_id: int) -> list[models.Agent]:
    return (
        db.query(models.Agent)
        .filter_by(user_id=user_id, status="active")
        .order_by(models.Agent.id)
        .all()
    )


def _reports(db: Session, parent: models.Agent) -> list[models.Agent]:
    return (
        db.query(models.Agent)
        .filter_by(user_id=parent.user_id, parent_id=parent.id, status="active")
        .order_by(models.Agent.id)
        .all()
    )


def pick_assignee(
    db: Session,
    user: models.User,
    *,
    owner: models.Agent,
    step_index: int,
    step_text: str,
    preferred_agent_id: int | None = None,
    preferred_role: str | None = None,
) -> models.Agent:
    """Choose best agent for a step: explicit id → role match → hierarchy round-robin → owner."""
    team = _active_team(db, user.id)
    by_id = {a.id: a for a in team}

    if preferred_agent_id and preferred_agent_id in by_id:
        return by_id[preferred_agent_id]

    role = (preferred_role or "").strip().lower()
    if role:
        for a in team:
            if (a.hierarchy_role or "").lower() == role:
                return a
            if (a.template_type or "").lower() == role:
                return a
            if role in (a.name or "").lower():
                return a

    text = (step_text or "").lower()
    # Prefer outreach member for email/call steps; sales lead for CRM / targets
    if any(k in text for k in ("email", "call", "sms", "outreach", "dial", "follow-up", "follow up")):
        for a in team:
            name_l = (a.name or "").lower()
            tpl = (a.template_type or "").lower()
            if "outreach" in name_l or tpl == "outreach" or (
                tpl == "sales" and (a.hierarchy_role or "") == "member"
            ):
                return a
    if any(k in text for k in ("crm", "customer", "target", "prospect", "pipeline", "deal", "lead gen")):
        for a in team:
            tpl = (a.template_type or "").lower()
            name_l = (a.name or "").lower()
            if tpl in ("sales", "crm", "lead_gen") and (
                (a.hierarchy_role or "") == "lead" or "lead" in name_l
            ):
                return a
        for a in team:
            if (a.template_type or "").lower() in ("sales", "crm", "lead_gen"):
                return a

    keyword_map = (
        ("sales", ("sales", "outreach", "lead_gen", "crm")),
        ("marketing", ("marketing", "content", "seo", "social")),
        ("support", ("support", "customer", "helpdesk")),
        ("coding", ("coding", "developer", "engineer", "qa")),
        ("finance", ("finance", "bookkeep", "accounting")),
        ("research", ("research", "analyst", "data")),
        ("design", ("design", "designer", "ux", "ui")),
        ("ops", ("ops", "operations", "fleet")),
    )
    for key, tpls in keyword_map:
        if key in text:
            for a in team:
                if (a.template_type or "").lower() in tpls:
                    return a

    # Hierarchy: prefer direct reports of owner, then any lead, then team round-robin
    kids = _reports(db, owner)
    if kids:
        return kids[step_index % len(kids)]

    leads = [a for a in team if is_lead_agent(a) or (a.hierarchy_role or "") == "lead"]
    leads = [a for a in leads if a.id != owner.id]
    if leads:
        return leads[step_index % len(leads)]

    others = [a for a in team if a.id != owner.id and not is_orchestrator(a)]
    if others:
        return others[step_index % len(others)]

    return owner


def _extract_count(text: str, default: int = 50, lo: int = 5, hi: int = 100) -> int:
    """Pull a target count like '50 sales targets' from free text."""
    m = re.search(
        r"\b(\d{1,3})\s*(?:sales?\s*)?(?:targets?|leads?|prospects?|contacts?|customers?)\b",
        text or "",
        re.I,
    )
    if not m:
        m = re.search(r"\b(\d{1,3})\b", text or "")
    if not m:
        return default
    try:
        n = int(m.group(1))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def looks_like_sales_pipeline(prompt: str) -> bool:
    """True when the goal is generate leads/targets → CRM → outreach/pipeline."""
    t = (prompt or "").lower()
    salesish = any(
        k in t
        for k in (
            "sales target", "sales targets", "lead", "leads", "prospect",
            "crm", "pipeline", "outreach", "cold email", "cold call",
            "book demo", "qualify", "sales board",
        )
    )
    action = any(
        k in t
        for k in (
            "get", "find", "generate", "build", "create", "save", "add",
            "email", "call", "send", "update", "run", "fill", "source",
            "prospect", "outreach",
        )
    )
    return salesish and (action or _extract_count(t, default=0, lo=0, hi=999) > 0)


def decompose_sales_pipeline(prompt: str, *, max_steps: int = 6) -> list[dict[str, Any]]:
    """
    Multi-agent sales handoff:
      1) Sales lead — generate N targets
      2) Sales lead — save customers + deals in CRM + qualify_lead
      3) Outreach — emails / calls / log activity (prefer qualified)
      4) Sales — move pipeline stages + re-qualify
      5) Lead/orchestrator — rollup + notify human
    """
    n = _extract_count(prompt, default=50)
    short = (prompt or "").strip()[:220]
    steps: list[dict[str, Any]] = [
        {
            "title": f"Generate {n} sales targets",
            "description": (
                f"GOAL CONTEXT: {short}\n\n"
                f"You are the sales research / lead gen agent.\n"
                f"Produce a list of exactly {n} sales targets (ICP-fit companies or contacts).\n"
                f"For EACH target include: full name, company, role/title, email (realistic placeholder "
                f"if unknown), phone if known, niche/notes, priority (high/med/low), and a rough "
                f"ICP fit note (budget/timeline/authority signals if known).\n"
                f"Write the full list in your reply (table or numbered).\n"
                f"Save a compact summary with save_memory key=sales_targets_batch.\n"
                f"Do NOT email yet — next agent will CRM-import and qualify_lead, then outreach.\n\n"
                f"DONE WHEN: {n} named targets with company + contact details in the task result.\n"
                f"TARGET: {n} sales targets ready for CRM import + qualify_lead."
            ),
            "role_hint": "sales",
            "done_when": f"{n} sales targets listed with company and contact details",
        },
        {
            "title": f"Save {n} targets into CRM + qualify",
            "description": (
                f"GOAL CONTEXT: {short}\n\n"
                f"You own the CRM step. Read parent goal / prior step results (list_tasks, get_task, "
                f"list_activity, list_customers).\n"
                f"For each sales target from step 1, call create_customer "
                f'(name, email, phone, tags=["sales-target","auto-chain"], notes).\n'
                f"Then create_deal for each new customer (title like '{{Company}} — outreach', "
                f"priority from target, value if known).\n"
                f"Then call qualify_lead for each new customer (customer_id or email; notes with ICP "
                f"signals; score 0–100; lead_status e.g. new/nurturing/qualified). "
                f"Use score_lead if you only need a score pass. Real skill blocks required — "
                f"prose alone is NOT enough.\n"
                f"Batch: aim for all {n} (or as many as listed). Use list_pipelines / get_pipeline "
                f"if you need stage ids.\n"
                f"Emit one ```skill block per create_customer, create_deal, and qualify_lead.\n\n"
                f"DONE WHEN: ≥{max(1, n // 2)} customers created in CRM with open deals and "
                f"qualify_lead (or score_lead) run on them (ideally all {n}).\n"
                f"TARGET: CRM populated; deals on sales pipeline; lead_score/lead_status set."
            ),
            "role_hint": "sales",
            "done_when": (
                f"At least half of {n} targets saved as CRM customers with deals and qualify_lead"
            ),
            "checklist": [
                "create_customer used for targets",
                "create_deal used for targets",
                "qualify_lead (or score_lead) used on new customers",
            ],
        },
        {
            "title": "Outreach: emails and calls",
            "description": (
                f"GOAL CONTEXT: {short}\n\n"
                f"You are the outreach specialist. Pull fresh CRM rows: list_customers, list_deals, "
                f"get_pipeline, list_qualified_leads (and list_leads if needed).\n"
                f"Prioritise customers with higher lead_score / lead_status=qualified from "
                f"qualify_lead; still cover other sales-target tags if capacity remains.\n"
                f"For each target customer:\n"
                f"  1) draft_email personalized pitch\n"
                f"  2) send_email when credentials allow (else leave draft + log)\n"
                f"  3) log_customer_activity (email/call note)\n"
                f"  4) If phone present, prepare call script; use call skill if available\n"
                f"  5) Optionally set_lead_status to contacted after a real touch\n"
                f"Do real skill calls — do not only describe outreach.\n"
                f"Cover as many CRM targets as practical this run (batch ≥10 or all open).\n\n"
                f"DONE WHEN: Outreach attempted for a clear batch of CRM targets with activity logs.\n"
                f"TARGET: Emails/calls logged on customers; human can see activity in Business CRM."
            ),
            "role_hint": "outreach",
            "done_when": "Outreach emails/calls logged on CRM customers",
        },
        {
            "title": "Update sales pipeline stages",
            "description": (
                f"GOAL CONTEXT: {short}\n\n"
                f"Update the board after outreach: list_pipelines, get_pipeline, list_deals, "
                f"list_qualified_leads.\n"
                f"move_deal / update_deal for contacts contacted → next stage "
                f"(e.g. Contacted / Qualified).\n"
                f"Re-run qualify_lead (or set_lead_status) when a lead shows real interest — "
                f"raise score / set lead_status=qualified with notes.\n"
                f"win_deal / lose_deal only with evidence; disqualify_lead only when clearly unfit.\n"
                f"pipeline_summary at the end.\n\n"
                f"DONE WHEN: Pipeline reflects outreach progress; qualified leads updated; "
                f"summary in task result.\n"
                f"TARGET: Deals moved; qualify_lead/list_qualified_leads consistent with board."
            ),
            "role_hint": "sales",
            "done_when": "Pipeline stages updated after outreach; leads re-qualified where earned",
        },
        {
            "title": "Report results to human",
            "description": (
                f"GOAL CONTEXT: {short}\n\n"
                f"Roll up: how many targets generated, CRM customers/deals created, "
                f"qualify_lead counts (qualified vs nurturing), emails/calls, pipeline value. "
                f"Use list_customers, list_qualified_leads, pipeline_summary, list_activity.\n"
                f"status_update or notify_human with a short owner brief.\n"
                f"save_memory key=sales_pipeline_run_summary.\n\n"
                f"DONE WHEN: Human notified with counts (incl. qualified leads) and next actions.\n"
                f"TARGET: Clear status_update delivered."
            ),
            "role_hint": "orchestrator",
            "done_when": "Human has status update with CRM, qualify_lead, and outreach counts",
        },
    ]
    return steps[:max_steps]


def decompose_goal(prompt: str, *, max_steps: int = 6) -> list[dict[str, Any]]:
    """
    Deterministic step breakdown without an extra LLM call.
    Prefer numbered lines from the human; else sales playbook; else synthesize.
    """
    text = (prompt or "").strip()
    steps: list[dict[str, Any]] = []

    # Numbered or bulleted lines from the user
    for line in text.splitlines():
        m = re.match(r"^\s*(?:\d+[.)]\s+|[-*•]\s+)(.+)$", line)
        if m:
            body = m.group(1).strip()
            if len(body) >= 4:
                steps.append({"title": body[:120], "description": body})

    if steps:
        return steps[:max_steps]

    # Multi-agent sales: targets → CRM → emails/calls → pipeline
    if looks_like_sales_pipeline(text):
        return decompose_sales_pipeline(text, max_steps=max_steps)

    # Sentence split for long prose
    chunks = re.split(r"(?<=[.!?])\s+|\n+", text)
    chunks = [c.strip() for c in chunks if len(c.strip()) >= 12]
    if len(chunks) >= 2:
        for c in chunks[:max_steps]:
            steps.append({"title": c[:120], "description": c})
        return steps

    # Synthesized chain: each step has a measurable DONE WHEN target
    short = text[:200]
    template = [
        {
            "title": "Clarify goal & success criteria",
            "description": (
                f"Restate the goal, constraints, and owner.\n"
                f"DONE WHEN: Written success criteria + 3 measurable targets for: {short}\n"
                f"TARGET: Criteria saved via save_memory or parent task note."
            ),
            "role_hint": "orchestrator",
            "done_when": "Success criteria and 3 measurable targets written",
        },
        {
            "title": "Set company/project targets",
            "description": (
                f"Attach work to the right company/project and timeline.\n"
                f"DONE WHEN: Company/project chosen and target metrics named for: {short}\n"
                f"TARGET: Scope note on the goal task."
            ),
            "role_hint": "lead",
            "done_when": "Scope and metrics attached to goal",
        },
        {
            "title": "Break work into owned workstreams",
            "description": (
                f"Create concrete subtasks with assignees for: {short}\n"
                f"DONE WHEN: At least 2 create_task or message_agent assignments with done_when each.\n"
                f"TARGET: Board shows child work under this goal."
            ),
            "role_hint": "lead",
            "done_when": "≥2 owned child tasks with acceptance criteria",
        },
        {
            "title": "Execute primary deliverable",
            "description": (
                f"Produce the main output for: {short}\n"
                f"DONE WHEN: Full deliverable text (draft/plan/email/analysis) is in the task result.\n"
                f"TARGET: Deliverable ready for human review."
            ),
            "role_hint": "specialist",
            "done_when": "Primary deliverable in task result",
        },
        {
            "title": "QA / review & pack result",
            "description": (
                f"Review outputs, fix gaps, summarize for the human owner.\n"
                f"DONE WHEN: Short QA checklist + final summary vs goal: {short}\n"
                f"TARGET: Human-ready summary via status_update or notify_human if possible."
            ),
            "role_hint": "orchestrator",
            "done_when": "QA summary and human-facing pack complete",
        },
        {
            "title": "Close loop & escalate only if blocked",
            "description": (
                f"Confirm all sibling steps done; re-queue stuck work once if needed.\n"
                f"DONE WHEN: Open chain steps = 0 or blockers escalated with reason.\n"
                f"TARGET: Parent goal can roll up. Goal: {short}"
            ),
            "role_hint": "orchestrator",
            "done_when": "Chain clear or blockers escalated",
        },
    ]
    return template[:max_steps]


async def start_goal_chain(
    db: Session,
    user: models.User,
    owner: models.Agent,
    prompt: str,
    *,
    title: str | None = None,
    company_id: int | None = None,
    project_id: int | None = None,
    priority: str = "high",
    steps: list[dict[str, Any]] | list[str] | None = None,
    max_steps: int = 6,
    auto_queue: bool = True,
    child_label_prefix: str = "",
    require_review_default: bool = False,
) -> dict[str, Any]:
    """
    Full automatic chain from one prompt.
    Returns parent task id, child ids, assignments.

    Steps may include: labels, acceptance_json, require_review, checklist, done_when.
    Labels/acceptance are applied atomically at create (no post-hoc patch).
    """
    prompt = (prompt or "").strip()
    if not prompt:
        return {"ok": False, "error": "empty prompt"}

    # Prefer orchestrator as chain owner when caller is a leaf
    chain_owner = owner
    if not is_orchestrator(owner) and not is_lead_agent(owner):
        orch = find_orchestrator(db, user.id)
        if orch:
            chain_owner = orch

    company_id = company_id or chain_owner.company_id
    project_id = project_id or chain_owner.project_id
    if company_id is None:
        co = (
            db.query(models.Company)
            .filter_by(owner_user_id=user.id)
            .order_by(models.Company.id)
            .first()
        )
        if co:
            company_id = co.id

    goal_title = (title or prompt.split("\n")[0] or "Goal")[:160]
    parent_status = "in_progress"  # parent monitors while children run

    parent = models.Task(
        user_id=user.id,
        agent_id=chain_owner.id,
        company_id=company_id,
        project_id=project_id,
        title=f"Goal: {goal_title}"[:200],
        description=prompt[:8000],
        status=parent_status,
        priority=priority or "high",
        labels="goal,auto-chain,monitor",
        assignee_type="agent",
    )
    db.add(parent)
    db.flush()

    raw_steps = steps if steps is not None else decompose_goal(prompt, max_steps=max_steps)
    normalized: list[dict[str, Any]] = []
    for s in raw_steps:
        if isinstance(s, str):
            normalized.append({"title": s[:120], "description": s})
        elif isinstance(s, dict):
            normalized.append(s)
    if not normalized:
        normalized = decompose_goal(prompt, max_steps=max_steps)

    children: list[dict[str, Any]] = []
    first_queued_id: int | None = None
    for i, step in enumerate(normalized[:max_steps]):
        stitle = (step.get("title") or step.get("description") or f"Step {i + 1}")[:120]
        sdesc = (step.get("description") or stitle)[:4000]
        done_when = (
            step.get("done_when")
            or step.get("success_criteria")
            or step.get("target")
            or f"Complete step: {stitle}"
        )
        pref_id = step.get("agent_id")
        try:
            pref_id = int(pref_id) if pref_id is not None and pref_id != "" else None
        except (TypeError, ValueError):
            pref_id = None
        assignee = pick_assignee(
            db,
            user,
            owner=chain_owner,
            step_index=i,
            step_text=f"{stitle} {sdesc}",
            preferred_agent_id=pref_id,
            preferred_role=step.get("role_hint") or step.get("role") or step.get("template_type"),
        )
        # Sequential chain: only the first step is queued immediately.
        # Later steps stay todo until on_task_finished promotes the next sibling.
        if auto_queue and i == 0 and getattr(assignee, "status", None) == "active":
            status = "queued"
        else:
            status = "todo"

        # Atomic labels: step defaults + optional step.labels / require_review
        from .orchestration.acceptance import merge_labels
        step_labels = step.get("labels") or ""
        extra = [f"step", str(i + 1)]
        if child_label_prefix:
            extra.append(child_label_prefix)
        require_rev = bool(
            step.get("require_review")
            if step.get("require_review") is not None
            else require_review_default
        )
        if require_rev or step.get("checklist"):
            extra.extend(["needs-review", "requires-review", "has-checklist"])
        labels = merge_labels("auto-chain", step_labels, extra=extra)

        desc = (
            f"{sdesc}\n\n---\nParent goal #{parent.id}: {goal_title}\n"
            f"DONE WHEN: {done_when}\n"
            f"TARGET: {done_when}\n"
            f"Assigned to {assignee.name} via auto-chain. "
            f"Call complete_task with evidence when the target is met."
        )
        # Prefer description already composed by workflow_run (has embed)
        if "DONE WHEN:" in (sdesc or "").upper() and len(sdesc) > 80:
            desc = sdesc
        acc_json = step.get("acceptance_json") or ""
        if not acc_json and (step.get("checklist") or require_rev):
            from .orchestration.acceptance import pack_acceptance
            acc_json = pack_acceptance(
                done_when=str(done_when),
                checklist=step.get("checklist") or [],
                require_review=require_rev or bool(step.get("checklist")),
            )

        child_kwargs: dict[str, Any] = {
            "user_id": user.id,
            "agent_id": assignee.id,
            "company_id": company_id or assignee.company_id,
            "project_id": project_id or assignee.project_id,
            "parent_task_id": parent.id,
            "title": f"[{i + 1}/{len(normalized)}] {stitle}"[:200],
            "description": desc[:8000],
            "status": status,
            "priority": priority or "high",
            "labels": labels,
            "assignee_type": "agent",
        }
        if hasattr(models.Task, "acceptance_json") and acc_json:
            child_kwargs["acceptance_json"] = acc_json[:8000]

        child = models.Task(**child_kwargs)
        db.add(child)
        db.flush()
        if status == "queued" and first_queued_id is None:
            first_queued_id = child.id
        children.append(
            {
                "task_id": child.id,
                "title": child.title,
                "agent_id": assignee.id,
                "agent_name": assignee.name,
                "status": child.status,
                "done_when": str(done_when)[:200],
                "labels": labels,
            }
        )

    db.commit()
    db.refresh(parent)

    # Start first step immediately (do not wait for Vercel daily cron)
    if first_queued_id:
        try:
            from .task_runner import kick_queued_task
            await kick_queued_task(first_queued_id, user_id=user.id)
        except Exception as e:
            log.warning("kick first chain step failed: %s", e)

    # Live ops banner
    try:
        from .live_ops import emit_ops

        await emit_ops(
            user.id,
            kind="plan",
            status="running",
            title=f"Auto-chain: {goal_title}"[:120],
            detail=f"{len(children)} steps delegated under task #{parent.id}",
            agent_id=chain_owner.id,
            task_id=parent.id,
            plan_id=f"goal-{parent.id}",
            payload={"children": children},
            db=db,
        )
        for c in children:
            await emit_ops(
                user.id,
                kind="step",
                status="queued" if c["status"] == "queued" else "todo",
                title=c["title"][:120],
                detail=f"→ {c['agent_name']}",
                agent_id=c["agent_id"],
                task_id=c["task_id"],
                plan_id=f"goal-{parent.id}",
                db=db,
            )
    except Exception as e:
        log.warning("emit_ops goal chain failed: %s", e)

    try:
        from .ws import manager
        from .agent_serialize import task_dict

        await manager.broadcast(
            f"agents:{user.id}",
            {
                "event": "goal_chain_started",
                "parent": task_dict(parent, db),
                "children": children,
            },
        )
    except Exception:
        pass

    return {
        "ok": True,
        "message": f"Goal chain started with {len(children)} delegated steps",
        "parent_task_id": parent.id,
        "owner_agent_id": chain_owner.id,
        "company_id": company_id,
        "project_id": project_id,
        "children": children,
        "steps": len(children),
    }


async def on_task_finished(
    db: Session,
    task: models.Task,
    *,
    final_status: str,
    commit: bool = True,
) -> dict[str, Any]:
    """
    Called when a task completes or fails.
    - Roll up parent goal when all children terminal
    - Queue next sibling step if sequential labels present
    - Escalate failed auto-chain children to parent agent

    commit=True (default): persist chain mutations here.
    commit=False: only mutate + flush so the caller owns a single transaction
    (task_runner sets status/billing then commits once after this returns).
    """
    out: dict[str, Any] = {"parent_updated": False, "next_queued": None}

    if not task or not getattr(task, "parent_task_id", None):
        return out

    parent = db.get(models.Task, task.parent_task_id)
    if not parent or parent.user_id != task.user_id:
        return out

    siblings = (
        db.query(models.Task)
        .filter(models.Task.parent_task_id == parent.id)
        .order_by(models.Task.id)
        .all()
    )
    terminal = {"completed", "failed", "review"}

    def _partition(kids: list[models.Task]) -> tuple[list, list, list]:
        open_ = [s for s in kids if (s.status or "") not in terminal]
        done_ = [s for s in kids if (s.status or "") == "completed"]
        failed_ = [s for s in kids if (s.status or "") == "failed"]
        return open_, done_, failed_

    # Current task status is already set by the caller on the same session identity;
    # include it so rollup/next-sibling see the terminal state before commit.
    open_kids, done, failed = _partition(siblings)

    # Sequential unlock: queue the next todo sibling after a completed step.
    # Skip chain-skipped / terminal-labeled rows so fail-smart never revives them.
    if final_status == "completed" and open_kids:
        for s in siblings:
            if s.id == task.id:
                continue
            st = (s.status or "")
            sl = (s.labels or "").lower()
            if "chain-skipped" in sl:
                continue
            if st == "todo" and s.agent_id:
                agent = db.get(models.Agent, s.agent_id)
                if agent and agent.status == "active":
                    s.status = "queued"
                    s.updated_at = datetime.utcnow()
                    out["next_queued"] = s.id
                    break
                # inactive assignee — keep scanning for a runnable todo
                continue
            if st in ("queued", "in_progress"):
                break  # already something in flight

    # Failed step: stop sequential progression. Cancel remaining todos so the
    # parent can roll up instead of hanging forever with open children.
    # In-flight (queued/in_progress) siblings are left alone.
    # Tag chain-skipped + escalated so autonomy will not re-queue them
    # (failed scan + high-priority escalate would otherwise revive the chain).
    # Also clear any already-queued next sibling so close-skill + fail-fast
    # cannot leave a half-alive chain zombie running after a hard fail.
    if final_status == "failed":
        skipped: list[int] = []
        for s in siblings:
            if s.id == task.id:
                continue
            st = (s.status or "")
            if st == "todo" or (
                st == "queued"
                and "auto-chain" in (s.labels or "").lower()
                and s.id > task.id
            ):
                s.status = "failed"
                s.result = (
                    f"Skipped: prior chain step #{task.id} failed"
                )[:2000]
                sl = (s.labels or "")
                extras = [x for x in ("chain-skipped", "escalated") if x not in sl]
                if extras:
                    s.labels = (f"{sl},{','.join(extras)}".strip(",") if sl else ",".join(extras))
                s.completed_at = s.completed_at or datetime.utcnow()
                s.updated_at = datetime.utcnow()
                skipped.append(s.id)
        if skipped:
            out["skipped"] = skipped
            open_kids, done, failed = _partition(siblings)

    # Parent roll-up
    labels = (parent.labels or "")
    if "goal" in labels or "auto-chain" in labels or "plan" in labels:
        if not open_kids:
            if failed and not done:
                parent.status = "failed"
                parent.result = (
                    f"Chain failed: {len(failed)} step(s) failed, {len(done)} completed."
                )[:2000]
            elif failed:
                parent.status = "review"
                parent.result = (
                    f"Chain finished with issues: {len(done)} ok, {len(failed)} failed. "
                    f"Review child tasks."
                )[:2000]
            else:
                parent.status = "completed"
                parent.completed_at = datetime.utcnow()
                parent.result = (
                    f"All {len(done)} chain steps completed."
                )[:2000]
            parent.updated_at = datetime.utcnow()
            out["parent_updated"] = True
            out["parent_status"] = parent.status
        else:
            # keep parent monitoring
            if parent.status not in ("in_progress", "review"):
                parent.status = "in_progress"
                parent.updated_at = datetime.utcnow()
                out["parent_updated"] = True
                out["parent_status"] = parent.status

    # Failed child → mark parent labels + escalate notice without un-failing
    # the child (requeue=False) or committing the caller's unit of work.
    if final_status == "failed":
        pl = parent.labels or ""
        if "child-failed" not in pl:
            parent.labels = (pl + ",child-failed").strip(",") if pl else "child-failed"
        # Stamp escalated even if policy is "never" so autonomy failed-scan
        # does not re-queue a terminal chain step.
        tl = task.labels or ""
        if "escalated" not in tl:
            task.labels = (tl + ",escalated").strip(",") if tl else "escalated"
        try:
            from .autonomy import escalate_task

            agent = db.get(models.Agent, task.agent_id) if task.agent_id else None
            esc = await escalate_task(
                db,
                task,
                reason_code="failure",
                reason_text=(task.result or "auto-chain step failed")[:500],
                from_agent=agent,
                requeue=False,
                commit=commit,
            )
            out["escalated"] = esc is not None
        except Exception as e:
            log.warning("escalate on chain fail: %s", e)
            out["escalated"] = False

    # Single-writer rule: either we commit, or the caller does (after flush).
    # Never leave callers double-committing the same unit of work.
    if commit:
        db.commit()
    else:
        db.flush()

    # Kick next sibling run immediately after unlock (outside caller's txn when possible)
    next_to_kick = out.get("next_queued")

    if out.get("parent_updated") or out.get("next_queued"):
        try:
            from .live_ops import emit_ops

            # When commit=False the caller still owns the open transaction.
            # emit_ops always commits — use a private session so it cannot
            # commit (or roll up with) the caller's pending unit of work.
            await emit_ops(
                task.user_id,
                kind="system",
                status=out.get("parent_status") or final_status,
                title=f"Chain update · parent #{parent.id}",
                detail=json.dumps(
                    {
                        "child": task.id,
                        "final": final_status,
                        "next_queued": out.get("next_queued"),
                        "parent_status": out.get("parent_status"),
                        "open": len(open_kids),
                    }
                )[:400],
                agent_id=parent.agent_id,
                task_id=parent.id,
                db=None if not commit else db,
            )
        except Exception:
            pass
        try:
            from .ws import manager

            await manager.broadcast(
                f"agents:{task.user_id}",
                {
                    "event": "goal_chain_progress",
                    "parent_id": parent.id,
                    "child_id": task.id,
                    "final_status": final_status,
                    **{k: v for k, v in out.items() if k != "escalated"},
                },
            )
        except Exception:
            pass

    if next_to_kick:
        try:
            from .task_runner import kick_queued_task
            # Runner reloads task by id after caller commits when commit=False.
            await kick_queued_task(int(next_to_kick), user_id=task.user_id)
            out["next_started"] = next_to_kick
        except Exception as e:
            log.warning("kick next chain step failed: %s", e)

    return out


def chain_info_from_skill_results(
    skill_results: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """
    If chat/task skill post-process already ran execute_goal successfully,
    return a goal_chain payload so callers can skip maybe_auto_chain_from_chat
    (avoids double parent) and still surface parent_task_id to the UI.
    """
    for r in skill_results or []:
        if r.get("skill") == "execute_goal" and r.get("ok"):
            return {**r, "from_skill": True}
    return None


async def maybe_auto_chain_from_chat(
    db: Session,
    user: models.User,
    agent: models.Agent,
    message: str,
    *,
    skill_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """
    If the human sent a goal-like prompt to orchestrator/lead, start the chain automatically.
    Returns chain result or None if skipped.

    If skill_results already contains a successful execute_goal, returns that
    chain payload (from_skill=True) without creating another parent.
    """
    from_skill = chain_info_from_skill_results(skill_results)
    if from_skill:
        return from_skill

    if not looks_like_goal(message):
        return None
    if not (is_orchestrator(agent) or is_lead_agent(agent) or (agent.permission_level or "") in ("admin", "lead")):
        # Still allow if they are the only agent
        n = db.query(models.Agent).filter_by(user_id=user.id, status="active").count()
        if n > 1:
            return None
    # Avoid double-chaining the same prompt spam
    recent = (
        db.query(models.Task)
        .filter(
            models.Task.user_id == user.id,
            models.Task.labels.contains("auto-chain"),
            models.Task.status.in_(("todo", "queued", "in_progress")),
        )
        .order_by(models.Task.id.desc())
        .limit(8)
        .all()
    )
    msg_head = (message or "").strip()[:80]
    for t in recent:
        if msg_head and msg_head in (t.description or ""):
            parent_id = t.id if "goal" in (t.labels or "") else t.parent_task_id
            # Prefer actual parent goal row when we matched a step child
            if parent_id and parent_id != t.id:
                parent = db.get(models.Task, parent_id)
                if parent and "goal" in (parent.labels or ""):
                    parent_id = parent.id
            return {
                "ok": True,
                "message": "Goal chain already running for similar prompt",
                "parent_task_id": parent_id,
                "deduped": True,
            }

    return await start_goal_chain(
        db,
        user,
        agent,
        message,
        priority="high",
        auto_queue=True,
    )
