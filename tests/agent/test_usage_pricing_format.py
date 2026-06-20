"""Tests for agent/usage_pricing.format_token_count_compact — compact token display."""

from agent.usage_pricing import format_token_count_compact as _format_tokens


class TestFormatTokenCountCompact:
    def test_below_thousand_returns_plain(self):
        assert _format_tokens(0) == "0"
        assert _format_tokens(999) == "999"

    def test_thousands(self):
        assert _format_tokens(1000) == "1K"
        assert _format_tokens(1500) == "1.5K"

    def test_millions(self):
        assert _format_tokens(1_000_000) == "1M"
        assert _format_tokens(1_500_000) == "1.5M"

    def test_billions(self):
        assert _format_tokens(1_000_000_000) == "1B"

    def test_negative_values(self):
        assert _format_tokens(-1000) == "-1K"
        assert _format_tokens(-1_000_000) == "-1M"

    def test_just_below_million_does_not_render_as_thousands_overflow(self):
        # Regression: 999999 used to render as "1000K" instead of promoting to "1M".
        assert _format_tokens(999999) == "1M"
        assert _format_tokens(999500) == "1M"

    def test_just_below_billion_does_not_render_as_millions_overflow(self):
        # Regression: 999999999 used to render as "1000M" instead of promoting to "1B".
        assert _format_tokens(999999999) == "1B"
        assert _format_tokens(999999500) == "1B"

    def test_trillion_scale_falls_back_to_plain_integer(self):
        # No unit above "B" exists; once the coefficient would overflow at the
        # billions level we must not emit "1000B" — fall back to the full
        # thousands-separated integer instead.
        assert _format_tokens(999_999_999_999) == "999,999,999,999"
        assert _format_tokens(1_500_000_000_000) == "1,500,000,000,000"
        assert _format_tokens(-999_999_999_999) == "-999,999,999,999"

    def test_no_carryover_overflow_anywhere(self):
        # No compact output should ever contain a 4+ digit coefficient before its suffix.
        for value in [9999, 99999, 999499, 999999, 999999499, 999999999]:
            result = _format_tokens(value)
            for suffix in ("K", "M", "B"):
                if result.endswith(suffix):
                    coeff = result[:-1]
                    # allow a leading minus; the numeric coefficient must be < 1000
                    assert abs(float(coeff)) < 1000, f"{value} -> {result!r} coefficient >= 1000"
                    break
