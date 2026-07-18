"""
Company type templates + project/task starter packs for Workspace setup.

- Company types (trades, agency, personal, …)
- Each type can seed projects and starter tasks
- Universal TASK_TEMPLATES available for any project ("task options for all")
"""

# ── Universal task options (available on every project) ─────────────────────

TASK_TEMPLATES = [
    {
        "id": "daily_standup",
        "name": "Daily standup summary",
        "title": "Daily standup",
        "description": "Summarise priorities for today, blockers, and who owns what. Keep it under 10 bullets.",
        "priority": "medium",
        "for_all": True,
    },
    {
        "id": "weekly_review",
        "name": "Weekly review",
        "title": "Weekly review",
        "description": "Review last week: wins, misses, metrics, and top 3 priorities for next week.",
        "priority": "medium",
        "for_all": True,
    },
    {
        "id": "inbox_triage",
        "name": "Inbox triage",
        "title": "Triage inbox",
        "description": "Sort pending messages into: reply now, schedule, delegate, archive. Draft replies for urgent items.",
        "priority": "high",
        "for_all": True,
    },
    {
        "id": "follow_ups",
        "name": "Follow-ups list",
        "title": "Chase follow-ups",
        "description": "List open follow-ups older than 48h and draft short chase messages.",
        "priority": "high",
        "for_all": True,
    },
    {
        "id": "content_draft",
        "name": "Content draft",
        "title": "Draft content piece",
        "description": "Write a short post or email (goal, audience, CTA). Offer 2 tone variants.",
        "priority": "medium",
        "for_all": True,
    },
    {
        "id": "research_brief",
        "name": "Research brief",
        "title": "Research brief",
        "description": "Research the topic and produce a 1-page brief with sources/assumptions.",
        "priority": "medium",
        "for_all": True,
    },
    {
        "id": "checklist",
        "name": "Process checklist",
        "title": "Build checklist",
        "description": "Create a step-by-step checklist for a recurring process so nothing is missed.",
        "priority": "low",
        "for_all": True,
    },
    {
        "id": "meeting_prep",
        "name": "Meeting prep",
        "title": "Prep for meeting",
        "description": "Agenda, goals, questions to ask, and a 5-bullet brief for attendees.",
        "priority": "medium",
        "for_all": True,
    },
    {
        "id": "status_report",
        "name": "Status report",
        "title": "Write status report",
        "description": "Clear status for stakeholders: progress, risks, decisions needed, next steps.",
        "priority": "medium",
        "for_all": True,
    },
    {
        "id": "ideas_backlog",
        "name": "Ideas backlog",
        "title": "Capture ideas backlog",
        "description": "Brainstorm and prioritise 10 ideas (impact × effort). Pick top 3 to execute.",
        "priority": "low",
        "for_all": True,
    },
]


def _tasks(*ids: str) -> list[dict]:
    by_id = {t["id"]: t for t in TASK_TEMPLATES}
    out = []
    for i in ids:
        if i in by_id:
            out.append(by_id[i])
    return out


# ── Company type templates ──────────────────────────────────────────────────

COMPANY_TEMPLATES = [
    {
        "id": "personal",
        "name": "Personal",
        "industry": "Personal",
        "notes": "Your life, goals, and personal ops — not a registered business.",
        "kind": "personal",
        "icon": "user",
        "badge": "Personal",
        "suggested_projects": [
            {
                "name": "Life admin",
                "description": "Bills, appointments, documents, household ops.",
                "template_id": "personal_admin",
                "tasks": [
                    {"title": "Weekly life admin sweep", "description": "Bills due, appointments, paperwork to file. List actions for the week."},
                    {"title": "Inbox zero pass", "description": "Clear personal email: archive, reply, or schedule. Draft replies for urgent items."},
                    {"title": "Calendar plan", "description": "Plan next 7 days: fixed commitments + deep-work blocks + personal time."},
                ],
            },
            {
                "name": "Goals & habits",
                "description": "Goals, habits, learning, and health tracking.",
                "template_id": "personal_goals",
                "tasks": [
                    {"title": "Define 90-day goals", "description": "3 goals with success metrics and weekly habits that support each."},
                    {"title": "Habit check-in", "description": "Review habits for the last 7 days. Adjust one system that is failing."},
                    {"title": "Learning plan", "description": "Pick one skill for this month; outline resources and a weekly study slot."},
                ],
            },
            {
                "name": "Side projects",
                "description": "Personal projects, side hustles, creative work.",
                "template_id": "personal_projects",
                "tasks": [
                    {"title": "Project shortlist", "description": "List active side projects; kill, pause, or prioritise each."},
                    {"title": "Next milestone", "description": "For the top project, define the next shippable milestone and tasks."},
                    {"title": "Weekly ship note", "description": "What shipped this week? What is blocked? Who can help?"},
                ],
            },
        ],
        "default_task_options": [t["id"] for t in TASK_TEMPLATES if t.get("for_all")],
    },
    {
        "id": "trades",
        "name": "Trades / field services",
        "industry": "Trades",
        "notes": "Electrical, plumbing, HVAC, fire safety, or similar field-service business.",
        "kind": "business",
        "icon": "tool",
        "suggested_projects": [
            {
                "name": "Inbound enquiries",
                "description": "Leads, quotes, and booking jobs.",
                "template_id": "sales_pipeline",
                "tasks": [
                    {"title": "Triage new enquiries", "description": "Score and prioritise inbound jobs. Draft quote replies for top 5."},
                    {"title": "Quote follow-ups", "description": "Chase open quotes older than 3 days with short SMS/email drafts."},
                ],
            },
            {
                "name": "Compliance & certificates",
                "description": "Certificates, paperwork, and compliance deadlines.",
                "template_id": "ops_compliance",
                "tasks": [
                    {"title": "Certificate backlog", "description": "List outstanding certificates and owners. Flag anything past SLA."},
                    {"title": "Compliance calendar", "description": "Upcoming renewals / inspections for the next 30 days."},
                ],
            },
            {
                "name": "Review reputation",
                "description": "Google reviews and reputation replies.",
                "template_id": "customer_support",
                "tasks": [
                    {"title": "Reply to recent reviews", "description": "Draft replies for the latest reviews (positive + negative)."},
                ],
            },
        ],
        "default_task_options": [t["id"] for t in TASK_TEMPLATES if t.get("for_all")],
    },
    {
        "id": "agency",
        "name": "Marketing / digital agency",
        "industry": "Agency",
        "notes": "Multi-client agency — one company per brand or client account.",
        "kind": "business",
        "icon": "team",
        "suggested_projects": [
            {
                "name": "Client retainers",
                "description": "Retainer delivery, reporting, and upsells.",
                "template_id": "client_delivery",
                "tasks": [
                    {"title": "Retainer status board", "description": "For each active client: status, blockers, deliverables due this week."},
                    {"title": "Monthly report draft", "description": "Draft a client-ready monthly performance summary with next actions."},
                ],
            },
            {
                "name": "Campaign production",
                "description": "Campaigns, creatives, and launches.",
                "template_id": "content_marketing",
                "tasks": [
                    {"title": "Campaign brief", "description": "Goal, audience, channels, budget, KPI, timeline for the next campaign."},
                    {"title": "Asset checklist", "description": "List creatives needed by channel with owners and due dates."},
                ],
            },
            {
                "name": "Reporting",
                "description": "Analytics and client reporting cadence.",
                "template_id": "reporting",
                "tasks": [
                    {"title": "KPI snapshot", "description": "Pull key metrics vs last period; highlight 3 insights and 3 actions."},
                ],
            },
        ],
        "default_task_options": [t["id"] for t in TASK_TEMPLATES if t.get("for_all")],
    },
    {
        "id": "saas",
        "name": "SaaS / software product",
        "industry": "Technology",
        "notes": "Product company with product, support, and GTM workstreams.",
        "kind": "business",
        "icon": "cloud",
        "suggested_projects": [
            {
                "name": "Product roadmap",
                "description": "Specs, prioritisation, and release planning.",
                "template_id": "product_dev",
                "tasks": [
                    {"title": "Roadmap triage", "description": "Rank top 10 feature requests (impact × effort). Recommend next 2 sprints."},
                    {"title": "Spec one feature", "description": "Write a one-pager: problem, users, success metrics, acceptance criteria."},
                ],
            },
            {
                "name": "Customer support",
                "description": "Tickets, FAQs, and churn saves.",
                "template_id": "customer_support",
                "tasks": [
                    {"title": "Ticket themes", "description": "Cluster recent support issues into themes; suggest FAQ/product fixes."},
                ],
            },
            {
                "name": "Growth & content",
                "description": "Content, SEO, and acquisition experiments.",
                "template_id": "content_marketing",
                "tasks": [
                    {"title": "Growth experiment backlog", "description": "5 experiments with hypothesis, metric, and effort score."},
                ],
            },
        ],
        "default_task_options": [t["id"] for t in TASK_TEMPLATES if t.get("for_all")],
    },
    {
        "id": "ecommerce",
        "name": "E‑commerce / retail",
        "industry": "Retail",
        "notes": "Online or multi-channel retail operations.",
        "kind": "business",
        "icon": "shop",
        "suggested_projects": [
            {
                "name": "Orders & ops",
                "description": "Fulfilment, returns, and stock issues.",
                "template_id": "ops_compliance",
                "tasks": [
                    {"title": "Order exception list", "description": "Late, missing, or problem orders — next action for each."},
                    {"title": "Returns process check", "description": "Review return flow; suggest 3 improvements for speed/CX."},
                ],
            },
            {
                "name": "Customer care",
                "description": "Pre/post-sale support and reviews.",
                "template_id": "customer_support",
                "tasks": [
                    {"title": "Support macros", "description": "Draft 5 reusable reply templates for common questions."},
                ],
            },
            {
                "name": "Catalogue & merch",
                "description": "Product copy, merchandising, promos.",
                "template_id": "content_marketing",
                "tasks": [
                    {"title": "Product page rewrite", "description": "Rewrite one product page for conversion (benefits, FAQ, CTA)."},
                ],
            },
        ],
        "default_task_options": [t["id"] for t in TASK_TEMPLATES if t.get("for_all")],
    },
    {
        "id": "professional",
        "name": "Professional services",
        "industry": "Professional services",
        "notes": "Consultancy, legal, accounting, or similar client work.",
        "kind": "business",
        "icon": "bank",
        "suggested_projects": [
            {
                "name": "Client delivery",
                "description": "Engagements, deliverables, and milestones.",
                "template_id": "client_delivery",
                "tasks": [
                    {"title": "Engagement status", "description": "Per client: phase, next deliverable, risk, next meeting."},
                ],
            },
            {
                "name": "BD / proposals",
                "description": "Pipeline, proposals, and pitch materials.",
                "template_id": "sales_pipeline",
                "tasks": [
                    {"title": "Proposal outline", "description": "Structure a proposal: problem, approach, timeline, fees, next step."},
                ],
            },
            {
                "name": "Knowledge base",
                "description": "Playbooks and reusable IP.",
                "template_id": "knowledge",
                "tasks": [
                    {"title": "Playbook stub", "description": "Start a playbook for a recurring service delivery process."},
                ],
            },
        ],
        "default_task_options": [t["id"] for t in TASK_TEMPLATES if t.get("for_all")],
    },
    {
        "id": "restaurant",
        "name": "Restaurant / hospitality",
        "industry": "Hospitality",
        "notes": "Restaurant, café, hotel, or venue operations.",
        "kind": "business",
        "icon": "coffee",
        "suggested_projects": [
            {
                "name": "Guest experience",
                "description": "Reviews, bookings, and guest recovery.",
                "template_id": "customer_support",
                "tasks": [
                    {"title": "Review reply pack", "description": "Draft replies for 5-star and 1–2 star reviews in brand voice."},
                ],
            },
            {
                "name": "Marketing & events",
                "description": "Promos, events, and social.",
                "template_id": "content_marketing",
                "tasks": [
                    {"title": "This week’s promo", "description": "One promo idea with copy for email + social + in-venue."},
                ],
            },
            {
                "name": "Ops & staffing",
                "description": "Rosters, suppliers, checklists.",
                "template_id": "ops_compliance",
                "tasks": [
                    {"title": "Service checklist", "description": "Opening/closing checklist for front and back of house."},
                ],
            },
        ],
        "default_task_options": [t["id"] for t in TASK_TEMPLATES if t.get("for_all")],
    },
    {
        "id": "healthcare",
        "name": "Clinic / healthcare",
        "industry": "Healthcare",
        "notes": "Clinic, practice, or wellness business (no medical advice — ops only).",
        "kind": "business",
        "icon": "medicine",
        "suggested_projects": [
            {
                "name": "Patient communications",
                "description": "Reminders, FAQs, and follow-ups (ops templates only).",
                "template_id": "customer_support",
                "tasks": [
                    {"title": "Appointment reminder copy", "description": "SMS + email reminder templates with reschedule CTA."},
                ],
            },
            {
                "name": "Practice ops",
                "description": "Scheduling, suppliers, compliance checklists.",
                "template_id": "ops_compliance",
                "tasks": [
                    {"title": "Weekly ops checklist", "description": "Front desk + clinical room prep checklist for the week."},
                ],
            },
        ],
        "default_task_options": [t["id"] for t in TASK_TEMPLATES if t.get("for_all")],
    },
    {
        "id": "real_estate",
        "name": "Real estate / property",
        "industry": "Real estate",
        "notes": "Agency, property management, or lettings.",
        "kind": "business",
        "icon": "home",
        "suggested_projects": [
            {
                "name": "Listings & leads",
                "description": "New listings, viewings, and lead follow-up.",
                "template_id": "sales_pipeline",
                "tasks": [
                    {"title": "Lead chase list", "description": "Warm leads needing a call/email this week with draft scripts."},
                    {"title": "Listing blurb", "description": "Write a listing description (features, lifestyle, CTA)."},
                ],
            },
            {
                "name": "Tenants & landlords",
                "description": "Property management communications.",
                "template_id": "customer_support",
                "tasks": [
                    {"title": "Maintenance triage", "description": "Template for logging and prioritising maintenance requests."},
                ],
            },
        ],
        "default_task_options": [t["id"] for t in TASK_TEMPLATES if t.get("for_all")],
    },
    {
        "id": "nonprofit",
        "name": "Nonprofit / community",
        "industry": "Nonprofit",
        "notes": "Charity, community group, or association.",
        "kind": "business",
        "icon": "heart",
        "suggested_projects": [
            {
                "name": "Fundraising",
                "description": "Campaigns, donors, and grants.",
                "template_id": "content_marketing",
                "tasks": [
                    {"title": "Donor update draft", "description": "Short impact update for donors with a soft ask."},
                ],
            },
            {
                "name": "Programmes",
                "description": "Delivery of programmes and events.",
                "template_id": "ops_compliance",
                "tasks": [
                    {"title": "Event run sheet", "description": "Timeline + owners for the next community event."},
                ],
            },
        ],
        "default_task_options": [t["id"] for t in TASK_TEMPLATES if t.get("for_all")],
    },
    {
        "id": "blank",
        "name": "Blank company",
        "industry": "",
        "notes": "",
        "kind": "business",
        "icon": "plus",
        "suggested_projects": [],
        "default_task_options": [t["id"] for t in TASK_TEMPLATES if t.get("for_all")],
    },
]

# Project templates (standalone when adding a project)
PROJECT_TEMPLATES = [
    {
        "id": "sales_pipeline",
        "name": "Sales pipeline",
        "description": "Outbound/inbound sales, lead qualification, and follow-ups.",
        "status": "active",
        "suggested_agent_roles": ["sales", "lead"],
        "suggested_task_ids": ["follow_ups", "inbox_triage", "status_report"],
    },
    {
        "id": "customer_support",
        "name": "Customer support",
        "description": "Inbox triage, FAQs, complaints, and review replies.",
        "status": "active",
        "suggested_agent_roles": ["support", "reviews"],
        "suggested_task_ids": ["inbox_triage", "follow_ups", "checklist"],
    },
    {
        "id": "content_marketing",
        "name": "Content & marketing",
        "description": "Blog, SEO, social calendar, and campaign copy.",
        "status": "active",
        "suggested_agent_roles": ["content", "marketing"],
        "suggested_task_ids": ["content_draft", "ideas_backlog", "weekly_review"],
    },
    {
        "id": "ops_compliance",
        "name": "Ops & compliance",
        "description": "Certificates, SLAs, scheduling, and internal checklists.",
        "status": "active",
        "suggested_agent_roles": ["ops", "support"],
        "suggested_task_ids": ["checklist", "status_report", "daily_standup"],
    },
    {
        "id": "product_dev",
        "name": "Product / engineering",
        "description": "Specs, code assistance, QA checklists, and release notes.",
        "status": "active",
        "suggested_agent_roles": ["coding", "lead"],
        "suggested_task_ids": ["research_brief", "checklist", "status_report"],
    },
    {
        "id": "onboarding",
        "name": "Client onboarding",
        "description": "Kickoff checklists, welcome sequences, and setup tasks.",
        "status": "active",
        "suggested_agent_roles": ["support", "sales"],
        "suggested_task_ids": ["checklist", "meeting_prep", "follow_ups"],
    },
    {
        "id": "client_delivery",
        "name": "Client delivery",
        "description": "Engagement delivery and retainers.",
        "status": "active",
        "suggested_agent_roles": ["ops", "lead"],
        "suggested_task_ids": ["status_report", "weekly_review", "meeting_prep"],
    },
    {
        "id": "reporting",
        "name": "Reporting & analytics",
        "description": "KPI reporting and insights.",
        "status": "active",
        "suggested_agent_roles": ["ops", "content"],
        "suggested_task_ids": ["status_report", "weekly_review", "research_brief"],
    },
    {
        "id": "knowledge",
        "name": "Knowledge base",
        "description": "Playbooks and documentation.",
        "status": "active",
        "suggested_agent_roles": ["ops", "content"],
        "suggested_task_ids": ["checklist", "content_draft", "research_brief"],
    },
    {
        "id": "personal_admin",
        "name": "Life admin",
        "description": "Personal admin and household ops.",
        "status": "active",
        "suggested_agent_roles": ["ops"],
        "suggested_task_ids": ["inbox_triage", "checklist", "weekly_review"],
    },
    {
        "id": "personal_goals",
        "name": "Goals & habits",
        "description": "Personal goals and habit systems.",
        "status": "active",
        "suggested_agent_roles": ["ops"],
        "suggested_task_ids": ["weekly_review", "ideas_backlog", "daily_standup"],
    },
    {
        "id": "personal_projects",
        "name": "Side projects",
        "description": "Personal or side-hustle projects.",
        "status": "active",
        "suggested_agent_roles": ["coding", "content"],
        "suggested_task_ids": ["status_report", "ideas_backlog", "checklist"],
    },
    {
        "id": "blank",
        "name": "Blank project",
        "description": "",
        "status": "active",
        "suggested_agent_roles": [],
        "suggested_task_ids": [t["id"] for t in TASK_TEMPLATES if t.get("for_all")],
    },
]


def get_company_template(tid: str | None) -> dict | None:
    if not tid:
        return None
    for t in COMPANY_TEMPLATES:
        if t["id"] == tid:
            return t
    return None


def get_project_template(tid: str | None) -> dict | None:
    if not tid:
        return None
    for t in PROJECT_TEMPLATES:
        if t["id"] == tid:
            return t
    return None


def get_task_template(tid: str | None) -> dict | None:
    if not tid:
        return None
    for t in TASK_TEMPLATES:
        if t["id"] == tid:
            return t
    return None


def public_company_templates() -> list[dict]:
    """Safe list for UI (includes nested project/task previews)."""
    out = []
    for t in COMPANY_TEMPLATES:
        projects = t.get("suggested_projects") or []
        # Normalise string-only legacy shape
        norm_projects = []
        for p in projects:
            if isinstance(p, str):
                norm_projects.append({"name": p, "description": "", "tasks": []})
            else:
                norm_projects.append({
                    "name": p.get("name"),
                    "description": p.get("description") or "",
                    "template_id": p.get("template_id"),
                    "task_count": len(p.get("tasks") or []),
                    "tasks": p.get("tasks") or [],
                })
        out.append({
            "id": t["id"],
            "name": t["name"],
            "industry": t.get("industry") or "",
            "notes": t.get("notes") or "",
            "kind": t.get("kind") or "business",
            "icon": t.get("icon") or "bank",
            "badge": t.get("badge"),
            "suggested_projects": norm_projects,
            "project_count": len(norm_projects),
            "default_task_options": t.get("default_task_options") or [],
        })
    return out


def public_project_templates() -> list[dict]:
    return [
        {
            "id": t["id"],
            "name": t["name"],
            "description": t.get("description") or "",
            "status": t.get("status") or "active",
            "suggested_agent_roles": t.get("suggested_agent_roles") or [],
            "suggested_task_ids": t.get("suggested_task_ids") or [],
            "suggested_tasks": [
                get_task_template(tid) for tid in (t.get("suggested_task_ids") or [])
                if get_task_template(tid)
            ],
        }
        for t in PROJECT_TEMPLATES
    ]


def public_task_templates() -> list[dict]:
    return list(TASK_TEMPLATES)
