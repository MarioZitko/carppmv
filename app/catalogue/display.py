"""Display-only formatting for catalogue variant text.

The stored `variant` is whatever the source spreadsheet's KOMPLETNO IME column
held. For most brands that's already human-readable (Audi "A5 SB 40TDI S line /
Diesel/Hybrid / 2l /150 kW/204 KS / 4-Vrata", VW "VW Golf 8 2.0 TDI"), but
BMW/MINI ship a machine spec blob with underscore separators and glued spec
tokens ("BMW 320e_touring_automatski_8stupnjevaprijenosa_5vrata_benzin_1998ccm_120kW").
That blob MUST stay in the DB — its door/transmission/displacement tokens are the
only thing separating same-badge rows with different prices (see ingest.py's
_to_catalogue_dict note) — so this cleanup happens purely at the API-response
boundary, on the way to the UI. It never touches match_key or scoring, and the
picked candidate round-trips by catalogue_id, not by this text, so reformatting
here is display-only and side-effect free.

Two tiers, both gated on the variant actually containing an underscore so every
already-clean brand (Audi, VW, Mercedes, and the legacy BMW trim rows like
"318d 3UMPH Sport") is returned untouched:

  1. BMW/MINI — the known spec-blob layout, decluttered into
     "320e · Touring · Automatski · 8-stup. · 5 vrata": strip the redundant
     leading brand token, drop the fuel word / power / displacement (all shown
     as their own fields in the card), compress the gear-count token, and
     title-case the body/gearbox words.
  2. Any other brand with an incidental underscore in an otherwise human name
     (Kia "cee'd_hb II ...", Opel "Trabus DRW_SRW") — just turn the underscore
     into a space; no structural assumptions, nothing dropped.
"""

import re

# Fuel words are shown as their own `fuel_type` field in the card, so they're
# pure duplication inside the variant text.
_FUEL_DISPLAY_DROP = frozenset({
    "benzin", "benzina", "diesel", "dizel", "gasoline", "hybrid",
})

# Glued spec tokens in the BMW/MINI blob. Matched per underscore-segment.
_SEG_KW = re.compile(r"^\d+\s*kw$", re.IGNORECASE)              # "120kW" — dup of power_kw
_SEG_CCM = re.compile(r"^\d+\s*ccm$", re.IGNORECASE)            # "1998ccm" — engine size, declutter
_SEG_DOORS = re.compile(r"^(\d+)\s*vrata$", re.IGNORECASE)      # "5vrata" -> "5 vrata"
_SEG_GEARS = re.compile(r"^(\d+)\s*stupnjeva.*", re.IGNORECASE)  # "8stupnjevaprijenosa" -> "8-stup."
_LEADING_BRAND = re.compile(r"^(BMW|MINI)\s+", re.IGNORECASE)


def _title_token(seg: str) -> str:
    """Capitalise the first letter only, leaving the rest as-is so mixed-case
    badges survive ("320i xDrive" stays "320i xDrive", not "320i xdrive")."""
    return seg[:1].upper() + seg[1:] if seg else seg


def _format_bmw_blob(variant: str) -> str:
    parts: list[str] = []
    for i, raw in enumerate(variant.split("_")):
        seg = raw.strip()
        if not seg:
            continue
        if seg.lower() in _FUEL_DISPLAY_DROP or _SEG_KW.match(seg) or _SEG_CCM.match(seg):
            continue
        gears = _SEG_GEARS.match(seg)
        if gears:
            parts.append(f"{gears.group(1)}-stup.")
            continue
        doors = _SEG_DOORS.match(seg)
        if doors:
            parts.append(f"{doors.group(1)} vrata")
            continue
        if i == 0:
            seg = _LEADING_BRAND.sub("", seg)  # brand already shown in the card header
        parts.append(_title_token(seg))
    # Fall back to the raw text if the blob was all-noise (never expected, but
    # keeps the function total rather than returning an empty string).
    return " · ".join(parts) if parts else variant


def format_variant_display(brand: str | None, variant: str | None) -> str | None:
    """Human-readable variant for the UI. No-op for already-clean text."""
    if not variant or "_" not in variant:
        return variant
    if (brand or "").strip().lower() in ("bmw", "mini"):
        return _format_bmw_blob(variant)
    return re.sub(r"\s+", " ", variant.replace("_", " ")).strip()
