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
PLAYWRIGHT_DIR = BASE_DIR / "playwright"
LOG_FILE_PATH = PLAYWRIGHT_DIR / "run_progress.log"

# Global state to keep track of the running test process
current_process = None
current_tc = None # "all" or "1".."7"

TEST_CASES = [
    {
        "id": "1",
        "name": "Dashboard & Menu Navigation",
        "desc": "Verify core page rendering and routing functionality across Invoices, Vendors, Contracts, Staff, Attendance, and Audit Logs tabs.",
        "steps": "1. Mở trang chủ (/) và kiểm tra tiêu đề.<br>2. Vào tab Vendors kiểm tra bộ lọc.<br>3. Vào tab Contracts kiểm tra nút thêm mới.<br>4. Vào tab Staff kiểm tra nút thêm mới.<br>5. Vào tab Attendance kiểm tra nút import.<br>6. Vào tab Invoices kiểm tra nút import.<br>7. Vào tab Audit Logs kiểm tra ô tìm kiếm.",
        "expect": "Pages load successfully with HTTP status 200, and primary UI navigation works without errors."
    },
    {
        "id": "2",
        "name": "Create a Staff Member",
        "desc": "Create a new mock staff member 'Nguyen UAT Tester' belonging to vendor FPT Software.",
        "steps": "1. Vào trang thêm nhân viên mới (/staff/new).<br>2. Nhập thông tin cho 'Nguyen UAT Tester' thuộc Vendor FPT Software.<br>3. Submit form để lưu thông tin.<br>4. Xác nhận nhân sự mới hiển thị tại danh sách HR.",
        "expect": "Submission succeeds and the new staff appears instantly in the system's HR database list."
    },
    {
        "id": "3",
        "name": "Create Contract, Annex, and Allocate Staff",
        "desc": "Set up a framework contract, create a linked annex, and allocate Nguyen UAT Tester to the annex with monthly rate.",
        "steps": "1. Tạo hợp đồng khung 'MHB/FPT/UAT/001' hiệu lực năm 2026.<br>2. Tạo phụ lục 'Annex UAT 2026-A' (01/01 -> 30/06).<br>3. Phân bổ 'Nguyen UAT Tester' vào phụ lục này với đơn giá 55 triệu/tháng.<br>4. Xác minh thông tin phân bổ hiển thị trong chi tiết hợp đồng.",
        "expect": "All entities link correctly in DB, and the contract overview shows active staff allocation details."
    },
    {
        "id": "4",
        "name": "Project Assignment Matrix",
        "desc": "Assign staff to project 'DOM_EUC' for months 2026-01 and 2026-02, and test matrix checkbox AJAX toggle interaction.",
        "steps": "1. Mở trang gán dự án DOM_EUC.<br>2. Chọn nhân sự 'Nguyen UAT Tester' gán vào tháng 01 và 02 năm 2026.<br>3. Mở trang sửa nhân sự, bỏ tích checkbox tháng 01 để test AJAX toggle.<br>4. Tích chọn lại checkbox tháng 01 để phục hồi phân bổ.",
        "expect": "Project assignments persist in database, and unchecking/checking matrix rows updates immediately via AJAX."
    },
    {
        "id": "5",
        "name": "Daily Attendance Logging & Lock",
        "desc": "Record daily attendance (8.0 hours) for the staff on 2026-01-01 and perform a monthly log lock operation.",
        "steps": "1. Mở bảng chấm công tháng 2026-01.<br>2. Nhập 8.0 giờ làm việc vào ô ngày 2026-01-01.<br>3. Nhấn Tab để tự động lưu qua AJAX.<br>4. Nhấn nút Lock để khóa chấm công tháng.<br>5. Xác minh ô chấm công bị vô hiệu hóa (disabled).",
        "expect": "Daily hours auto-save via AJAX database calls, and locking success disables further edits (fields become read-only)."
    },
    {
        "id": "6",
        "name": "Contract Reference Numbers Management",
        "desc": "Enter a Work Order / Reference Number 'WO-UAT-9999' for the contract month 2026-01.",
        "steps": "1. Vào trang quản lý mã Work Order / Reference.<br>2. Điền mã 'WO-UAT-9999' cho Hợp đồng 1 vào tháng 2026-01.<br>3. Nhấn Tab để tự động lưu vào DB.",
        "expect": "Reference number is successfully saved and correctly linked to the contract allocation cycle."
    },
    {
        "id": "7",
        "name": "XML Invoice Upload & Match",
        "desc": "Upload a mock XML invoice file matching framework contract parameters and locked attendance hours calculation.",
        "steps": "1. Vào trang thêm hoá đơn mới.<br>2. Upload file XML mock_invoice.xml (khớp số giờ 8.0 và đơn giá 55 triệu).<br>3. Click Import Invoice và kiểm tra kết quả.<br>4. Quay lại danh sách hoá đơn, xác nhận nhãn '✓ Match' xuất hiện.",
        "expect": "System matches invoice against stored attendance hours and renders the '✓ Match' badge status."
    },
    {
        "id": "8",
        "name": "Create a Vendor (Seller)",
        "desc": "Create a new vendor 'FPT Software 2' (short name: FPT2, purchasing: No) and verify creation.",
        "steps": "1. Vào trang tạo Vendor (/vendor/new).<br>2. Điền tên 'FPT Software 2', MST và chọn loại Seller (purchasing=0).<br>3. Click tạo mới và xác nhận Vendor xuất hiện trong danh sách.",
        "expect": "New seller vendor is saved and appears correctly in the vendor listings."
    },
    {
        "id": "9",
        "name": "Create a Vendor (Buyer)",
        "desc": "Create a new buyer vendor 'Mizuho Bank 2' (short name: Mizuho2, purchasing: Yes) and verify creation.",
        "steps": "1. Vào trang tạo Vendor (/vendor/new).<br>2. Điền tên 'Mizuho Bank 2', MST và chọn loại Buyer (purchasing=1).<br>3. Click tạo mới và xác nhận Vendor xuất hiện trong danh sách.",
        "expect": "New buyer vendor is saved and appears correctly in the vendor listings."
    },
    {
        "id": "10",
        "name": "Vendor Deactivation & Restoration",
        "desc": "Deactivate 'Mizuho Bank 2' from its edit page, filter by inactive status, and restore it.",
        "steps": "1. Tìm 'Mizuho Bank 2' trong danh sách, click Deactive.<br>2. Lọc danh sách theo status=deactive, xác nhận vendor hiển thị ở danh sách ẩn.<br>3. Click Restore để khôi phục hoạt động.<br>4. Xác nhận vendor quay lại danh sách hoạt động chính.",
        "expect": "Vendor switches status from active to inactive and restores back successfully."
    },
    {
        "id": "11",
        "name": "Edit Staff Information",
        "desc": "Update position description of 'Nguyen UAT Tester' to 'Principal QA Automator'.",
        "steps": "1. Mở trang sửa thông tin nhân sự Nguyen UAT Tester.<br>2. Đổi chức danh thành 'Principal QA Automator' và click Save.<br>3. Quay về danh sách nhân sự, kiểm tra chức danh mới đã được cập nhật.",
        "expect": "Updates are saved, and the staff list reflects the new position instantly."
    },
    {
        "id": "12",
        "name": "Staff Deactivation & Filter",
        "desc": "Create a temporary staff, deactivate them to inactive status, and check list filters.",
        "steps": "1. Tạo nhân viên tạm thời 'Staff to Deactivate'.<br>2. Click sửa nhân sự, đổi status thành 'inactive' và click Save.<br>3. Xác nhận nhân viên biến mất khỏi danh sách active và xuất hiện tại danh sách inactive.<br>4. Click sửa và đổi status thành active, đồng thời phân bổ vào Hợp đồng 1.",
        "expect": "Staff is removed from active list and appears under the Inactive filter."
    },
    {
        "id": "13",
        "name": "Search & Filter Staff",
        "desc": "Use keyword 'Principal' to filter the staff list to find the matching employee.",
        "steps": "1. Vào trang danh sách nhân sự.<br>2. Tìm kiếm với từ khoá 'Principal'.<br>3. Xác nhận chỉ hiển thị 'Nguyen UAT Tester' (Principal QA Automator), các nhân sự khác bị loại trừ.",
        "expect": "Staff list displays Nguyen UAT Tester and excludes other non-matching records."
    },
    {
        "id": "14",
        "name": "Contract Edit & Update",
        "desc": "Edit framework contract 'MHB/FPT/UAT/001' to update its end date to '2026-11-30'.",
        "steps": "1. Sửa hợp đồng khung ID=1.<br>2. Đổi ngày kết thúc thành '2026-11-30' và click Save.<br>3. Truy cập lại trang sửa, xác nhận ngày kết thúc mới được hiển thị đúng.",
        "expect": "Modified end date is stored successfully and displays correctly upon reloading the edit form."
    },
    {
        "id": "15",
        "name": "Contract Deactivation & Restoration",
        "desc": "Deactivate framework contract 'MHB/FPT/UAT/001' and then restore it back to active.",
        "steps": "1. Click nút Delete (hủy hoạt động) hợp đồng MHB/FPT/UAT/001.<br>2. Chuyển sang lọc danh sách đã xóa, xác nhận hợp đồng hiển thị tại đây.<br>3. Click Restore hợp đồng.<br>4. Xác nhận hợp đồng quay lại danh sách hoạt động.",
        "expect": "Contract updates is_active flag in DB, showing under inactive filter, and returns to active successfully."
    },
    {
        "id": "16",
        "name": "Create Annex with Value",
        "desc": "Create a new contract annex 'Annex UAT 2026-B' with a value of '150,000,000 VND'.",
        "steps": "1. Vào trang thêm phụ lục mới cho hợp đồng 1.<br>2. Điền tên 'Annex UAT 2026-B', hiệu lực nửa cuối 2026, giá trị '150000000' (không chứa dấu phẩy) và submit.<br>3. Xác nhận phụ lục mới hiển thị tại danh sách phụ lục.",
        "expect": "Annex is created successfully under contract 1 and shows up in the annex details list."
    },
    {
        "id": "17",
        "name": "Annex Deactivation & Restoration",
        "desc": "Deactivate 'Annex UAT 2026-B' and then restore it on the contract overview page.",
        "steps": "1. Vào trang sửa hợp đồng 1, click Delete phụ lục Annex UAT 2026-B.<br>2. Xác nhận phụ lục bị gạch bỏ / chuyển trạng thái.<br>3. Click Restore phụ lục ngay tại bảng.<br>4. Xác nhận phụ lục khôi phục hoạt động bình thường.",
        "expect": "Annex status switches between active/inactive, showing the correct inline restore/deactivate actions."
    },
    {
        "id": "18",
        "name": "Staff Allocation Overlap Validation",
        "desc": "Attempt to allocate Nguyen UAT Tester to Annex B with dates that overlap with their Annex A allocation.",
        "steps": "1. Phân bổ 'Nguyen UAT Tester' vào phụ lục B mới tạo.<br>2. Chọn ngày bắt đầu 2026-01-15 đến 2026-03-31 (trùng khoảng thời gian Annex A).<br>3. Gửi biểu mẫu, xác nhận hệ thống từ chối và báo lỗi 'overlap'.",
        "expect": "System rejects the allocation and renders a clear validation error about overlapping allocation dates."
    },
    {
        "id": "19",
        "name": "Staff Allocation Rates Update",
        "desc": "Edit staff contract link monthly rate to '60,000,000 VND'.",
        "steps": "1. Vào trang sửa phân bổ của Nguyen UAT Tester.<br>2. Cập nhật đơn giá tháng thành '60,000,000 VND' và click Save.<br>3. Xác nhận đơn giá mới hiển thị định dạng chuẩn tại chi tiết hợp đồng.",
        "expect": "Updated monthly rate persists in database and displays in formatting on contract edit page."
    },
    {
        "id": "20",
        "name": "Remove Staff Allocation",
        "desc": "Create a temporary staff allocation to Annex A, and click Remove to delete it.",
        "steps": "1. Tạo nhân sự 'Staff to Remove Alloc'.<br>2. Phân bổ nhân sự này vào Hợp đồng 1, Phụ lục 1.<br>3. Vào chi tiết hợp đồng, tìm dòng phân bổ và click Remove.<br>4. Xác nhận nhân sự bị xóa hoàn toàn khỏi danh sách phân bổ hợp đồng.",
        "expect": "Allocation link is deleted, and the staff no longer appears as allocated under the contract."
    },
    {
        "id": "21",
        "name": "Create a Project",
        "desc": "Create a new project 'UAT_PROJ' (UAT Test Project) with budget and active dates.",
        "steps": "1. Vào trang danh sách dự án (/projects).<br>2. Điền thông tin 'UAT_PROJ' với ngân sách 500 triệu, hiệu lực năm 2026.<br>3. Click submit tạo mới và xác nhận dự án xuất hiện trong danh sách.",
        "expect": "Project is created, showing up in project lists and available for staff assignments."
    },
    {
        "id": "22",
        "name": "Project Close & Reopen",
        "desc": "Close the project 'UAT_PROJ' and reopen it back from the project listings page.",
        "steps": "1. Tìm dự án 'UAT_PROJ' trong danh sách, click Close để đóng dự án.<br>2. Click Reopen dự án trên chính dòng đó.<br>3. Xác nhận dự án khôi phục hoạt động bình thường.",
        "expect": "Project status changes successfully from open to closed and vice versa."
    },
    {
        "id": "23",
        "name": "Assign Staff via Dropdown",
        "desc": "Assign 'Temp QA' to project 'DOM_EUC' for month 2026-01 using the project assign page dropdown.",
        "steps": "1. Vào trang gán dự án, chọn dự án DOM_EUC.<br>2. Chọn nhân viên 'Staff to Deactivate' (ID=2), chọn tháng 2026-01 và click Add.<br>3. Xác nhận nhân viên được gán vào dự án và xuất hiện trong ma trận.",
        "expect": "Temp QA is added to project assignments and appears in the monthly matrix."
    },
    {
        "id": "24",
        "name": "Unassign Staff via Matrix",
        "desc": "Go to Temp QA details and uncheck their assignment matrix checkbox for month 2026-01.",
        "steps": "1. Vào trang sửa nhân sự Staff to Deactivate (ID=2).<br>2. Bỏ tích checkbox dự án DOM_EUC tháng 2026-01 để hủy gán.<br>3. Đợi trang tự động tải lại, xác nhận dự án biến mất khỏi bảng ma trận của nhân sự.",
        "expect": "Checkbox is unchecked, and assignment record is deleted from DB via AJAX."
    },
    {
        "id": "25",
        "name": "Attendance Log Cell Validation",
        "desc": "Input non-numeric characters ('invalid_hours') into the daily attendance grid.",
        "steps": "1. Vào bảng chấm công tháng 2026-02.<br>2. Sử dụng JS để cưỡng ép nhập giá trị chữ 'invalid_hours' vào ô chấm công.<br>3. Xác nhận ô chấm công tự động từ chối giá trị chữ không hợp lệ này.",
        "expect": "Invalid input triggers verification warning, and input restores to its previous valid numeric state."
    },
    {
        "id": "26",
        "name": "Unlock Attendance Log",
        "desc": "Perform an unlock operation on the locked attendance logs of Nguyen UAT Tester for 2026-01.",
        "steps": "1. Vào bảng chấm công tháng 2026-01 (đang bị khóa ở UAT 5).<br>2. Click nút Unlock để mở khóa tháng.<br>3. Xác nhận các ô chấm công của Nguyen UAT Tester trở lại trạng thái editable (không còn disabled).",
        "expect": "Log status changes to unlocked, and daily grid inputs become editable (disabled attributes removed)."
    },
    {
        "id": "27",
        "name": "Audit Logs Search & Verification",
        "desc": "Access Audit Logs dashboard and query action logs using the keyword 'CREATE_STAFF'.",
        "steps": "1. Vào trang nhật ký hệ thống (/audit-logs).<br>2. Nhập từ khoá 'Nguyen UAT Tester' vào ô tìm kiếm.<br>3. Xác nhận bảng lịch sử hiển thị đúng log ghi nhận hành động tạo nhân sự (CREATE_STAFF).",
        "expect": "Audit Log table returns matching history records, including details of the 'Nguyen UAT Tester' creation."
    }
]

def page_playwright_runner(handler):
    """
    Renders the Playwright Test Runner Dashboard interface.
    """
    rows_html = []
    for tc in TEST_CASES:
        rows_html.append(f"""
        <tr id="tc-row-{tc['id']}">
          <td style="text-align: center; font-weight: bold; color: var(--text-secondary);">{tc['id']}</td>
          <td>
            <div style="font-weight: 600; color: var(--primary);">{escape(tc['name'])}</div>
            <div style="font-size: 12px; color: var(--text-muted); margin-top: 3px;">{escape(tc['desc'])}</div>
          </td>
          <td style="font-size: 12px; color: var(--text-secondary); line-height: 1.5;">{tc['steps']}</td>
          <td style="font-size: 13px; color: var(--text-secondary);">{escape(tc['expect'])}</td>
          <td style="text-align: center;">
            <span class="test-status badge badge-idle" id="status-{tc['id']}">Ready</span>
          </td>
          <td style="text-align: center;">
            <button type="button" class="btn btn-run" onclick="runTestCase('{tc['id']}')" style="font-size: 12px; padding: 6px 12px;">Run</button>
          </td>
        </tr>
        """)

    body_html = f"""
    <div style="margin-bottom: 24px; display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 16px;">
      <div>
        <h2 style="margin: 0 0 6px 0; color: var(--text-primary);">Playwright UAT Test Runner</h2>
        <p style="margin: 0; color: var(--text-muted); font-size: 14px;">Verify system workflow automation and UI integrity using Playwright integration.</p>
      </div>
      <div style="display: flex; gap: 10px;">
        <button type="button" id="btn-run-all" class="btn" style="background: var(--success); color:#fff; border-color: var(--success); font-weight: 600;" onclick="runTestCase('all')">
          ▶ Run All Scenarios (Headed)
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
            <th style="width: 60px; text-align: center;">ID</th>
            <th style="text-align: left; width: 200px;">UAT Scenario</th>
            <th style="text-align: left; width: 380px;">Trình tự thực hiện (Execution Steps)</th>
            <th style="text-align: left; width: 200px;">Expected Result</th>
            <th style="width: 120px; text-align: center;">Status</th>
            <th style="width: 100px; text-align: center;">Action</th>
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
          alert('Another test scenario is currently running. Please wait for it to complete!');
          return;
        }}

        clearConsole();
        document.getElementById('terminal-box').innerText = 'Initializing environment and starting test...\\n';
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
        fetch('/api/tests/run', {{
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
            document.getElementById('runner-process-status').innerText = 'Testing (Headed Chromium active)';
            activeInterval = setInterval(() => pollLog(tcId), 500);
          }} else {{
            alert(data.message || 'Could not start test scenario.');
            resetRunnerUI();
          }}
        }})
        .catch(err => {{
          alert('Cannot connect to server: ' + err);
          resetRunnerUI();
        }});
      }}

      function pollLog(tcId) {{
        fetch('/api/tests/log?offset=' + lastLogIndex)
        .then(res => res.json())
        .then(data => {{
          const term = document.getElementById('terminal-box');
          
          if (data.log) {{
            term.innerText += data.log;
            term.scrollTop = term.scrollHeight; // Auto scroll
          }}
          
          if (data.status === 'done') {{
            clearInterval(activeInterval);
            activeInterval = null;
            document.getElementById('runner-process-status').innerText = 'Completed';
            
            // Mark results
            const success = data.exit_code === 0;
            if (tcId === 'all') {{
              document.querySelectorAll('.test-status').forEach(b => {{
                b.className = success ? 'test-status badge badge-passed' : 'test-status badge badge-failed';
                b.innerText = success ? 'Passed' : 'Failed';
              }});
            }} else {{
              updateStatusBadge(tcId, success ? 'Passed' : 'Failed');
              // Set others back to ready
              document.querySelectorAll('.test-status').forEach(b => {{
                const id = b.id.replace('status-', '');
                if (id !== tcId) {{
                  b.className = 'test-status badge badge-idle';
                  b.innerText = 'Ready';
                }}
              }});
            }}
            
            term.innerText += '\\n------------------------------------------------------------\\n';
            term.innerText += success ? '🎉 TEST SCENARIO SUCCESSFUL!\\n' : '❌ TEST SCENARIO FAILED!\\n';
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
    send_html(handler, layout("Playwright Test Runner", body_html))

def send_json(handler, data: dict, status=200):
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    encoded = json.dumps(data).encode("utf-8")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.end_headers()
    handler.wfile.write(encoded)

def handle_run_tests_post(handler):
    """
    Handles POST requests to trigger Playwright subprocess.
    """
    global current_process, current_tc
    
    if current_process and current_process.poll() is None:
        send_json(handler, {"status": "error", "message": "A test process is already running."}, status=400)
        return

    form = read_post_form(handler)
    tc = (form.get("tc", ["all"])[0] or "").strip()
    
    # Empty progress log file
    PLAYWRIGHT_DIR.mkdir(exist_ok=True)
    with open(LOG_FILE_PATH, "w") as f:
        f.write("=== Playwright Test Runner Init ===\n")
        f.write(f"Scenario: {tc}\n")
        f.write(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("====================================\n\n")

    # Construct execution command
    # Base command uses current python executable to run run_tests.py with --headed and --log-to-file
    args = [sys.executable, str(PLAYWRIGHT_DIR / "run_tests.py"), "--headed", "--log-to-file"]
    if tc != "all":
        args += ["--tc", tc]

    try:
        # Launch subprocess asynchronously
        # close_fds=True prevents leaking HTTP socket file descriptors to the child process (fixes Failed to fetch)
        current_process = subprocess.Popen(
            args,
            env=dict(os.environ),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True
        )
        current_tc = tc
        send_json(handler, {"status": "ok", "message": "Test process started."})
    except Exception as e:
        send_json(handler, {"status": "error", "message": f"Could not launch process: {str(e)}"}, status=500)

def handle_get_test_log(handler):
    """
    Returns the accumulated log content and the current process running status.
    """
    global current_process
    
    status = "idle"
    exit_code = None
    
    if current_process:
        poll_res = current_process.poll()
        if poll_res is None:
            status = "running"
        else:
            status = "done"
            exit_code = poll_res
            current_process = None # Reset
            
    # Read log file content
    log_content = ""
    if LOG_FILE_PATH.exists():
        try:
            with open(LOG_FILE_PATH, "r") as f:
                log_content = f.read()
        except Exception:
            pass

    # Support offset polling if required
    # But for http.server, returning the whole log content is simple and safe enough
    # If the user client JS sends offset, we can slice it
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
