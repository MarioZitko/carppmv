"""Phase 2 table selection — the pure, DB-free half (app/wikipedia/tables.py)."""

import pytest

from app.wikipedia import tables as tbl

NORMAL_TABLE = """{| class="wikitable"
! Modell !! Motor !! Hubraum !! Leistung !! CO<sub>2</sub>-Emission
|-
| 1.0 TSI || R3 || 999 cm³ || 70 kW || 109 g/km
|-
| 1.6 TDI || R4 || 1598 cm³ || 85 kW || 106 g/km
|}"""

TRANSPOSED_TABLE = """{| class="wikitable"
! !! 2.0 TFSI !! 40 TDI
|-
! Bauzeitraum
| seit 06/2016 || seit 09/2016
|-
! Hubraum
| 1984 cm³ || 1968 cm³
|-
! max. Leistung
| 185 kW || 140 kW
|-
! CO<sub>2</sub>-Emission, kombiniert
| 144 g/km || 116 g/km
|}"""

NO_CO2_TABLE = """{| class="wikitable"
! Motortyp !! Hubraum !! Drehmoment
|-
| R4 || 1598 cm³ || 250 Nm
|}"""

ARTICLE = f"""Einleitung.

== Technische Daten ==
=== Ottomotoren ===
{NORMAL_TABLE}

=== Dieselmotoren ===
{TRANSPOSED_TABLE}

== Zulassungszahlen ==
{NO_CO2_TABLE}
"""


def test_heading_path_is_carried_with_each_table():
    found = tbl.iter_article_tables(ARTICLE)
    assert len(found) == 3
    assert found[0].heading_path == ("Technische Daten", "Ottomotoren")
    assert found[1].heading_path == ("Technische Daten", "Dieselmotoren")
    # A level-2 heading pops the level-3 above it off the stack.
    assert found[2].heading_path == ("Zulassungszahlen",)
    assert found[0].heading_context == "Technische Daten > Ottomotoren"


def test_heading_markup_is_stripped_so_anchors_can_match():
    article = "== [[Ottomotor]]en ==\n" + NORMAL_TABLE
    assert tbl.iter_article_tables(article)[0].heading_path == ("Ottomotoren",)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("CO2-Emission", True),
        ("CO<sub>2</sub>-Emission", True),
        ("CO₂-Emission", True),
        ("Kohlenstoffdioxid", True),
        ("Motortyp | Hubraum | Drehmoment", False),
    ],
)
def test_co2_token_prefilter(text, expected):
    assert tbl.has_co2_token(text) is expected


def test_prefilter_drops_tables_without_a_co2_token():
    kept, dropped = tbl.select_tables(ARTICLE, anchor=None)
    assert len(kept) == 2
    assert len(dropped) == 1
    assert "Drehmoment" in dropped[0].wikitext


def test_prefilter_is_per_table_not_per_article():
    """A CO2-less table must not disqualify its article's other tables — CO2
    data often sits in only one table of several."""
    kept, _ = tbl.select_tables(NO_CO2_TABLE + "\n\n" + NORMAL_TABLE, anchor=None)
    assert len(kept) == 1


def test_euro_ncap_tables_are_dropped_even_when_they_mention_co2():
    ncap = """{| class="wikitable"
! Euro NCAP Crashtest !! Erwachsenensicherheit !! CO2
|-
| 5 Sterne || 93 % || –
|}"""
    kept, dropped = tbl.select_tables(ncap, anchor=None)
    assert not kept and len(dropped) == 1


def test_anchor_scopes_extraction_to_its_section():
    kept, _ = tbl.select_tables(ARTICLE, anchor="Dieselmotoren")
    assert len(kept) == 1
    assert "40 TDI" in kept[0].wikitext


def test_unmatched_anchor_falls_back_to_the_whole_article():
    """A renamed section costs provenance precision, never coverage."""
    kept, _ = tbl.select_tables(ARTICLE, anchor="Gibt es nicht")
    assert len(kept) == 2


def test_anchor_matching_tolerates_dash_variants():
    article = "== Agila A (2000–2007) ==\n" + NORMAL_TABLE
    kept, _ = tbl.select_tables(article, anchor="Agila A (2000-2007)")
    assert len(kept) == 1


@pytest.mark.parametrize(
    "table,expected",
    [
        (NORMAL_TABLE, "normal"),
        (TRANSPOSED_TABLE, "transposed"),
        ('{| class="wikitable"\n| a || b\n|-\n| c || d\n|}', "no_header_cells"),
    ],
)
def test_mechanical_orientation_guess(table, expected):
    assert tbl.guess_orientation(table) == expected


def test_nested_tables_are_not_returned_separately():
    nested = '{| class="wikitable"\n|\n' + NORMAL_TABLE + "\n|}"
    assert len(tbl.iter_article_tables(nested)) == 1


def test_fingerprint_includes_the_heading_path():
    """The same table under Ottomotoren and Dieselmotoren is a different
    question, because the heading is what supplies fuel_type."""
    otto = tbl.iter_article_tables("=== Ottomotoren ===\n" + NORMAL_TABLE)[0]
    diesel = tbl.iter_article_tables("=== Dieselmotoren ===\n" + NORMAL_TABLE)[0]
    assert otto.fingerprint != diesel.fingerprint


@pytest.mark.parametrize(
    "text,expected",
    [("144 g/km", True), ("116&nbsp;g/km", True), ("1,4 l/100 km", False), ("CO2", False)],
)
def test_co2_shaped_tripwire_pattern(text, expected):
    assert tbl.has_co2_shaped_value(text) is expected


KENNGROESSEN_TABLE = """{| class="wikitable"
|- class="hintergrundfarbe5"
|'''Kenngrößen'''
! SCe 100
! dCi 75
|- align="center"
|align="left" style="background:#F5F5F5"|'''Bauzeitraum'''
|2015-2018
|2018-2021
|- align="center"
|align="left" style="background:#F5F5F5"|'''Hubraum'''
|1598&nbsp;cm3
|1461&nbsp;cm3
|- align="center"
|align="left" style="background:#F5F5F5"|'''CO<sub>2</sub>-Emission'''
|175
|118
|}"""


def test_bold_label_rows_count_as_transposed():
    """The Kenngroessen style writes row labels as bold DATA cells and reserves
    "!" for the variant names on top — an exclamation-mark-only rule calls this
    "normal", which is the wrong axis (caught on "Dacia Dokker")."""
    assert tbl.guess_orientation(KENNGROESSEN_TABLE) == "transposed"
