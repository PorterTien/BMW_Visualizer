from sqlalchemy import Column, Index, Integer, Text, Float, ForeignKey
from sqlalchemy.orm import relationship
from backend.database import Base


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_name = Column(Text, nullable=False, unique=True)
    industry_segment = Column(Text)       # cell_manufacturing, materials_mining, recycling, ev_oem, energy_storage, other
    description = Column(Text)            # extended overview
    founding_year = Column(Integer)
    logo_url = Column(Text)
    company_hq_city = Column(Text)
    company_hq_state = Column(Text)
    company_hq_country = Column(Text)
    company_hq_lat = Column(Float)
    company_hq_lng = Column(Float)
    company_locations = Column(Text)          # JSON array
    company_type = Column(Text)
    company_status = Column(Text)
    company_focus = Column(Text)              # JSON array
    supply_chain_segment = Column(Text)
    keywords = Column(Text)                   # JSON array
    announced_partners = Column(Text)         # JSON array of objects
    number_of_employees = Column(Integer)
    market_cap_usd = Column(Float)        # in millions USD
    revenue_usd = Column(Float)           # in millions USD
    total_funding_usd = Column(Float)     # in millions USD
    last_fundraise_date = Column(Text)
    company_website = Column(Text)
    hq_company = Column(Text)             # parent company name
    hq_company_website = Column(Text)
    chemistries = Column(Text)            # battery chemistries (comma-separated)
    feedstock = Column(Text)              # feedstock / raw material input
    contact_name = Column(Text)
    contact_email = Column(Text)
    contact_phone = Column(Text)
    notes = Column(Text)
    summary = Column(Text)
    long_description = Column(Text)
    extra_description = Column(Text)      # Column1 from XLSX (additional profile text)
    naatbatt_member = Column(Integer, default=0)
    naatbatt_id = Column(Text)
    contact_email2 = Column(Text)         # second contact email
    sources = Column(Text)                # data sources/references (aggregated)
    sources2 = Column(Text)               # additional sources
    qc = Column(Text)                     # QC reviewer initials (aggregated)
    qc_date = Column(Text)               # QC date (aggregated)
    summary_word_count = Column(Integer)  # word count of summary
    # BBD (Volta Foundation) fields
    employee_size = Column(Text)          # e.g. "11-50", "501-1000"
    funding_status = Column(Text)         # e.g. "Private", "Public", "Acquired"
    crunchbase_url = Column(Text)
    linkedin_url = Column(Text)
    pitchbook_url = Column(Text)
    volta_member = Column(Integer, default=0)
    volta_verified = Column(Integer, default=0)
    products = Column(Text)               # product list
    product_services_desc = Column(Text)  # product/services description
    battery_chemistry_flags = Column(Text)  # JSON obj of chemistry booleans
    supply_chain_flags = Column(Text)     # JSON obj of supply chain booleans
    # Gigafactory fields
    gwh_capacity = Column(Text)           # JSON: {"2022": 60, "2023": 65, ...}
    plant_start_date = Column(Text)       # earliest plant start date
    last_updated = Column(Text)
    data_source = Column(Text)
    manual_overrides = Column(Text)          # JSON list of field names manually set by user


Index("ix_company_name", Company.company_name)
Index("ix_company_type", Company.company_type)
Index("ix_company_status", Company.company_status)
Index("ix_supply_chain_segment", Company.supply_chain_segment)
Index("ix_company_hq_country", Company.company_hq_country)


class NewsHeadline(Base):
    __tablename__ = "news_headlines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"))
    company_name = Column(Text)
    news_headline = Column(Text, nullable=False)
    category = Column(Text)
    partners = Column(Text)                   # JSON array
    news_source = Column(Text)
    date_of_article = Column(Text)
    location = Column(Text)
    topics = Column(Text)                     # JSON array
    url = Column(Text)
    summary = Column(Text)
    created_at = Column(Text)


Index("ix_news_company_id", NewsHeadline.company_id)


class SyncLog(Base):
    __tablename__ = "sync_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(Text)
    status = Column(Text)
    rows_added = Column(Integer)
    rows_updated = Column(Integer)
    error_message = Column(Text)
    run_at = Column(Text)


class ResearchJob(Base):
    __tablename__ = "research_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_type = Column(Text)
    status = Column(Text, default="pending")
    target = Column(Text)
    result = Column(Text)
    created_at = Column(Text)
    updated_at = Column(Text)


class Partnership(Base):
    __tablename__ = "partnerships"

    id = Column(Integer, primary_key=True, autoincrement=True)
    partnership_name = Column(Text)
    partnership_type = Column(Text)       # jv, supply_agreement, licensing, equity_stake, r_and_d_collab, government_grant, other
    stage = Column(Text)                  # announced, signed, active, dissolved
    direction = Column(Text)              # supplier_to_buyer, investor_to_investee, bidirectional
    date_announced = Column(Text)
    date_effective = Column(Text)
    date_expiration = Column(Text)
    deal_value = Column(Float)            # in millions USD
    deal_currency = Column(Text, default="USD")
    scope = Column(Text)                  # description of what the partnership covers
    geography = Column(Text)
    industry_segment = Column(Text)       # cell_manufacturing, materials_mining, recycling, ev_oem, energy_storage, other
    source_name = Column(Text)
    source_url = Column(Text)
    date_sourced = Column(Text)
    created_at = Column(Text)
    updated_at = Column(Text)

    members = relationship("PartnershipMember", back_populates="partnership", cascade="all, delete-orphan")


Index("ix_partnership_type", Partnership.partnership_type)


class PartnershipMember(Base):
    __tablename__ = "partnership_members"

    id = Column(Integer, primary_key=True, autoincrement=True)
    partnership_id = Column(Integer, ForeignKey("partnerships.id", ondelete="CASCADE"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    role = Column(Text)                   # supplier, buyer, investor, investee, partner

    partnership = relationship("Partnership", back_populates="members")


Index("ix_pm_partnership", PartnershipMember.partnership_id)
Index("ix_pm_company", PartnershipMember.company_id)


class CompanyFacility(Base):
    __tablename__ = "company_facilities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    facility_name = Column(Text)
    address = Column(Text)
    city = Column(Text)
    state = Column(Text)
    country = Column(Text)
    zip_code = Column(Text)
    lat = Column(Float)
    lng = Column(Float)
    phone = Column(Text)
    facility_type = Column(Text)
    product = Column(Text)
    product_type = Column(Text)
    chemistries = Column(Text)
    feedstock = Column(Text)
    capacity = Column(Text)
    capacity_units = Column(Text)
    status = Column(Text)
    workforce = Column(Text)
    segment = Column(Text)
    sources = Column(Text)
    qc = Column(Text)
    qc_date = Column(Text)
    source_name = Column(Text)            # naatbatt_xlsx, bbd_xlsx, gigafactory_xlsx, etc.
    source_url = Column(Text)
    date_added = Column(Text)


Index("ix_facility_company", CompanyFacility.company_id)


class CompanyMetric(Base):
    __tablename__ = "company_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    metric_name = Column(Text, nullable=False)  # market_cap, revenue, manufacturing_capacity_gwh, employee_count, etc.
    metric_value = Column(Float)
    metric_unit = Column(Text)
    date_recorded = Column(Text)
    source_name = Column(Text)
    source_url = Column(Text)


Index("ix_metric_company", CompanyMetric.company_id)
Index("ix_metric_name", CompanyMetric.metric_name)


class WatchlistEntry(Base):
    __tablename__ = "watchlist"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, unique=True)
    added_at = Column(Text)


Index("ix_watchlist_company", WatchlistEntry.company_id)


class WatchlistDigest(Base):
    __tablename__ = "watchlist_digest"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    company_name = Column(Text)
    run_date = Column(Text)          # YYYY-MM-DD
    articles_json = Column(Text)     # JSON array of article objects
    has_breaking = Column(Integer, default=0)
    created_at = Column(Text)


Index("ix_digest_company", WatchlistDigest.company_id)
Index("ix_digest_run_date", WatchlistDigest.run_date)
