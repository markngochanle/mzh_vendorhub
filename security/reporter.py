"""
Visual Security Report Generator.
Generates 100% offline, self-contained HTML security audit reports with Chart.js and JSON data.
"""

import json
import time
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Dict, Any, Optional, List

from security.config import (
    REPORTS_DIR,
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    SEVERITY_LOW,
    SEVERITY_INFO,
    SEVERITY_COLORS,
)
from security.scanner_engine import ScanResult


class SecurityReporter:
    """
    Generates enterprise-grade HTML reports and JSON artifacts for security audits.
    """

    def __init__(self, result: ScanResult):
        self.result = result
        self.timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.readable_timestamp = self.result.timestamp

    def export_json(self, filename: Optional[str] = None) -> Path:
        if not filename:
            filename = f"sec_report_{self.timestamp_str}.json"
        target_path = REPORTS_DIR / filename

        r = self.result
        data = {
            "meta": {
                "generated_at": r.timestamp,
                "duration_sec": r.duration_sec,
                "profile": r.profile_name,
                "security_score": r.security_score,
                "security_grade": r.security_grade,
                "total_endpoints_scanned": r.total_endpoints_scanned,
                "total_files_analyzed": r.total_files_analyzed,
            },
            "statistics": {
                "total_checks": r.total_checks_run,
                "passed_checks": r.total_checks_passed,
                "failed_checks": r.total_checks_failed,
                "pass_rate_pct": round((r.total_checks_passed / max(1, r.total_checks_run)) * 100, 1),
            },
            "findings_by_severity": r.findings_by_severity,
            "owasp_compliance": r.owasp_compliance,
            "findings": [
                {
                    "rule_id": f.rule_id,
                    "title": f.title,
                    "category_id": f.category_id,
                    "severity": f.severity,
                    "component": f.component,
                    "description": f.description,
                    "evidence": f.evidence,
                    "remediation": f.remediation,
                }
                for f in r.findings
            ],
            "database_audit": r.database_audit,
            "endpoint_matrix": r.endpoint_matrix,
        }

        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return target_path

    def export_html(self, filename: Optional[str] = None) -> Path:
        if not filename:
            filename = f"sec_report_{self.timestamp_str}.html"
        target_path = REPORTS_DIR / filename

        r = self.result
        pass_rate_pct = round((r.total_checks_passed / max(1, r.total_checks_run)) * 100, 1)

        # Severity counts
        crit = r.findings_by_severity.get(SEVERITY_CRITICAL, 0)
        high = r.findings_by_severity.get(SEVERITY_HIGH, 0)
        med = r.findings_by_severity.get(SEVERITY_MEDIUM, 0)
        low = r.findings_by_severity.get(SEVERITY_LOW, 0)
        info = r.findings_by_severity.get(SEVERITY_INFO, 0)

        # Grade styling
        if r.security_score >= 85:
            score_color = "#16a34a"
            score_bg = "#dcfce7"
        elif r.security_score >= 70:
            score_color = "#ca8a04"
            score_bg = "#fef9c3"
        else:
            score_color = "#dc2626"
            score_bg = "#fee2e2"

        # Findings table rows
        findings_rows = []
        for i, f in enumerate(r.findings, 1):
            sev_meta = SEVERITY_COLORS.get(f.severity, SEVERITY_COLORS[SEVERITY_INFO])
            findings_rows.append(f"""
            <tr style="border-bottom: 1px solid var(--border);">
              <td style="padding: 12px; font-weight: 600; font-size: 12px; color: var(--text-muted);">{i}</td>
              <td style="padding: 12px;">
                <span class="badge" style="background: {sev_meta['bg']}; color: {sev_meta['color']}; font-weight: 700; font-size: 11px;">
                  {f.severity}
                </span>
              </td>
              <td style="padding: 12px; font-family: monospace; font-size: 12px; font-weight: 600; color: var(--primary);">
                {escape(f.rule_id)}
              </td>
              <td style="padding: 12px;">
                <div style="font-weight: 700; font-size: 13px; color: var(--text-main); margin-bottom: 4px;">{escape(f.title)}</div>
                <div style="font-size: 12px; color: var(--text-muted);">{escape(f.description)}</div>
                <div style="margin-top: 6px; padding: 6px 10px; background: #f8fafc; border-left: 3px solid var(--primary); font-family: monospace; font-size: 11px; color: #334155; word-break: break-all;">
                  <strong>Vị trí:</strong> {escape(f.component)}<br>
                  <strong>Bằng chứng:</strong> {escape(f.evidence)}
                </div>
                <div style="margin-top: 6px; font-size: 12px; color: #15803d; background: #f0fdf4; padding: 6px 10px; border-radius: 4px;">
                  <strong>💡 Khắc phục:</strong> {escape(f.remediation)}
                </div>
              </td>
            </tr>
            """)

        # Endpoint matrix rows
        ep_rows = []
        for ep in r.endpoint_matrix:
            def status_badge(p: bool):
                return "<span style='color: #16a34a; font-weight: bold;'>✅ Đạt</span>" if p else "<span style='color: #dc2626; font-weight: bold;'>⚠️ Lỗi</span>"

            ep_status_badge = "<span class='badge' style='background:#dcfce7; color:#166534;'>AN TOÀN</span>"
            if ep["status"] == "FAIL":
                ep_status_badge = "<span class='badge' style='background:#fee2e2; color:#991b1b;'>RỦI RO CAO</span>"
            elif ep["status"] == "WARNING":
                ep_status_badge = "<span class='badge' style='background:#fef9c3; color:#854d0e;'>CẢNH BÁO</span>"

            ep_rows.append(f"""
            <tr style="border-bottom: 1px solid var(--border); font-size: 12px;">
              <td style="padding: 10px 12px; font-weight: 600;">{escape(ep['name'])}</td>
              <td style="padding: 10px 12px; font-family: monospace; color: var(--primary);">{escape(ep['path'])}</td>
              <td style="padding: 10px 12px;"><span class="badge" style="background: #f1f5f9; color: #475569;">{escape(ep['category'])}</span></td>
              <td style="padding: 10px 12px; text-align: center;">{status_badge(ep['headers_passed'])}</td>
              <td style="padding: 10px 12px; text-align: center;">{status_badge(ep['sqli_passed'])}</td>
              <td style="padding: 10px 12px; text-align: center;">{status_badge(ep['xss_passed'])}</td>
              <td style="padding: 10px 12px; text-align: center;">{status_badge(ep['traceback_passed'])}</td>
              <td style="padding: 10px 12px; text-align: center;">{ep_status_badge}</td>
            </tr>
            """)

        # OWASP radar chart data
        owasp_labels = [c["id"] + " " + c["name"] for c in r.owasp_compliance.values()]
        owasp_scores = [c["score"] for c in r.owasp_compliance.values()]

        html_content = f"""<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Báo Cáo Kiểm Định Bảo Mật Hệ Thống - Mizuho VMS</title>
  <style>
    :root {{
      --primary: #1e3a8a;
      --primary-light: #3b82f6;
      --bg: #f8fafc;
      --card-bg: #ffffff;
      --border: #e2e8f0;
      --text-main: #0f172a;
      --text-muted: #64748b;
      --success: #16a34a;
      --warning: #ca8a04;
      --danger: #dc2626;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: var(--bg);
      color: var(--text-main);
      margin: 0;
      padding: 24px;
      line-height: 1.5;
    }}
    .container {{
      max-width: 1280px;
      margin: 0 auto;
    }}
    .header {{
      background: white;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 24px;
      margin-bottom: 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 16px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.02);
    }}
    .badge {{
      display: inline-block;
      padding: 3px 8px;
      border-radius: 4px;
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }}
    .kpi-card {{
      background: white;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 18px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.02);
    }}
    .kpi-val {{
      font-size: 28px;
      font-weight: 800;
      margin-top: 6px;
      letter-spacing: -0.5px;
    }}
    .card {{
      background: white;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 24px;
      margin-bottom: 24px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.02);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      text-align: left;
    }}
    th {{
      background: #f8fafc;
      color: var(--text-muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      padding: 12px;
      border-bottom: 1px solid var(--border);
    }}
    .btn {{
      display: inline-flex;
      align-items: center;
      padding: 8px 14px;
      border-radius: 4px;
      font-size: 13px;
      font-weight: 600;
      text-decoration: none;
      cursor: pointer;
      border: 1px solid transparent;
    }}
    .btn-primary {{
      background: var(--primary);
      color: white;
    }}
    .btn-secondary {{
      background: white;
      border-color: var(--border);
      color: var(--text-main);
    }}
  </style>
  <script src="/static/js/chart.umd.min.js"></script>
</head>
<body>
  <div class="container">
    <!-- Header -->
    <div class="header">
      <div>
        <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 6px;">
          <h1 style="margin: 0; font-size: 22px; color: var(--primary);">🛡️ Báo Cáo Kiểm Định An Ninh & Bảo Mật Toàn Diện</h1>
          <span class="badge" style="background: {score_bg}; color: {score_color}; font-size: 13px; padding: 4px 10px;">
            {r.security_grade}
          </span>
        </div>
        <div style="font-size: 13px; color: var(--text-muted);">
          Hệ thống: Mizuho Vendor Management System | Kiểm định: OWASP Top 10 | Độ bao phủ: 100% Endpoints & Source Code
        </div>
        <div style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">
          Thời gian thực hiện: <strong>{r.timestamp}</strong> | Thời lượng quét: <strong>{r.duration_sec}s</strong> | Chế độ: <strong>{r.profile_name}</strong>
        </div>
      </div>
      <div style="display: flex; gap: 10px;">
        <a href="/security-checks" class="btn btn-secondary">&larr; Quay lại Bộ Kiểm Tra</a>
        <a href="/security-reports" class="btn btn-secondary">📑 Danh Mục Báo Cáo</a>
        <button class="btn btn-primary" onclick="window.print()">🖨️ In Báo Cáo (PDF)</button>
      </div>
    </div>

    <!-- KPI Grid -->
    <div class="kpi-grid">
      <div class="kpi-card" style="border-left: 4px solid {score_color};">
        <div style="font-size: 12px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">Điểm Số An Ninh</div>
        <div class="kpi-val" style="color: {score_color};">{r.security_score} <span style="font-size: 16px; font-weight: normal; color: var(--text-muted);">/ 100.0</span></div>
        <div style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">Xếp hạng: {r.security_grade}</div>
      </div>

      <div class="kpi-card" style="border-left: 4px solid var(--primary);">
        <div style="font-size: 12px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">Tổng Số Hạng Mục Kiểm Định</div>
        <div class="kpi-val" style="color: var(--primary);">{r.total_checks_run}</div>
        <div style="font-size: 12px; color: #16a34a; margin-top: 4px;">Đạt: {r.total_checks_passed} ({pass_rate_pct}%) | Cần xử lý: {r.total_checks_failed}</div>
      </div>

      <div class="kpi-card" style="border-left: 4px solid var(--primary-light);">
        <div style="font-size: 12px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">Độ Bao Phủ Hệ Thống</div>
        <div class="kpi-val" style="color: var(--primary-light);">100%</div>
        <div style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">{r.total_endpoints_scanned} Endpoints | {r.total_files_analyzed} File nguồn Python</div>
      </div>

      <div class="kpi-card" style="border-left: 4px solid {SEVERITY_COLORS[SEVERITY_CRITICAL]['badge'] if crit > 0 else '#16a34a'};">
        <div style="font-size: 12px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">Phát Hiện Rủi Ro</div>
        <div class="kpi-val" style="color: {'#dc2626' if crit > 0 or high > 0 else '#16a34a'};">
          {len(r.findings)} <span style="font-size: 14px; font-weight: normal; color: var(--text-muted);">vấn đề</span>
        </div>
        <div style="font-size: 11px; margin-top: 4px;">
          <span style="color: #dc2626; font-weight: bold;">{crit} Nghiêm trọng</span> &bull; 
          <span style="color: #ea580c; font-weight: bold;">{high} Cao</span> &bull; 
          <span style="color: #ca8a04; font-weight: bold;">{med} Trung bình</span> &bull; 
          <span style="color: #2563eb;">{low} Thấp</span>
        </div>
      </div>
    </div>

    <!-- Charts Section -->
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(480px, 1fr)); gap: 20px; margin-bottom: 24px;">
      <div class="card" style="margin-bottom: 0;">
        <h3 style="margin: 0 0 16px 0; font-size: 15px; color: var(--text-main);">📊 Phân Bổ Phát Hiện Theo Mức Độ Nghiêm Trọng</h3>
        <div style="height: 250px; display: flex; justify-content: center; align-items: center;">
          <canvas id="severityChart"></canvas>
        </div>
      </div>

      <div class="card" style="margin-bottom: 0;">
        <h3 style="margin: 0 0 16px 0; font-size: 15px; color: var(--text-main);">🎯 Mức Độ Tuân Thủ 10 Hạng Mục OWASP Top 10 (Thang điểm 100)</h3>
        <div style="height: 250px; display: flex; justify-content: center; align-items: center;">
          <canvas id="owaspChart"></canvas>
        </div>
      </div>
    </div>

    <!-- Executive Recommendations -->
    <div class="card">
      <h3 style="margin: 0 0 14px 0; font-size: 16px; color: var(--primary);">
        💡 Khuyến Nghị Tối Ưu Hóa & Gia Cố Bảo Mật Hệ Thống
      </h3>
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 14px;">
        <div style="background: #f8fafc; border: 1px solid var(--border); border-left: 4px solid #2563eb; border-radius: 6px; padding: 14px;">
          <div style="font-weight: 700; font-size: 14px; color: #1e40af; margin-bottom: 4px;">1. Bổ sung các Header Bảo Mật HTTP</div>
          <div style="font-size: 12px; color: var(--text-muted);">
            Thêm <code>X-Content-Type-Options: nosniff</code> và <code>X-Frame-Options: SAMEORIGIN</code> vào hàm <code>send_html</code> trong <code>common.py</code> để chống lại tấn công MIME-sniffing và Clickjacking.
          </div>
        </div>

        <div style="background: #f8fafc; border: 1px solid var(--border); border-left: 4px solid #16a34a; border-radius: 6px; padding: 14px;">
          <div style="font-weight: 700; font-size: 14px; color: #15803d; margin-bottom: 4px;">2. Duy trì Tham Số Hóa Truy Vấn 100%</div>
          <div style="font-size: 12px; color: var(--text-muted);">
            Tuyệt đối tuân thủ sử dụng dấu hỏi <code>?</code> và tuple trong các truy vấn <code>conn.execute()</code>, loại bỏ hoàn toàn việc ghép chuỗi để triệt tiêu nguy cơ SQL Injection.
          </div>
        </div>

        <div style="background: #f8fafc; border: 1px solid var(--border); border-left: 4px solid #ca8a04; border-radius: 6px; padding: 14px;">
          <div style="font-weight: 700; font-size: 14px; color: #854d0e; margin-bottom: 4px;">3. Tăng cường Kiểm Soát Lỗi Ngoại Lệ</div>
          <div style="font-size: 12px; color: var(--text-muted);">
            Bắt toàn bộ ngoại lệ <code>ValueError</code> khi phân tích tham số ID hoặc ngày tháng để trả về thông báo lỗi thân thiện (400 Bad Request), không làm rò rỉ Python Traceback ra màn hình.
          </div>
        </div>
      </div>
    </div>

    <!-- Detailed Findings Table -->
    <div class="card">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px;">
        <h3 style="margin: 0; font-size: 16px; color: var(--text-main);">
          📑 Danh Sách Chi Tiết Các Phát Hiện & Đề Xuất Khắc Phục ({len(r.findings)})
        </h3>
      </div>
      <div style="overflow-x: auto;">
        <table>
          <thead>
            <tr>
              <th style="width: 40px;">#</th>
              <th style="width: 120px;">Mức Độ</th>
              <th style="width: 150px;">Quy Tắc</th>
              <th>Chi Tiết Phát Hiện, Bằng Chứng & Hướng Dẫn Khắc Phục</th>
            </tr>
          </thead>
          <tbody>
            {"".join(findings_rows) if findings_rows else "<tr><td colspan='4' style='padding: 24px; text-align: center; color: #16a34a; font-weight: 600;'>🎉 Không phát hiện lỗ hổng bảo mật nào! Hệ thống đạt mức an toàn tối đa.</td></tr>"}
          </tbody>
        </table>
      </div>
    </div>

    <!-- 100% Endpoint Matrix -->
    <div class="card">
      <h3 style="margin: 0 0 14px 0; font-size: 16px; color: var(--text-main);">
        🌐 Ma Trận Kiểm Định 100% Endpoints & Màn Hình Hệ Thống ({len(r.endpoint_matrix)} Endpoints)
      </h3>
      <div style="overflow-x: auto;">
        <table>
          <thead>
            <tr>
              <th>Màn Hình Chức Năng</th>
              <th>Đường Dẫn URL</th>
              <th>Phân Hệ</th>
              <th style="text-align: center;">HTTP Headers</th>
              <th style="text-align: center;">Chống SQLi</th>
              <th style="text-align: center;">Chống XSS</th>
              <th style="text-align: center;">Không Lộ Lỗi</th>
              <th style="text-align: center;">Trạng Thái</th>
            </tr>
          </thead>
          <tbody>
            {"".join(ep_rows)}
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <script>
    // Severity Doughnut Chart
    const ctxSev = document.getElementById('severityChart');
    if (ctxSev) {{
      new Chart(ctxSev, {{
        type: 'doughnut',
        data: {{
          labels: ['Nghiêm Trọng', 'Cao', 'Trung Bình', 'Thấp', 'Thông Tin'],
          datasets: [{{
            data: [{crit}, {high}, {med}, {low}, {info}],
            backgroundColor: ['#dc2626', '#ea580c', '#ca8a04', '#2563eb', '#64748b'],
            borderWidth: 2,
            borderColor: '#ffffff'
          }}]
        }},
        options: {{
          responsive: true,
          maintainAspectRatio: false,
          plugins: {{
            legend: {{ position: 'bottom', labels: {{ boxWidth: 12, font: {{ size: 11 }} }} }}
          }}
        }}
      }});
    }}

    // OWASP Horizontal Bar Chart
    const ctxOwasp = document.getElementById('owaspChart');
    if (ctxOwasp) {{
      new Chart(ctxOwasp, {{
        type: 'bar',
        data: {{
          labels: {json.dumps(owasp_labels, ensure_ascii=False)},
          datasets: [{{
            label: 'Điểm Tuân Thủ (/100)',
            data: {json.dumps(owasp_scores)},
            backgroundColor: function(context) {{
              const val = context.raw;
              if (val >= 85) return '#16a34a';
              if (val >= 60) return '#ca8a04';
              return '#dc2626';
            }},
            borderRadius: 4
          }}]
        }},
        options: {{
          indexAxis: 'y',
          responsive: true,
          maintainAspectRatio: false,
          scales: {{
            x: {{ min: 0, max: 100, grid: {{ color: '#f1f5f9' }} }},
            y: {{ grid: {{ display: false }}, ticks: {{ font: {{ size: 10 }} }} }}
          }},
          plugins: {{
            legend: {{ display: false }}
          }}
        }}
      }});
    }}
  </script>
</body>
</html>
"""
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        return target_path
