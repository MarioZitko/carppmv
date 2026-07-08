"""Tests for the autobid.de URL-slug brand/model fallback parser."""

from app.scraping.extractors.autobid_de import _brand_model_from_url_slug


def test_engine_badge_after_digit_containing_model_is_not_appended():
    # Regression: "audi-a4-40-tdi-s-tronic" must parse as model "A4", not
    # "A4 40" — "40" here is the engine-displacement badge (paired with TDI),
    # not part of the model name. The bogus "A4 40" previously made every
    # genuine A4 catalogue row fail the matcher's model-similarity check.
    brand, model = _brand_model_from_url_slug(
        "https://autobid.de/hr/artikal/audi-a4-40-tdi-s-tronic-3473241"
    )
    assert brand == "Audi"
    assert model == "A4"


def test_numeric_badge_after_bare_letter_model_is_appended():
    # Mercedes-style slugs spell the model as a bare letter + number
    # ("a-200" -> "A 200"), where the digit genuinely completes the model name.
    brand, model = _brand_model_from_url_slug(
        "https://autobid.de/hr/artikal/mercedes-benz-a-200-1234567"
    )
    assert brand == "Mercedes-Benz"
    assert model == "A 200"
