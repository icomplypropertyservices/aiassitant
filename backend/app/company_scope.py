"""Canonical company ownership + default company for a subscriber."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from . import models


def user_default_company_id(db: Session, user: models.User) -> int | None:
    co = (
        db.query(models.Company)
        .filter_by(owner_user_id=user.id)
        .order_by(models.Company.id)
        .first()
    )
    return co.id if co else None


def resolve_company_id(
    db: Session,
    user: models.User,
    company_id: int | None,
    *,
    required: bool = False,
    resource: str = "records",
) -> int | None:
    """Ensure company belongs to the user; optionally default to first company."""
    if company_id is not None and int(company_id) != 0:
        co = db.get(models.Company, int(company_id))
        if not co or co.owner_user_id != user.id:
            raise HTTPException(400, "Company not found or not linked to your account")
        return co.id
    default_id = user_default_company_id(db, user)
    if required and not default_id:
        raise HTTPException(
            400,
            f"Link a company first (Workspace → Companies). {resource.capitalize()} must belong to your company.",
        )
    return default_id
