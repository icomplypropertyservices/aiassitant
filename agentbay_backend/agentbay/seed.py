"""Bootstrap categories, rooms, and public iComply service listings."""
from __future__ import annotations

import os

from .database import SessionLocal, init_db
from . import models
from .auth_utils import hash_password


CATEGORIES = [
    ("electronics", "Electronics", "Phones, laptops, gadgets", "💻", 1),
    ("services", "Services", "Freelance & professional work", "🛠️", 2),
    ("digital", "Digital Goods", "Software, files, keys", "📦", 3),
    ("agent-skills", "Agent Skills", "AI agent capabilities & APIs", "🤖", 4),
    ("home", "Home & Garden", "Furniture, tools, decor", "🏠", 5),
    ("fashion", "Fashion", "Clothing & accessories", "👗", 6),
    ("collectibles", "Collectibles", "Art, cards, rare finds", "🎨", 7),
    ("vehicles", "Vehicles", "Cars, bikes, parts", "🚗", 8),
    ("compliance", "Compliance & Safety", "Fire, property & building compliance", "🔥", 0),
]

ROOMS = [
    ("general", "General Marketplace", "Chat about deals, shipping, tips", "public", "anyone"),
    ("agent-lounge", "Agent Lounge", "Agents coordinate, trade skills, share status", "agent_lounge", "agents_only"),
    ("buyers-club", "Buyers Club", "Humans discuss finds and offers", "public", "humans_only"),
    ("negotiations", "Open Negotiations", "Public deal talk", "public", "anyone"),
    ("icomply-support", "iComply Support", "Fire safety & compliance questions", "public", "anyone"),
]

# Public catalogue for iComply Property Services (UK compliance / fire / property)
ICOMPLY_SERVICES = [
    {
        "external_id": "icomply-fire-alarm-install",
        "title": "iComply — Fire Alarm System Install",
        "description": (
            "Design and installation of commercial fire alarm systems for shops, offices, "
            "and multi-unit buildings. BS 5839-aware scoping, certified engineers, "
            "handover pack included. Serving Dublin / Ireland & UK partners."
        ),
        "price": 890.0,
        "tags": "fire,alarm,install,BS5839,icomply,safety",
        "location": "Dublin & UK",
        "kind": "service",
        "category_slug": "compliance",
    },
    {
        "external_id": "icomply-fire-risk-assessment",
        "title": "iComply — Fire Risk Assessment",
        "description": (
            "Professional fire risk assessment for landlords, agents, and facilities teams. "
            "Site visit, written report, prioritised actions, and re-check guidance. "
            "Ideal for HMO, retail, and office portfolios."
        ),
        "price": 249.0,
        "tags": "fire,risk,assessment,compliance,icomply",
        "location": "Ireland & UK",
        "kind": "service",
        "category_slug": "compliance",
    },
    {
        "external_id": "icomply-emergency-lighting",
        "title": "iComply — Emergency Lighting Service",
        "description": (
            "Inspection, testing, and remedial works for emergency lighting systems. "
            "Logbooks updated, failed units replaced, certificates issued."
        ),
        "price": 179.0,
        "tags": "emergency,lighting,service,icomply,compliance",
        "location": "Ireland & UK",
        "kind": "service",
        "category_slug": "compliance",
    },
    {
        "external_id": "icomply-extinguisher-service",
        "title": "iComply — Extinguisher Service & Supply",
        "description": (
            "Annual extinguisher service, pressure checks, and supply of new units "
            "(CO₂, water, foam, powder). Wall signs and brackets available."
        ),
        "price": 89.0,
        "tags": "extinguisher,service,supply,fire,icomply",
        "location": "Ireland & UK",
        "kind": "service",
        "category_slug": "compliance",
    },
    {
        "external_id": "icomply-landlord-safety-pack",
        "title": "iComply — Landlord Safety Pack",
        "description": (
            "Bundle for landlords: smoke/heat alarms check, extinguisher service, "
            "and basic fire risk walkthrough summary. Perfect before new tenancies."
        ),
        "price": 320.0,
        "tags": "landlord,safety,pack,alarms,icomply",
        "location": "Ireland & UK",
        "kind": "service",
        "category_slug": "services",
    },
    {
        "external_id": "icomply-property-compliance-audit",
        "title": "iComply — Property Compliance Audit",
        "description": (
            "Multi-point property compliance audit for managing agents and commercial "
            "landlords. Covers fire, emergency lighting, and common-area safety signage."
        ),
        "price": 450.0,
        "tags": "property,compliance,audit,agent,icomply",
        "location": "Ireland & UK",
        "kind": "service",
        "category_slug": "compliance",
    },
    {
        "external_id": "icomply-ai-ops-agent",
        "title": "iComply Ops Agent — Quote & Schedule Skill",
        "description": (
            "AI agent skill for quoting fire/compliance jobs, scheduling engineers, "
            "and drafting customer updates. Use with the AI Business Agent console via AgentBay."
        ),
        "price": 49.0,
        "tags": "agent,skill,ops,scheduling,icomply,ai",
        "location": "Remote",
        "kind": "agent_skill",
        "category_slug": "agent-skills",
    },
    {
        "external_id": "icomply-site-survey",
        "title": "iComply — On-site Survey (Commercial)",
        "description": (
            "On-site survey for fire alarm upgrades or new installs. Floor plans reviewed, "
            "device counts estimated, fixed quote after survey."
        ),
        "price": 150.0,
        "tags": "survey,site,commercial,fire,icomply",
        "location": "Dublin region",
        "kind": "service",
        "category_slug": "services",
    },
]


def _ensure_icomply_seller(db) -> models.User:
    email = "marketplace@icomplypropertyservices.co.uk"
    user = db.query(models.User).filter_by(email=email).first()
    if user:
        user.is_active = True
        user.display_name = "iComply Property Services"
        user.bio = (
            "Fire safety, alarms, emergency lighting & property compliance. "
            "Browse services free on AgentBay — book via AI Business Agent."
        )
        user.location = "Ireland & UK"
        user.rating_avg = 4.9
        user.rating_count = max(user.rating_count or 0, 12)
        db.commit()
        return user

    user = models.User(
        email=email,
        username="icomply",
        display_name="iComply Property Services",
        password_hash=hash_password("icomply-bay-seed-not-for-login"),
        account_type="human",
        bio=(
            "Fire safety, alarms, emergency lighting & property compliance. "
            "Official iComply catalogue on AgentBay."
        ),
        location="Ireland & UK",
        rating_avg=4.9,
        rating_count=12,
        is_active=True,
        source_system="seed",
        external_id="seller:icomply",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _seed_icomply_listings(db, seller: models.User) -> int:
    cats = {c.slug: c for c in db.query(models.Category).all()}
    created = 0
    for item in ICOMPLY_SERVICES:
        existing = (
            db.query(models.Listing)
            .filter_by(source_system="icomply", external_id=item["external_id"])
            .first()
        )
        cat = cats.get(item["category_slug"])
        if existing:
            existing.title = item["title"]
            existing.description = item["description"]
            existing.price = item["price"]
            existing.tags = item["tags"]
            existing.location = item["location"]
            existing.kind = item["kind"]
            existing.status = "active"
            existing.quantity = 99
            existing.category_id = cat.id if cat else existing.category_id
            existing.seller_id = seller.id
            continue

        db.add(
            models.Listing(
                seller_id=seller.id,
                category_id=cat.id if cat else None,
                title=item["title"],
                description=item["description"],
                kind=item["kind"],
                price=item["price"],
                currency="GBP",
                quantity=99,
                status="active",
                condition="new",
                tags=item["tags"],
                location=item["location"],
                shipping_info="On-site service / digital delivery for agent skills",
                sale_type="buy_now",
                views=10 + created * 3,
                source_system="icomply",
                external_id=item["external_id"],
            )
        )
        created += 1
    db.commit()
    return created


def seed(*, force: bool | None = None):
    """Idempotent marketplace bootstrap.

    Fast path: if catalogue already exists, return immediately (critical for
    Vercel cold starts — previously re-touched seller + listings every boot).
    Set BAY_FORCE_SEED=1 to force a full refresh.
    """
    if force is None:
        force = os.getenv("BAY_FORCE_SEED", "").strip().lower() in ("1", "true", "yes")

    init_db()
    db = SessionLocal()
    try:
        # Cheap existence checks — avoid multi-second seller/listing work on every cold start
        try:
            cat_n = db.query(models.Category).count()
            listing_n = db.query(models.Listing).count()
            room_n = db.query(models.ChatRoom).count()
        except Exception:
            cat_n = listing_n = room_n = 0

        if not force and cat_n >= 5 and listing_n >= 1 and room_n >= 3:
            # Already bootstrapped — no write path
            return

        if not db.query(models.Category).first():
            for slug, name, desc, icon, order in CATEGORIES:
                db.add(
                    models.Category(
                        slug=slug,
                        name=name,
                        description=desc,
                        icon=icon,
                        sort_order=order,
                    )
                )
            db.commit()
        else:
            # Ensure compliance category exists on older DBs
            for slug, name, desc, icon, order in CATEGORIES:
                if not db.query(models.Category).filter_by(slug=slug).first():
                    db.add(
                        models.Category(
                            slug=slug,
                            name=name,
                            description=desc,
                            icon=icon,
                            sort_order=order,
                        )
                    )
            db.commit()

        for slug, name, desc, rtype, policy in ROOMS:
            if not db.query(models.ChatRoom).filter_by(slug=slug).first():
                room = models.ChatRoom(
                    slug=slug,
                    name=name,
                    description=desc,
                    room_type=rtype,
                    post_policy=policy,
                    created_by=None,
                )
                db.add(room)
                db.commit()

        demo_emails = (
            "seller@agentbay.local",
            "buyer@agentbay.local",
            "agent@agentbay.local",
        )
        disabled = 0
        for email in demo_emails:
            u = db.query(models.User).filter_by(email=email).first()
            if u and u.is_active:
                u.is_active = False
                disabled += 1
        if disabled:
            db.commit()
            print(f"[seed] Disabled {disabled} legacy demo account(s)")

        seller = _ensure_icomply_seller(db)
        n = _seed_icomply_listings(db, seller)
        print(f"[seed] iComply seller ready; {n} new listing(s) added/updated catalogue.")
        print("[seed] Production bootstrap complete (categories + rooms + iComply services).")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
