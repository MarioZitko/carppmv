"""Tests for display-only variant formatting (app/catalogue/display.py).

The invariant that matters: already-clean text (any brand without an underscore
blob) must pass through byte-for-byte, and the BMW/MINI spec blob must declutter
without losing the tokens a human picks by (badge, body, drivetrain, doors).
"""

from app.catalogue.display import format_variant_display as fmt


def test_bmw_blob_decluttered():
    v = "BMW 320e_touring_automatski_8stupnjevaprijenosa_5vrata_benzin_1998ccm_120kW"
    assert fmt("BMW", v) == "320e · Touring · Automatski · 8-stup. · 5 vrata"


def test_bmw_blob_keeps_drivetrain_and_iperformance():
    assert fmt("BMW", "BMW 320i xDrive_automatski_8stupnjevaprijenosa_4vrata_1998ccm_135kW") \
        == "320i xDrive · Automatski · 8-stup. · 4 vrata"
    assert fmt("BMW", "BMW 320e iPerformance_automatski_8stupnjevaprijenosa_4vrata_benzin_1998ccm_120kW") \
        == "320e iPerformance · Automatski · 8-stup. · 4 vrata"


def test_bmw_drops_redundant_fuel_power_displacement():
    # benzin (fuel_type field), 120kW (power_kw field), 1998ccm all removed.
    out = fmt("BMW", "BMW 118i_rucni_6stupnjevaPrijenosa_5 vrata_benzin_1499ccm_103kW")
    assert out == "118i · Rucni · 6-stup. · 5 vrata"
    assert "benzin" not in out and "ccm" not in out and "kW" not in out


def test_mini_blob_strips_brand_prefix():
    v = "MINI Cooper S_Hatchback_Automatski_7stupnjevaprijenosa_3vrata_benzin_1998ccm_150kW"
    assert fmt("MINI", v) == "Cooper S · Hatchback · Automatski · 7-stup. · 3 vrata"


def test_legacy_bmw_trim_without_underscore_untouched():
    # These carry real equipment-line trims and no underscore — leave them alone.
    assert fmt("BMW", "116d Shadow Sport") == "116d Shadow Sport"
    assert fmt("BMW", "318d 3UMPH Luxury") == "318d 3UMPH Luxury"


def test_non_bmw_underscore_only_despaced():
    # Incidental underscore in a human name: just space it, drop nothing.
    assert fmt("Kia", "cee'd_hb II 1,4 CRDi EX City Alu") == "cee'd hb II 1,4 CRDi EX City Alu"
    assert fmt("Opel", "Trabus DRW_SRW") == "Trabus DRW SRW"


def test_already_clean_brands_untouched():
    audi = "A5 SB 40TDI S tr S line / Diesel/Hybrid / 2l /150 kW/204 KS / 4-Vrata"
    assert fmt("Audi", audi) == audi
    assert fmt("Volkswagen", "VW Golf 8 2.0 TDI") == "VW Golf 8 2.0 TDI"


def test_none_and_empty_pass_through():
    assert fmt("BMW", None) is None
    assert fmt("BMW", "") == ""


def test_idempotent():
    v = "BMW 320e_touring_automatski_8stupnjevaprijenosa_5vrata_benzin_1998ccm_120kW"
    once = fmt("BMW", v)
    assert fmt("BMW", once) == once  # no underscore left → unchanged
