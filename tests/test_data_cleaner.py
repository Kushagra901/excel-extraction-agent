from src.core.cleaning_rules import (
    clean_numeric, is_placeholder_null, normalize_email, normalize_phone,
    normalize_whitespace, parse_date_flexible,
)


def test_placeholder_nulls_detected():
    for val in ["", "N/A", "n/a", "NULL", "-", "TBD", None, "unknown"]:
        assert is_placeholder_null(val), f"{val!r} should be a placeholder null"
    assert not is_placeholder_null("Alice")
    assert not is_placeholder_null(0)  # zero is a real value, not null


def test_normalize_whitespace_collapses_and_strips():
    assert normalize_whitespace("  Alice   Johnson  ") == "Alice Johnson"
    assert normalize_whitespace("Alice\xa0Johnson") == "Alice Johnson"
    assert normalize_whitespace("   ") is None


def test_date_parsing_multiple_formats():
    cases = {
        "2026-01-15": "2026-01-15",
        "01/20/2026": "2026-01-20",
        "March 3, 2026": "2026-03-03",
        "3 Mar 2026": "2026-03-03",
    }
    for raw, expected in cases.items():
        value, valid, note = parse_date_flexible(raw)
        assert valid, f"expected {raw!r} to parse"
        assert value == expected


def test_date_parsing_invalid_value_flagged():
    value, valid, note = parse_date_flexible("2026-13-45")
    assert not valid
    assert value is None
    assert "unparseable" in note


def test_clean_numeric_handles_currency_and_parens_negative():
    value, valid, note = clean_numeric("$1,250.00")
    assert valid and value == 1250.0

    value, valid, note = clean_numeric("(150.00)")
    assert valid and value == -150.0

    value, valid, note = clean_numeric("not a number")
    assert not valid and value is None


def test_email_normalization():
    value, valid, note = normalize_email("  Alice.J@Example.COM ")
    assert valid
    assert value == "alice.j@example.com"

    value, valid, note = normalize_email("not-an-email")
    assert not valid


def test_phone_normalization():
    value, valid, note = normalize_phone("(555) 123-4567")
    assert valid
    assert value == "5551234567"

    value, valid, note = normalize_phone("123")
    assert not valid
