"""Canonical brand vocabulary — the single source of truth for brand names.

Three call sites depend on this so they can never drift apart:

  1. Ingestion (`app/data/catalogues/ingest.py`) snaps each row's raw brand
     string to a canonical brand, using the file's folder-group as the allowed
     set. This is what fixes source-data defects like the "Marcedes-Benz" typo
     (306 rows in the 2017/2018 price lists) and a stray type code
     ("688978.13") that leaked into a BMW M4's brand cell.
  2. autobid.de's URL-slug parser (`extractors/autobid_de.py`) matches the
     longest canonical brand prefix, so "mercedes-benz-a-200-progressive"
     yields brand "Mercedes-Benz" (not "Mercedes") and model "A 200"
     (not "BENZ") — the bug that made hyphenated-brand listings match nothing.
  3. Lookup (`catalogue/matching.py`) normalizes the incoming listing brand
     before the hard brand filter, so a site that says "Mercedes" still hits
     the catalogue's "Mercedes-Benz" rows.

Deterministic: alias/exact lookup first, then a conservative fuzzy snap against
a bounded allowed set, then a last-resort scan of the row's own free text. No
LLM in this path — the vocabulary is small and closed, so a lookup table is both
cheaper and more predictable than a model call.
"""

import unicodedata

from rapidfuzz import fuzz

# folder slug -> the canonical brands that folder's price lists can contain.
# Importer groups bundle several marques into one Excel/folder; a row's brand
# can only legitimately be one of its group's brands, which is what makes the
# ingest-time snap safe (a fuzzy hit is constrained to this handful, never the
# whole vocabulary).
FOLDER_BRANDS: dict[str, tuple[str, ...]] = {
    "audi-porsche-seat-škoda-volkswagen-cupra": (
        "Audi", "Porsche", "Seat", "Škoda", "Volkswagen", "Cupra",
    ),
    "baic": ("BAIC",),
    "bmw-mini": ("BMW", "MINI"),
    "byd": ("BYD",),
    "chevrolet": ("Chevrolet",),
    "citroën-ds": ("Citroën", "DS"),
    "dacia": ("Dacia",),
    "fiat-lancia-alfa-romeo-abarth-jeep-maserati": (
        "Fiat", "Lancia", "Alfa Romeo", "Abarth", "Jeep", "Maserati",
    ),
    "forthing": ("Forthing",),
    "foton": ("Foton",),
    "geely": ("Geely",),
    "honda": ("Honda",),
    "hyundai": ("Hyundai",),
    "infiniti": ("Infiniti",),
    "isuzu": ("Isuzu",),
    "jaguar": ("Jaguar",),
    "kia": ("Kia",),
    "land-rover": ("Land Rover",),
    "lexus": ("Lexus",),
    "lynkco": ("Lynk & Co",),
    "mazda": ("Mazda",),
    "mercedes-benz-smart": ("Mercedes-Benz", "smart"),
    "mg": ("MG",),
    "mitsubishi": ("Mitsubishi",),
    "nissan": ("Nissan",),
    "omoda-jaecoo": ("Omoda", "Jaecoo"),
    "opel": ("Opel",),
    "peugeot": ("Peugeot",),
    "renault": ("Renault",),
    "ssangyong": ("SsangYong",),
    "subaru": ("Subaru",),
    "suzuki": ("Suzuki",),
    "tata": ("Tata",),
    "toyota": ("Toyota",),
    "volvo": ("Volvo",),
}

# Every individual marque we know about.
CANONICAL_BRANDS: frozenset[str] = frozenset(
    b for brands in FOLDER_BRANDS.values() for b in brands
)

# Known non-canonical spellings -> canonical. Keys are folded (see _fold).
# Covers source typos, short forms and site-specific spellings.
_ALIAS_SEED: dict[str, str] = {
    "marcedes-benz": "Mercedes-Benz",
    "marcedes benz": "Mercedes-Benz",
    "mercedes": "Mercedes-Benz",
    "mercedes benz": "Mercedes-Benz",
    "mercedes-amg": "Mercedes-Benz",
    "mercedes amg": "Mercedes-Benz",
    "amg": "Mercedes-Benz",
    "benz": "Mercedes-Benz",
    "vw": "Volkswagen",
    "skoda": "Škoda",
    "landrover": "Land Rover",
    "land-rover": "Land Rover",
    "range rover": "Land Rover",
    "alfa": "Alfa Romeo",
    "alfa-romeo": "Alfa Romeo",
    "citroen": "Citroën",
    "lynk": "Lynk & Co",
    "lynkco": "Lynk & Co",
    "lynk&co": "Lynk & Co",
}


def _fold(text: str) -> str:
    """Lowercase + strip diacritics + collapse whitespace, so 'Škoda', 'skoda'
    and 'SKODA' all key the same. đ/Đ don't decompose under NFKD."""
    decomposed = unicodedata.normalize("NFKD", text.strip().lower())
    decomposed = decomposed.replace("đ", "d")
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(stripped.split())


# Folded lookup: alias spellings + every canonical brand keyed by its own fold.
_LOOKUP: dict[str, str] = {_fold(canon): canon for canon in CANONICAL_BRANDS}
_LOOKUP.update({_fold(k): v for k, v in _ALIAS_SEED.items()})

# Slug lookup for the URL-slug prefix match: folded brand with spaces/&/- all
# reduced to single '-' tokens, so a hyphen-joined URL slug can be matched
# token-by-token. Value is (canonical, number_of_slug_tokens_it_spans).
def _slugify(text: str) -> str:
    folded = _fold(text)
    out = []
    for ch in folded:
        out.append(ch if ch.isalnum() else "-")
    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")


_SLUG_TO_BRAND: dict[str, str] = {}
for _key, _canon in _LOOKUP.items():
    _SLUG_TO_BRAND[_slugify(_key)] = _canon
_MAX_SLUG_TOKENS = max(len(s.split("-")) for s in _SLUG_TO_BRAND)


def canonical_brand(raw: str | None) -> str | None:
    """Map any brand spelling to its canonical form, or return the input
    unchanged (title-cased-as-given) when it isn't recognised. Never raises."""
    if not raw:
        return raw
    return _LOOKUP.get(_fold(raw), raw)


def brand_from_text(text: str | None, allowed: tuple[str, ...] | None = None) -> str | None:
    """Find the first canonical brand named anywhere in free text (e.g. a
    variant string 'BMW M4 ...'). Restricted to `allowed` when given. Used as
    the last-resort fallback when a row's own brand cell is garbage."""
    if not text:
        return None
    folded = _fold(text)
    tokens = folded.split()
    allowed_set = set(allowed) if allowed else None
    # Try 2-token then 1-token windows so "alfa romeo" / "mercedes benz" win.
    for width in (2, 1):
        for i in range(len(tokens) - width + 1):
            hit = _LOOKUP.get(" ".join(tokens[i : i + width]))
            if hit and (allowed_set is None or hit in allowed_set):
                return hit
    return None


# Below this rapidfuzz ratio, a raw brand is too far from any allowed brand to
# be a confident typo of it (keeps unrelated garbage from snapping onto a
# random brand); we then fall back to reading the brand out of the row text.
_SNAP_CUTOFF = 80.0


def snap_brand(
    raw: str | None,
    allowed: tuple[str, ...],
    *fallback_texts: str | None,
) -> str | None:
    """Ingest-time resolver: return the canonical brand for a row, constrained
    to `allowed` (the file's folder-group brands).

    Order: exact/alias hit within allowed → close fuzzy match within allowed →
    a brand named in the row's own free text → the sole brand if the group has
    only one → None (caller skips the row rather than invent a brand)."""
    canon = canonical_brand(raw)
    if canon in allowed:
        return canon

    if raw:
        folded = _fold(raw)
        best, best_score = None, 0.0
        for b in allowed:
            score = fuzz.ratio(folded, _fold(b))
            if score > best_score:
                best, best_score = b, score
        if best is not None and best_score >= _SNAP_CUTOFF:
            return best

    for text in (raw, *fallback_texts):
        hit = brand_from_text(text, allowed)
        if hit:
            return hit

    if len(allowed) == 1:
        return allowed[0]
    return None


def brand_from_slug_tokens(tokens: list[str]) -> tuple[str | None, int]:
    """Longest canonical brand matched from the start of a hyphen-split URL
    slug. Returns (canonical_brand, tokens_consumed); (None, 0) if no brand
    prefix is recognised (caller keeps its old single-token guess)."""
    for width in range(min(_MAX_SLUG_TOKENS, len(tokens)), 0, -1):
        candidate = "-".join(t.lower() for t in tokens[:width])
        hit = _SLUG_TO_BRAND.get(candidate)
        if hit:
            return hit, width
    return None, 0
