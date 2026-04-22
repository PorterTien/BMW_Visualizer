from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from backend.config import DATABASE_URL

_db_url = DATABASE_URL
if _db_url.startswith("postgresql://") or _db_url.startswith("postgresql+psycopg2://"):
    _db_url = _db_url.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)
    _db_url = _db_url.replace("postgresql://", "postgresql+psycopg://", 1)

connect_args = {}
if _db_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    _db_url,
    connect_args=connect_args,
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
    # Ensure new tables exist (idempotent)
    from backend import models  # noqa: F401
    Base.metadata.create_all(bind=engine)

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
        ("industry_segment", "TEXT"),
        ("description", "TEXT"),
        ("founding_year", "INTEGER"),
        ("logo_url", "TEXT"),
        ("manual_overrides", "TEXT"),
    ]
    dialect = engine.dialect.name
    with engine.connect() as conn:
        if dialect == "sqlite":
            existing = {row[1] for row in conn.execute(text("PRAGMA table_info(companies)"))}
            for col, col_type in new_columns:
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE companies ADD COLUMN {col} {col_type}"))
                    conn.commit()
        elif dialect == "postgresql":
            existing = {
                row[0] for row in conn.execute(text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'companies'"
                ))
            }
            pg_type_map = {"REAL": "DOUBLE PRECISION", "INTEGER": "INTEGER", "TEXT": "TEXT"}
            for col, col_type in new_columns:
                if col not in existing:
                    pg_type = pg_type_map.get(col_type, "TEXT")
                    conn.execute(text(f"ALTER TABLE companies ADD COLUMN {col} {pg_type}"))
                    conn.commit()
