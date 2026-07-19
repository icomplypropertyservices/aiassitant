"""Extract product + Shopify routes from business.py into business_products.py."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "backend" / "app" / "routers"
src = ROOT / "business.py"
lines = src.read_text(encoding="utf-8").splitlines(keepends=True)

# Find start of products section and end before deals
start = None
end = None
for i, line in enumerate(lines):
    if start is None and line.startswith("# ── Products"):
        start = i
    if start is not None and line.startswith("# ── Deals"):
        end = i
        break
assert start is not None and end is not None, (start, end)

# Also remove ProductIn/ProductUpdate schemas and product helpers that only products need
# Keep helpers that customers use: _normalize_tags, _resolve_company_id, etc.
# Move product-only helpers with the routes.

header = '''"""Business products catalogue + Shopify sync/push routes."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models
from ..auth_utils import get_current_user
from ..live_ops import emit_ops
from ..tags_util import normalize_tags, tags_list

router = APIRouter(prefix="/business", tags=["business-products"])

PRODUCT_TAG_PRESETS = [
    "core", "addon", "featured", "service", "digital", "physical",
    "subscription", "bundle", "new", "sale", "b2b", "b2c",
]


def _user_default_company_id(db: Session, user: models.User) -> int | None:
    co = (
        db.query(models.Company)
        .filter_by(owner_user_id=user.id)
        .order_by(models.Company.id)
        .first()
    )
    return co.id if co else None


def _resolve_company_id(
    db: Session,
    user: models.User,
    company_id: int | None,
    *,
    required: bool = False,
) -> int | None:
    if company_id is not None and company_id != 0:
        co = db.get(models.Company, int(company_id))
        if not co or co.owner_user_id != user.id:
            raise HTTPException(400, "Company not found or not linked to your account")
        return co.id
    default_id = _user_default_company_id(db, user)
    if required and not default_id:
        raise HTTPException(
            400,
            "Link a company first (Workspace -> Companies). Products must belong to your company.",
        )
    return default_id


def _owned_product(db: Session, product_id: int, user) -> models.Product:
    p = db.get(models.Product, product_id)
    if not p or p.owner_user_id != user.id:
        raise HTTPException(404, "Product not found")
    return p


def _product_out(p: models.Product, db: Session) -> dict:
    co = db.get(models.Company, p.company_id) if p.company_id else None
    return {
        "id": p.id,
        "name": p.name,
        "sku": p.sku or "",
        "description": p.description or "",
        "kind": p.kind or "product",
        "price": float(p.price or 0),
        "currency": p.currency or "USD",
        "status": p.status or "active",
        "tags": tags_list(p.tags),
        "tags_raw": p.tags or "",
        "company_id": p.company_id,
        "company_name": co.name if co else None,
        "external_source": getattr(p, "external_source", None) or "",
        "external_id": getattr(p, "external_id", None) or "",
        "benefits": p.benefits or "",
        "audience": p.audience or "",
        "offer": p.offer or "",
        "image_url": p.image_url or "",
        "created_at": p.created_at,
        "updated_at": p.updated_at,
    }


class ProductIn(BaseModel):
    name: str
    sku: str = ""
    description: str = ""
    kind: str = "product"
    price: float = 0.0
    currency: str = "USD"
    status: str = "active"
    tags: str | list[str] = ""
    company_id: int | None = None
    benefits: str = ""
    audience: str = ""
    offer: str = ""
    image_url: str = ""


class ProductUpdate(BaseModel):
    name: str | None = None
    sku: str | None = None
    description: str | None = None
    kind: str | None = None
    price: float | None = None
    currency: str | None = None
    status: str | None = None
    tags: str | list[str] | None = None
    company_id: int | None = None
    benefits: str | None = None
    audience: str | None = None
    offer: str | None = None
    image_url: str | None = None


class ShopifySyncIn(BaseModel):
    company_id: int | None = None
    connection_id: int | None = None
    limit: int = 50
    what: str = "all"


'''

# Rewrite extracted route block to use normalize_tags / tags_list
body = "".join(lines[start:end])
body = body.replace("_normalize_tags", "normalize_tags")
body = body.replace("_tags_list", "tags_list")
# PRODUCT_TAG_PRESETS already defined in header — drop local if any reference works

out = header + body
(ROOT / "business_products.py").write_text(out, encoding="utf-8")

# Remove product schemas from original (ProductIn/ProductUpdate blocks)
new_lines = lines[:start] + lines[end:]
text = "".join(new_lines)

# Remove ProductIn and ProductUpdate class blocks from remaining file
import re
text = re.sub(
    r"\nclass ProductIn\(BaseModel\):.*?(?=\nclass ProductUpdate)",
    "\n",
    text,
    count=1,
    flags=re.S,
)
text = re.sub(
    r"\nclass ProductUpdate\(BaseModel\):.*?(?=\nclass DealIn)",
    "\n",
    text,
    count=1,
    flags=re.S,
)
# Remove product-only helpers
text = re.sub(
    r"\ndef _owned_product\(.*?(?=\ndef _product_out)",
    "\n",
    text,
    count=1,
    flags=re.S,
)
text = re.sub(
    r"\ndef _product_out\(.*?(?=\n# ── Overview|\n@router\.get\(\"/overview\"\))",
    "\n",
    text,
    count=1,
    flags=re.S,
)
# Use shared tags util
if "from ..tags_util import" not in text:
    text = text.replace(
        "from ..live_ops import emit_ops\n",
        "from ..live_ops import emit_ops\nfrom ..tags_util import normalize_tags, tags_list\n",
    )
text = text.replace("def _normalize_tags(tags) -> str:\n", "def _normalize_tags_REMOVED(tags) -> str:\n")
# Delete the whole _normalize_tags and _tags_list local defs
text = re.sub(
    r"\ndef _normalize_tags_REMOVED\(tags\) -> str:.*?(?=\ndef _user_default_company_id)",
    "\n\ndef _normalize_tags(tags):\n    return normalize_tags(tags)\n\n\ndef _tags_list(raw):\n    return tags_list(raw)\n",
    text,
    count=1,
    flags=re.S,
)
# PRODUCT_TAG_PRESETS may still be referenced in overview - keep CUSTOMER and PRODUCT presets
src.write_text(text, encoding="utf-8")
print("business.py lines", text.count("\n") + 1)
print("business_products.py lines", out.count("\n") + 1)
print("extracted start-end", start, end)
