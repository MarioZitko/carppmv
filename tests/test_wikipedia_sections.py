"""Unit tests for the Phase 0 wikitext parsing rules (no network, no DB).

These encode the plan's specific decisions: fuzzy "modell" section matching
(an exact whitelist missed Volvo's real heading), #anchor links meaning "a
section of a shared article" rather than a page of their own, and the explicit
escalation threshold.
"""

from app.wikipedia.sections import (
    MIN_QUALIFYING_LINKS,
    ModelLink,
    dedupe_links,
    extract_index_targets,
    extract_link_candidates,
    extract_model_links,
    find_model_sections,
    heading_matches,
    iter_level2_sections,
    matches_brand,
    normalize_anchor,
    normalize_title,
    sections_by_heading,
    should_escalate,
    split_anchor,
)

ARTICLE = """
Ein Automobilhersteller.

== Geschichte ==
Gegründet 1899. Siehe [[Opel Blitz]] im Nutzfahrzeugbereich.

== Modellübersicht ==
{{Hauptartikel|Opel Astra}}
Aktuelle Pkw: [[Opel Corsa]], [[Opel Mokka]] und [[Opel Agila#Agila A (Typ 0HAF68, 2000–2007)|Agila A]].
Ein Bild: [[Datei:Opel Corsa.jpg|mini|Corsa]] und [[Kategorie:Opel]].
Wettbewerber: [[Volkswagen Golf]].
Wiederholung: [[Opel_Corsa]].

== Weblinks ==
[[Opel Insignia]]
"""


def test_level2_sections_skip_the_lead():
    headings = [s.heading for s in iter_level2_sections(ARTICLE)]
    assert headings == ["Geschichte", "Modellübersicht", "Weblinks"]


def test_heading_match_is_fuzzy_not_a_whitelist():
    assert heading_matches("Modelle")
    assert heading_matches("Modellübersicht")
    assert heading_matches("Pkw-Modellüberblick")
    assert heading_matches("Aktuelle Modelle")
    assert not heading_matches("Geschichte")


def test_find_model_sections_picks_only_the_model_section():
    matched = find_model_sections(ARTICLE)
    assert [s.heading for s in matched] == ["Modellübersicht"]


def test_extract_links_filters_namespaces_other_brands_and_other_sections():
    section = find_model_sections(ARTICLE)[0]
    links = extract_model_links(section.text, ("Opel",))
    titles = [link.title for link in links]

    assert "Opel Astra" in titles  # {{Hauptartikel}} target
    assert "Opel Corsa" in titles
    assert "Volkswagen Golf" not in titles  # different brand
    assert not any(t.startswith(("Datei:", "Kategorie:")) for t in titles)
    assert "Opel Insignia" not in titles  # lives in Weblinks, not the model section
    assert titles.count("Opel Corsa") == 1  # [[Opel_Corsa]] is the same page


def test_anchor_link_becomes_base_article_plus_anchor():
    section = find_model_sections(ARTICLE)[0]
    links = extract_model_links(section.text, ("Opel",))
    agila = [link for link in links if link.title == "Opel Agila"]
    assert agila == [ModelLink("Opel Agila", "Agila A (Typ 0HAF68, 2000–2007)")]


def test_split_anchor_and_normalization():
    assert split_anchor("Opel Agila#Agila_A") == ("Opel Agila", "Agila A")
    assert split_anchor("opel corsa") == ("Opel corsa", None)
    assert split_anchor(":Opel Corsa") == ("Opel Corsa", None)
    assert normalize_title("Opel_Corsa  ") == "Opel Corsa"
    assert normalize_anchor("Agila%20A") == "Agila A"
    assert normalize_anchor("") is None
    assert normalize_anchor(None) is None


def test_dedupe_is_on_title_and_anchor_together():
    links = [
        ModelLink("Opel Agila", "Agila A"),
        ModelLink("Opel Agila", "Agila B"),
        ModelLink("Opel Agila", "Agila A"),
        ModelLink("Opel Corsa", None),
    ]
    assert dedupe_links(links) == [
        ModelLink("Opel Agila", "Agila A"),
        ModelLink("Opel Agila", "Agila B"),
        ModelLink("Opel Corsa", None),
    ]


def test_model_link_url_carries_the_anchor():
    assert ModelLink("Opel Agila", "Agila A").url == (
        "https://de.wikipedia.org/wiki/Opel_Agila#Agila_A"
    )
    assert ModelLink("Opel Corsa").url == "https://de.wikipedia.org/wiki/Opel_Corsa"


def test_sections_by_heading_is_the_phase_1_selector():
    picked = sections_by_heading(ARTICLE, ["Geschichte"])
    assert [s.heading for s in picked] == ["Geschichte"]
    assert sections_by_heading(ARTICLE, ["Nicht vorhanden"]) == []


def test_escalation_trigger_is_zero_sections_or_too_few_links():
    section = find_model_sections(ARTICLE)[0]
    plenty = [ModelLink(f"Opel {i}") for i in range(MIN_QUALIFYING_LINKS)]
    too_few = plenty[:-1]

    assert should_escalate([], plenty) is True
    assert should_escalate([section], too_few) is True
    assert should_escalate([section], plenty) is False


RESCUE_SECTION = """
== Modelle ==
{| class="wikitable"
| seit 2015 || [[Oroch]] || Basiert auf dem [[Dacia Duster]].
|-
| 1992–2007 || [[Twingo I]] || Eine [[Limousine]].
|-
| seit 2020 || [[Renault Captur II]] || Konkurrent des [[Nissan Juke]].
|}
"""


def test_extract_link_candidates_keeps_short_names_the_prefix_filter_drops():
    section = find_model_sections(RESCUE_SECTION)[0]

    prefixed = [link.title for link in extract_model_links(section.text, ("Renault",))]
    assert prefixed == ["Renault Captur II"]

    # The candidate pass keeps everything (minus namespaces) so the crawler can
    # ask the API which of these redirect into a Renault article.
    candidates = [link.title for link in extract_link_candidates(section.text)]
    assert "Oroch" in candidates  # redirects to "Renault Oroch"
    assert "Twingo I" in candidates  # redirects to "Renault Twingo"
    assert "Nissan Juke" in candidates  # kept here, rejected after resolution


def test_matches_brand_is_what_admits_a_resolved_candidate():
    assert matches_brand("Renault Twingo", ("Renault",))
    assert matches_brand("Range Rover Sport", ("Land Rover", "Range Rover"))
    assert not matches_brand("Nissan Juke", ("Renault",))
    assert not matches_brand("Limousine", ("Renault",))


INDEX_SECTION = """
== Modelle ==
=== Personenwagen ===
{{Hauptartikel|Personenwagen von Hyundai}}

=== Nutzfahrzeuge ===
{{Hauptartikel|Hyundai Porter}}
[[Hyundai Xcient]]
"""


def test_index_targets_are_hauptartikel_links_that_arent_model_articles():
    section = find_model_sections(INDEX_SECTION)[0]

    # "Personenwagen von Hyundai" is an index of models; "Hyundai Porter" is a
    # model article and must NOT be followed one hop.
    assert [link.title for link in extract_index_targets(section.text, ("Hyundai",))] == [
        "Personenwagen von Hyundai"
    ]

    # Both still count as ordinary links for the crawl itself.
    titles = [link.title for link in extract_model_links(section.text, ("Hyundai",))]
    assert "Personenwagen von Hyundai" in titles
    assert "Hyundai Porter" in titles
    assert "Hyundai Xcient" in titles


NOISY_INDEX_SECTION = """
== Modelle ==
{{Hauptartikel|Personenwagen von Hyundai}}
{{Hauptartikel|Konzeptfahrzeuge von Volkswagen}}
{{Hauptartikel|Liste der Suzuki-Motorräder}}
{{Hauptartikel|Volkswagen Golf}}
"""


def test_index_targets_exclude_non_passenger_car_indexes():
    """The one-hop rule was narrow across the first ten brands but not at 38:
    it started following concept-car lists and motorcycle lists, neither of
    which can appear in a customs catalogue."""
    section = find_model_sections(NOISY_INDEX_SECTION)[0]
    targets = [link.title for link in extract_index_targets(section.text, ("Volkswagen",))]

    assert "Personenwagen von Hyundai" in targets
    assert "Konzeptfahrzeuge von Volkswagen" not in targets  # never homologated
    assert "Liste der Suzuki-Motorräder" not in targets  # PPMV is a car tax
    assert "Volkswagen Golf" not in targets  # a model article, not an index


GALLERY_SECTION = """
== Modelle ==
=== Kleinwagen ===
<gallery>
Seat Ibiza front.JPG|[[Seat Ibiza II]] (1993–2002)
Seat Ibiza V.jpg|[[Seat Ibiza V]] (seit 2017)
</gallery>
=== Kompaktklasse ===
[[Seat Leon IV]]
"""


def test_links_inside_gallery_tags_are_found():
    """mwparserfromhell treats an extension tag's body as raw text, so
    filter_wikilinks() alone misses gallery captions. Several brands list their
    whole production range that way — Seat's section is almost all galleries."""
    section = find_model_sections(GALLERY_SECTION)[0]
    titles = [link.title for link in extract_model_links(section.text, ("Seat",))]

    assert "Seat Ibiza II" in titles
    assert "Seat Ibiza V" in titles
    assert "Seat Leon IV" in titles  # the ordinary non-gallery link still works
    assert not any(t.endswith(".JPG") or t.endswith(".jpg") for t in titles)


def test_gallery_links_also_reach_the_candidate_pass():
    section = find_model_sections(GALLERY_SECTION)[0]
    assert "Seat Ibiza II" in [link.title for link in extract_link_candidates(section.text)]
