from sqlalchemy import create_engine, event, text
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

    # SQLite doesn't enforce foreign keys unless PRAGMA is set per connection,
    # which means CASCADE deletes (e.g. Partnership → PartnershipMember) are
    # silently skipped and orphan rows accumulate. Flip it on for every
    # connection the pool hands out.
    @event.listens_for(engine, "connect")
    def _sqlite_fk_on(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()
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
        ("number_of_employees", "INTEGER"),
        ("last_fundraise_date", "TEXT"),
        ("keywords", "TEXT"),
        ("extra_description", "TEXT"),
        ("naatbatt_id", "TEXT"),
        ("contact_email2", "TEXT"),
        ("sources", "TEXT"),
        ("sources2", "TEXT"),
        ("qc", "TEXT"),
        ("qc_date", "TEXT"),
        ("summary_word_count", "INTEGER"),
        ("employee_size", "TEXT"),
        ("funding_status", "TEXT"),
        ("crunchbase_url", "TEXT"),
        ("linkedin_url", "TEXT"),
        ("pitchbook_url", "TEXT"),
        ("volta_member", "INTEGER"),
        ("volta_verified", "INTEGER"),
        ("products", "TEXT"),
        ("product_services_desc", "TEXT"),
        ("battery_chemistry_flags", "TEXT"),
        ("supply_chain_flags", "TEXT"),
        ("gwh_capacity", "TEXT"),
        ("plant_start_date", "TEXT"),
        ("data_source", "TEXT"),
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

    # watchlist.user_id was added after the initial ship. Back-fill on old DBs
    # so per-user watchlist queries don't crash with "no such column". We also
    # need to drop the legacy single-column UNIQUE(company_id) constraint —
    # that made sense pre-auth when the watchlist was global, but today
    # different users can (and must) be able to watch the same company.
    with engine.connect() as conn:
        if dialect == "sqlite":
            existing = {row[1] for row in conn.execute(text("PRAGMA table_info(watchlist)"))}
            if "user_id" not in existing:
                conn.execute(text("ALTER TABLE watchlist ADD COLUMN user_id TEXT"))
                conn.commit()
            # SQLite can't drop a column-level UNIQUE in place — detect + recreate.
            schema = conn.execute(
                text("SELECT sql FROM sqlite_master WHERE type='table' AND name='watchlist'"),
            ).scalar() or ""
            if "UNIQUE (company_id)" in schema.replace("  ", " "):
                conn.execute(text("ALTER TABLE watchlist RENAME TO watchlist__legacy"))
                conn.execute(text(
                    "CREATE TABLE watchlist ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "company_id INTEGER NOT NULL, "
                    "user_id TEXT, "
                    "added_at TEXT, "
                    "FOREIGN KEY(company_id) REFERENCES companies(id))"
                ))
                conn.execute(text(
                    "INSERT INTO watchlist (id, company_id, user_id, added_at) "
                    "SELECT id, company_id, user_id, added_at FROM watchlist__legacy"
                ))
                conn.execute(text("DROP TABLE watchlist__legacy"))
                conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ux_watchlist_user_company "
                    "ON watchlist (user_id, company_id)"
                ))
                conn.commit()
        elif dialect == "postgresql":
            existing = {
                row[0] for row in conn.execute(text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'watchlist'"
                ))
            }
            if "user_id" not in existing:
                conn.execute(text("ALTER TABLE watchlist ADD COLUMN user_id TEXT"))
                conn.commit()
            # Drop any UNIQUE constraint that targets only company_id.
            rows = conn.execute(text(
                "SELECT tc.constraint_name "
                "FROM information_schema.table_constraints tc "
                "JOIN information_schema.constraint_column_usage ccu "
                "  ON tc.constraint_name = ccu.constraint_name "
                "WHERE tc.table_name = 'watchlist' AND tc.constraint_type = 'UNIQUE' "
                "  AND ccu.column_name = 'company_id' "
                "GROUP BY tc.constraint_name "
                "HAVING COUNT(*) = 1"
            )).fetchall()
            for (cname,) in rows:
                conn.execute(text(f'ALTER TABLE watchlist DROP CONSTRAINT "{cname}"'))
                conn.commit()
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_watchlist_user_company "
                "ON watchlist (user_id, company_id)"
            ))
            conn.commit()

    # ── Multi-list watchlist migration ────────────────────────────────────────
    # 1. Create watchlist_lists table (idempotent via create_all above)
    # 2. Add list_id column to watchlist
    # 3. Migrate existing entries: create a default "My Watchlist" per user,
    #    then point all their orphan entries at it.
    # 4. Drop old unique index and create the new 3-column one.
    with engine.connect() as conn:
        if dialect == "sqlite":
            wl_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(watchlist)"))}
            if "list_id" not in wl_cols:
                conn.execute(text("ALTER TABLE watchlist ADD COLUMN list_id INTEGER REFERENCES watchlist_lists(id) ON DELETE CASCADE"))
                conn.commit()
            # Migrate existing entries that have no list_id
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()
            # Distinct user_ids with un-assigned entries
            orphan_users = conn.execute(
                text("SELECT DISTINCT user_id FROM watchlist WHERE list_id IS NULL AND user_id IS NOT NULL")
            ).fetchall()
            for (uid,) in orphan_users:
                existing_default = conn.execute(
                    text("SELECT id FROM watchlist_lists WHERE user_id = :u AND name = 'My Watchlist'"),
                    {"u": uid},
                ).fetchone()
                if existing_default:
                    lid = existing_default[0]
                else:
                    conn.execute(
                        text("INSERT INTO watchlist_lists (user_id, name, created_at) VALUES (:u, 'My Watchlist', :t)"),
                        {"u": uid, "t": now},
                    )
                    conn.commit()
                    lid = conn.execute(
                        text("SELECT id FROM watchlist_lists WHERE user_id = :u AND name = 'My Watchlist'"),
                        {"u": uid},
                    ).fetchone()[0]
                conn.execute(
                    text("UPDATE watchlist SET list_id = :l WHERE user_id = :u AND list_id IS NULL"),
                    {"l": lid, "u": uid},
                )
                conn.commit()
            # Drop old unique index and create new one
            conn.execute(text("DROP INDEX IF EXISTS ux_watchlist_user_company"))
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_watchlist_user_company_list "
                "ON watchlist (user_id, company_id, list_id)"
            ))
            conn.commit()
        elif dialect == "postgresql":
            pg_wl_cols = {
                row[0] for row in conn.execute(text(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = 'watchlist'"
                ))
            }
            if "list_id" not in pg_wl_cols:
                conn.execute(text(
                    "ALTER TABLE watchlist ADD COLUMN list_id INTEGER "
                    "REFERENCES watchlist_lists(id) ON DELETE CASCADE"
                ))
                conn.commit()
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()
            orphan_users = conn.execute(
                text("SELECT DISTINCT user_id FROM watchlist WHERE list_id IS NULL AND user_id IS NOT NULL")
            ).fetchall()
            for (uid,) in orphan_users:
                existing_default = conn.execute(
                    text("SELECT id FROM watchlist_lists WHERE user_id = :u AND name = 'My Watchlist'"),
                    {"u": uid},
                ).fetchone()
                if existing_default:
                    lid = existing_default[0]
                else:
                    conn.execute(
                        text("INSERT INTO watchlist_lists (user_id, name, created_at) VALUES (:u, 'My Watchlist', :t)"),
                        {"u": uid, "t": now},
                    )
                    conn.commit()
                    lid = conn.execute(
                        text("SELECT id FROM watchlist_lists WHERE user_id = :u AND name = 'My Watchlist'"),
                        {"u": uid},
                    ).fetchone()[0]
                conn.execute(
                    text("UPDATE watchlist SET list_id = :l WHERE user_id = :u AND list_id IS NULL"),
                    {"l": lid, "u": uid},
                )
                conn.commit()
            conn.execute(text("DROP INDEX IF EXISTS ux_watchlist_user_company"))
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_watchlist_user_company_list "
                "ON watchlist (user_id, company_id, list_id)"
            ))
            conn.commit()

    # Ensure filter-column indices exist (idempotent via IF NOT EXISTS)
    filter_indices = [
        ("ix_company_type", "companies", "company_type"),
        ("ix_company_status", "companies", "company_status"),
        ("ix_supply_chain_segment", "companies", "supply_chain_segment"),
        ("ix_company_hq_country", "companies", "company_hq_country"),
        ("ix_watchlist_user", "watchlist", "user_id"),
        ("ix_watchlist_company", "watchlist", "company_id"),
        ("ix_watchlist_list", "watchlist", "list_id"),
        ("ix_watchlist_lists_user", "watchlist_lists", "user_id"),
    ]
    with engine.connect() as conn:
        for idx_name, table, col in filter_indices:
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} ({col})"))
            conn.commit()
