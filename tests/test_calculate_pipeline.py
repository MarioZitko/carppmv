"""Decision-logic tests for POST /calculate.

The endpoint's job is not just "scrape then compute" — it decides, per listing,
whether it has enough to produce a number at all, and when it doesn't, which
prefilled manual-entry response the user gets instead. That branching is the
part that silently breaks, so it's what these tests pin down.

Everything with I/O (the scrape, the catalogue lookup, the scrape-outcome
write) is stubbed, so this needs no DB, no network and no browser.
"""

from datetime import date

import pytest

from app.calculate import router as calc
from app.calculate.schemas import CalculateRequest
from app.catalogue.matching import CandidateRow, MatchResult, MatchStatus, ScoredCandidate
from app.scraping.mobile_de_service import ApifyBudgetExceeded
from app.scraping.schemas import ListingData


def _listing(**overrides) -> ListingData:
    """A listing with everything present, so each test can knock out one field
    and see only that field's effect."""
    base = dict(
        source_url="https://www.autoscout24.de/angebote/x",
        source_site="autoscout24",
        brand="Audi",
        model="A5",
        variant="40 TDI",
        fuel_type="diesel",
        first_registration_date="2020-08-17",
        power_kw=140.0,
        co2_g_km=136.0,
        price_eur=36490.0,
    )
    base.update(overrides)
    return ListingData(**base)


def _row(co2: float | None = 150.0) -> CandidateRow:
    return CandidateRow(
        catalogue_id=1,
        brand="Audi",
        model="A5",
        variant="40 TDI",
        match_key="audi a5 40 tdi",
        price_eur=50000.0,
        co2_g_km=co2,
        co2_standard="NEDC",
        fuel_type="diesel",
        power_kw=140.0,
        valid_from=date(2020, 1, 1),
    )


@pytest.fixture
def pipeline(monkeypatch):
    """Stubs the endpoint's three I/O calls and returns a `run()` that invokes
    the real `calculate()` against whatever listing/match result you set."""

    state = {"listing": _listing(), "match": MatchResult(MatchStatus.NO_MATCH, None, [])}

    async def fake_scrape(url, site, session, request, turnstile_token):
        result = state["listing"]
        if isinstance(result, Exception):
            raise result
        return result

    async def fake_find_match(session, **kwargs):
        state["find_match_kwargs"] = kwargs
        return state["match"]

    async def fake_record(*args, **kwargs):
        return None

    monkeypatch.setattr(calc, "_scrape", fake_scrape)
    monkeypatch.setattr(calc, "find_match", fake_find_match)
    monkeypatch.setattr(calc, "record_scrape_outcome", fake_record)

    async def run(listing=None, match=None):
        if listing is not None:
            state["listing"] = listing
        if match is not None:
            state["match"] = match
        body = CalculateRequest(url="https://www.autoscout24.de/angebote/x")
        return await calc.calculate(body, request=None, session=None)

    run.state = state
    return run


class TestHappyPath:
    async def test_listing_co2_is_used_directly(self, pipeline):
        resp = await pipeline(_listing(co2_g_km=136.0))
        assert resp.co2_source == "scraped"
        assert resp.confidence == "high"
        assert resp.ppmv_eur is not None
        assert resp.warnings == []

    async def test_official_audi_a5_case_survives_the_pipeline(self, pipeline):
        """Same inputs as the carina.gov.hr regression in test_ppmv_engine, but
        arriving as a scraped listing — proves /calculate doesn't distort them
        on the way to the engine. Declaration date is today, so assert on the
        components that don't move rather than the final figure."""
        resp = await pipeline(_listing())
        assert resp.parsed.price_eur == 36490.0
        assert resp.parsed.co2_g_km == 136.0
        assert resp.ppmv_eur > 0

    async def test_parsed_fields_mirror_the_listing(self, pipeline):
        resp = await pipeline(_listing(vin="WAUZZZF47LA012345", seat_count=5))
        assert resp.parsed.brand == "Audi"
        assert resp.parsed.variant == "40 TDI"
        assert resp.parsed.vin == "WAUZZZF47LA012345"
        assert resp.parsed.seat_count == 5
        # Raw string is passed through untouched for the frontend to re-parse.
        assert resp.parsed.first_registration == "2020-08-17"


class TestCatalogueFallback:
    async def test_auto_match_fills_missing_co2(self, pipeline):
        match = MatchResult(MatchStatus.AUTO_MATCHED, _row(co2=150.0), [])
        resp = await pipeline(_listing(co2_g_km=None), match)
        assert resp.co2_source == "catalogue"
        assert resp.parsed.co2_g_km == 150.0
        assert resp.ppmv_eur is not None

    async def test_unconfirmed_candidates_do_not_fill_co2(self, pipeline):
        """"Confirm unless certain": a non-AUTO_MATCHED result must never
        silently supply a CO2 value, because a wrong one corrupts the tax."""
        match = MatchResult(MatchStatus.CANDIDATES, None, [ScoredCandidate(_row(), 91.0)])
        resp = await pipeline(_listing(co2_g_km=None), match)
        assert resp.co2_source == "manual_required"
        assert resp.ppmv_eur is None
        assert resp.match_status == "candidates"
        assert len(resp.candidates) == 1

    async def test_candidates_surface_even_when_co2_was_scraped(self, pipeline):
        """The user must still be able to override the price with a different
        catalogue row, so candidates come back regardless of the CO2 source."""
        match = MatchResult(MatchStatus.CANDIDATES, None, [ScoredCandidate(_row(), 88.0)])
        resp = await pipeline(_listing(co2_g_km=136.0), match)
        assert resp.co2_source == "scraped"
        assert len(resp.candidates) == 1

    async def test_registration_year_is_passed_to_the_matcher(self, pipeline):
        await pipeline(_listing(first_registration_date="2020-08-17"))
        assert pipeline.state["find_match_kwargs"]["year"] == 2020

    async def test_no_brand_skips_matching_entirely(self, pipeline):
        resp = await pipeline(_listing(brand=None, co2_g_km=None))
        assert resp.match_status == "not_attempted"
        assert resp.candidates == []


class TestCo2Guard:
    async def test_nonpositive_co2_is_rejected_for_combustion(self, pipeline):
        resp = await pipeline(_listing(co2_g_km=0.0, fuel_type="diesel"))
        assert resp.co2_source == "manual_required"
        assert resp.parsed.co2_g_km is None
        assert resp.ppmv_eur is None
        assert any("≤ 0" in w for w in resp.warnings)

    async def test_zero_co2_is_valid_for_electric(self, pipeline):
        resp = await pipeline(_listing(co2_g_km=0.0, fuel_type="electric"))
        assert resp.co2_source == "scraped"
        assert resp.ppmv_eur == 0.0  # electric is fully exempt


class TestIncompleteListings:
    """Each missing field yields a 200 with a prefilled form, never an error."""

    async def test_unknown_fuel_skips_calculation(self, pipeline):
        resp = await pipeline(_listing(fuel_type="wasserstoff"))
        assert resp.ppmv_eur is None
        assert any("goriva" in w for w in resp.warnings)
        assert resp.parsed.price_eur == 36490.0  # still prefilled

    async def test_lpg_is_treated_as_petrol_not_unknown(self, pipeline):
        """Regression: the extractors emit lpg/cng/hybrid, and any spelling
        missing from _FUEL_MAP aborts the whole calculation."""
        for fuel in ("lpg", "cng", "hybrid"):
            resp = await pipeline(_listing(fuel_type=fuel))
            assert resp.ppmv_eur is not None, f"{fuel} aborted the calculation"

    async def test_missing_registration_date_skips_calculation(self, pipeline):
        resp = await pipeline(_listing(first_registration_date=None))
        assert resp.ppmv_eur is None
        assert any("registracije" in w for w in resp.warnings)

    async def test_missing_price_skips_calculation(self, pipeline):
        resp = await pipeline(_listing(price_eur=None))
        assert resp.ppmv_eur is None
        assert any("cijena" in w.lower() for w in resp.warnings)

    async def test_missing_co2_returns_no_warning_duplication(self, pipeline):
        """A listing with no CO2 and no match gets exactly one CO2 warning,
        not one from the matcher plus one from the final guard."""
        resp = await pipeline(_listing(co2_g_km=None))
        assert sum("CO2" in w for w in resp.warnings) == 1


class TestApifyBudget:
    async def test_exhausted_budget_degrades_to_manual_entry(self, pipeline):
        resp = await pipeline(ApifyBudgetExceeded())
        assert resp.ppmv_eur is None
        assert resp.co2_source == "manual_required"
        assert resp.confidence == "low"
        assert resp.match_status == "not_attempted"
        assert resp.candidates == []
        assert any("limit" in w.lower() for w in resp.warnings)
