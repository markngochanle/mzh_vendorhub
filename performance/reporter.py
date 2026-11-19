"""
Performance Test Reporting Engine.
Produces visual HTML reports with Chart.js charts, JSON metrics exports, and ANSI console summaries.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from performance.config import REPORTS_DIR, SLA_THRESHOLDS
from performance.benchmark_engine import BenchmarkResult


class PerformanceReporter:
    def __init__(self, result: BenchmarkResult, db_bench_result: Optional[Dict[str, Any]] = None, sys_metrics: Optional[Dict[str, Any]] = None):
        self.result = result
        self.db_bench = db_bench_result
        self.sys_metrics = sys_metrics
        self.timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.readable_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def export_json(self, filename: Optional[str] = None) -> Path:
        if not filename:
            filename = f"perf_report_{self.timestamp_str}.json"
        target_path = REPORTS_DIR / filename

        recommendations = self.generate_recommendations()

        report_data = {
            "meta": {
                "generated_at": self.readable_timestamp,
                "scenario": self.result.scenario_name,
                "concurrency": self.result.concurrency,
                "duration_sec": self.result.duration_sec,
                "grade": self.result.performance_grade,
            },
            "sla_thresholds": SLA_THRESHOLDS,
            "sla_compliance": self.result.sla_compliance,
            "metrics": {
                "total_requests": self.result.total_requests,
                "successful_requests": self.result.successful_requests,
                "failed_requests": self.result.failed_requests,
                "error_rate_pct": self.result.error_rate_pct,
                "rps": self.result.rps,
                "throughput_kb_s": self.result.throughput_kb_s,
                "total_bytes_kb": self.result.total_bytes_kb,
                "apdex_score": self.result.apdex_score,
                "latency_min_ms": self.result.latency_min_ms,
                "latency_mean_ms": self.result.latency_mean_ms,
                "latency_median_ms": self.result.latency_median_ms,
                "latency_p90_ms": self.result.latency_p90_ms,
                "latency_p95_ms": self.result.latency_p95_ms,
                "latency_p99_ms": self.result.latency_p99_ms,
                "latency_max_ms": self.result.latency_max_ms,
                "latency_stddev_ms": self.result.latency_stddev_ms,
            },
            "status_codes": self.result.status_codes,
            "endpoint_breakdown": self.result.endpoint_breakdown,
            "timeline": self.result.timeline_series,
            "recommendations": recommendations,
            "database_benchmark": self.db_bench,
            "system_resources": self.sys_metrics,
        }

        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)

        return target_path

    def generate_recommendations(self) -> List[Dict[str, Any]]:
        """
        Analyzes performance metrics and generates prioritized system optimization recommendations.
        """
        recs = []
        r = self.result

        # 1. Invoice List Pagination (if '/' has high latency)
        root_ep = r.endpoint_breakdown.get("/", {})
        if root_ep.get("p95_ms", 0) > 300 or root_ep.get("median_ms", 0) > 200:
            recs.append({
                "priority": "HIGH",
                "tag": "Database & Pagination",
                "title": "Implement Server-Side Pagination for Invoices List ('/')",
                "observation": f"The root invoices list endpoint '/' exhibited a high P95 latency of {root_ep.get('p95_ms', 0):.1f}ms (Median: {root_ep.get('median_ms', 0):.1f}ms).",
                "root_cause": "The page queries, reconciles, and renders all invoice records in a single database query without SQL LIMIT/OFFSET pagination, creating heavy serialization and CPU overhead.",
                "solution": "Add pagination to page_invoices_list(filters, page=1, page_size=50). Fetch only 50 rows per view: SELECT * FROM invoices WHERE ... ORDER BY id DESC LIMIT 50 OFFSET (page-1)*50.",
                "impact": "Estimated 80% - 90% latency reduction on the main invoice dashboard."
            })

        # 2. Dashboard In-Memory Caching (if '/dashboard' is slow)
        dash_ep = r.endpoint_breakdown.get("/dashboard", {})
        dash_fy_ep = r.endpoint_breakdown.get("/dashboard?fy=2026", {})
        max_dash_p95 = max(dash_ep.get("p95_ms", 0), dash_fy_ep.get("p95_ms", 0))
        if max_dash_p95 > 250:
            recs.append({
                "priority": "HIGH",
                "tag": "In-Memory Caching",
                "title": "Add In-Memory Caching (LRU/TTL) for Executive Dashboard Calculations",
                "observation": f"Dashboard calculations recorded a P95 latency of {max_dash_p95:.1f}ms under concurrent load.",
                "root_cause": "Annual cash-out matrix, vendor commitments, and FY totals iterate and aggregate across all framework contracts and annexes repeatedly on every single GET request, even when underlying data has not changed.",
                "solution": "Wrap page_dashboard() calculations with a simple in-memory 60-second TTL cache (or functools.lru_cache with periodic invalidation on write events).",
                "impact": "Reduces repeated dashboard load latency from seconds to < 5ms (over 95% throughput boost)."
            })

        # 3. Staff Leaves & Attendance N+1 Query Optimization
        staff_ep = r.endpoint_breakdown.get("/staff", {})
        punct_ep = r.endpoint_breakdown.get("/attendance/punctuality", {})
        if staff_ep.get("p95_ms", 0) > 250 or punct_ep.get("p95_ms", 0) > 300:
            recs.append({
                "priority": "MEDIUM",
                "tag": "Query Optimization",
                "title": "Optimize Staff Leave Balance & Attendance Aggregation Queries",
                "observation": f"Staff management ('/staff') and attendance punctuality endpoints recorded P95 latencies up to {max(staff_ep.get('p95_ms', 0), punct_ep.get('p95_ms', 0)):.1f}ms.",
                "root_cause": "Calculating remaining leave balance and carryover across multiple annexes performs nested iterative lookups across contract_staff_links and monthly_attendance_summary.",
                "solution": "Use pre-aggregated JOIN queries and ensure composite index coverage: CREATE INDEX IF NOT EXISTS idx_mas_staff_month ON monthly_attendance_summary(staff_id, month); and CREATE INDEX IF NOT EXISTS idx_csl_staff ON contract_staff_links(staff_id, contract_id).",
                "impact": "Eliminates N+1 query loops and ensures sub-50ms response times for HR and payroll views."
            })

        # 4. Multi-Worker WSGI/ASGI Production Deployment (if Concurrency > 20)
        if r.concurrency >= 20:
            recs.append({
                "priority": "ARCHITECTURE",
                "tag": "Web Server Scalability",
                "title": "Deploy with Multi-Worker Production Server (Gunicorn / Waitress)",
                "observation": f"During high concurrency ({r.concurrency} concurrent virtual users), request queuing occurred as median latency increased to {r.latency_median_ms:.1f}ms.",
                "root_cause": "The development server (http.server.BaseHTTPRequestHandler) runs in a single Python process, meaning incoming concurrent connections queue behind active CPU-bound template rendering.",
                "solution": "In production or high-traffic environments, deploy the app behind a multi-process WSGI server (e.g. gunicorn -w 4 -b 0.0.0.0:8800 server:app or Waitress) with an Nginx reverse proxy.",
                "impact": "Enables multi-core CPU parallel execution and sustains 200+ concurrent users with zero request queuing."
            })

        # 5. SQLite WAL Mode & Concurrency Tuning (Quick Win)
        recs.append({
            "priority": "QUICK WIN",
            "tag": "SQLite Engine Tuning",
            "title": "Enable SQLite WAL Mode (Write-Ahead Logging) & Optimize Cache Size",
            "observation": "Concurrent read and write operations on SQLite can experience table lock wait times when multiple transactions execute simultaneously.",
            "root_cause": "Default SQLite rollback journal locks the entire database file during writes, momentarily blocking concurrent readers.",
            "solution": "Execute PRAGMA journal_mode = WAL; and PRAGMA synchronous = NORMAL; and PRAGMA cache_size = -64000; (64MB memory cache) inside db_connect() in common.py.",
            "impact": "Allows simultaneous readers while a write transaction is executing, preventing database lock contention entirely."
        })

        # 6. Static Asset Caching & HTTP Compression
        recs.append({
            "priority": "QUICK WIN",
            "tag": "HTTP Compression & Caching",
            "title": "Enable HTTP Gzip Compression & Long-Lived Static Cache Headers",
            "observation": f"Total payload transferred during benchmark was {r.total_bytes_kb:,.1f} KB ({r.throughput_kb_s:,.1f} KB/s).",
            "root_cause": "Large static assets like chart.umd.min.js (210 KB) and uncompressed HTML tables are served in raw text without gzip/brotli transfer-encoding.",
            "solution": "Add gzip Content-Encoding for text/html, application/javascript, and text/css responses exceeding 1KB, and set Cache-Control: public, max-age=604800 for /static/ assets.",
            "impact": "Reduces network bandwidth consumption by 70% and accelerates page load times for client browsers."
        })

        return recs

    def export_html(self, filename: Optional[str] = None) -> Path:
        if not filename:
            filename = f"perf_report_{self.timestamp_str}.html"
        target_path = REPORTS_DIR / filename

        r = self.result
        all_passed = all(r.sla_compliance.values()) if r.sla_compliance else False

        # Endpoint data for Chart.js
        ep_labels = list(r.endpoint_breakdown.keys())
        ep_p95 = [r.endpoint_breakdown[k]["p95_ms"] for k in ep_labels]
        ep_rps = [r.endpoint_breakdown[k]["rps"] for k in ep_labels]

        # Timeline data for Chart.js
        time_labels = [f"{t['second']}s" for t in r.timeline_series]
        time_rps = [t["requests"] for t in r.timeline_series]
        time_p95 = [t["p95_ms"] for t in r.timeline_series]

        # System resource timeline
        sys_time_labels = []
        sys_cpu = []
        sys_rss = []
        if self.sys_metrics and self.sys_metrics.get("timeline"):
            for sm in self.sys_metrics["timeline"]:
                sys_time_labels.append(f"{sm['elapsed_sec']}s")
                sys_cpu.append(sm["cpu_pct"])
                sys_rss.append(sm["rss_mb"])

        # SLA Badges helper
        def sla_badge(passed: bool) -> str:
            if passed:
                return "<span class='badge pass'>PASS</span>"
            return "<span class='badge fail'>FAIL</span>"

        # Recommendations HTML
        recommendations = self.generate_recommendations()
        recs_cards_html = ""
        for rec in recommendations:
            if rec["priority"] == "HIGH":
                p_bg = "#fee2e2"
                p_color = "#dc2626"
            elif rec["priority"] == "MEDIUM":
                p_bg = "#fef9c3"
                p_color = "#ca8a04"
            elif rec["priority"] == "ARCHITECTURE":
                p_bg = "#dbeafe"
                p_color = "#2563eb"
            else:  # QUICK WIN
                p_bg = "#dcfce7"
                p_color = "#16a34a"

            recs_cards_html += f"""
            <div style="background: #ffffff; border: 1px solid var(--border); border-left: 5px solid {p_color}; border-radius: 8px; padding: 18px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.03);">
              <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px; flex-wrap: wrap; gap: 8px;">
                <div style="font-size: 16px; font-weight: 700; color: var(--text-main);">
                  {rec['title']}
                </div>
                <div style="display: flex; gap: 6px;">
                  <span class="badge" style="background: {p_bg}; color: {p_color}; font-weight: 800; font-size: 11px; padding: 4px 8px; border-radius: 4px;">{rec['priority']}</span>
                  <span class="badge" style="background: #f1f5f9; color: var(--text-muted); font-size: 11px; padding: 4px 8px; border-radius: 4px;">{rec['tag']}</span>
                </div>
              </div>
              
              <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px; font-size: 13px;">
                <div style="background: #f8fafc; padding: 12px; border-radius: 6px; border: 1px solid #f1f5f9;">
                  <strong style="color: var(--primary); display: block; margin-bottom: 4px;">🔍 Observed Finding:</strong>
                  <span style="color: var(--text-secondary);">{rec['observation']}</span>
                </div>
                <div style="background: #f8fafc; padding: 12px; border-radius: 6px; border: 1px solid #f1f5f9;">
                  <strong style="color: #ca8a04; display: block; margin-bottom: 4px;">⚙️ Root Cause:</strong>
                  <span style="color: var(--text-secondary);">{rec['root_cause']}</span>
                </div>
              </div>

              <div style="margin-top: 12px; background: #f0fdf4; border: 1px solid #bbf7d0; padding: 12px; border-radius: 6px; font-size: 13px;">
                <strong style="color: #166534; display: block; margin-bottom: 4px;">🛠️ Recommended Solution & Action:</strong>
                <span style="color: #14532d; line-height: 1.5;">{rec['solution']}</span>
                <div style="margin-top: 6px; font-size: 12px; color: #15803d; font-weight: 700;">
                  🚀 Expected Impact: {rec['impact']}
                </div>
              </div>
            </div>
            """

        # Endpoints table HTML
        ep_rows_html = ""
        for ep, data in r.endpoint_breakdown.items():
            err_class = "danger" if data["errors"] > 0 else "neutral"
            ep_rows_html += f"""
            <tr>
              <td><code>{ep}</code></td>
              <td class="text-right">{data['count']}</td>
              <td class="text-right {err_class}">{data['errors']} ({data['error_rate_pct']}%)</td>
              <td class="text-right">{data['rps']}</td>
              <td class="text-right">{data['min_ms']} ms</td>
              <td class="text-right">{data['median_ms']} ms</td>
              <td class="text-right font-bold">{data['p95_ms']} ms</td>
              <td class="text-right">{data['max_ms']} ms</td>
            </tr>
            """

        # DB Benchmarks HTML (if available)
        db_section_html = ""
        if self.db_bench and self.db_bench.get("queries"):
            db_rows_html = ""
            for q in self.db_bench["queries"]:
                scan_badge = "<span class='badge warn'>FULL SCAN</span>" if q.get("has_full_table_scan") else "<span class='badge pass'>INDEXED</span>"
                health_color = "pass" if q.get("health") in ("EXCELLENT", "GOOD") else "warn"
                db_rows_html += f"""
                <tr>
                  <td><strong>{q['id']}</strong><br><small class="text-muted">{q['name']}</small></td>
                  <td class="text-right">{q.get('rows_returned', 0)}</td>
                  <td class="text-right">{q.get('iterations', 0)}</td>
                  <td class="text-right font-bold">{q.get('p95_ms', 0)} ms</td>
                  <td class="text-center">{scan_badge}</td>
                  <td class="text-center"><span class="badge {health_color}">{q.get('health', 'UNKNOWN')}</span></td>
                </tr>
                """
            db_section_html = f"""
            <div class="card mt-4">
              <h2>🗄️ Database Query Benchmarking & Query Plan Analysis</h2>
              <p class="text-muted">Direct SQLite query execution times (50 iterations) with index coverage validation.</p>
              <div class="table-container">
                <table>
                  <thead>
                    <tr>
                      <th>Query Name</th>
                      <th class="text-right">Rows</th>
                      <th class="text-right">Runs</th>
                      <th class="text-right">P95 Latency</th>
                      <th class="text-center">Query Plan</th>
                      <th class="text-center">Health</th>
                    </tr>
                  </thead>
                  <tbody>
                    {db_rows_html}
                  </tbody>
                </table>
              </div>
            </div>
            """

        html_content = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Performance Benchmark Report - Mizuho VMS</title>
  <script src="/static/js/chart.umd.min.js"></script>
  <style>
    :root {{
      --primary: #183181;
      --primary-light: #2a49ad;
      --success: #16a34a;
      --warning: #ca8a04;
      --danger: #dc2626;
      --bg-page: #f8fafc;
      --bg-card: #ffffff;
      --text-main: #0f172a;
      --text-muted: #64748b;
      --border: #e2e8f0;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: var(--bg-page);
      color: var(--text-main);
      padding: 30px 20px;
      line-height: 1.5;
    }}
    .container {{
      max-width: 1200px;
      margin: 0 auto;
    }}
    .header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 25px;
      padding-bottom: 15px;
      border-bottom: 2px solid var(--border);
    }}
    .title-group h1 {{
      font-size: 26px;
      font-weight: 800;
      color: var(--primary);
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .title-group .meta {{
      color: var(--text-muted);
      font-size: 14px;
      margin-top: 4px;
    }}
    .grade-badge {{
      background: { "#16a34a" if "A" in r.performance_grade else ("#ca8a04" if "B" in r.performance_grade or "C" in r.performance_grade else "#dc2626") };
      color: white;
      font-size: 22px;
      font-weight: 800;
      padding: 10px 22px;
      border-radius: 8px;
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
      text-align: center;
    }}
    .grid-4 {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
      gap: 18px;
      margin-bottom: 25px;
    }}
    .card {{
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 20px;
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
    }}
    .card h2 {{
      font-size: 18px;
      font-weight: 700;
      margin-bottom: 12px;
      color: var(--primary);
    }}
    .kpi-card {{
      display: flex;
      flex-direction: column;
    }}
    .kpi-title {{
      font-size: 13px;
      text-transform: uppercase;
      font-weight: 600;
      color: var(--text-muted);
      letter-spacing: 0.5px;
    }}
    .kpi-value {{
      font-size: 30px;
      font-weight: 800;
      margin: 8px 0 4px 0;
      color: var(--text-main);
    }}
    .kpi-sub {{
      font-size: 12px;
      color: var(--text-muted);
    }}
    .charts-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
      gap: 20px;
      margin-bottom: 25px;
    }}
    .chart-box {{
      position: relative;
      height: 280px;
      width: 100%;
    }}
    .badge {{
      display: inline-block;
      padding: 3px 8px;
      font-size: 11px;
      font-weight: 700;
      border-radius: 4px;
      letter-spacing: 0.5px;
    }}
    .badge.pass {{ background: #dcfce7; color: #166534; }}
    .badge.fail {{ background: #fee2e2; color: #991b1b; }}
    .badge.warn {{ background: #fef9c3; color: #854d0e; }}
    .table-container {{
      overflow-x: auto;
      margin-top: 10px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    th, td {{
      padding: 10px 14px;
      border-bottom: 1px solid var(--border);
    }}
    th {{
      background: #f1f5f9;
      font-weight: 700;
      color: var(--text-main);
      text-align: left;
    }}
    .text-right {{ text-align: right; }}
    .text-center {{ text-align: center; }}
    .font-bold {{ font-weight: 700; }}
    .mt-4 {{ margin-top: 25px; }}
    .sla-table td {{ padding: 8px 14px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div class="title-group">
        <h1>⚡ Mizuho Performance Benchmark Report</h1>
        <div class="meta">
          <strong>Scenario:</strong> {r.scenario_name} | 
          <strong>Concurrency:</strong> {r.concurrency} users | 
          <strong>Duration:</strong> {r.duration_sec}s | 
          <strong>Executed At:</strong> {self.readable_timestamp}
        </div>
      </div>
      <div class="grade-badge">
        Grade: {r.performance_grade}
      </div>
    </div>

    <!-- Executive KPI Cards -->
    <div class="grid-4">
      <div class="card kpi-card">
        <span class="kpi-title">Total Requests</span>
        <span class="kpi-value">{r.total_requests:,}</span>
        <span class="kpi-sub">Success: {r.successful_requests:,} | Failed: {r.failed_requests}</span>
      </div>
      <div class="card kpi-card">
        <span class="kpi-title">Throughput (RPS)</span>
        <span class="kpi-value">{r.rps:,.1f}</span>
        <span class="kpi-sub">Bandwidth: {r.throughput_kb_s:,.1f} KB/s</span>
      </div>
      <div class="card kpi-card">
        <span class="kpi-title">Latency P95 (95th%)</span>
        <span class="kpi-value">{r.latency_p95_ms:.1f} <span style="font-size: 16px; font-weight: 500;">ms</span></span>
        <span class="kpi-sub">Median: {r.latency_median_ms:.1f}ms | P99: {r.latency_p99_ms:.1f}ms</span>
      </div>
      <div class="card kpi-card">
        <span class="kpi-title">Apdex Score (T=100ms)</span>
        <span class="kpi-value">{r.apdex_score:.3f}</span>
        <span class="kpi-sub">Error Rate: {r.error_rate_pct:.2f}%</span>
      </div>
    </div>

    <!-- SLA Verification Table -->
    <div class="card mb-4">
      <h2>🎯 Service Level Agreement (SLA) Compliance</h2>
      <div class="table-container">
        <table class="sla-table">
          <thead>
            <tr>
              <th>Metric Requirement</th>
              <th>Target Threshold</th>
              <th>Observed Result</th>
              <th class="text-center">Status</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Median Latency (P50)</td>
              <td>&le; {SLA_THRESHOLDS['p50_latency_ms']} ms</td>
              <td><strong>{r.latency_median_ms:.1f} ms</strong></td>
              <td class="text-center">{sla_badge(r.sla_compliance.get('p50_latency', False))}</td>
            </tr>
            <tr>
              <td>95th Percentile Latency (P95)</td>
              <td>&le; {SLA_THRESHOLDS['p95_latency_ms']} ms</td>
              <td><strong>{r.latency_p95_ms:.1f} ms</strong></td>
              <td class="text-center">{sla_badge(r.sla_compliance.get('p95_latency', False))}</td>
            </tr>
            <tr>
              <td>99th Percentile Latency (P99)</td>
              <td>&le; {SLA_THRESHOLDS['p99_latency_ms']} ms</td>
              <td><strong>{r.latency_p99_ms:.1f} ms</strong></td>
              <td class="text-center">{sla_badge(r.sla_compliance.get('p99_latency', False))}</td>
            </tr>
            <tr>
              <td>Maximum Error Rate</td>
              <td>&le; {SLA_THRESHOLDS['max_error_rate_pct']}%</td>
              <td><strong>{r.error_rate_pct:.2f}%</strong></td>
              <td class="text-center">{sla_badge(r.sla_compliance.get('error_rate', False))}</td>
            </tr>
            <tr>
              <td>Minimum Throughput (RPS)</td>
              <td>&ge; {SLA_THRESHOLDS['min_rps']} req/s</td>
              <td><strong>{r.rps:.1f} req/s</strong></td>
              <td class="text-center">{sla_badge(r.sla_compliance.get('min_rps', False))}</td>
            </tr>
            <tr>
              <td>Application Performance Index (Apdex)</td>
              <td>&ge; {SLA_THRESHOLDS['min_apdex_score']}</td>
              <td><strong>{r.apdex_score:.3f}</strong></td>
              <td class="text-center">{sla_badge(r.sla_compliance.get('apdex_score', False))}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Charts Section -->
    <div class="charts-grid mt-4">
      <div class="card">
        <h2>📈 Throughput & Latency Timeline</h2>
        <div class="chart-box">
          <canvas id="timelineChart"></canvas>
        </div>
      </div>
      <div class="card">
        <h2>⏱️ Endpoint P95 Latency (ms)</h2>
        <div class="chart-box">
          <canvas id="endpointChart"></canvas>
        </div>
      </div>
    </div>

    { f'''
    <!-- System Resources Chart -->
    <div class="card mt-4">
      <h2>🖥️ System Resource Consumption (CPU & Memory RSS)</h2>
      <div class="chart-box">
        <canvas id="sysChart"></canvas>
      </div>
    </div>
    ''' if sys_time_labels else '' }

    <!-- System Optimization Recommendations Section -->
    <div class="card mt-4">
      <h2>💡 System Optimization & Architecture Recommendations</h2>
      <p class="text-muted" style="margin-bottom: 18px;">
        Prioritized, actionable engineering recommendations automatically derived from observed benchmark metrics and latency bottlenecks.
      </p>
      {recs_cards_html}
    </div>

    <!-- Detailed Endpoint Breakdown Table -->
    <div class="card mt-4">
      <h2>🌐 Endpoint Latency & Error Breakdown</h2>
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>Endpoint</th>
              <th class="text-right">Requests</th>
              <th class="text-right">Errors</th>
              <th class="text-right">RPS</th>
              <th class="text-right">Min</th>
              <th class="text-right">Median</th>
              <th class="text-right">P95</th>
              <th class="text-right">Max</th>
            </tr>
          </thead>
          <tbody>
            {ep_rows_html}
          </tbody>
        </table>
      </div>
    </div>

    <!-- Database Section (if available) -->
    {db_section_html}

  </div>

  <script>
    // 1. Timeline Chart
    const ctxTimeline = document.getElementById('timelineChart').getContext('2d');
    new Chart(ctxTimeline, {{
      type: 'line',
      data: {{
        labels: {json.dumps(time_labels)},
        datasets: [
          {{
            label: 'Requests/sec',
            data: {json.dumps(time_rps)},
            borderColor: '#183181',
            backgroundColor: 'rgba(24, 49, 129, 0.1)',
            yAxisID: 'yRps',
            tension: 0.3,
            fill: true
          }},
          {{
            label: 'P95 Latency (ms)',
            data: {json.dumps(time_p95)},
            borderColor: '#ed1a3a',
            backgroundColor: 'transparent',
            borderDash: [5, 5],
            yAxisID: 'yLat',
            tension: 0.3
          }}
        ]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        scales: {{
          yRps: {{
            type: 'linear',
            position: 'left',
            title: {{ display: true, text: 'Req / sec' }}
          }},
          yLat: {{
            type: 'linear',
            position: 'right',
            grid: {{ drawOnChartArea: false }},
            title: {{ display: true, text: 'Latency (ms)' }}
          }}
        }}
      }}
    }});

    // 2. Endpoint Breakdown Chart
    const ctxEndpoint = document.getElementById('endpointChart').getContext('2d');
    new Chart(ctxEndpoint, {{
      type: 'bar',
      data: {{
        labels: {json.dumps(ep_labels)},
        datasets: [{{
          label: 'P95 Latency (ms)',
          data: {json.dumps(ep_p95)},
          backgroundColor: '#3b82f6',
          borderRadius: 4
        }}]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        indexAxis: 'y',
        scales: {{
          x: {{ title: {{ display: true, text: 'Latency P95 (ms)' }} }}
        }}
      }}
    }});

    { f'''
    // 3. System Monitor Chart
    const ctxSys = document.getElementById('sysChart').getContext('2d');
    new Chart(ctxSys, {{
      type: 'line',
      data: {{
        labels: {json.dumps(sys_time_labels)},
        datasets: [
          {{
            label: 'CPU Usage (%)',
            data: {json.dumps(sys_cpu)},
            borderColor: '#f59e0b',
            backgroundColor: 'transparent',
            yAxisID: 'yCpu',
            tension: 0.2
          }},
          {{
            label: 'Memory RSS (MB)',
            data: {json.dumps(sys_rss)},
            borderColor: '#10b981',
            backgroundColor: 'rgba(16, 185, 129, 0.1)',
            yAxisID: 'yMem',
            fill: true,
            tension: 0.2
          }}
        ]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        scales: {{
          yCpu: {{
            type: 'linear',
            position: 'left',
            title: {{ display: true, text: 'CPU %' }},
            max: 100
          }},
          yMem: {{
            type: 'linear',
            position: 'right',
            grid: {{ drawOnChartArea: false }},
            title: {{ display: true, text: 'Memory RSS (MB)' }}
          }}
        }}
      }}
    }});
    ''' if sys_time_labels else '' }
  </script>
</body>
</html>
"""
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        return target_path

    def print_console_summary(self):
        r = self.result
        print("\n" + "=" * 80)
        print(f" 🚀 PERFORMANCE BENCHMARK RESULTS: {r.scenario_name.upper()}")
        print(f" Concurrency: {r.concurrency} | Duration: {r.duration_sec}s | Grade: {r.performance_grade}")
        print("=" * 80)
        print(f"  Total Requests:       {r.total_requests:,}")
        print(f"  Successful Requests:  {r.successful_requests:,}")
        print(f"  Failed Requests:      {r.failed_requests} ({r.error_rate_pct:.2f}%)")
        print(f"  Throughput (RPS):     {r.rps:,.1f} req/s")
        print(f"  Bandwidth:            {r.throughput_kb_s:,.1f} KB/s ({r.total_bytes_kb:,.1f} KB)")
        print(f"  Apdex Score:          {r.apdex_score:.3f} (Target 100ms)")
        print("-" * 80)
        print(f"  Latency Min:          {r.latency_min_ms:.1f} ms")
        print(f"  Latency Median:       {r.latency_median_ms:.1f} ms")
        print(f"  Latency Mean:         {r.latency_mean_ms:.1f} ms")
        print(f"  Latency P90:          {r.latency_p90_ms:.1f} ms")
        print(f"  Latency P95:          {r.latency_p95_ms:.1f} ms")
        print(f"  Latency P99:          {r.latency_p99_ms:.1f} ms")
        print(f"  Latency Max:          {r.latency_max_ms:.1f} ms")
        print("-" * 80)
        print("  SLA Compliance Checklist:")
        for sla_name, passed in r.sla_compliance.items():
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"    - {sla_name:<20}: {status}")
        print("=" * 80 + "\n")
