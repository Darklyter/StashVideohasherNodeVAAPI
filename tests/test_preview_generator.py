"""
Tests for PreviewVideoGenerator.

Covers:
- Short-video guard (get_start_times raises when video is too short)
- Start time calculation correctness
- get_video_duration error handling
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers.preview_video_generator import PreviewVideoGenerator


def _make_generator(**kwargs):
    defaults = dict(
        filename="/fake/video.mp4",
        output_path="/fake/output.mp4",
        filehash="abc123",
        ffmpeg="ffmpeg",
        ffprobe="ffprobe",
        preview_clips=15,
        clip_length=1,
        skip_seconds=15,
        include_audio=False,
        use_vaapi=False,
        vaapi_device=None,
    )
    defaults.update(kwargs)
    return PreviewVideoGenerator(**defaults)


class TestGetStartTimes(unittest.TestCase):
    def setUp(self):
        self.gen = _make_generator(preview_clips=5, clip_length=2, skip_seconds=10)

    def test_raises_on_too_short_video(self):
        # duration=11, skip=10, clip=2 → usable = -1
        with self.assertRaises(RuntimeError) as ctx:
            self.gen.get_start_times(11)
        self.assertIn("too short", str(ctx.exception).lower())

    def test_raises_when_usable_exactly_zero(self):
        # duration=12, skip=10, clip=2 → usable = 0
        with self.assertRaises(RuntimeError):
            self.gen.get_start_times(12)

    def test_returns_correct_count(self):
        # duration=100, skip=10, clip=2, num_clips=5 → 5 start times
        times = self.gen.get_start_times(100)
        self.assertEqual(len(times), 5)

    def test_all_times_after_skip(self):
        times = self.gen.get_start_times(100)
        for t in times:
            self.assertGreaterEqual(t, 10)

    def test_all_times_leave_room_for_clip(self):
        # Each start time + clip_length must be within duration
        times = self.gen.get_start_times(100)
        for t in times:
            self.assertLessEqual(t + 2, 100)

    def test_times_are_ordered(self):
        times = self.gen.get_start_times(100)
        self.assertEqual(times, sorted(times))

    def test_no_skip(self):
        gen = _make_generator(preview_clips=3, clip_length=1, skip_seconds=0)
        times = gen.get_start_times(60)
        self.assertEqual(len(times), 3)
        for t in times:
            self.assertGreaterEqual(t, 0)


class TestGetVideoDuration(unittest.TestCase):
    def setUp(self):
        self.gen = _make_generator()

    def test_parses_valid_output(self):
        mock_result = MagicMock()
        mock_result.stdout = b"123.456\n"
        mock_result.stderr = b""
        with patch("helpers.ffmpeg_utils.run", return_value=mock_result):
            self.assertAlmostEqual(self.gen.get_video_duration(), 123.456, places=2)

    def test_strips_whitespace(self):
        mock_result = MagicMock()
        mock_result.stdout = b"  99.0  \n"
        mock_result.stderr = b""
        with patch("helpers.ffmpeg_utils.run", return_value=mock_result):
            self.assertAlmostEqual(self.gen.get_video_duration(), 99.0, places=1)

    def test_raises_on_empty_output(self):
        mock_result = MagicMock()
        mock_result.stdout = b""
        mock_result.stderr = b"No such file"
        with patch("helpers.ffmpeg_utils.run", return_value=mock_result):
            with self.assertRaises(RuntimeError) as ctx:
                self.gen.get_video_duration()
            self.assertIn("Could not determine duration", str(ctx.exception))

    def test_raises_on_non_numeric_output(self):
        mock_result = MagicMock()
        mock_result.stdout = b"N/A\n"
        mock_result.stderr = b"ffprobe error"
        with patch("helpers.ffmpeg_utils.run", return_value=mock_result):
            with self.assertRaises(RuntimeError):
                self.gen.get_video_duration()


if __name__ == '__main__':
    unittest.main()
