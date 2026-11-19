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
        Phân tích các chỉ số hiệu năng và tự động đưa ra các khuyến nghị tối ưu hóa hệ thống cụ thể.
        Chạy 100% offline nội bộ, không phụ thuộc vào bất kỳ dịch vụ hay server bên ngoài nào.
        """
        recs = []
        r = self.result

        # 1. Invoice List Pagination (nếu trang '/' bị chậm)
        root_ep = r.endpoint_breakdown.get("/", {})
        if root_ep.get("p95_ms", 0) > 300 or root_ep.get("median_ms", 0) > 200:
            recs.append({
                "priority": "ƯU TIÊN CAO",
                "tag": "Cơ Sở Dữ Liệu & Phân Trang",
                "title": "Áp Dụng Phân Trang Phía Server Cho Danh Sách Hóa Đơn ('/')",
                "observation": f"Đường dẫn trang chủ danh sách hóa đơn '/' ghi nhận độ trễ P95 lên đến {root_ep.get('p95_ms', 0):.1f}ms (Trung vị: {root_ep.get('median_ms', 0):.1f}ms).",
                "root_cause": "Hệ thống thực hiện truy vấn, đối soát và render toàn bộ bản ghi hóa đơn trong 1 truy vấn duy nhất mà không có mệnh đề SQL LIMIT/OFFSET, dẫn đến tải CPU và tuần tự hóa dữ liệu rất nặng.",
                "solution": "Bổ sung phân trang vào page_invoices_list(filters, page=1, page_size=50). Chỉ truy vấn 50 dòng mỗi trang: SELECT * FROM invoices WHERE ... ORDER BY id DESC LIMIT 50 OFFSET (page-1)*50.",
                "impact": "Dự kiến giảm từ 80% - 90% thời gian tải trang danh sách hóa đơn chính."
            })

        # 2. Dashboard In-Memory Caching (nếu trang '/dashboard' bị chậm)
        dash_ep = r.endpoint_breakdown.get("/dashboard", {})
        dash_fy_ep = r.endpoint_breakdown.get("/dashboard?fy=2026", {})
        max_dash_p95 = max(dash_ep.get("p95_ms", 0), dash_fy_ep.get("p95_ms", 0))
        if max_dash_p95 > 250:
            recs.append({
                "priority": "ƯU TIÊN CAO",
                "tag": "Bộ Nhớ Đệm In-Memory",
                "title": "Bổ Sung Bộ Nhớ Đệm In-Memory (LRU/TTL) Cho Màn Hình Executive Dashboard",
                "observation": f"Màn hình Dashboard ghi nhận độ trễ P95 là {max_dash_p95:.1f}ms khi có nhiều người dùng đồng thời.",
                "root_cause": "Ma trận dòng tiền cash-out, cam kết hợp đồng và tổng chi phí năm tài chính phải quét và tính toán lại qua toàn bộ hợp đồng và phụ lục trên mỗi request GET, dù dữ liệu thực tế không thay đổi liên tục từng giây.",
                "solution": "Bọc hàm tính toán page_dashboard() bằng bộ nhớ đệm in-memory TTL 60 giây (hoặc dùng functools.lru_cache và tự động xóa cache khi có sự kiện ghi dữ liệu mới).",
                "impact": "Giảm độ trễ tải Dashboard lặp lại từ vài giây xuống dưới 5ms (tăng hơn 95% năng lực phục vụ)."
            })

        # 3. Staff Leaves & Attendance N+1 Query Optimization
        staff_ep = r.endpoint_breakdown.get("/staff", {})
        punct_ep = r.endpoint_breakdown.get("/attendance/punctuality", {})
        if staff_ep.get("p95_ms", 0) > 250 or punct_ep.get("p95_ms", 0) > 300:
            recs.append({
                "priority": "ƯU TIÊN VỪA",
                "tag": "Tối Ưu Truy Vấn SQL",
                "title": "Tối Ưu Truy Vấn Tính Ngày Phép & Báo Cáo Chuyên Cần",
                "observation": f"Quản lý nhân sự ('/staff') và chuyên cần ('/attendance/punctuality') ghi nhận độ trễ P95 lên đến {max(staff_ep.get('p95_ms', 0), punct_ep.get('p95_ms', 0)):.1f}ms.",
                "root_cause": "Việc tính toán số ngày phép còn lại và chuyển tiếp qua nhiều phụ lục thực hiện các vòng lặp truy vấn con (N+1) lồng nhau qua contract_staff_links và monthly_attendance_summary.",
                "solution": "Sử dụng truy vấn gộp JOIN và đảm bảo có index: CREATE INDEX IF NOT EXISTS idx_mas_staff_month ON monthly_attendance_summary(staff_id, month); và CREATE INDEX IF NOT EXISTS idx_csl_staff ON contract_staff_links(staff_id, contract_id).",
                "impact": "Triệt tiêu hoàn toàn vòng lặp truy vấn N+1, đảm bảo tốc độ phản hồi dưới 50ms cho màn hình nhân sự và chấm công."
            })

        # 4. Multi-Worker WSGI/ASGI Production Deployment (nếu Concurrency >= 20)
        if r.concurrency >= 20:
            recs.append({
                "priority": "KIẾN TRÚC HỆ THỐNG",
                "tag": "Khả Năng Mở Rộng Máy Chủ",
                "title": "Triển Khai Máy Chủ Ứng Dụng Đa Luồng (Multi-Worker WSGI/ASGI) Cho Production",
                "observation": f"Ở mức tải cao ({r.concurrency} người dùng đồng thời), hiện tượng dồn ứ hàng đợi xuất hiện khiến thời gian phản hồi trung vị tăng lên {r.latency_median_ms:.1f}ms.",
                "root_cause": "Máy chủ phát triển (http.server.BaseHTTPRequestHandler) chạy đơn tiến trình Python, nên các request đến đồng thời phải xếp hàng đợi sau các tác vụ render HTML tốn CPU.",
                "solution": "Ở môi trường production có nhiều người dùng thực tế, triển khai ứng dụng phía sau máy chủ WSGI đa tiến trình (ví dụ: gunicorn -w 4 -b 0.0.0.0:8800 server:app hoặc Waitress) kết hợp Nginx reverse proxy.",
                "impact": "Khai thác sức mạnh CPU đa nhân, phục vụ mượt mà trên 200 người dùng đồng thời mà không bị nghẽn hàng đợi."
            })

        # 5. SQLite WAL Mode & Concurrency Tuning (Quick Win)
        recs.append({
            "priority": "CẢI TIẾN NHANH",
            "tag": "Tối Ưu Động Cơ SQLite",
            "title": "Bật Chế Độ WAL (Write-Ahead Logging) & Tối Ưu Bộ Nhớ Đệm Cho SQLite",
            "observation": "Các tác vụ đọc và ghi dữ liệu đồng thời trên SQLite có thể gặp độ trễ chờ khóa bảng khi nhiều giao dịch chạy cùng lúc.",
            "root_cause": "Cơ chế Rollback Journal mặc định của SQLite sẽ khóa toàn bộ file CSDL trong khi ghi, tạm thời chặn các luồng đọc đồng thời.",
            "solution": "Thực thi PRAGMA journal_mode = WAL; và PRAGMA synchronous = NORMAL; và PRAGMA cache_size = -64000; (bộ nhớ đệm 64MB RAM) trong hàm db_connect() tại common.py.",
            "impact": "Cho phép nhiều luồng đọc đồng thời trong khi một luồng đang ghi, xóa bỏ hoàn toàn xung đột khóa CSDL."
        })

        # 6. Static Asset Caching & HTTP Compression
        recs.append({
            "priority": "CẢI TIẾN NHANH",
            "tag": "Nén HTTP & Bộ Nhớ Đệm",
            "title": "Bật Nén HTTP Gzip & Đặt Header Cache Trình Duyệt Cho File Tĩnh",
            "observation": f"Tổng dung lượng dữ liệu truyền tải trong đợt test là {r.total_bytes_kb:,.1f} KB ({r.throughput_kb_s:,.1f} KB/s).",
            "root_cause": "Các tài nguyên tĩnh lớn như chart.umd.min.js (210 KB) và bảng HTML lớn đang được truyền tải dạng raw text mà không có Content-Encoding nén gzip.",
            "solution": "Bổ sung nén Gzip cho các phản hồi text/html, javascript, css có kích thước > 1KB, đồng thời cấu hình Cache-Control: public, max-age=604800 cho thư mục /static/.",
            "impact": "Giảm khoảng 70% băng thông mạng truyền tải, giúp trình duyệt của người dùng tải trang nhanh hơn gấp nhiều lần."
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
                return "<span class='badge pass'>ĐẠT</span>"
            return "<span class='badge fail'>KHÔNG ĐẠT</span>"

        # Recommendations HTML
        recommendations = self.generate_recommendations()
        recs_cards_html = ""
        for rec in recommendations:
            if rec["priority"] == "ƯU TIÊN CAO":
                p_bg = "#fee2e2"
                p_color = "#dc2626"
            elif rec["priority"] == "ƯU TIÊN VỪA":
                p_bg = "#fef9c3"
                p_color = "#ca8a04"
            elif rec["priority"] == "KIẾN TRÚC HỆ THỐNG":
                p_bg = "#dbeafe"
                p_color = "#2563eb"
            else:  # CẢI TIẾN NHANH
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
                  <strong style="color: var(--primary); display: block; margin-bottom: 4px;">🔍 Hiện tượng ghi nhận:</strong>
                  <span style="color: var(--text-secondary);">{rec['observation']}</span>
                </div>
                <div style="background: #f8fafc; padding: 12px; border-radius: 6px; border: 1px solid #f1f5f9;">
                  <strong style="color: #ca8a04; display: block; margin-bottom: 4px;">⚙️ Nguyên nhân cốt lõi:</strong>
                  <span style="color: var(--text-secondary);">{rec['root_cause']}</span>
                </div>
              </div>

              <div style="margin-top: 12px; background: #f0fdf4; border: 1px solid #bbf7d0; padding: 12px; border-radius: 6px; font-size: 13px;">
                <strong style="color: #166534; display: block; margin-bottom: 4px;">🛠️ Giải pháp & Hành động cụ thể:</strong>
                <span style="color: #14532d; line-height: 1.5;">{rec['solution']}</span>
                <div style="margin-top: 6px; font-size: 12px; color: #15803d; font-weight: 700;">
                  🚀 Hiệu quả dự kiến: {rec['impact']}
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
              <td class="text-right">{data['count']:,}</td>
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
                scan_badge = "<span class='badge warn'>QUÉT BẢNG</span>" if q.get("has_full_table_scan") else "<span class='badge pass'>CÓ INDEX</span>"
                h_map = {"EXCELLENT": "XUẤT SẮC", "GOOD": "TỐT", "ACCEPTABLE": "CHẤP NHẬN ĐƯỢC", "SLOW": "CHẬM"}
                h_text = h_map.get(q.get("health", ""), q.get("health", "CHƯA RÕ"))
                health_color = "pass" if q.get("health") in ("EXCELLENT", "GOOD") else "warn"
                db_rows_html += f"""
                <tr>
                  <td><strong>{q['id']}</strong><br><small class="text-muted">{q['name']}</small></td>
                  <td class="text-right">{q.get('rows_returned', 0):,}</td>
                  <td class="text-right">{q.get('iterations', 0)}</td>
                  <td class="text-right font-bold">{q.get('p95_ms', 0)} ms</td>
                  <td class="text-center">{scan_badge}</td>
                  <td class="text-center"><span class="badge {health_color}">{h_text}</span></td>
                </tr>
                """
            db_section_html = f"""
            <div class="card mt-4">
              <h2>🗄️ Đánh Giá Hiệu Năng Truy Vấn SQLite & Kế Hoạch Thực Thi (Execution Plan)</h2>
              <p class="text-muted">Thời gian thực thi trực tiếp trên CSDL SQLite (50 lần lặp) kèm kiểm tra độ phủ của chỉ mục Index.</p>
              <div class="table-container">
                <table>
                  <thead>
                    <tr>
                      <th>Tên Truy Vấn</th>
                      <th class="text-right">Số Dòng</th>
                      <th class="text-right">Lần Chạy</th>
                      <th class="text-right">Độ Trễ P95</th>
                      <th class="text-center">Kế Hoạch (Plan)</th>
                      <th class="text-center">Đánh Giá</th>
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
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Báo Cáo Hiệu Năng & Đo Lường Tải - Mizuho VMS</title>
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
        <h1>⚡ Báo Cáo Đo Lường & Đánh Giá Hiệu Năng Hệ Thống</h1>
        <div class="meta">
          <strong>Kịch bản:</strong> {r.scenario_name} | 
          <strong>Người dùng đồng thời:</strong> {r.concurrency} users | 
          <strong>Thời lượng chạy:</strong> {r.duration_sec}s | 
          <strong>Thời điểm thực thi:</strong> {self.readable_timestamp}
        </div>
      </div>
      <div class="grade-badge">
        Xếp hạng: {r.performance_grade}
      </div>
    </div>

    <!-- Executive KPI Cards -->
    <div class="grid-4">
      <div class="card kpi-card">
        <span class="kpi-title">Tổng Số Request</span>
        <span class="kpi-value">{r.total_requests:,}</span>
        <span class="kpi-sub">Thành công: {r.successful_requests:,} | Thất bại: {r.failed_requests}</span>
      </div>
      <div class="card kpi-card">
        <span class="kpi-title">Lưu Lượng Xử Lý (RPS)</span>
        <span class="kpi-value">{r.rps:,.1f}</span>
        <span class="kpi-sub">Băng thông: {r.throughput_kb_s:,.1f} KB/s</span>
      </div>
      <div class="card kpi-card">
        <span class="kpi-title">Độ Trễ P95 (95% Người Dùng)</span>
        <span class="kpi-value">{r.latency_p95_ms:.1f} <span style="font-size: 16px; font-weight: 500;">ms</span></span>
        <span class="kpi-sub">Trung vị: {r.latency_median_ms:.1f}ms | P99: {r.latency_p99_ms:.1f}ms</span>
      </div>
      <div class="card kpi-card">
        <span class="kpi-title">Điểm Hài Lòng Apdex (T=100ms)</span>
        <span class="kpi-value">{r.apdex_score:.3f}</span>
        <span class="kpi-sub">Tỷ lệ lỗi: {r.error_rate_pct:.2f}%</span>
      </div>
    </div>

    <!-- SLA Verification Table -->
    <div class="card mb-4">
      <h2>🎯 Đối Soát Tiêu Chuẩn Chất Lượng Dịch Vụ (SLA)</h2>
      <div class="table-container">
        <table class="sla-table">
          <thead>
            <tr>
              <th>Chỉ Số Kiểm Định</th>
              <th>Ngưỡng Tiêu Chuẩn</th>
              <th>Kết Quả Thực Tế</th>
              <th class="text-center">Trạng Thái</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Độ trễ trung vị (P50 - Median)</td>
              <td>&le; {SLA_THRESHOLDS['p50_latency_ms']} ms</td>
              <td><strong>{r.latency_median_ms:.1f} ms</strong></td>
              <td class="text-center">{sla_badge(r.sla_compliance.get('p50_latency', False))}</td>
            </tr>
            <tr>
              <td>Độ trễ phân vị 95 (P95)</td>
              <td>&le; {SLA_THRESHOLDS['p95_latency_ms']} ms</td>
              <td><strong>{r.latency_p95_ms:.1f} ms</strong></td>
              <td class="text-center">{sla_badge(r.sla_compliance.get('p95_latency', False))}</td>
            </tr>
            <tr>
              <td>Độ trễ phân vị 99 (P99)</td>
              <td>&le; {SLA_THRESHOLDS['p99_latency_ms']} ms</td>
              <td><strong>{r.latency_p99_ms:.1f} ms</strong></td>
              <td class="text-center">{sla_badge(r.sla_compliance.get('p99_latency', False))}</td>
            </tr>
            <tr>
              <td>Tỷ lệ lỗi tối đa</td>
              <td>&le; {SLA_THRESHOLDS['max_error_rate_pct']}%</td>
              <td><strong>{r.error_rate_pct:.2f}%</strong></td>
              <td class="text-center">{sla_badge(r.sla_compliance.get('error_rate', False))}</td>
            </tr>
            <tr>
              <td>Lưu lượng tối thiểu (RPS)</td>
              <td>&ge; {SLA_THRESHOLDS['min_rps']} req/s</td>
              <td><strong>{r.rps:.1f} req/s</strong></td>
              <td class="text-center">{sla_badge(r.sla_compliance.get('min_rps', False))}</td>
            </tr>
            <tr>
              <td>Chỉ số hài lòng người dùng (Apdex)</td>
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
        <h2>📈 Biểu Đồ Lưu Lượng (RPS) & Độ Trễ Theo Thời Gian</h2>
        <div class="chart-box">
          <canvas id="timelineChart"></canvas>
        </div>
      </div>
      <div class="card">
        <h2>⏱️ Biểu Đồ So Sánh Độ Trễ P95 (ms) Từng Endpoint</h2>
        <div class="chart-box">
          <canvas id="endpointChart"></canvas>
        </div>
      </div>
    </div>

    { f'''
    <!-- System Resources Chart -->
    <div class="card mt-4">
      <h2>🖥️ Tiêu Thụ Tài Nguyên Hệ Thống (CPU & Bộ Nhớ RAM RSS)</h2>
      <div class="chart-box">
        <canvas id="sysChart"></canvas>
      </div>
    </div>
    ''' if sys_time_labels else '' }

    <!-- System Optimization Recommendations Section -->
    <div class="card mt-4">
      <h2>💡 Khuyến Nghị Tối Ưu Hóa & Cải Tiến Kiến Trúc Hệ Thống</h2>
      <p class="text-muted" style="margin-bottom: 18px;">
        Các giải pháp kỹ thuật cụ thể được thuật toán phân tích tự động từ dữ liệu đo lường thực tế của bài test (chạy 100% offline nội bộ).
      </p>
      {recs_cards_html}
    </div>

    <!-- Detailed Endpoint Breakdown Table -->
    <div class="card mt-4">
      <h2>🌐 Bảng Phân Tích Độ Trễ & Tỷ Lệ Lỗi Từng Endpoint</h2>
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>Đường Dẫn (Endpoint)</th>
              <th class="text-right">Tổng Request</th>
              <th class="text-right">Số Lỗi</th>
              <th class="text-right">RPS</th>
              <th class="text-right">Tối Thiểu (Min)</th>
              <th class="text-right">Trung Vị (Median)</th>
              <th class="text-right">Phân Vị 95 (P95)</th>
              <th class="text-right">Tối Đa (Max)</th>
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
            label: 'Request / giây (RPS)',
            data: {json.dumps(time_rps)},
            borderColor: '#183181',
            backgroundColor: 'rgba(24, 49, 129, 0.1)',
            yAxisID: 'yRps',
            tension: 0.3,
            fill: true
          }},
          {{
            label: 'Độ trễ P95 (ms)',
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
            title: {{ display: true, text: 'Request / giây' }}
          }},
          yLat: {{
            type: 'linear',
            position: 'right',
            grid: {{ drawOnChartArea: false }},
            title: {{ display: true, text: 'Độ trễ (ms)' }}
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
          label: 'Độ trễ P95 (ms)',
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
          x: {{ title: {{ display: true, text: 'Độ trễ P95 (ms)' }} }}
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
            label: 'CPU (%)',
            data: {json.dumps(sys_cpu)},
            borderColor: '#f59e0b',
            backgroundColor: 'transparent',
            yAxisID: 'yCpu',
            tension: 0.2
          }},
          {{
            label: 'Bộ nhớ RAM RSS (MB)',
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
            title: {{ display: true, text: 'RAM RSS (MB)' }}
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
        print(f" 🚀 KẾT QUẢ ĐO LƯỜNG HIỆU NĂNG: {r.scenario_name.upper()}")
        print(f" Người dùng đồng thời: {r.concurrency} | Thời lượng: {r.duration_sec}s | Xếp hạng: {r.performance_grade}")
        print("=" * 80)
        print(f"  Tổng số Request:         {r.total_requests:,}")
        print(f"  Request thành công:      {r.successful_requests:,}")
        print(f"  Request thất bại:        {r.failed_requests} ({r.error_rate_pct:.2f}%)")
        print(f"  Lưu lượng xử lý (RPS):   {r.rps:,.1f} req/s")
        print(f"  Băng thông mạng:         {r.throughput_kb_s:,.1f} KB/s ({r.total_bytes_kb:,.1f} KB)")
        print(f"  Điểm hài lòng Apdex:     {r.apdex_score:.3f} (Mục tiêu 100ms)")
        print("-" * 80)
        print(f"  Độ trễ tối thiểu (Min):  {r.latency_min_ms:.1f} ms")
        print(f"  Độ trễ trung vị (P50):   {r.latency_median_ms:.1f} ms")
        print(f"  Độ trễ trung bình:       {r.latency_mean_ms:.1f} ms")
        print(f"  Độ trễ phân vị 90 (P90): {r.latency_p90_ms:.1f} ms")
        print(f"  Độ trễ phân vị 95 (P95): {r.latency_p95_ms:.1f} ms")
        print(f"  Độ trễ phân vị 99 (P99): {r.latency_p99_ms:.1f} ms")
        print(f"  Độ trễ tối đa (Max):     {r.latency_max_ms:.1f} ms")
        print("-" * 80)
        print("  Danh Sách Đối Soát Cam Kết SLA:")
        sla_labels = {
            "p50_latency": "Độ trễ trung vị P50 (<= 60ms)",
            "p95_latency": "Độ trễ phân vị P95 (<= 250ms)",
            "p99_latency": "Độ trễ phân vị P99 (<= 600ms)",
            "error_rate": "Tỷ lệ lỗi (<= 0.5%)",
            "min_rps": "Lưu lượng tối thiểu (>= 35 req/s)",
            "apdex_score": "Điểm hài lòng Apdex (>= 0.90)",
        }
        for sla_key, passed in r.sla_compliance.items():
            label = sla_labels.get(sla_key, sla_key)
            status = "✅ ĐẠT" if passed else "❌ KHÔNG ĐẠT"
            print(f"    - {label:<35}: {status}")
        print("=" * 80 + "\n")
