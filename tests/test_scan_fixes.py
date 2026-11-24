"""
Regression tests for the fixes from the project scan:
- CLI flags / config values are read live (dry-run really is dry)
- CLI flags only override config.py when actually passed
- Path translation is prefix-anchored with an existence fallback
- Filemask → Stash regex conversion
- ffmpeg wrapper: timeouts, shutdown handling, atomic outputs
- Short videos still get a preview plan
"""

import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from helpers import ffmpeg_utils, paths, stash_utils
from helpers.preview_video_generator import PreviewVideoGenerator


class TestDryRunIsLive(unittest.TestCase):
    """--dry-run is applied after modules are imported; it must still take effect."""

    def test_no_stash_writes_in_dry_run(self):
        fake = MagicMock()
        with patch.object(stash_utils, "stash", fake), patch.object(config, "dry_run", True):
            stash_utils.claim_scene(1)
            stash_utils.release_scene(1)
            stash_utils.tag_scene_error(1, 99, "boom")
            stash_utils.clear_error_tags([1, 2])
            stash_utils.clear_hashing_tags([1, 2])
            stash_utils.update_phash(1, "abc")
            stash_utils.update_cover(1, "data")
        self.assertEqual(fake.mock_calls, [])

    def test_writes_happen_without_dry_run(self):
        fake = MagicMock()
        with patch.object(stash_utils, "stash", fake), patch.object(config, "dry_run", False):
            stash_utils.claim_scene(1)
        fake.update_scenes.assert_called_once()


class TestCliOverrides(unittest.TestCase):
    def _args(self, argv):
        import phash_videohasher_main as main_mod
        captured = {}
        with patch.object(main_mod, "_run", side_effect=lambda a: captured.setdefault("args", a) and 0), \
             patch.object(main_mod.signal, "signal"), \
             patch.object(main_mod.ffmpeg_utils, "clean_tmp"), \
             patch.object(main_mod, "reset_terminal"), \
             patch.object(sys, "argv", ["prog"] + argv):
            with self.assertRaises(SystemExit):
                main_mod.main()
        return captured["args"]

    def test_config_values_survive_when_flag_absent(self):
        with patch.object(config, "generate_markers", True), patch.object(config, "verbose", True), \
             patch.object(config, "dry_run", False):
            self._args([])
            self.assertTrue(config.generate_markers)
            self.assertTrue(config.verbose)
            self.assertFalse(config.dry_run)

    def test_flags_override_config(self):
        with patch.object(config, "dry_run", False), patch.object(config, "nvenc", False), \
             patch.object(config, "max_workers", 4):
            self._args(["--dry-run", "--nvenc", "--max-workers", "2"])
            self.assertTrue(config.dry_run)
            self.assertTrue(config.nvenc)
            self.assertEqual(config.max_workers, 2)

    def test_nvenc_flag_reaches_encoder_selection(self):
        with patch.object(config, "nvenc", True):
            _, out = ffmpeg_utils.h264_encode_args(False, None)
        self.assertIn("h264_nvenc", out)


class TestTranslatePath(unittest.TestCase):
    def test_prefix_only(self):
        tr = [{'orig': '/data/', 'local': '/mnt/a/'}, {'orig': '/xerxes/', 'local': '/mnt/x/'}]
        with patch.object(config, "translations", tr):
            self.assertEqual(paths.translate_path('/data/v.mp4'), '/mnt/a/v.mp4')
            # '/data/' in the middle of a path must not be rewritten
            self.assertEqual(paths.translate_path('/xerxes/data/v.mp4'), '/mnt/x/data/v.mp4')
            self.assertEqual(paths.translate_path('/other/data/v.mp4'), '/other/data/v.mp4')

    def test_alternative_mounts_use_the_one_that_exists(self):
        with tempfile.TemporaryDirectory() as d:
            real = os.path.join(d, "Real") + os.sep
            os.makedirs(real)
            open(os.path.join(real, "v.mp4"), "w").close()
            tr = [{'orig': '/s/', 'local': os.path.join(d, "missing") + os.sep},
                  {'orig': '/s/', 'local': real}]
            with patch.object(config, "translations", tr):
                self.assertEqual(paths.translate_path('/s/v.mp4'), os.path.join(real, "v.mp4"))
                # nothing exists → first candidate
                self.assertEqual(paths.translate_path('/s/nope.mp4'),
                                 os.path.join(d, "missing", "nope.mp4"))


class TestFilemaskRegex(unittest.TestCase):
    def test_glob_conversion(self):
        import re
        rx = re.compile(stash_utils._glob_to_regex("JoonMali*"))
        self.assertTrue(rx.search("/data/x/JoonMali 2024.mp4"))
        self.assertFalse(rx.search("/data/JoonMali/other.mp4"))
        self.assertFalse(rx.search("/data/x/NotJoonMali.mp4"))
        rx = re.compile(stash_utils._glob_to_regex("*.mp4"))
        self.assertTrue(rx.search("/a/b (1).mp4"))
        self.assertFalse(rx.search("/a/b.mp4.bak"))

    def test_filter_includes_exclusions_and_mask(self):
        with patch.object(config, "excluded_paths", ["/mnt/archive/"]), patch.object(config, "filemask", "A*"):
            f = stash_utils.pending_scene_filter()
        self.assertEqual(f["path"]["modifier"], "NOT_MATCHES_REGEX")
        self.assertEqual(f["AND"]["path"]["modifier"], "MATCHES_REGEX")


class TestRunWrapper(unittest.TestCase):
    def tearDown(self):
        ffmpeg_utils.shutdown_event.clear()

    def test_success_and_failure(self):
        ok = ffmpeg_utils.run([sys.executable, "-c", "print('hi')"], timeout=20)
        self.assertEqual(ok.stdout.strip(), b"hi")
        with self.assertRaises(subprocess.CalledProcessError) as ctx:
            ffmpeg_utils.run([sys.executable, "-c", "import sys; sys.stderr.write('bad\\n'); sys.exit(3)"], timeout=20)
        self.assertEqual(ffmpeg_utils.error_detail(ctx.exception), "bad")

    def test_timeout_kills_child(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            ffmpeg_utils.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.5)

    def test_shutdown_stops_running_child_without_error(self):
        import threading, time
        outcome = {}

        def worker():
            try:
                ffmpeg_utils.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=60)
            except BaseException as e:  # noqa
                outcome["exc"] = e

        t = threading.Thread(target=worker)
        start = time.time()
        t.start()
        time.sleep(0.5)
        ffmpeg_utils.request_shutdown()
        t.join(timeout=10)
        self.assertFalse(t.is_alive())
        self.assertLess(time.time() - start, 8)
        self.assertIsInstance(outcome["exc"], ffmpeg_utils.ShutdownRequested)
        # An interrupted job must not be catchable as an ordinary failure
        self.assertNotIsInstance(outcome["exc"], Exception)

    def test_no_new_children_after_shutdown(self):
        ffmpeg_utils.shutdown_event.set()
        with self.assertRaises(ffmpeg_utils.ShutdownRequested):
            ffmpeg_utils.run([sys.executable, "-c", "pass"], timeout=5)


class TestAtomicOutput(unittest.TestCase):
    def test_renamed_on_success(self):
        with tempfile.TemporaryDirectory() as d:
            final = os.path.join(d, "out.mp4")
            with ffmpeg_utils.atomic_output(final) as tmp:
                self.assertTrue(tmp.endswith("out.mp4"))
                with open(tmp, "w") as f:
                    f.write("x")
            self.assertTrue(os.path.exists(final))
            self.assertEqual(os.listdir(d), ["out.mp4"])

    def test_nothing_left_on_failure(self):
        with tempfile.TemporaryDirectory() as d:
            final = os.path.join(d, "out.mp4")
            with self.assertRaises(ValueError):
                with ffmpeg_utils.atomic_output(final) as tmp:
                    with open(tmp, "w") as f:
                        f.write("partial")
                    raise ValueError("ffmpeg died")
            self.assertEqual(os.listdir(d), [])

    def test_existing_file_kept_on_failure(self):
        with tempfile.TemporaryDirectory() as d:
            final = os.path.join(d, "out.mp4")
            with open(final, "w") as f:
                f.write("good")
            with self.assertRaises(RuntimeError):
                with ffmpeg_utils.atomic_output(final):
                    pass  # produced nothing
            with open(final) as f:
                self.assertEqual(f.read(), "good")


class TestShortVideoPlan(unittest.TestCase):
    def _gen(self):
        return PreviewVideoGenerator("/fake/v.mp4", "/fake/o.mp4", "abc", preview_clips=15,
                                     clip_length=1, skip_seconds=15, include_audio=False)

    def test_normal_video(self):
        plan = self._gen().plan_clips(600)
        self.assertEqual(len(plan), 15)
        self.assertTrue(all(length == 1 for _, length in plan))

    def test_short_video_gets_single_clip(self):
        self.assertEqual(self._gen().plan_clips(8.0), [(0, 8.0)])

    def test_zero_duration_raises(self):
        with self.assertRaises(RuntimeError):
            self._gen().plan_clips(0)


if __name__ == '__main__':
    unittest.main()
