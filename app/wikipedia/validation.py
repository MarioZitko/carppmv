"""Phase 3 — mechanical validation of Phase 2's extracted rows. No LLM.

Runs on every extracted variant before it is eligible for Phase 4's upsert.
Failing rows go to a REVIEW QUEUE — flagged, never silently discarded and never
silently inserted. Same "confirm unless certain" posture as
catalogue/matching.py: a wrong CO2 value corrupts a tax result invisibly,
whereas a flagged row is something a human can look at.

Pure and DB-free (tests/test_wikipedia_validation.py).

The one rule that is NOT a validation failure: **null CO2 passes cleanly**
(plan §0). A table without emissions data is an expected, valid outcome, not an
extraction error — flagging it would bury the real failures under thousands of
non-events.
"""

import re
from dataclasses import dataclass, field

# Plausible CO2 band. Below the floor is a unit confusion (g/mile, or a
# fuel-consumption figure read as CO2); above the ceiling is a misread cell —
# the plan's stated ~500 g/km bound. 0 is legitimate: battery-electric rows in
# a mixed table state 0 g/km.
CO2_MIN_PLAUSIBLE = 0.0
CO2_MAX_PLAUSIBLE = 500.0

# Bounds for the supporting specs. Deliberately loose — these exist to catch a
# parse that went sideways (a displacement read out of a price column), not to
# second-guess unusual but real engines.
POWER_KW_MAX_PLAUSIBLE = 1500.0
DISPLACEMENT_CC_MIN_PLAUSIBLE = 200.0
DISPLACEMENT_CC_MAX_PLAUSIBLE = 9000.0

# "2016-06" or "2016". A bare year is accepted on purpose: German tables often
# print only a year, and forcing YYYY-MM would mean inventing a month, which
# §0's no-estimation rule forbids.
_PERIOD_RE = re.compile(r"^(\d{4})(?:-(\d{2}))?$")


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)


def period_sort_key(value: str | None) -> tuple[int, int] | None:
    """Comparable form of a production period, or None if unparseable."""
    if not value:
        return None
    match = _PERIOD_RE.match(value.strip())
    if not match:
        return None
    year = int(match.group(1))
    month = int(match.group(2)) if match.group(2) else 1
    return (year, month)


def validate_variant(variant: dict) -> ValidationResult:
    """Phase 3's checks against one extracted variant.

    Checks (plan §Phase 3):
      - co2_min <= co2_max when both present
      - CO2 within a plausible band (reject negative or > ~500 g/km)
      - power_kw is a positive number when present
      - production_start <= production_end when both present
      - null CO2 is NOT an error
    """
    errors: list[str] = []

    co2_min = variant.get("co2_min")
    co2_max = variant.get("co2_max")
    for name, value in (("co2_min", co2_min), ("co2_max", co2_max)):
        if value is None:
            continue  # §0: expected, not an error
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            errors.append(f"{name} is not a number: {value!r}")
            continue
        if not CO2_MIN_PLAUSIBLE <= value <= CO2_MAX_PLAUSIBLE:
            errors.append(
                f"{name}={value} outside plausible band "
                f"{CO2_MIN_PLAUSIBLE}-{CO2_MAX_PLAUSIBLE} g/km"
            )
    if _is_number(co2_min) and _is_number(co2_max) and co2_min > co2_max:
        errors.append(f"co2_min ({co2_min}) > co2_max ({co2_max})")

    power = variant.get("power_kw")
    if power is not None:
        if not _is_number(power):
            errors.append(f"power_kw is not a number: {power!r}")
        elif power <= 0:
            errors.append(f"power_kw must be positive, got {power}")
        elif power > POWER_KW_MAX_PLAUSIBLE:
            errors.append(f"power_kw={power} exceeds {POWER_KW_MAX_PLAUSIBLE} kW")

    displacement = variant.get("displacement_cc")
    if displacement is not None:
        if not _is_number(displacement):
            errors.append(f"displacement_cc is not a number: {displacement!r}")
        elif not DISPLACEMENT_CC_MIN_PLAUSIBLE <= displacement <= DISPLACEMENT_CC_MAX_PLAUSIBLE:
            errors.append(
                f"displacement_cc={displacement} outside "
                f"{DISPLACEMENT_CC_MIN_PLAUSIBLE}-{DISPLACEMENT_CC_MAX_PLAUSIBLE} cm3"
            )

    start_raw = variant.get("production_start")
    end_raw = variant.get("production_end")
    start = period_sort_key(start_raw)
    end = period_sort_key(end_raw)
    if start_raw and start is None:
        errors.append(f"production_start not YYYY or YYYY-MM: {start_raw!r}")
    if end_raw and end is None:
        errors.append(f"production_end not YYYY or YYYY-MM: {end_raw!r}")
    if start and end and start > end:
        errors.append(f"production_start ({start_raw}) after production_end ({end_raw})")

    return ValidationResult(ok=not errors, errors=errors)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
