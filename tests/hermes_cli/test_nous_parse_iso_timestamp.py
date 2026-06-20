"""Tests for _parse_iso_timestamp in nous_account.

The function must treat naive (timezone-less) ISO timestamps as UTC,
matching the behavior of the identical helper in auth.py. Calling
``.timestamp()`` on a naive datetime interprets it as *local* time,
producing an epoch that drifts by the host's UTC offset.
"""
from __future__ import annotations

from datetime import datetime, timezone

from hermes_cli.nous_account import _parse_iso_timestamp


class TestParseIsoTimestamp:
    def test_naive_timestamp_treated_as_utc(self):
        """A naive ISO timestamp must produce the same epoch as its UTC-suffixed form."""
        naive = "2024-01-15T12:30:00"
        utc_z = "2024-01-15T12:30:00Z"

        naive_epoch = _parse_iso_timestamp(naive)
        utc_epoch = _parse_iso_timestamp(utc_z)

        assert naive_epoch is not None
        assert utc_epoch is not None
        assert naive_epoch == utc_epoch, (
            f"naive ({naive_epoch}) != utc ({utc_epoch}); "
            "naive timestamp was interpreted as local time instead of UTC"
        )

    def test_z_suffix_timestamp(self):
        """Timestamps with Z suffix are correctly parsed as UTC."""
        result = _parse_iso_timestamp("2024-06-01T00:00:00Z")
        expected = datetime(2024, 6, 1, tzinfo=timezone.utc).timestamp()
        assert result is not None
        assert abs(result - expected) < 0.001

    def test_explicit_offset_timestamp(self):
        """Timestamps with explicit offset are correctly parsed."""
        result = _parse_iso_timestamp("2024-06-01T00:00:00+00:00")
        expected = datetime(2024, 6, 1, tzinfo=timezone.utc).timestamp()
        assert result is not None
        assert abs(result - expected) < 0.001

    def test_non_utc_offset(self):
        """A non-UTC offset is honored."""
        result = _parse_iso_timestamp("2024-06-01T15:00:00+05:00")
        expected = datetime(2024, 6, 1, 10, 0, tzinfo=timezone.utc).timestamp()
        assert result is not None
        assert abs(result - expected) < 0.001

    def test_negative_offset(self):
        """A negative offset is honored (regression guard for sign handling)."""
        result = _parse_iso_timestamp("2024-06-01T07:00:00-05:00")
        expected = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc).timestamp()
        assert result is not None
        assert abs(result - expected) < 0.001

    def test_fractional_seconds(self):
        """Fractional seconds are preserved for both naive and aware forms."""
        # Naive with fractional → treated as UTC
        result = _parse_iso_timestamp("2024-06-01T00:00:00.123456")
        expected = datetime(2024, 6, 1, 0, 0, 0, 123456, tzinfo=timezone.utc).timestamp()
        assert result is not None
        assert abs(result - expected) < 0.0001

    def test_date_only_naive(self):
        """A date-only string (midnight) is treated as UTC."""
        result = _parse_iso_timestamp("2024-06-01")
        expected = datetime(2024, 6, 1, tzinfo=timezone.utc).timestamp()
        assert result is not None
        assert abs(result - expected) < 0.001

    def test_whitespace_padded(self):
        """Whitespace around the timestamp is stripped before parsing."""
        result = _parse_iso_timestamp("  2024-06-01T00:00:00Z  ")
        expected = datetime(2024, 6, 1, tzinfo=timezone.utc).timestamp()
        assert result is not None
        assert abs(result - expected) < 0.001

    def test_whitespace_only(self):
        assert _parse_iso_timestamp("   ") is None

    def test_none_input(self):
        assert _parse_iso_timestamp(None) is None

    def test_empty_input(self):
        assert _parse_iso_timestamp("") is None

    def test_non_string_input(self):
        assert _parse_iso_timestamp(12345) is None

    def test_invalid_input(self):
        assert _parse_iso_timestamp("not-a-date") is None
