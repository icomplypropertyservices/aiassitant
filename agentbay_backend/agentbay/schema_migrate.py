"""Lightweight column / table adds for existing AgentBay DBs."""
from sqlalchemy import text, inspect
from .database import engine, Base
from . import models  # noqa: F401 — register models


def _cols(table: str) -> set[str]:
    try:
        insp = inspect(engine)
        return {c["name"] for c in insp.get_columns(table)}
    except Exception:
        return set()


def _tables() -> set[str]:
    try:
        insp = inspect(engine)
        return set(insp.get_table_names())
    except Exception:
        return set()


def _ts_type() -> str:
    """Postgres rejects DATETIME; use TIMESTAMP. SQLite accepts both."""
    try:
        name = (engine.dialect.name or "").lower()
    except Exception:
        name = ""
    return "TIMESTAMP" if name in ("postgresql", "postgres") else "DATETIME"


def migrate():
    """Add missing columns/tables for escrow + seller payouts."""
    statements: list[str] = []
    tables = _tables()
    ts = _ts_type()

    # Ensure new tables exist (create_all also runs at boot)
    if "bay_seller_payout_profiles" not in tables:
        try:
            Base.metadata.create_all(
                bind=engine,
                tables=[models.SellerPayoutProfile.__table__],
            )
            print("[migrate] created bay_seller_payout_profiles")
        except Exception as e:
            print(f"[migrate] create payout table: {e}")

    order_cols = _cols("bay_orders")
    if order_cols:
        adds = {
            "payment_method": "ALTER TABLE bay_orders ADD COLUMN payment_method VARCHAR DEFAULT 'stripe'",
            "crypto_chain": "ALTER TABLE bay_orders ADD COLUMN crypto_chain VARCHAR DEFAULT ''",
            "crypto_tx_hash": "ALTER TABLE bay_orders ADD COLUMN crypto_tx_hash VARCHAR DEFAULT ''",
            "platform_fee": "ALTER TABLE bay_orders ADD COLUMN platform_fee FLOAT DEFAULT 0",
            "seller_net": "ALTER TABLE bay_orders ADD COLUMN seller_net FLOAT DEFAULT 0",
            "payout_status": "ALTER TABLE bay_orders ADD COLUMN payout_status VARCHAR DEFAULT 'none'",
            "payout_method": "ALTER TABLE bay_orders ADD COLUMN payout_method VARCHAR DEFAULT ''",
            "payout_reference": "ALTER TABLE bay_orders ADD COLUMN payout_reference VARCHAR DEFAULT ''",
            "payout_notes": "ALTER TABLE bay_orders ADD COLUMN payout_notes TEXT DEFAULT ''",
            "payout_destination_json": "ALTER TABLE bay_orders ADD COLUMN payout_destination_json TEXT DEFAULT '{}'",
            "escrow_held_at": f"ALTER TABLE bay_orders ADD COLUMN escrow_held_at {ts}",
            "seller_delivered_at": f"ALTER TABLE bay_orders ADD COLUMN seller_delivered_at {ts}",
            "buyer_confirmed_at": f"ALTER TABLE bay_orders ADD COLUMN buyer_confirmed_at {ts}",
            "payout_released_at": f"ALTER TABLE bay_orders ADD COLUMN payout_released_at {ts}",
            "payout_released_by": "ALTER TABLE bay_orders ADD COLUMN payout_released_by INTEGER",
        }
        for col, sql in adds.items():
            if col not in order_cols:
                statements.append(sql)

    user_cols = _cols("bay_users")
    if user_cols and "main_user_id" not in user_cols:
        statements.append("ALTER TABLE bay_users ADD COLUMN main_user_id INTEGER")

    if not statements:
        return
    # One statement per transaction so a single bad SQL does not abort the rest
    # (Postgres: InFailedSqlTransaction after first error in a txn).
    for sql in statements:
        try:
            with engine.begin() as conn:
                conn.execute(text(sql))
            print(f"[migrate] {sql}")
        except Exception as e:
            print(f"[migrate] skip: {e}")
