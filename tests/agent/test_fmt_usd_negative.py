"""Tests for agent.account_usage._fmt_usd negative-balance formatting.

_fmt_usd renders dollar amounts for /usage and account snapshots.  The Nous
credits system explicitly allows negative (debt) balances — see
test_nous_credits_gauge.py::test_gauge_debt_clamps_to_100 which feeds
credits_remaining=-5.0 through the gauge.  A debt balance must render with the
minus sign BEFORE the currency symbol (financial convention: "-$5.00"), not
after it ("$-5.00").
"""

from agent.account_usage import _fmt_usd


def test_fmt_usd_positive():
    assert _fmt_usd(18.0) == "$18.00"


def test_fmt_usd_zero():
    assert _fmt_usd(0.0) == "$0.00"


def test_fmt_usd_negative_places_sign_before_dollar():
    # Regression: previously produced "$-5.00" (sign after currency symbol).
    assert _fmt_usd(-5.0) == "-$5.00"


def test_fmt_usd_negative_large_with_commas():
    assert _fmt_usd(-1234.5) == "-$1,234.50"


def test_fmt_usd_negative_small_magnitude():
    assert _fmt_usd(-0.5) == "-$0.50"


def test_fmt_usd_signed_zero_no_spurious_minus():
    # -0.0 must render as "$0.00", never "-$0.00".
    assert _fmt_usd(-0.0) == "$0.00"


def test_fmt_usd_subcent_debt_rounds_to_zero_no_minus():
    # A sub-cent debt (-0.003) rounds to $0.00 display; the minus sign must
    # not appear on a zero magnitude (would read "-$0.00").
    assert _fmt_usd(-0.003) == "$0.00"