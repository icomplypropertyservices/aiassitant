"""Lightweight SQLite column adds for existing DBs."""
from sqlalchemy import text, inspect
from .database import engine


def _cols(table: str) -> set[str]:
    try:
        insp = inspect(engine)
        return {c["name"] for c in insp.get_columns(table)}
    except Exception:
        return set()


def migrate():
    """Add columns on bay_* tables (create_all handles new tables)."""
    statements = []
    user_cols = _cols("bay_users")
    if user_cols and "main_user_id" not in user_cols:
        statements.append("ALTER TABLE bay_users ADD COLUMN main_user_id INTEGER")

    if not statements:
        return
    with engine.begin() as conn:
        for sql in statements:
            try:
                conn.execute(text(sql))
                print(f"[migrate] {sql}")
            except Exception as e:
                print(f"[migrate] skip: {e}")
