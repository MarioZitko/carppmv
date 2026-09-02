"""Decision-logic tests for POST /calculate.

The endpoint's job is not just "scrape then compute" — it decides, per listing,
whether it has enough to produce a number at all, and when it doesn't, which
prefilled manual-entry response the user gets instead. That branching is the
part that silently breaks, so it's what these tests pin down.

Everything with I/O (the scrape, the catalogue lookup, the scrape-outcome
write) is stubbed, so this needs no DB, no network and no browser.
"""

import dataclasses
from datetime import date

import pytest

from app.calculate import router as calc
from app.calculate.schemas import CalculateRequest
from app.catalogue.matching import CandidateRow, MatchResult, MatchStatus, ScoredCandidate
from app.scraping.mobile_de_service import ApifyBudgetExceeded
from app.scraping.schemas import ListingData
from app.wikipedia.co2_lookup import WikipediaCo2Estimate


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


#: Distinguishes "leave the stubbed Wikipedia result alone" from "make it
#: return None", which is itself a meaningful case (the common one, in fact).
_UNSET = object()


def _estimate(co2_min: float = 106.0, co2_max: float = 123.0) -> WikipediaCo2Estimate:
    """A Phase 5 answer, shaped like the real BMW 320d one from the live table."""
    return WikipediaCo2Estimate(
        co2_min=co2_min,
        co2_max=co2_max,
        source_url="https://de.wikipedia.org/wiki/BMW_F30",
        source_urls=("https://de.wikipedia.org/wiki/BMW_F30",),
        brand="BMW",
        model_article_title="BMW F30",
        engine_code="320d",
        score=88.0,
        merged_rows=2,
        source_order_corrected=False,
    )


@pytest.fixture
def pipeline(monkeypatch):
    """Stubs the endpoint's three I/O calls and returns a `run()` that invokes
    the real `calculate()` against whatever listing/match result you set."""

    state = {
        "listing": _listing(),
        "match": MatchResult(MatchStatus.NO_MATCH, None, []),
        "wikipedia": None,
        "wikipedia_calls": [],
    }

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

    async def fake_resolve(**kwargs):
        state["wikipedia_calls"].append(kwargs)
        result = state["wikipedia"]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(calc, "_scrape", fake_scrape)
    monkeypatch.setattr(calc, "find_match", fake_find_match)
    monkeypatch.setattr(calc, "record_scrape_outcome", fake_record)
    monkeypatch.setattr(calc, "resolve_co2_from_wikipedia", fake_resolve)

    async def run(listing=None, match=None, wikipedia=_UNSET, session=None):
        if listing is not None:
            state["listing"] = listing
        if match is not None:
            state["match"] = match
        if wikipedia is not _UNSET:
            state["wikipedia"] = wikipedia
        body = CalculateRequest(url="https://www.autoscout24.de/angebote/x")
        return await calc.calculate(body, request=None, session=session)

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


class TestFuelFromCatalogue:
    """An auto-matched row can supply the fuel the listing never stated.

    autobid.de exposes neither CO2 nor fuel before login, and an unknown fuel
    aborts the whole calculation — so a real listing the catalogue had matched
    exactly still returned no number. Taking fuel from the same row we already
    take CO2 from is the smaller of the two leaps of faith.
    """

    async def test_auto_matched_row_supplies_a_missing_fuel(self, pipeline):
        match = MatchResult(MatchStatus.AUTO_MATCHED, _row(co2=150.0), [])
        resp = await pipeline(_listing(fuel_type=None, co2_g_km=None), match)
        assert resp.parsed.fuel_type == "diesel"
        assert resp.ppmv_eur is not None
        assert resp.warnings == []

    async def test_the_listings_own_fuel_always_wins(self, pipeline):
        """The listing saw the actual car; the catalogue row is a fuzzy match."""
        petrol_row = dataclasses.replace(_row(co2=150.0), fuel_type="petrol")
        match = MatchResult(MatchStatus.AUTO_MATCHED, petrol_row, [])
        resp = await pipeline(_listing(fuel_type="diesel", co2_g_km=None), match)
        assert resp.parsed.fuel_type == "diesel"

    async def test_fuel_is_filled_even_when_co2_came_from_the_listing(self, pipeline):
        """The CO2 early-return must not skip the fuel fill — a listing can
        state CO2 and still omit fuel."""
        match = MatchResult(MatchStatus.AUTO_MATCHED, _row(co2=150.0), [])
        resp = await pipeline(_listing(fuel_type=None, co2_g_km=136.0), match)
        assert resp.parsed.fuel_type == "diesel"
        assert resp.co2_source == "scraped"
        assert resp.ppmv_eur is not None

    async def test_unconfirmed_candidates_never_supply_fuel(self, pipeline):
        """Same "confirm unless certain" rule as CO2: a fuel guessed off a row
        we weren't sure about would silently pick a different tax table."""
        match = MatchResult(MatchStatus.CANDIDATES, None, [ScoredCandidate(_row(), 91.0)])
        resp = await pipeline(_listing(fuel_type=None, co2_g_km=None), match)
        assert resp.parsed.fuel_type is None


class TestWikipediaHint:
    """The fourth, last-resort CO2 tier.

    Its whole contract is negative: it must fire in exactly two situations,
    stay silent in every other, and never once influence the number. So most of
    these assert what does *not* happen.
    """

    async def test_fires_when_nothing_else_produced_co2(self, pipeline):
        resp = await pipeline(_listing(co2_g_km=None), wikipedia=_estimate())
        assert resp.wikipedia_hint is not None
        assert resp.wikipedia_hint.co2_min_g_km == 106.0
        assert resp.wikipedia_hint.co2_max_g_km == 123.0
        assert resp.wikipedia_hint.source_url == "https://de.wikipedia.org/wiki/BMW_F30"
        assert resp.wikipedia_hint.model_article_title == "BMW F30"

    async def test_hint_does_not_relax_manual_required(self, pipeline):
        """The plan's §0 rule, which is the entire reason this tier is a
        separate field rather than a fourth co2_source value."""
        resp = await pipeline(_listing(co2_g_km=None), wikipedia=_estimate())
        assert resp.co2_source == "manual_required"
        assert resp.confidence == "low"
        assert resp.parsed.co2_g_km is None
        assert resp.ppmv_eur is None

    async def test_auto_matched_row_with_null_co2_still_reaches_wikipedia(self, pipeline):
        """The latent hole the audit found: matching.py's accept rule tests
        score and price agreement, never CO2 presence, so AUTO_MATCHED can
        arrive carrying no CO2 at all. No catalogue row hits this today, which
        is exactly why it needs a forced fixture — it would otherwise be found
        in production by a user getting a blank result and no prompt."""
        match = MatchResult(MatchStatus.AUTO_MATCHED, _row(co2=None), [])
        resp = await pipeline(_listing(co2_g_km=None), match, wikipedia=_estimate())

        assert resp.co2_source == "manual_required"  # not "catalogue"
        assert resp.parsed.co2_g_km is None
        assert resp.wikipedia_hint is not None
        assert len(pipeline.state["wikipedia_calls"]) == 1
        assert sum("CO2" in w for w in resp.warnings) == 1

    async def test_not_called_when_the_listing_had_co2(self, pipeline):
        resp = await pipeline(_listing(co2_g_km=136.0), wikipedia=_estimate())
        assert pipeline.state["wikipedia_calls"] == []
        assert resp.wikipedia_hint is None
        assert resp.co2_source == "scraped"

    async def test_not_called_when_the_catalogue_supplied_co2(self, pipeline):
        match = MatchResult(MatchStatus.AUTO_MATCHED, _row(co2=150.0), [])
        resp = await pipeline(_listing(co2_g_km=None), match, wikipedia=_estimate())
        assert pipeline.state["wikipedia_calls"] == []
        assert resp.wikipedia_hint is None
        assert resp.co2_source == "catalogue"
        assert resp.ppmv_eur is not None

    async def test_not_called_without_a_brand(self, pipeline):
        """No brand means no catalogue match and no Wikipedia lookup either —
        `brand` is the resolver's one required argument and its SQL filter."""
        resp = await pipeline(_listing(brand=None, co2_g_km=None), wikipedia=_estimate())
        assert pipeline.state["wikipedia_calls"] == []
        assert resp.wikipedia_hint is None

    async def test_declining_to_answer_is_the_common_case(self, pipeline):
        """~2 of 3 real queries return None. That must be an ordinary
        manual_required response, indistinguishable from before this tier."""
        resp = await pipeline(_listing(co2_g_km=None), wikipedia=None)
        assert len(pipeline.state["wikipedia_calls"]) == 1
        assert resp.wikipedia_hint is None
        assert resp.co2_source == "manual_required"
        assert sum("CO2" in w for w in resp.warnings) == 1

    async def test_no_warning_duplication_when_the_hint_fires(self, pipeline):
        """The invariant test_missing_co2_returns_no_warning_duplication pins,
        re-checked on the path that now runs an extra lookup. A firing hint is
        a success, not a third thing to warn about."""
        resp = await pipeline(_listing(co2_g_km=None), wikipedia=_estimate())
        assert sum("CO2" in w for w in resp.warnings) == 1

    async def test_the_estimate_never_reaches_the_tax_engine(self, monkeypatch, pipeline):
        """Structural, not incidental: with every other input present and only
        CO2 missing, the engine must not be invoked at all — the hint cannot
        stand in for the value the user still has to type."""
        calls = []
        monkeypatch.setattr(
            calc, "calculate_ppmv", lambda **kw: calls.append(kw)
        )
        resp = await pipeline(_listing(co2_g_km=None), wikipedia=_estimate())

        assert calls == []
        assert resp.ppmv_eur is None
        assert resp.wikipedia_hint is not None

    async def test_the_requests_own_session_is_passed_through(self, pipeline):
        """Never let the resolver open a second AsyncSessionLocal inside a
        request. Paired with
        TestWikipediaResolverSession::test_passing_a_session_opens_no_other_one,
        which proves the resolver honours it."""
        sentinel = object()
        await pipeline(_listing(co2_g_km=None), wikipedia=_estimate(), session=sentinel)
        assert pipeline.state["wikipedia_calls"][0]["session"] is sentinel

    async def test_model_text_carries_model_and_variant(self, pipeline):
        await pipeline(_listing(co2_g_km=None), wikipedia=_estimate())
        call = pipeline.state["wikipedia_calls"][0]
        assert call["model"] == "a5 40 tdi"
        assert call["brand"] == "Audi"
        assert call["fuel"] == "diesel"
        assert call["power_kw"] == 140.0
        assert call["date"] == date(2020, 8, 17)


class TestWikipediaQueryText:
    """`_wikipedia_model_text` — what the matcher actually gets asked.

    Pure, so tested directly. Every rule here only ever removes tokens: the
    cleaner can lose a lookup but can never invent a match, which is the
    property that makes it safe to tune.
    """

    def _text(self, **fields) -> str | None:
        base = dict(source_url="https://x/y", source_site="autobid.de")
        base.update(fields)
        return calc._wikipedia_model_text(ListingData(**base))

    def test_the_reported_autobid_listing(self):
        """autobid.de puts the entire title in `variant`, so this arrived as
        'a3 audi a3 sportback 1 2 tfsi attraction' — eight tokens, four of them
        noise. The correct row (Audi A3 8P, 1.2 TFSI, 77 kW, exact power match)
        still ranked first but scored 74.0 against ACCEPT_SCORE 80.0, so the
        lookup declined on a car it had found. Cleaned, it scores 80.0 and
        answers 123-132 g/km."""
        assert self._text(
            brand="Audi", model="A3", variant='Audi A3 Sportback 1,2 TFSI "Attraction"'
        ) == "a3 1 2 tfsi"

    def test_brand_tokens_are_dropped(self):
        """The brand is already the matcher's SQL filter and is stripped from
        the candidate side, so repeating it in the query is pure dilution."""
        assert self._text(brand="BMW", model="BMW 320d", variant="BMW 320d") == "320d"

    def test_repeated_tokens_collapse(self):
        assert self._text(brand="Audi", model="A3", variant="A3 1.6 TDI") == "a3 1 6 tdi"

    def test_engine_designations_are_never_stripped(self):
        """The failure mode that would matter: losing a designation makes the
        matcher answer confidently about a different engine."""
        text = self._text(
            brand="Volkswagen", model="Golf", variant="Golf 2.0 TDI quattro DSG"
        )
        assert "tdi" in text and "2" in text and "quattro" in text

    def test_a_variant_of_pure_trim_words_falls_back_to_the_raw_text(self):
        """Cleaning to an empty string would query for nothing at all, which
        matches every row equally badly — worse than the noisy query."""
        assert self._text(brand="Audi", model=None, variant="Attraction") == "Attraction"

    def test_no_model_and_no_variant(self):
        assert self._text(brand="Audi") is None

    async def test_a_failing_lookup_cannot_break_the_response(self, pipeline):
        """Strictly additive tier: the user gets the same manual-entry response
        with or without it, so a DB error in a hint must not become a 500."""
        resp = await pipeline(_listing(co2_g_km=None), wikipedia=RuntimeError("db down"))
        assert resp.wikipedia_hint is None
        assert resp.co2_source == "manual_required"
        assert sum("CO2" in w for w in resp.warnings) == 1


class TestWikipediaResolverSession:
    """The one test that exercises the real resolver rather than the stub."""

    async def test_passing_a_session_opens_no_other_one(self, monkeypatch):
        """`resolve_co2_from_wikipedia` imports AsyncSessionLocal lazily inside
        its own body, so booby-trapping it is enough to prove the session=
        branch never reaches it. Cheaper and more direct than counting pool
        checkouts, and it fails loudly if that branch is ever reordered."""
        import app.db.session as db_session
        from app.wikipedia import co2_lookup

        def explode(*args, **kwargs):
            raise AssertionError("resolver opened a second AsyncSessionLocal")

        monkeypatch.setattr(db_session, "AsyncSessionLocal", explode)

        seen = {}

        async def fake_load(session, brand):
            seen["session"] = session
            return []

        monkeypatch.setattr(co2_lookup, "load_candidates", fake_load)

        sentinel = object()
        result = await co2_lookup.resolve_co2_from_wikipedia(
            brand="BMW", model="320d", session=sentinel
        )
        assert result is None
        assert seen["session"] is sentinel
