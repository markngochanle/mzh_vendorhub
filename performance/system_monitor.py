"""
Real-time System Resource Monitor (CPU, Memory RSS, Threads, DB Size).
Pure Python standard library implementation with zero external dependencies.
"""

import os
import sys
import time
import threading
import resource
from typing import Dict, Any, List, Optional
from pathlib import Path

from performance.config import MAIN_DB_PATH


class SystemMonitor:
    def __init__(self, db_path: Optional[str] = None, interval_sec: float = 0.5):
        self.db_path = str(db_path or MAIN_DB_PATH)
        self.interval_sec = interval_sec
        self.timeline: List[Dict[str, Any]] = []
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self.start_wall_time = 0.0
        self.start_cpu_time = 0.0
        self.start_rss_mb = 0.0
        self.start_db_bytes = 0

        self.end_wall_time = 0.0
        self.end_cpu_time = 0.0
        self.end_rss_mb = 0.0
        self.end_db_bytes = 0

        self.peak_rss_mb = 0.0
        self.peak_threads = 0

    def _get_current_rss_mb(self) -> float:
        try:
            r = resource.getrusage(resource.RUSAGE_SELF)
            if sys.platform == "darwin":
                # On macOS, ru_maxrss is in bytes
                return round(r.ru_maxrss / (1024.0 * 1024.0), 2)
            else:
                # On Linux, ru_maxrss is in kilobytes
                return round(r.ru_maxrss / 1024.0, 2)
        except Exception:
            return 0.0

    def _get_db_size_bytes(self) -> int:
        try:
            p = Path(self.db_path)
            return p.stat().st_size if p.exists() else 0
        except Exception:
            return 0

    def _get_process_cpu_seconds(self) -> float:
        try:
            t = os.times()
            return t.user + t.system
        except Exception:
            return time.process_time()

    def _monitor_loop(self):
        last_wall = self.start_wall_time
        last_cpu = self.start_cpu_time

        while not self._stop_event.is_set():
            time.sleep(self.interval_sec)
            now_wall = time.time()
            now_cpu = self._get_process_cpu_seconds()
            rss_mb = self._get_current_rss_mb()
            active_threads = threading.active_count()
            db_size_kb = round(self._get_db_size_bytes() / 1024.0, 1)

            # Calculate windowed CPU %
            elapsed_wall = now_wall - last_wall
            elapsed_cpu = now_cpu - last_cpu
            cpu_pct = round((elapsed_cpu / elapsed_wall) * 100.0, 1) if elapsed_wall > 0 else 0.0

            last_wall = now_wall
            last_cpu = now_cpu

            if rss_mb > self.peak_rss_mb:
                self.peak_rss_mb = rss_mb
            if active_threads > self.peak_threads:
                self.peak_threads = active_threads

            self.timeline.append({
                "elapsed_sec": round(now_wall - self.start_wall_time, 1),
                "rss_mb": rss_mb,
                "cpu_pct": cpu_pct,
                "active_threads": active_threads,
                "db_size_kb": db_size_kb
            })

    def start(self):
        self.timeline.clear()
        self._stop_event.clear()
        self.start_wall_time = time.time()
        self.start_cpu_time = self._get_process_cpu_seconds()
        self.start_rss_mb = self._get_current_rss_mb()
        self.peak_rss_mb = self.start_rss_mb
        self.start_db_bytes = self._get_db_size_bytes()
        self.peak_threads = threading.active_count()

        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop(self) -> Dict[str, Any]:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        self.end_wall_time = time.time()
        self.end_cpu_time = self._get_process_cpu_seconds()
        self.end_rss_mb = self._get_current_rss_mb()
        self.end_db_bytes = self._get_db_size_bytes()

        if self.end_rss_mb > self.peak_rss_mb:
            self.peak_rss_mb = self.end_rss_mb

        total_wall = self.end_wall_time - self.start_wall_time
        total_cpu = self.end_cpu_time - self.start_cpu_time
        avg_cpu_pct = round((total_cpu / total_wall) * 100.0, 1) if total_wall > 0 else 0.0
        delta_rss_mb = round(self.end_rss_mb - self.start_rss_mb, 2)
        delta_db_kb = round((self.end_db_bytes - self.start_db_bytes) / 1024.0, 1)

        return {
            "duration_sec": round(total_wall, 2),
            "start_rss_mb": self.start_rss_mb,
            "end_rss_mb": self.end_rss_mb,
            "peak_rss_mb": self.peak_rss_mb,
            "delta_rss_mb": delta_rss_mb,
            "average_cpu_pct": avg_cpu_pct,
            "peak_threads": self.peak_threads,
            "start_db_kb": round(self.start_db_bytes / 1024.0, 1),
            "end_db_kb": round(self.end_db_bytes / 1024.0, 1),
            "delta_db_kb": delta_db_kb,
            "samples_count": len(self.timeline),
            "timeline": self.timeline
        }
