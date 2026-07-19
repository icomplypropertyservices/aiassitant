"""
Skills policy: categories, role default packs, integration gates, catalog hygiene.

Keeps product rules out of the giant execute_skill chain.
"""
from __future__ import annotations

from typing import Any

# ── Categories (for Admin / Settings UI) ────────────────────────────────────

CATEGORY_ORDER = [
    "core",
    "crm",
    "comms",
    "google",
    "sales",
    "support",
    "content",
    "code",
    "data",
    "finance",
    "hr",
    "legal",
    "design",
    "social",
    "commerce",
    "automation",
    "ops",
    "media",
    "meta",
    "other",
]

CATEGORY_LABELS = {
    "core": "Core ops",
    "crm": "CRM & diary",
    "comms": "Communication",
    "google": "Google",
    "sales": "Sales",
    "support": "Support",
    "content": "Content & marketing",
    "code": "Engineering",
    "data": "Data & analytics",
    "finance": "Finance",
    "hr": "HR",
    "legal": "Legal & risk",
    "design": "Design & brand",
    "social": "Social (live)",
    "commerce": "Commerce",
    "automation": "Automation & integrations",
    "ops": "Ops & process",
    "media": "Media (premium)",
    "meta": "Team factory / meta",
    "other": "Other",
}

# Prefix → category (first match wins, longest prefixes first when sorting)
_PREFIX_CATEGORY: list[tuple[str, str]] = [
    ("facebook_", "social"),
    ("instagram_", "social"),
    ("linkedin_", "social"),
    ("whatsapp_", "comms"),
    ("mailchimp_", "content"),
    ("calendar_", "google"),
    ("shopify_", "commerce"),
    ("hubspot_", "commerce"),
    ("notion_", "automation"),
    ("discord_", "social"),
    ("dropbox_", "automation"),
    ("gmail_", "google"),
    ("sheets_", "google"),
    ("slack_", "comms"),
    ("email_", "comms"),
    ("x_", "social"),
    # Mega packs (1000 skills)
    ("sales_", "sales"),
    ("mkt_", "content"),
    ("cs_", "support"),
    ("sup_", "support"),
    ("fin_", "finance"),
    ("leg_", "legal"),
    ("hr_", "hr"),
    ("ops_", "ops"),
    ("prd_", "ops"),
    ("eng_", "code"),
    ("dat_", "data"),
    ("cnt_", "content"),
    ("soc_", "social"),
    ("pm_", "ops"),
    ("prc_", "commerce"),
    ("log_", "ops"),
    ("re_", "ops"),
    ("hc_", "ops"),
    ("edu_", "hr"),
    ("exec_", "ops"),
]

_ID_CATEGORY: dict[str, str] = {
    # core
    "spawn_agent": "meta",
    "message_agent": "core",
    "use_app": "automation",
    "assign_human": "core",
    "save_memory": "core",
    "save_training": "core",
    "create_task": "core",
    "execute_goal": "core",
    "announce_plan": "core",
    "set_agent_status": "meta",
    "create_reminder": "ops",
    "list_team": "meta",
    "pause_agent": "meta",
    "resume_agent": "meta",
    "delete_agent": "meta",
    "spawn_team": "meta",
    "spawn_specialist": "meta",
    "clone_agent": "meta",
    "enable_skills_on": "meta",
    "bulk_enable_skills": "meta",
    "configure_agent": "meta",
    "promote_to_lead": "meta",
    "skill_recommend": "meta",
    "agent_compare": "meta",
    # crm
    "list_customers": "crm",
    "get_customer": "crm",
    "update_customer": "crm",
    "log_customer_activity": "crm",
    "create_deal": "crm",
    "schedule_meeting": "crm",
    "list_diary": "crm",
    "list_pipelines": "crm",
    "get_pipeline": "crm",
    "list_pipeline_stages": "crm",
    "move_deal": "crm",
    "win_deal": "crm",
    "lose_deal": "crm",
    "pipeline_summary": "crm",
    "ensure_sales_pipeline": "crm",
    "list_tasks": "ops",
    "get_task": "ops",
    "list_meetings": "ops",
    "list_humans": "core",
    "list_deals": "crm",
    "read_workspace": "ops",
    "comment": "core",
    "create_skill": "meta",
    "list_created_skills": "meta",
    "publish_skill_to_bay": "meta",
    "unpublish_skill_from_bay": "meta",
    "share_skill": "meta",
    "update_pipeline": "crm",
    # meeting rooms (multi-agent brainstorm / war-room)
    "open_meeting": "ops",
    "post_to_meeting": "ops",
    "run_meeting_round": "ops",
    "close_meeting": "ops",
    "extract_meeting_tasks": "ops",
    # comms free
    "draft_email": "comms",
    "draft_sms": "comms",
    "log_communication": "comms",
    "send_email": "comms",
    "send_sms": "comms",
    "send_whatsapp": "comms",
    "make_voice_call": "comms",
    "send_message": "comms",
    # media
    "generate_image": "media",
    "generate_video": "media",
    # content / research
    "generate_content": "content",
    "research": "content",
    "summarize": "content",
    "get_time": "ops",
    "suggest_times": "ops",
    # business
    "create_invoice_draft": "finance",
    "escalate_to_human": "support",
    "search_memory": "core",
    "search_knowledge": "core",
}


def category_for(skill_id: str) -> str:
    sid = (skill_id or "").strip()
    if sid in _ID_CATEGORY:
        return _ID_CATEGORY[sid]
    for prefix, cat in sorted(_PREFIX_CATEGORY, key=lambda x: -len(x[0])):
        if sid.startswith(prefix):
            return cat
    # heuristic by keyword
    if any(k in sid for k in ("sales", "lead", "proposal", "outreach", "upsell", "close_", "qualify", "cold_")):
        return "sales"
    if any(k in sid for k in ("ticket", "support", "refund", "churn", "sla", "onboarding", "triage", "cancel")):
        return "support"
    if any(k in sid for k in ("code", "api", "docker", "sql", "debug", "refactor", "test", "ci_", "sdk", "openapi", "load_test", "tech_debt", "architecture")):
        return "code"
    if any(k in sid for k in ("seo", "content", "newsletter", "ad_copy", "calendar", "landing", "webinar", "influencer", "twitter", "linkedin_write", "video_script", "case_study")):
        return "content"
    if any(k in sid for k in ("invoice", "payment", "expense", "cashflow", "pricing", "tax", "forecast", "subscription_health")):
        return "finance"
    if any(k in sid for k in ("job_", "interview", "cv_", "hr", "onboarding_plan", "performance", "morale", "offer_letter", "sourcing")):
        return "hr"
    if any(k in sid for k in ("gdpr", "contract", "legal", "risk", "policy", "incident", "dpa")):
        return "legal"
    if any(k in sid for k in ("brand", "logo", "ui_copy", "design", "illustration", "pitch_deck", "social_asset")):
        return "design"
    if any(k in sid for k in ("metric", "cohort", "funnel", "anomaly", "experiment", "dashboard", "report", "analyze")):
        return "data"
    if any(k in sid for k in ("webhook", "etl", "oauth", "cron", "zapier", "sync_")):
        return "automation"
    if any(k in sid for k in ("standup", "review", "runbook", "okr", "status_", "process", "checklist", "meeting", "weekly", "autonomy", "training", "lesson", "reflect")):
        return "ops"
    return "other"


# ── Integration skill → app_id (for coming_soon / not-connected gates) ──────

# skill_id or prefix → integration app_id
_SKILL_APP_EXACT: dict[str, str] = {
    "use_app": "",  # resolved from args at runtime
    "gmail_send": "gmail",
    "gmail_reply": "gmail",
    "gmail_draft": "gmail",
    "gmail_list": "gmail",
    "gmail_get_thread": "gmail",
    "gmail_search": "gmail",
    "gmail_archive": "gmail",
    "email_send": "gmail",
    "email_reply": "gmail",
}

_SKILL_APP_PREFIX: list[tuple[str, str]] = [
    ("gmail_", "gmail"),
    ("sheets_", "google_sheets"),
    ("calendar_", "google"),
    ("facebook_", "meta"),
    ("instagram_", "instagram"),
    ("linkedin_", "linkedin"),
    ("x_", "x"),
    ("slack_", "slack"),
    ("shopify_", "shopify"),
    ("hubspot_", "hubspot"),
    ("notion_", "notion"),
    ("discord_", "discord"),
    ("whatsapp_", "meta"),  # often Meta Cloud API; treat as coming_soon with meta
    ("mailchimp_", "mailchimp"),
    ("dropbox_", "dropbox"),
]


def required_app_for_skill(skill_id: str, args: dict | None = None) -> str | None:
    """Return integration app_id required for this skill, or None if internal."""
    sid = (skill_id or "").strip()
    if sid == "use_app":
        a = args or {}
        app = a.get("app_id") or a.get("app") or a.get("application") or a.get("integration")
        return str(app).strip().lower() if app not in (None, "") else None
    if sid in _SKILL_APP_EXACT:
        return _SKILL_APP_EXACT[sid] or None
    for prefix, app_id in sorted(_SKILL_APP_PREFIX, key=lambda x: -len(x[0])):
        if sid.startswith(prefix):
            return app_id
    return None


def integration_skill_available(
    skill_id: str,
    user_id: int,
    db,
    args: dict | None = None,
) -> tuple[bool, str]:
    """
    Gate integration skills: block if app is coming_soon or user has no connection.
    Returns (ok, error_message).
    """
    app_id = required_app_for_skill(skill_id, args)
    if not app_id:
        return True, ""

    # Numeric app_id is almost always a mistaken connection primary key
    if str(app_id).isdigit():
        return (
            False,
            f"app_id '{app_id}' looks like a connection id. "
            "Pass the app key string (gmail, slack, shopify, hubspot, …).",
        )

    try:
        from .integrations_catalog import get_app, GOOGLE_FAMILY
    except Exception:
        return True, ""

    app = get_app(app_id)
    if not app:
        return (
            False,
            f"Unknown app '{app_id}' for skill '{skill_id}'. "
            "Use a catalog app key (gmail, slack, shopify, …), not a numeric id.",
        )

    is_google = app_id in GOOGLE_FAMILY or app.get("family") == "google"
    coming = bool(app.get("coming_soon")) if "coming_soon" in app else (not is_google)
    if coming and not is_google:
        return (
            False,
            f"{app.get('name') or app_id} is coming soon. "
            "Use Google 1-click apps for now, or wait for this integration.",
        )

    try:
        from . import models
        row = (
            db.query(models.IntegrationConnection)
            .filter_by(user_id=user_id, app_id=app_id, status="connected")
            .first()
        )
        # Calendar skills map to app "google" — any Google-family connection can unlock calendar
        if not row and app_id == "google":
            row = (
                db.query(models.IntegrationConnection)
                .filter(
                    models.IntegrationConnection.user_id == user_id,
                    models.IntegrationConnection.status == "connected",
                    models.IntegrationConnection.app_id.in_(list(GOOGLE_FAMILY)),
                )
                .first()
            )
        if not row:
            return (
                False,
                f"Connect {app.get('name') or app_id} in Settings → Connected apps "
                f"before using '{skill_id}'.",
            )
    except Exception as e:
        return False, f"Could not verify app connection: {e}"

    return True, ""


# ── Role default packs ──────────────────────────────────────────────────────

# Destructive / factory skills — orchestrator (and sometimes lead) only via roles;
# also excluded from member/specialist defaults even if role list is wide.
_META_DANGEROUS = frozenset({
    "delete_agent",
    "promote_to_lead",
    "pause_agent",
    "resume_agent",
    "bulk_enable_skills",
    "enable_skills_on",
    "configure_agent",
    "clone_agent",
    "spawn_team",
})

# Core free pack for every role — read + comment across the workspace
_CORE_ALWAYS = frozenset({
    "message_agent",
    "save_memory",
    "save_training",
    "create_task",
    "execute_goal",
    "announce_plan",
    "list_customers",
    "get_customer",
    "log_customer_activity",
    "list_diary",
    "list_pipelines",
    "get_pipeline",
    "list_pipeline_stages",
    "list_deals",
    "create_deal",
    "move_deal",
    "win_deal",
    "lose_deal",
    "update_pipeline",
    "pipeline_summary",
    "ensure_sales_pipeline",
    "list_tasks",
    "get_task",
    "list_meetings",
    "list_humans",
    "read_workspace",
    "comment",
    "draft_email",
    "draft_sms",
    "log_communication",
    "generate_content",
    "research",
    "summarize",
    "get_time",
    "suggest_times",
    "search_memory",
    "search_knowledge",
    "create_reminder",
    "list_team",
    "weekly_review",
    "status_update",
    "notify_human",
    "action_items",
    "meeting_agenda",
    "prioritize_list",
    # multi-agent meeting rooms
    "open_meeting",
    "post_to_meeting",
    "run_meeting_round",
    "close_meeting",
    "extract_meeting_tasks",
    # Agents invent skills + optional AgentBay listing
    "create_skill",
    "list_created_skills",
    "publish_skill_to_bay",
    "share_skill",
})

# Mega domain packs (20×50) — stay in SKILL_CATALOG for search/opt-in, never default-on.
_MEGA_ID_PREFIXES = (
    "sales_",
    "mkt_",
    "cs_",
    "sup_",
    "fin_",
    "leg_",
    "hr_",
    "ops_",
    "prd_",
    "eng_",
    "dat_",
    "cnt_",
    "soc_",
    "pm_",
    "prc_",
    "log_",
    "re_",
    "hc_",
    "edu_",
    "exec_",
)

# Free LLM content packs (non-mega) — layered by skills_for_template domain packs, not
# auto-enabled on every member. Keeps DEFAULT_ENABLED lean (<150).
_FREE_CONTENT_CATEGORIES = frozenset({
    "sales",
    "support",
    "content",
    "code",
    "data",
    "finance",
    "hr",
    "legal",
    "design",
})


def is_mega_catalog_skill(skill: dict | str) -> bool:
    """True for domain mega-pack entries (catalog_deliverable / pack field / id prefix).

    Prefer handler/pack metadata from load_mega_skills(). Prefix fallback is for
    bare skill ids only and never treats _CORE_ALWAYS ids as mega (e.g. log_*).
    """
    if isinstance(skill, dict):
        if skill.get("handler") == "catalog_deliverable":
            return True
        if skill.get("pack"):
            return True
        sid = str(skill.get("id") or "")
    else:
        sid = str(skill or "")
    if not sid or sid in _CORE_ALWAYS:
        return False
    # Prefix fallback for id-only checks (logistics uses log_*; core log_* is excluded above)
    return sid.startswith(_MEGA_ID_PREFIXES)


def premium_skill_ids(catalog: list[dict]) -> frozenset[str]:
    return frozenset(s["id"] for s in catalog if s.get("premium"))


# ── template_type → skill pack ──────────────────────────────────────────────
# Canonical packs for spawn / seed / bulk_enable. Always union with core free
# skills so agents never get domain-keyword-only partial sets.

SKILL_PACKS = (
    "sales",
    "marketing",
    "support",
    "coding",
    "research",
    "orchestrator",
    "lead",
    "full",
)

_TEMPLATE_TO_PACK: dict[str, str] = {
    # sales
    "sales": "sales",
    "outreach": "sales",
    "sdr": "sales",
    "ae": "sales",
    "pipeline": "sales",
    "lead_qualifier": "sales",
    "qualifier": "sales",
    # marketing / content
    "marketing": "marketing",
    "content": "marketing",
    "growth": "marketing",
    "seo": "marketing",
    "social": "marketing",
    "brand": "marketing",
    "designer": "marketing",
    # support
    "support": "support",
    "customer": "support",
    "success": "support",
    "cx": "support",
    "reviews": "support",
    "cs": "support",
    # coding / eng
    "coding": "coding",
    "code": "coding",
    "engineer": "coding",
    "engineering": "coding",
    "developer": "coding",
    "dev": "coding",
    "qa": "coding",
    "devops": "coding",
    # research / analysis
    "research": "research",
    "analyst": "research",
    "analysis": "research",
    "data": "research",
    # hierarchy
    "orchestrator": "orchestrator",
    "staff_orchestrator": "orchestrator",
    "lead": "lead",
    "manager": "lead",
}

# Substring tokens matched against skill id for domain packs.
_PACK_KEYWORDS: dict[str, tuple[str, ...]] = {
    "sales": (
        "sales", "lead", "proposal", "outreach", "cold", "book_meeting", "qualif",
        "close", "churn", "upsell", "deal", "pipeline", "objection", "follow_up",
        "pricing", "qbr", "enrich_lead", "customer", "invoice", "payment",
        "hubspot", "draft_email", "draft_sms", "send_email", "send_sms",
    ),
    "marketing": (
        "content", "linkedin", "twitter", "ad_", "ad_copy", "newsletter", "seo",
        "video", "script", "blog", "landing", "influencer", "referral", "webinar",
        "brand", "social", "generate_content", "mailchimp", "facebook", "instagram",
        "x_post", "x_reply", "illustration", "ui_copy", "case_study", "sms_campaign",
    ),
    "support": (
        "support", "ticket", "triage", "refund", "escalat", "onboard", "knowledge",
        "health", "cancel", "sla", "success", "complaint", "customer", "diary",
        "schedule_meeting", "draft_email", "draft_sms", "send_email", "send_sms",
    ),
    "coding": (
        "code", "api", "test", "debug", "refactor", "docker", "ci_", "migration",
        "review", "arch", "sql", "sdk", "openapi", "load_test", "tech_debt",
        "feature_flag", "write_api", "write_tests", "database", "etl", "oauth",
        "cron", "sync_", "webhook",
    ),
    "research": (
        "research", "summarize", "analy", "competitor", "cohort", "funnel",
        "experiment", "forecast", "metric", "report", "enrich", "battlecard",
        "dashboard", "anomaly", "search_knowledge", "search_memory", "generate_report",
    ),
    "lead": (
        "spawn", "list_team", "message_agent", "create_task", "execute_goal",
        "announce_plan", "configure", "enable_skills", "promote", "status",
        "weekly", "okr", "prioritize", "meeting", "action_items", "decision",
        "standup", "runbook",
    ),
    "orchestrator": (),  # full catalog via pack handler
}


def skill_pack_for_template(template_type: str | None) -> str:
    """Map agent template_type → canonical skill pack name (or \"\" if generic)."""
    t = (template_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not t:
        return ""
    if t in ("full", "all"):
        return "full"
    if t in SKILL_PACKS:
        return t
    if t in _TEMPLATE_TO_PACK:
        return _TEMPLATE_TO_PACK[t]
    # preset aliases used by bulk_enable / spawn_team enable_preset
    if t in ("engineering", "eng"):
        return "coding"
    if t in ("comms", "communication"):
        return "sales"
    for key, pack in _TEMPLATE_TO_PACK.items():
        if key in t or t.startswith(key):
            return pack
    return ""


def _matches_pack_keywords(skill_id: str, pack: str) -> bool:
    keys = _PACK_KEYWORDS.get(pack) or ()
    if not keys:
        return False
    sid = skill_id or ""
    return any(k in sid for k in keys)


def _filter_live_sends_for_member(skill_id: str) -> bool:
    """False if live integration send/post should stay off for member/specialist defaults."""
    app = required_app_for_skill(skill_id)
    if not app:
        return True
    if skill_id.startswith((
        "facebook_", "instagram_", "linkedin_post", "linkedin_comment",
        "x_post", "x_reply", "slack_post", "slack_dm", "shopify_",
        "hubspot_", "gmail_send", "gmail_reply", "whatsapp_", "discord_",
        "email_send", "email_reply",
    )):
        if any(x in skill_id for x in (
            "_list", "_get", "_search", "_read", "draft", "sheets_read", "calendar_list",
        )):
            return True
        return False
    return True


def role_matches_skill(agent_role: str, skill_roles: list | None) -> bool:
    """Whether hierarchy_role may use a skill's roles list.

    specialist inherits member skill access (same free toolkit pack).
    orchestrator may use any skill.
    """
    r = (agent_role or "member").lower()
    if r == "orchestrator":
        return True
    roles = list(skill_roles or [])
    if r in roles:
        return True
    if r == "specialist" and "member" in roles:
        return True
    return False


def skills_for_pack(
    pack: str,
    catalog: list[dict],
    *,
    role: str = "member",
    include_premium: bool | None = None,
) -> list[str]:
    """
    Build a complete skill id list for a named pack.

    Always includes core free skills (when role allows) so spawns never enable
    only a partial keyword slice of the domain.
    """
    pack = (pack or "").strip().lower()
    role = (role or "member").lower()
    by_id = {s["id"]: s for s in catalog}
    premium = premium_skill_ids(catalog)
    if include_premium is None:
        include_premium = role in ("lead", "orchestrator")

    # Full / orchestrator → everything the role may use
    if pack in ("full", "all", "orchestrator"):
        if role == "orchestrator" or pack == "orchestrator":
            return list(dict.fromkeys(s["id"] for s in catalog))
        if role == "lead":
            return [s["id"] for s in catalog if s["id"] != "delete_agent"]
        return default_enabled_for_role(role, catalog)

    if pack == "lead":
        use_role = "lead" if role in ("lead", "orchestrator") else role
        base = default_enabled_for_role(use_role if use_role != "orchestrator" else "lead", catalog)
        extra = [
            s["id"] for s in catalog
            if not is_mega_catalog_skill(s)
            and role_matches_skill(use_role if use_role != "member" else "lead", s.get("roles"))
            and (_matches_pack_keywords(s["id"], "lead") or s["id"] in _CORE_ALWAYS)
        ]
        return list(dict.fromkeys([*base, *extra]))

    # Domain packs: role free/premium base + domain keyword hits + core always.
    # Mega 1000-skill dump stays opt-in/search only — templates layer non-mega domain skills.
    use_role = role
    role_base = set(default_enabled_for_role(use_role, catalog))
    domain: list[str] = []
    if pack in _PACK_KEYWORDS:
        for s in catalog:
            sid = s["id"]
            if is_mega_catalog_skill(s):
                continue
            if not _matches_pack_keywords(sid, pack):
                continue
            if not role_matches_skill(use_role, s.get("roles")):
                continue
            if sid in premium and not include_premium:
                continue
            if use_role in ("member", "specialist") and sid in _META_DANGEROUS:
                continue
            if use_role in ("member", "specialist") and not _filter_live_sends_for_member(sid):
                continue
            domain.append(sid)

    out: list[str] = []
    for c in _CORE_ALWAYS:
        if c in by_id and role_matches_skill(use_role, by_id[c].get("roles")):
            if c in premium and not include_premium:
                continue
            out.append(c)
    for sid in role_base:
        if sid not in out:
            out.append(sid)
    for sid in domain:
        if sid not in out:
            out.append(sid)
    return list(dict.fromkeys(out))


def skills_for_template(
    template_type: str | None,
    catalog: list[dict],
    *,
    role: str = "member",
) -> list[str]:
    """Resolve template_type → pack → complete skill id list (never partial-only)."""
    tpl = (template_type or "").strip().lower()
    role = (role or "member").lower()
    pack = skill_pack_for_template(template_type)

    if tpl in ("orchestrator", "staff_orchestrator") or role == "orchestrator":
        return skills_for_pack("orchestrator", catalog, role="orchestrator")

    if tpl in ("lead", "manager") or role == "lead":
        # Lead + domain template (e.g. sales lead) merges lead pack with domain
        if pack and pack not in ("lead", "orchestrator", ""):
            domain = skills_for_pack(pack, catalog, role="lead")
            lead_base = skills_for_pack("lead", catalog, role="lead")
            return list(dict.fromkeys([*lead_base, *domain]))
        return skills_for_pack("lead", catalog, role="lead")

    if pack:
        return skills_for_pack(pack, catalog, role=role)
    return default_enabled_for_role(role, catalog)


def default_enabled_for_role(role: str, catalog: list[dict]) -> list[str]:
    """
    Role-based default skill packs (lean — mega catalog is search/opt-in only).

    - member / specialist: _CORE_ALWAYS + free non-mega toolkit (CRM/comms/ops/integrations).
      No premium, no destructive meta, no live social sends, no ~1000 mega packs,
      no free domain content dumps (those layer via skills_for_template).
    - lead: non-mega free + premium + spawn/configure (not delete); mega still opt-in
    - orchestrator: full catalog including mega (intentional enable surface)
    """
    role = (role or "member").lower()
    by_id = {s["id"]: s for s in catalog}
    catalog_by_id = {s["id"]: s for s in catalog}
    allowed = []
    for s in catalog:
        if role_matches_skill(role, s.get("roles")):
            allowed.append(s["id"])

    premium = premium_skill_ids(catalog)

    if role == "orchestrator":
        # Full catalog for orchestrator (includes mega for intentional full enable)
        out = list(dict.fromkeys(allowed))
        for c in _CORE_ALWAYS:
            if c in by_id and c not in out:
                out.append(c)
        return out

    if role == "lead":
        # Premium yes; mega no (opt-in); delete_agent no
        out = []
        for i in allowed:
            if i == "delete_agent":
                continue
            meta = catalog_by_id.get(i) or {"id": i}
            if is_mega_catalog_skill(meta):
                continue
            out.append(i)
        for c in _CORE_ALWAYS:
            if c in by_id and c not in out and role_matches_skill(role, by_id[c].get("roles")):
                out.append(c)
        return list(dict.fromkeys(out))

    # member + specialist: lean free toolkit — no mega, no free content dumps
    out = []
    for i in allowed:
        meta = catalog_by_id.get(i) or {"id": i}
        if is_mega_catalog_skill(meta):
            continue
        if i in premium:
            continue
        if i in _META_DANGEROUS:
            continue
        if not _filter_live_sends_for_member(i):
            continue
        # Free domain content packs stay opt-in unless in core always
        if i not in _CORE_ALWAYS:
            cat = meta.get("category") or category_for(i)
            if cat in _FREE_CONTENT_CATEGORIES:
                continue
        out.append(i)

    # Ensure core always present when role allows (specialist ≡ member)
    for c in _CORE_ALWAYS:
        if c in by_id and c not in out:
            if role_matches_skill(role, by_id[c].get("roles")):
                out.append(c)

    return list(dict.fromkeys(out))


def ensure_specialist_on_free_skills(raw: list[dict]) -> list[dict]:
    """
    Free skills that already allow `member` should also list `specialist`
    in SKILL_CATALOG.roles (specialists are focused members).
    Premium / lead-only / orch-only left alone.
    """
    out: list[dict] = []
    for s in raw:
        entry = dict(s)
        roles = list(entry.get("roles") or [])
        if (
            not entry.get("premium")
            and "member" in roles
            and "specialist" not in roles
        ):
            mi = roles.index("member")
            roles.insert(mi + 1, "specialist")
            entry["roles"] = roles
        out.append(entry)
    return out


def dedupe_catalog(raw: list[dict]) -> list[dict]:
    """First occurrence wins; inject category; specialist on free member skills."""
    raw = ensure_specialist_on_free_skills(raw)
    seen: set[str] = set()
    out: list[dict] = []
    for s in raw:
        sid = s.get("id")
        if not sid or sid in seen:
            continue
        seen.add(sid)
        entry = dict(s)
        entry["category"] = entry.get("category") or category_for(sid)
        entry["category_label"] = CATEGORY_LABELS.get(entry["category"], entry["category"])
        out.append(entry)
    return out


def group_skills_by_category(catalog: list[dict]) -> list[dict]:
    """[{category, label, skills: [...]}] in CATEGORY_ORDER."""
    buckets: dict[str, list] = {c: [] for c in CATEGORY_ORDER}
    for s in catalog:
        cat = s.get("category") or category_for(s["id"])
        if cat not in buckets:
            buckets[cat] = []
        buckets[cat].append({
            "id": s["id"],
            "name": s.get("name"),
            "description": s.get("description"),
            "premium": bool(s.get("premium")),
            "cost_credits": float(s.get("cost_credits") or 0) if s.get("premium") else 0,
            "roles": s.get("roles") or [],
            "args": s.get("args") or [],
        })
    return [
        {
            "category": c,
            "label": CATEGORY_LABELS.get(c, c),
            "count": len(buckets.get(c) or []),
            "skills": buckets.get(c) or [],
        }
        for c in CATEGORY_ORDER
        if buckets.get(c)
    ]
