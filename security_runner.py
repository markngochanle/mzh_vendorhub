"""
Web Runner and UI Handlers for the Mizuho VMS Automated Security Audit Suite.
Provides interactive runner dashboard (/security-checks), reports archive (/security-reports),
and report visualizer (/security/report).
"""

import json
import subprocess
import sys
import time
from html import escape
from pathlib import Path
from urllib.parse import parse_qs

from common import layout, send_html, read_post_form
from security.config import REPORTS_DIR, LOG_FILE_PATH, SECURITY_PROFILES
from security.rules import RULES_METADATA

current_process: subprocess.Popen = None
current_profile: str = "standard"


def page_security_runner(handler):
    """
    Renders the Security Audit Suite Dashboard (/security-checks).
    """
    rules_rows_html = []
    for rule_id, rule_meta in RULES_METADATA.items():
        rules_rows_html.append(f"""
        <tr id="rule-row-{rule_id}">
          <td style="vertical-align: top; padding: 14px 12px;">
            <div style="font-weight: 700; color: var(--primary); font-size: 14px;">🛡️ {escape(rule_meta['name'])}</div>
            <div style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">{escape(rule_meta['description'])}</div>
          </td>
          <td style="vertical-align: top; padding: 14px 12px;">
            <span class="badge" style="background: #e0f2fe; color: #0369a1; font-weight: 700; font-family: monospace;">{escape(rule_meta['category'])}</span>
          </td>
          <td style="vertical-align: top; padding: 14px 12px; font-size: 12px;">
            <span class="badge" style="background: #fee2e2; color: #991b1b;">{escape(rule_meta['default_severity'])}</span>
          </td>
          <td style="text-align: center; vertical-align: top; padding: 14px 12px;">
            <span class="rule-status badge badge-idle" id="status-{rule_id}" style="background: #f1f5f9; color: #475569;">Sẵn sàng</span>
          </td>
        </tr>
        """)

    # Recent security reports
    reports_html = []
    if REPORTS_DIR.exists():
        html_files = sorted(REPORTS_DIR.glob("sec_report_*.html"), key=lambda f: f.stat().st_mtime, reverse=True)[:6]
        for f in html_files:
            mtime_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(f.stat().st_mtime))
            size_kb = round(f.stat().st_size / 1024, 1)
            reports_html.append(f"""
            <li style="display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; border-bottom: 1px solid var(--border); font-size: 13px;">
              <div>
                <strong><a href="/security/report?name={f.name}" target="_blank" style="color: var(--primary); text-decoration: none;">🛡️ {f.name}</a></strong>
                <span style="color: var(--text-muted); font-size: 11px; margin-left: 8px;">({size_kb} KB - {mtime_str})</span>
              </div>
              <a href="/security/report?name={f.name}" target="_blank" class="btn btn-secondary" style="font-size: 11px; padding: 4px 10px; text-decoration: none;">Mở Báo Cáo &rarr;</a>
            </li>
            """)

    if not reports_html:
        reports_html.append("<li style='padding: 12px; color: var(--text-muted); font-size: 13px;'>Chưa có báo cáo nào được ghi nhận. Bấm 'Bắt Đầu Quét Bảo Mật' để tạo phiên kiểm định đầu tiên.</li>")

    body_html = f"""
    <div style="margin-bottom: 24px; display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 16px;">
      <div>
        <h2 style="margin: 0 0 6px 0; color: var(--text-primary); display: flex; align-items: center; gap: 8px;">
          <span>🛡️ Trung Tâm Kiểm Định An Ninh & Tuân Thủ (Security Audit Suite)</span>
          <span style="font-size: 12px; background: #dcfce7; color: #166534; padding: 3px 8px; border-radius: 4px; font-weight: 600;">OWASP Top 10</span>
        </h2>
        <p style="margin: 0; color: var(--text-muted); font-size: 14px;">
          Tự động rà soát lỗ hổng bảo mật tĩnh (AST) và kiểm tra động 100% tất cả 40 endpoints (SQL Injection, XSS, Path Traversal, Security Headers, IDOR, Traceback Leak).
        </p>
      </div>
      <div style="display: flex; gap: 10px; align-items: center;">
        <select id="sec-profile-select" style="padding: 7px 10px; font-size: 13px; border: 1px solid var(--border); border-radius: 4px; background: white;">
          <option value="standard" selected>Cấu hình: Tiêu chuẩn (100% 40 Endpoints & Toàn bộ Mã Nguồn)</option>
          <option value="deep">Cấu hình: Chuyên sâu (Kiểm tra Toàn Diện + Fuzzing + Audit Logs)</option>
          <option value="quick">Cấu hình: Nhanh (Quét Tĩnh + 12 Endpoint Cốt Lõi)</option>
        </select>
        <button type="button" id="btn-run-security" class="btn" style="background: var(--primary); color:#fff; border:none; font-weight: 600; padding: 7px 16px; border-radius: 4px; cursor: pointer;" onclick="runSecurityScan()">
          ▶ Bắt Đầu Quét Bảo Mật 100%
        </button>
      </div>
    </div>

    <!-- Rules Table -->
    <div class="card" style="padding: 0; overflow: hidden; margin-bottom: 24px;">
      <table style="width:100%; border-collapse: collapse; margin:0; border:none;">
        <thead>
          <tr style="background: #f8fafc; border-bottom: 1px solid var(--border);">
            <th style="text-align: left; padding: 12px;">Quy Tắc Kiểm Định An Ninh</th>
            <th style="text-align: left; width: 140px; padding: 12px;">Hạng Mục OWASP</th>
            <th style="text-align: left; width: 140px; padding: 12px;">Mức Độ Rủi Ro</th>
            <th style="width: 130px; text-align: center; padding: 12px;">Trạng Thái</th>
          </tr>
        </thead>
        <tbody>
          {"".join(rules_rows_html)}
        </tbody>
      </table>
    </div>

    <!-- Live Execution Console -->
    <div class="card" style="margin-bottom: 24px;">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
        <h3 style="margin: 0; font-size: 15px; color: var(--text-primary); display: flex; align-items: center; gap: 8px;">
          <span>🖥️ Nhật Ký Kiểm Tra Thời Gian Thực (Audit Console Log)</span>
          <span id="scanner-process-status" style="font-size: 11px; background: #f1f5f9; padding: 2px 8px; border-radius: 4px; font-weight: 600; color: var(--text-muted);">Sẵn sàng</span>
        </h3>
        <button type="button" class="btn btn-secondary" onclick="clearSecurityConsole()" style="font-size: 11px; padding: 4px 10px;">Xóa Màn Hình</button>
      </div>
      <pre id="sec-terminal-box" style="background: #0f172a; color: #f8fafc; font-family: monospace; font-size: 12px; padding: 14px; border-radius: 6px; height: 260px; overflow-y: auto; margin: 0; white-space: pre-wrap; line-height: 1.5;"></pre>
    </div>

    <!-- Recent Reports -->
    <div class="card">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
        <h3 style="margin: 0; font-size: 15px; color: var(--text-primary);">📑 Báo Cáo Kiểm Định Bảo Mật Gần Đây</h3>
        <a href="/security-reports" class="btn btn-secondary" style="font-size: 12px; padding: 4px 10px;">Xem Toàn Bộ Báo Cáo &rarr;</a>
      </div>
      <ul style="list-style: none; padding: 0; margin: 0;">
        {"".join(reports_html)}
      </ul>
    </div>

    <script>
      let activeSecInterval = null;
      const NL = String.fromCharCode(10);

      function clearSecurityConsole() {{
        document.getElementById('sec-terminal-box').innerText = '';
      }}

      function updateAllRuleBadges(status) {{
        document.querySelectorAll('.rule-status').forEach(el => {{
          el.innerText = status;
          if (status === 'Đang quét...') {{
            el.style.background = '#fef08a';
            el.style.color = '#854d0e';
          }} else if (status === 'Hoàn tất') {{
            el.style.background = '#dcfce7';
            el.style.color = '#166534';
          }} else {{
            el.style.background = '#f1f5f9';
            el.style.color = '#475569';
          }}
        }});
      }}

      function runSecurityScan() {{
        const btn = document.getElementById('btn-run-security');
        const profile = document.getElementById('sec-profile-select').value;
        const statusEl = document.getElementById('scanner-process-status');
        const term = document.getElementById('sec-terminal-box');

        btn.disabled = true;
        btn.innerText = '⏳ Đang quét an ninh...';
        statusEl.innerText = 'Đang chạy';
        statusEl.style.background = '#fef08a';
        statusEl.style.color = '#854d0e';

        updateAllRuleBadges('Đang quét...');

        term.innerText = '>>> Khởi tạo phiên kiểm định bảo mật hệ thống (Profile: ' + profile + ')...' + NL;

        const formData = new URLSearchParams();
        formData.append('profile', profile);

        fetch('/api/security-checks/run', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/x-www-form-urlencoded' }},
          body: formData.toString()
        }})
        .then(res => res.json())
        .then(data => {{
          if (data.status === 'started') {{
            pollSecurityLogs();
          }} else {{
            alert('Lỗi: ' + (data.message || 'Không thể khởi động kiểm định'));
            resetSecUI();
          }}
        }})
        .catch(err => {{
          alert('Lỗi kết nối máy chủ: ' + err);
          resetSecUI();
        }});
      }}

      function pollSecurityLogs() {{
        if (activeSecInterval) clearInterval(activeSecInterval);

        activeSecInterval = setInterval(() => {{
          fetch('/api/security-checks/log')
          .then(res => res.json())
          .then(data => {{
            const term = document.getElementById('sec-terminal-box');
            if (data.log) {{
              term.innerText = data.log;
              term.scrollTop = term.scrollHeight;
            }}

            if (!data.running) {{
              clearInterval(activeSecInterval);
              activeSecInterval = null;
              resetSecUI();
              updateAllRuleBadges('Hoàn tất');

              term.innerText += NL + '------------------------------------------------------------' + NL;
              term.innerText += '🎉 PHIÊN KIỂM ĐỊNH AN NINH ĐÃ HOÀN TẤT THÀNH CÔNG!' + NL;
              if (data.latest_report) {{
                term.innerText += '👉 BÁO CÁO MỚI NHẤT: /security/report?name=' + data.latest_report + NL;
              }}
              term.scrollTop = term.scrollHeight;
            }}
          }})
          .catch(err => {{
            console.error('Lỗi khi lấy log an ninh:', err);
          }});
        }}, 600);
      }}

      function resetSecUI() {{
        const btn = document.getElementById('btn-run-security');
        if (btn) {{
          btn.disabled = false;
          btn.innerText = '▶ Bắt Đầu Quét Bảo Mật 100%';
        }}
        const statusEl = document.getElementById('scanner-process-status');
        if (statusEl) {{
          statusEl.innerText = 'Sẵn sàng';
          statusEl.style.background = '#f1f5f9';
          statusEl.style.color = '#475569';
        }}
      }}

      // Attach backup event listener once DOM is ready
      document.addEventListener('DOMContentLoaded', () => {{
        const btn = document.getElementById('btn-run-security');
        if (btn) {{
          btn.onclick = runSecurityScan;
        }}
      }});
    </script>
    """
    send_html(handler, layout("Kiểm Định Bảo Mật Hệ Thống", body_html))


def handle_run_security_post(handler):
    """
    Handles POST requests to start an automated security scan.
    """
    global current_process, current_profile

    if current_process and current_process.poll() is None:
        send_json(handler, {"status": "error", "message": "Phiên kiểm định an ninh khác đang được thực thi."}, status=400)
        return

    form = read_post_form(handler)
    profile = (form.get("profile", ["standard"])[0] or "").strip()
    if profile not in SECURITY_PROFILES:
        profile = "standard"

    current_profile = profile

    LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE_PATH, "w", encoding="utf-8") as f:
        f.write("=== Mizuho Security Audit Suite ===\n")
        f.write(f"Hồ sơ quét: {profile}\n")
        f.write(f"Thời gian bắt đầu: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("===================================\n\n")

    args = [sys.executable, "run_security_checks.py", "--profile", profile]

    try:
        runner_log = REPORTS_DIR / "security_runner_proc.log"
        proc_out = open(runner_log, "w", encoding="utf-8")
        current_process = subprocess.Popen(
            args,
            cwd=str(REPORTS_DIR.parent),
            stdout=proc_out,
            stderr=proc_out,
            text=True
        )
        send_json(handler, {"status": "started", "profile": profile})
    except Exception as e:
        send_json(handler, {"status": "error", "message": str(e)}, status=500)


def handle_get_security_log(handler):
    """
    Returns the real-time execution log output and process status.
    """
    global current_process

    running = current_process is not None and current_process.poll() is None
    log_content = ""

    if LOG_FILE_PATH.exists():
        try:
            log_content = LOG_FILE_PATH.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            pass

    latest_report = ""
    if REPORTS_DIR.exists():
        html_files = sorted(REPORTS_DIR.glob("sec_report_*.html"), key=lambda f: f.stat().st_mtime, reverse=True)
        if html_files:
            latest_report = html_files[0].name

    send_json(handler, {
        "running": running,
        "log": log_content,
        "latest_report": latest_report,
        "exit_code": current_process.poll() if current_process else None
    })


def page_security_reports_list(handler):
    """
    Renders the archive of past security audit reports (/security-reports).
    """
    rows_html = []
    if REPORTS_DIR.exists():
        json_files = sorted(REPORTS_DIR.glob("sec_report_*.json"), key=lambda f: f.stat().st_mtime, reverse=True)

        for jf in json_files:
            try:
                with open(jf, "r", encoding="utf-8") as f:
                    data = json.load(f)

                meta = data.get("meta", {})
                stats = data.get("statistics", {})
                sev_counts = data.get("findings_by_severity", {})

                html_name = jf.stem + ".html"
                has_html = (REPORTS_DIR / html_name).exists()

                gen_at = meta.get("generated_at", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(jf.stat().st_mtime)))
                score = meta.get("security_score", 0.0)
                grade = meta.get("security_grade", "Chưa xếp hạng")

                crit = sev_counts.get("NGHIÊM TRỌNG", 0)
                high = sev_counts.get("CAO", 0)
                med = sev_counts.get("TRUNG BÌNH", 0)
                low = sev_counts.get("THẤP", 0)

                # Grade color
                if score >= 85:
                    grade_color = "#16a34a"
                    grade_bg = "#dcfce7"
                elif score >= 70:
                    grade_color = "#ca8a04"
                    grade_bg = "#fef9c3"
                else:
                    grade_color = "#dc2626"
                    grade_bg = "#fee2e2"

                actions_html = f'<a href="/security/report?name={html_name}" target="_blank" class="btn btn-secondary" style="font-size: 11px; padding: 3px 8px;">📊 Mở HTML</a>' if has_html else '<span style="color: var(--text-muted); font-size: 11px;">Chỉ có JSON</span>'

                rows_html.append(f"""
                <tr style="border-bottom: 1px solid var(--border);">
                  <td style="padding: 12px; font-weight: 600;">{escape(gen_at)}</td>
                  <td style="padding: 12px; font-family: monospace; font-size: 12px; color: var(--primary);">
                    <a href="/security/report?name={html_name}" target="_blank" style="text-decoration: none; color: inherit;">
                      🛡️ {escape(jf.name)}
                    </a>
                  </td>
                  <td style="padding: 12px;">
                    <span class="badge" style="background:#e0f2fe; color:#0369a1; font-weight: 700;">
                      {escape(meta.get('profile', 'standard').upper())}
                    </span>
                  </td>
                  <td style="padding: 12px; text-align: right; font-weight: 800; font-size: 14px; color: {grade_color};">
                    {score} <span style="font-size: 11px; color: var(--text-muted);">/ 100</span>
                  </td>
                  <td style="padding: 12px; text-align: center;">
                    <span class="badge" style="background: {grade_bg}; color: {grade_color}; font-weight: 800; font-size: 11px;">
                      {escape(grade)}
                    </span>
                  </td>
                  <td style="padding: 12px; font-size: 12px;">
                    <span style="color: #dc2626; font-weight: bold;">{crit} Crit</span> &bull; 
                    <span style="color: #ea580c; font-weight: bold;">{high} High</span> &bull; 
                    <span style="color: #ca8a04;">{med} Med</span> &bull; 
                    <span style="color: #2563eb;">{low} Low</span>
                  </td>
                  <td style="padding: 12px; text-align: center;">
                    {actions_html}
                  </td>
                </tr>
                """)
            except Exception:
                continue

    if not rows_html:
        rows_html.append("<tr><td colspan='7' style='padding: 24px; text-align: center; color: var(--text-muted);'>Chưa có dữ liệu báo cáo an ninh. <a href='/security-checks'>Tạo phiên kiểm định mới</a></td></tr>")

    body_html = f"""
    <div style="margin-bottom: 24px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 16px;">
      <div>
        <h2 style="margin: 0 0 6px 0; color: var(--text-primary); display: flex; align-items: center; gap: 8px;">
          <span>📑 Lịch Sử Báo Cáo Kiểm Định Bảo Mật (Security Audit Archive)</span>
        </h2>
        <p style="margin: 0; color: var(--text-muted); font-size: 14px;">
          Theo dõi lịch sử điểm số an ninh, tỷ lệ tuân thủ OWASP Top 10 và các đề xuất khắc phục theo thời gian.
        </p>
      </div>
      <div>
        <a href="/security-checks" class="btn btn-primary" style="background: var(--primary); color: white; padding: 8px 14px; text-decoration: none; border-radius: 4px; font-weight: 600;">
          + Chạy Phiên Kiểm Định Mới
        </a>
      </div>
    </div>

    <div class="card" style="padding: 0; overflow: hidden;">
      <table style="width: 100%; border-collapse: collapse; margin: 0; border: none;">
        <thead>
          <tr style="background: #f8fafc; border-bottom: 1px solid var(--border);">
            <th style="text-align: left; width: 170px; padding: 12px;">Thời Gian Quét</th>
            <th style="text-align: left; padding: 12px;">Tên Tệp Báo Cáo</th>
            <th style="text-align: left; width: 110px; padding: 12px;">Hồ Sơ</th>
            <th style="text-align: right; width: 120px; padding: 12px;">Điểm An Ninh</th>
            <th style="text-align: center; width: 180px; padding: 12px;">Xếp Hạng</th>
            <th style="text-align: left; width: 180px; padding: 12px;">Lỗ Hổng Phát Hiện</th>
            <th style="text-align: center; width: 120px; padding: 12px;">Thao Tác</th>
          </tr>
        </thead>
        <tbody>
          {"".join(rows_html)}
        </tbody>
      </table>
    </div>
    """
    send_html(handler, layout("Lịch Sử Báo Cáo Bảo Mật", body_html))


def page_view_security_report(handler):
    """
    Serves a specific generated HTML security report safely.
    """
    qs = parse_qs(handler.path.split("?")[-1]) if "?" in handler.path else {}
    name = qs.get("name", [""])[0].strip()

    if not name:
        html_files = sorted(REPORTS_DIR.glob("sec_report_*.html"), key=lambda f: f.stat().st_mtime, reverse=True)
        if html_files:
            name = html_files[0].name
        else:
            handler.send_response(302)
            handler.send_header("Location", "/security-reports")
            handler.end_headers()
            return

    if ".." in name or "/" in name or "\\" in name:
        send_html(handler, layout("Lỗi", "<div class='card danger'>Tên tệp báo cáo không hợp lệ.</div>"), status=400)
        return

    target_file = (REPORTS_DIR / name).resolve()
    try:
        target_file.relative_to(REPORTS_DIR.resolve())
    except ValueError:
        send_html(handler, layout("Lỗi", "<div class='card danger'>Truy cập bị từ chối.</div>"), status=403)
        return

    if not target_file.exists() or not target_file.is_file():
        send_html(handler, layout("Không Tìm Thấy", f"<div class='card danger'>Báo cáo {escape(name)} không tồn tại. <a href='/security-reports'>Quay lại danh mục</a></div>"), status=404)
        return

    content = target_file.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(content)))
    handler.end_headers()
    handler.wfile.write(content)


def send_json(handler, data: dict, status=200):
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    encoded = json.dumps(data).encode("utf-8")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.end_headers()
    handler.wfile.write(encoded)
