"""
Tests for BatchStatistics.

Covers thread safety, division-by-zero guards, format correctness,
and behaviour when start_batch() has not been called.
"""

import sys
import os
import time
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers.statistics import BatchStatistics


class TestBatchStatisticsBasic(unittest.TestCase):
    def setUp(self):
        self.stats = BatchStatistics()

    def test_summary_before_start_batch(self):
        result = self.stats.get_summary()
        self.assertEqual(result, "No statistics available")

    def test_start_resets_counters(self):
        self.stats.start_batch(10)
        self.stats.record_success(1.0)
        self.stats.record_failure()
        self.stats.start_batch(5)
        summary = self.stats.get_summary()
        self.assertIn("0/5", summary)

    def test_all_success(self):
        self.stats.start_batch(3)
        self.stats.record_success(1.0)
        self.stats.record_success(2.0)
        self.stats.record_success(3.0)
        summary = self.stats.get_summary()
        self.assertIn("3/3", summary)
        self.assertIn("100.0%", summary)

    def test_all_failure(self):
        self.stats.start_batch(2)
        self.stats.record_failure()
        self.stats.record_failure()
        summary = self.stats.get_summary()
        self.assertIn("0/2", summary)
        self.assertIn("0.0%", summary)

    def test_mixed_results(self):
        self.stats.start_batch(4)
        self.stats.record_success(1.0)
        self.stats.record_success(2.0)
        self.stats.record_failure()
        self.stats.record_failure()
        summary = self.stats.get_summary()
        self.assertIn("2/4", summary)
        self.assertIn("50.0%", summary)

    def test_no_division_by_zero_zero_batch(self):
        self.stats.start_batch(0)
        summary = self.stats.get_summary()
        self.assertIn("0.0%", summary)

    def test_average_time_calculation(self):
        self.stats.start_batch(2)
        self.stats.record_success(4.0)
        self.stats.record_success(6.0)
        summary = self.stats.get_summary()
        self.assertIn("5.0s", summary)

    def test_no_times_recorded(self):
        self.stats.start_batch(2)
        self.stats.record_failure()
        self.stats.record_failure()
        summary = self.stats.get_summary()
        self.assertIn("0.0s", summary)

    def test_summary_contains_separator(self):
        self.stats.start_batch(1)
        summary = self.stats.get_summary()
        self.assertIn("=" * 60, summary)


class TestBatchStatisticsFormatDuration(unittest.TestCase):
    def setUp(self):
        self.stats = BatchStatistics()

    def test_seconds_format(self):
        self.assertEqual(self.stats._format_duration(45.3), "45.3s")

    def test_minutes_format(self):
        result = self.stats._format_duration(90)
        self.assertIn("1m", result)
        self.assertIn("30s", result)

    def test_hours_format(self):
        result = self.stats._format_duration(3661)
        self.assertIn("1h", result)
        self.assertIn("1m", result)

    def test_exactly_one_minute(self):
        result = self.stats._format_duration(60)
        self.assertIn("1m", result)
        self.assertIn("0s", result)


class TestBatchStatisticsThreadSafety(unittest.TestCase):
    def test_concurrent_record_success(self):
        stats = BatchStatistics()
        stats.start_batch(100)

        def worker():
            for _ in range(10):
                stats.record_success(0.1)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        summary = stats.get_summary()
        self.assertIn("100/100", summary)
        self.assertIn("100.0%", summary)

    def test_concurrent_mixed_records(self):
        stats = BatchStatistics()
        stats.start_batch(100)

        def success_worker():
            for _ in range(5):
                stats.record_success(1.0)

        def failure_worker():
            for _ in range(5):
                stats.record_failure()

        threads = (
            [threading.Thread(target=success_worker) for _ in range(10)] +
            [threading.Thread(target=failure_worker) for _ in range(10)]
        )
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        summary = stats.get_summary()
        self.assertIn("50/100", summary)
        self.assertIn("50.0%", summary)


if __name__ == '__main__':
    unittest.main()
