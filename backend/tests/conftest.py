"""Pytest fixtures — offline SQLite, no network."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure backend/ is on path when running from repo root or backend/
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

# Force sqlite for tests before app.database is imported elsewhere
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-prod")
os.environ.setdefault("ENCRYPTION_KEY", "test-encryption-key-32bytes-ok!!")


@pytest.fixture()
def db():
    """Fresh in-memory SQLite session with all models created."""
    from app.database import Base
    from app import models  # noqa: F401 — register metadata

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def user_factory(db):
    """Create a User row; password hash is a dummy (auth not exercised)."""
    from app import models

    def _make(email: str = "owner@example.com", *, role: str = "user", **kwargs):
        u = models.User(
            email=email,
            name=kwargs.get("name") or email.split("@")[0],
            password_hash=kwargs.get("password_hash") or "x",
            role=role,
            plan=kwargs.get("plan") or "pro",
            subscription_active=kwargs.get("subscription_active", True),
            email_verified=True,
        )
        db.add(u)
        db.commit()
        db.refresh(u)
        return u

    return _make


@pytest.fixture()
def agent_factory(db, user_factory):
    """Create an Agent for a user (defaults to a new owner)."""
    from app import models

    def _make(user=None, **kwargs):
        owner = user or user_factory()
        a = models.Agent(
            user_id=owner.id,
            name=kwargs.get("name") or "Test Agent",
            template_type=kwargs.get("template_type") or "general",
            hierarchy_role=kwargs.get("hierarchy_role") or "member",
            permission_level=kwargs.get("permission_level") or "operator",
            status=kwargs.get("status") or "active",
            personality=kwargs.get("personality") or "Concise.",
            model=kwargs.get("model") or "vps-fast",
        )
        db.add(a)
        db.commit()
        db.refresh(a)
        return a, owner

    return _make
