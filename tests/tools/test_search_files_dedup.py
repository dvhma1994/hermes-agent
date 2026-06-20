#!/usr/bin/env python3
"""
Tests for the search_files result-deduplication mechanism.

Mirrors read_file's existing mtime-dedup (see test_file_read_guards.py):

1. Two identical consecutive search_files calls with no writes between -> the
   2nd call is served from cache (the underlying scan is NOT re-run).
2. After a write to a file in scope, the next identical search re-runs (the
   shared invalidation mechanism clears the cache, same one read_file uses).
3. Different args (pattern / target / output_mode / context / file_glob /
   pagination) are never served stale.
4. The dedup stub-loop guard escalates to a hard BLOCK after repeated cached
   returns, mirroring read_file's dedup_hits guard.

Run with:  python -m pytest tests/tools/test_search_files_dedup.py -v
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from tools.file_tools import (
    search_tool,
    write_file_tool,
    reset_file_dedup,
    _invalidate_dedup_for_path,
    _read_tracker,
    notify_other_tool_call,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeSearchResult:
    """Minimal stand-in for FileOperations.search return value."""

    def __init__(self, matches=None, truncated=False):
        self.matches = matches if matches is not None else []
        self._truncated = truncated

    def to_dict(self):
        return {
            "matches": self.matches,
            "truncated": self._truncated,
        }


def _make_search_spy_ops(matches=None, truncated=False):
    """A fake file-ops whose ``search`` is a real Mock so call_count works."""
    fake = MagicMock()
    fake.search = MagicMock(
        return_value=_FakeSearchResult(matches=matches, truncated=truncated)
    )
    # write_file used by the invalidation tests.
    fake.write_file = MagicMock(
        return_value=MagicMock(to_dict=lambda: {"success": True})
    )
    fake.read_file = MagicMock(
        return_value=MagicMock(to_dict=lambda: {"content": "x", "total_lines": 1})
    )
    return fake


def _make_safe_tempdir(prefix: str) -> str:
    return tempfile.mkdtemp(prefix=prefix, dir=os.getcwd())


# ---------------------------------------------------------------------------
# Core dedup behaviour
# ---------------------------------------------------------------------------

class TestSearchFilesDedup(unittest.TestCase):
    """Re-running an identical search with an unchanged scope returns cache."""

    def setUp(self):
        _read_tracker.clear()
        self._tmpdir = _make_safe_tempdir("hermes-search-dedup-")
        # A file inside scope so the scope dir has real content.
        self._infile = os.path.join(self._tmpdir, "in_scope.txt")
        with open(self._infile, "w") as f:
            f.write("TODO: fix me\n")

    def tearDown(self):
        _read_tracker.clear()
        try:
            os.unlink(self._infile)
        except OSError:
            pass
        try:
            os.rmdir(self._tmpdir)
        except OSError:
            pass

    @patch("tools.file_tools._get_file_ops")
    def test_second_identical_search_is_cached(self, mock_ops):
        """Acceptance #1: 2 identical consecutive calls -> 2nd is cached."""
        mock_ops.return_value = _make_search_spy_ops(
            matches=[{"file": "in_scope.txt", "line": 1, "text": "TODO: fix me"}]
        )

        # 1st call — real scan.
        r1 = json.loads(search_tool("TODO", path=self._tmpdir, task_id="dup"))
        self.assertNotIn("dedup", r1)
        self.assertEqual(mock_ops.return_value.search.call_count, 1)

        # 2nd identical call — must be served from cache: scan NOT re-run,
        # and the result carries a dedup marker.
        r2 = json.loads(search_tool("TODO", path=self._tmpdir, task_id="dup"))
        self.assertTrue(r2.get("dedup"), "Second identical search should be cached")
        self.assertEqual(
            mock_ops.return_value.search.call_count, 1,
            "Scan must not re-run for an identical cached search",
        )
        # Cached result still carries the matches.
        self.assertIn("matches", r2)

    @patch("tools.file_tools._get_file_ops")
    def test_write_in_scope_invalidates_cache(self, mock_ops):
        """Acceptance #2: after a write to a file in scope, the next identical
        search re-runs because the shared invalidation mechanism clears it."""
        mock_ops.return_value = _make_search_spy_ops(
            matches=[{"file": "in_scope.txt", "line": 1, "text": "TODO: fix me"}]
        )

        # Populate the cache.
        search_tool("TODO", path=self._tmpdir, task_id="inv")
        self.assertEqual(mock_ops.return_value.search.call_count, 1)
        # Confirm dedup engaged.
        search_tool("TODO", path=self._tmpdir, task_id="inv")
        self.assertEqual(mock_ops.return_value.search.call_count, 1)

        # Write to an EXISTING file in scope. Writing an existing file does NOT
        # change the scope dir's mtime (only the file's), so the ONLY thing that
        # can invalidate the cache here is the shared _invalidate_dedup_for_path
        # hook called by write_file_tool -> _update_read_timestamp.
        write_file_tool(self._infile, "TODO: different now\n", task_id="inv")

        # Next identical search must re-run the scan.
        r3 = json.loads(search_tool("TODO", path=self._tmpdir, task_id="inv"))
        self.assertNotEqual(r3.get("dedup"), True,
                            "Search after an in-scope write must not be cached")
        self.assertEqual(
            mock_ops.return_value.search.call_count, 2,
            "Scan must re-run after an in-scope write",
        )

    @patch("tools.file_tools._get_file_ops")
    def test_different_pattern_not_served_stale(self, mock_ops):
        """Acceptance #3: different args never share the cache."""
        mock_ops.return_value = _make_search_spy_ops(
            matches=[{"file": "in_scope.txt", "line": 1, "text": "TODO"}]
        )

        search_tool("TODO", path=self._tmpdir, task_id="diff")
        self.assertEqual(mock_ops.return_value.search.call_count, 1)

        # Different pattern -> must re-run, not served the cached TODO result.
        search_tool("FIXME", path=self._tmpdir, task_id="diff")
        self.assertEqual(mock_ops.return_value.search.call_count, 2)

    @patch("tools.file_tools._get_file_ops")
    def test_different_output_mode_not_served_stale(self, mock_ops):
        """Different output_mode must NOT share the cache (it changes results)."""
        mock_ops.return_value = _make_search_spy_ops(
            matches=[{"file": "in_scope.txt", "line": 1, "text": "TODO"}]
        )

        search_tool("TODO", path=self._tmpdir, output_mode="content", task_id="om")
        search_tool("TODO", path=self._tmpdir, output_mode="files_only", task_id="om")
        # Two distinct args -> two real scans.
        self.assertEqual(mock_ops.return_value.search.call_count, 2)

    @patch("tools.file_tools._get_file_ops")
    def test_different_context_not_served_stale(self, mock_ops):
        """Different context-line count must NOT share the cache."""
        mock_ops.return_value = _make_search_spy_ops(
            matches=[{"file": "in_scope.txt", "line": 1, "text": "TODO"}]
        )

        search_tool("TODO", path=self._tmpdir, context=0, task_id="ctx")
        search_tool("TODO", path=self._tmpdir, context=3, task_id="ctx")
        self.assertEqual(mock_ops.return_value.search.call_count, 2)

    @patch("tools.file_tools._get_file_ops")
    def test_different_pagination_not_served_stale(self, mock_ops):
        """Different offset/limit must NOT share the cache."""
        mock_ops.return_value = _make_search_spy_ops(
            matches=[{"file": "in_scope.txt", "line": 1, "text": "TODO"}]
        )

        search_tool("TODO", path=self._tmpdir, offset=0, limit=50, task_id="pg")
        search_tool("TODO", path=self._tmpdir, offset=50, limit=50, task_id="pg")
        self.assertEqual(mock_ops.return_value.search.call_count, 2)

    @patch("tools.file_tools._get_file_ops")
    def test_different_task_not_served_stale(self, mock_ops):
        """Different task_ids have separate caches."""
        mock_ops.return_value = _make_search_spy_ops(
            matches=[{"file": "in_scope.txt", "line": 1, "text": "TODO"}]
        )

        search_tool("TODO", path=self._tmpdir, task_id="task_a")
        search_tool("TODO", path=self._tmpdir, task_id="task_b")
        self.assertEqual(mock_ops.return_value.search.call_count, 2)

    @patch("tools.file_tools._get_file_ops")
    def test_write_outside_scope_does_not_invalidate(self, mock_ops):
        """A write to a file NOT in the search scope must not evict the cache."""
        other_dir = _make_safe_tempdir("hermes-search-other-")
        other_file = os.path.join(other_dir, "unrelated.txt")
        try:
            with open(other_file, "w") as f:
                f.write("data\n")

            mock_ops.return_value = _make_search_spy_ops(
                matches=[{"file": "in_scope.txt", "line": 1, "text": "TODO"}]
            )

            search_tool("TODO", path=self._tmpdir, task_id="iso")
            self.assertEqual(mock_ops.return_value.search.call_count, 1)

            # Write to a file in a DIFFERENT directory.
            write_file_tool(other_file, "changed\n", task_id="iso")

            # In-scope identical search should STILL be cached.
            r = json.loads(search_tool("TODO", path=self._tmpdir, task_id="iso"))
            self.assertTrue(r.get("dedup"),
                            "Out-of-scope write must not invalidate the search cache")
            self.assertEqual(mock_ops.return_value.search.call_count, 1)
        finally:
            try:
                os.unlink(other_file)
            except OSError:
                pass
            try:
                os.rmdir(other_dir)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Dedup stub-loop guard (mirrors read_file's dedup_hits escalation)
# ---------------------------------------------------------------------------

class TestSearchDedupStubLoopGuard(unittest.TestCase):
    """Repeated cached returns must escalate to a hard BLOCK so a weak
    tool-follower doesn't burn iteration budget in a
    ``search -> cached -> search -> cached -> ...`` loop."""

    def setUp(self):
        _read_tracker.clear()
        self._tmpdir = _make_safe_tempdir("hermes-search-loop-")

    def tearDown(self):
        _read_tracker.clear()
        try:
            os.rmdir(self._tmpdir)
        except OSError:
            pass

    @patch("tools.file_tools._get_file_ops")
    def test_third_search_is_blocked(self, mock_ops):
        """search -> cached -> BLOCKED. Second cached return escalates."""
        mock_ops.return_value = _make_search_spy_ops(matches=[])

        # 1. Real search.
        r1 = json.loads(search_tool("def main", path=self._tmpdir, task_id="loop"))
        self.assertNotIn("dedup", r1)
        self.assertNotIn("error", r1)

        # 2. Cached (1st hit).
        r2 = json.loads(search_tool("def main", path=self._tmpdir, task_id="loop"))
        self.assertTrue(r2.get("dedup"))
        self.assertNotIn("error", r2)

        # 3. Cached (2nd hit) — escalates to BLOCKED, mirroring read_file.
        r3 = json.loads(search_tool("def main", path=self._tmpdir, task_id="loop"))
        self.assertIn("error", r3, "Second cached return should be BLOCKED")
        self.assertIn("BLOCKED", r3["error"])
        self.assertIn("STOP", r3["error"])
        self.assertEqual(r3.get("already_searched"), 3)
        self.assertNotIn("dedup", r3)

    @patch("tools.file_tools._get_file_ops")
    def test_other_tool_call_resets_hits(self, mock_ops):
        """An intervening non-search tool call resets the stub-hit counter."""
        mock_ops.return_value = _make_search_spy_ops(matches=[])

        search_tool("def main", path=self._tmpdir, task_id="loop")
        search_tool("def main", path=self._tmpdir, task_id="loop")  # 1st cached hit

        notify_other_tool_call("loop")  # dispatcher signals another tool ran

        r3 = json.loads(search_tool("def main", path=self._tmpdir, task_id="loop"))
        # Should be cached again, NOT blocked.
        self.assertTrue(r3.get("dedup"))
        self.assertNotIn("error", r3)


# ---------------------------------------------------------------------------
# Reset on compression + invalidation helper noop safety
# ---------------------------------------------------------------------------

class TestSearchDedupResetAndInvalidation(unittest.TestCase):
    """reset_file_dedup clears the search cache; the invalidation helper is
    safe on edge cases."""

    def setUp(self):
        _read_tracker.clear()
        self._tmpdir = _make_safe_tempdir("hermes-search-reset-")

    def tearDown(self):
        _read_tracker.clear()
        try:
            os.rmdir(self._tmpdir)
        except OSError:
            pass

    @patch("tools.file_tools._get_file_ops")
    def test_reset_clears_search_dedup(self, mock_ops):
        """reset_file_dedup (post-compression) clears the search cache too."""
        mock_ops.return_value = _make_search_spy_ops(matches=[])

        search_tool("TODO", path=self._tmpdir, task_id="reset")
        r_dedup = json.loads(search_tool("TODO", path=self._tmpdir, task_id="reset"))
        self.assertTrue(r_dedup.get("dedup"), "Should dedup before reset")

        reset_file_dedup("reset")

        r_post = json.loads(search_tool("TODO", path=self._tmpdir, task_id="reset"))
        self.assertNotEqual(r_post.get("dedup"), True,
                            "Post-reset search must re-run")

    def test_invalidate_dedup_for_path_noop_on_missing_task(self):
        """Invalidating a path for a task with no search cache is safe."""
        _read_tracker.clear()
        _invalidate_dedup_for_path("/nonexistent/path", "no_such_task")

    def test_invalidate_dedup_for_path_clears_in_scope_search(self):
        """Directly verify _invalidate_dedup_for_path evicts an in-scope entry."""
        _read_tracker.clear()
        scope = self._tmpdir
        in_scope_file = os.path.join(scope, "inner.txt")
        skey = (scope, "TODO", "content", "", 50, 0, "content", 0)
        _read_tracker["t"] = {
            "last_key": None, "consecutive": 0, "read_history": set(),
            "dedup": {}, "dedup_hits": {}, "search_dedup": {
                skey: (1.0, {"matches": []}, False),
            },
        }
        _invalidate_dedup_for_path(in_scope_file, "t")
        self.assertNotIn(skey, _read_tracker["t"]["search_dedup"],
                         "In-scope file write must evict the search cache entry")

    def test_invalidate_dedup_for_path_keeps_out_of_scope_search(self):
        """A write outside the scope must NOT evict an unrelated search entry."""
        _read_tracker.clear()
        scope = self._tmpdir
        other_file = os.path.join(_make_safe_tempdir("hermes-search-oos-"), "x.txt")
        skey = (scope, "TODO", "content", "", 50, 0, "content", 0)
        _read_tracker["t"] = {
            "last_key": None, "consecutive": 0, "read_history": set(),
            "dedup": {}, "dedup_hits": {}, "search_dedup": {
                skey: (1.0, {"matches": []}, False),
            },
        }
        try:
            _invalidate_dedup_for_path(other_file, "t")
            self.assertIn(skey, _read_tracker["t"]["search_dedup"],
                          "Out-of-scope write must not evict the search entry")
        finally:
            d = os.path.dirname(other_file)
            try:
                os.unlink(other_file)
            except OSError:
                pass
            try:
                os.rmdir(d)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Worktree / multi-cwd regression (task_id resolution mismatch)
# ---------------------------------------------------------------------------

class TestWorktreeResolutionMismatch(unittest.TestCase):
    """Regression: in a worktree session the WRITE's task_id has a different
    base dir than ``"default"``.  ``search_files`` resolves its scope with the
    real ``task_id``, and ``_invalidate_dedup_for_path`` must resolve the
    written file with the SAME ``task_id`` — not hard-code ``"default"`` —
    otherwise the two resolved paths land in different directories and an
    in-scope relative write fails to invalidate the cache (acceptance #2)."""

    def setUp(self):
        _read_tracker.clear()
        self._wt_dir = _make_safe_tempdir("hermes-wt-")
        self._default_dir = _make_safe_tempdir("hermes-def-")
        with open(os.path.join(self._wt_dir, "target.py"), "w") as f:
            f.write("# old\n")

    def tearDown(self):
        _read_tracker.clear()
        for d in (self._wt_dir, self._default_dir):
            for fn in os.listdir(d):
                try:
                    os.unlink(os.path.join(d, fn))
                except OSError:
                    pass
            try:
                os.rmdir(d)
            except OSError:
                pass

    @patch("tools.file_tools._get_file_ops")
    def test_in_scope_relative_write_invalidates(self, mock_ops):
        """Acceptance #2 in a worktree session (relative path, default scope '.').

        The search scope resolves to the worktree dir; the relative write
        should land inside it and invalidate the cache.  This would FAIL if
        ``_invalidate_dedup_for_path`` resolved the written file with
        ``task_id='default'`` instead of the write's real ``task_id``.
        """
        from pathlib import Path
        import tools.file_tools as ft

        mock_ops.return_value = _make_search_spy_ops(matches=[])

        # Patch _resolve_base_dir so each task_id resolves to a different dir:
        #   'wt'      -> worktree dir  (where the search scope '.' lives)
        #   'default' -> the OTHER dir (what _resolve_path would hard-code)
        def fake_base(task_id="default"):
            if task_id == "wt":
                return Path(self._wt_dir).resolve()
            return Path(self._default_dir).resolve()

        with patch.object(ft, "_resolve_base_dir", side_effect=fake_base):
            # Sanity: confirm the two base dirs differ (the worktree scenario).
            self.assertNotEqual(
                str(ft._resolve_path_for_task(".", "wt")),
                str(ft._resolve_path_for_task(".", "default")),
            )

            # 1. Search with default scope "." in the worktree task.
            search_tool("TODO", path=".", task_id="wt")
            self.assertEqual(mock_ops.return_value.search.call_count, 1)

            # 2. Write to a RELATIVE path (in the worktree) with the SAME task.
            write_file_tool("target.py", "# new TODO here\n", task_id="wt")

            # 3. The next identical search MUST re-run (acceptance #2).
            r3 = json.loads(search_tool("TODO", path=".", task_id="wt"))
            self.assertNotEqual(
                r3.get("dedup"), True,
                "In-scope relative write must invalidate the search cache "
                "(it should NOT be served stale)",
            )
            self.assertEqual(
                mock_ops.return_value.search.call_count, 2,
                "Scan must re-run after an in-scope relative write",
            )


if __name__ == "__main__":
    unittest.main()
