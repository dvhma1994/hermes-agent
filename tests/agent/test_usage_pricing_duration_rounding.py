"""Tests for agent/usage_pricing.py — format_duration_compact rounding boundary."""

from agent.usage_pricing import format_duration_compact


class TestFormatDurationRoundingBoundary:
    """Regression: values near 60 minutes must not round up to '60m'."""

    def test_just_under_60min_rounds_to_59m(self):
        # 59.5 minutes = 3570s — must display as "60m" is wrong; "1h" or "59m" is correct
        assert format_duration_compact(3570) != "60m"

    def test_3590_seconds(self):
        assert format_duration_compact(3590) != "60m"

    def test_3599_seconds(self):
        assert format_duration_compact(3599) != "60m"

    def test_3599_99_seconds(self):
        assert format_duration_compact(3599.99) != "60m"

    def test_3540_seconds_still_59m(self):
        assert format_duration_compact(3540) == "59m"

    def test_3600_seconds_is_1h(self):
        assert format_duration_compact(3600) == "1h"

    def test_round_to_nearest_minute_unchanged(self):
        # Non-boundary minutes values must keep original round-to-nearest behavior
        assert format_duration_compact(90) == "2m"    # 1m30s -> 2m
        assert format_duration_compact(119) == "2m"   # 1m59s -> 2m
        assert format_duration_compact(179) == "3m"   # 2m59s -> 3m
        assert format_duration_compact(899) == "15m"  # 14m59s -> 15m
        assert format_duration_compact(1799) == "30m" # 29m59s -> 30m

    def test_boundary_3570_rounds_up_to_1h(self):
        # 59m30s rounds up to exactly 1h, not "60m"
        assert format_duration_compact(3570) == "1h"