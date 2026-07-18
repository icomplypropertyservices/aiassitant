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
    "update_pipeline": "crm",
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
        app = (args or {}).get("app_id") or (args or {}).get("app")
        return str(app).strip().lower() if app else None
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

    try:
        from .integrations_catalog import get_app, GOOGLE_FAMILY
    except Exception:
        return True, ""

    app = get_app(app_id)
    if not app:
        return False, f"Unknown app '{app_id}' for skill '{skill_id}'"

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

# Core free pack for every role
_CORE_ALWAYS = frozenset({
    "message_agent",
    "save_memory",
    "save_training",
    "create_task",
    "announce_plan",
    "list_customers",
    "get_customer",
    "log_customer_activity",
    "list_diary",
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
    "action_items",
    "meeting_agenda",
    "prioritize_list",
})


def premium_skill_ids(catalog: list[dict]) -> frozenset[str]:
    return frozenset(s["id"] for s in catalog if s.get("premium"))


def default_enabled_for_role(role: str, catalog: list[dict]) -> list[str]:
    """
    Role-based default skill packs.

    - member / specialist: free toolkit + draft skills; no premium, no destructive meta
    - lead: + premium + spawn/configure (not delete)
    - orchestrator: full catalog (minus nothing except role filters already on skills)
    """
    role = (role or "member").lower()
    by_id = {s["id"]: s for s in catalog}
    allowed = []
    for s in catalog:
        roles = s.get("roles") or []
        if role == "orchestrator" or role in roles:
            allowed.append(s["id"])
        elif role == "orchestrator":
            allowed.append(s["id"])

    premium = premium_skill_ids(catalog)
    dangerous = _META_DANGEROUS

    if role == "orchestrator":
        return list(dict.fromkeys(allowed))

    if role == "lead":
        # Premium yes; delete_agent no (orchestrator-only in roles usually)
        out = [i for i in allowed if i != "delete_agent"]
        return list(dict.fromkeys(out))

    # member + specialist: no premium, no dangerous meta, no live social send unless in core
    out = []
    for i in allowed:
        if i in premium:
            continue
        if i in dangerous:
            continue
        # Block live integration *send/post* skills for members by default
        # (they can still draft; leads enable premium)
        app = required_app_for_skill(i)
        if app and i.startswith((
            "facebook_", "instagram_", "linkedin_post", "linkedin_comment",
            "x_post", "x_reply", "slack_post", "slack_dm", "shopify_",
            "hubspot_", "gmail_send", "gmail_reply", "whatsapp_", "discord_",
            "email_send", "email_reply",
        )):
            # allow read/list variants for google if free
            if any(x in i for x in ("_list", "_get", "_search", "_read", "draft", "sheets_read", "calendar_list")):
                out.append(i)
            continue
        out.append(i)

    # Ensure core always present when role allows
    for c in _CORE_ALWAYS:
        if c in by_id and c not in out:
            roles = by_id[c].get("roles") or []
            if role in roles or role == "orchestrator":
                out.append(c)

    return list(dict.fromkeys(out))


def dedupe_catalog(raw: list[dict]) -> list[dict]:
    """First occurrence wins; inject category."""
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
