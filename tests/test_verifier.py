"""
Unit tests for the verification logic.
No Ollama or network connection required — tests the comparison rules directly.

Run with:  pytest tests/test_verifier.py -v
"""
import pytest
from app.models import LabelApplication
from app.services.verifier import verify_label


GOOD_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink "
    "alcoholic beverages during pregnancy because of the risk of birth defects. "
    "(2) Consumption of alcoholic beverages impairs your ability to drive a car or "
    "operate machinery, and may cause health problems."
)

BASE_APP = LabelApplication(
    brand_name="OLD TOM DISTILLERY",
    class_type="Kentucky Straight Bourbon Whiskey",
    alcohol_content="45% Alc./Vol. (90 Proof)",
    net_contents="750 mL",
    bottler_info="Old Tom Distillery, Lexington, KY 40511",
)

BASE_EXTRACTED: dict = {
    "brand_name": "OLD TOM DISTILLERY",
    "class_type": "Kentucky Straight Bourbon Whiskey",
    "alcohol_content": "45% Alc./Vol. (90 Proof)",
    "net_contents": "750 mL",
    "bottler_info": "Old Tom Distillery, Lexington, KY 40511",
    "country_of_origin": None,
    "government_warning": GOOD_WARNING,
}


def run(overrides: dict | None = None, app_overrides: dict | None = None):
    extracted = {**BASE_EXTRACTED, **(overrides or {})}
    app = BASE_APP if not app_overrides else BASE_APP.model_copy(update=app_overrides)
    return verify_label(extracted, app, 0)


def field(result, key):
    return next(f for f in result.fields if f.field == key)


# --- Happy path ---

def test_perfect_match_passes():
    result = run()
    assert result.overall_status == "pass"
    assert all(f.status == "pass" for f in result.fields)
    assert result.government_warning.status == "pass"


def test_brand_name_case_difference_passes():
    # Dave's example: "STONE'S THROW" vs "Stone's Throw" — should be acceptable
    result = run(
        overrides={"brand_name": "Stone's Throw"},
        app_overrides={"brand_name": "STONE'S THROW"},
    )
    assert field(result, "brand_name").status == "pass"


def test_extra_whitespace_in_field_passes():
    result = run(overrides={"net_contents": "  750 mL  "})
    assert field(result, "net_contents").status == "pass"


# --- Field mismatches ---

def test_wrong_abv_fails():
    result = run(overrides={"alcohol_content": "46% Alc./Vol. (92 Proof)"})
    assert field(result, "alcohol_content").status == "fail"
    assert result.overall_status == "fail"


def test_wrong_brand_name_fails():
    result = run(overrides={"brand_name": "DIFFERENT DISTILLERY"})
    assert field(result, "brand_name").status == "fail"


def test_wrong_net_contents_fails():
    result = run(overrides={"net_contents": "1 L"})
    assert field(result, "net_contents").status == "fail"


# --- Missing fields ---

def test_missing_field_returns_none_and_fails():
    result = run(overrides={"brand_name": None})
    f = field(result, "brand_name")
    assert f.status == "fail"
    assert f.found is None
    assert "Not found" in f.note


def test_empty_string_field_treated_as_missing():
    result = run(overrides={"bottler_info": ""})
    assert field(result, "bottler_info").status == "fail"


def test_non_string_model_output_handled_safely():
    # Model sometimes returns a number instead of a string; should not crash
    result = run(overrides={"net_contents": 999})
    # 999 doesn't match the 750 mL application value — must fail, not raise
    assert field(result, "net_contents").status == "fail"


# --- Lenient field matching (bare declared value vs full label text) ---

def test_alcohol_content_number_within_label_passes():
    # Application has the bare number; the label wraps it in "ALC. ... BY VOL."
    result = run(
        overrides={"alcohol_content": "ALC. 13.3% BY VOL."},
        app_overrides={"alcohol_content": "13.3"},
    )
    assert field(result, "alcohol_content").status == "pass"


def test_net_contents_spacing_and_case_passes():
    result = run(
        overrides={"net_contents": "750 ML"},
        app_overrides={"net_contents": "750ml"},
    )
    assert field(result, "net_contents").status == "pass"


def test_bottler_name_within_full_line_passes():
    result = run(
        overrides={"bottler_info": "PRODUCED AND BOTTLED BY BRAVIUM WINES, ST. HELENA, NAPA COUNTY, CA"},
        app_overrides={"bottler_info": "BRAVIUM WINES"},
    )
    assert field(result, "bottler_info").status == "pass"


def test_containment_still_rejects_a_real_mismatch():
    # A different ABV must not slip through just because matching is lenient
    result = run(
        overrides={"alcohol_content": "ALC. 14.5% BY VOL."},
        app_overrides={"alcohol_content": "13.3"},
    )
    assert field(result, "alcohol_content").status == "fail"


# --- Government warning ---

def test_government_warning_exact_match_passes():
    result = run()
    assert result.government_warning.status == "pass"


def test_warning_lowercase_prefix_fails():
    bad = GOOD_WARNING.replace("GOVERNMENT WARNING:", "Government Warning:")
    result = run(overrides={"government_warning": bad})
    assert result.government_warning.status == "fail"
    assert "all capital" in result.government_warning.note


def test_warning_missing_fails():
    result = run(overrides={"government_warning": None})
    assert result.government_warning.status == "fail"
    assert result.overall_status == "fail"


def test_warning_truncated_text_fails():
    result = run(overrides={"government_warning": "GOVERNMENT WARNING: This product may be harmful."})
    assert result.government_warning.status == "fail"
    assert "27 CFR" in result.government_warning.note


def test_warning_extra_whitespace_still_passes():
    padded = GOOD_WARNING.replace("birth defects.", "birth  defects.")
    result = run(overrides={"government_warning": padded})
    assert result.government_warning.status == "pass"


def test_warning_all_caps_body_passes():
    # Many real labels print the whole statement in caps (e.g. Captain Morgan).
    # That is compliant as long as the wording and the caps prefix are correct.
    result = run(overrides={"government_warning": GOOD_WARNING.upper()})
    assert result.government_warning.status == "pass"


# --- Optional country of origin ---

def test_country_of_origin_skipped_when_not_in_application():
    result = run()
    assert not any(f.field == "country_of_origin" for f in result.fields)


def test_country_of_origin_checked_when_provided():
    result = run(
        overrides={"country_of_origin": "Scotland"},
        app_overrides={"country_of_origin": "Scotland"},
    )
    assert any(f.field == "country_of_origin" for f in result.fields)
    assert field(result, "country_of_origin").status == "pass"


def test_country_of_origin_wrong_value_fails():
    result = run(
        overrides={"country_of_origin": "Ireland"},
        app_overrides={"country_of_origin": "Scotland"},
    )
    assert field(result, "country_of_origin").status == "fail"
    assert result.overall_status == "fail"
