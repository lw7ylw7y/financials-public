"""The screener's saved filter settings: validation, and reading and
writing the `screener_settings` hash. The defaults are
`scoring.ScreenSettings`' and the filters themselves live in
`scoring.py`; this module only turns what the panel sends into a
`ScreenSettings` and back.

The "form" is the panel's shape: field name to {"value": number} and,
for a filter that can be switched off, {"value": number, "on": bool}.
It keeps the number of a switched-off filter, so switching it back on
restores what was typed. A field never saved uses its default, so an
empty hash means every default. A Redis failure raises `KvStoreError`.
"""

import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for _path in (os.path.join(os.path.dirname(_HERE), "web"), _HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import kv_store  # noqa: E402
from scoring import DEFAULT_SETTINGS, ScreenSettings  # noqa: E402

SETTINGS_KEY = "screener_settings"

# Field name to the (lowest, highest) value accepted. Wide enough that
# no sensible threshold is refused, narrow enough to catch a typo.
RANGES = {
    "market_cap_min_m": (0.0, 10_000_000.0),
    "market_cap_max_m": (0.0, 10_000_000.0),
    "net_margin_min": (-100.0, 100.0),
    "fcf_min_m": (-1_000_000.0, 1_000_000.0),
    "max_debt_equity": (0.0, 100.0),
    "max_dilution_pct": (-100.0, 100.0),
    "min_roi_pct": (-100.0, 1000.0),
    "stale_years": (1.0, 100.0),
    "stale_min_growth_pct": (-100.0, 1000.0),
}
# The filters with an on/off switch; the market cap band is always on and
# the growth floor goes with the stale rule's switch.
SWITCHABLE = ("net_margin_min", "fcf_min_m", "max_debt_equity", "max_dilution_pct", "min_roi_pct", "stale_years")
FIELDS = tuple(RANGES)


def default_form() -> dict[str, dict]:
    form = {}
    for name in FIELDS:
        form[name] = {"value": getattr(DEFAULT_SETTINGS, name)}
        if name in SWITCHABLE:
            form[name]["on"] = True
    return form


def _number_error(name: str) -> str:
    low, high = RANGES[name]
    return f"Enter a number between {low:,.0f} and {high:,.0f}."


def validate_form(raw) -> tuple[dict[str, dict], dict[str, str]]:
    """(form, errors): the cleaned form, and a message for each field
    that is wrong. Every field must be present, a number inside its
    range (a switched-off filter's number is checked too), and the
    market cap minimum must be below the maximum. Nothing should be
    saved unless `errors` is empty.
    """
    raw = raw if isinstance(raw, dict) else {}
    form, errors = {}, {}
    for name in FIELDS:
        entry = raw.get(name)
        value = entry.get("value") if isinstance(entry, dict) else None
        low, high = RANGES[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            errors[name] = _number_error(name)
            continue
        form[name] = {"value": float(value)}
        if name in SWITCHABLE:
            on = entry.get("on")
            if not isinstance(on, bool):
                errors[name] = "Switch this filter on or off."
                continue
            form[name]["on"] = on
    if not errors and form["market_cap_min_m"]["value"] >= form["market_cap_max_m"]["value"]:
        errors["market_cap_min_m"] = "The minimum must be below the maximum."
    return form, errors


def to_settings(form: dict[str, dict]) -> ScreenSettings:
    """A `ScreenSettings` from a validated form; a filter switched off
    becomes `None`, which `scoring` does not apply."""
    values = {}
    for name in FIELDS:
        entry = form[name]
        values[name] = entry["value"] if entry.get("on", True) else None
    return ScreenSettings(**values)


def load_form() -> dict[str, dict]:
    """The saved form, each field it has not saved filled from the
    defaults. A stored field that no longer validates falls back to its
    default rather than blocking the page."""
    stored = kv_store.hgetall_json(SETTINGS_KEY)
    form = default_form()
    for name in FIELDS:
        if name in stored:
            candidate = {**form, name: stored[name]}
            cleaned, errors = validate_form(candidate)
            if name not in errors:
                form[name] = cleaned[name]
    return form


def load_settings() -> ScreenSettings:
    """The filters in force."""
    return to_settings(load_form())


def save_form(form: dict[str, dict]) -> None:
    """Saves a validated form in one multi-field write, so a failed
    save leaves the old settings entirely in place."""
    kv_store.hset_many_json(SETTINGS_KEY, {name: form[name] for name in FIELDS})
