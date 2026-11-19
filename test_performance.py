"""
Automated CI/CD Performance & SLA Test Suite.
Run via: python3 -m unittest test_performance.py
"""

import os
import json
import unittest
from pathlib import Path

from performance.benchmark_engine import (
    BenchmarkEngine,
    calculate_percentile,
    determine_grade,
    DirectHandler,
)
from performance.config import SLA_THRESHOLDS, REPORTS_DIR
from performance.scenarios import (
    SCENARIO_REGISTRY,
    get_read_heavy_generator,
    get_heavy_reports_generator,
    get_write_mixed_generator,
)
from performance.db_benchmarks import DatabaseBenchmark, BENCHMARK_QUERIES
from performance.data_generator import SyntheticDataGenerator
from performance.system_monitor import SystemMonitor
from performance.reporter import PerformanceReporter


class TestStatisticalEngine(unittest.TestCase):
    def test_percentile_calculation(self):
        values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
        p50 = calculate_percentile(values, 50.0)
        p90 = calculate_percentile(values, 90.0)
        p95 = calculate_percentile(values, 95.0)

        self.assertAlmostEqual(p50, 55.0, places=1)
        self.assertAlmostEqual(p90, 91.0, places=1)
        self.assertAlmostEqual(p95, 95.5, places=1)

    def test_determine_grade(self):
        self.assertEqual(determine_grade(apdex=0.98, error_rate=0.0, p95=80.0), "A+ (Xuất sắc)")
        self.assertEqual(determine_grade(apdex=0.92, error_rate=0.0, p95=200.0), "A (Rất tốt)")
        self.assertEqual(determine_grade(apdex=0.85, error_rate=0.4, p95=280.0), "B (Tốt)")
        self.assertEqual(determine_grade(apdex=0.75, error_rate=1.5, p95=450.0), "C (Trung bình)")
        self.assertEqual(determine_grade(apdex=0.50, error_rate=10.0, p95=1200.0), "F (Kém)")


class TestDirectHandler(unittest.TestCase):
    def test_direct_handler_execution(self):
        handler = DirectHandler("/contracts")
        handler.do_GET()
        self.assertEqual(handler.response_status, 200)
        self.assertGreater(len(handler.wfile.getvalue()), 1000)
        self.assertIn(b"Contracts", handler.wfile.getvalue())


class TestScenarios(unittest.TestCase):
    def test_scenario_registry(self):
        self.assertIn("read_heavy", SCENARIO_REGISTRY)
        self.assertIn("heavy_reports", SCENARIO_REGISTRY)
        self.assertIn("write_mixed", SCENARIO_REGISTRY)

        gen_read = get_read_heavy_generator()
        target = gen_read()
        self.assertIn("path", target)
        self.assertEqual(target.get("method"), "GET")

        gen_write = get_write_mixed_generator()
        target_w = gen_write()
        self.assertIn("path", target_w)


class TestDatabaseBenchmark(unittest.TestCase):
    def test_sqlite_benchmarks(self):
        dbb = DatabaseBenchmark()
        results = dbb.run_all(iterations=5)
        self.assertEqual(results["total_queries_tested"], len(BENCHMARK_QUERIES))
        self.assertGreater(results["average_p95_ms"], 0.0)
        self.assertLess(results["average_p95_ms"], 100.0)


class TestDataGenerator(unittest.TestCase):
    def test_synthetic_data_generation(self):
        test_db = REPORTS_DIR / "test_temp_perf.sqlite3"
        gen = SyntheticDataGenerator(db_path=str(test_db))
        counts = gen.generate(scale="small", verbose=False)
        self.assertGreater(counts["vendors"], 10)
        self.assertGreater(counts["contracts"], 30)
        self.assertGreater(counts["staff"], 100)
        if test_db.exists():
            test_db.unlink()


class TestSystemMonitor(unittest.TestCase):
    def test_monitor_lifecycle(self):
        mon = SystemMonitor(interval_sec=0.2)
        mon.start()
        import time
        time.sleep(0.5)
        stats = mon.stop()
        self.assertGreater(stats["samples_count"], 0)
        self.assertGreater(stats["peak_rss_mb"], 0.0)


class TestPerformanceSLA(unittest.TestCase):
    def test_read_heavy_sla_compliance(self):
        """
        Automated SLA regression gate: read-heavy workload must strictly comply with SLA thresholds.
        """
        engine = BenchmarkEngine(transport="inprocess")
        sc = SCENARIO_REGISTRY["read_heavy"]
        res = engine.run_workload(
            scenario_name="CI Read-Heavy SLA Validation",
            target_generator=sc["generator_factory"](),
            concurrency=2,
            duration_sec=3.0
        )

        reporter = PerformanceReporter(result=res)
        json_path = reporter.export_json(filename="ci_test_report.json")
        html_path = reporter.export_html(filename="ci_test_report.html")

        self.assertTrue(json_path.exists())
        self.assertTrue(html_path.exists())

        # SLA Assertions
        self.assertEqual(res.failed_requests, 0, f"Errors encountered: {res.failed_requests}")
        self.assertLessEqual(res.error_rate_pct, SLA_THRESHOLDS["max_error_rate_pct"])
        self.assertLessEqual(res.latency_median_ms, SLA_THRESHOLDS["p50_latency_ms"])
        self.assertLessEqual(res.latency_p95_ms, SLA_THRESHOLDS["p95_latency_ms"])
        self.assertGreaterEqual(res.rps, SLA_THRESHOLDS["min_rps"])
        self.assertGreaterEqual(res.apdex_score, SLA_THRESHOLDS["min_apdex_score"])
        self.assertTrue(res.sla_compliance["p50_latency"])
        self.assertTrue(res.sla_compliance["p95_latency"])
        self.assertTrue(res.sla_compliance["error_rate"])


if __name__ == "__main__":
    unittest.main()
