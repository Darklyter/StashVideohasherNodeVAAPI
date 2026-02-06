# statistics.py

import time
import threading
from datetime import datetime

class BatchStatistics:
    """Thread-safe statistics tracker for batch processing"""

    def __init__(self):
        self.lock = threading.Lock()
        self.total_scenes = 0
        self.successful = 0
        self.failed = 0
        self.start_time = None
        self.scene_times = []

    def start_batch(self, total_scenes):
        """Initialize batch tracking"""
        with self.lock:
            self.total_scenes = total_scenes
            self.successful = 0
            self.failed = 0
            self.start_time = time.time()
            self.scene_times = []

    def record_success(self, elapsed_time=None):
        """Record successful scene processing"""
        with self.lock:
            self.successful += 1
            if elapsed_time:
                self.scene_times.append(elapsed_time)

    def record_failure(self):
        """Record failed scene processing"""
        with self.lock:
            self.failed += 1

    def get_summary(self):
        """Get formatted statistics summary"""
        with self.lock:
            if self.start_time is None:
                return "No statistics available"

            elapsed = time.time() - self.start_time
            total_processed = self.successful + self.failed
            success_rate = (self.successful / total_processed * 100) if total_processed > 0 else 0
            avg_time = sum(self.scene_times) / len(self.scene_times) if self.scene_times else 0

            lines = [
                "",
                "=" * 60,
                "📊 Batch Summary",
                "=" * 60,
                f"  ✅ Successful: {self.successful}/{self.total_scenes} ({success_rate:.1f}%)",
                f"  ❌ Failed: {self.failed}/{self.total_scenes}",
                f"  ⏱️  Average time per scene: {avg_time:.1f}s",
                f"  🎯 Total processing time: {self._format_duration(elapsed)}",
                "=" * 60,
                ""
            ]

            return "\n".join(lines)

    def _format_duration(self, seconds):
        """Format seconds into human-readable duration"""
        if seconds < 60:
            return f"{seconds:.1f}s"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}h {minutes}m"

# Global statistics instance
batch_stats = BatchStatistics()
