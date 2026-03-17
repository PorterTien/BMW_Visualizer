from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from backend.config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from backend import models  # noqa: F401
    Base.metadata.create_all(bind=engine)


def migrate_db():
    """Add new columns to existing tables without dropping data."""
    new_columns = [
        ("market_cap_usd", "REAL"),
        ("revenue_usd", "REAL"),
        ("total_funding_usd", "REAL"),
        ("hq_company", "TEXT"),
        ("hq_company_website", "TEXT"),
        ("chemistries", "TEXT"),
        ("feedstock", "TEXT"),
        ("contact_name", "TEXT"),
        ("contact_email", "TEXT"),
        ("contact_phone", "TEXT"),
        ("notes", "TEXT"),
    ]
    with engine.connect() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(companies)"))}
        for col, col_type in new_columns:
            if col not in existing:
                conn.execute(text(f"ALTER TABLE companies ADD COLUMN {col} {col_type}"))
                conn.commit()
