import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool
from . import config

url = config.DATABASE_URL
# Vercel serverless: prefer Postgres. SQLite on /tmp is ephemeral (dev only).
if os.getenv("VERCEL") and url.startswith("sqlite"):
    # Allow cold-start demos but data will reset; set DATABASE_URL to Neon/Postgres for real use.
    url = "sqlite:////tmp/ai_assistant.db"

connect_args = {}
if url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
elif url.startswith("postgres") and "sslmode" not in url and "localhost" not in url:
    # Many managed Postgres providers require SSL
    sep = "&" if "?" in url else "?"
    url = f"{url}{sep}sslmode=require"

# Serverless: NullPool avoids holding stale connections across freezes and is
# faster/safer on short-lived Vercel instances than a queue pool.
_engine_kwargs: dict = {"connect_args": connect_args}
if os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
    _engine_kwargs["poolclass"] = NullPool
else:
    _engine_kwargs["pool_pre_ping"] = True

engine = create_engine(url, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
