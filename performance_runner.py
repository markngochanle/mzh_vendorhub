"""
Web Dashboard Runner for Mizuho Performance Testing Suite.
Provides a modern visual interface for triggering performance benchmarks, viewing live logs,
and opening Chart.js performance reports directly in the browser.
"""

import os
import sys
import json
import time
import subprocess
from pathlib import Path
from html import escape
from urllib.parse import parse_qs

from common import layout, send_html, read_post_form, APP_DIR
from performance.config import REPORTS_DIR, PROFILES
from performance.scenarios import SCENARIO_REGISTRY

BASE_DIR = APP_DIR
LOG_FILE_PATH = REPORTS_DIR / "perf_progress.log"

current_process = None
current_scenario = None
current_log_file = None


def page_performance_runner(handler):
    """
    Hiển thị giao diện Dashboard điều khiển Performance Testing Suite.
    """
    scenario_cards_html = []
    for sc_id, sc in SCENARIO_REGISTRY.items():
        prof = sc.get("default_profile", "standard")
        prof_info = PROFILES.get(prof, PROFILES["standard"])

        scenario_cards_html.append(f"""
        <tr id="sc-row-{sc_id}">
          <td style="vertical-align: top; padding: 14px 12px;">
            <div style="font-weight: 700; color: var(--primary); font-size: 14px;">⚡ {escape(sc['name'])}</div>
            <div style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">{escape(sc['description'])}</div>
          </td>
          <td style="vertical-align: top; padding: 14px 12px;">
            <span class="badge" style="background:#e0f2fe; color:#0369a1; font-weight:600;">{prof.upper()}</span>
            <div style="font-size: 11px; color: var(--text-muted); margin-top: 4px;">{prof_info['concurrency']} người dùng, {prof_info['duration_sec']}s</div>
          </td>
          <td style="vertical-align: top; padding: 14px 12px; font-size: 12px; color: var(--text-secondary);">
            Trung vị &le; 60ms<br>
            P95 &le; 250ms<br>
            Tỷ lệ lỗi &le; 0.5%
          </td>
          <td style="text-align: center; vertical-align: top; padding: 14px 12px;">
            <span class="test-status badge badge-idle" id="status-{sc_id}">Sẵn sàng</span>
          </td>
          <td style="text-align: center; vertical-align: top; padding: 14px 12px;">
            <button type="button" class="btn btn-run" onclick="runScenario('{sc_id}')" style="font-size: 12px; padding: 6px 14px; background: var(--primary); color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600;">Chạy Test</button>
          </td>
        </tr>
        """)

    # List recently generated HTML reports
    reports_html = []
    if REPORTS_DIR.exists():
        html_files = sorted(REPORTS_DIR.glob("*.html"), key=lambda f: f.stat().st_mtime, reverse=True)[:6]
        for f in html_files:
            mtime_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(f.stat().st_mtime))
            size_kb = round(f.stat().st_size / 1024, 1)
            reports_html.append(f"""
            <li style="display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; border-bottom: 1px solid var(--border); font-size: 13px;">
              <div>
                <strong><a href="/performance/report?name={f.name}" target="_blank" style="color: var(--primary); text-decoration: none;">📊 {f.name}</a></strong>
                <span style="color: var(--text-muted); font-size: 11px; margin-left: 8px;">({size_kb} KB - {mtime_str})</span>
              </div>
              <a href="/performance/report?name={f.name}" target="_blank" class="btn btn-secondary" style="font-size: 11px; padding: 4px 10px; text-decoration: none;">Mở Báo Cáo &rarr;</a>
            </li>
            """)

    if not reports_html:
        reports_html.append("<li style='padding: 10px; color: var(--text-muted); font-size: 13px;'>Chưa có báo cáo nào được tạo. Hãy chạy một kịch bản kiểm thử để xem kết quả.</li>")

    body_html = f"""
    <div style="margin-bottom: 24px; display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 16px;">
      <div>
        <h2 style="margin: 0 0 6px 0; color: var(--text-primary); display: flex; align-items: center; gap: 8px;">
          <span>⚡ Trung Tâm Đo Lường & Kiểm Thử Tải (Performance Suite)</span>
          <span style="font-size: 12px; background: #dbeafe; color: #1e40af; padding: 3px 8px; border-radius: 4px; font-weight: 600;">Chuẩn Doanh Nghiệp</span>
        </h2>
        <p style="margin: 0; color: var(--text-muted); font-size: 14px;">
          Đo lường năng lực chịu tải, kiểm định chất lượng SLA, chấm điểm Apdex và phân tích kế hoạch thực thi truy vấn SQLite (chạy 100% offline nội bộ).
        </p>
      </div>
      <div style="display: flex; gap: 10px; align-items: center;">
        <select id="profile-select" style="padding: 7px 10px; font-size: 13px; border: 1px solid var(--border); border-radius: 4px; background: white;">
          <option value="smoke">Cấu hình: Nhanh (Smoke - 2 users, 5s)</option>
          <option value="standard" selected>Cấu hình: Tiêu chuẩn (Standard - 10 users, 15s)</option>
          <option value="stages">Cấu hình: Đa giai đoạn (k6 Stages: 5 -> 15 -> 2 VUs)</option>
          <option value="saturation_knee">Cấu hình: Quét trần chịu tải (Knee-of-the-Curve 5-100 VUs)</option>
          <option value="heavy">Cấu hình: Tải cao (Heavy - 25 users, 20s)</option>
          <option value="stress">Cấu hình: Quá tải cực hạn (Stress - 50 users, 15s)</option>
          <option value="soak">Cấu hình: Độ bền bỉ dài hạn (Soak - 8 users, 45s)</option>
        </select>
        <button type="button" id="btn-db-bench" class="btn" style="background: #0284c7; color:#fff; border:none; font-weight: 600; padding: 7px 14px; border-radius: 4px; cursor: pointer;" onclick="runDbBench()">
          🗄️ Benchmark CSDL SQLite
        </button>
        <button type="button" id="btn-run-all" class="btn" style="background: var(--success); color:#fff; border:none; font-weight: 600; padding: 7px 14px; border-radius: 4px; cursor: pointer;" onclick="runScenario('all')">
          ▶ Chạy Tất Cả Kịch Bản
        </button>
      </div>
    </div>

    <!-- Scenarios Table -->
    <div class="card" style="padding: 0; overflow: hidden; margin-bottom: 24px;">
      <table style="width:100%; border-collapse: collapse; margin:0; border:none;">
        <thead>
          <tr style="background: #f8fafc; border-bottom: 1px solid var(--border);">
            <th style="text-align: left; padding: 12px;">Kịch Bản Kiểm Thử</th>
            <th style="text-align: left; width: 190px; padding: 12px;">Mức Tải (Profile)</th>
            <th style="text-align: left; width: 180px; padding: 12px;">Cam Kết SLA</th>
            <th style="width: 120px; text-align: center; padding: 12px;">Trạng Thái</th>
            <th style="width: 110px; text-align: center; padding: 12px;">Thao Tác</th>
          </tr>
        </thead>
        <tbody>
          {"".join(scenario_cards_html)}
        </tbody>
      </table>
    </div>

    <!-- Live Execution Console -->
    <div class="card" style="margin-bottom: 24px;">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
        <h3 style="margin: 0; font-size: 15px; color: var(--text-primary); display: flex; align-items: center; gap: 8px;">
          <span>🖥️ Nhật Ký Thực Thi Thời Gian Thực (Console Log)</span>
          <span id="runner-process-status" style="font-size: 11px; background: #f1f5f9; padding: 2px 8px; border-radius: 4px; font-weight: 600; color: var(--text-muted);">Sẵn sàng</span>
        </h3>
        <button type="button" class="btn btn-secondary" onclick="clearConsole()" style="font-size: 11px; padding: 4px 10px;">Xóa Màn Hình</button>
      </div>
      <pre id="terminal-box" style="background: #0f172a; color: #f8fafc; font-family: monospace; font-size: 12px; padding: 14px; border-radius: 6px; height: 260px; overflow-y: auto; margin: 0; white-space: pre-wrap; line-height: 1.5;"></pre>
    </div>

    <!-- Reports Section -->
    <div class="card">
      <h3 style="margin: 0 0 12px 0; font-size: 15px; color: var(--text-primary);">📊 Báo Cáo Đo Lường Gần Đây (Đồ Thị Chart.js)</h3>
      <ul style="list-style: none; padding: 0; margin: 0;">
        {"".join(reports_html)}
      </ul>
    </div>

    <script>
      let activeInterval = null;
      let lastLogIndex = 0;

      function clearConsole() {{
        document.getElementById('terminal-box').innerText = '';
      }}

      function updateStatusBadge(id, status) {{
        const b = document.getElementById('status-' + id);
        if (!b) return;
        b.innerText = status;
        if (status === 'Đang chạy...') {{
          b.className = 'test-status badge';
          b.style.background = '#fef08a';
          b.style.color = '#854d0e';
        }} else if (status === 'Đạt' || status.includes('Xuất sắc') || status.includes('Rất tốt') || status.includes('Tốt')) {{
          b.className = 'test-status badge';
          b.style.background = '#dcfce7';
          b.style.color = '#166534';
        }} else if (status === 'Thất bại' || status.includes('Kém')) {{
          b.className = 'test-status badge';
          b.style.background = '#fee2e2';
          b.style.color = '#991b1b';
        }} else {{
          b.className = 'test-status badge badge-idle';
        }}
      }}

      function runScenario(scId) {{
        if (activeInterval) {{
          alert('Đang có một tiến trình kiểm thử chạy.');
          return;
        }}
        const profile = document.getElementById('profile-select').value;
        const term = document.getElementById('terminal-box');
        term.innerText = '>>> Đang khởi động kịch bản: ' + scId + ' (Cấu hình: ' + profile + ')...\\n';
        lastLogIndex = 0;
        document.getElementById('runner-process-status').innerText = 'Đang chạy';

        if (scId === 'all') {{
          document.querySelectorAll('.test-status').forEach(b => {{
            b.innerText = 'Đang chờ';
            b.style.background = '#e2e8f0';
            b.style.color = '#475569';
          }});
        }} else {{
          updateStatusBadge(scId, 'Đang chạy...');
        }}

        fetch('/api/performance-tests/run', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/x-www-form-urlencoded' }},
          body: 'scenario=' + encodeURIComponent(scId) + '&profile=' + encodeURIComponent(profile)
        }})
        .then(res => res.json())
        .then(data => {{
          if (data.status === 'ok') {{
            activeInterval = setInterval(() => pollLog(scId), 300);
          }} else {{
            alert(data.message || 'Không thể khởi động kiểm thử.');
            resetUI();
          }}
        }})
        .catch(err => {{
          alert('Lỗi kết nối tới máy chủ: ' + err);
          resetUI();
        }});
      }}

      function runDbBench() {{
        runScenario('db_bench');
      }}

      function pollLog(scId) {{
        fetch('/api/performance-tests/log?offset=' + lastLogIndex)
        .then(res => res.json())
        .then(data => {{
          const term = document.getElementById('terminal-box');
          if (data.log) {{
            term.innerText += data.log;
            term.scrollTop = term.scrollHeight;
          }}
          lastLogIndex = data.next_offset || lastLogIndex;

          if (data.status === 'done') {{
            clearInterval(activeInterval);
            activeInterval = null;
            document.getElementById('runner-process-status').innerText = 'Hoàn thành';
            const success = data.exit_code === 0;

            if (scId === 'all') {{
              document.querySelectorAll('.test-status').forEach(b => {{
                b.innerText = success ? 'Đạt SLA' : 'Không đạt';
                b.style.background = success ? '#dcfce7' : '#fee2e2';
                b.style.color = success ? '#166534' : '#991b1b';
              }});
            }} else if (scId !== 'db_bench') {{
              updateStatusBadge(scId, success ? 'Đạt SLA' : 'Không đạt');
            }}

            term.innerText += '\\n------------------------------------------------------------\\n';
            term.innerText += success ? '🎉 ĐỢT KIỂM THỬ HIỆU NĂNG ĐÃ HOÀN TẤT THÀNH CÔNG!\\n' : '⚠️ KIỂM THỬ HOÀN TẤT VỚI CÁC CHỈ SỐ GHI NHẬN Ở TRÊN.\\n';
            term.scrollTop = term.scrollHeight;
          }}
        }})
        .catch(err => {{
          console.error('Lỗi khi lấy log:', err);
        }});
      }}

      function resetUI() {{
        if (activeInterval) {{
          clearInterval(activeInterval);
          activeInterval = null;
        }}
        document.getElementById('runner-process-status').innerText = 'Sẵn sàng';
      }}
    </script>
    """
    send_html(handler, layout("Đo Lường Hiệu Năng", body_html))


def handle_run_performance_post(handler):
    """
    Handles POST requests to run performance test scenarios.
    """
    global current_process, current_scenario, current_log_file

    if current_process and current_process.poll() is None:
        send_json(handler, {"status": "error", "message": "A performance test is already in progress."}, status=400)
        return

    form = read_post_form(handler)
    sc = (form.get("scenario", ["read_heavy"])[0] or "").strip()
    profile = (form.get("profile", ["standard"])[0] or "").strip()

    LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE_PATH, "w", encoding="utf-8") as f:
        f.write("=== Mizuho Performance Test Runner ===\n")
        f.write(f"Scenario: {sc}\n")
        f.write(f"Profile: {profile}\n")
        f.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("======================================\n\n")

    args = [sys.executable, "run_performance_tests.py"]
    if sc == "db_bench":
        args += ["--db-bench", "--scenario", "read_heavy", "--profile", "smoke", "--no-html"]
    elif sc == "all":
        args += ["--scenario", "all", "--profile", profile, "--db-bench"]
    else:
        args += ["--scenario", sc, "--profile", profile]

    try:
        current_log_file = open(LOG_FILE_PATH, "a", buffering=1, encoding="utf-8")
        current_process = subprocess.Popen(
            args,
            cwd=str(BASE_DIR),
            stdout=current_log_file,
            stderr=subprocess.STDOUT,
            close_fds=True
        )
        current_scenario = sc
        send_json(handler, {"status": "ok", "message": "Performance benchmark started."})
    except Exception as e:
        if current_log_file:
            current_log_file.close()
            current_log_file = None
        send_json(handler, {"status": "error", "message": f"Could not launch benchmark: {str(e)}"}, status=500)


def handle_get_performance_log(handler):
    """
    Returns accumulated logs and completion status.
    """
    global current_process, current_log_file

    status = "idle"
    exit_code = None

    if current_process:
        poll_res = current_process.poll()
        if poll_res is None:
            status = "running"
        else:
            status = "done"
            exit_code = poll_res
            current_process = None
            if current_log_file:
                current_log_file.close()
                current_log_file = None

    log_content = ""
    if LOG_FILE_PATH.exists():
        try:
            with open(LOG_FILE_PATH, "r", encoding="utf-8", errors="ignore") as f:
                log_content = f.read()
        except Exception:
            pass

    qs = parse_qs(handler.path.split("?")[-1]) if "?" in handler.path else {}
    offset_raw = qs.get("offset", ["0"])[0]
    offset = int(offset_raw) if offset_raw.isdigit() else 0

    sliced_log = log_content[offset:]
    send_json(handler, {
        "status": status,
        "exit_code": exit_code,
        "log": sliced_log,
        "next_offset": len(log_content)
    })


def page_performance_reports_list(handler):
    """
    Renders the Performance Reports Archive & Analytics Dashboard at /performance-reports.
    """
    reports_data = []
    if REPORTS_DIR.exists():
        json_files = sorted(REPORTS_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
        for jf in json_files:
            try:
                with open(jf, "r", encoding="utf-8") as f:
                    data = json.load(f)
                html_name = jf.stem + ".html"
                has_html = (REPORTS_DIR / html_name).exists()
                meta = data.get("meta", {})
                metrics = data.get("metrics", {})
                grade = meta.get("grade", "N/A")

                reports_data.append({
                    "json_name": jf.name,
                    "html_name": html_name if has_html else None,
                    "scenario": meta.get("scenario", jf.stem),
                    "timestamp": meta.get("generated_at", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(jf.stat().st_mtime))),
                    "concurrency": meta.get("concurrency", "-"),
                    "duration": meta.get("duration_sec", "-"),
                    "grade": grade,
                    "rps": metrics.get("rps", 0.0),
                    "p50_ms": metrics.get("latency_median_ms", 0.0),
                    "p95_ms": metrics.get("latency_p95_ms", 0.0),
                    "apdex": metrics.get("apdex_score", 0.0),
                    "error_rate": metrics.get("error_rate_pct", 0.0),
                    "total_reqs": metrics.get("total_requests", 0),
                    "size_kb": round(jf.stat().st_size / 1024, 1)
                })
            except Exception:
                continue

    # KPI summary counts
    total_runs = len(reports_data)
    latest_grade = reports_data[0]["grade"] if reports_data else "N/A"
    best_p95 = min([r["p95_ms"] for r in reports_data if r["p95_ms"] > 0], default=0.0)
    max_rps = max([r["rps"] for r in reports_data], default=0.0)

    rows_html = []
    for r in reports_data:
        # Grade badge color
        if "A" in r["grade"]:
            g_bg = "#dcfce7"
            g_color = "#166534"
        elif "B" in r["grade"] or "C" in r["grade"]:
            g_bg = "#fef9c3"
            g_color = "#854d0e"
        else:
            g_bg = "#fee2e2"
            g_color = "#991b1b"

        err_style = "color: #dc2626; font-weight: bold;" if r["error_rate"] > 0.5 else "color: var(--text-secondary);"
        view_btn = f"""<a href="/performance/report?name={r['html_name']}" target="_blank" class="btn" style="background: var(--primary); color: white; padding: 5px 12px; font-size: 12px; border-radius: 4px; text-decoration: none; font-weight: 600;">📊 Xem Báo Cáo</a>""" if r["html_name"] else """<span class="text-muted" style="font-size: 11px;">Chưa có HTML</span>"""

        rows_html.append(f"""
        <tr>
          <td style="padding: 12px; font-size: 13px;">
            <div style="font-weight: 700; color: var(--primary); font-size: 14px;">{escape(r['scenario'])}</div>
            <div style="font-size: 11px; color: var(--text-muted); margin-top: 2px;">🕒 {escape(r['timestamp'])}</div>
          </td>
          <td style="text-align: center; padding: 12px;">
            <span class="badge" style="background: {g_bg}; color: {g_color}; font-weight: 800; font-size: 12px; padding: 4px 10px; border-radius: 6px;">
              {escape(r['grade'])}
            </span>
          </td>
          <td style="text-align: right; padding: 12px; font-size: 13px;">
            <strong>{r['concurrency']}</strong> users<br>
            <small class="text-muted">{r['duration']}s</small>
          </td>
          <td style="text-align: right; padding: 12px; font-size: 13px;">
            <strong>{r['rps']:,.1f}</strong> req/s<br>
            <small class="text-muted">{r['total_reqs']:,} reqs</small>
          </td>
          <td style="text-align: right; padding: 12px; font-size: 13px;">
            <strong style="color: {'#166534' if r['p95_ms'] <= 250 else '#dc2626'};">{r['p95_ms']:.1f} ms</strong><br>
            <small class="text-muted">P50: {r['p50_ms']:.1f}ms</small>
          </td>
          <td style="text-align: right; padding: 12px; font-size: 13px; font-weight: 600;">
            {r['apdex']:.3f}
          </td>
          <td style="text-align: right; padding: 12px; font-size: 13px; {err_style}">
            {r['error_rate']:.2f}%
          </td>
          <td style="text-align: center; padding: 12px; white-space: nowrap;">
            {view_btn}
          </td>
        </tr>
        """)

    if not rows_html:
        rows_html.append("""
        <tr>
          <td colspan="8" style="text-align: center; padding: 30px; color: var(--text-muted); font-size: 14px;">
            Chưa có báo cáo hiệu năng nào. Hãy chuyển sang <a href="/performance-tests">⚡ Performance Suite</a> để thực hiện bài test đầu tiên!
          </td>
        </tr>
        """)

    body_html = f"""
    <div style="margin-bottom: 24px; display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 16px;">
      <div>
        <h2 style="margin: 0 0 6px 0; color: var(--text-primary); display: flex; align-items: center; gap: 8px;">
          <span>📊 Kho Lưu Trữ Báo Cáo & Phân Tích Hiệu Năng</span>
          <span style="font-size: 12px; background: #dbeafe; color: #1e40af; padding: 3px 8px; border-radius: 4px; font-weight: 600;">Lịch Sử Kiểm Thử</span>
        </h2>
        <p style="margin: 0; color: var(--text-muted); font-size: 14px;">
          Theo dõi, đối sánh kết quả các lần kiểm thử tải, mức độ tuân thủ tiêu chuẩn SLA và đồ thị trực quan Chart.js (hoạt động 100% offline).
        </p>
      </div>
      <div style="display: flex; gap: 10px;">
        <a href="/performance-tests" class="btn" style="background: var(--primary); color: white; padding: 8px 16px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 13px; display: flex; align-items: center; gap: 6px;">
          ⚡ Mở Trình Chạy Kiểm Thử Mới
        </a>
      </div>
    </div>

    <!-- KPI Summary Grid -->
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 24px;">
      <div class="card" style="padding: 16px; border-left: 4px solid var(--primary);">
        <div style="font-size: 12px; text-transform: uppercase; color: var(--text-muted); font-weight: 600;">Tổng Số Đợt Benchmark</div>
        <div style="font-size: 26px; font-weight: 800; color: var(--text-primary); margin-top: 4px;">{total_runs}</div>
        <div style="font-size: 11px; color: var(--text-muted); margin-top: 2px;">Lưu trữ trong performance_reports/</div>
      </div>
      <div class="card" style="padding: 16px; border-left: 4px solid #16a34a;">
        <div style="font-size: 12px; text-transform: uppercase; color: var(--text-muted); font-weight: 600;">Xếp Hạng Gần Nhất</div>
        <div style="font-size: 26px; font-weight: 800; color: #16a34a; margin-top: 4px;">{escape(latest_grade)}</div>
        <div style="font-size: 11px; color: var(--text-muted); margin-top: 2px;">Đánh giá qua Apdex & SLA gate</div>
      </div>
      <div class="card" style="padding: 16px; border-left: 4px solid #0284c7;">
        <div style="font-size: 12px; text-transform: uppercase; color: var(--text-muted); font-weight: 600;">Độ Trễ P95 Tốt Nhất</div>
        <div style="font-size: 26px; font-weight: 800; color: #0284c7; margin-top: 4px;">{best_p95:.1f} <span style="font-size: 14px; font-weight: 500;">ms</span></div>
        <div style="font-size: 11px; color: var(--text-muted); margin-top: 2px;">Ngưỡng SLA cam kết: &le; 250 ms</div>
      </div>
      <div class="card" style="padding: 16px; border-left: 4px solid #f59e0b;">
        <div style="font-size: 12px; text-transform: uppercase; color: var(--text-muted); font-weight: 600;">Lưu Lượng Đỉnh (RPS)</div>
        <div style="font-size: 26px; font-weight: 800; color: #f59e0b; margin-top: 4px;">{max_rps:,.1f} <span style="font-size: 14px; font-weight: 500;">req/s</span></div>
        <div style="font-size: 11px; color: var(--text-muted); margin-top: 2px;">Ngưỡng SLA cam kết: &ge; 35 req/s</div>
      </div>
    </div>

    <!-- Reports Table -->
    <div class="card" style="padding: 0; overflow: hidden;">
      <table style="width: 100%; border-collapse: collapse; margin: 0; border: none;">
        <thead>
          <tr style="background: #f8fafc; border-bottom: 1px solid var(--border);">
            <th style="text-align: left; padding: 12px;">Kịch Bản & Thời Điểm Thực Thi</th>
            <th style="text-align: center; width: 150px; padding: 12px;">Xếp Hạng (Grade)</th>
            <th style="text-align: right; width: 120px; padding: 12px;">Mức Tải</th>
            <th style="text-align: right; width: 140px; padding: 12px;">Lưu Lượng (RPS)</th>
            <th style="text-align: right; width: 130px; padding: 12px;">Độ Trễ P95</th>
            <th style="text-align: right; width: 120px; padding: 12px;">Apdex (T=100ms)</th>
            <th style="text-align: right; width: 100px; padding: 12px;">Tỷ Lệ Lỗi</th>
            <th style="text-align: center; width: 140px; padding: 12px;">Thao Tác</th>
          </tr>
        </thead>
        <tbody>
          {"".join(rows_html)}
        </tbody>
      </table>
    </div>
    """
    send_html(handler, layout("Báo Cáo Hiệu Năng", body_html))


def page_view_performance_report(handler):
    """
    Serves a specific generated HTML report file from performance_reports/.
    If no name provided, automatically loads the latest report or redirects to /performance-reports.
    """
    qs = parse_qs(handler.path.split("?")[-1]) if "?" in handler.path else {}
    name = qs.get("name", [""])[0].strip()

    if not name:
        html_files = sorted(REPORTS_DIR.glob("*.html"), key=lambda f: f.stat().st_mtime, reverse=True)
        if html_files:
            name = html_files[0].name
        else:
            handler.send_response(302)
            handler.send_header("Location", "/performance-reports")
            handler.end_headers()
            return

    if ".." in name or "/" in name or "\\" in name:
        send_html(handler, layout("Error", "<div class='card danger'>Invalid report filename.</div>"), status=400)
        return

    target_file = (REPORTS_DIR / name).resolve()
    try:
        target_file.relative_to(REPORTS_DIR)
    except ValueError:
        send_html(handler, layout("Error", "<div class='card danger'>Access denied.</div>"), status=403)
        return

    if not target_file.exists() or not target_file.is_file():
        send_html(handler, layout("Not Found", f"<div class='card danger'>Report {escape(name)} not found. <a href='/performance-reports'>Back to Reports</a></div>"), status=404)
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
