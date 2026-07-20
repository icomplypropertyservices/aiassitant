"""Billing / pricing helpers — null-safe labels (offline, no network)."""
from __future__ import annotations

from app.pricing import format_token_count, public_rates, _safe_rate


def test_format_token_count_none_and_invalid():
    """format_token_count never raises on None / bad input (Billing UI labels)."""
    assert format_token_count(None) == "0"
    assert format_token_count("") == "0"
    assert format_token_count("nope") == "0"
    # Non-int types that fail int() still degrade to "0"
    assert format_token_count(object()) == "0"
    assert format_token_count([1, 2]) == "0"


def test_format_token_count_scales():
    assert format_token_count(0) == "0"
    assert format_token_count(42) == "42"
    assert format_token_count(1_500) == "1.5k"
    assert format_token_count(12_000) == "12.0k"
    assert format_token_count(2_500_000) == "2.50M"
    # String digits coerce
    assert format_token_count("1000") == "1.0k"


def test_safe_rate_and_public_rates_offline():
    """public_rates builds a table without raising even if optional fields missing."""
    assert _safe_rate(None) == 0.0
    assert _safe_rate("bad") == 0.0
    assert _safe_rate("1.25") == 1.25

    rates = public_rates()
    assert isinstance(rates, list)
    assert len(rates) >= 1
    for row in rates:
        assert "id" in row or "model" in row or "label" in row
        # Numeric fields must be float-coercible or null — never explode UI
        for key in ("input_per_1m", "output_per_1m", "input", "output", "price"):
            if key in row and row[key] is not None:
                float(row[key])
