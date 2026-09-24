import os
import sys
import json
import time
import subprocess
from pathlib import Path
from html import escape
from urllib.parse import parse_qs

from common import layout, send_html, read_post_form

BASE_DIR = Path(__file__).resolve().parent
LOG_FILE_PATH = BASE_DIR / "playwright" / "unittest_progress.log"

current_process = None
current_tc = None
current_log_file = None

TEST_SUITES = [
    {
        "id": "TestCommon",
        "name": "Test Core & DB Migrations",
        "desc": "Verify core database helper functions, schema migrations, and column definitions.",
        "cases": [
            ("test_parse_int_or_none", "Parse integer or None values safely"),
            ("test_safe_return_to", "Clean redirection URLs to prevent open redirects"),
            ("test_fmt_money", "Format floats/ints to standard currency strings"),
            ("test_now_iso", "Get current local timestamp in ISO format"),
            ("test_redirect", "Issue standard HTTP 302 redirect responses")
        ],
        "steps": "1. Initialize SQLite database.<br>2. Run ensure_column helper checks.<br>3. Verify migration script execution on legacy schemas.",
        "expect": "Database structure initializes with correct columns and constraints without errors."
    },
    {
        "id": "TestVendors",
        "name": "Test Vendor Management",
        "desc": "Verify creating buyer and seller vendors, deactivating active vendors, and restoring deactivated records.",
        "cases": [
            ("test_page_vendors_list", "Render vendor grid with basic styling"),
            ("test_page_vendor_form", "Render create/edit vendor forms"),
            ("test_handle_vendor_create_post", "Create vendor records with validation"),
            ("test_handle_vendor_update_post", "Update vendor metadata successfully"),
            ("test_handle_vendor_deactivate_post", "Deactivate vendors safely"),
            ("test_handle_vendor_restore_post", "Restore deactivated vendors")
        ],
        "steps": "1. Insert seller and buyer vendors.<br>2. Submit deactivation status request.<br>3. Submit restoration status request.<br>4. Verify list filtering by status.",
        "expect": "Vendors switch active status states, and listings correctly filter records based on status."
    },
    {
        "id": "TestContracts",
        "name": "Test Contract & Annex Validations",
        "desc": "Verify framework contract creation, contract reference numbers (Work Orders), and annex value constraints.",
        "cases": [
            ("test_page_contracts_list", "Render contract listings with search filters"),
            ("test_page_contract_form", "Render contract forms with selector options"),
            ("test_handle_contract_create_post", "Save new contracts in DB"),
            ("test_handle_contract_update_post", "Edit contract details"),
            ("test_toggle_reference_lock_ajax", "Toggle locking state for reference numbers"),
            ("test_handle_contract_delete_post", "Deactivate contract and mark as deleted"),
            ("test_handle_contract_assign_staff_save_post_error_handling", "Validate multi-row staff allocation saving and error state preservation"),
            ("test_contract_and_annex_values", "Verify value constraint validation rules"),
            ("test_contract_assign_staff_with_leave_and_rates", "Verify staff allocation with paid leave and rate fields"),
            ("test_multi_row_contract_staff_allocation", "Verify multi-row horizontal table staff allocation saving")
        ],
        "steps": "1. Create framework contract with start/end dates.<br>2. Add contract annexes with values.<br>3. Try inserting non-numeric characters in value field.",
        "expect": "Contracts and annexes persist correctly, and invalid currency/number formats are rejected."
    },
    {
        "id": "TestStaff",
        "name": "Test Staff & Employment Period",
        "desc": "Verify staff registration, shift configs, and direct saving of start/end dates to contract_staff table.",
        "cases": [
            ("test_check_no_overlap", "Validate staff dates overlap rules"),
            ("test_page_staff_shifts", "Render staff shifts and custom layouts"),
            ("test_page_staff_list_locked_payroll", "Display locked payroll total for staff"),
            ("test_handle_staff_create_post", "Create staff profiles and save employment dates"),
            ("test_page_staff_form_with_none_values", "Handle edge cases with null constraints"),
            ("test_page_staff_form_payroll", "Render staff edit form with payroll metrics"),
            ("test_handle_staff_update_post", "Update staff profiles and save employment dates directly"),
            ("test_staff_submenu_assign_to_project", "Verify staff submenu project assign link")
        ],
        "steps": "1. Create staff member and check mandatory inputs.<br>2. Verify start/end date columns in contract_staff table.<br>3. Verify update form doesn't override contract links dates.",
        "expect": "Staff record saves successfully with overall employment period dates directly on the main table."
    },
    {
        "id": "TestInvoices",
        "name": "Test Invoices Parsing & Matching",
        "desc": "Verify parsing of XML invoice files, matching buyer/seller parameters, and auto-matching with locked hours.",
        "cases": [
            ("test_normalization", "Standardize names, tax IDs, and metadata"),
            ("test_match_party", "Verify vendor/mst comparison engine"),
            ("test_parse_xml_bytes", "Parse XML invoice file uploads"),
            ("test_handle_new_invoice_post_paste_method", "Process invoice copy-paste input body"),
            ("test_invoice_payroll_reconciliation", "Calculate matching rate and verify variance"),
            ("test_mgs_details_and_button", "Verify matching invoice rows and MGS button"),
            ("test_force_match", "Support manual overriding for mismatching parameters")
        ],
        "steps": "1. Load mock XML invoice template.<br>2. Run invoice parser and matching engine.<br>3. Verify auto-match badge logic based on locked attendance.",
        "expect": "Invoices parse correctly, auto-match returns exact matching framework contracts, and matching rates calculate correctly."
    },
    {
        "id": "TestAttendance",
        "name": "Test Attendance & Log Locks",
        "desc": "Verify daily attendance inputs, monthly log auto-sync, lock/unlock validations, and paid leave conversions.",
        "cases": [
            ("test_parse_attendance_csv", "Load legacy CSV layout"),
            ("test_parse_attendance_csv_new_format", "Load updated CSV layout"),
            ("test_remove_accents", "Standardize Vietnamese diacritics"),
            ("test_parse_dt", "Parse various date format standards"),
            ("test_page_attendance_totals", "Calculate standard, actual and OT days"),
            ("test_monthly_auto_sync_from_daily_logs", "Automatically calculate monthly summary"),
            ("test_attendance_calculations_and_save", "Compute attendance aggregations"),
            ("test_attendance_lock_unlock", "Toggle grid input editing states"),
            ("test_monthly_attendance_calculations_and_save", "Process monthly adjustments"),
            ("test_handle_attendance_import_post_success", "Import daily attendance logs from CSV file"),
            ("test_attendance_clear", "Clear daily logs"),
            ("test_attendance_manual_totals", "Add manual totals for missing days"),
            ("test_page_attendance_acceptance", "Render BBNT acceptance report page"),
            ("test_attendance_acceptance_both_locks_required", "Require both daily and monthly locks for acceptance"),
            ("test_attendance_acceptance_all_contract_staff_must_be_locked", "Require all contract staff locked for acceptance"),
            ("test_attendance_pdf_lock_date_leave_and_amount_consistency", "Verify PDF lock date, leave, and amount consistency"),
            ("test_attendance_acceptance_joining_date_filtering", "Filter acceptance report by staff joining date"),
            ("test_service_fee_calculation_columns_and_rates", "Verify service fee calculation columns and rates")
        ],
        "steps": "1. Log daily attendance hours via grid.<br>2. Sync summary and verify auto-save.<br>3. Submit log lock and verify inputs become read-only.<br>4. Submit unlock request.",
        "expect": "Locks disable attendance input fields, monthly aggregates compute correctly, and unlocking restores editing."
    },
    {
        "id": "TestServerRoutes",
        "name": "Test Server HTTP Routing",
        "desc": "Verify basic page routes rendering and correct HTTP status responses.",
        "cases": [
            ("test_do_GET_routes", "Verify all HTTP GET endpoints render correctly"),
            ("test_do_POST_routes", "Verify POST requests respond with correct redirects/status codes")
        ],
        "steps": "1. Request index, staff, vendors, and contracts pages.<br>2. Verify status code 200.<br>3. Request invalid route and check 404 response.",
        "expect": "All primary routes load successfully, and non-existing pages return standard 404 error."
    },
    {
        "id": "TestNewImprovements",
        "name": "Test New Improvements",
        "desc": "Verify new database enhancements, project assignments regressions, and custom bug fixes coverage.",
        "cases": [
            ("test_attendance_save_cell_ajax_success", "Save daily attendance hours dynamically"),
            ("test_attendance_save_cell_ajax_locked_error", "Block editing locked daily cells"),
            ("test_monthly_payroll_export_csv", "Export monthly attendance summary to CSV")
        ],
        "steps": "1. Verify project assignment constraints.<br>2. Check boundary conditions for null pointers.<br>3. Verify audit logging trigger for changes.",
        "expect": "New database patches run safely, and system records logs for critical modifications."
    },
    {
        "id": "TestReferences",
        "name": "Test Contract References",
        "desc": "Verify managing contract reference numbers and work orders.",
        "cases": [
            ("test_get_months_between", "Generate list of months between two dates"),
            ("test_page_contract_references", "Render reference numbers management table"),
            ("test_page_contract_references_filters", "Filter contract references by company, contract, annex, and month"),
            ("test_handle_save_reference_ajax_success", "Save custom contract reference code"),
            ("test_handle_toggle_mgs_sent_ajax_success", "Toggle sent to MGS checkbox for invoices")
        ],
        "steps": "1. Save contract reference number.<br>2. Check for reference duplicates.<br>3. Verify reference locked states.",
        "expect": "Reference numbers save correctly, and locked states prevent further edits."
    },
    {
        "id": "TestDashboard",
        "name": "Test Dashboard Metrics",
        "desc": "Verify dashboard metrics aggregation, vendor count, and active staff counts.",
        "cases": [
            ("test_page_dashboard_rendering", "Render dashboard charts, metrics, and currency counts"),
            ("test_page_dashboard_filtering_and_payroll_trend", "Verify dashboard filtering and payroll trend metrics")
        ],
        "steps": "1. Compute dashboard statistics.<br>2. Verify active staff count matching.<br>3. Check monthly cost aggregations.",
        "expect": "Dashboard calculations match database rows, and totals aggregate correctly."
    },
    {
        "id": "TestAnnexFilters",
        "name": "Test Annex Filtering",
        "desc": "Verify filtering and displaying annexes by contract status.",
        "cases": [
            ("test_annex_filter_handling", "Filter staff list and attendance grid by annex selection"),
            ("test_monthly_multiselect_filters", "Verify multi-select month filtering")
        ],
        "steps": "1. Filter annexes by contract.<br>2. Toggle contract status.<br>3. Verify annex list visibility.",
        "expect": "Annex list is updated dynamically based on selected contract status."
    },
    {
        "id": "TestDashboardAndReferencesImprovements",
        "name": "Test Dashboard Improvements",
        "desc": "Verify custom dashboard updates, reference locks, and invoice auto-calculations.",
        "cases": [
            ("test_dashboard_active_staff_filtering", "Verify unique staff filtering on dashboard metrics"),
            ("test_reference_numbers_highlight_sent_mgs", "Highlight months with invoices sent to MGS"),
            ("test_dashboard_annex_alert", "Generate warnings for annexes expiring within 30 days")
        ],
        "steps": "1. Verify dashboard layout metrics.<br>2. Toggle reference lock status.<br>3. Run invoice calculation checks.",
        "expect": "Metrics align with DB updates, and calculations match expected results."
    },
    {
        "id": "TestProjects",
        "name": "Test Project Assignments",
        "desc": "Verify project creation, closing, and monthly assignments matrix validations.",
        "cases": [
            ("test_page_projects_list", "Render project listings with outsourcing budget"),
            ("test_handle_project_create_post", "Create projects with validation"),
            ("test_handle_project_delete_post", "Deactivate project record"),
            ("test_staff_assignments_logic", "Prevent overlapping project assignments"),
            ("test_staff_assignments_multi_month", "Verify assignment across multiple months"),
            ("test_page_project_edit_payroll", "Render project edit page with payroll metrics"),
            ("test_locked_payroll_payment_matrix", "Verify locked payroll payment matrix in project details"),
            ("test_projects_assign_export_csv", "Export project staff assignments to CSV"),
            ("test_inactive_staff_in_projects_and_attendance", "Include inactive staff in project matrix and attendance reports")
        ],
        "steps": "1. Create project with budget and dates.<br>2. Assign staff to project.<br>3. Toggle project assignment check box.<br>4. Close project and check assignment read-only state.",
        "expect": "Project assignments persist correctly, and closed projects reject new staff assignments."
    }
]

def page_unittest_runner(handler):
    """
    Renders the Unit Test Runner Dashboard interface.
    """
    rows_html = []
    for tc in TEST_SUITES:
        # Build individual test cases HTML
        cases_html = []
        for index, case in enumerate(tc["cases"], 1):
            cases_html.append(f"""
            <div style="margin-bottom: 8px; font-size: 12px; border-bottom: 1px dashed #f1f5f9; padding-bottom: 4px;">
              <span style="font-family: monospace; font-weight: 600; color: #0f766e;">{index}. {case[0]}</span>
              <div style="color: var(--text-muted); padding-left: 14px; font-style: italic; margin-top: 1px;">{escape(case[1])}</div>
            </div>
            """)

        rows_html.append(f"""
        <tr id="tc-row-{tc['id']}">
          <td style="text-align: left; font-weight: bold; padding-left: 12px; font-family: monospace; color: var(--text-secondary); vertical-align: top; padding-top: 12px;">{tc['id']}</td>
          <td style="vertical-align: top; padding-top: 12px;">
            <div style="font-weight: 600; color: var(--primary);">{escape(tc['name'])}</div>
            <div style="font-size: 12px; color: var(--text-muted); margin-top: 3px;">{escape(tc['desc'])}</div>
          </td>
          <td style="vertical-align: top; padding-top: 12px;">
            <div style="max-height: 250px; overflow-y: auto; padding-right: 4px;">
              {"".join(cases_html)}
            </div>
          </td>
          <td style="font-size: 12px; color: var(--text-secondary); line-height: 1.5; vertical-align: top; padding-top: 12px;">{tc['steps']}</td>
          <td style="font-size: 13px; color: var(--text-secondary); vertical-align: top; padding-top: 12px;">{escape(tc['expect'])}</td>
          <td style="text-align: center; vertical-align: top; padding-top: 12px;">
            <span class="test-status badge badge-idle" id="status-{tc['id']}">Ready</span>
          </td>
          <td style="text-align: center; vertical-align: top; padding-top: 12px;">
            <button type="button" class="btn btn-run" onclick="runTestCase('{tc['id']}')" style="font-size: 12px; padding: 6px 12px;">Run</button>
          </td>
        </tr>
        """)

    body_html = f"""
    <div style="margin-bottom: 24px; display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 16px;">
      <div>
        <h2 style="margin: 0 0 6px 0; color: var(--text-primary);">Unit Test Runner Dashboard</h2>
        <p style="margin: 0; color: var(--text-muted); font-size: 14px;">Verify server database operations, validations, and logic handlers using Python unittest (80 test cases total).</p>
      </div>
      <div style="display: flex; gap: 10px;">
        <button type="button" id="btn-run-all" class="btn" style="background: var(--success); color:#fff; border-color: var(--success); font-weight: 600;" onclick="runTestCase('all')">
          ▶ Run All Unit Tests
        </button>
        <button type="button" id="btn-clear-terminal" class="btn btn-secondary" onclick="clearConsole()">
          Clear Console
        </button>
      </div>
    </div>

    <!-- Test Cases Table -->
    <div class="card" style="padding: 0; overflow: hidden;">
      <table style="width:100%; border-collapse: collapse; margin:0; border:none;">
        <thead>
          <tr style="background: #f8fafc; border-bottom: 1px solid var(--border);">
            <th style="width: 140px; text-align: left; padding-left: 12px;">Class Name</th>
            <th style="text-align: left; width: 180px;">Test Suite</th>
            <th style="text-align: left; width: 280px;">Chi tiết 61 Test Cases (Test Methods)</th>
            <th style="text-align: left; width: 260px;">Trình tự thực hiện (Execution Steps)</th>
            <th style="text-align: left; width: 180px;">Expected Result</th>
            <th style="width: 100px; text-align: center;">Status</th>
            <th style="width: 80px; text-align: center;">Action</th>
          </tr>
        </thead>
        <tbody>
          {"".join(rows_html)}
        </tbody>
      </table>
    </div>

    <!-- Live Console Output -->
    <div style="margin-top: 24px;">
      <div style="font-weight: 600; font-size: 14px; margin-bottom: 8px; display: flex; align-items: center; justify-content: space-between;">
        <span>Terminal Output (Real-time logs)</span>
        <span id="runner-process-status" style="font-weight: normal; font-size: 12px; color: var(--text-muted);">Idle</span>
      </div>
      <div id="terminal-box" style="background: #0f172a; color: #38bdf8; font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, Courier, monospace; font-size: 13px; line-height: 1.6; padding: 16px; border-radius: 12px; height: 350px; overflow-y: auto; border: 1px solid #1e293b; box-shadow: var(--shadow-md); white-space: pre-wrap; word-break: break-all;">No active logs. Click "Run" to start a test.</div>
    </div>

    <style>
      .badge {{
        display: inline-block;
        padding: 4px 10px;
        border-radius: 999px;
        font-size: 11px;
        font-weight: 600;
        border: 1px solid transparent;
      }}
      .badge-idle {{
        background: #f1f5f9;
        border-color: #cbd5e1;
        color: #475569;
      }}
      .badge-running {{
        background: #eff6ff;
        border-color: #bfdbfe;
        color: #1d4ed8;
        animation: blinker 1.5s linear infinite;
      }}
      .badge-passed {{
        background: #f0fdf4;
        border-color: #bbf7d0;
        color: #15803d;
      }}
      .badge-failed {{
        background: #fef2f2;
        border-color: #fca5a5;
        color: #b91c1c;
      }}
      .btn-run {{
        background: #fff;
        color: var(--primary);
        border-color: var(--primary);
      }}
      .btn-run:hover {{
        background: var(--primary);
        color: #fff;
      }}
      @keyframes blinker {{
        50% {{ opacity: 0.5; }}
      }}
    </style>

    <script>
      let activeInterval = null;
      let lastLogIndex = 0;

      function updateStatusBadge(id, statusText) {{
        const badge = document.getElementById('status-' + id);
        if (!badge) return;
        badge.className = 'test-status badge badge-' + statusText.toLowerCase();
        badge.innerText = statusText;
      }}

      function clearConsole() {{
        document.getElementById('terminal-box').innerText = '';
      }}

      function runTestCase(tcId) {{
        if (activeInterval) {{
          alert('Another test run is currently running. Please wait for it to complete!');
          return;
        }}

        clearConsole();
        document.getElementById('terminal-box').innerText = 'Initializing Python unit test runner...\\n';
        document.getElementById('runner-process-status').innerText = 'Starting...';

        // Update UI status badges
        if (tcId === 'all') {{
          document.querySelectorAll('.test-status').forEach(b => {{
            b.className = 'test-status badge badge-running';
            b.innerText = 'Running';
          }});
        }} else {{
          document.querySelectorAll('.test-status').forEach(b => {{
            const id = b.id.replace('status-', '');
            if (id === tcId) {{
              b.className = 'test-status badge badge-running';
              b.innerText = 'Running';
            }} else {{
              b.className = 'test-status badge badge-idle';
              b.innerText = 'Ready';
            }}
          }});
        }}

        // Call API to run test
        fetch('/api/unit-tests/run', {{
          method: 'POST',
          headers: {{
            'Content-Type': 'application/x-www-form-urlencoded',
          }},
          body: 'tc=' + encodeURIComponent(tcId)
        }})
        .then(res => res.json())
        .then(data => {{
          if (data.status === 'ok') {{
            lastLogIndex = 0;
            document.getElementById('runner-process-status').innerText = 'Testing...';
            activeInterval = setInterval(() => pollLog(tcId), 200);
          }} else {{
            alert(data.message || 'Could not start test runner.');
            resetRunnerUI();
          }}
        }})
        .catch(err => {{
          alert('Cannot connect to server: ' + err);
          resetRunnerUI();
        }});
      }}

      function pollLog(tcId) {{
        fetch('/api/unit-tests/log?offset=' + lastLogIndex)
        .then(res => res.json())
        .then(data => {{
          const term = document.getElementById('terminal-box');
          
          if (data.log) {{
            term.innerText += data.log;
            term.scrollTop = term.scrollHeight;
          }}
          
          if (data.status === 'done') {{
            clearInterval(activeInterval);
            activeInterval = null;
            document.getElementById('runner-process-status').innerText = 'Completed';
            
            const success = data.exit_code === 0;
            if (tcId === 'all') {{
              document.querySelectorAll('.test-status').forEach(b => {{
                b.className = success ? 'test-status badge badge-passed' : 'test-status badge badge-failed';
                b.innerText = success ? 'Passed' : 'Failed';
              }});
            }} else {{
              updateStatusBadge(tcId, success ? 'Passed' : 'Failed');
              document.querySelectorAll('.test-status').forEach(b => {{
                const id = b.id.replace('status-', '');
                if (id !== tcId) {{
                  b.className = 'test-status badge badge-idle';
                  b.innerText = 'Ready';
                }}
              }});
            }}
            
            term.innerText += '\\n------------------------------------------------------------\\n';
            term.innerText += success ? '🎉 UNIT TESTS COMPLETED SUCCESSFULLY!\\n' : '❌ UNIT TESTS FAILED!\\n';
            term.scrollTop = term.scrollHeight;
          }}
        }})
        .catch(err => {{
          console.error('Error polling logs:', err);
        }});
      }}

      function resetRunnerUI() {{
        if (activeInterval) {{
          clearInterval(activeInterval);
          activeInterval = null;
        }}
        document.getElementById('runner-process-status').innerText = 'Idle';
        document.querySelectorAll('.test-status').forEach(b => {{
          b.className = 'test-status badge badge-idle';
          b.innerText = 'Ready';
        }});
      }}
    </script>
    """
    send_html(handler, layout("Unit Test Runner", body_html))

def handle_run_unittests_post(handler):
    """
    Handles POST requests to trigger Python unittest.
    """
    global current_process, current_tc, current_log_file
    
    if current_process and current_process.poll() is None:
        send_json(handler, {"status": "error", "message": "A test process is already running."}, status=400)
        return

    form = read_post_form(handler)
    tc = (form.get("tc", ["all"])[0] or "").strip()
    
    # Empty progress log file
    LOG_FILE_PATH.parent.mkdir(exist_ok=True)
    with open(LOG_FILE_PATH, "w") as f:
        f.write("=== Unit Test Runner Init ===\n")
        f.write(f"Test Suite: {tc}\n")
        f.write(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("====================================\n\n")

    # Construct execution command
    args = [sys.executable, "-m", "unittest"]
    if tc != "all":
        args += [f"test_app.{tc}"]
    else:
        args += ["test_app.py"]

    try:
        current_log_file = open(LOG_FILE_PATH, "a", buffering=1)
        current_process = subprocess.Popen(
            args,
            env=dict(os.environ),
            stdout=current_log_file,
            stderr=subprocess.STDOUT,
            close_fds=True
        )
        current_tc = tc
        send_json(handler, {"status": "ok", "message": "Unit tests started."})
    except Exception as e:
        if current_log_file:
            current_log_file.close()
            current_log_file = None
        send_json(handler, {"status": "error", "message": f"Could not launch process: {str(e)}"}, status=500)

def handle_get_unittest_log(handler):
    """
    Returns the accumulated log content and running status.
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
            with open(LOG_FILE_PATH, "r") as f:
                log_content = f.read()
        except Exception:
            pass

    qs = parse_qs(handler.path.split("?")[-1]) if "?" in handler.path else {}
    offset_raw = qs.get("offset", ["0"])[0]
    offset = int(offset_raw) if offset_raw.isdigit() else 0
    
    sliced_log = log_content[offset:]
    
    response_data = {
        "status": status,
        "exit_code": exit_code,
        "log": sliced_log,
        "next_offset": len(log_content)
    }
    
    send_json(handler, response_data)

def send_json(handler, data: dict, status=200):
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    encoded = json.dumps(data).encode("utf-8")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.end_headers()
    handler.wfile.write(encoded)
