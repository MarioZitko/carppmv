"""Phase 4's row-building: brand cross-check, CO2 order correction, validation.

`build_rows` is the pure part of app/wikipedia/upsert.py — it turns the Phase 2
extraction store into (eligible, review_queue, wide_corrections) with no
database involved, which is where every decision about what may be stored is
made.
"""

from app.wikipedia.upsert import WIDE_CORRECTED_RANGE_G_KM, UpsertStats, build_rows


def store_with(**variant) -> dict:
    """One-table extraction store holding a single variant."""
    base = {
        "engine_code": "1.6 TDI",
        "production_start": "2015-01",
        "production_end": "2018-01",
        "displacement_cc": 1598,
        "power_kw": 81,
        "fuel_type": "diesel",
        "co2_min": 100,
        "co2_max": 110,
    }
    return {
        "fp0": {
            "brand": variant.pop("_brand", "Audi"),
            "article_title": variant.pop("_title", "Audi A3 8V"),
            "anchor": None,
            "source_url": "https://de.wikipedia.org/wiki/Audi_A3_8V",
            "heading_context": "Technische Daten > Ottomotoren",
            "orientation": "transposed",
            "table_wikitext": "{| ... |}",
            "variants": [{**base, **variant}],
        }
    }


def run(store: dict):
    stats = UpsertStats()
    eligible, review, wide = build_rows(store, None, stats)
    return eligible, review, wide, stats


# --------------------------------------------------------------------------
# CO2 order correction
# --------------------------------------------------------------------------


def test_backwards_range_is_swapped_flagged_and_upserted() -> None:
    """The ordinary case: the source printed the range backwards. 48 of the 49
    corrections in the first run are this, all 28 g/km wide or less."""
    eligible, review, wide, stats = run(store_with(co2_min=147, co2_max=129))

    assert len(eligible) == 1
    assert not review
    assert not wide
    row = eligible[0]
    assert (row["co2_min"], row["co2_max"]) == (129.0, 147.0)
    # Corrected, not silently corrected.
    assert row["source_order_corrected"] is True
    assert stats.co2_order_corrected == 1


def test_correction_runs_before_validation() -> None:
    """A row whose only defect is the ordering must become eligible, not sit in
    the queue forever — the swap is applied first, then Phase 3 re-checks."""
    eligible, review, _wide, _stats = run(store_with(co2_min=147, co2_max=129))
    assert len(eligible) == 1 and not review


def test_implausibly_wide_correction_is_disbelieved_and_held() -> None:
    """`Audi A3 8V / 30 g-tron`, whose wikitext reads "114-12 g/km" — a dropped
    digit on 124 in the Wikipedia source, not a backwards range. Swapping it
    manufactures a 12-114 range that matches neither the car's CNG (~88-99) nor
    its petrol (~115-120) mode, so the correction is refused."""
    eligible, review, wide, stats = run(
        store_with(engine_code="30 g-tron", co2_min=114, co2_max=12)
    )

    assert eligible == []
    assert len(wide) == 1
    assert stats.correction_rejected == 1

    entry = next(r for r in review if r["reason"] == "implausible_correction")
    assert entry["source_fingerprint"] == "fp0"
    assert entry["variant_index"] == 0
    assert "corrupt" in entry["validation_errors"][0]
    # The key the prune step deletes by must be present, or the stale row in the
    # table can never be removed.
    assert {"source_fingerprint", "variant_index"} <= set(entry)


def test_correction_threshold_boundary() -> None:
    """Just inside the band is a real correction; just outside is a corrupt cell."""
    width = WIDE_CORRECTED_RANGE_G_KM
    inside, _, _, _ = run(store_with(co2_min=100 + width, co2_max=100))
    assert len(inside) == 1 and inside[0]["source_order_corrected"] is True

    outside_eligible, outside_review, _, _ = run(
        store_with(co2_min=100 + width + 1, co2_max=100)
    )
    assert outside_eligible == []
    assert outside_review[0]["reason"] == "implausible_correction"


def test_a_wide_range_that_needed_no_correction_is_kept() -> None:
    """Width alone is not an error signal — plenty of real rows span a model's
    whole production era (VW Sharan I 2.8 VR6: 283-326). Only a range that ALSO
    needed swapping is suspect."""
    eligible, review, wide, _stats = run(store_with(co2_min=283, co2_max=326))
    assert len(eligible) == 1
    assert not review and not wide
    assert eligible[0]["source_order_corrected"] is False


# --------------------------------------------------------------------------
# Brand cross-check, at the row level
# --------------------------------------------------------------------------


def test_refiled_row_is_stored_under_the_marque_the_title_names() -> None:
    eligible, review, _wide, stats = run(
        store_with(_brand="Subaru", _title="Opel Zafira")
    )
    assert not review
    row = eligible[0]
    assert row["brand"] == "Opel"          # what Phase 5 filters on
    assert row["crawl_brand"] == "Subaru"  # kept, so the re-filing is auditable
    assert stats.brand_refiled == 1


def test_unverifiable_brand_is_held_not_filed() -> None:
    eligible, review, _wide, stats = run(
        store_with(_brand="Peugeot", _title="Eurovan (PSA/Fiat)")
    )
    assert eligible == []
    assert review[0]["reason"] == "brand_unverified"
    assert stats.brand_unverified == 1


def test_validation_failure_is_queued_never_inserted() -> None:
    eligible, review, _wide, _stats = run(store_with(production_end="04/2024"))
    assert eligible == []
    assert review[0]["reason"] == "phase3_validation"


def test_null_co2_is_not_an_error() -> None:
    """Plan §0: a table with no emissions row is an expected outcome."""
    eligible, review, _wide, _stats = run(store_with(co2_min=None, co2_max=None))
    assert len(eligible) == 1 and not review
