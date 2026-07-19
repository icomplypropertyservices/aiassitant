"""Shared ownership checks for tenant-scoped models."""
from __future__ import annotations

from typing import TypeVar, Type

from fastapi import HTTPException
from sqlalchemy.orm import Session

from . import models

T = TypeVar("T")


def require_owned(
    db: Session,
    model: Type[T],
    obj_id: int,
    user: models.User,
    *,
    user_field: str = "owner_user_id",
    not_found: str = "Not found",
    allow_admin: bool = True,
) -> T:
    """Load row by id; 404 if missing or not owned by user (admins optional)."""
    obj = db.get(model, obj_id)
    if not obj:
        raise HTTPException(404, not_found)
    owner = getattr(obj, user_field, None)
    if owner is None and user_field == "owner_user_id":
        # agents/tasks often use user_id
        owner = getattr(obj, "user_id", None)
        user_field = "user_id" if owner is not None else user_field
    if owner != user.id and not (allow_admin and getattr(user, "role", None) == "admin"):
        raise HTTPException(404, not_found)
    return obj
