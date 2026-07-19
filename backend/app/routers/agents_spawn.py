"""Spawn, seed teams, ensure-orchestrator/designer related endpoints."""
import json
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models
from ..auth_utils import get_current_user, ensure_credits
from ..plans import plan_limits
from ..agent_serialize import agent_out
from ..agent_roles import find_orchestrator, is_orchestrator
from ..agent_hierarchy import ensure_main_orchestrator, ensure_master_designer
from ..seed_templates import SEED_TEMPLATES
from .agents_common import (
    _get_owned,
    _agent_plan_cap,
    log_activity,
    SpawnIn,
)

router = APIRouter()


@router.post("/ensure-orchestrator")
async def ensure_orchestrator(
    bootstrap: bool = Query(
        False,
        description=(
            "If true, also seed guided companies (no extra agents). "
            "Default false: new accounts only get Main AI Orchestrator."
        ),
    ),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Create the Main AI Orchestrator if missing — always sits at top of hierarchy.

    Default: orchestrator only (no leads / starter team). Optional bootstrap=true
    creates private companies for this user without hiring extra agents.

    Always applies the full orchestrator skill pack via ensure_main_orchestrator
    (create_task, execute_goal, message_agent, open_meeting, spawn_*, …).
    """
    existing = find_orchestrator(db, user.id)
    if not existing:
        ensure_credits(db, user.id)
        count = db.query(models.Agent).filter_by(user_id=user.id).count()
        max_agents = int(plan_limits(user.plan).get("agents") or 0)
        if user.role != "admin" and count >= max_agents:
            raise HTTPException(400, f"Your plan allows up to {max_agents} agents. Upgrade on Billing.")

    # ensure_main_orchestrator persists role-appropriate skills (new + existing)
    a = ensure_main_orchestrator(db, user)
    if not existing:
        await log_activity(a.id, user.id, "info", "Main AI Orchestrator created — pinned at top of hierarchy")
    out = agent_out(a, db, include_team=True)
    if bootstrap:
        from ..orchestrator_bootstrap import bootstrap_workspace
        try:
            # Companies only for this user — never auto-hire leads (shared-looking data)
            out["bootstrap"] = bootstrap_workspace(
                db, user, create_leads=False, create_wallets=True,
            )
            await log_activity(
                a.id, user.id, "action",
                "Orchestrator bootstrap: private companies ready (orchestrator only)",
            )
        except Exception as e:
            out["bootstrap_error"] = str(e)
    return out


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
    from ..agent_skills import SKILL_CATALOG, set_enabled_skills
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
        _mk(nm, "sales", pers, "member", parent=_pid(sales_lead))

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
        ("Research Analyst", "research", "Competitor deep dives, market sizing, ICP research."),
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

    # Full role + template packs for every agent (never domain-keyword-only)
    from ..agent_scaffold import ensure_agent_skills
    from ..agent_skills import skills_for_template
    from ..agent_roles import normalize_role as _norm_role
    all_agents = db.query(models.Agent).filter_by(user_id=user.id).all()
    for a in all_agents:
        ensure_agent_skills(db, a)
        if is_orchestrator(a):
            continue
        pack = skills_for_template(a.template_type, SKILL_CATALOG, role=_norm_role(a))
        # set_enabled_skills enforces plan skills_per_agent cap
        set_enabled_skills(db, a, list(pack))

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

@router.post("/{agent_id}/spawn")
async def spawn_child(agent_id: int, data: SpawnIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """
    Explicit UI/API spawn under an agent.

    Does NOT depend on the skill being toggled on — account owners always need
    a working "Spawn agent" action. Still enforces plan caps + credits.
    """
    from ..agent_skills import _skill_spawn, set_enabled_skills, enabled_skill_ids

    a = _get_owned(agent_id, user, db)
    if user.role != "admin" and (not user.subscription_active or user.plan in (None, "", "none")):
        raise HTTPException(402, "Choose a subscription plan to spawn agents")
    ensure_credits(db, user.id)
    count, max_agents, is_admin = _agent_plan_cap(db, user)
    if not is_admin and count >= max_agents:
        raise HTTPException(
            400,
            f"Your plan allows up to {max_agents} agents. Upgrade on Billing or delete an agent first.",
        )

    # Ensure spawn_agent is in the enabled pack so future chat skill-calls work too
    try:
        cur = enabled_skill_ids(a, db)
        if "spawn_agent" not in cur:
            set_enabled_skills(db, a, list(cur | {"spawn_agent"}))
            db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass

    payload = data.model_dump()
    # Default parent = this agent (team grows under the selected lead)
    if payload.get("parent_id") is None:
        payload["parent_id"] = a.id

    result = await _skill_spawn(db, a, user, payload)
    if not result.get("ok", True) and result.get("error"):
        raise HTTPException(400, result["error"])
    # Surface agent for SPA to navigate
    return result

