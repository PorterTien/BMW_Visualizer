from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from backend.config import DATABASE_URL

_db_url = DATABASE_URL
# Normalize Railway's postgres:// and postgresql:// to psycopg2 driver
if _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql+psycopg2://", 1)
elif _db_url.startswith("postgresql://") and "+psycopg" not in _db_url:
    _db_url = _db_url.replace("postgresql://", "postgresql+psycopg2://", 1)

connect_args = {}
is_sqlite = _db_url.startswith("sqlite")

if is_sqlite:
    connect_args = {"check_same_thread": False}

if is_sqlite:
    engine = create_engine(_db_url, connect_args=connect_args, echo=False)
else:
    # PostgreSQL: keep a pool of persistent connections so each request
    # doesn't pay the ~100-200ms cost of a new TCP handshake to Supabase.
    engine = create_engine(
        _db_url,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=300,      # recycle connections every 5 min
        pool_pre_ping=True,    # test connection health before use
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

    # Ensure filter-column indices exist (idempotent via IF NOT EXISTS)
    filter_indices = [
        ("ix_company_type", "companies", "company_type"),
        ("ix_company_status", "companies", "company_status"),
        ("ix_supply_chain_segment", "companies", "supply_chain_segment"),
        ("ix_company_hq_country", "companies", "company_hq_country"),
    ]
    with engine.connect() as conn:
        for idx_name, table, col in filter_indices:
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} ({col})"))
            conn.commit()
