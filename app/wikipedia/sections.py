"""Wikitext parsing for Phase 0: brand article -> model article references.

Pure and DB-free on purpose (same posture as catalogue/matching.py's
rank_candidates) so every rule here is unit-testable without a network or a
database — see tests/test_wikipedia_sections.py.

Two decisions from docs/WIKIPEDIA_CO2_PLAN.md are load-bearing:

1. **Section matching is fuzzy, not a whitelist.** German brand articles head
   their model list "Modelle", "Modellübersicht", "Modellprogramm",
   "Pkw-Modellüberblick", "Aktuelle Modelle"… An exact whitelist missed
   Volvo's actual heading in testing, so the rule is substring "modell".

2. **A ``#anchor`` link is not a separate page.** "Opel Agila#Agila A (Typ
   0HAF68, 2000–2007)" means that generation lives as a *section* of the
   shared "Opel Agila" article. The pair (base title, anchor) is what gets
   stored and deduped; the article is fetched once no matter how many anchors
   point into it.
"""

import html
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import unquote

import mwparserfromhell

# Fuzzy section rule (plan §Phase 0 step 3). Lowercased substring test, so it
# also catches "Modellübersicht", "Pkw-Modelle", "Aktuelle Modelle".
SECTION_KEYWORD = "modell"

# Escalation threshold (plan §Phase 0, "explicit trigger condition"): a brand
# goes to Phase 1 when the fuzzy match finds no section at all, or finds one
# holding fewer than this many qualifying links after filtering.
MIN_QUALIFYING_LINKS = 5

# Templates that point at a model's main article from inside a section.
_MAIN_ARTICLE_TEMPLATES = {"hauptartikel", "main", "siehe hauptartikel"}

# Namespace and interwiki prefixes that are never model articles. Checked
# case-insensitively against the text before the first colon.
_EXCLUDED_PREFIXES = {
    "datei", "file", "bild", "image", "media", "kategorie", "category",
    "vorlage", "template", "wikipedia", "wp", "hilfe", "help", "portal",
    "benutzer", "user", "benutzerin", "diskussion", "talk", "spezial",
    "special", "s", "b", "q", "n", "v", "wikt", "commons", "c", "d",
    "en", "fr", "it", "es", "nl", "pl", "sv", "hr", "cs", "ru", "ja", "zh",
}


@dataclass(frozen=True)
class ModelLink:
    """One (base article, section anchor) reference found in a model section."""

    title: str
    anchor: str | None = None

    @property
    def key(self) -> tuple[str, str]:
        """Dedup key — anchor None and "" must not be two different rows."""
        return (self.title, self.anchor or "")

    @property
    def url(self) -> str:
        base = "https://de.wikipedia.org/wiki/" + self.title.replace(" ", "_")
        return f"{base}#{self.anchor.replace(' ', '_')}" if self.anchor else base


@dataclass(frozen=True)
class Section:
    heading: str
    text: str


def normalize_title(raw: str) -> str:
    """MediaWiki title normalization: underscores become spaces, whitespace
    collapses, a leading ":" is dropped, first character uppercased.

    Must stay deterministic — the same function normalizes both the link found
    in the brand article and the title later looked up/stored, and a divergence
    would silently split one article into two rows."""
    # html.unescape first: wikitext links sometimes carry entities
    # ("Opel&nbsp;Corsa"), and an unresolved nbsp makes a real page look missing.
    title = html.unescape(unquote(raw)).replace("\xa0", " ").replace("_", " ").strip()
    title = title.lstrip(":").strip()
    title = re.sub(r"\s+", " ", title)
    # HTML comments occasionally survive inside a link target.
    title = re.sub(r"<!--.*?-->", "", title, flags=re.DOTALL).strip()
    if not title:
        return ""
    return title[0].upper() + title[1:]


def normalize_anchor(raw: str | None) -> str | None:
    """Section anchors travel percent-encoded and/or underscored ("Agila_A" vs
    "Agila A"). Normalize to spaces so two spellings of the same section dedupe
    to one row. Returns None for an empty/absent anchor."""
    if raw is None:
        return None
    anchor = html.unescape(unquote(raw)).replace("\xa0", " ").replace("_", " ").strip()
    anchor = re.sub(r"\s+", " ", anchor)
    anchor = unicodedata.normalize("NFC", anchor)
    return anchor or None


def split_anchor(raw: str) -> tuple[str, str | None]:
    """"Opel Agila#Agila A" -> ("Opel Agila", "Agila A")."""
    base, sep, fragment = raw.partition("#")
    return normalize_title(base), normalize_anchor(fragment) if sep else None


def _is_excluded_namespace(title: str) -> bool:
    prefix, sep, _ = title.partition(":")
    return bool(sep) and prefix.strip().lower() in _EXCLUDED_PREFIXES


def iter_level2_sections(wikitext: str) -> list[Section]:
    """Every ``== level-2 ==`` section, as (heading, section text) pairs.

    The lead section (no heading) is skipped: model links there are navigation
    or prose, not the model list this phase is after."""
    code = mwparserfromhell.parse(wikitext)
    sections: list[Section] = []
    for node in code.get_sections(levels=[2], include_headings=True):
        headings = node.filter_headings()
        if not headings:
            continue
        sections.append(Section(heading=str(headings[0].title).strip(), text=str(node)))
    return sections


def heading_matches(heading: str) -> bool:
    return SECTION_KEYWORD in heading.lower()


def find_model_sections(wikitext: str) -> list[Section]:
    """Sections whose heading fuzzy-matches the model-list rule."""
    return [s for s in iter_level2_sections(wikitext) if heading_matches(s.heading)]


def sections_by_heading(wikitext: str, headings: list[str]) -> list[Section]:
    """Sections selected by exact heading string — the Phase 1 path, where the
    LLM returns literal headings taken from this same article."""
    wanted = {h.strip() for h in headings}
    return [s for s in iter_level2_sections(wikitext) if s.heading in wanted]


def _iter_wikilinks(code) -> list:
    """All wikilinks in a chunk of parsed wikitext, INCLUDING those inside
    ``<gallery>`` tags.

    mwparserfromhell treats an extension tag's body as raw text, so
    ``filter_wikilinks()`` cannot see links written in gallery captions —
    ``<gallery>Seat Ibiza.jpg|[[Seat Ibiza V]] (seit 2017)</gallery>``. Several
    brands list their entire production range that way: Seat's model section is
    almost all galleries, and skipping them left it with 8 articles (concept and
    racing cars) instead of its real range, despite 8,091 catalogue rows.
    Re-parsing each gallery body recovers them.
    """
    links = list(code.filter_wikilinks())
    for tag in code.filter_tags(matches=lambda t: t.tag == "gallery"):
        links.extend(mwparserfromhell.parse(str(tag.contents)).filter_wikilinks())
    return links


def extract_main_article_targets(section_text: str) -> list[ModelLink]:
    """``{{Hauptartikel|…}}`` targets in a section, namespace-filtered.

    Split out from extract_model_links because a target that is NOT itself a
    brand-prefixed model article is an INDEX article: Hyundai's "Modelle"
    section lists commercial vehicles inline but delegates passenger cars to
    ``{{Hauptartikel|Personenwagen von Hyundai}}``, so the models live one hop
    away. Across the ten Phase 0 brands this is the only such target — the
    rule is narrow by construction, not a general recursion.
    """
    code = mwparserfromhell.parse(section_text)
    links: list[ModelLink] = []
    for template in code.filter_templates():
        if str(template.name).strip().lower() not in _MAIN_ARTICLE_TEMPLATES:
            continue
        for param in template.params:
            if param.showkey:
                continue
            raw = str(param.value).strip()
            if not raw:
                continue
            title, anchor = split_anchor(raw)
            if title and not _is_excluded_namespace(title):
                links.append(ModelLink(title, anchor))
    return dedupe_links(links)


# Index titles that are NOT passenger-car model lists. Checked as
# case-insensitive substrings of the target title.
#
# This denylist exists because the one-hop rule was narrow at ten brands (only
# Hyundai's "Personenwagen von Hyundai" qualified) but stopped being narrow at
# 38: it began following "Konzeptfahrzeuge von Volkswagen" (+34 show cars that
# were never homologated and appear in no customs catalogue) and "Liste der
# Suzuki-Motorräder" (+141 motorcycles — PPMV is a car tax). Both are pure
# noise for this pipeline, so the categories are excluded by name.
_INDEX_TITLE_DENYLIST = (
    "konzeptfahrzeug", "konzeptauto", "konzeptstudie", "studien",
    "motorrad", "motorräder", "motorroller",
    "lastkraftwagen", "nutzfahrzeug", "omnibus", "traktor",
    "rennwagen", "rennsport", "formel", "militärfahrzeug",
)


def _is_denied_index_title(title: str) -> bool:
    lowered = title.lower()
    return any(word in lowered for word in _INDEX_TITLE_DENYLIST)


def extract_index_targets(
    section_text: str, brand_prefixes: tuple[str, ...]
) -> list[ModelLink]:
    """Hauptartikel targets that are not themselves model articles — i.e. the
    index articles worth following one hop into.

    Excludes non-passenger-car indexes (see _INDEX_TITLE_DENYLIST). The caller
    is responsible for the other guard that cannot be decided here: skipping a
    target that is another BRAND's article (Citroën's model section points at
    "DS Automobiles" and vice versa, and both are separately crawled brands).
    """
    return [
        link
        for link in extract_main_article_targets(section_text)
        if not matches_brand(link.title, brand_prefixes)
        and not _is_denied_index_title(link.title)
    ]


def extract_model_links(section_text: str, brand_prefixes: tuple[str, ...]) -> list[ModelLink]:
    """Model references inside one section.

    Two signals, per the plan:
    - ``{{Hauptartikel|…}}`` positional params — the primary signal where
      present, taken without the brand-prefix filter because the template's
      whole purpose is "this subsection's main article".
    - plain ``[[wikilinks]]`` — filtered to titles starting with one of the
      brand's article prefixes, which is what keeps a "Modelle" section's prose
      links to suppliers, engines and competitors out of the crawl.

    Namespace links (Datei:/File:/Kategorie:/interwiki) are excluded from both.
    """
    code = mwparserfromhell.parse(section_text)
    links: list[ModelLink] = list(extract_main_article_targets(section_text))

    for wikilink in _iter_wikilinks(code):
        title, anchor = split_anchor(str(wikilink.title))
        if not title or _is_excluded_namespace(title):
            continue
        if not matches_brand(title, brand_prefixes):
            continue
        links.append(ModelLink(title, anchor))

    return dedupe_links(links)


def matches_brand(title: str, brand_prefixes: tuple[str, ...]) -> bool:
    lowered = title.lower()
    return any(lowered.startswith(p.lower()) for p in brand_prefixes)


def extract_link_candidates(section_text: str) -> list[ModelLink]:
    """Every namespace-filtered link in a section, brand prefix or not.

    Exists because German model tables often link a model by its short name:
    Renault's post-1945 tables say ``[[Twingo]]``, ``[[Captur]]``, ``[[Oroch]]``,
    which the brand-prefix filter drops even though they redirect straight to
    "Renault Twingo" etc. The crawler resolves these and keeps only the ones
    whose *resolved* title carries the brand prefix — so the redirect, not a
    looser text rule, is what admits them, and neighbours in the same table
    ("Nissan Navara", "Limousine", "Le Mans") stay out.
    """
    code = mwparserfromhell.parse(section_text)
    links: list[ModelLink] = []
    for wikilink in _iter_wikilinks(code):
        title, anchor = split_anchor(str(wikilink.title))
        if title and not _is_excluded_namespace(title):
            links.append(ModelLink(title, anchor))
    return dedupe_links(links)


def dedupe_links(links: list[ModelLink]) -> list[ModelLink]:
    """Dedupe on (title, anchor), preserving first-seen order."""
    seen: set[tuple[str, str]] = set()
    out: list[ModelLink] = []
    for link in links:
        if link.key in seen:
            continue
        seen.add(link.key)
        out.append(link)
    return out


def should_escalate(sections: list[Section], links: list[ModelLink]) -> bool:
    """Phase 1 trigger (plan §Phase 0): zero matched sections, or fewer than
    MIN_QUALIFYING_LINKS qualifying links after filtering."""
    return not sections or len(links) < MIN_QUALIFYING_LINKS
