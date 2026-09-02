"""The engine-browser's filter (GET /wikipedia/engines).

`rank_engine_rows` is pure and DB-free, same split as co2_lookup's
rank_candidates / resolve. The rules here are search-box rules, not matcher
rules — the user is reading the list and deciding, so the bar for showing a row
is "might be what they typed", not "we believe this is their car".
"""

import pytest

from app.wikipedia.browse import EngineRow, rank_engine_rows


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
