"""Tests for ``_file_metadata`` line counting in ``agent.context_references``.

Regression: the folder-listing metadata helper used ``count("\\n") + 1`` which
over-counted files ending with a trailing newline and reported "1 lines" for
empty files. The fix uses ``len(text.splitlines())`` — the same convention used
elsewhere in the module (``_expand_file_reference``) and in ``tools/file_tools.py``.
"""
from __future__ import annotations

from pathlib import Path

from agent.context_references import _file_metadata


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_empty_file_reports_zero_lines(tmp_path: Path) -> None:
    p = _write(tmp_path / "empty.txt", "")
    assert _file_metadata(p) == "0 lines"


def test_single_line_without_newline(tmp_path: Path) -> None:
    p = _write(tmp_path / "one.txt", "hello")
    assert _file_metadata(p) == "1 lines"


def test_trailing_newline_does_not_overcount(tmp_path: Path) -> None:
    p = _write(tmp_path / "three_nl.txt", "line1\nline2\nline3\n")
    assert _file_metadata(p) == "3 lines"


def test_multi_line_without_final_newline(tmp_path: Path) -> None:
    p = _write(tmp_path / "three.txt", "line1\nline2\nline3")
    assert _file_metadata(p) == "3 lines"


def test_crlf_line_endings(tmp_path: Path) -> None:
    """CRLF files must count lines correctly (one break per \\r\\n, not two).

    write_text would mangle ``\\r\\n`` on Windows (text-mode newline
    translation), so write raw bytes to guarantee the exact CRLF payload.
    """
    p = tmp_path / "crlf.txt"
    p.write_bytes(b"line1\r\nline2\r\nline3\r\n")
    assert _file_metadata(p) == "3 lines"


def test_binary_file_reports_bytes(tmp_path: Path) -> None:
    p = tmp_path / "blob.bin"
    p.write_bytes(b"\x00\x01\x02\x03")
    result = _file_metadata(p)
    assert result.endswith(" bytes")
