"""
Idempotent schema upgrades for SQLite and Postgres.

SQLAlchemy create_all only creates missing *tables*, not missing *columns*.
Production Neon DBs created before newer model fields need ALTER TABLE.
"""
from __future__ import annotations

import logging
from typing import Iterable

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

log = logging.getLogger("schema_migrate")

# table -> list of (column_name, sql_type_decl)
# Types are portable-ish: INTEGER/BIGINT, TEXT, REAL/FLOAT, BOOLEAN, TIMESTAMP
COLUMN_ADDS: dict[str, list[tuple[str, str]]] = {
    "users": [
        ("subscription_active", "BOOLEAN DEFAULT FALSE"),
        ("subscription_expires_at", "TIMESTAMP"),
        ("plan", "TEXT DEFAULT 'none'"),
        ("role", "TEXT DEFAULT 'user'"),
        ("name", "TEXT DEFAULT ''"),
        # Auth: JWT revoke counter + email ownership
        ("token_version", "INTEGER DEFAULT 0"),
        ("email_verified", "BOOLEAN DEFAULT FALSE"),
    ],
    # Auth token tables (create_all creates them; COLUMN_ADDS covers partial older schemas)
    "email_tokens": [
        ("user_id", "INTEGER"),
        ("purpose", "TEXT DEFAULT 'verify'"),
        ("token_hash", "TEXT"),
        ("expires_at", "TIMESTAMP"),
        ("used_at", "TIMESTAMP"),
        ("created_at", "TIMESTAMP"),
    ],
    "password_reset_tokens": [
        ("user_id", "INTEGER"),
        ("token_hash", "TEXT"),
        ("expires_at", "TIMESTAMP"),
        ("used_at", "TIMESTAMP"),
        ("created_at", "TIMESTAMP"),
    ],
    "email_verification_tokens": [
        ("user_id", "INTEGER"),
        ("token_hash", "TEXT"),
        ("expires_at", "TIMESTAMP"),
        ("used_at", "TIMESTAMP"),
        ("created_at", "TIMESTAMP"),
    ],
    "balances": [
        ("tokens_included", "INTEGER DEFAULT 0"),
        ("tokens_used_period", "INTEGER DEFAULT 0"),
        ("period_start", "TIMESTAMP"),
        ("credits", "DOUBLE PRECISION DEFAULT 0"),
        ("auto_topup_enabled", "BOOLEAN DEFAULT FALSE"),
        ("auto_topup_amount", "DOUBLE PRECISION DEFAULT 25"),
        ("auto_topup_threshold_credits", "DOUBLE PRECISION DEFAULT 5"),
        ("auto_topup_token_pct", "INTEGER DEFAULT 85"),
        ("auto_topup_last_at", "TIMESTAMP"),
    ],
    "agents": [
        ("company_id", "INTEGER"),
        ("project_id", "INTEGER"),
        ("parent_id", "INTEGER"),
        ("hierarchy_role", "TEXT DEFAULT 'member'"),
        ("is_lead", "BOOLEAN DEFAULT FALSE"),
        ("permission_level", "TEXT DEFAULT 'operator'"),
        ("escalate_when", "TEXT DEFAULT 'on_failure'"),
        ("escalate_reason", "TEXT DEFAULT ''"),
        ("escalate_to", "TEXT DEFAULT 'parent'"),
        ("escalate_human_id", "INTEGER"),
        ("idle_mode", "TEXT DEFAULT 'allow_idle'"),
        ("config", "TEXT DEFAULT '{}'"),
        ("personality", "TEXT DEFAULT ''"),
        ("model", "TEXT DEFAULT 'vps-fast'"),
        ("status", "TEXT DEFAULT 'active'"),
    ],
    "tasks": [
        ("project_id", "INTEGER"),
        ("company_id", "INTEGER"),
        ("human_id", "INTEGER"),
        ("assignee_type", "TEXT DEFAULT 'agent'"),
        ("title", "TEXT DEFAULT ''"),
        ("result", "TEXT DEFAULT ''"),
        ("priority", "TEXT DEFAULT 'medium'"),
        ("labels", "TEXT DEFAULT ''"),
        ("tokens_used", "INTEGER DEFAULT 0"),
        ("cost", "DOUBLE PRECISION DEFAULT 0"),
        ("completed_at", "TIMESTAMP"),
        ("updated_at", "TIMESTAMP"),
        ("user_id", "INTEGER"),
        ("agent_id", "INTEGER"),
        ("description", "TEXT DEFAULT ''"),
        ("status", "TEXT DEFAULT 'queued'"),
    ],
    "token_usage": [
        ("company_id", "INTEGER"),
        ("project_id", "INTEGER"),
        ("bill_source", "TEXT DEFAULT 'included'"),
        ("cost", "DOUBLE PRECISION DEFAULT 0"),
        ("input_tokens", "INTEGER DEFAULT 0"),
        ("output_tokens", "INTEGER DEFAULT 0"),
    ],
    "conversations": [
        ("project_id", "INTEGER"),
        ("agent_id", "INTEGER"),
        ("mode", "TEXT DEFAULT 'general'"),
        ("title", "TEXT DEFAULT 'New conversation'"),
    ],
    "humans": [
        ("email", "TEXT DEFAULT ''"),
        ("role_title", "TEXT DEFAULT ''"),
        ("skills", "TEXT DEFAULT ''"),
        ("company_id", "INTEGER"),
        ("project_id", "INTEGER"),
        ("status", "TEXT DEFAULT 'active'"),
        ("capacity", "INTEGER DEFAULT 5"),
        ("permission_level", "TEXT DEFAULT 'operator'"),
        ("escalate_when", "TEXT DEFAULT 'on_blocked'"),
        ("escalate_reason", "TEXT DEFAULT ''"),
        ("escalate_to", "TEXT DEFAULT 'orchestrator'"),
        ("notes", "TEXT DEFAULT ''"),
        ("updated_at", "TIMESTAMP"),
    ],
    "diary_entries": [
        ("deal_id", "INTEGER"),
        ("owner_human_id", "INTEGER"),
        ("owner_agent_id", "INTEGER"),
        ("completed_at", "TIMESTAMP"),
        ("location", "TEXT DEFAULT ''"),
        ("notes", "TEXT DEFAULT ''"),
        ("status", "TEXT DEFAULT 'scheduled'"),
        ("end_at", "TIMESTAMP"),
        ("start_at", "TIMESTAMP"),
        ("updated_at", "TIMESTAMP"),
    ],
    "crypto_invoices": [
        ("public_id", "TEXT"),
        ("chain", "TEXT"),
        ("kind", "TEXT DEFAULT 'plan'"),
        ("plan", "TEXT DEFAULT ''"),
        ("company_name", "TEXT DEFAULT ''"),
        ("amount_usd", "DOUBLE PRECISION DEFAULT 0"),
        ("amount_crypto", "DOUBLE PRECISION DEFAULT 0"),
        ("asset_symbol", "TEXT DEFAULT ''"),
        ("receive_address", "TEXT DEFAULT ''"),
        ("dest_tag", "INTEGER"),
        ("status", "TEXT DEFAULT 'pending'"),
        ("tx_hash", "TEXT DEFAULT ''"),
        ("expires_at", "TIMESTAMP"),
        ("paid_at", "TIMESTAMP"),
        ("note", "TEXT DEFAULT ''"),
    ],
    "customers": [
        ("company_id", "INTEGER"),
        ("email", "TEXT DEFAULT ''"),
        ("phone", "TEXT DEFAULT ''"),
        ("job_title", "TEXT DEFAULT ''"),
        ("account_name", "TEXT DEFAULT ''"),
        ("website", "TEXT DEFAULT ''"),
        ("industry", "TEXT DEFAULT ''"),
        ("address", "TEXT DEFAULT ''"),
        ("city", "TEXT DEFAULT ''"),
        ("country", "TEXT DEFAULT ''"),
        ("status", "TEXT DEFAULT 'active'"),
        ("source", "TEXT DEFAULT ''"),
        ("tags", "TEXT DEFAULT ''"),
        ("owner_human_id", "INTEGER"),
        ("owner_agent_id", "INTEGER"),
        ("annual_value", "DOUBLE PRECISION DEFAULT 0"),
        ("notes", "TEXT DEFAULT ''"),
        ("meta_json", "TEXT DEFAULT '{}'"),
        ("last_contacted_at", "TIMESTAMP"),
        ("updated_at", "TIMESTAMP"),
    ],
    "deals": [
        ("company_id", "INTEGER"),
        ("value", "DOUBLE PRECISION DEFAULT 0"),
        ("currency", "TEXT DEFAULT 'USD'"),
        ("status", "TEXT DEFAULT 'open'"),
        ("priority", "TEXT DEFAULT 'medium'"),
        ("expected_close", "TIMESTAMP"),
        ("owner_human_id", "INTEGER"),
        ("owner_agent_id", "INTEGER"),
        ("position", "INTEGER DEFAULT 0"),
        ("description", "TEXT DEFAULT ''"),
        ("lost_reason", "TEXT DEFAULT ''"),
        ("updated_at", "TIMESTAMP"),
        ("closed_at", "TIMESTAMP"),
    ],
}


def _is_postgres(engine: Engine) -> bool:
    return engine.dialect.name in ("postgresql", "postgres")


def _is_sqlite(engine: Engine) -> bool:
    return engine.dialect.name == "sqlite"


def _existing_columns(engine: Engine, table: str) -> set[str]:
    insp = inspect(engine)
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def _sqlite_type(decl: str) -> str:
    d = decl.upper()
    if "DOUBLE" in d or "FLOAT" in d or "REAL" in d:
        return decl.replace("DOUBLE PRECISION", "REAL")
    if "BOOLEAN" in d:
        return decl.replace("BOOLEAN", "INTEGER").replace("FALSE", "0").replace("TRUE", "1")
    if "TIMESTAMP" in d:
        return decl.replace("TIMESTAMP", "DATETIME")
    return decl


# Tables that must exist after migrate (create_all). Missing ⇒ log warning.
AUTH_TABLES = (
    "email_tokens",
    "password_reset_tokens",
    "email_verification_tokens",
)


def ensure_schema(engine: Engine) -> dict:
    """create_all + add any missing columns. Safe to call on every cold start."""
    from .database import Base
    from . import models  # noqa: F401 — register metadata (User auth cols + token tables)

    report: dict = {
        "created_tables": False,
        "added": [],
        "errors": [],
        "auth_tables": [],
        "auth_missing": [],
    }
    try:
        # Creates password_reset_tokens, email_verification_tokens, email_tokens, etc.
        Base.metadata.create_all(bind=engine)
        report["created_tables"] = True
    except Exception as e:
        report["errors"].append(f"create_all: {e}")
        log.exception("create_all failed")

    insp = inspect(engine)
    tables = set(insp.get_table_names())
    pg = _is_postgres(engine)
    sqlite = _is_sqlite(engine)

    for name in AUTH_TABLES:
        if name in tables:
            report["auth_tables"].append(name)
        else:
            report["auth_missing"].append(name)
            log.warning("Auth table missing after create_all: %s", name)

    for table, cols in COLUMN_ADDS.items():
        if table not in tables:
            continue
        existing = _existing_columns(engine, table)
        for col, decl in cols:
            if col in existing:
                continue
            sql_decl = _sqlite_type(decl) if sqlite else decl
            try:
                if pg:
                    stmt = text(f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS "{col}" {sql_decl}')
                else:
                    stmt = text(f"ALTER TABLE {table} ADD COLUMN {col} {sql_decl}")
                with engine.begin() as conn:
                    conn.execute(stmt)
                report["added"].append(f"{table}.{col}")
                log.info("Added column %s.%s", table, col)
            except Exception as e:
                msg = f"{table}.{col}: {e}"
                report["errors"].append(msg)
                log.warning("Could not add %s: %s", f"{table}.{col}", e)

    # Re-check users auth columns after ALTERs (for reporting)
    if "users" in tables:
        ucols = _existing_columns(engine, "users")
        for col in ("token_version", "email_verified"):
            if col not in ucols:
                report["errors"].append(f"users.{col} still missing after migrate")
                log.error("users.%s still missing after migrate", col)

    return report
