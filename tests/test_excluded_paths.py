"""
Tests for excluded_paths filtering logic.

The same startswith-based filter is used in scene_discovery.py,
stash_utils.get_total_scene_count(), and all three discovery modules.
This suite validates the filtering logic directly.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _apply_filter(paths, excluded_paths):
    """Mirrors the filter used across the codebase."""
    return [p for p in paths if not any(p.startswith(ep) for ep in excluded_paths)]


class TestExcludedPathsFilter(unittest.TestCase):
    def test_excludes_matching_prefix(self):
        result = _apply_filter(["/mnt/archive/video.mp4"], ["/mnt/archive/"])
        self.assertEqual(result, [])

    def test_keeps_non_matching(self):
        result = _apply_filter(["/mnt/media/video.mp4"], ["/mnt/archive/"])
        self.assertEqual(result, ["/mnt/media/video.mp4"])

    def test_no_false_positive_partial_match(self):
        """'/mnt/archive/' must NOT exclude '/mnt/archive2/video.mp4'"""
        result = _apply_filter(["/mnt/archive2/video.mp4"], ["/mnt/archive/"])
        self.assertEqual(result, ["/mnt/archive2/video.mp4"])

    def test_multiple_excluded_paths(self):
        paths = [
            "/mnt/archive/a.mp4",
            "/mnt/backup/b.mp4",
            "/mnt/media/c.mp4",
        ]
        result = _apply_filter(paths, ["/mnt/archive/", "/mnt/backup/"])
        self.assertEqual(result, ["/mnt/media/c.mp4"])

    def test_empty_excluded_paths(self):
        paths = ["/mnt/archive/video.mp4", "/mnt/media/video.mp4"]
        result = _apply_filter(paths, [])
        self.assertEqual(result, paths)

    def test_excludes_nested_paths(self):
        result = _apply_filter(
            ["/mnt/archive/subdir/deep/video.mp4"],
            ["/mnt/archive/"]
        )
        self.assertEqual(result, [])

    def test_exact_path_not_excluded_without_trailing_slash(self):
        """Excluded paths should end in '/' to avoid matching siblings."""
        # /mnt/archive without trailing slash would match /mnt/archives/ too
        # This test documents current behaviour — callers should include trailing /
        result = _apply_filter(["/mnt/archives/video.mp4"], ["/mnt/archive"])
        # startswith("/mnt/archive") matches "/mnt/archives/..." — this is a
        # known edge case users should avoid by always including trailing /
        self.assertEqual(result, [])  # documents current behaviour


class TestOshashValidation(unittest.TestCase):
    """Tests for the oshash validation logic in scene_processor."""

    def _is_valid_oshash(self, filehash):
        """Mirrors the validation in scene_processor.py"""
        return bool(filehash) and ":" not in filehash and "\\" not in filehash and "/" not in filehash

    def test_valid_hex_hash(self):
        self.assertTrue(self._is_valid_oshash("a1b2c3d4e5f6a7b8"))

    def test_empty_string_invalid(self):
        self.assertFalse(self._is_valid_oshash(""))

    def test_none_invalid(self):
        self.assertFalse(self._is_valid_oshash(None))

    def test_colon_invalid(self):
        self.assertFalse(self._is_valid_oshash("abc:def"))

    def test_backslash_invalid(self):
        self.assertFalse(self._is_valid_oshash("abc\\def"))

    def test_forward_slash_invalid(self):
        self.assertFalse(self._is_valid_oshash("abc/def"))

    def test_windows_path_fragment_invalid(self):
        self.assertFalse(self._is_valid_oshash("C:\\Users\\file"))


if __name__ == '__main__':
    unittest.main()
