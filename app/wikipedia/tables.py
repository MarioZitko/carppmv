"""Phase 2 table selection: cached article wikitext -> the tables worth an LLM call.

Pure and DB-free, same posture as sections.py — every rule here is unit-testable
without a network or a database (tests/test_wikipedia_tables.py).

Three decisions from docs/WIKIPEDIA_CO2_PLAN.md are load-bearing here:

1. **Prefilter by CO2 token, per TABLE not per article** (§Open items 4 and 8).
   Only ~29% of the corpus's tables carry a CO2 token at all; the rest are
   genuine engine-spec tables (Motortyp / Hubraum / Leistung / Drehmoment) with
   no emissions row, plus Euro-NCAP crashtest and sales-figure tables. A call
   against one of those can only return null CO2, which serves no purpose in
   this pipeline. The filter is per table because CO2 sometimes sits in one
   table of an article whose other tables have none — skipping a whole article
   on one table's absence would lose real coverage.

2. **The section heading above a table is context, not decoration** (§Phase 2).
   fuel_type is frequently stated nowhere in the table itself and is only
   inferable from the heading ("Ottomotoren" / "Dieselmotoren"), so the whole
   heading path is carried alongside the table and passed into the prompt.

3. **An anchor scopes extraction to one section** (§Phase 0 step 5). A row with
   anchor "Agila A (Typ 0HAF68, 2000-2007)" means that generation's tables are
   the ones inside that section, not the whole shared article's.

Table ORIENTATION is deliberately NOT decided here. 60% of the corpus is normal
(one row per variant), 38% transposed (one column per variant), ~1% has no
header cells — the LLM identifies which it is looking at per table (§Open items
6). The mechanical `guess_orientation` below exists only as an independent
sanity check on that, so a prompt regression shows up as a divergence between
the two rather than as silently wrong data.
"""

import hashlib
import re
from dataclasses import dataclass

import mwparserfromhell

# CO2 token prefilter (plan §Open items 4). Covers every spelling seen in the
# corpus: "CO2", "CO<sub>2</sub>", the "CO₂" subscript character, and the
# spelled-out German. Case-insensitive because headings and prose disagree.
CO2_TOKEN_RE = re.compile(
    r"CO\s*(?:<\s*sub\s*>\s*2\s*<\s*/\s*sub\s*>|₂|2)|Kohlen(?:stoff)?dioxid",
    re.IGNORECASE,
)

# Tripwire (Phase 2.5 amendment): CO2-SHAPED text, used to flag a table whose
# extraction came back with null CO2 even though a plausible figure is sitting
# in the wikitext. Deliberately separate from the token filter above — this one
# looks for a NUMBER in g/km, not for the substance's name.
CO2_VALUE_RE = re.compile(r"\d{2,3}(?:[.,]\d+)?\s*(?:&nbsp;|\s)*g\s*/\s*km", re.IGNORECASE)

# ==…== through ======…======. MediaWiki requires the markers on their own line.
_HEADING_RE = re.compile(r"^(={2,6})\s*(.+?)\s*\1\s*$", re.MULTILINE)

# Wikitext that is a table but never an engine-spec table. Cheap pre-LLM drop;
# the CO2 filter already removes most of these, but a crashtest table quoting a
# CO2 figure in a footnote would otherwise slip through.
_NON_ENGINE_TABLE_HINTS = (
    "euro ncap",
    "erwachsenensicherheit",
    "kindersicherheit",
)


@dataclass(frozen=True)
class WikiTable:
    """One table, with the heading path that gives it meaning.

    `heading_path` is outermost-first ("Technische Daten", "Ottomotoren"), which
    is what the prompt needs for fuel inference — the innermost heading alone is
    often just "Motoren".
    """

    wikitext: str
    heading_path: tuple[str, ...]
    index: int

    @property
    def heading_context(self) -> str:
        return " > ".join(self.heading_path) if self.heading_path else "(article lead)"

    @property
    def fingerprint(self) -> str:
        """Content hash of the exact question Phase 2 asks about this table.

        Includes the heading path because the same table wikitext under
        "Dieselmotoren" and under "Ottomotoren" is genuinely a different
        question — the heading is what supplies fuel_type."""
        blob = self.heading_context + "\n" + self.wikitext
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def strip_heading_markup(raw: str) -> str:
    """Heading text as MediaWiki renders it — links, bold, refs and templates
    removed. Needed because an anchor points at the RENDERED heading, so
    "== [[Ottomotor]]en ==" is anchored as "Ottomotoren"."""
    text = mwparserfromhell.parse(raw).strip_code().strip()
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def iter_article_tables(wikitext: str) -> list[WikiTable]:
    """Every table in an article, in document order, each tagged with the
    heading path above it.

    Segments the article by heading first (regex on the raw text, so character
    offsets stay exact) and parses each segment separately — this is what keeps
    the heading path attached. Nested tables are dropped: a table whose wikitext
    is contained inside another returned table is that table's inner detail, not
    a second engine table (plan §Open items 9 verified the outer scan is sound).
    """
    segments: list[tuple[tuple[str, ...], str]] = []
    stack: list[tuple[int, str]] = []  # (level, heading text)
    cursor = 0

    for match in _HEADING_RE.finditer(wikitext):
        chunk = wikitext[cursor : match.start()]
        if chunk.strip():
            segments.append((tuple(h for _, h in stack), chunk))
        level = len(match.group(1))
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, strip_heading_markup(match.group(2))))
        cursor = match.end()

    tail = wikitext[cursor:]
    if tail.strip():
        segments.append((tuple(h for _, h in stack), tail))

    tables: list[WikiTable] = []
    for path, chunk in segments:
        found = [
            str(tag)
            for tag in mwparserfromhell.parse(chunk).filter_tags(
                matches=lambda t: t.tag == "table"
            )
        ]
        for text in found:
            if any(text != other and text in other for other in found):
                continue  # nested inside another table in this same segment
            tables.append(WikiTable(wikitext=text, heading_path=path, index=len(tables)))
    return tables


def tables_for_anchor(wikitext: str, anchor: str | None) -> list[WikiTable]:
    """Tables in scope for one crawled row.

    No anchor -> the whole article. With an anchor -> only tables whose heading
    path contains that section, so a shared article's other generations don't
    bleed in. An anchor that matches no heading falls back to the whole article
    rather than returning nothing: a renamed section is a provenance
    imprecision, but returning zero tables would be a silent coverage loss.
    """
    tables = iter_article_tables(wikitext)
    if not anchor:
        return tables

    wanted = _normalize_for_anchor(anchor)
    scoped = [t for t in tables if any(_normalize_for_anchor(h) == wanted for h in t.heading_path)]
    if scoped:
        return scoped
    # Second chance on a prefix match — anchors are often the heading with a
    # disambiguating parenthetical the heading itself doesn't carry.
    scoped = [
        t
        for t in tables
        if any(
            _normalize_for_anchor(h).startswith(wanted) or wanted.startswith(_normalize_for_anchor(h))
            for h in t.heading_path
            if _normalize_for_anchor(h)
        )
    ]
    return scoped or tables


def _normalize_for_anchor(text: str) -> str:
    """Anchor/heading comparison form: lowercase, dashes unified, spaces
    collapsed. de.wikipedia mixes "–" (en dash) and "-" freely between a
    heading and the links pointing at it."""
    cleaned = strip_heading_markup(text).lower()
    cleaned = cleaned.replace("–", "-").replace("—", "-").replace("−", "-")
    return re.sub(r"\s+", " ", cleaned).strip()


def has_co2_token(table_wikitext: str) -> bool:
    """The prefilter (plan §Open items 3/4)."""
    return bool(CO2_TOKEN_RE.search(table_wikitext))


def looks_non_engine(table_wikitext: str) -> bool:
    lowered = table_wikitext.lower()
    return any(hint in lowered for hint in _NON_ENGINE_TABLE_HINTS)


def has_co2_shaped_value(text: str) -> bool:
    """Tripwire predicate: does this wikitext contain something SHAPED like a
    CO2 figure (a 2-3 digit number in g/km)?"""
    return bool(CO2_VALUE_RE.search(text))


def select_tables(wikitext: str, anchor: str | None) -> tuple[list[WikiTable], list[WikiTable]]:
    """(tables to send to the LLM, tables filtered out) for one crawled row."""
    kept: list[WikiTable] = []
    dropped: list[WikiTable] = []
    for table in tables_for_anchor(wikitext, anchor):
        if has_co2_token(table.wikitext) and not looks_non_engine(table.wikitext):
            kept.append(table)
        else:
            dropped.append(table)
    return kept, dropped


def guess_orientation(table_wikitext: str) -> str:
    """Independent mechanical guess at a table's orientation, for cross-checking
    the LLM's own verdict (plan §Open items 6).

    The signal is where the ATTRIBUTE LABELS sit. A NORMAL table puts them in
    one header row across the top, so each subsequent row is a variant. A
    TRANSPOSED table leads most of its rows with a label ("Bauzeitraum",
    "CO<sub>2</sub>-Emission, kombiniert") and the variants run across as
    columns.

    Markup alone does not answer this, which is why the rule is content-based.
    Two markup signals were tried and both failed on real tables:

    - ``!`` header cells only: the "Kenngrößen" style used across
      Renault/Dacia/VW-group articles writes its row labels as ordinary bold
      data cells and reserves ``!`` for the variant names on top, so every such
      transposed table was called "normal" ("Dacia Dokker" is the case that
      exposed it).
    - a bold first cell: normal tables routinely bold the variant name in their
      first column too, which flipped 94% of the corpus to "transposed".

    So the discriminator is WHERE THE ATTRIBUTE VOCABULARY LIVES. German engine
    tables label their attributes from a small, stable set of words
    (Bauzeitraum, Hubraum, Leistung, Drehmoment, Abgasnorm…). Whichever axis
    carries those words is the attribute axis: down the first column means
    transposed, across the top row means normal.

    Returns "normal" | "transposed" | "no_header_cells". This is a heuristic
    used for reporting and for cross-checking the model, never to override it.
    """
    rows = _split_rows(table_wikitext)
    if not rows:
        return "no_header_cells"
    if len(rows) < 2:
        return "normal" if _starts_with_label_cell(rows[0]) else "no_header_cells"

    column_hits = sum(1 for row in rows if _is_attribute_label(_first_cell_text(row)))
    row_hits = sum(1 for cell in _row_cell_texts(rows[0]) if _is_attribute_label(cell))

    if column_hits > row_hits:
        return "transposed"
    if row_hits > 0:
        return "normal"
    # No attribute vocabulary on either axis — fall back to the markup signal.
    if not any(_starts_with_label_cell(row) for row in rows):
        return "no_header_cells"
    return "normal"


def _split_rows(table_wikitext: str) -> list[str]:
    """Rows of a wikitext table, split on ``|-`` at line start. The opening
    ``{|`` line and closing ``|}`` are dropped; a table with no explicit ``|-``
    before its first row still yields that row."""
    body = table_wikitext
    body = re.sub(r"^\{\|[^\n]*\n?", "", body)
    body = re.sub(r"\n?\|\}\s*$", "", body)
    parts = re.split(r"^\s*\|-[^\n]*$", body, flags=re.MULTILINE)
    return [p for p in parts if p.strip()]


# The stable German vocabulary of engine-table attribute labels. Membership is
# a substring test, so "max. Leistung", "Leistung pro Liter" and "! Leistung"
# all hit. This set is the orientation discriminator, so keep it to words that
# are attribute NAMES — never words that could be a variant name.
_ATTRIBUTE_WORDS = (
    "bauzeitraum", "produktionszeitraum", "baujahr",
    "hubraum", "leistung", "drehmoment", "motortyp", "motorkenndaten",
    "zylinder", "ventile", "bohrung", "verdichtung", "gemischaufbereitung",
    "motoraufladung", "aufladung", "getriebe", "antrieb", "kraftstoff",
    "höchstgeschwindigkeit", "beschleunigung", "verbrauch", "emission",
    "abgasnorm", "leergewicht", "tankinhalt", "kenngrößen", "nennleistung",
)


def _is_attribute_label(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in _ATTRIBUTE_WORDS) or bool(
        CO2_TOKEN_RE.search(text)
    )


def _clean_cell(raw: str) -> str:
    """A cell's visible text: leading cell-attribute segment and wiki markup
    stripped, whitespace collapsed."""
    content = raw.strip().lstrip("|!").strip()
    head, sep, tail = content.partition("|")
    if sep and "=" in head and "[[" not in head:
        content = tail
    text = mwparserfromhell.parse(content).strip_code()
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _row_cell_texts(row: str) -> list[str]:
    """Every cell of one row, as visible text."""
    cells: list[str] = []
    for line in row.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("|-") or stripped.startswith("{|"):
            continue
        if not (stripped.startswith("|") or stripped.startswith("!")):
            continue
        separator = "!!" if stripped.startswith("!") else "||"
        cells.extend(_clean_cell(part) for part in stripped.split(separator))
    return [c for c in cells if c]


def _first_cell_text(row: str) -> str:
    cells = _row_cell_texts(row)
    return cells[0] if cells else ""


def _starts_with_label_cell(row: str) -> bool:
    """Does this row lead with an attribute label rather than with data?

    Two spellings, both common in the corpus: a ``!`` header cell, or a data
    cell whose content is bold-wrapped — the Kenngrößen-template style, where
    the label is written as ``|align="left" style="…"|`` followed by bold text.
    """
    for line in row.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("|-"):
            continue
        if stripped.startswith("!"):
            return True
        if stripped.startswith("|"):
            content = stripped.lstrip("|")
            # Drop a leading cell-attribute segment ( align="left" style=… | ).
            head, sep, tail = content.partition("|")
            if sep and "=" in head:
                content = tail
            return content.strip().startswith("'" * 3)
        return False
    return False
