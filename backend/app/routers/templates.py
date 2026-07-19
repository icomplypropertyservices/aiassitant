import json
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models
from ..auth_utils import get_current_user
from ..seed_templates import SEED_TEMPLATES, NOTIFY_FIELDS

router = APIRouter(prefix="/templates", tags=["templates"])

# Catalogue must never look empty in the spawn UI. Seed list is the source of truth.
_EXPECTED_COUNT = len(SEED_TEMPLATES)


def _safe_rollback(db: Session) -> None:
    try:
        db.rollback()
    except Exception:
        pass


def _existing_names(db: Session) -> set[str]:
    """Collect template names already in DB (robust across SQLAlchemy row shapes)."""
    names: set[str] = set()
    try:
        rows = db.query(models.AgentTemplate.name).all()
    except Exception:
        _safe_rollback(db)
        raise
    for row in rows:
        name = None
        if row is None:
            continue
        # Row / keyed tuple: .name or [0]
        name = getattr(row, "name", None)
        if name is None:
            try:
                name = row[0]
            except Exception:
                name = None
        if name:
            names.add(str(name))
    return names


def _ensure_templates(db: Session) -> int:
    """Insert any missing catalog rows. Returns how many were added.

    Production cold starts used to skip heavy seed; if the table is empty or
    incomplete, spawn UI shows no templates. This keeps the catalogue full
    without rewriting every row every request.

    Concurrent serverless cold-starts may race: both see empty, both insert.
    Without a unique name constraint that is harmless (duplicates). On commit
    failure we roll back and the next list/load path re-reads or falls back.
    """
    existing_names = _existing_names(db)
    added = 0
    for name, type_, desc, fields, cost in SEED_TEMPLATES:
        if name in existing_names:
            continue
        full_fields = fields + list(NOTIFY_FIELDS)
        db.add(models.AgentTemplate(
            name=name,
            type=type_,
            description=desc,
            unique_fields=json.dumps(full_fields),
            est_cost=cost,
        ))
        existing_names.add(name)
        added += 1
    if added:
        try:
            db.commit()
        except Exception:
            # Race / transient DB error: drop pending inserts so caller can
            # re-read or serve the in-memory catalogue.
            _safe_rollback(db)
            raise
    return added


def _safe_fields(raw) -> list:
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _sort_key_type_name(type_: str | None, name: str | None):
    order = {"orchestrator": 0, "designer": 1, "lead": 2}.get((type_ or "").lower(), 50)
    return (order, (name or "").lower())


def _row_out(t) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "type": t.type,
        "description": t.description or "",
        "unique_fields": _safe_fields(t.unique_fields),
        "est_cost": t.est_cost or "",
    }


def _catalog_fallback() -> list:
    """In-memory seed catalogue when DB is empty/unavailable.

    Ids are synthetic (1..N) so the SPA can still select a template; create
    only needs type/name/fields from the client payload, not a real FK.
    """
    out = []
    for i, (name, type_, desc, fields, cost) in enumerate(SEED_TEMPLATES, start=1):
        out.append({
            "id": i,
            "name": name,
            "type": type_,
            "description": desc or "",
            "unique_fields": list(fields) + list(NOTIFY_FIELDS),
            "est_cost": cost or "",
            "ephemeral": True,
        })
    out.sort(key=lambda t: _sort_key_type_name(t.get("type"), t.get("name")))
    return out


def _load_rows(db: Session) -> list:
    rows = (
        db.query(models.AgentTemplate)
        .order_by(models.AgentTemplate.id.asc())
        .all()
    )
    rows = sorted(rows, key=lambda t: _sort_key_type_name(t.type, t.name))
    return rows


def _count_templates(db: Session) -> int:
    return int(db.query(models.AgentTemplate).count() or 0)


@router.get("/")
def list_templates(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Return agent template catalogue — never empty when SEED_TEMPLATES is set.

    Path: GET /api/templates/  (and /templates/ locally)

    Demo / production tokens all hit this path. If Postgres is empty (new Neon
    branch, failed cold-start seed), we re-seed on read. If the DB is down, we
    still return the in-code catalogue so spawn UI is usable.

    Empty-catalog race: concurrent cold starts may both see count=0. We seed,
    re-load, and if the table is still empty (commit race / read replica lag /
    ephemeral sqlite), serve the in-memory SEED_TEMPLATES catalogue.
    """
    if not SEED_TEMPLATES:
        return []

    count = None
    try:
        count = _count_templates(db)
    except Exception as e:
        _safe_rollback(db)
        print(f"[templates] count failed: {e}")
        return _catalog_fallback()

    # Seed when empty or incomplete vs code catalogue
    if count < _EXPECTED_COUNT:
        try:
            added = _ensure_templates(db)
            if added:
                print(f"[templates] seeded {added} missing template(s) on list "
                      f"(was {count}, expected {_EXPECTED_COUNT})")
        except Exception as e:
            _safe_rollback(db)
            print(f"[templates] ensure failed: {e}")

    try:
        rows = _load_rows(db)
    except Exception as e:
        _safe_rollback(db)
        print(f"[templates] load failed: {e}")
        return _catalog_fallback()

    if not rows:
        # Last attempt — ensure again after rollback, then fall back to memory
        try:
            _ensure_templates(db)
            rows = _load_rows(db)
        except Exception as e:
            _safe_rollback(db)
            print(f"[templates] re-ensure failed: {e}")
            return _catalog_fallback()

    if not rows:
        print("[templates] DB empty after ensure — serving in-memory catalogue")
        return _catalog_fallback()

    return [_row_out(t) for t in rows]


@router.post("/ensure")
def ensure_templates(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Force re-seed missing templates (staff/debug / SPA retry button).

    Path: POST /api/templates/ensure
    """
    try:
        n = _ensure_templates(db)
        total = _count_templates(db)
        # If DB still empty, report fallback size so SPA knows catalogue exists
        if total == 0 and _EXPECTED_COUNT:
            return {
                "ok": True,
                "added": n,
                "total": 0,
                "expected": _EXPECTED_COUNT,
                "fallback": len(SEED_TEMPLATES),
                "note": "db empty; GET /templates/ will serve in-memory catalogue",
            }
        return {"ok": True, "added": n, "total": total, "expected": _EXPECTED_COUNT}
    except Exception as e:
        _safe_rollback(db)
        print(f"[templates] POST /ensure failed: {e}")
        return {
            "ok": False,
            "added": 0,
            "total": 0,
            "expected": _EXPECTED_COUNT,
            "error": str(e)[:200],
            "fallback": len(SEED_TEMPLATES),
        }
