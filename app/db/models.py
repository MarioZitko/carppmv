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
    Boolean,
    Date,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
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
    # exact trim/variant string as it appears in the source Excel
    variant: Mapped[str] = mapped_column(String(256))

    # Normalized brand+model+variant (lowercased, diacritics/punctuation stripped),
    # computed at ingestion. Drives listing→catalogue matching: the exact tier
    # hits this index directly, the fuzzy tier scores against it. See
    # app/catalogue/matching.py (build_match_key). A scraped listing never carries
    # the source Excel's internal code (MODEL KOD / KOD MODELA / Porsche `model`),
    # so this human-readable normalized text — not any of those codes — is the
    # only viable cross-source key.
    match_key: Mapped[str] = mapped_column(String(512), index=True, default="")

    # always normalized to EUR at ingestion (HRK_TO_EUR_RATE if source was HRK)
    price_eur: Mapped[float] = mapped_column(Float)
    co2_g_km: Mapped[float] = mapped_column(Float)
    # Base engine power in kW, when the source Excel had it. Not part of the
    # lookup key, but the strongest disambiguator between same-named variants
    # with different engines (e.g. 320d ~140 kW vs 330d ~190 kW) — the matcher
    # uses it to reject a wrong-engine fuzzy hit the listing's power contradicts.
    power_kw: Mapped[float | None] = mapped_column(Float, nullable=True)
    co2_standard: Mapped[CO2Standard] = mapped_column(SAEnum(CO2Standard, native_enum=False))
    fuel_type: Mapped[FuelType] = mapped_column(SAEnum(FuelType, native_enum=False))

    # source Excel's "VRIJEDI OD", decoded from Excel serial date
    valid_from: Mapped[date] = mapped_column(Date)
    # null = still current as of last ingestion
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    # original Excel filename, kept for traceability after the Excels themselves are discarded
    source_file: Mapped[str] = mapped_column(String(512))
    # "EUR" or "HRK" — the currency as it appeared in the source, pre-normalization
    source_currency: Mapped[str] = mapped_column(String(3))
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
    # site's own listing ID, if exposed
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    brand: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    variant: Mapped[str | None] = mapped_column(String(256), nullable=True)

    price_eur: Mapped[float | None] = mapped_column(Float, nullable=True)
    # often unavailable pre-login/pre-COC — see PPMV §7 CO2 problem
    co2_g_km: Mapped[float | None] = mapped_column(Float, nullable=True)
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


class WikipediaFetchStatus(str, Enum):
    OK = "ok"
    NOT_FOUND = "not_found"
    ERROR = "error"


class WikipediaRawArticle(Base):
    """Raw de.wikipedia wikitext cached by the Phase 0 crawl
    (app/wikipedia/crawl.py), one row per (brand, article, anchor) model
    reference found in a brand article's model-list section.

    Offline/batch only — nothing in the /calculate request path reads this.
    It exists so Phase 2's table extraction runs against cached wikitext
    instead of re-hitting Wikipedia, and so a killed crawl resumes rather
    than re-fetching (see the resumability requirement in
    docs/WIKIPEDIA_CO2_PLAN.md §Phase 0).

    anchor is set when the brand article linked into a *section* of a shared
    article (e.g. "Opel Agila#Agila A (Typ 0HAF68, 2000-2007)") — the
    generation's data lives in that section, not on its own page. Two anchors
    into one article are two rows: wikitext is fetched once per unique title
    but stored per row, so Phase 2 can process a row standalone without a
    join back to a separate article table.

    anchor_key exists only to make the unique constraint work: Postgres
    treats NULLs as distinct, so a nullable anchor column alone would let
    duplicate anchor-less rows through. It mirrors anchor with "" for None
    and is never read as data.
    """

    __tablename__ = "wikipedia_raw_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Catalogue.brand value this article was crawled for (e.g. "Mercedes-Benz").
    brand: Mapped[str] = mapped_column(String(64), index=True)
    # de.wikipedia title AFTER redirect resolution (the title the wikitext is of).
    article_title: Mapped[str] = mapped_column(String(512), index=True)
    anchor: Mapped[str | None] = mapped_column(String(512), nullable=True)
    anchor_key: Mapped[str] = mapped_column(String(512), default="")

    # Null when fetch_status is not_found/error — the row still records the
    # attempt, which is what makes coverage auditable after the run.
    wikitext: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetch_status: Mapped[WikipediaFetchStatus] = mapped_column(
        SAEnum(WikipediaFetchStatus, native_enum=False)
    )
    # Populated on error/not_found (API error code, HTTP status, exception text).
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "brand", "article_title", "anchor_key", name="uq_wikipedia_raw_article"
        ),
    )

    @property
    def source_url(self) -> str:
        """Provenance URL (§0 of the plan) — article plus section anchor."""
        base = "https://de.wikipedia.org/wiki/" + self.article_title.replace(" ", "_")
        return f"{base}#{self.anchor.replace(' ', '_')}" if self.anchor else base

    def __repr__(self) -> str:
        frag = f"#{self.anchor}" if self.anchor else ""
        return f"<WikipediaRawArticle {self.brand} {self.article_title}{frag} {self.fetch_status}>"


class WikipediaBrandCheck(str, Enum):
    """Verdict of the crawl-brand vs. article-title cross-check (Phase 4).

    The crawl brand alone is NOT authoritative: the Phase 0 crawl files a row
    under the brand whose article linked to it, and brand articles link to
    other marques' rebadges. The real cases in the corpus are a Subaru-filed
    "Opel Zafira" (the Traviq rebadge, 28 variants), Toyota-filed "Lexus
    ES/GS/IS", Nissan-filed "Dacia Logan"/"Renault Symbol", and a Peugeot-filed
    "Eurovan (PSA/Fiat)" multi-marque van platform article.
    """

    #: article title's marque prefix agrees with the crawl brand
    CONFIRMED = "confirmed"
    #: title names a DIFFERENT known marque; the row was re-filed under it
    REFILED = "refiled"
    #: title carries no recognisable marque prefix — cannot confirm or deny
    UNVERIFIED = "unverified"


class WikipediaEngineData(Base):
    """One engine variant extracted from a de.wikipedia spec table
    (docs/WIKIPEDIA_CO2_PLAN.md §Phase 4), upserted by app/wikipedia/upsert.py.

    Read only by app/wikipedia/co2_lookup.py (Phase 5). This is a CO2 *hint*
    tier, never an auto-fill: §0 of the plan requires /calculate to keep
    returning manual_required when this is the only source available.

    Identity (`source_fingerprint`, `variant_index`) rather than the spec
    columns: the Phase 2 schema has no gearbox/drivetrain field, so a table's
    "2.0 TDI 103 kW manual / 153 g" and "2.0 TDI 103 kW automatic / 159 g" rows
    are byte-identical on every spec column and would collapse under a
    spec-shaped key — 757 of 8,895 rows did, 409 of those groups carrying
    genuinely different CO2. The fingerprint is a content hash of the source
    table, so re-running extraction re-derives the same key (idempotent upsert)
    and two brands that crawled the same article converge on one row instead of
    duplicating.

    `brand` is the EFFECTIVE brand after the title cross-check, and is what
    Phase 5 filters on. `crawl_brand` keeps what the crawl thought, so a
    re-filing is auditable rather than silent.
    """

    __tablename__ = "wikipedia_engine_data"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Cross-checked brand — see WikipediaBrandCheck. Phase 5 filters on this.
    brand: Mapped[str] = mapped_column(String(64), index=True)
    # Brand the Phase 0 crawl filed the article under. Provenance only; never
    # used as a matching filter, precisely because it is the untrustworthy one.
    crawl_brand: Mapped[str] = mapped_column(String(64), index=True)
    brand_check: Mapped[WikipediaBrandCheck] = mapped_column(
        SAEnum(WikipediaBrandCheck, native_enum=False), index=True
    )

    model_article_title: Mapped[str] = mapped_column(String(512), index=True)
    # Section path the table sat under ("Technische Daten > Ottomotoren").
    # Carries the fuel context and the NEDC/WLTP distinction the table itself
    # often states only in its heading.
    heading_context: Mapped[str] = mapped_column(String(512), default="")

    engine_code: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # "YYYY" or "YYYY-MM" as printed. German tables frequently give only a year
    # and forcing a month would mean inventing one (plan §Phase 3).
    production_start: Mapped[str | None] = mapped_column(String(16), nullable=True)
    production_end: Mapped[str | None] = mapped_column(String(16), nullable=True)

    displacement_cc: Mapped[float | None] = mapped_column(Float, nullable=True)
    power_kw: Mapped[float | None] = mapped_column(Float, nullable=True)
    fuel_type: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Null is a valid, expected outcome (plan §0) — the table simply had no
    # emissions row. Phase 5 reports "no estimate available" for such a row
    # rather than showing an empty range.
    co2_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    co2_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    # True when the source gave co2_min > co2_max and the upsert swapped them.
    # Traceable rather than silent — 53 rows in the first run.
    source_order_corrected: Mapped[bool] = mapped_column(Boolean, default=False)

    # Provenance (plan §0, non-negotiable): the exact table and the URL.
    source_url: Mapped[str] = mapped_column(String(1024))
    source_wikitext_snippet: Mapped[str] = mapped_column(Text)
    # sha1 of the source table's wikitext (app/wikipedia/tables.py) + the
    # variant's position within that table's extraction.
    source_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    variant_index: Mapped[int] = mapped_column(Integer)

    upserted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "source_fingerprint", "variant_index", name="uq_wikipedia_engine_row"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<WikipediaEngineData {self.brand} {self.model_article_title} "
            f"{self.engine_code!r} {self.power_kw}kW {self.co2_min}-{self.co2_max}>"
        )
