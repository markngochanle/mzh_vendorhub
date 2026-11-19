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
    Renders the Performance Testing Dashboard interface.
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
            <div style="font-size: 11px; color: var(--text-muted); margin-top: 4px;">{prof_info['concurrency']} users, {prof_info['duration_sec']}s</div>
          </td>
          <td style="vertical-align: top; padding: 14px 12px; font-size: 12px; color: var(--text-secondary);">
            Median &le; 60ms<br>
            P95 &le; 250ms<br>
            Error &le; 0.5%
          </td>
          <td style="text-align: center; vertical-align: top; padding: 14px 12px;">
            <span class="test-status badge badge-idle" id="status-{sc_id}">Ready</span>
          </td>
          <td style="text-align: center; vertical-align: top; padding: 14px 12px;">
            <button type="button" class="btn btn-run" onclick="runScenario('{sc_id}')" style="font-size: 12px; padding: 6px 14px; background: var(--primary); color: white; border: none; border-radius: 4px; cursor: pointer;">Run</button>
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
              <a href="/performance/report?name={f.name}" target="_blank" class="btn btn-secondary" style="font-size: 11px; padding: 4px 10px; text-decoration: none;">Open Report &rarr;</a>
            </li>
            """)

    if not reports_html:
        reports_html.append("<li style='padding: 10px; color: var(--text-muted); font-size: 13px;'>No reports generated yet. Run a benchmark to view results.</li>")

    body_html = f"""
    <div style="margin-bottom: 24px; display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 16px;">
      <div>
        <h2 style="margin: 0 0 6px 0; color: var(--text-primary); display: flex; align-items: center; gap: 8px;">
          <span>⚡ Performance & Load Testing Suite</span>
          <span style="font-size: 12px; background: #dbeafe; color: #1e40af; padding: 3px 8px; border-radius: 4px; font-weight: 600;">Enterprise Grade</span>
        </h2>
        <p style="margin: 0; color: var(--text-muted); font-size: 14px;">
          High-performance benchmarking engine, SLA compliance gates, Apdex scoring, and direct SQLite query analysis.
        </p>
      </div>
      <div style="display: flex; gap: 10px; align-items: center;">
        <select id="profile-select" style="padding: 6px 10px; font-size: 13px; border: 1px solid var(--border); border-radius: 4px; background: white;">
          <option value="smoke">Profile: Smoke (2 users, 5s)</option>
          <option value="standard" selected>Profile: Standard (10 users, 15s)</option>
          <option value="heavy">Profile: Heavy (25 users, 20s)</option>
          <option value="stress">Profile: Stress (50 users, 15s)</option>
        </select>
        <button type="button" id="btn-db-bench" class="btn" style="background: #0284c7; color:#fff; border:none; font-weight: 600; padding: 7px 14px; border-radius: 4px; cursor: pointer;" onclick="runDbBench()">
          🗄️ Run DB Benchmarks
        </button>
        <button type="button" id="btn-run-all" class="btn" style="background: var(--success); color:#fff; border:none; font-weight: 600; padding: 7px 14px; border-radius: 4px; cursor: pointer;" onclick="runScenario('all')">
          ▶ Run All Workloads
        </button>
      </div>
    </div>

    <!-- Scenarios Table -->
    <div class="card" style="padding: 0; overflow: hidden; margin-bottom: 24px;">
      <table style="width:100%; border-collapse: collapse; margin:0; border:none;">
        <thead>
          <tr style="background: #f8fafc; border-bottom: 1px solid var(--border);">
            <th style="text-align: left; padding: 12px;">Benchmark Scenario</th>
            <th style="text-align: left; width: 180px; padding: 12px;">Workload Profile</th>
            <th style="text-align: left; width: 180px; padding: 12px;">SLA Thresholds</th>
            <th style="width: 120px; text-align: center; padding: 12px;">Status</th>
            <th style="width: 100px; text-align: center; padding: 12px;">Action</th>
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
          <span>🖥️ Live Benchmark Console</span>
          <span id="runner-process-status" style="font-size: 11px; background: #f1f5f9; padding: 2px 8px; border-radius: 4px; font-weight: 600; color: var(--text-muted);">Idle</span>
        </h3>
        <button type="button" class="btn btn-secondary" onclick="clearConsole()" style="font-size: 11px; padding: 4px 10px;">Clear Console</button>
      </div>
      <pre id="terminal-box" style="background: #0f172a; color: #f8fafc; font-family: monospace; font-size: 12px; padding: 14px; border-radius: 6px; height: 260px; overflow-y: auto; margin: 0; white-space: pre-wrap; line-height: 1.5;"></pre>
    </div>

    <!-- Reports Section -->
    <div class="card">
      <h3 style="margin: 0 0 12px 0; font-size: 15px; color: var(--text-primary);">📊 Generated Benchmark Reports (Chart.js)</h3>
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
        if (status === 'Running...') {{
          b.className = 'test-status badge';
          b.style.background = '#fef08a';
          b.style.color = '#854d0e';
        }} else if (status === 'Passed' || status === 'Grade: A+' || status === 'Grade: A') {{
          b.className = 'test-status badge';
          b.style.background = '#dcfce7';
          b.style.color = '#166534';
        }} else if (status === 'Failed' || status.includes('Grade: F')) {{
          b.className = 'test-status badge';
          b.style.background = '#fee2e2';
          b.style.color = '#991b1b';
        }} else {{
          b.className = 'test-status badge badge-idle';
        }}
      }}

      function runScenario(scId) {{
        if (activeInterval) {{
          alert('A benchmark is already running.');
          return;
        }}
        const profile = document.getElementById('profile-select').value;
        const term = document.getElementById('terminal-box');
        term.innerText = '>>> Initializing benchmark run: ' + scId + ' (Profile: ' + profile + ')...\\n';
        lastLogIndex = 0;
        document.getElementById('runner-process-status').innerText = 'Running';

        if (scId === 'all') {{
          document.querySelectorAll('.test-status').forEach(b => {{
            b.innerText = 'Queued';
            b.style.background = '#e2e8f0';
            b.style.color = '#475569';
          }});
        }} else {{
          updateStatusBadge(scId, 'Running...');
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
            alert(data.message || 'Could not start benchmark.');
            resetUI();
          }}
        }})
        .catch(err => {{
          alert('Failed to connect to server: ' + err);
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
            document.getElementById('runner-process-status').innerText = 'Completed';
            const success = data.exit_code === 0;

            if (scId === 'all') {{
              document.querySelectorAll('.test-status').forEach(b => {{
                b.innerText = success ? 'Passed' : 'Failed';
                b.style.background = success ? '#dcfce7' : '#fee2e2';
                b.style.color = success ? '#166534' : '#991b1b';
              }});
            }} else if (scId !== 'db_bench') {{
              updateStatusBadge(scId, success ? 'Passed' : 'Failed');
            }}

            term.innerText += '\\n------------------------------------------------------------\\n';
            term.innerText += success ? '🎉 PERFORMANCE RUN FINISHED WITH EXCELLENT STATUS!\\n' : '⚠️ BENCHMARK COMPLETED WITH NOTED THRESHOLDS.\\n';
            term.scrollTop = term.scrollHeight;
          }}
        }})
        .catch(err => {{
          console.error('Error polling performance logs:', err);
        }});
      }}

      function resetUI() {{
        if (activeInterval) {{
          clearInterval(activeInterval);
          activeInterval = null;
        }}
        document.getElementById('runner-process-status').innerText = 'Idle';
      }}
    </script>
    """
    send_html(handler, layout("Performance Test Suite", body_html))


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


def page_view_performance_report(handler):
    """
    Serves a specific generated HTML report file from performance_reports/.
    """
    qs = parse_qs(handler.path.split("?")[-1]) if "?" in handler.path else {}
    name = qs.get("name", [""])[0].strip()

    if not name or ".." in name or "/" in name or "\\" in name:
        send_html(handler, layout("Error", "<div class='card danger'>Invalid report filename.</div>"), status=400)
        return

    target_file = (REPORTS_DIR / name).resolve()
    try:
        target_file.relative_to(REPORTS_DIR)
    except ValueError:
        send_html(handler, layout("Error", "<div class='card danger'>Access denied.</div>"), status=403)
        return

    if not target_file.exists() or not target_file.is_file():
        send_html(handler, layout("Not Found", f"<div class='card danger'>Report {escape(name)} not found.</div>"), status=404)
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
