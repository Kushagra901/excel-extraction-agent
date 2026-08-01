"""
Deterministic, unit-testable cleaning functions.

Every function here follows the same contract: given a raw cell value
(which may be a string, number, datetime, None, or something weird from
Excel), return a (cleaned_value, is_valid, note) tuple. `note` is only
populated when something noteworthy happened (e.g. a fallback format was
used, or the value could not be parsed at all) so the caller can log it
without re-deriving what happened.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Optional

from src.core.canonical_schema import NULL_PLACEHOLDERS

_WHITESPACE_RE = re.compile(r"\s+")
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_NON_DIGIT_RE = re.compile(r"[^\d+]")
_CURRENCY_SYMBOLS_RE = re.compile(r"[$€£₹,]")

# Order matters: tried top to bottom until one parses cleanly.
_DATE_FORMATS = [
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%m-%d-%Y",
    "%d-%m-%Y",
    "%Y/%m/%d",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d %B %Y",
    "%d %b %Y",
    "%m/%d/%y",
    "%d/%m/%y",
]


def is_placeholder_null(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip().lower() in NULL_PLACEHOLDERS:
        return True
    return False


def normalize_whitespace(value: Any) -> Optional[str]:
    if is_placeholder_null(value):
        return None
    text = str(value)
    text = text.replace("\xa0", " ")  # non-breaking space, common Excel export artifact
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text or None


def clean_text(value: Any) -> tuple[Optional[str], bool, Optional[str]]:
    text = normalize_whitespace(value)
    if text is None:
        return None, False, None
    return text, True, None


def parse_date_flexible(value: Any) -> tuple[Optional[str], bool, Optional[str]]:
    """Returns an ISO 8601 date string (YYYY-MM-DD) or (None, False, note)."""
    if is_placeholder_null(value):
        return None, False, None

    # openpyxl already gives real datetime/date objects for genuine date cells.
    if isinstance(value, dt.datetime):
        return value.date().isoformat(), True, None
    if isinstance(value, dt.date):
        return value.isoformat(), True, None

    text = normalize_whitespace(value)
    if text is None:
        return None, False, None

    for fmt in _DATE_FORMATS:
        try:
            parsed = dt.datetime.strptime(text, fmt)
            note = None if fmt == "%Y-%m-%d" else f"parsed using fallback format '{fmt}'"
            return parsed.date().isoformat(), True, note
        except ValueError:
            continue

    return None, False, f"unparseable date value: '{text}'"


def clean_numeric(value: Any) -> tuple[Optional[float], bool, Optional[str]]:
    if is_placeholder_null(value):
        return None, False, None
    if isinstance(value, (int, float)):
        return float(value), True, None

    text = normalize_whitespace(value)
    if text is None:
        return None, False, None

    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]

    stripped = _CURRENCY_SYMBOLS_RE.sub("", text).strip()
    try:
        num = float(stripped)
        if negative:
            num = -num
        note = "currency symbols/commas stripped" if stripped != text else None
        return num, True, note
    except ValueError:
        return None, False, f"unparseable numeric value: '{text}'"


def normalize_email(value: Any) -> tuple[Optional[str], bool, Optional[str]]:
    text = normalize_whitespace(value)
    if text is None:
        return None, False, None
    text = text.lower()
    if _EMAIL_RE.match(text):
        return text, True, None
    return text, False, f"does not match a valid email pattern: '{text}'"


def normalize_phone(value: Any) -> tuple[Optional[str], bool, Optional[str]]:
    text = normalize_whitespace(value)
    if text is None:
        return None, False, None
    digits_and_plus = _NON_DIGIT_RE.sub("", text)
    digit_count = sum(ch.isdigit() for ch in digits_and_plus)
    if digit_count < 7:
        return digits_and_plus, False, f"too few digits to be a valid phone number: '{text}'"
    if digit_count > 15:
        return digits_and_plus, False, f"too many digits to be a valid phone number: '{text}'"
    return digits_and_plus, True, None


# Dispatch table used by the Data Cleaning Agent -- keyed by the
# `value_type` declared in canonical_schema.CANONICAL_SCHEMA.
CLEANERS = {
    "text": clean_text,
    "date": parse_date_flexible,
    "number": clean_numeric,
    "currency": clean_numeric,
    "email": normalize_email,
    "phone": normalize_phone,
}
