"""Ready-made company + project templates for Workspace setup."""

COMPANY_TEMPLATES = [
    {
        "id": "trades",
        "name": "Trades / field services",
        "industry": "Trades",
        "notes": "Electrical, plumbing, HVAC, fire safety, or similar field-service business.",
        "suggested_projects": ["Inbound enquiries", "Compliance & certificates", "Review reputation"],
        "icon": "tool",
    },
    {
        "id": "agency",
        "name": "Marketing / digital agency",
        "industry": "Agency",
        "notes": "Multi-client agency — one company per brand or client account.",
        "suggested_projects": ["Client retainers", "Campaign production", "Reporting"],
        "icon": "team",
    },
    {
        "id": "saas",
        "name": "SaaS / software product",
        "industry": "Technology",
        "notes": "Product company with product, support, and GTM workstreams.",
        "suggested_projects": ["Product roadmap", "Customer support", "Growth & content"],
        "icon": "cloud",
    },
    {
        "id": "ecommerce",
        "name": "E‑commerce / retail",
        "industry": "Retail",
        "notes": "Online or multi-channel retail operations.",
        "suggested_projects": ["Orders & ops", "Customer care", "Catalogue & merch"],
        "icon": "shop",
    },
    {
        "id": "professional",
        "name": "Professional services",
        "industry": "Professional services",
        "notes": "Consultancy, legal, accounting, or similar client work.",
        "suggested_projects": ["Client delivery", "BD / proposals", "Knowledge base"],
        "icon": "bank",
    },
    {
        "id": "blank",
        "name": "Blank company",
        "industry": "",
        "notes": "",
        "suggested_projects": [],
        "icon": "plus",
    },
]

PROJECT_TEMPLATES = [
    {
        "id": "sales_pipeline",
        "name": "Sales pipeline",
        "description": "Outbound/inbound sales, lead qualification, and follow-ups.",
        "status": "active",
        "suggested_agent_roles": ["sales", "lead"],
    },
    {
        "id": "customer_support",
        "name": "Customer support",
        "description": "Inbox triage, FAQs, complaints, and review replies.",
        "status": "active",
        "suggested_agent_roles": ["support", "reviews"],
    },
    {
        "id": "content_marketing",
        "name": "Content & marketing",
        "description": "Blog, SEO, social calendar, and campaign copy.",
        "status": "active",
        "suggested_agent_roles": ["content", "marketing"],
    },
    {
        "id": "ops_compliance",
        "name": "Ops & compliance",
        "description": "Certificates, SLAs, scheduling, and internal checklists.",
        "status": "active",
        "suggested_agent_roles": ["ops", "support"],
    },
    {
        "id": "product_dev",
        "name": "Product / engineering",
        "description": "Specs, code assistance, QA checklists, and release notes.",
        "status": "active",
        "suggested_agent_roles": ["coding", "lead"],
    },
    {
        "id": "onboarding",
        "name": "Client onboarding",
        "description": "Kickoff checklists, welcome sequences, and setup tasks.",
        "status": "active",
        "suggested_agent_roles": ["support", "sales"],
    },
    {
        "id": "blank",
        "name": "Blank project",
        "description": "",
        "status": "active",
        "suggested_agent_roles": [],
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
