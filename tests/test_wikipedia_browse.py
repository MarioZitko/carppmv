"""The engine-browser's filter (GET /wikipedia/engines).

`rank_engine_rows` is pure and DB-free, same split as co2_lookup's
rank_candidates / resolve. The rules here are search-box rules, not matcher
rules — the user is reading the list and deciding, so the bar for showing a row
is "might be what they typed", not "we believe this is their car".
"""

from datetime import date

import pytest

from app.wikipedia.browse import (
    EngineRow,
    clean_query,
    group_models,
    rank_engine_rows,
    search_engine_rows,
)


def make(title: str, engine: str | None, *, kw: float | None = 100.0,
         start: str | None = "2015-01", co2: tuple[float, float] = (100.0, 110.0)) -> EngineRow:
    return EngineRow(
        model_article_title=title, engine_code=engine, power_kw=kw,
        displacement_cc=1998.0, fuel_type="diesel", production_start=start,
        production_end="2018-01", co2_min=co2[0], co2_max=co2[1],
        source_url=f"https://de.wikipedia.org/wiki/{title.replace(' ', '_')}",
    )


BMW = [
    make("BMW F30", "320d"), make("BMW F30", "320i"), make("BMW F30", "318d"),
    make("BMW F30", "330d"), make("BMW E90", "320d"),
]


def codes(rows: list[EngineRow]) -> list[str | None]:
    return [r.engine_code for r in rows]


class TestTokenFiltering:
    def test_partial_designation_finds_its_full_forms(self) -> None:
        """The regression this filter was rewritten for: token_set_ratio scored
        '320' against 'bmw f30 320d efficientdynamics' at ~24, so typing '320'
        returned nothing while '320d' returned everything."""
        assert set(codes(rank_engine_rows(BMW, "320"))) == {"320d", "320i"}

    def test_exact_token_outranks_a_prefix_match(self) -> None:
        assert codes(rank_engine_rows(BMW, "320d"))[0] == "320d"

    def test_every_query_token_must_match(self) -> None:
        rows = [
            make("VW Golf VII", "1.6 TDI"), make("VW Golf VII", "2.0 TDI"),
            make("VW Golf Sportsvan", "1.6 TDI"), make("VW Passat B8", "1.6 TDI"),
        ]
        assert len(rank_engine_rows(rows, "golf")) == 3
        assert len(rank_engine_rows(rows, "golf 1.6")) == 2
        assert len(rank_engine_rows(rows, "passat 1.6 tdi")) == 1

    def test_numeric_fragment_does_not_match_inside_another_token(self) -> None:
        """'1.6' normalizes to the tokens ('1','6'). As a substring of the
        joined text the '1' would hit 'Audi A1 8X'; per-token it correctly does
        not, because no token there starts with '1'."""
        rows = [make("Audi A1 8X", "1.4 TFSI"), make("Audi A3 8V", "1.6 TDI")]
        assert codes(rank_engine_rows(rows, "1.6")) == ["1.6 TDI"]

    def test_the_audi_a2_case_separates_petrol_from_diesel(self) -> None:
        """The reason this endpoint exists. Both are 55 kW and the listing has
        no fuel, so the matcher ties them and reports 116-142; typing the
        designation the owner actually knows separates them cleanly."""
        rows = [make("Audi A2", "1.4", kw=55, co2=(142, 142)),
                make("Audi A2", "1.4 TDI", kw=55, co2=(116, 116))]
        assert codes(rank_engine_rows(rows, "1.4 tdi")) == ["1.4 TDI"]
        assert len(rank_engine_rows(rows, "1.4")) == 2  # both, for the user to choose

    def test_no_match_returns_empty_rather_than_relaxing(self) -> None:
        assert rank_engine_rows(BMW, "zzzqqq") == []


class TestTypoFallback:
    def test_fuzzy_only_engages_when_the_token_filter_found_nothing(self) -> None:
        rows = [make("VW Golf VII", "GTI"), make("VW Golf VII", "1.6 TDI")]
        assert codes(rank_engine_rows(rows, "gti")) == ["GTI"]

    def test_a_misspelling_still_finds_something(self) -> None:
        assert len(rank_engine_rows([make("Škoda Karoq", "1.6 TDI")], "karokq")) == 1


class TestOrderingAndLimits:
    def test_blank_query_returns_everything_in_display_order(self) -> None:
        rows = [make("BMW F30", "330d", start="2016-01"),
                make("BMW E90", "320d", start="2007-01"),
                make("BMW F30", "320d", start="2012-01")]
        assert [(r.model_article_title, r.engine_code) for r in rank_engine_rows(rows, None)] == [
            ("BMW E90", "320d"), ("BMW F30", "320d"), ("BMW F30", "330d")]

    @pytest.mark.parametrize("query", [None, "320"])
    def test_limit_is_respected(self, query: str | None) -> None:
        assert len(rank_engine_rows(BMW, query, limit=2)) <= 2

    def test_empty_input(self) -> None:
        assert rank_engine_rows([], "320") == []

    def test_rows_with_no_engine_code_do_not_crash(self) -> None:
        rows = [make("BMW F30", None)]
        assert rank_engine_rows(rows, None) == rows
        assert rank_engine_rows(rows, "f30") == rows


class TestListingTextIsNotFatal:
    """The regression this filter was rewritten a second time for.

    Callers pass a listing blob, and one word the corpus has never heard of used
    to annihilate the whole result set. Against the live corpus,
    `320d xDrive GT Sport-Automatic "Sport Line"` and
    `Golf 1.6 TDI Comfortline DSG` both returned zero rows while `320d` returned
    fourteen.
    """

    def test_an_unmatchable_word_no_longer_empties_the_result(self) -> None:
        rows = [make("BMW G20", "320d xDrive"), make("BMW F30", "320d")]
        assert codes(rank_engine_rows(rows, "320d xdrive gt sport automatic line")) == [
            "320d xDrive"
        ]

    def test_the_reported_failing_string(self) -> None:
        """The exact query from the bug report, cleaned as the endpoint cleans it."""
        rows = [
            make("BMW G20", "320d xDrive"), make("BMW G20", "320d"),
            make("BMW F30", "320d"), make("BMW F30", "318d"),
        ]
        found = rank_engine_rows(rows, clean_query(
            '320d xDrive GT Sport-Automatic "Sport Line"', brand="BMW"))
        assert codes(found) == ["320d xDrive"]

    def test_a_word_that_matches_still_narrows(self) -> None:
        """Ignoring unmatchable words must not turn the box into an OR."""
        rows = [make("VW Golf VII", "1.6 TDI"), make("VW Golf VII", "2.0 TDI")]
        assert codes(rank_engine_rows(rows, "golf 1.6 dsg navi")) == ["1.6 TDI"]

    def test_ignored_terms_name_what_went_unanswered(self) -> None:
        rows = [make("BMW G20", "320d xDrive")]
        result = search_engine_rows(rows, "320d xdrive gt sport automatic")
        assert set(result.ignored_terms) == {"gt", "sport", "automatic"}
        assert result.rows

    def test_a_clean_match_ignores_nothing(self) -> None:
        assert search_engine_rows(BMW, "320d").ignored_terms == ()

    def test_a_query_matching_nothing_at_all_still_returns_empty(self) -> None:
        result = search_engine_rows(BMW, "zzzqqq")
        assert result.rows == []
        assert result.ignored_terms == ("zzzqqq",)

    def test_a_long_noisy_query_stays_sane(self) -> None:
        """Feeds the rendering cap on the UI's "Zanemareno:" line — a real
        listing title can leave five or more words unanswered."""
        rows = [make("BMW G20", "320d xDrive"), make("BMW F30", "318d")]
        result = search_engine_rows(
            rows, "320d xdrive gt sport automatic line navi klima alu xenon")
        assert codes(result.rows) == ["320d xDrive"]
        assert len(result.ignored_terms) >= 5


class TestPrefixIsNotEvidence:
    def test_a_one_letter_token_does_not_prefix_match(self) -> None:
        """"C 220 d" tokenizes to ("c","220","d"), and "c" prefixing "citan" put
        a Citan van above the W205 C 220 d it was asked for."""
        rows = [make("Mercedes-Benz W 420", "Citan 110 CDI / T 160 d"),
                make("Mercedes-Benz Baureihe 205", "C 220 d")]
        assert codes(rank_engine_rows(rows, "c 220 d")) == ["C 220 d"]

    def test_prefixing_a_known_noise_word_earns_nothing(self) -> None:
        """"sport" reaching "sportback" ranked Q3 Sportback rows above the A4
        rows an A4 query asked for."""
        rows = [make("Audi Q3 FJ Sportback", "2.0 TDI"), make("Audi A4 B9", "2.0 TDI")]
        assert [r.model_article_title for r in
                rank_engine_rows(rows, "a4 2.0 tdi sport")] == ["Audi A4 B9"]


class TestRegistrationScope:
    """Scoping happens *before* ranking, not after. A 2016 "320d xDrive" query
    filtered afterwards returns nothing, because the only xDrive rows in the
    corpus are a 2019+ G20; scoped first it settles for "320d" and finds the
    correct-era F30."""

    G20 = make("BMW G20", "320d xDrive", start="2019-03", co2=(118, 125))
    F30 = make("BMW F30", "320d", start="2015-07", co2=(113, 123))
    ROWS = [G20, F30]

    def test_a_2016_registration_gets_the_era_it_asked_for(self) -> None:
        found = rank_engine_rows(
            self.ROWS, "320d xdrive gt", registered=date(2016, 6, 1))
        assert [r.model_article_title for r in found] == ["BMW F30"]

    def test_the_same_query_unscoped_still_prefers_the_fuller_match(self) -> None:
        found = rank_engine_rows(self.ROWS, "320d xdrive gt")
        assert [r.model_article_title for r in found] == ["BMW G20"]

    def test_a_row_stating_no_period_survives_scoping(self) -> None:
        """Browse shows what it cannot rule out; the matcher withholds it."""
        undated = make("BMW F31", "320d", start=None)
        undated = EngineRow(**{**vars(undated), "production_end": None})
        found = rank_engine_rows([undated], "320d", registered=date(2016, 6, 1))
        assert found == [undated]

    def test_an_over_narrow_date_falls_back_rather_than_empties(self) -> None:
        """A mistyped year should cost relevance, never the whole list."""
        found = rank_engine_rows(self.ROWS, "320d", registered=date(1994, 1, 1))
        assert len(found) == 2


class TestPoolStability:
    """IDF is computed over the current pool, so the same query can be weighted
    differently in different pools. What must hold is that this never reorders
    across tiers — the tier is picked by matched-token count before any weight
    is applied — only within one."""

    BMW_ROWS = [make("BMW F30", "320d"), make("BMW F30", "320i"),
                make("BMW G20", "320d xDrive")]
    VW_ROWS = [make("VW Golf VII", "1.6 TDI"), make("VW Passat B8", "2.0 TDI"),
               make("VW Touran", "1.6 TDI")]

    def test_a_mixed_pool_does_not_disturb_the_answer(self) -> None:
        """Unreachable through the endpoint, which always filters to one brand —
        but `rank_engine_rows` is public and pure, so pin it."""
        alone = rank_engine_rows(self.BMW_ROWS, "320d xdrive")
        mixed = rank_engine_rows(self.BMW_ROWS + self.VW_ROWS, "320d xdrive")
        assert codes(alone)[0] == codes(mixed)[0] == "320d xDrive"
        assert all(r.model_article_title.startswith("BMW") for r in mixed)

    def test_narrowing_the_pool_by_date_never_promotes_a_weaker_match(self) -> None:
        rows = [make("BMW G20", "320d xDrive", start="2019-03"),
                make("BMW F30", "320d", start="2015-07"),
                make("BMW F25", "xDrive20d", start="2014-04")]
        for registered in (None, date(2016, 6, 1), date(2021, 3, 1)):
            found = rank_engine_rows(rows, "320d xdrive", registered=registered)
            # Whatever the scope, a row carried only by "xdrive" never leads a
            # row that carried "320d" too.
            assert found, registered
            assert "320d" in (found[0].engine_code or ""), registered


class TestModelGrouping:
    """The picker's first step. Free-text matching over a listing blob cannot
    always be trusted to have found the right car, and nothing in its result
    says when it hasn't — so the user picks the generation, and the text box is
    left the job it does reliably."""

    ROWS = [
        make("BMW F30", "320d", start="2012-05", co2=(124, 124)),
        make("BMW F30", "320i EfficientDynamics Edition", start="2011-10", co2=(124, 124)),
        make("BMW F30", "318d", start="2012-02", co2=(114, 118)),
        make("BMW G20", "320d xDrive", start="2019-03", co2=(118, 125)),
        make("BMW F25", "xDrive20d", start="2014-04", co2=(136, 136)),
    ]

    def titles(self, result) -> list[str]:
        return [g.model_article_title for g in result.models]

    def test_rows_collapse_into_their_articles(self) -> None:
        result = group_models(self.ROWS)
        assert set(self.titles(result)) == {"BMW F30", "BMW G20", "BMW F25"}
        f30 = next(g for g in result.models if g.model_article_title == "BMW F30")
        assert f30.variant_count == 3

    def test_newest_generation_leads_an_unsearched_list(self) -> None:
        assert self.titles(group_models(self.ROWS))[0] == "BMW G20"

    def test_a_query_ranks_but_never_hides_a_model(self) -> None:
        """The case this screen exists for is the one where matching is wrong —
        a 3-series Gran Turismo has no article at all, so every "match" is the
        wrong body. Filtering would strand that user on one wrong option."""
        result = group_models(self.ROWS, "320d")
        assert self.titles(result)[0] in {"BMW F30", "BMW G20"}
        assert set(self.titles(result)) == {"BMW F30", "BMW G20", "BMW F25"}

    def test_an_engine_badge_finds_an_article_named_by_chassis_code(self) -> None:
        """"F30" appears in no listing ever written; "320d" does."""
        assert self.titles(group_models(self.ROWS, "318d"))[0] == "BMW F30"

    def test_registration_date_scopes_the_generations_offered(self) -> None:
        result = group_models(self.ROWS, registered=date(2016, 6, 1))
        assert "BMW G20" not in self.titles(result)

    def test_sample_codes_are_the_short_recognisable_badges(self) -> None:
        """Only bites once there are more codes than slots — and then the base
        badge is what earns the slot. "320i" says 3-series far better than
        "320i EfficientDynamics Edition", which crowds out three other badges
        for no extra information."""
        rows = [make("BMW F30", code) for code in
                ("320i EfficientDynamics Edition", "318d", "320d", "316i", "340i")]
        f30 = group_models(rows).models[0]
        assert len(f30.sample_engine_codes) == 4
        assert "320i EfficientDynamics Edition" not in f30.sample_engine_codes
        assert set(f30.sample_engine_codes) == {"316i", "318d", "320d", "340i"}

    def test_a_discontinued_generation_reports_its_end(self) -> None:
        """Keying "still in production" off *any* member lacking an end marked
        the long-dead F30 as current, because one of its 48 rows stated none."""
        rows = [make("BMW F30", "320d", start="2012-05"),
                make("BMW F30", "318d", start="2012-02")]
        rows[0] = EngineRow(**{**vars(rows[0]), "production_end": "2019-06"})
        rows[1] = EngineRow(**{**vars(rows[1]), "production_end": None})
        assert group_models(rows).models[0].production_end == "2019-06"

    def test_a_current_generation_reports_no_end(self) -> None:
        rows = [make("BMW G20", "320d", start="2019-03"),
                make("BMW G20", "330e", start="2024-07")]
        rows[0] = EngineRow(**{**vars(rows[0]), "production_end": "2024-05"})
        rows[1] = EngineRow(**{**vars(rows[1]), "production_end": None})
        assert group_models(rows).models[0].production_end is None

    def test_no_rows_at_all(self) -> None:
        assert group_models([]).models == []


class TestArticleFilter:
    """Step two. The title came off the model list the user just chose from, so
    it is matched exactly — a fuzzy reading of an explicit choice would be a
    worse answer than none."""

    ROWS = [
        make("BMW F30", "320d", start="2012-05"),
        make("BMW G20", "320d xDrive", start="2019-03"),
    ]

    def test_the_chosen_article_is_all_that_is_offered(self) -> None:
        found = rank_engine_rows(self.ROWS, None, article="BMW F30")
        assert [r.model_article_title for r in found] == ["BMW F30"]

    def test_free_text_still_narrows_within_it(self) -> None:
        rows = [make("BMW F30", "320d"), make("BMW F30", "318d")]
        assert codes(rank_engine_rows(rows, "318d", article="BMW F30")) == ["318d"]

    def test_an_unknown_article_returns_nothing_rather_than_guessing(self) -> None:
        assert rank_engine_rows(self.ROWS, None, article="BMW F34") == []

    def test_the_users_choice_outranks_a_disagreeing_date(self) -> None:
        """They are the one holding the logbook."""
        found = rank_engine_rows(
            self.ROWS, None, article="BMW G20", registered=date(2016, 6, 1))
        assert [r.model_article_title for r in found] == ["BMW G20"]
