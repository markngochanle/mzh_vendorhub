#!/usr/bin/env python3
"""
CLI Runner for Mizuho Vendor Management System Performance Testing Suite.

Usage examples:
  python3 run_performance_tests.py --scenario read_heavy
  python3 run_performance_tests.py --profile smoke
  python3 run_performance_tests.py --concurrency 20 --duration 10
  python3 run_performance_tests.py --scenario all --db-bench
  python3 run_performance_tests.py --generate-data medium
  python3 run_performance_tests.py --fail-on-sla
"""

import sys
import argparse
from typing import List

from performance.config import TARGET_BASE_URL, PROFILES
from performance.benchmark_engine import BenchmarkEngine, BenchmarkResult
from performance.scenarios import SCENARIO_REGISTRY
from performance.system_monitor import SystemMonitor
from performance.db_benchmarks import DatabaseBenchmark
from performance.data_generator import SyntheticDataGenerator
from performance.reporter import PerformanceReporter


def parse_args():
    parser = argparse.ArgumentParser(description="Mizuho VMS Performance & Load Testing Suite")
    parser.add_argument(
        "--scenario",
        default="read_heavy",
        choices=list(SCENARIO_REGISTRY.keys()) + ["all"],
        help="Workload scenario to execute (default: read_heavy)"
    )
    parser.add_argument(
        "--profile",
        choices=list(PROFILES.keys()),
        help="Preset load profile (smoke, standard, heavy, stress, spike, soak)"
    )
    parser.add_argument(
        "-c", "--concurrency",
        type=int,
        help="Number of concurrent virtual users (overrides profile)"
    )
    parser.add_argument(
        "-d", "--duration",
        type=float,
        help="Duration of the benchmark run in seconds (overrides profile)"
    )
    parser.add_argument(
        "--target-url",
        default=TARGET_BASE_URL,
        help=f"Target base URL (default: {TARGET_BASE_URL})"
    )
    parser.add_argument(
        "--db-bench",
        action="store_true",
        help="Execute direct SQLite database query benchmarking & EXPLAIN QUERY PLAN"
    )
    parser.add_argument(
        "--generate-data",
        choices=["small", "medium", "large"],
        help="Generate synthetic enterprise database before benchmark run"
    )
    parser.add_argument(
        "--no-html",
        action="store_true",
        help="Disable HTML report export"
    )
    parser.add_argument(
        "--no-json",
        action="store_true",
        help="Disable JSON metrics export"
    )
    parser.add_argument(
        "--fail-on-sla",
        action="store_true",
        help="Exit with code 1 if any SLA requirement fails (for CI/CD gates)"
    )
    return parser.parse_args()


def run_single_scenario(
    scenario_key: str,
    concurrency: int,
    duration: float,
    target_url: str,
    export_html: bool = True,
    export_json: bool = True,
    db_bench_result = None
) -> BenchmarkResult:
    sc_meta = SCENARIO_REGISTRY[scenario_key]
    scenario_name = sc_meta["name"]
    generator = sc_meta["generator_factory"]()

    print(f"\n▶ Starting benchmark: {scenario_name}")
    print(f"  Target: {target_url} | Concurrency: {concurrency} | Duration: {duration}s")

    engine = BenchmarkEngine(base_url=target_url)
    monitor = SystemMonitor()
    monitor.start()

    def progress_callback(elapsed: float, total: float, pct: float):
        print(f"  [{pct:5.1f}%] Running... {elapsed:.1f}s / {total:.1f}s", end="\r", flush=True)

    result = engine.run_workload(
        scenario_name=scenario_name,
        target_generator=generator,
        concurrency=concurrency,
        duration_sec=duration,
        on_progress=progress_callback
    )

    sys_metrics = monitor.stop()
    print("  [100.0%] Benchmark completed! Analyzing metrics...       ")

    reporter = PerformanceReporter(
        result=result,
        db_bench_result=db_bench_result,
        sys_metrics=sys_metrics
    )

    reporter.print_console_summary()

    if export_json:
        json_path = reporter.export_json()
        print(f"  💾 JSON Metrics Exported: {json_path}")

    if export_html:
        html_path = reporter.export_html()
        print(f"  📊 HTML Visual Report Exported: {html_path}")

    return result


def main():
    args = parse_args()

    # Step 1: Optional Data Generation
    if args.generate_data:
        print(f"\n📦 Generating synthetic enterprise dataset (scale: {args.generate_data})...")
        generator = SyntheticDataGenerator()
        stats = generator.generate(scale=args.generate_data, verbose=True)

    # Step 2: Optional DB Benchmark
    db_bench_result = None
    if args.db_bench:
        print("\n🗄️ Executing direct SQLite query benchmarks & EXPLAIN QUERY PLAN analysis...")
        db_benchmark = DatabaseBenchmark()
        db_bench_result = db_benchmark.run_all(iterations=50)
        print(f"  Completed {db_bench_result['total_queries_tested']} query benchmarks.")
        print(f"  Average P95 Latency: {db_bench_result['average_p95_ms']} ms")
        print(f"  Full Table Scans Detected: {db_bench_result['full_table_scans_detected']}")

    # Step 3: Determine Scenarios to run
    if args.scenario == "all":
        scenarios_to_run = list(SCENARIO_REGISTRY.keys())
    else:
        scenarios_to_run = [args.scenario]

    sla_failures = 0
    all_results: List[BenchmarkResult] = []

    for sc_key in scenarios_to_run:
        sc_meta = SCENARIO_REGISTRY[sc_key]
        prof_name = args.profile or sc_meta.get("default_profile", "standard")
        profile = PROFILES.get(prof_name, PROFILES["standard"])

        concurrency = args.concurrency if args.concurrency is not None else profile["concurrency"]
        duration = args.duration if args.duration is not None else profile["duration_sec"]

        res = run_single_scenario(
            scenario_key=sc_key,
            concurrency=concurrency,
            duration=duration,
            target_url=args.target_url,
            export_html=not args.no_html,
            export_json=not args.no_json,
            db_bench_result=db_bench_result
        )
        all_results.append(res)

        if not all(res.sla_compliance.values()):
            sla_failures += 1

    if args.fail_on_sla and sla_failures > 0:
        print(f"\n❌ Failure: {sla_failures} scenario(s) failed SLA compliance check!")
        sys.exit(1)

    print("\n✨ All performance tests completed successfully.")
    sys.exit(0)


if __name__ == "__main__":
    main()
