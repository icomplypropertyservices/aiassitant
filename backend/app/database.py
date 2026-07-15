from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from . import config

url = config.DATABASE_URL
connect_args = {}
if url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
