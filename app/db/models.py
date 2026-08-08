"""SQLAlchemy ORM models.

Three tables for this build phase:
- Catalogue: ingested from brand Excel files (one row per brand/model/variant/
  period). Source of truth for as-new price + CO2, replacing the raw Excels
  once ingested — see catalogue_inventory.py for the ingestion CLI.
- ScrapeRun: one row per scraper execution (sweep or on-demand), for
  observability/cost-tracking (Apify billing, success rates).
- Listing: one row per scraped vehicle, linked to the run that found it.

Deferred (per MASTER_PLAN_v7 §4/§6, add when actually needed):
listing_snapshots, price_history, model_stats, sweep_config.
"""

from datetime import date, datetime
from enum import Enum

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class CO2Standard(str, Enum):
    NEDC = "NEDC"
    WLTP = "WLTP"


class FuelType(str, Enum):
    DIESEL = "diesel"
    PETROL = "petrol"
    ELECTRIC = "electric"
    HYBRID = "hybrid"
    LPG = "lpg"
    CNG = "cng"


class Catalogue(Base):
    """One priced variant of one model for one validity period, ingested
    from an official Croatian customs brand Excel file.

    Lookup key (per decision: exact text match, no fuzzy/normalized
    matching yet): brand + model + variant + valid_from. All four are
    part of the unique constraint below. If multiple sheets/files give
    the same (brand, model, variant) for overlapping periods, that's a
    data problem for catalogue_inventory.py to flag, not something this
    table resolves silently.
    """

    __tablename__ = "catalogue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    brand: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(String(128), index=True)
    variant: Mapped[str] = mapped_column(String(256))  # exact trim/variant string as it appears in the source Excel

    # Normalized brand+model+variant (lowercased, diacritics/punctuation stripped),
    # computed at ingestion. Drives listing→catalogue matching: the exact tier
    # hits this index directly, the fuzzy tier scores against it. See
    # app/catalogue/matching.py (build_match_key). A scraped listing never carries
    # the source Excel's internal code (MODEL KOD / KOD MODELA / Porsche `model`),
    # so this human-readable normalized text — not any of those codes — is the
    # only viable cross-source key.
    match_key: Mapped[str] = mapped_column(String(512), index=True, default="")

    price_eur: Mapped[float] = mapped_column(Float)  # always normalized to EUR at ingestion (HRK_TO_EUR_RATE if source was HRK)
    co2_g_km: Mapped[float] = mapped_column(Float)
    # Base engine power in kW, when the source Excel had it. Not part of the
    # lookup key, but the strongest disambiguator between same-named variants
    # with different engines (e.g. 320d ~140 kW vs 330d ~190 kW) — the matcher
    # uses it to reject a wrong-engine fuzzy hit the listing's power contradicts.
    power_kw: Mapped[float | None] = mapped_column(Float, nullable=True)
    co2_standard: Mapped[CO2Standard] = mapped_column(SAEnum(CO2Standard, native_enum=False))
    fuel_type: Mapped[FuelType] = mapped_column(SAEnum(FuelType, native_enum=False))

    valid_from: Mapped[date] = mapped_column(Date)  # source Excel's "VRIJEDI OD", decoded from Excel serial date
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)  # null = still current as of last ingestion

    source_file: Mapped[str] = mapped_column(String(512))  # original Excel filename, kept for traceability after the Excels themselves are discarded
    source_currency: Mapped[str] = mapped_column(String(3))  # "EUR" or "HRK" — the currency as it appeared in the source, pre-normalization
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("brand", "model", "variant", "valid_from", name="uq_catalogue_lookup_key"),
    )

    def __repr__(self) -> str:
        return f"<Catalogue {self.brand} {self.model} {self.variant!r} @ {self.valid_from}>"


class ScrapeSite(str, Enum):
    MOBILE_DE = "mobile.de"
    NJUSKALO = "njuskalo.hr"
    AUTOSCOUT24 = "autoscout24"
    AUTOBID_DE = "autobid.de"


class ScrapeMode(str, Enum):
    ON_DEMAND = "on_demand"  # single-URL, user-triggered
    SWEEP = "sweep"  # nightly/weekly batch


class ScrapeRunStatus(str, Enum):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"  # some listings fetched before failure/abort
    FAILED = "failed"


class ScrapeRun(Base):
    """One execution of a scraper — on-demand single fetch or a sweep.

    Exists for cost/observability tracking (per memory: Apify billing
    behavior is per-result and partial runs still charge for pulled
    results, so knowing what a run actually produced matters) and for
    debugging when a site's bot-detection posture changes.
    """

    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    site: Mapped[ScrapeSite] = mapped_column(SAEnum(ScrapeSite, native_enum=False))
    mode: Mapped[ScrapeMode] = mapped_column(SAEnum(ScrapeMode, native_enum=False))
    status: Mapped[ScrapeRunStatus] = mapped_column(
        SAEnum(ScrapeRunStatus, native_enum=False), default=ScrapeRunStatus.RUNNING
    )

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    listings_found: Mapped[int] = mapped_column(Integer, default=0)
    listings_failed: Mapped[int] = mapped_column(Integer, default=0)

    # Apify-specific cost tracking — null for httpx/Playwright-only runs.
    apify_actor_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    apify_run_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    estimated_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    error_message: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    listings: Mapped[list["Listing"]] = relationship(back_populates="scrape_run")

    def __repr__(self) -> str:
        return f"<ScrapeRun {self.site} {self.mode} {self.status} #{self.id}>"


class Listing(Base):
    """One scraped vehicle listing. Mirrors the scraping.schemas.ListingData
    contract (the normalized cross-feature interface) but as a persisted
    row, linked to the run that found it.

    Deliberately flat/minimal for this build phase — no snapshot history,
    no price-change tracking (that's listing_snapshots/price_history,
    deferred). One row = current known state of one listing.
    """

    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    scrape_run_id: Mapped[int] = mapped_column(ForeignKey("scrape_runs.id"))
    scrape_run: Mapped["ScrapeRun"] = relationship(back_populates="listings")

    site: Mapped[ScrapeSite] = mapped_column(SAEnum(ScrapeSite, native_enum=False))
    source_url: Mapped[str] = mapped_column(String(1024))
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)  # site's own listing ID, if exposed

    brand: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    variant: Mapped[str | None] = mapped_column(String(256), nullable=True)

    price_eur: Mapped[float | None] = mapped_column(Float, nullable=True)
    co2_g_km: Mapped[float | None] = mapped_column(Float, nullable=True)  # often unavailable pre-login/pre-COC — see PPMV §7 CO2 problem
    fuel_type: Mapped[FuelType | None] = mapped_column(SAEnum(FuelType, native_enum=False), nullable=True)
    first_registration_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    mileage_km: Mapped[int | None] = mapped_column(Integer, nullable=True)
    power_kw: Mapped[int | None] = mapped_column(Integer, nullable=True)

    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("site", "external_id", name="uq_listing_site_external_id"),
    )

    def __repr__(self) -> str:
        return f"<Listing {self.site} {self.brand} {self.model} {self.price_eur} EUR>"


class ListingCache(Base):
    """Cached Apify result for a single listing, keyed by "{site}:{id}"
    (e.g. "mobile.de:459632333"). Avoids paying for a fresh Apify call on
    every /calculate request for the same listing within the TTL window —
    see app/core/limits.py and the mobile.de branch in calculate/router.py.
    """

    __tablename__ = "listing_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cache_key: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON)  # serialized ListingData
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ApifyEvent(Base):
    """One /calculate request served via the Apify on-demand path — cache
    hit, paid Apify call, or budget-cap degrade — for cost/observability
    tracking (per-day spend, success rate).
    """

    __tablename__ = "apify_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ip_hash: Mapped[str] = mapped_column(String(64), index=True, default="")
    site: Mapped[str] = mapped_column(String(64))  # "mobile.de"
    listing_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source: Mapped[str] = mapped_column(String(16))  # "cache" | "apify"
    # "success" | "failed" | "cap_reached" | "rate_limited" | "bot_rejected"
    status: Mapped[str] = mapped_column(String(16))
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)