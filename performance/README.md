# Mizuho Vendor Management System - Enterprise Performance Testing Suite

A comprehensive, zero-dependency, production-grade load and performance testing framework designed for the Mizuho Vendor Management System (`performance_test` branch).

---

## 🌟 Key Features

1. **Multi-Threaded Benchmark Engine (`performance/benchmark_engine.py`)**
   - High-precision nanosecond timings (`time.perf_counter_ns`).
   - Detailed statistical analysis: Throughput (RPS), Latencies (Min, Mean, Median, P90, P95, P99, Max, StdDev).
   - Industry-standard **Apdex Score** calculation ($T = 100\text{ ms}$, $4T = 400\text{ ms}$).
   - Automated Performance Letter Grading (**A+**, **A**, **B**, **C**, **F**).
   - Dual-transport support: Real network HTTP sockets (`transport="http"`) and high-speed in-process handler invocation (`transport="inprocess"`).

2. **Realistic Enterprise Workloads (`performance/scenarios.py`)**
   - `read_heavy`: Standard browsing across contracts, annexes, staff, leaves, invoices, and dashboards.
   - `heavy_reports`: High-demand analytics queries (FY cash-out matrix, staff leaves aggregation, attendance punctuality).
   - `write_mixed`: Realistic operational traffic with 85% reads and 15% state updates/AJAX.
   - `stress_burst`: High concurrency saturation to identify queue bottlenecks.
   - `soak_endurance`: Extended duration load to evaluate memory leak and latency drift.

3. **Direct SQLite Query Benchmarking (`performance/db_benchmarks.py`)**
   - Benchmarks 8 core system queries (active contracts, annexes, staff allocations, leave carryover, monthly attendance, invoices aggregation, and milestones).
   - Automated `EXPLAIN QUERY PLAN` analyzer detecting unindexed full table scans (`SCAN TABLE ...` vs `SEARCH TABLE ... USING INDEX`).

4. **Synthetic Enterprise Dataset Generator (`performance/data_generator.py`)**
   - Generates production-scale datasets (`small`, `medium`, `large`) with realistic Vietnamese & Japanese enterprise names, contracts, annexes, staff links, attendance summaries, and invoices in seconds.

5. **Real-Time Resource Monitoring (`performance/system_monitor.py`)**
   - Samples process Memory RSS (MB), CPU %, active thread count, and SQLite DB size growth over time.

6. **Interactive Visual HTML & JSON Reports (`performance/reporter.py`)**
   - Responsive HTML reports with Chart.js charts:
     - Throughput & Latency Timeline curve.
     - Endpoint P95 Latency comparison bars.
     - CPU & Memory RSS consumption timeline.
     - SLA compliance verification scorecard.
     - Query plan optimization table.
   - Automated JSON metrics export for metrics ingestion.

7. **Web Runner Dashboard (`performance_runner.py` at `/performance-tests`)**
   - Direct web-based runner integrated into the application's **System & Tools** navigation menu.
   - Live streaming terminal log viewer with real-time polling.
   - Quick links to open generated HTML reports directly in the browser.

8. **Automated CI/CD Quality Gate (`test_performance.py`)**
   - Automated SLA regression test suite executable in GitHub Actions / CI pipelines.

---

## 🎯 SLA Thresholds (Service Level Agreements)

| Metric | Target SLA | Description |
| :--- | :--- | :--- |
| **Median Latency (P50)** | $\le 60\text{ ms}$ | 50% of requests must complete under 60ms |
| **95th Percentile (P95)** | $\le 250\text{ ms}$ | 95% of requests must complete under 250ms |
| **99th Percentile (P99)** | $\le 600\text{ ms}$ | 99% of requests must complete under 600ms |
| **Error Rate** | $\le 0.5\%$ | Maximum acceptable failed request rate |
| **Throughput (RPS)** | $\ge 35\text{ req/s}$ | Minimum required requests per second |
| **Apdex Score** | $\ge 0.90$ | Application Performance Index (0.90+ is Good / Excellent) |

---

## 🚀 Usage Guide

### 1. Command-Line Interface (CLI)

Run standard smoke benchmark:
```bash
python3 run_performance_tests.py --scenario read_heavy --profile smoke
```

Run with custom concurrency and duration:
```bash
python3 run_performance_tests.py --scenario heavy_reports --concurrency 20 --duration 15
```

Run all scenarios with direct SQLite query benchmarking:
```bash
python3 run_performance_tests.py --scenario all --db-bench
```

Generate synthetic enterprise database before test:
```bash
python3 run_performance_tests.py --generate-data medium
```

Fail with non-zero exit code on SLA violation (for CI/CD gates):
```bash
python3 run_performance_tests.py --scenario read_heavy --fail-on-sla
```

### 2. Web UI Dashboard

1. Start server:
   ```bash
   python3 server.py
   ```
2. Navigate to: `http://127.0.0.1:8800/performance-tests` (or via **System & Tools** &rarr; **⚡ Performance Suite**).
3. Select your desired profile (Smoke, Standard, Heavy, Stress) and click **Run**.
4. View live execution logs in the terminal console and click **Open Report** to inspect the Chart.js visual charts.

### 3. Automated CI/CD Regression Suite

Run unit and SLA validation suite:
```bash
python3 -m unittest test_performance.py
```

Run application unit test suite:
```bash
python3 test_app.py
```
