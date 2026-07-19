"""ownership.require_owned — tenant isolation (offline)."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app import models
from app.ownership import require_owned


def test_require_owned_ok_for_owner(db, agent_factory):
    agent, owner = agent_factory()
    got = require_owned(db, models.Agent, agent.id, owner, user_field="user_id")
    assert got.id == agent.id
    assert got.user_id == owner.id


def test_require_owned_404_for_wrong_user(db, agent_factory, user_factory):
    agent, owner = agent_factory(email="owner@example.com")
    other = user_factory(email="intruder@example.com")

    with pytest.raises(HTTPException) as ei:
        require_owned(db, models.Agent, agent.id, other, user_field="user_id")
    assert ei.value.status_code == 404
    # Must not leak existence
    assert "not found" in str(ei.value.detail).lower()


def test_require_owned_404_missing_id(db, user_factory):
    user = user_factory()
    with pytest.raises(HTTPException) as ei:
        require_owned(db, models.Agent, 424242, user, user_field="user_id")
    assert ei.value.status_code == 404


def test_require_owned_admin_bypass(db, agent_factory, user_factory):
    agent, _owner = agent_factory(email="owner2@example.com")
    admin = user_factory(email="admin@example.com", role="admin")
    got = require_owned(
        db, models.Agent, agent.id, admin, user_field="user_id", allow_admin=True
    )
    assert got.id == agent.id


def test_require_owned_customer_owner_user_id(db, user_factory):
    owner = user_factory(email="crm@example.com")
    other = user_factory(email="other-crm@example.com")
    cust = models.Customer(
        owner_user_id=owner.id,
        name="Acme",
        email="acme@example.com",
    )
    db.add(cust)
    db.commit()
    db.refresh(cust)

    got = require_owned(db, models.Customer, cust.id, owner)
    assert got.id == cust.id

    with pytest.raises(HTTPException) as ei:
        require_owned(db, models.Customer, cust.id, other)
    assert ei.value.status_code == 404
