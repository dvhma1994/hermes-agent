"""Regression tests for read_file line counting on files with no trailing newline.

The bug: ShellFileOperations.read_file used ``wc -l`` to compute
``total_lines``, but ``wc -l`` counts *newlines*, not lines.  A non-empty
file whose final line has no trailing newline (e.g. bytes ending
``...line9\\nline10``) was therefore undercounted by 1 (reported 9 instead of
10).  That undercount defeated the truncation check (``total_lines > end_line``
was False when it should be True), so the "use offset=... to continue reading"
hint was never emitted and the model silently never saw the final line — it
was dropped without any indication that more content existed.

These tests exercise the *real* shell path (LocalEnvironment + real wc/awk/sed
running against a real tmp file) so they reproduce the production ``wc -l``
behaviour that caused the bug, not a mocked approximation.

Expected after the fix:
  * a 10-line no-trailing-newline file reports ``total_lines == 10``;
  * reading it with ``limit=9`` sets ``truncated=True`` and emits the continue
    hint, and the dropped ``line10`` is hinted (not silently swallowed);
  * reading it with a limit/offset that reaches the end surfaces ``line10``;
  * an empty file reports 0 lines; a normal trailing-newline file is unchanged.
"""

import os

import pytest

from tools.environments.local import LocalEnvironment
from tools.file_operations import ShellFileOperations


def _make_file(path, body_bytes):
    """Write raw bytes and return the path as a POSIX-ish string for bash."""
    with open(path, "wb") as f:
        f.write(body_bytes)
    return str(path)


@pytest.fixture
def env(tmp_path):
    return LocalEnvironment(cwd=str(tmp_path))


@pytest.fixture
def ops(env, tmp_path):
    return ShellFileOperations(env, cwd=str(tmp_path))


class TestReadFileCountsNoTrailingNewlineLine:
    """The final newline-less line must be counted, never silently dropped."""

    TEN_LINES_NO_NL = (
        b"line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\nline9\nline10"
    )

    def test_total_lines_counts_final_newline_less_line(self, ops, tmp_path):
        path = _make_file(tmp_path / "ten.txt", self.TEN_LINES_NO_NL)
        result = ops.read_file(path, offset=1, limit=500)
        assert result.error is None
        # A 10-line file with no trailing newline has 10 lines, not 9.
        assert result.total_lines == 10
        # The final line is reachable, not silently dropped.
        assert "line10" in result.content

    def test_partial_read_marks_truncated_and_hints_dropped_line(self, ops, tmp_path):
        path = _make_file(tmp_path / "ten.txt", self.TEN_LINES_NO_NL)
        # Read only the first 9 of 10 lines.
        result = ops.read_file(path, offset=1, limit=9)
        assert result.error is None
        # total_lines must be the TRUE count (10) so the truncation check works.
        assert result.total_lines == 10
        # 10 lines total, only 1..9 shown -> there IS more to read.
        assert result.truncated is True
        # The continuation hint must point past the shown range so the model
        # knows line10 exists and how to fetch it.
        assert result.hint is not None
        assert "offset=10" in result.hint
        # line10 is the truncated content: it must NOT appear yet in this page.
        assert "line10" not in result.content

    def test_reading_to_the_end_surfaces_final_line(self, ops, tmp_path):
        path = _make_file(tmp_path / "ten.txt", self.TEN_LINES_NO_NL)
        # limit >= total_lines shows everything including the last line.
        full = ops.read_file(path, offset=1, limit=10)
        assert full.error is None
        assert full.total_lines == 10
        assert full.truncated is False
        assert "line10" in full.content

        # And following the hint (offset=10) lands exactly on the last line.
        tail = ops.read_file(path, offset=10, limit=9)
        assert tail.error is None
        assert tail.total_lines == 10
        assert "line10" in tail.content

    def test_normal_trailing_newline_file_unchanged(self, ops, tmp_path):
        # A file that DOES end with a newline must keep its pre-fix count.
        path = _make_file(tmp_path / "three.txt", b"line1\nline2\nline3\n")
        result = ops.read_file(path, offset=1, limit=500)
        assert result.error is None
        assert result.total_lines == 3
        assert "line3" in result.content

        # Partial read of a trailing-newline file still truncates correctly.
        partial = ops.read_file(path, offset=1, limit=2)
        assert partial.total_lines == 3
        assert partial.truncated is True
        assert partial.hint is not None
        assert "offset=3" in partial.hint

    def test_empty_file_reports_zero_lines(self, ops, tmp_path):
        path = _make_file(tmp_path / "empty.txt", b"")
        result = ops.read_file(path, offset=1, limit=500)
        # An empty file must not be over-counted to 1.
        assert result.total_lines == 0

    def test_file_named_dash_counted_not_read_as_stdin(self, ops, tmp_path):
        # A file literally named "-" must be counted by opening the file,
        # NOT by awk interpreting "-" as stdin.  The count command must use
        # a shell redirect (``< path``) so the shell opens the file, not
        # pass "-" as an awk argument.  Regression guard: the original
        # ``wc -l < {path}`` form opened "-" as a file; switching to awk
        # must preserve that for this edge-case path.
        path = _make_file(tmp_path / "-", b"line1\nline2\nline3")
        result = ops.read_file(str(path), offset=1, limit=500)
        assert result.error is None
        assert result.total_lines == 3
        assert "line3" in result.content
