import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
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

engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
