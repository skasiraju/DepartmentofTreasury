from __future__ import annotations
import time
from app.models import FieldResult, LabelApplication, VerificationResponse, WarningResult

# Exact text required by 27 CFR Part 16
_REQUIRED_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink "
    "alcoholic beverages during pregnancy because of the risk of birth defects. "
    "(2) Consumption of alcoholic beverages impairs your ability to drive a car or "
    "operate machinery, and may cause health problems."
)


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _soft_match(expected: str, found: str) -> bool:
    """Case-insensitive, whitespace-normalized comparison.
    Handles common OCR/formatting differences like 'STONE'S THROW' vs 'Stone's Throw'."""
    return _normalize(expected) == _normalize(found)


def _coerce(value: object) -> str | None:
    """Safely convert model output to string, treating empty/null as missing."""
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _check_field(
    field_key: str,
    field_label: str,
    expected: str,
    raw_found: object,
) -> FieldResult:
    found = _coerce(raw_found)

    if found is None:
        return FieldResult(
            field=field_key,
            label=field_label,
            status="fail",
            expected=expected,
            found=None,
            note="Not found on label",
        )

    matched = _soft_match(expected, found)
    return FieldResult(
        field=field_key,
        label=field_label,
        status="pass" if matched else "fail",
        expected=expected,
        found=found,
        note=None if matched else "Text does not match application",
    )


def _check_government_warning(raw_found: object) -> WarningResult:
    found = _coerce(raw_found)

    if found is None:
        return WarningResult(
            status="fail",
            found=None,
            note="Government warning statement not found on label",
        )

    # Normalise whitespace for comparison, but preserve original capitalisation for the prefix check
    normalized_found = " ".join(found.split())
    normalized_required = " ".join(_REQUIRED_WARNING.split())

    # The "GOVERNMENT WARNING:" prefix must be in all caps — this is a common
    # rejection reason and one of the few things TTB is explicit about.
    if not normalized_found.startswith("GOVERNMENT WARNING:"):
        return WarningResult(
            status="fail",
            found=found,
            note='"GOVERNMENT WARNING:" prefix must appear in all capital letters',
        )

    # The wording must match word-for-word, but the body may be printed in any
    # case — plenty of labels set the whole statement in caps — so compare the
    # rest case-insensitively.
    if normalized_found.lower() != normalized_required.lower():
        return WarningResult(
            status="fail",
            found=found,
            note="Warning text does not match the required TTB statement (27 CFR Part 16)",
        )

    return WarningResult(
        status="pass",
        found=found,
        note="Required warning statement present and exact",
    )


def verify_label(
    extracted: dict[str, object],
    application: LabelApplication,
    start_ms: int,
) -> VerificationResponse:
    fields = [
        _check_field("brand_name",      "Brand Name",        application.brand_name,      extracted.get("brand_name")),
        _check_field("class_type",      "Class / Type",      application.class_type,      extracted.get("class_type")),
        _check_field("alcohol_content", "Alcohol Content",   application.alcohol_content, extracted.get("alcohol_content")),
        _check_field("net_contents",    "Net Contents",      application.net_contents,    extracted.get("net_contents")),
        _check_field("bottler_info",    "Bottler / Producer", application.bottler_info,   extracted.get("bottler_info")),
    ]

    if application.country_of_origin.strip():
        fields.append(
            _check_field(
                "country_of_origin",
                "Country of Origin",
                application.country_of_origin,
                extracted.get("country_of_origin"),
            )
        )

    government_warning = _check_government_warning(extracted.get("government_warning"))

    all_pass = all(f.status == "pass" for f in fields) and government_warning.status == "pass"

    return VerificationResponse(
        overall_status="pass" if all_pass else "fail",
        fields=fields,
        government_warning=government_warning,
        processing_time_ms=int(time.time() * 1000) - start_ms,
    )
