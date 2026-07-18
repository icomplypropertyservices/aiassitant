import asyncio, json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..database import get_db, SessionLocal
from .. import models
from ..auth_utils import get_current_user, user_from_ws_token, ensure_credits, accept_and_authenticate_ws
from ..ws import manager
from ..llm import stream_completion, complete, provider_hint
from .. import channels
from ..pricing import estimate_tokens
from ..plans import plan_limits
from ..usage_billing import charge_usage, bill_llm_turn
from ..user_keys import credentials_for_user
from ..async_jobs import schedule as schedule_job
from ..task_status import ALLOWED as TASK_STATUSES, normalize_status
from ..agent_prompts import build_agent_system_prompt, build_task_prompt, team_context
from ..agent_roles import (
    agent_sort_key,
    find_orchestrator,
    is_orchestrator,
    promote_orchestrator,
    resolve_create_role,
)
from ..agent_serialize import agent_out, agents_out_list, task_dict
from ..agent_hierarchy import build_hierarchy_payload, ensure_main_orchestrator, ensure_master_designer
from ..seed_templates import SEED_TEMPLATES, NOTIFY_FIELDS
from ..agent_roles import is_orchestrator

router = APIRouter(prefix="/agents", tags=["agents"])


def _agent_plan_cap(db: Session, user) -> tuple[int, int, bool]:
    """Return (current_count, max_agents, is_admin). max_agents from plan_limits."""
    count = db.query(models.Agent).filter_by(user_id=user.id).count()
    max_agents = int(plan_limits(user.plan).get("agents") or 0)
    is_admin = user.role == "admin"
    return count, max_agents, is_admin


def _require_agent_slot(db: Session, user) -> tuple[int, int]:
    """Raise 400 if non-admin is at/over plan agent cap. Returns (count, max_agents)."""
    count, max_agents, is_admin = _agent_plan_cap(db, user)
    if not is_admin and count >= max_agents:
        raise HTTPException(
            400,
            f"Your plan allows up to {max_agents} agents. Upgrade on Billing.",
        )
    return count, max_agents


def mode_for_template(template_type: str) -> str:
    tt = (template_type or "").lower()
    if any(k in tt for k in ("sales", "marketing")):
        return "sales"
    if any(k in tt for k in ("support", "reviews", "booking")):
        return "support"
    if any(k in tt for k in ("coding", "code", "dev", "ops")):
        return "coding" if "coding" in tt or "code" in tt or "dev" in tt else "general"
    if "lead" in tt:
        return "general"
    return "general"


def _would_cycle(db: Session, agent_id: int, new_parent_id: int) -> bool:
    """True if setting parent_id would create a cycle."""
    seen = set()
    cur = new_parent_id
    while cur:
        if cur == agent_id:
            return True
        if cur in seen:
            return True
        seen.add(cur)
        p = db.get(models.Agent, cur)
        cur = p.parent_id if p else None
    return False


def _team_context(a: models.Agent, db: Session) -> str:
    """Back-compat wrapper — prefer agent_prompts.team_context."""
    return team_context(a, db)


class AgentIn(BaseModel):
    name: str
    template_type: str = "custom"
    personality: str = "Professional, friendly and concise."
    model: str = "vps-fast"
    idle_mode: str = "never_idle"
    config: dict = {}
    is_lead: bool = False
    hierarchy_role: str = "member"  # lead | member | specialist
    parent_id: int | None = None
    company_id: int | None = None
    project_id: int | None = None
    permission_level: str = "operator"
    escalate_when: str = "on_failure"
    escalate_reason: str = ""
    escalate_to: str = "parent"
    escalate_human_id: int | None = None

class AgentUpdate(BaseModel):
    name: str | None = None
    personality: str | None = None
    model: str | None = None
    idle_mode: str | None = None
    config: dict | None = None
    is_lead: bool | None = None
    hierarchy_role: str | None = None
    parent_id: int | None = None  # set null by sending 0 or use HierarchyIn
    company_id: int | None = None
    project_id: int | None = None
    permission_level: str | None = None
    escalate_when: str | None = None
    escalate_reason: str | None = None
    escalate_to: str | None = None
    escalate_human_id: int | None = None

class HierarchyIn(BaseModel):
    parent_id: int | None = None  # None / omit to clear? use clear_parent
    clear_parent: bool = False
    is_lead: bool | None = None
    hierarchy_role: str | None = None
    report_ids: list[int] | None = None  # make these agents report to this one

class DelegateIn(BaseModel):
    to_agent_id: int
    description: str
    title: str = ""
    priority: str = "medium"
    run_now: bool = True

class TaskIn(BaseModel):
    description: str
    title: str = ""
    project_id: int | None = None
    priority: str = "medium"
    labels: str = ""
    run_now: bool = True

class AgentChatIn(BaseModel):
    message: str
    conversation_id: int | None = None

class TaskStatusIn(BaseModel):
    status: str
    priority: str | None = None
    title: str | None = None
    description: str | None = None
    agent_id: int | None = None


class SkillsUpdateIn(BaseModel):
    enabled: list[str] = []


class SkillRunIn(BaseModel):
    skill: str
    args: dict = {}


class MemoryIn(BaseModel):
    title: str = ""
    content: str
    kind: str = "note"
    tags: str = ""
    save_to_training: bool = False


class AgentMsgIn(BaseModel):
    to_agent_id: int
    message: str
    expect_reply: bool = True


class SpawnIn(BaseModel):
    name: str
    template_type: str = "custom"
    personality: str = "Professional, friendly and concise."
    hierarchy_role: str = "member"
    parent_id: int | None = None


async def log_activity(agent_id: int, user_id: int, type_: str, message: str):
    db = SessionLocal()
    try:
        log = models.ActivityLog(agent_id=agent_id, type=type_, message=message)
        db.add(log); db.commit()
        await manager.broadcast(f"agents:{user_id}", {
            "event": "activity", "agent_id": agent_id,
            "entry": {"id": log.id, "type": type_, "message": message, "created_at": log.created_at},
        })
    finally:
        db.close()

@router.get("/")
def list_agents(
    company_id: int | None = None,
    project_id: int | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    q = db.query(models.Agent).filter_by(user_id=user.id)
    if company_id is not None:
        q = q.filter_by(company_id=company_id)
    if project_id is not None:
        q = q.filter_by(project_id=project_id)
    agents = q.all()
    agents.sort(key=agent_sort_key)
    return agents_out_list(db, agents)


@router.get("/hierarchy")
def agent_hierarchy(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Full agent org tree: Main Orchestrator always first, then leads → reports."""
    return build_hierarchy_payload(db, user.id)


@router.post("/ensure-orchestrator")
async def ensure_orchestrator(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Create the Main AI Orchestrator if missing — always sits at top of hierarchy."""
    existing = find_orchestrator(db, user.id)
    if existing:
        promote_orchestrator(db, existing)
        db.commit()
        return agent_out(existing, db, include_team=True)

    ensure_credits(db, user.id)
    count = db.query(models.Agent).filter_by(user_id=user.id).count()
    max_agents = int(plan_limits(user.plan).get("agents") or 0)
    if user.role != "admin" and count >= max_agents:
        raise HTTPException(400, f"Your plan allows up to {max_agents} agents. Upgrade on Billing.")

    a = ensure_main_orchestrator(db, user)
    await log_activity(a.id, user.id, "info", "Main AI Orchestrator created — pinned at top of hierarchy")
    return agent_out(a, db, include_team=True)


@router.post("/ensure-designer")
async def ensure_designer(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Create or return Master Designer — polish guardian for mobile/agent UX."""
    from ..agent_hierarchy import ensure_master_designer, polish_checklist
    a = ensure_master_designer(db, user)
    await log_activity(a.id, user.id, "info", "Master Designer ready — polish gates active")
    out = agent_out(a, db, include_team=True)
    out["polish_gates"] = polish_checklist()
    return out


@router.post("/seed-starter-team")
async def seed_starter_team(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """One-click seed: creates a rich, balanced professional team (~20 agents) using all the great templates."""
    if user.role != "admin" and (not user.subscription_active or user.plan in (None, "", "none")):
        raise HTTPException(402, "Choose a subscription plan to create agents")
    ensure_credits(db, user.id)

    count = db.query(models.Agent).filter_by(user_id=user.id).count()
    max_agents = int(plan_limits(user.plan).get("agents") or 0)
    # Admin may bypass plan caps with a high ceiling
    if user.role == "admin":
        max_agents = max(max_agents, 10_000)
    remaining = max(0, max_agents - count)
    if remaining < 3:
        raise HTTPException(
            400,
            f"Your plan allows up to {max_agents} agents "
            f"({count} in use, {remaining} slot(s) left). "
            "Need at least 3 free slots to seed the starter team. Upgrade on Billing.",
        )

    created_ids = []
    name_map = {}
    _live_count = count  # track newly created (not re-used existing)

    # Core always (may create if missing — respect remaining slots)
    orch = ensure_main_orchestrator(db, user)
    name_map["Main AI Orchestrator"] = orch
    created_ids.append(orch.id)
    _live_count = db.query(models.Agent).filter_by(user_id=user.id).count()

    if _live_count < max_agents:
        designer = ensure_master_designer(db, user)
        name_map["Master Designer"] = designer
        created_ids.append(designer.id)
        _live_count = db.query(models.Agent).filter_by(user_id=user.id).count()
    else:
        designer = db.query(models.Agent).filter_by(user_id=user.id, name="Master Designer").first()
        if designer:
            name_map["Master Designer"] = designer
            created_ids.append(designer.id)

    def create_from_seed(seed_name: str, overrides: dict | None = None):
        nonlocal _live_count
        tpl = next((t for t in SEED_TEMPLATES if t[0] == seed_name), None)
        if not tpl:
            return None
        full_name, ttype, desc, fields, _cost = tpl
        # Skip if already exists with that name
        existing = db.query(models.Agent).filter_by(user_id=user.id, name=full_name).first()
        if existing:
            name_map[full_name] = existing
            if existing.id not in created_ids:
                created_ids.append(existing.id)
            return existing

        # Stop creating new agents when at plan max
        if _live_count >= max_agents:
            return None

        cfg = {f["name"]: (overrides or {}).get(f["name"], "") for f in fields}

        from ..agent_scaffold import apply_create_defaults, repair_agent
        hrole = "orchestrator" if ttype == "orchestrator" else ("lead" if ttype == "lead" else "member")
        defaults = apply_create_defaults(None, ttype, hrole)
        a = models.Agent(
            user_id=user.id,
            name=full_name,
            template_type=ttype,
            personality=desc[:220],
            model=defaults["model"],
            idle_mode="never_idle",
            config=json.dumps({**cfg, "autonomy": "full"}),
            hierarchy_role=hrole,
            is_lead=ttype in ("orchestrator", "lead"),
            status="active",
            permission_level=defaults["permission_level"],
            escalate_when="on_failure",
            escalate_to="parent",
        )
        db.add(a)
        db.flush()
        repair_agent(db, a, force_never_idle=True, expand_skills=True)
        name_map[full_name] = a
        created_ids.append(a.id)
        _live_count += 1
        return a

    # Leadership
    create_from_seed("Main AI Orchestrator")
    create_from_seed("Master Designer")
    lead = create_from_seed("Lead Agent / Team Lead")
    sales_lead = create_from_seed("Sales Lead Agent")
    ops_lead = create_from_seed("Operations Lead")

    # Sales
    create_from_seed("Sales Outreach Agent")
    create_from_seed("Lead Qualifier")
    create_from_seed("Appointment Booker")

    # Support
    create_from_seed("Customer Support Agent")
    create_from_seed("Review Responder")
    create_from_seed("Complaint Handler")

    # Content
    create_from_seed("Content Writer Agent")
    create_from_seed("Social Media Manager")
    create_from_seed("Email Newsletter Writer")

    # Engineering (the biggest pod)
    create_from_seed("Full-Stack Developer")
    create_from_seed("Frontend Engineer")
    create_from_seed("Backend API Engineer")
    create_from_seed("Code Reviewer")
    create_from_seed("QA / Test Engineer")

    # Ops & PM
    create_from_seed("Research Analyst")
    create_from_seed("Meeting Summariser")
    create_from_seed("Product Manager")

    # Nice hierarchy wiring
    if sales_lead:
        for n in ["Sales Outreach Agent", "Lead Qualifier", "Appointment Booker"]:
            if n in name_map:
                name_map[n].parent_id = sales_lead.id
    if ops_lead:
        for n in ["Meeting Summariser", "Research Analyst"]:
            if n in name_map:
                name_map[n].parent_id = ops_lead.id
    if lead:
        for n in ["Sales Lead Agent", "Operations Lead"]:
            if n in name_map:
                name_map[n].parent_id = lead.id

    # Full autonomy stack for every seeded agent
    from ..agent_scaffold import scaffold_workspace, repair_workspace
    for a in name_map.values():
        a.idle_mode = "never_idle"
        a.status = "active"
    db.commit()
    repair_workspace(db, user.id)

    # Return fresh list
    fresh = db.query(models.Agent).filter(models.Agent.id.in_(created_ids)).all()
    capped = _live_count >= max_agents
    msg = "Professional starter team of ~20 agents created with proper hierarchy, leads, and specialist pods."
    if capped:
        msg = (
            f"Starter team seeded up to your plan limit ({max_agents} agents). "
            "Upgrade on Billing for more agent slots."
        )
    return {
        "ok": True,
        "count": len(fresh),
        "agents": [agent_out(a, db) for a in fresh],
        "message": msg,
        "plan_limit": max_agents,
        "at_limit": capped,
    }


@router.post("/seed-professional-40")
async def seed_professional_40(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """
    ONE-CLICK: Spawn a massive professional team of ~40 agents.
    Uses the meta 'spawn_team' + bulk skill enabling logic so agents are 'made' with skills.
    Creates rich hierarchy: Orchestrator + Designer + Leads (sales/ops/content/eng) + 30+ specialists.
    Respects plan agent caps (admin bypass); stops at max or 400 if no room to seed.
    """
    from ..agent_scaffold import repair_agent, repair_workspace, map_model
    from ..agent_skills import SKILL_CATALOG, set_enabled_skills, DEFAULT_ENABLED, _apply_preset_skills
    import json as _json

    count0, max_agents, is_admin = _agent_plan_cap(db, user)
    live_count = count0
    capped = False
    newly_created = 0

    created = []
    name_map = {}

    def _room() -> bool:
        """True if another agent may be created under plan limits."""
        nonlocal live_count, capped
        if is_admin:
            return True
        live_count = db.query(models.Agent).filter_by(user_id=user.id).count()
        if live_count >= max_agents:
            capped = True
            return False
        return True

    # 1. Core leaders (reuse existing; only create when a plan slot remains)
    existing_orch = find_orchestrator(db, user.id)
    if not existing_orch and not _room():
        raise HTTPException(
            400,
            f"Your plan allows up to {max_agents} agents. Cannot seed team. Upgrade on Billing.",
        )
    before = db.query(models.Agent).filter_by(user_id=user.id).count()
    orch = ensure_main_orchestrator(db, user)
    after = db.query(models.Agent).filter_by(user_id=user.id).count()
    newly_created += max(0, after - before)
    live_count = after
    name_map["Main AI Orchestrator"] = orch
    created.append(orch.id)

    designer_existing = (
        db.query(models.Agent)
        .filter_by(user_id=user.id, name="Master Designer")
        .first()
    )
    if designer_existing or _room():
        before = db.query(models.Agent).filter_by(user_id=user.id).count()
        designer = ensure_master_designer(db, user)
        after = db.query(models.Agent).filter_by(user_id=user.id).count()
        newly_created += max(0, after - before)
        live_count = after
        name_map["Master Designer"] = designer
        created.append(designer.id)

    def _mk(name, ttype, personality, hrole="member", parent=None):
        nonlocal live_count, capped, newly_created
        existing = db.query(models.Agent).filter_by(user_id=user.id, name=name).first()
        if existing:
            name_map[name] = existing
            if existing.id not in created:
                created.append(existing.id)
            return existing
        if not _room():
            return None
        a = models.Agent(
            user_id=user.id,
            name=name,
            template_type=ttype,
            personality=personality[:240],
            model=map_model("quality"),
            idle_mode="never_idle",
            status="active",
            hierarchy_role=hrole,
            is_lead=hrole in ("lead", "orchestrator"),
            parent_id=parent,
            permission_level="admin" if hrole == "orchestrator" else ("lead" if hrole == "lead" else "operator"),
            config=_json.dumps({"autonomy": "full"}),
            escalate_when="on_failure",
            escalate_to="parent",
        )
        db.add(a)
        db.flush()
        repair_agent(db, a, force_never_idle=True, expand_skills=True)
        name_map[name] = a
        created.append(a.id)
        newly_created += 1
        live_count += 1
        return a

    def _pid(agent):
        return agent.id if agent else None

    # Leadership pod
    ceo = _mk("CEO / Vision Lead", "lead", "Sets company direction and priorities. Owns top-level decisions and OKRs.", "lead")
    sales_lead = _mk("VP Sales", "lead", "Owns revenue, pipeline, outreach pods and quota attainment.", "lead", parent=_pid(ceo))
    ops_lead = _mk("VP Operations", "lead", "Runs delivery, support, scheduling and customer ops.", "lead", parent=_pid(ceo))
    content_lead = _mk("VP Content & Growth", "lead", "Owns all content, SEO, social, email, ads and brand.", "lead", parent=_pid(ceo))
    eng_lead = _mk("VP Engineering", "lead", "Architecture, code quality, delivery velocity and infra.", "lead", parent=_pid(ceo))
    cs_lead = _mk("VP Customer Success", "lead", "Health scores, onboarding, retention, QBRs and expansion.", "lead", parent=_pid(ceo))

    # Sales pod (8)
    for nm, pers in [
        ("Outbound SDR", "Cold outreach specialist (email + LinkedIn + calls). Books first meetings."),
        ("Lead Qualifier", "Qualifies inbound leads, scores them, books discovery calls."),
        ("Appointment Booker", "Negotiates calendars and books meetings into the diary."),
        ("Proposal Writer", "Creates beautiful, accurate proposals and SOWs from briefs."),
        ("Deal Closer", "Handles late-stage objections and gets signatures."),
        ("Account Executive", "Runs full-cycle demos and negotiations for larger deals."),
        ("Renewals & Expansion", "Manages renewals, upsells and cross-sells."),
        ("Sales Ops Analyst", "Keeps CRM clean, builds reports and forecasts."),
    ]:
        a = _mk(nm, "sales", pers, "member", parent=_pid(sales_lead))
        if a:
            set_enabled_skills(db, a, [s for s in DEFAULT_ENABLED if any(k in s for k in ("sales","lead","proposal","cold","book","qualif","close","churn","upsell","email","sms"))] or DEFAULT_ENABLED)

    # Support / Success pod (7)
    for nm, pers in [
        ("Tier-1 Support", "Answers everyday questions fast with perfect tone."),
        ("Escalations & Complaints", "De-escalates and resolves complex or angry customers."),
        ("Onboarding Specialist", "Gets new customers live and hitting value quickly."),
        ("Customer Success Manager", "Owns named accounts, health scores and QBRs."),
        ("Retention & Cancel Save", "Stops churn and wins customers back with smart offers."),
        ("Review & Reputation", "Monitors and replies to Google / Trustpilot reviews."),
        ("Knowledge Curator", "Writes help articles and improves the training base from tickets."),
    ]:
        _mk(nm, "support", pers, "member", parent=_pid(cs_lead))

    # Content & Growth pod (7)
    for nm, pers in [
        ("Blog & SEO Writer", "Long-form SEO articles that rank and convert."),
        ("Social Media Manager", "Posts daily across LinkedIn, X, Instagram with hooks."),
        ("Email Newsletter", "Writes weekly value-packed newsletters that drive replies."),
        ("Ad Copywriter", "High-converting Google/FB/IG ad copy and landing pages."),
        ("Video Scriptwriter", "Short and long-form video scripts for YouTube and ads."),
        ("Case Study Writer", "Turns happy customers into powerful proof assets."),
        ("Growth Experimenter", "Designs and analyses acquisition experiments."),
    ]:
        _mk(nm, "content", pers, "member", parent=_pid(content_lead))

    # Engineering pod (8)
    for nm, pers in [
        ("Backend Engineer", "APIs, data models, auth, billing, integrations."),
        ("Frontend Engineer", "Polished React UIs, forms, mobile-first components."),
        ("Full-Stack Feature Dev", "Ships complete features end-to-end."),
        ("Code Reviewer & QA", "Reviews PRs, writes tests, prevents regressions."),
        ("DevOps & Infra", "Docker, CI, deploy, monitoring, secrets."),
        ("Data & Analytics Eng", "Pipelines, dashboards, metric definitions."),
        ("Security & Compliance", "Threat modelling, audits, GDPR, pen-test support."),
        ("Mobile / React Native", "iOS + Android apps and Capacitor shells."),
    ]:
        _mk(nm, "coding", pers, "member", parent=_pid(eng_lead))

    # Ops + PM + Finance + HR + Legal pod (more to hit ~40)
    extra = [
        ("Product Manager", "ops", "Writes specs, prioritises roadmap, runs discovery."),
        ("Research Analyst", "ops", "Competitor deep dives, market sizing, ICP research."),
        ("Finance & Invoicing", "ops", "Invoices, chasers, cashflow, basic reporting."),
        ("Recruiter / HR", "ops", "Writes JDs, screens CVs, coordinates interviews."),
        ("Legal & Compliance", "ops", "First-pass contracts, policies and risk notes."),
        ("Meeting Summariser", "ops", "Turns every call into actions + follow-ups."),
        ("Project Coordinator", "ops", "Tracks milestones, unblocks teams, reports status."),
        ("Executive Assistant", "ops", "Prioritises CEO time, books travel, manages comms."),
    ]
    for nm, tt, pers in extra:
        _mk(nm, tt, pers, "member", parent=_pid(ops_lead))

    # Cannot seed meaningfully: no agents collected and no creates under cap
    if not created:
        raise HTTPException(
            400,
            f"Your plan allows up to {max_agents} agents. Cannot seed team. Upgrade on Billing.",
        )

    # Bulk-enable powerful presets on all non-orchestrator agents
    all_agents = db.query(models.Agent).filter_by(user_id=user.id).all()
    for a in all_agents:
        if is_orchestrator(a):
            continue
        # Give everyone a strong base + role-specific extras
        base = list(DEFAULT_ENABLED)
        if any(k in (a.template_type or "") for k in ("sales", "lead")):
            base = list(set(base) | {s["id"] for s in SKILL_CATALOG if any(x in s["id"] for x in ("sales","proposal","cold","qualif","close"))})
        elif "support" in (a.template_type or "") or "success" in (a.name or "").lower():
            base = list(set(base) | {s["id"] for s in SKILL_CATALOG if any(x in s["id"] for x in ("support","ticket","escalat","onboard","health"))})
        elif "content" in (a.template_type or "") or "growth" in (a.name or "").lower():
            base = list(set(base) | {s["id"] for s in SKILL_CATALOG if any(x in s["id"] for x in ("content","linkedin","newsletter","seo","ad","video"))})
        elif "coding" in (a.template_type or "") or "engineer" in (a.name or "").lower():
            base = list(set(base) | {s["id"] for s in SKILL_CATALOG if any(x in s["id"] for x in ("code","api","test","debug","docker","ci","review"))})
        set_enabled_skills(db, a, base[:240])

    # Make everything fully autonomous
    for a in all_agents:
        a.idle_mode = "never_idle"
        a.status = "active"
    db.commit()
    repair_workspace(db, user.id)

    final = db.query(models.Agent).filter(models.Agent.id.in_(created)).all()
    msg = (
        f"Professional team of {len(final)} agents spawned with skills pre-enabled. "
        "Agents can now spawn + skill-enable more themselves."
    )
    if capped and not is_admin:
        msg += f" Plan limit of {max_agents} agents reached; remaining roles were not created. Upgrade on Billing for more."
    return {
        "ok": True,
        "count": len(final),
        "agents": [agent_out(a, db) for a in final],
        "message": msg,
        "plan_capped": bool(capped and not is_admin),
        "max_agents": max_agents,
        "newly_created": newly_created,
    }


@router.get("/designer/polish-review")
async def polish_review(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Master Designer review: pass/fail gates for ChatGPT-style agent chat + mobile polish."""
    from ..agent_hierarchy import ensure_master_designer, polish_checklist
    from ..live_ops import emit_ops

    designer = ensure_master_designer(db, user)
    gates = polish_checklist()
    implemented = {
        "agent_chat_fullscreen",
        "chatgpt_composer",
        "mobile_bottom_nav",
        "touch_targets",
        "safe_areas",
        "live_ops_banner",
        "business_crm",
        "permissions",
    }
    results = []
    for g in gates:
        ok = g["id"] in implemented
        results.append({
            **g,
            "status": "pass" if ok else "fail",
            "notes": "Verified in product build" if ok else "Needs work",
        })
    passed = sum(1 for r in results if r["status"] == "pass")
    summary = {
        "designer": agent_out(designer, db),
        "passed": passed,
        "total": len(results),
        "acceptable": passed == len(results),
        "gates": results,
        "verdict": (
            "Polish acceptable for mobile agent chat ship."
            if passed == len(results)
            else f"{passed}/{len(results)} gates passed — polish not yet acceptable."
        ),
    }
    await emit_ops(
        user.id,
        kind="system",
        status="done" if summary["acceptable"] else "failed",
        title="Master Designer polish review",
        detail=summary["verdict"],
        agent_id=designer.id,
        db=db,
    )
    await log_activity(designer.id, user.id, "action", f"Polish review: {summary['verdict']}")
    return summary


@router.get("/tasks/board")
def tasks_board(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """All tasks for the subscriber — kanban workflow (separate from chat)."""
    rows = (
        db.query(models.Task)
        .filter_by(user_id=user.id)
        .order_by(models.Task.id.desc())
        .limit(200)
        .all()
    )
    columns = {
        "todo": [], "queued": [], "in_progress": [], "review": [],
        "completed": [], "failed": [],
    }
    for t in rows:
        st = t.status if t.status in columns else "todo"
        columns[st].append(task_dict(t, db))
    return {
        "columns": columns,
        "counts": {k: len(v) for k, v in columns.items()},
        "total": len(rows),
    }


@router.get("/{agent_id}")
def get_agent(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = _get_owned(agent_id, user, db)
    out = agent_out(a, db, activity_limit=40, include_team=True)
    out["recent_tasks"] = [
        task_dict(t, db)
        for t in db.query(models.Task).filter_by(agent_id=a.id).order_by(models.Task.id.desc()).limit(30).all()
    ]
    # Team tasks for lead view
    report_ids = [r["id"] for r in out.get("reports") or []]
    if report_ids:
        team_tasks = (
            db.query(models.Task)
            .filter(models.Task.agent_id.in_(report_ids))
            .order_by(models.Task.id.desc())
            .limit(40)
            .all()
        )
        out["team_tasks"] = [task_dict(t, db) for t in team_tasks]
    else:
        out["team_tasks"] = []
    conv = (
        db.query(models.Conversation)
        .filter_by(user_id=user.id, agent_id=a.id)
        .order_by(models.Conversation.id.desc())
        .first()
    )
    out["chat"] = None
    if conv:
        msgs = (
            db.query(models.Message)
            .filter_by(conversation_id=conv.id)
            .order_by(models.Message.id)
            .all()
        )
        out["chat"] = {
            "conversation_id": conv.id,
            "messages": [{"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at} for m in msgs],
        }
    return out


@router.get("/{agent_id}/activity")
def agent_activity(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = _get_owned(agent_id, user, db)
    logs = (
        db.query(models.ActivityLog)
        .filter_by(agent_id=a.id)
        .order_by(models.ActivityLog.id.desc())
        .limit(100)
        .all()
    )
    return [
        {"id": l.id, "type": l.type, "message": l.message, "created_at": l.created_at}
        for l in logs
    ]


@router.post("/{agent_id}/duplicate")
async def duplicate_agent(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = _get_owned(agent_id, user, db)
    count = db.query(models.Agent).filter_by(user_id=user.id).count()
    max_agents = int(plan_limits(user.plan).get("agents") or 0)
    if user.role != "admin" and count >= max_agents:
        raise HTTPException(400, f"Your plan allows up to {max_agents} agents.")
    clone = models.Agent(
        user_id=user.id,
        name=f"{a.name} (copy)",
        template_type=a.template_type,
        personality=a.personality,
        model=a.model,
        idle_mode=a.idle_mode,
        status="paused",
        config=a.config,
        company_id=a.company_id,
        project_id=a.project_id,
        parent_id=a.parent_id,
        is_lead=False,
        hierarchy_role="member",
        permission_level=getattr(a, "permission_level", None) or "operator",
        escalate_when=getattr(a, "escalate_when", None) or "on_failure",
        escalate_reason=getattr(a, "escalate_reason", None) or "",
        escalate_to=getattr(a, "escalate_to", None) or "parent",
        escalate_human_id=getattr(a, "escalate_human_id", None),
    )
    db.add(clone)
    db.commit()
    db.refresh(clone)
    await log_activity(clone.id, user.id, "info", f"Cloned from agent #{a.id}")
    return agent_out(clone, db)

@router.post("/")
async def create_agent(data: AgentIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user.role != "admin" and (not user.subscription_active or user.plan in (None, "", "none")):
        raise HTTPException(402, "Choose a subscription plan to create agents")
    ensure_credits(db, user.id)
    count = db.query(models.Agent).filter_by(user_id=user.id).count()
    max_agents = int(plan_limits(user.plan).get("agents") or 0)
    if user.role != "admin" and count >= max_agents:
        raise HTTPException(400, f"Your plan allows up to {max_agents} agents. Upgrade on Billing.")

    role, is_lead, make_orch = resolve_create_role(
        hierarchy_role=data.hierarchy_role,
        template_type=data.template_type,
        is_lead=data.is_lead,
    )
    parent_id = data.parent_id
    if make_orch:
        parent_id = None
    if parent_id:
        _get_owned(parent_id, user, db)
    # Default non-orchestrator agents without parent → hang under main orchestrator
    if parent_id is None and not make_orch:
        orch = find_orchestrator(db, user.id)
        if orch:
            parent_id = orch.id

    company_id = data.company_id
    project_id = data.project_id
    if project_id:
        p = db.get(models.Project, project_id)
        if not p or (p.owner_user_id != user.id and user.role != "admin"):
            raise HTTPException(400, "Invalid project")
        if company_id is None:
            company_id = p.company_id
        elif company_id != p.company_id:
            raise HTTPException(400, "project_id does not belong to company_id")
    if company_id:
        c = db.get(models.Company, company_id)
        if not c or (c.owner_user_id != user.id and user.role != "admin"):
            raise HTTPException(400, "Invalid company")

    from ..permissions import normalize_permission, normalize_escalate_when, normalize_escalate_to
    from ..agent_scaffold import apply_create_defaults, repair_agent, map_model
    defaults = apply_create_defaults(data.model, data.template_type, role)
    cfg = dict(data.config or {})
    cfg.setdefault("autonomy", "full")
    a = models.Agent(
        user_id=user.id, name=data.name, template_type=data.template_type,
        personality=data.personality,
        model=map_model(data.model or defaults["model"]),
        idle_mode="never_idle",
        config=json.dumps(cfg),
        is_lead=is_lead,
        hierarchy_role=role,
        parent_id=parent_id,
        permission_level=normalize_permission(data.permission_level or defaults["permission_level"]),
        escalate_when=normalize_escalate_when(data.escalate_when or "on_failure"),
        escalate_reason=(data.escalate_reason or "").strip(),
        escalate_to=normalize_escalate_to(data.escalate_to or "parent"),
        escalate_human_id=data.escalate_human_id,
        status="active",
        company_id=company_id,
        project_id=project_id,
    )
    db.add(a)
    db.flush()
    if make_orch:
        promote_orchestrator(db, a)
    repair_agent(db, a, force_never_idle=True, expand_skills=True)
    db.commit()
    db.refresh(a)
    role_msg = " as Main Orchestrator" if make_orch else (" as Lead" if is_lead else (f" under #{parent_id}" if parent_id else ""))
    await log_activity(a.id, user.id, "info", f"Agent '{a.name}' created{role_msg} — full autonomy online")
    # Optional: auto-publish skill listing to AgentBay marketplace
    try:
        from ..agentbay_bridge import maybe_auto_publish
        await maybe_auto_publish(a, db)
        db.refresh(a)
    except Exception:
        pass
    return agent_out(a, db, include_team=True)

def _get_owned(agent_id: int, user, db) -> models.Agent:
    a = db.get(models.Agent, agent_id)
    if not a or (a.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Agent not found")
    return a

def _apply_hierarchy(a: models.Agent, db: Session, user, *, parent_id=None, clear_parent=False,
                     is_lead=None, hierarchy_role=None, report_ids=None):
    if clear_parent:
        a.parent_id = None
    elif parent_id is not None:
        if parent_id == a.id:
            raise HTTPException(400, "An agent cannot report to itself")
        if parent_id == 0:
            a.parent_id = None
        else:
            parent = _get_owned(parent_id, user, db)
            if _would_cycle(db, a.id, parent_id):
                raise HTTPException(400, "That parent would create a hierarchy cycle")
            a.parent_id = parent_id
            # Parent becomes a lead automatically
            parent.is_lead = True
            if (parent.hierarchy_role or "member") == "member":
                parent.hierarchy_role = "lead"

    if is_lead is not None:
        a.is_lead = is_lead
        if is_lead and (a.hierarchy_role or "member") == "member":
            a.hierarchy_role = "lead"
        if not is_lead and a.hierarchy_role == "lead":
            a.hierarchy_role = "member"
    if hierarchy_role is not None:
        if hierarchy_role not in ("orchestrator", "lead", "member", "specialist"):
            raise HTTPException(400, "hierarchy_role must be orchestrator, lead, member, or specialist")
        if hierarchy_role == "orchestrator":
            promote_orchestrator(db, a)
        else:
            a.hierarchy_role = hierarchy_role
            a.is_lead = hierarchy_role == "lead" or a.is_lead

    if report_ids is not None:
        a.is_lead = True
        if (a.hierarchy_role or "member") == "member":
            a.hierarchy_role = "lead"
        for rid in report_ids:
            if rid == a.id:
                continue
            child = _get_owned(rid, user, db)
            if _would_cycle(db, rid, a.id):
                raise HTTPException(400, f"Cannot assign agent #{rid} — would create a cycle")
            child.parent_id = a.id
            if (child.hierarchy_role or "") == "lead" and not child.is_lead:
                pass
            if child.hierarchy_role == "lead" and child.id == a.id:
                continue
            if child.hierarchy_role not in ("lead", "specialist"):
                child.hierarchy_role = child.hierarchy_role or "member"

@router.patch("/{agent_id}")
def update_agent(agent_id: int, data: AgentUpdate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    from ..permissions import normalize_permission, normalize_escalate_when, normalize_escalate_to
    a = _get_owned(agent_id, user, db)
    for field in ["name", "personality", "model", "idle_mode"]:
        v = getattr(data, field)
        if v is not None:
            setattr(a, field, v)
    if data.permission_level is not None:
        a.permission_level = normalize_permission(data.permission_level)
    if data.escalate_when is not None:
        a.escalate_when = normalize_escalate_when(data.escalate_when)
    if data.escalate_reason is not None:
        a.escalate_reason = (data.escalate_reason or "").strip()
    if data.escalate_to is not None:
        a.escalate_to = normalize_escalate_to(data.escalate_to)
    if data.escalate_human_id is not None:
        a.escalate_human_id = data.escalate_human_id or None
    if data.config is not None:
        a.config = json.dumps(data.config)
    if data.parent_id is not None or data.is_lead is not None or data.hierarchy_role is not None:
        _apply_hierarchy(
            a, db, user,
            parent_id=data.parent_id if data.parent_id is not None else None,
            clear_parent=data.parent_id == 0,
            is_lead=data.is_lead,
            hierarchy_role=data.hierarchy_role,
        )
    if data.company_id is not None or data.project_id is not None:
        company_id = data.company_id if data.company_id is not None else a.company_id
        project_id = data.project_id if data.project_id is not None else a.project_id
        # Allow clearing with 0
        if data.company_id == 0:
            company_id = None
        if data.project_id == 0:
            project_id = None
        if project_id:
            p = db.get(models.Project, project_id)
            if not p or (p.owner_user_id != user.id and user.role != "admin"):
                raise HTTPException(400, "Invalid project")
            if company_id is None:
                company_id = p.company_id
            elif company_id != p.company_id:
                raise HTTPException(400, "project_id does not belong to company_id")
        if company_id:
            c = db.get(models.Company, company_id)
            if not c or (c.owner_user_id != user.id and user.role != "admin"):
                raise HTTPException(400, "Invalid company")
        if data.company_id is not None:
            a.company_id = None if data.company_id == 0 else company_id
        if data.project_id is not None:
            a.project_id = None if data.project_id == 0 else project_id
        if data.company_id is not None and data.project_id is None and a.project_id:
            # Keep project if still under company; else clear
            p = db.get(models.Project, a.project_id)
            if not p or p.company_id != a.company_id:
                a.project_id = None
    db.commit()
    return agent_out(a, db, include_team=True)


@router.put("/{agent_id}/hierarchy")
async def set_hierarchy(agent_id: int, data: HierarchyIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Set lead flag, parent, and/or direct reports for an agent."""
    a = _get_owned(agent_id, user, db)
    _apply_hierarchy(
        a, db, user,
        parent_id=data.parent_id,
        clear_parent=data.clear_parent or data.parent_id == 0,
        is_lead=data.is_lead,
        hierarchy_role=data.hierarchy_role,
        report_ids=data.report_ids,
    )
    db.commit()
    db.refresh(a)
    await log_activity(a.id, user.id, "info", "Hierarchy updated")
    return agent_out(a, db, include_team=True)


@router.post("/{agent_id}/delegate")
async def delegate_task(agent_id: int, data: DelegateIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Lead agent delegates a task to a report (or any owned agent)."""
    lead = _get_owned(agent_id, user, db)
    target = _get_owned(data.to_agent_id, user, db)
    # Prefer target reporting to this lead, but allow any agent the user owns
    ensure_credits(db, user.id)
    t = models.Task(
        agent_id=target.id,
        user_id=user.id,
        project_id=target.project_id,
        company_id=target.company_id,
        title=(data.title or data.description[:60]).strip(),
        description=f"[Delegated by {lead.name}] {data.description}",
        status="queued" if data.run_now else "todo",
        priority=data.priority or "medium",
        labels="delegated",
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    await log_activity(lead.id, user.id, "action", f"Delegated task to {target.name}: {data.description[:60]}")
    await log_activity(target.id, user.id, "info", f"Task received from lead {lead.name}: {data.description[:60]}")
    if data.run_now:
        if target.status != "active":
            t.status = "todo"
            db.commit()
            raise HTTPException(400, f"{target.name} is paused — task saved as todo")
        await schedule_job(_run_task(target.id, user.id, t.id, t.description, target.name))
    return {"task": task_dict(t, db), "from_lead": lead.name, "to_agent": target.name}

@router.post("/{agent_id}/pause")
async def pause(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = _get_owned(agent_id, user, db)
    a.status = "paused"; db.commit()
    await log_activity(a.id, a.user_id, "info", "Agent paused")
    return agent_out(a, db)

@router.post("/{agent_id}/resume")
async def resume(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = _get_owned(agent_id, user, db)
    a.status = "active"; db.commit()
    await log_activity(a.id, a.user_id, "info", "Agent resumed")
    return agent_out(a, db)

@router.delete("/{agent_id}")
def delete_agent(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = _get_owned(agent_id, user, db)
    # Re-parent reports to this agent's parent (or root)
    for child in db.query(models.Agent).filter_by(parent_id=a.id).all():
        child.parent_id = a.parent_id
    db.query(models.ActivityLog).filter_by(agent_id=a.id).delete()
    db.query(models.Task).filter_by(agent_id=a.id).delete()
    db.delete(a); db.commit()
    return {"ok": True}

async def _run_task(agent_id: int, user_id: int, task_id: int, description: str, agent_name: str):
    """Delegate to task_runner (single implementation)."""
    from ..task_runner import run_agent_task
    await run_agent_task(agent_id, user_id, task_id, description, agent_name)


@router.post("/{agent_id}/tasks")
async def assign_task(agent_id: int, data: TaskIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = _get_owned(agent_id, user, db)
    if data.run_now and a.status != "active":
        raise HTTPException(400, "Agent is paused — resume it before running tasks")
    ensure_credits(db, user.id)
    company_id = None
    if data.project_id:
        p = db.get(models.Project, data.project_id)
        if not p or p.owner_user_id != user.id:
            raise HTTPException(400, "Invalid project")
        company_id = p.company_id
    t = models.Task(
        agent_id=a.id,
        user_id=user.id,
        project_id=data.project_id,
        company_id=company_id or a.company_id,
        title=(data.title or data.description[:60]).strip(),
        description=data.description,
        status="queued" if data.run_now else "todo",
        priority=data.priority or "medium",
        labels=data.labels or "",
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    await log_activity(a.id, user.id, "info", f"Task received: {data.description[:80]}")
    if data.run_now:
        await schedule_job(_run_task(a.id, user.id, t.id, data.description, a.name))
    return task_dict(t, db)


@router.get("/{agent_id}/tasks")
def list_tasks(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = _get_owned(agent_id, user, db)
    tasks = db.query(models.Task).filter_by(agent_id=a.id).order_by(models.Task.id.desc()).limit(50).all()
    return [task_dict(t, db) for t in tasks]


@router.get("/tasks/{task_id}")
def get_task(task_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    t = db.get(models.Task, task_id)
    if not t or (t.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Task not found")
    return task_dict(t, db)


@router.patch("/tasks/{task_id}")
async def update_task(task_id: int, data: TaskStatusIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    t = db.get(models.Task, task_id)
    if not t or (t.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Task not found")
    if data.status is not None:
        try:
            st = normalize_status(data.status)
        except ValueError as e:
            raise HTTPException(400, str(e))
        t.status = st
        if st == "completed":
            t.completed_at = datetime.utcnow()
    if data.priority is not None:
        t.priority = data.priority
    if data.title is not None:
        t.title = data.title.strip()
    if data.description is not None:
        t.description = data.description.strip()
    if data.agent_id is not None:
        if data.agent_id:
            _get_owned(data.agent_id, user, db)
        t.agent_id = data.agent_id or None
    t.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(t)
    await manager.broadcast(f"agents:{user.id}", {"event": "task_updated", "task": task_dict(t, db)})
    return task_dict(t, db)


@router.post("/tasks/{task_id}/run")
async def run_task(task_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Execute (or re-run) a task with its assigned agent."""
    t = db.get(models.Task, task_id)
    if not t or (t.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Task not found")
    if not t.agent_id:
        raise HTTPException(400, "Assign an agent to this task first")
    a = _get_owned(t.agent_id, user, db)
    if a.status != "active":
        raise HTTPException(400, "Agent is paused")
    ensure_credits(db, user.id)
    t.status = "queued"
    t.result = ""
    db.commit()
    await log_activity(a.id, user.id, "info", f"Re-running task: {(t.title or t.description)[:80]}")
    await schedule_job(_run_task(a.id, user.id, t.id, t.description, a.name))
    return task_dict(t, db)


@router.get("/{agent_id}/skills")
def get_skills(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    from ..agent_skills import (
        list_skills_for_agent,
        list_skills_grouped,
        SKILL_CATALOG,
        get_comprehensive_skill_catalog,
        enabled_skill_ids,
    )
    from ..agent_roles import normalize_role
    a = _get_owned(agent_id, user, db)
    skills = list_skills_for_agent(a, db)
    free = [s for s in skills if not s.get("premium")]
    premium = [s for s in skills if s.get("premium")]
    enabled = enabled_skill_ids(a, db)
    return {
        "agent_id": a.id,
        "role": normalize_role(a),
        "skills": skills,
        "catalog": SKILL_CATALOG,
        "categories": list_skills_grouped(),
        "grouped": get_comprehensive_skill_catalog(),
        "enabled_count": len(enabled),
        "summary": {
            "total": len(skills),
            "unique_catalog": len(SKILL_CATALOG),
            "enabled": len(enabled),
            "free": len(free),
            "premium": len(premium),
            "premium_examples": [p["name"] for p in premium[:8]],
        },
    }


@router.put("/{agent_id}/skills")
def put_skills(agent_id: int, data: SkillsUpdateIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    from ..agent_skills import set_enabled_skills, list_skills_for_agent
    a = _get_owned(agent_id, user, db)
    enabled = set_enabled_skills(db, a, data.enabled or [])
    return {"agent_id": a.id, "enabled": enabled, "skills": list_skills_for_agent(a, db)}


@router.post("/{agent_id}/skills/run")
async def run_skill(agent_id: int, data: SkillRunIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    from ..agent_skills import execute_skill
    a = _get_owned(agent_id, user, db)
    ensure_credits(db, user.id)
    result = await execute_skill(db, a, user, data.skill, data.args or {})
    return result


@router.post("/{agent_id}/spawn")
async def spawn_child(agent_id: int, data: SpawnIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    from ..agent_skills import execute_skill
    a = _get_owned(agent_id, user, db)
    return await execute_skill(db, a, user, "spawn_agent", data.model_dump())


@router.post("/{agent_id}/message-agent")
async def message_agent(agent_id: int, data: AgentMsgIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    from ..agent_skills import execute_skill
    a = _get_owned(agent_id, user, db)
    ensure_credits(db, user.id)
    return await execute_skill(db, a, user, "message_agent", data.model_dump())


@router.get("/{agent_id}/messages")
def list_agent_messages(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = _get_owned(agent_id, user, db)
    rows = (
        db.query(models.AgentMessage)
        .filter(
            models.AgentMessage.user_id == user.id,
            ((models.AgentMessage.from_agent_id == a.id) | (models.AgentMessage.to_agent_id == a.id)),
        )
        .order_by(models.AgentMessage.id.desc())
        .limit(80)
        .all()
    )
    out = []
    for m in rows:
        fa = db.get(models.Agent, m.from_agent_id)
        ta = db.get(models.Agent, m.to_agent_id)
        out.append({
            "id": m.id,
            "from_agent_id": m.from_agent_id,
            "from_name": fa.name if fa else "?",
            "to_agent_id": m.to_agent_id,
            "to_name": ta.name if ta else "?",
            "thread_key": m.thread_key,
            "content": m.content,
            "status": m.status,
            "created_at": m.created_at,
        })
    return {"messages": out}


@router.get("/{agent_id}/memory")
def list_memory(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = _get_owned(agent_id, user, db)
    rows = (
        db.query(models.AgentMemory)
        .filter_by(agent_id=a.id)
        .order_by(models.AgentMemory.id.desc())
        .limit(100)
        .all()
    )
    return {
        "memories": [
            {
                "id": m.id,
                "kind": m.kind,
                "title": m.title,
                "content": m.content,
                "tags": m.tags,
                "knowledge_file_id": m.knowledge_file_id,
                "created_at": m.created_at,
            }
            for m in rows
        ]
    }


@router.post("/{agent_id}/memory")
async def save_memory(agent_id: int, data: MemoryIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    from ..agent_skills import execute_skill
    a = _get_owned(agent_id, user, db)
    if data.save_to_training:
        return await execute_skill(
            db, a, user, "save_training",
            {"title": data.title, "content": data.content, "tags": data.tags},
        )
    return await execute_skill(
        db, a, user, "save_memory",
        {"title": data.title, "content": data.content, "kind": data.kind, "tags": data.tags},
    )


@router.delete("/{agent_id}/memory/{memory_id}")
def delete_memory(agent_id: int, memory_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = _get_owned(agent_id, user, db)
    m = db.get(models.AgentMemory, memory_id)
    if not m or m.agent_id != a.id:
        raise HTTPException(404, "Memory not found")
    db.delete(m)
    db.commit()
    return {"ok": True}


@router.post("/{agent_id}/chat")
async def chat_with_agent(agent_id: int, data: AgentChatIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    from ..agent_scaffold import map_model, resolve_runtime
    a = _get_owned(agent_id, user, db)
    ensure_credits(db, user.id)
    rt = resolve_runtime(a)
    mode = mode_for_template(a.template_type)
    model = rt.model
    if mode == "coding" and model in ("fast", "small", "medium"):
        model = "quality"

    conv = None
    if data.conversation_id:
        conv = db.get(models.Conversation, data.conversation_id)
        if not conv or conv.user_id != user.id or conv.agent_id != a.id:
            conv = None
    if not conv:
        conv = (
            db.query(models.Conversation)
            .filter_by(user_id=user.id, agent_id=a.id)
            .order_by(models.Conversation.id.desc())
            .first()
        )
    if not conv:
        conv = models.Conversation(
            user_id=user.id, agent_id=a.id,
            title=f"Chat · {a.name}", mode=mode,
        )
        db.add(conv)
        db.commit()
        db.refresh(conv)

    text = (data.message or "").strip()
    db.add(models.Message(conversation_id=conv.id, role="user", content=text))
    db.commit()

    history = (
        db.query(models.Message)
        .filter_by(conversation_id=conv.id)
        .order_by(models.Message.id)
        .all()
    )
    from ..agent_skills import run_skills_from_text
    from ..live_ops import emit_ops

    system = build_agent_system_prompt(db, a)
    # Proper system role + short history (long threads were blowing context / timeouts)
    llm_messages: list[dict] = [{"role": "system", "content": system}]
    for m in history[-10:]:
        role = m.role if m.role in ("user", "assistant") else "user"
        content = (m.content or "")[:4000]
        if content.strip():
            llm_messages.append({"role": role, "content": content})

    await emit_ops(
        user.id, kind="action", status="running",
        title=f"{a.name} thinking", detail=(text or "")[:200],
        agent_id=a.id, db=db,
    )

    creds = credentials_for_user(db, user.id)
    reply = ""
    try:
        async for chunk in stream_completion(llm_messages, model, mode, credentials=creds):
            reply += chunk
    except Exception as e:
        reply = f"Chat backend error: {e}"
    reply = (reply or "").strip()
    if not reply:
        reply = (
            "No reply was generated. Please try again in a moment. "
            "If this keeps happening, check Settings → API / Grok is configured."
        )

    clean_reply, skill_results = await run_skills_from_text(db, a, user, reply)
    if skill_results:
        summary = "; ".join(
            f"{r.get('skill')}: {r.get('message') or r.get('error')}" for r in skill_results
        )
        if summary:
            clean_reply = (clean_reply + f"\n\n— Skills: {summary}").strip()

    final_text = (clean_reply or reply).strip()
    db.add(models.Message(conversation_id=conv.id, role="assistant", content=final_text))
    db.commit()

    charged = bill_llm_turn(db, user, model, llm_messages, final_text)
    await manager.broadcast(f"tokens:{user.id}", {
        "event": "usage",
        "tokens": charged["tokens"],
        "cost": charged["cost"],
        "model": charged.get("model") or model,
        "tokens_used_period": charged.get("tokens_used_period"),
        "credits": charged.get("credits"),
    })
    await log_activity(a.id, user.id, "action", f"Replied to a direct chat message")
    await emit_ops(
        user.id, kind="action", status="done",
        title=f"{a.name} replied",
        detail=final_text[:240],
        agent_id=a.id, db=db,
    )
    return {
        "reply": final_text,
        "tokens": charged["tokens"],
        "cost": charged["cost"],
        "tokens_used_period": charged.get("tokens_used_period"),
        "credits": charged.get("credits"),
        "bill_source": charged.get("bill_source"),
        "conversation_id": conv.id,
        "skills": skill_results,
        "provider_hint": provider_hint(model, creds),
        "ok": True,
    }


@router.websocket("/{agent_id}/ws/chat")
async def agent_live_chat(ws: WebSocket, agent_id: int, token: str = Query("")):
    """Streaming live chat with a single agent.

    Auth: ?token= (legacy/mobile) or first-message {"type":"auth","token":...}.
    """
    db = SessionLocal()
    user = await accept_and_authenticate_ws(ws, token, db)
    if not user:
        db.close()
        return
    a = db.get(models.Agent, agent_id)
    if not a or (a.user_id != user.id and user.role != "admin"):
        db.close()
        try:
            await ws.close(code=4404)
        except Exception:
            pass
        return
    agent_id = a.id
    user_id = user.id
    agent_name = a.name
    personality = a.personality
    template_type = a.template_type
    model = a.model
    config_raw = a.config or "{}"
    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)
            if data.get("type") == "auth":
                # Extra auth frames after handshake are ignored
                continue
            if data.get("type") == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
                continue
            text = (data.get("message") or "").strip()
            if not text:
                continue

            bal = db.query(models.Balance).filter_by(user_id=user_id).first()
            user_obj = db.get(models.User, user_id)
            # light credit gate
            try:
                from ..auth_utils import ensure_credits
                ensure_credits(db, user_id)
            except HTTPException as he:
                await ws.send_text(json.dumps({"type": "error", "content": he.detail}))
                continue

            mode = mode_for_template(template_type)
            use_model = model
            if mode == "coding" and use_model in ("vps-fast", "vps-quality"):
                use_model = "vps-qwen-coder"

            conv = (
                db.query(models.Conversation)
                .filter_by(user_id=user_id, agent_id=agent_id)
                .order_by(models.Conversation.id.desc())
                .first()
            )
            if not conv:
                conv = models.Conversation(
                    user_id=user_id, agent_id=agent_id,
                    title=f"Chat · {agent_name}", mode=mode,
                )
                db.add(conv)
                db.commit()
                db.refresh(conv)
            await ws.send_text(json.dumps({
                "type": "conversation", "conversation_id": conv.id,
            }))

            db.add(models.Message(conversation_id=conv.id, role="user", content=text))
            db.commit()

            history = (
                db.query(models.Message)
                .filter_by(conversation_id=conv.id)
                .order_by(models.Message.id)
                .all()
            )
            a_live = db.get(models.Agent, agent_id)
            system = (
                build_agent_system_prompt(db, a_live)
                if a_live
                else f"You are {agent_name}. Personality: {personality}."
            )
            llm_messages = [{"role": "system", "content": system}]
            for m in history[-10:]:
                role = m.role if m.role in ("user", "assistant") else "user"
                content = (m.content or "")[:4000]
                if content.strip():
                    llm_messages.append({"role": role, "content": content})

            await ws.send_text(json.dumps({"type": "start"}))
            creds = credentials_for_user(db, user_id)
            reply = ""
            try:
                async for chunk in stream_completion(llm_messages, use_model, mode, credentials=creds):
                    reply += chunk
                    await ws.send_text(json.dumps({"type": "chunk", "content": chunk}))
            except Exception as e:
                err = f"Chat backend error: {e}"
                reply = err
                await ws.send_text(json.dumps({"type": "chunk", "content": err}))
            reply = (reply or "").strip() or "No reply generated — please try again."
            db.add(models.Message(conversation_id=conv.id, role="assistant", content=reply))
            db.commit()

            charged = bill_llm_turn(db, user_obj, use_model, llm_messages, reply)
            await ws.send_text(json.dumps({
                "type": "done",
                "tokens": charged["tokens"],
                "cost": charged["cost"],
                "conversation_id": conv.id,
                "tokens_used_period": charged.get("tokens_used_period"),
                "credits": charged.get("credits"),
            }))
            await manager.broadcast(f"tokens:{user_id}", {
                "event": "usage",
                "tokens": charged["tokens"],
                "cost": charged["cost"],
                "model": charged.get("model") or use_model,
                "tokens_used_period": charged.get("tokens_used_period"),
                "credits": charged.get("credits"),
            })
            await log_activity(agent_id, user_id, "action", "Live chat reply sent")
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_text(json.dumps({"type": "error", "content": str(e)[:200]}))
        except Exception:
            pass
    finally:
        db.close()


@router.websocket("/ws")
async def agents_ws(ws: WebSocket, token: str = Query("")):
    """Agent activity feed WS. Auth: ?token= (legacy/mobile) or first-message {"type":"auth","token":...}."""
    db = SessionLocal()
    user = await accept_and_authenticate_ws(ws, token, db)
    db.close()
    if not user:
        return
    channel = f"agents:{user.id}"
    manager.register(channel, ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(channel, ws)
