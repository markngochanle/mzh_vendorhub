# attendance.py
import calendar
import csv
import io
import sqlite3
import unicodedata
import urllib.parse
from datetime import datetime, date
from html import escape
from pathlib import Path

from common import (
    db_connect, layout, parse_int_or_none, fmt_money,
    send_html, redirect, safe_return_to
)

# -------------------- Normalization --------------------
import re

def remove_accents(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "D")
    return s.casefold()


def clean_name_from_csv(name: str) -> str:
    name = name.strip()
    # digits(name) ví dụ: "378(Can Duy Hung)"
    m1 = re.match(r'^\d+\s*\(([^)]+)\)', name)
    if m1:
        return m1.group(1).strip()
    # name(digits) ví dụ: "Can Duy Hung(378)"
    m2 = re.match(r'^([^(]+?)\s*\(\d+\)', name)
    if m2:
        return m2.group(1).strip()
    return name


def norm_text(s: str | None) -> str:
    if s is None:
        return ""
    s = s.strip()
    s = unicodedata.normalize("NFC", s)
    s = s.replace("\u00A0", " ")
    s = s.replace("\u200B", "")
    s = s.replace("\u200C", "")
    s = s.replace("\u200D", "")
    s = s.replace("\ufeff", "")
    s = " ".join(s.split())
    return s.casefold()


def parse_dt(time_str: str) -> datetime | None:
    time_str = time_str.strip()
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y %H:%M",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(time_str, fmt)
        except ValueError:
            continue
    return None


def parse_attendance_csv(csv_content: bytes) -> list[tuple[str, str]]:
    try:
        text = csv_content.decode("utf-8-sig")
    except Exception:
        text = csv_content.decode("latin-1")
    
    f = io.StringIO(text.strip())
    reader = csv.reader(f)
    rows = list(reader)
    if not rows:
        return []
    
    # Parse header
    header = [col.strip().lower() for col in rows[0]]
    
    name_idx = -1
    time_idx = -1
    
    # Nhận diện cột tên thông minh hơn để tránh nhận nhầm "user group"
    exact_names = ["user", "name", "username", "member", "employee", "họ tên", "họ và tên", "nhân viên", "tên"]
    for i, col in enumerate(header):
        if col in exact_names:
            name_idx = i
            break
            
    if name_idx == -1:
        for i, col in enumerate(header):
            if any(kw in col for kw in ["name", "tên", "member", "employee", "user"]) and not any(ex in col for ex in ["group", "id", "code", "role"]):
                name_idx = i
                break
            
    time_keywords = ["time", "date", "timestamp", "thời gian", "ngày", "giờ", "checktime", "datetime"]
    for i, col in enumerate(header):
        if any(kw in col for kw in time_keywords):
            time_idx = i
            break
            
    if name_idx == -1:
        name_idx = 0
    if time_idx == -1:
        time_idx = min(1, len(header) - 1)
        
    records = []
    for r in rows[1:]:
        if len(r) <= max(name_idx, time_idx):
            continue
        name = r[name_idx].strip()
        time_str = r[time_idx].strip()
        if name and time_str:
            cleaned_name = clean_name_from_csv(name)
            records.append((cleaned_name, time_str))
            
    return records


def parse_attendance_times(csv_content: bytes) -> list[str]:
    try:
        text = csv_content.decode("utf-8-sig")
    except Exception:
        text = csv_content.decode("latin-1")
    
    f = io.StringIO(text.strip())
    reader = csv.reader(f)
    rows = list(reader)
    if not rows:
        return []
    
    # Parse header
    header = [col.strip().lower() for col in rows[0]]
    
    time_idx = -1
    time_keywords = ["time", "date", "timestamp", "thời gian", "ngày", "giờ", "checktime", "datetime"]
    for i, col in enumerate(header):
        if any(kw in col for kw in time_keywords):
            time_idx = i
            break
            
    if time_idx == -1:
        time_idx = min(1, len(header) - 1)
        
    times = []
    for r in rows[1:]:
        if len(r) <= time_idx:
            continue
        time_str = r[time_idx].strip()
        if time_str:
            times.append(time_str)
            
    return times


# -------------------- Manual Multipart Form Parser --------------------
def parse_multipart_attendance(handler):
    content_type = handler.headers.get("Content-Type", "")
    if not content_type.startswith("multipart/form-data"):
        return {}

    parts = content_type.split("boundary=")
    if len(parts) < 2:
        return {}
    boundary = parts[1].strip()
    if boundary.startswith('"') and boundary.endswith('"'):
        boundary = boundary[1:-1]

    boundary_bytes = f"--{boundary}".encode("utf-8")
    
    length = int(handler.headers.get("Content-Length", 0))
    body = handler.rfile.read(length)

    raw_parts = body.split(boundary_bytes)
    form_data = {}

    for part in raw_parts:
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue

        if b"\r\n\r\n" not in part:
            continue
        header_part, content_part = part.split(b"\r\n\r\n", 1)

        headers = {}
        for line in header_part.decode("utf-8", errors="ignore").split("\r\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()

        disp = headers.get("content-disposition", "")
        if not disp.startswith("form-data"):
            continue

        params = {}
        for p in disp.split(";")[1:]:
            if "=" in p:
                pk, pv = p.split("=", 1)
                params[pk.strip()] = pv.strip().strip('"')

        name = params.get("name")
        if not name:
            continue

        filename = params.get("filename")
        if filename:
            file_info = {
                "filename": filename,
                "content_type": headers.get("content-type", "application/octet-stream"),
                "content": content_part
            }
            form_data.setdefault(name, []).append(file_info)
        else:
            value = content_part.decode("utf-8", errors="ignore")
            form_data.setdefault(name, []).append(value)

    return form_data


# -------------------- Pages --------------------
def page_attendance(filters: dict, error_msg: str | None = None, success_msg: str | None = None):
    # Selected Month
    month_val = filters.get("month") or ""
    if not month_val:
        today = date.today()
        month_val = today.strftime("%Y-%m") # e.g. "2026-07"
        
    try:
        year = int(month_val.split("-")[0])
        month = int(month_val.split("-")[1])
    except Exception:
        today = date.today()
        year, month = today.year, today.month
        month_val = today.strftime("%Y-%m")

    # Days in month
    num_days = calendar.monthrange(year, month)[1]
    
    # Filter params
    vendor_filter = parse_int_or_none(filters.get("vendor_id"))
    contract_filter = parse_int_or_none(filters.get("contract_id"))
    q_filter = (filters.get("q") or "").strip()

    conn = db_connect()
    try:
        if vendor_filter is not None and contract_filter is not None:
            c_row = conn.execute("SELECT 1 FROM contracts WHERE id=? AND seller_vendor_id=?", (contract_filter, vendor_filter)).fetchone()
            if not c_row:
                contract_filter = None

        # Load vendors (purchasing=0)
        vendors = conn.execute("SELECT id, COALESCE(company_name, company_name_vi) AS company_name, tax_id FROM vendors WHERE is_active=1 AND purchasing=0").fetchall()
        
        # Load contracts
        if vendor_filter is not None:
            contracts = conn.execute("SELECT id, framework_no, framework_name FROM contracts WHERE is_active=1 AND seller_vendor_id=?", (vendor_filter,)).fetchall()
        else:
            contracts = conn.execute("SELECT id, framework_no, framework_name FROM contracts WHERE is_active=1").fetchall()

        # Build SQL where
        where = ["(s.status IS NULL OR s.status <> 'inactive')"]
        params = []

        if vendor_filter is not None:
            where.append("s.vendor_id = ?")
            params.append(vendor_filter)
        if contract_filter is not None:
            where.append("s.contract_id = ?")
            params.append(contract_filter)
        if q_filter:
            where.append("s.full_name_vi LIKE ?")
            params.append(f"%{q_filter}%")

        where_sql = "WHERE " + " AND ".join(where)

        # Load active staff
        staff_list = conn.execute(f"""
            SELECT s.id, s.full_name_vi, s.ot, s.work_shift,
                   COALESCE(v.company_name, v.company_name_vi) AS vendor_name,
                   c.framework_no AS contract_no
            FROM contract_staff s
            JOIN vendors v ON v.id=s.vendor_id
            JOIN contracts c ON c.id=s.contract_id
            {where_sql}
            ORDER BY s.full_name_vi ASC
        """, params).fetchall()

        # Load active staff và còn hạn hợp đồng trong tháng để hiển thị ở mục Import
        month_start_date = f"{year:04d}-{month:02d}-01"
        month_end_date = f"{year:04d}-{month:02d}-{num_days:02d}"
        
        import_staff_list = conn.execute("""
            SELECT s.id, s.full_name_vi, s.work_shift, s.ot, COALESCE(v.company_name, v.company_name_vi) AS company_name
            FROM contract_staff s
            JOIN vendors v ON v.id = s.vendor_id
            WHERE (s.status IS NULL OR s.status <> 'inactive')
              AND (s.joining_date IS NULL OR s.joining_date <= ?)
              AND (s.tentative_leaving_date IS NULL OR s.tentative_leaving_date >= ?)
            ORDER BY s.full_name_vi ASC
        """, (month_end_date, month_start_date)).fetchall()

        # Load locks for this month
        locks_rows = conn.execute("SELECT staff_id FROM attendance_locks WHERE month=? AND locked=1", (month_val,)).fetchall()
        locked_staff_ids = {r["staff_id"] for r in locks_rows}

        # Load monthly summary locks and manual totals for this month
        m_locks_rows = conn.execute("SELECT staff_id, locked, manual_work_hours, manual_ot_hours FROM monthly_attendance_summary WHERE month=?", (month_val,)).fetchall()
        monthly_locked_staff_ids = {r["staff_id"] for r in m_locks_rows if r["locked"] == 1}
        manual_totals_map = {r["staff_id"]: (r["manual_work_hours"], r["manual_ot_hours"]) for r in m_locks_rows}

        # Load existing attendance for this month
        month_start_date = f"{year:04d}-{month:02d}-01"
        month_end_date = f"{year:04d}-{month:02d}-{num_days:02d}"
        
        att_rows = conn.execute("""
            SELECT staff_id, date, work_hours, ot_hours, check_in, check_out
            FROM attendance
            WHERE date >= ? AND date <= ?
        """, (month_start_date, month_end_date)).fetchall()

        # Group attendance by staff_id and day
        # att_map[staff_id][day] = (work_hours, ot_hours)
        att_map = {}
        for r in att_rows:
            sid = r["staff_id"]
            d_str = r["date"]
            try:
                day_num = int(d_str.split("-")[2])
            except Exception:
                continue
            att_map.setdefault(sid, {})[day_num] = (r["work_hours"], r["ot_hours"], r["check_in"], r["check_out"])

    finally:
        conn.close()

    # Vendors options
    vendor_opts = ['<option value="">-- All Vendors --</option>']
    for v in vendors:
        sel = "selected" if vendor_filter == v["id"] else ""
        label = v["company_name"] or f"Vendor#{v['id']}"
        vendor_opts.append(f'<option value="{v["id"]}" {sel}>{escape(label)}</option>')

    # Contracts options
    contract_opts = ['<option value="">-- All Contracts --</option>']
    for c in contracts:
        sel = "selected" if contract_filter == c["id"] else ""
        label = c["framework_no"] or f"Contract#{c['id']}"
        if c["framework_name"]:
            label += f" | {c['framework_name']}"
        contract_opts.append(f'<option value="{c["id"]}" {sel}>{escape(label)}</option>')

    # Render table headers
    # Row 1: day number with colspan=2
    # Row 2: subheaders Work | OT for each day
    day_headers_r1 = []
    day_headers_r2 = []
    
    # Track weekends
    weekend_days = {} # day_num -> bool
    
    for d in range(1, num_days + 1):
        day_date = date(year, month, d)
        day_name = day_date.strftime("%a") # e.g. "Mon", "Tue"
        # Translate to EN
        vn_names = {"Mon": "Mon", "Tue": "Tue", "Wed": "Wed", "Thu": "Thu", "Fri": "Fri", "Sat": "Sat", "Sun": "Sun"}
        vn_name = vn_names.get(day_name, day_name)
        
        is_we = day_date.weekday() in (5, 6)
        weekend_days[d] = is_we
        
        we_style = "background: #fff5e6; color: #b00020;" if is_we else ""
        day_headers_r1.append(f"""
          <th colspan="2" style="text-align: center; font-size: 11px; padding: 4px; border-bottom: none; {we_style}">
            <b>{d}</b><br><span style="font-size: 9px; opacity: 0.8;">{vn_name}</span>
          </th>
        """)
        day_headers_r2.append(f"""
          <th style="font-size: 9px; padding: 2px; text-align: center; border-top: none; {we_style}">W</th>
          <th style="font-size: 9px; padding: 2px; text-align: center; border-top: none; {we_style}">OT</th>
        """)

    # Render rows
    trs = []
    for s in staff_list:
        sid = s["id"]
        
        is_locked = sid in locked_staff_ids
        disabled_attr = "disabled" if is_locked else ""
        
        # Lock/unlock URL parameters
        act_qs = f"staff_id={sid}&month={month_val}&vendor_id={vendor_filter or ''}&contract_id={contract_filter or ''}&q={urllib.parse.quote(q_filter)}"
        
        if is_locked:
            if sid in monthly_locked_staff_ids:
                lock_label = '🔒 <b style="color:#b00020;">Locked (Monthly Locked)</b>'
                lock_action_html = f"""
                <div style="margin-top: 4px;">
                  <span style="font-size: 9px; color: #999; background: #eee; border: 1px solid #ddd; padding: 2px 4px; border-radius: 4px; display: inline-block; font-weight: bold; cursor: not-allowed;" title="Cannot unlock daily attendance because monthly payroll is locked.">🔓 Unlock</span>
                </div>
                """
            else:
                lock_label = '🔒 <b style="color:#b00020;">Locked</b>'
                lock_action_html = f"""
                <div style="margin-top: 4px;">
                  <a href="/attendance/unlock?{act_qs}" style="font-size: 9px; color: #b00020; background: #fff5f6; border: 1px solid #f1c0c6; padding: 2px 4px; border-radius: 4px; display: inline-block; font-weight: bold; text-decoration: none;">🔓 Unlock</a>
                </div>
                """
        else:
            lock_label = '<span class="muted" style="font-size: 9px;">Unlocked</span>'
            lock_action_html = f"""
            <div style="margin-top: 4px;">
              <a href="/attendance/lock?{act_qs}" style="font-size: 9px; color: #137333; background: #e6f4ea; border: 1px solid #b4e3be; padding: 2px 4px; border-radius: 4px; display: inline-block; font-weight: bold; text-decoration: none;">🔒 Lock</a>
            </div>
            """

        total_work = 0.0
        total_ot = 0.0
        cells = []
        for d in range(1, num_days + 1):
            is_we = weekend_days[d]
            cell_bg = "background: #fffdf5;" if is_we else ""
            
            d_str = f"{year:04d}-{month:02d}-{d:02d}"
            
            work_val = ""
            ot_val = ""
            tooltip_title = ""
            
            if sid in att_map and d in att_map[sid]:
                w, ot, ci, co = att_map[sid][d]
                work_val = f"{w:.2f}" if w > 0 else ""
                ot_val = f"{ot:.2f}" if ot > 0 else ""
                total_work += w if w > 0 else 0.0
                total_ot += ot if ot > 0 else 0.0
                if ci or co:
                    tooltip_title = f' title="Fingerprint logs: {ci or "?"} → {co or "?"}"'
            
            cells.append(f"""
              <td style="padding: 2px; text-align: center; {cell_bg}">
                <input type="number" name="w_{sid}_{d_str}" data-staff-id="{sid}" data-date="{d_str}" data-type="w" class="att-input" min="0" max="24" step="0.01" value="{work_val}" {tooltip_title} {disabled_attr}
                       placeholder="-" style="width: 36px; font-size: 10px; padding: 2px 0; text-align: center; border: 1px solid #ddd; border-radius: 4px; background: transparent;">
              </td>
              <td style="padding: 2px; text-align: center; {cell_bg}">
                <input type="number" name="ot_{sid}_{d_str}" data-staff-id="{sid}" data-date="{d_str}" data-type="ot" class="att-input" min="0" max="24" step="0.01" value="{ot_val}" {tooltip_title} {disabled_attr}
                       placeholder="-" style="width: 36px; font-size: 10px; padding: 2px 0; text-align: center; border: 1px solid #ddd; border-radius: 4px; background: transparent;">
              </td>
            """)
            
        # Determine totals to display (check for manual overrides)
        manual_w, manual_ot = manual_totals_map.get(sid, (None, None))
        display_total_work = manual_w if manual_w is not None else total_work
        display_total_ot = manual_ot if manual_ot is not None else total_ot

        if is_locked:
            total_work_html = f"{display_total_work:.2f}"
            total_ot_html = f"{display_total_ot:.2f}"
        else:
            w_style = "border: 1px solid #0369a1; background: #e0f2fe; color: #0369a1;" if manual_w is not None else "border: 1px solid #cbd5e1; background: transparent; color: #0369a1;"
            ot_style = "border: 1px solid #b45309; background: #fef3c7; color: #b45309;" if manual_ot is not None else "border: 1px solid #cbd5e1; background: transparent; color: #b45309;"
            manual_w_attr = 'data-manual="true"' if manual_w is not None else ''
            manual_ot_attr = 'data-manual="true"' if manual_ot is not None else ''
            total_work_html = f'<input type="number" step="0.01" name="total_work_{sid}" value="{display_total_work:.2f}" style="width: 48px; font-size: 11px; font-weight: bold; text-align: center; border-radius: 4px; {w_style}" {manual_w_attr}>'
            total_ot_html = f'<input type="number" step="0.01" name="total_ot_{sid}" value="{display_total_ot:.2f}" style="width: 48px; font-size: 11px; font-weight: bold; text-align: center; border-radius: 4px; {ot_style}" {manual_ot_attr}>'

        trs.append(f"""
        <tr>
          <td class="sticky-col1" style="font-size: 11px; text-align: center;">{sid}</td>
          <td class="sticky-col2" style="font-size: 12px;">
            <b>{escape(s["full_name_vi"])}</b>
            <div class="muted" style="font-size: 9px;">{escape(s["contract_no"])}</div>
            {lock_action_html}
          </td>
          <td style="font-size: 11px; max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
            {escape(s["vendor_name"] or "")}
          </td>
          <td style="font-size: 11px; text-align: center;">
            {"Yes" if s["ot"]==1 else "No"}
            <div class="muted" style="font-size: 9px;">{escape(s["work_shift"] or "Not set")}</div>
            <div style="margin-top:2px;">{lock_label}</div>
          </td>
          <td style="font-size: 11px; text-align: center; font-weight: bold; background: #f0f9ff; color: #0369a1; padding: 2px;">
            {total_work_html}
          </td>
          <td style="font-size: 11px; text-align: center; font-weight: bold; background: #fffbeb; color: #b45309; padding: 2px;">
            {total_ot_html}
          </td>
          {''.join(cells)}
        </tr>
        """)

    error_html = f"<div class='card danger'><b>Error:</b> {escape(error_msg)}</div>" if error_msg else ""
    success_html = f"<div class='card success' style='border-color:#b4e3be; background:#f4fbf6; color:#137333; padding:12px; border-radius:8px; margin-bottom:16px;'><b>Success:</b> {escape(success_msg)}</div>" if success_msg else ""

    # Spreadsheet styles
    extra_styles = """
    <style>
      .spreadsheet-container {
        overflow-x: auto;
        max-width: 100%;
        margin-top: 14px;
        border: 1px solid #e0e0e0;
        border-radius: 8px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
      }
      .spreadsheet-container table {
        margin: 0;
        border-collapse: separate;
        border-spacing: 0;
        width: max-content;
      }
      .spreadsheet-container th, .spreadsheet-container td {
        border-right: 1px solid #e0e0e0;
        border-bottom: 1px solid #e0e0e0;
      }
      /* Sticky columns */
      .sticky-col1 {
        position: sticky;
        left: 0;
        background: #fff;
        z-index: 5;
        width: 35px;
        border-right: 1px solid #e0e0e0;
      }
      .sticky-col2 {
        position: sticky;
        left: 36px;
        background: #fff;
        z-index: 5;
        width: 150px;
        border-right: 2px solid #ccc !important;
      }
      th.sticky-col1 {
        z-index: 6;
        background: #fafafa;
      }
      th.sticky-col2 {
        z-index: 6;
        background: #fafafa;
        border-right: 2px solid #ccc !important;
      }
      tr:hover td.sticky-col1, tr:hover td.sticky-col2 {
        background: #f5f5f5;
      }
      input::-webkit-outer-spin-button,
      input::-webkit-inner-spin-button {
        -webkit-appearance: none;
        margin: 0;
      }
      input[type=number] {
        -moz-appearance: textfield;
      }
    </style>
    """

    sub_nav = f"""
    <div class="actions" style="margin-bottom: 14px; border-bottom: 1px solid #ddd; padding-bottom: 8px;">
      <a href="/attendance?month={month_val}&vendor_id={vendor_filter or ''}&contract_id={contract_filter or ''}&q={escape(q_filter)}" style="margin-right: 18px; font-weight: bold; color:#0b57d0; border-bottom: 2px solid #0b57d0; padding-bottom: 8px;">📅 Daily Attendance</a>
      <a href="/attendance/monthly?month={month_val}&vendor_id={vendor_filter or ''}&contract_id={contract_filter or ''}&q={escape(q_filter)}" style="margin-right: 18px; font-weight: bold; color:#666; text-decoration:none;">💵 Monthly Payroll & Payment</a>
      <a href="/attendance/import-bulk" style="font-weight: bold; color:#666; text-decoration:none;">📤 Bulk Import Face Logs</a>
    </div>
    """

    body = f"""
    {extra_styles}
    {sub_nav}
    {error_html}
    {success_html}

    <!-- 2. Filters -->
    <div class="card">
      <form method="GET" action="/attendance" class="filters" style="margin: 0;">
        <div>
          <div class="label">Attendance Month</div>
          <input type="month" name="month" value="{month_val}" onchange="this.form.submit()">
        </div>
        <div>
          <div class="label">Vendor</div>
          <select name="vendor_id" onchange="this.form.submit()">
            {''.join(vendor_opts)}
          </select>
        </div>
        <div>
          <div class="label">Framework Contract</div>
          <select name="contract_id" onchange="this.form.submit()">
            {''.join(contract_opts)}
          </select>
        </div>
        <div>
          <div class="label">Search staff</div>
          <input type="text" name="q" placeholder="Enter staff name..." value="{escape(q_filter)}">
        </div>
        <div class="actions">
          <button type="submit">Filter</button>
          <a class="muted" href="/attendance">Reset</a>
        </div>
      </form>
    </div>

    <!-- 1. Import Section -->
    <div class="card" style="background:#fafafa;">
      <h3>Import attendance data for active staff in {month_val}</h3>
      <div class="muted" style="margin-bottom:12px;">
        Select the CSV attendance file for each staff member below. The system will read only the timestamp log in the file to calculate daily work hours and OT based on their work shift, ignoring the names inside the CSV file.
      </div>
      
      <form method="POST" action="/attendance/import" enctype="multipart/form-data">
        <input type="hidden" name="month" value="{month_val}">
        <input type="hidden" name="vendor_id" value="{vendor_filter or ''}">
        <input type="hidden" name="contract_id" value="{contract_filter or ''}">
        <input type="hidden" name="q" value="{escape(q_filter)}">
        
        <div style="max-height: 250px; overflow-y: auto; border: 1px solid var(--border); border-radius: 8px; margin-bottom: 12px; background: #fff; box-shadow: var(--shadow-sm);">
          <table style="width: 100%; border: none; margin: 0; border-collapse: collapse;">
            <thead>
              <tr style="background: #f1f5f9;">
                <th style="padding: 8px 12px; text-align: left; font-size: 11px; text-transform: uppercase; border-bottom: 1px solid var(--border); border-right: none;">ID</th>
                <th style="padding: 8px 12px; text-align: left; font-size: 11px; text-transform: uppercase; border-bottom: 1px solid var(--border); border-right: none;">Staff Name</th>
                <th style="padding: 8px 12px; text-align: left; font-size: 11px; text-transform: uppercase; border-bottom: 1px solid var(--border); border-right: none;">Vendor</th>
                <th style="padding: 8px 12px; text-align: left; font-size: 11px; text-transform: uppercase; border-bottom: 1px solid var(--border); border-right: none;">Work Shift</th>
                <th style="padding: 8px 12px; text-align: left; font-size: 11px; text-transform: uppercase; border-bottom: 1px solid var(--border); border-right: none; width: 320px;">Upload CSV File</th>
                <th style="padding: 8px 12px; text-align: left; font-size: 11px; text-transform: uppercase; border-bottom: 1px solid var(--border); border-right: none; width: 100px;">Actions</th>
              </tr>
            </thead>
            <tbody>
              {"".join([f'''
              <tr style="border-bottom: 1px solid var(--border);">
                <td style="padding: 8px 12px; font-size: 12px; color: var(--text-muted); border-right: none;">{st["id"]}</td>
                <td style="padding: 8px 12px; font-size: 13px; border-right: none;"><b>{escape(st["full_name_vi"])}</b></td>
                <td style="padding: 8px 12px; font-size: 12px; color: var(--text-secondary); border-right: none;">{escape(st["company_name"] or "")}</td>
                <td style="padding: 8px 12px; font-size: 12px; color: var(--text-secondary); border-right: none;">{escape(st["work_shift"] or "Not set")}</td>
                <td style="padding: 6px 12px; border-right: none;">
                  {f'<span style="display: inline-block; font-size: 11px; font-weight: 600; color: #b00020; background: #fff5f6; border: 1px solid #f1c0c6; padding: 4px 10px; border-radius: 4px;">🔒 Locked</span>'
                   if (st["id"] in locked_staff_ids or st["id"] in monthly_locked_staff_ids)
                   else f'<input type="file" name="file_{st["id"]}" accept=".csv" style="font-size: 11px; padding: 4px; border: 1px solid var(--border); border-radius: 4px; background: #fff; width: 100%;">'
                  }
                </td>
                <td style="padding: 6px 12px; border-right: none;">
                  {("" if (st["id"] in locked_staff_ids or st["id"] in monthly_locked_staff_ids)
                    else (f'<a href="/attendance/clear?staff_id={st["id"]}&month={month_val}&vendor_id={vendor_filter or ""}&contract_id={contract_filter or ""}&q={urllib.parse.quote(q_filter)}" class="btn btn-danger" style="font-size: 11px; padding: 4px 8px; line-height: 1;" onclick="return confirm(\'Xóa toàn bộ dữ liệu chấm công tháng {month_val} của {escape(st["full_name_vi"])}?\')">🗑️ Xóa công</a>'
                          if st["id"] in att_map else '<span class="muted" style="font-size:11px;">Chưa có công</span>')
                   )}
                </td>
              </tr>
              ''' for st in import_staff_list]) if import_staff_list else '<tr><td colspan="6" class="muted" style="padding:15px; text-align:center;">No active staff with valid contract in this month</td></tr>'}
            </tbody>
          </table>
        </div>
        <div>
          <button type="submit" style="background:#0b57d0; color:#fff; border-color:#0b57d0; font-weight:600; padding: 8px 20px;">Import Selected Files</button>
        </div>
      </form>
    </div>

    <!-- 3. Attendance Sheet -->
    <form method="POST" action="/attendance/save">
      <input type="hidden" name="month" value="{month_val}">
      <input type="hidden" name="vendor_id" value="{vendor_filter or ''}">
      <input type="hidden" name="contract_id" value="{contract_filter or ''}">
      <input type="hidden" name="q" value="{escape(q_filter)}">

      <div class="spreadsheet-container">
        <table>
          <thead>
            <tr>
              <th rowspan="2" class="sticky-col1" style="text-align: center; vertical-align: middle;">ID</th>
              <th rowspan="2" class="sticky-col2" style="text-align: left; vertical-align: middle;">Full Name</th>
              <th rowspan="2" style="text-align: left; vertical-align: middle; min-width: 120px;">Vendor</th>
              <th rowspan="2" style="text-align: center; vertical-align: middle; min-width: 65px;">OT / Shift</th>
              <th rowspan="2" style="text-align: center; vertical-align: middle; min-width: 60px; background: #e0f2fe; color: #0369a1; font-weight: bold;">Total Days</th>
              <th rowspan="2" style="text-align: center; vertical-align: middle; min-width: 60px; background: #fef3c7; color: #b45309; font-weight: bold;">Total OT</th>
              {''.join(day_headers_r1)}
            </tr>
            <tr>
              {''.join(day_headers_r2)}
            </tr>
          </thead>
          <tbody>
            {''.join(trs) if trs else f'<tr><td colspan="{6 + num_days*2}" class="muted" style="padding:15px;">No active staff found matching the filters</td></tr>'}
          </tbody>
        </table>
      </div>

      {f'''
      <div class="actions" style="margin-top:20px;">
        <button type="submit" style="background:#0b57d0; color:#fff; border-color:#0b57d0; font-weight:600; padding: 10px 24px;">Save Attendance</button>
        <span class="muted">Hover over an attendance cell to see the raw check-in/check-out times from the file.</span>
      </div>
      ''' if trs else ''}
    </form>

    <script>
      (function() {{
        document.querySelectorAll('.att-input').forEach(input => {{
          input.addEventListener('change', function() {{
            const staffId = this.getAttribute('data-staff-id');
            const date = this.getAttribute('data-date');
            const type = this.getAttribute('data-type');
            const value = this.value;
            const originalVal = this.defaultValue;
            const targetCell = this;

            // Set saving visual indicator
            targetCell.style.borderColor = '#4f46e5';
            targetCell.style.background = '#e0e7ff';

            fetch('/attendance/save-cell', {{
              method: 'POST',
              headers: {{
                'Content-Type': 'application/json'
              }},
              body: JSON.stringify({{
                staff_id: staffId,
                date: date,
                type: type,
                value: value
              }})
            }})
            .then(res => {{
              if (!res.ok) {{
                return res.json().then(err => {{ throw new Error(err.message || 'Error saving cell'); }});
              }}
              return res.json();
            }})
            .then(data => {{
              if (data.status === 'ok') {{
                targetCell.style.borderColor = '#10b981'; // Green on success
                targetCell.style.background = '#ecfdf5';
                targetCell.defaultValue = value; // Update default value
                setTimeout(() => {{
                  targetCell.style.borderColor = '#ddd';
                  targetCell.style.background = 'transparent';
                }}, 1000);

                // Dynamically update the totals input if not manually overridden
                const totalInput = document.querySelector('input[name="total_' + (type === 'w' ? 'work' : 'ot') + '_' + staffId + '"]');
                if (totalInput && totalInput.dataset.manual !== 'true') {{
                  let sum = 0.0;
                  document.querySelectorAll('input[data-staff-id="' + staffId + '"][data-type="' + type + '"]').forEach(cell => {{
                    const val = parseFloat(cell.value);
                    if (!isNaN(val)) {{
                      sum += val;
                    }}
                  }});
                  totalInput.value = sum.toFixed(2);
                }}
              }} else {{
                throw new Error(data.message || 'Error saving cell');
              }}
            }})
            .catch(err => {{
              targetCell.style.borderColor = '#ef4444'; // Red on error
              targetCell.style.background = '#fef2f2';
              alert('Error: ' + err.message);
              // Revert to original value
              targetCell.value = originalVal;
              setTimeout(() => {{
                targetCell.style.borderColor = '#ddd';
                targetCell.style.background = 'transparent';
              }}, 1500);
            }});
          }});
        }});

        // Add manual flag when total inputs are changed
        document.querySelectorAll('input[name^="total_work_"], input[name^="total_ot_"]').forEach(totalInput => {{
          totalInput.addEventListener('change', function() {{
            this.dataset.manual = 'true';
            this.style.borderColor = '#4f46e5';
            this.style.background = '#f5f3ff';
          }});
        }});
      }})();
    </script>
    """
    
    return layout(f"Time Attendance - Month {month:02d}/{year:04d}", body)


def handle_attendance_import_post(handler):
    form = parse_multipart_attendance(handler)
    
    # Retrieve filters to redirect back
    month_val = form.get("month", [""])[0].strip()
    vendor_id = form.get("vendor_id", [""])[0].strip()
    contract_id = form.get("contract_id", [""])[0].strip()
    q = form.get("q", [""])[0].strip()
    
    redirect_url = f"/attendance?month={month_val}&vendor_id={vendor_id}&contract_id={contract_id}&q={q}"

    conn = db_connect()
    try:
        staff_rows = conn.execute("""
            SELECT id, full_name_vi, ot, work_shift 
            FROM contract_staff 
            WHERE status IS NULL OR status <> 'inactive'
        """).fetchall()
        staff_map = {s["id"]: s for s in staff_rows}

        # Load existing locks for this month
        locks_rows = conn.execute("SELECT staff_id FROM attendance_locks WHERE month=? AND locked=1", (month_val,)).fetchall()
        locked_staff_ids = {r["staff_id"] for r in locks_rows}

        ok_count = 0
        locked_skip_count = 0
        imported_staff_names = []
        
        cur = conn.cursor()
        
        for key, files in form.items():
            if not key.startswith("file_"):
                continue
            try:
                sid = int(key.split("_")[1])
            except ValueError:
                continue
                
            if sid not in staff_map:
                continue
                
            s = staff_map[sid]
            
            if sid in locked_staff_ids:
                locked_skip_count += 1
                continue
                
            valid_files = [f for f in files if isinstance(f, dict) and f.get("filename") and len(f.get("content", b"")) > 0]
            if not valid_files:
                continue
                
            file_info = valid_files[0]
            try:
                times = parse_attendance_times(file_info["content"])
            except Exception as e:
                continue
                
            if not times:
                continue
                
            # Group timestamps by date_str -> list of datetime
            date_map = {}
            for t_str in times:
                dt = parse_dt(t_str)
                if not dt:
                    continue
                d_str = dt.strftime("%Y-%m-%d")
                date_map.setdefault(d_str, []).append(dt)
                
            staff_ok_count = 0
            for d_str, dts in date_map.items():
                if not dts:
                    continue
                dts.sort()
                
                check_in_dt = dts[0]
                check_out_dt = dts[-1]
                
                check_in_str = check_in_dt.strftime("%H:%M")
                check_out_str = check_out_dt.strftime("%H:%M")
                
                # Calculation hours
                dur_hours = (check_out_dt - check_in_dt).total_seconds() / 3600.0
                
                # Check lunch break (12:00 -> 13:00)
                if check_in_dt.hour < 12 and check_out_dt.hour >= 13:
                    net_hours = dur_hours - 1.0
                elif dur_hours > 4.0:
                    net_hours = dur_hours - 1.0
                else:
                    net_hours = dur_hours
                
                # Convert to shifts
                if net_hours > 6.0:
                    work_hours = 8.0
                elif net_hours > 3.0:
                    work_hours = 4.0
                else:
                    work_hours = 0.0
                    
                # OT calculation
                ot_hours = 0.0
                if s["ot"] == 1 and s["work_shift"]:
                    # Determine shift end in hours
                    shift_end = None
                    if "8:00 - 17:00" in s["work_shift"]:
                        shift_end = 17.0
                    elif "8:30 - 17:30" in s["work_shift"]:
                        shift_end = 17.5
                        
                    if shift_end is not None:
                        co_hours = check_out_dt.hour + check_out_dt.minute / 60.0
                        if co_hours > shift_end:
                            ot_hours = round(co_hours - shift_end, 1)

                # Upsert into DB
                cur.execute("""
                    INSERT INTO attendance (staff_id, date, check_in, check_out, work_hours, ot_hours, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                    ON CONFLICT(staff_id, date) DO UPDATE SET
                        check_in=excluded.check_in,
                        check_out=excluded.check_out,
                        work_hours=excluded.work_hours,
                        ot_hours=excluded.ot_hours,
                        updated_at=datetime('now')
                """, (sid, d_str, check_in_str, check_out_str, work_hours, ot_hours))
                
                staff_ok_count += 1
                
            if staff_ok_count > 0:
                ok_count += staff_ok_count
                imported_staff_names.append(s["full_name_vi"])
                
        conn.commit()
    finally:
        conn.close()

    if ok_count > 0:
        success_msg = f"Successfully imported {ok_count} attendance records for: {', '.join(imported_staff_names)}."
    else:
        success_msg = "No new attendance records were imported."
        
    if locked_skip_count > 0:
        success_msg += f" Skipped {locked_skip_count} employees because their attendance for this month is locked."
        
    send_html(handler, page_attendance({"month": month_val, "vendor_id": vendor_id, "contract_id": contract_id, "q": q}, success_msg=success_msg))


def handle_attendance_save_post(handler):
    # Read urlencoded post data
    # Form can be very large because of all input boxes
    length = int(handler.headers.get("Content-Length", 0))
    raw = handler.rfile.read(length).decode("utf-8", errors="ignore")
    import urllib.parse
    form = urllib.parse.parse_qs(raw, keep_blank_values=True)

    month_val = form.get("month", [""])[0].strip()
    vendor_id = form.get("vendor_id", [""])[0].strip()
    contract_id = form.get("contract_id", [""])[0].strip()
    q = form.get("q", [""])[0].strip()
    
    redirect_url = f"/attendance?month={month_val}&vendor_id={vendor_id}&contract_id={contract_id}&q={q}"

    conn = db_connect()
    try:
        # Load locks for this month
        locks_rows = conn.execute("SELECT staff_id FROM attendance_locks WHERE month=? AND locked=1", (month_val,)).fetchall()
        locked_staff_ids = {r["staff_id"] for r in locks_rows}

        cur = conn.cursor()
        
        # We need to find all keys in form: w_{sid}_{date} and ot_{sid}_{date}
        # Gather updates
        updates = {} # (sid, date) -> {"w": val, "ot": val}
        manual_totals = {} # sid -> {"work": val, "ot": val}
        
        for key, vals in form.items():
            if key.startswith("w_"):
                parts = key.split("_")
                if len(parts) >= 3:
                    sid = int(parts[1])
                    d_str = "_".join(parts[2:]) # Handles YYYY-MM-DD
                    val = to_xml_float(vals[0]) or 0.0
                    updates.setdefault((sid, d_str), {})["w"] = val
            elif key.startswith("ot_"):
                parts = key.split("_")
                if len(parts) >= 3:
                    sid = int(parts[1])
                    d_str = "_".join(parts[2:])
                    val = to_xml_float(vals[0]) or 0.0
                    updates.setdefault((sid, d_str), {})["ot"] = val
            elif key.startswith("total_work_"):
                sid = int(key.split("_")[2])
                val = to_xml_float(vals[0])
                manual_totals.setdefault(sid, {})["work"] = val
            elif key.startswith("total_ot_"):
                sid = int(key.split("_")[2])
                val = to_xml_float(vals[0])
                manual_totals.setdefault(sid, {})["ot"] = val
        
        # Perform updates
        for (sid, d_str), vals in updates.items():
            if sid in locked_staff_ids:
                continue # Skip locked staff member from manual updates
            w = vals.get("w", 0.0)
            ot = vals.get("ot", 0.0)
            
            # If w=0 and ot=0, we can either delete or upsert 0. Let's upsert so it preserves 0.
            cur.execute("""
                INSERT INTO attendance (staff_id, date, work_hours, ot_hours, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(staff_id, date) DO UPDATE SET
                    work_hours=excluded.work_hours,
                    ot_hours=excluded.ot_hours,
                    updated_at=datetime('now')
            """, (sid, d_str, w, ot))
            
        # Update monthly summary for modified staff
        if month_val:
            try:
                year = int(month_val.split("-")[0])
                month = int(month_val.split("-")[1])
                import calendar
                num_days = calendar.monthrange(year, month)[1]
                month_start_date = f"{year:04d}-{month:02d}-01"
                month_end_date = f"{year:04d}-{month:02d}-{num_days:02d}"
                std_days_default = get_standard_working_days(year, month)
            except Exception:
                month_start_date = ""
                month_end_date = ""
                std_days_default = 22.0

            if month_start_date:
                # Load staff rates
                staff_data = {}
                staff_rows = conn.execute("""
                    SELECT id, monthly_rate, manday_rate FROM contract_staff
                """).fetchall()
                for s in staff_rows:
                    staff_data[s["id"]] = s

                for sid in manual_totals.keys():
                    if sid in locked_staff_ids:
                        continue
                        
                    # Calculate default/calculated sums from daily cells in DB
                    row_sum = conn.execute("""
                        SELECT SUM(work_hours) AS sum_w, SUM(ot_hours) AS sum_ot
                        FROM attendance
                        WHERE staff_id = ? AND date >= ? AND date <= ?
                    """, (sid, month_start_date, month_end_date)).fetchone()
                    
                    calc_w = row_sum["sum_w"] or 0.0
                    calc_ot = row_sum["sum_ot"] or 0.0
                    
                    sub_w = manual_totals[sid].get("work")
                    sub_ot = manual_totals[sid].get("ot")
                    
                    # Check override
                    manual_w = None
                    if sub_w is not None and abs(sub_w - calc_w) > 0.001:
                        manual_w = sub_w
                        
                    manual_ot = None
                    if sub_ot is not None and abs(sub_ot - calc_ot) > 0.001:
                        manual_ot = sub_ot
                        
                    # Fetch existing monthly summary values
                    summary_row = conn.execute("""
                        SELECT standard_days, paid_leave_days, locked FROM monthly_attendance_summary
                        WHERE staff_id = ? AND month = ?
                    """, (sid, month_val)).fetchone()
                    
                    std = std_days_default
                    pl = 0.0
                    if summary_row:
                        if summary_row["locked"] == 1:
                            continue
                        std = summary_row["standard_days"]
                        pl = summary_row["paid_leave_days"]
                        
                    actual_days = (manual_w if manual_w is not None else calc_w) / 8.0
                    ot_converted = (manual_ot if manual_ot is not None else calc_ot) * 1.5
                    
                    s = staff_data.get(sid)
                    daily_rate = 0.0
                    if s:
                        if s["manday_rate"] is not None and s["manday_rate"] > 0:
                            daily_rate = s["manday_rate"]
                        elif s["monthly_rate"] is not None and s["monthly_rate"] > 0:
                            daily_rate = s["monthly_rate"] / std if std > 0 else 0.0
                            
                    total_days = actual_days + pl
                    work_amt = round(total_days * daily_rate)
                    ot_rate = daily_rate / 8.0
                    ot_amt = round(ot_converted * ot_rate)
                    total_amount = work_amt + ot_amt
                    
                    conn.execute("""
                        INSERT INTO monthly_attendance_summary (
                            staff_id, month, standard_days, actual_days, paid_leave_days,
                            ot_converted_hours, daily_rate, total_amount, locked, 
                            manual_work_hours, manual_ot_hours, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, datetime('now'), datetime('now'))
                        ON CONFLICT(staff_id, month) DO UPDATE SET
                            actual_days = excluded.actual_days,
                            ot_converted_hours = excluded.ot_converted_hours,
                            daily_rate = excluded.daily_rate,
                            total_amount = excluded.total_amount,
                            manual_work_hours = excluded.manual_work_hours,
                            manual_ot_hours = excluded.manual_ot_hours,
                            updated_at = datetime('now')
                        """, (sid, month_val, std, actual_days, pl, ot_converted, daily_rate, total_amount, manual_w, manual_ot))

        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

    # Redirect back
    redirect(handler, redirect_url)


def handle_attendance_lock_get(handler):
    parsed = urllib.parse.urlparse(handler.path)
    qs = urllib.parse.parse_qs(parsed.query)

    sid = parse_int_or_none(qs.get("staff_id", [""])[0])
    month_val = (qs.get("month", [""])[0] or "").strip()
    
    vendor_id = qs.get("vendor_id", [""])[0].strip()
    contract_id = qs.get("contract_id", [""])[0].strip()
    q = qs.get("q", [""])[0].strip()
    
    redirect_url = f"/attendance?month={month_val}&vendor_id={vendor_id}&contract_id={contract_id}&q={q}"

    if sid and month_val:
        conn = db_connect()
        try:
            conn.execute("""
                INSERT INTO attendance_locks (staff_id, month, locked, locked_at)
                VALUES (?, ?, 1, datetime('now'))
                ON CONFLICT(staff_id, month) DO UPDATE SET locked=1, locked_at=datetime('now')
            """, (sid, month_val))
            conn.commit()
        finally:
            conn.close()

    redirect(handler, redirect_url)


def handle_attendance_unlock_get(handler):
    parsed = urllib.parse.urlparse(handler.path)
    qs = urllib.parse.parse_qs(parsed.query)

    sid = parse_int_or_none(qs.get("staff_id", [""])[0])
    month_val = (qs.get("month", [""])[0] or "").strip()
    
    vendor_id = qs.get("vendor_id", [""])[0].strip()
    contract_id = qs.get("contract_id", [""])[0].strip()
    q = qs.get("q", [""])[0].strip()
    
    redirect_url = f"/attendance?month={month_val}&vendor_id={vendor_id}&contract_id={contract_id}&q={q}"

    if sid and month_val:
        conn = db_connect()
        try:
            # Check if monthly summary is locked
            monthly_locked = conn.execute("""
                SELECT 1 FROM monthly_attendance_summary
                WHERE staff_id=? AND month=? AND locked=1
            """, (sid, month_val)).fetchone()
            if monthly_locked:
                send_html(handler, page_attendance(
                    {"month": month_val, "vendor_id": parse_int_or_none(vendor_id), "contract_id": parse_int_or_none(contract_id), "q": q},
                    error_msg="Cannot unlock daily attendance because monthly payroll is locked."
                ))
                return

            conn.execute("""
                UPDATE attendance_locks
                SET locked=0, locked_at=datetime('now')
                WHERE staff_id=? AND month=?
            """, (sid, month_val))
            conn.commit()
        finally:
            conn.close()

    redirect(handler, redirect_url)


def handle_attendance_clear_get(handler):
    parsed = urllib.parse.urlparse(handler.path)
    qs = urllib.parse.parse_qs(parsed.query)

    sid = parse_int_or_none(qs.get("staff_id", [""])[0])
    month_val = (qs.get("month", [""])[0] or "").strip()
    
    vendor_id = qs.get("vendor_id", [""])[0].strip()
    contract_id = qs.get("contract_id", [""])[0].strip()
    q = qs.get("q", [""])[0].strip()
    
    redirect_url = f"/attendance?month={month_val}&vendor_id={vendor_id}&contract_id={contract_id}&q={q}"

    if sid and month_val:
        conn = db_connect()
        try:
            # Check daily lock
            locked_daily = conn.execute("""
                SELECT 1 FROM attendance_locks
                WHERE staff_id=? AND month=? AND locked=1
            """, (sid, month_val)).fetchone()
            if locked_daily:
                send_html(handler, page_attendance(
                    {"month": month_val, "vendor_id": parse_int_or_none(vendor_id), "contract_id": parse_int_or_none(contract_id), "q": q},
                    error_msg="Cannot clear attendance data because it is locked."
                ))
                return

            # Check monthly lock
            locked_monthly = conn.execute("""
                SELECT 1 FROM monthly_attendance_summary
                WHERE staff_id=? AND month=? AND locked=1
            """, (sid, month_val)).fetchone()
            if locked_monthly:
                send_html(handler, page_attendance(
                    {"month": month_val, "vendor_id": parse_int_or_none(vendor_id), "contract_id": parse_int_or_none(contract_id), "q": q},
                    error_msg="Cannot clear attendance data because monthly payroll is locked."
                ))
                return

            try:
                year = int(month_val.split("-")[0])
                month = int(month_val.split("-")[1])
                num_days = calendar.monthrange(year, month)[1]
                month_start_date = f"{year:04d}-{month:02d}-01"
                month_end_date = f"{year:04d}-{month:02d}-{num_days:02d}"
            except Exception:
                send_html(handler, page_attendance(
                    {"month": month_val, "vendor_id": parse_int_or_none(vendor_id), "contract_id": parse_int_or_none(contract_id), "q": q},
                    error_msg="Invalid month format."
                ))
                return

            cur = conn.cursor()
            # Delete from attendance table
            cur.execute("""
                DELETE FROM attendance
                WHERE staff_id = ? AND date >= ? AND date <= ?
            """, (sid, month_start_date, month_end_date))

            # Reset manual columns and total amount in monthly_attendance_summary if it exists
            cur.execute("""
                UPDATE monthly_attendance_summary
                SET actual_days = 0.0,
                    ot_converted_hours = 0.0,
                    total_amount = 0.0,
                    manual_work_hours = NULL,
                    manual_ot_hours = NULL,
                    updated_at = datetime('now')
                WHERE staff_id = ? AND month = ?
            """, (sid, month_val))

            conn.commit()
            
            send_html(handler, page_attendance(
                {"month": month_val, "vendor_id": parse_int_or_none(vendor_id), "contract_id": parse_int_or_none(contract_id), "q": q},
                success_msg="Successfully cleared attendance data."
            ))
            return
        finally:
            conn.close()

    redirect(handler, redirect_url)


def to_xml_float(s: str | None) -> float | None:
    if s is None:
        return None
    s = s.strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def get_standard_working_days(year: int, month: int) -> float:
    num_days = calendar.monthrange(year, month)[1]
    workdays = 0
    for d in range(1, num_days + 1):
        if date(year, month, d).weekday() < 5:
            workdays += 1
    return float(workdays)


def get_attendance_actual_days_and_ot(conn, staff_id: int, month_val: str) -> tuple[float, float]:
    try:
        year = int(month_val.split("-")[0])
        month = int(month_val.split("-")[1])
    except Exception:
        return 0.0, 0.0
        
    month_start = f"{year:04d}-{month:02d}-01"
    month_end = f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
    
    row = conn.execute("""
        SELECT SUM(work_hours) AS sum_w, SUM(ot_hours) AS sum_ot
        FROM attendance
        WHERE staff_id = ? AND date >= ? AND date <= ?
    """, (staff_id, month_start, month_end)).fetchone()
    
    if row:
        sum_w = row["sum_w"] or 0.0
        sum_ot = row["sum_ot"] or 0.0
        return sum_w / 8.0, sum_ot * 1.5
    return 0.0, 0.0


def page_monthly_attendance(filters: dict, error_msg: str | None = None, success_msg: str | None = None):
    month_val = filters.get("month") or ""
    if not month_val:
        today = date.today()
        month_val = today.strftime("%Y-%m")
        
    try:
        year = int(month_val.split("-")[0])
        month = int(month_val.split("-")[1])
    except Exception:
        today = date.today()
        year, month = today.year, today.month
        month_val = today.strftime("%Y-%m")

    vendor_filter = parse_int_or_none(filters.get("vendor_id"))
    contract_filter = parse_int_or_none(filters.get("contract_id"))
    q_filter = (filters.get("q") or "").strip()

    conn = db_connect()
    try:
        if vendor_filter is not None and contract_filter is not None:
            c_row = conn.execute("SELECT 1 FROM contracts WHERE id=? AND seller_vendor_id=?", (contract_filter, vendor_filter)).fetchone()
            if not c_row:
                contract_filter = None

        # Load vendors and contracts for dropdowns
        vendors = conn.execute("SELECT id, COALESCE(company_name, company_name_vi) AS company_name FROM vendors WHERE is_active=1 AND purchasing=0").fetchall()
        if vendor_filter is not None:
            contracts = conn.execute("SELECT id, framework_no FROM contracts WHERE is_active=1 AND seller_vendor_id=?", (vendor_filter,)).fetchall()
        else:
            contracts = conn.execute("SELECT id, framework_no FROM contracts WHERE is_active=1").fetchall()

        # Build SQL to load staff WHOSE ATTENDANCE IS LOCKED for this month
        where = ["(s.status IS NULL OR s.status <> 'inactive')", "l.month = ?", "l.locked = 1"]
        params = [month_val]

        if vendor_filter is not None:
            where.append("s.vendor_id = ?")
            params.append(vendor_filter)
        if contract_filter is not None:
            where.append("s.contract_id = ?")
            params.append(contract_filter)
        if q_filter:
            where.append("s.full_name_vi LIKE ?")
            params.append(f"%{q_filter}%")

        where_sql = "WHERE " + " AND ".join(where)

        locked_staff = conn.execute(f"""
            SELECT s.id, s.full_name_vi, s.ot, s.work_shift, s.monthly_rate, s.manday_rate,
                   s.paid_leave_total_hours, s.paid_leave_used_hours,
                   COALESCE(v.company_name, v.company_name_vi) AS vendor_name,
                   c.framework_no AS contract_no
            FROM contract_staff s
            JOIN vendors v ON v.id=s.vendor_id
            JOIN contracts c ON c.id=s.contract_id
            JOIN attendance_locks l ON l.staff_id=s.id
            {where_sql}
            ORDER BY s.full_name_vi ASC
        """, params).fetchall()

        # Month standard days
        std_days_default = get_standard_working_days(year, month)

        # Month start/end dates
        month_start = f"{year:04d}-{month:02d}-01"
        month_end = f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"

        # Load raw work & OT hours from daily logs
        raw_hours_rows = conn.execute("""
            SELECT staff_id, SUM(work_hours) AS sum_w, SUM(ot_hours) AS sum_ot
            FROM attendance
            WHERE date >= ? AND date <= ?
            GROUP BY staff_id
        """, (month_start, month_end)).fetchall()
        raw_hours_map = {r["staff_id"]: (r["sum_w"] or 0.0, r["sum_ot"] or 0.0) for r in raw_hours_rows}

        # For each staff, load or initialize summary
        summaries = {}
        cur = conn.cursor()
        
        for s in locked_staff:
            sid = s["id"]
            row = conn.execute("""
                SELECT standard_days, actual_days, paid_leave_days, ot_converted_hours, daily_rate, total_amount, locked, manual_work_hours, manual_ot_hours
                FROM monthly_attendance_summary
                WHERE staff_id=? AND month=?
            """, (sid, month_val)).fetchone()

            sum_w, sum_ot = raw_hours_map.get(sid, (0.0, 0.0))
            calc_actual_days = sum_w / 8.0
            calc_ot_converted = sum_ot * 1.5

            if row:
                summary_data = dict(row)
                if summary_data["locked"] == 0:
                    # Auto update calculations from daily logs if not locked
                    std_days = summary_data["standard_days"]
                    pl_days = summary_data["paid_leave_days"]
                    
                    manual_w = summary_data.get("manual_work_hours")
                    manual_ot = summary_data.get("manual_ot_hours")
                    
                    actual_days = (manual_w if manual_w is not None else sum_w) / 8.0
                    ot_converted = (manual_ot if manual_ot is not None else sum_ot) * 1.5
                    
                    if s["manday_rate"] is not None and s["manday_rate"] > 0:
                        daily_rate = s["manday_rate"]
                    elif s["monthly_rate"] is not None and s["monthly_rate"] > 0:
                        daily_rate = s["monthly_rate"] / std_days if std_days > 0 else 0.0
                    else:
                        daily_rate = 0.0
                        
                    total_days = actual_days + pl_days
                    work_amt = round(total_days * daily_rate)
                    ot_rate = daily_rate / 8.0
                    ot_amt = round(ot_converted * ot_rate)
                    total_amount = work_amt + ot_amt
                    
                    cur.execute("""
                        UPDATE monthly_attendance_summary
                        SET actual_days = ?, ot_converted_hours = ?, daily_rate = ?, total_amount = ?, updated_at = datetime('now')
                        WHERE staff_id = ? AND month = ?
                    """, (actual_days, ot_converted, daily_rate, total_amount, sid, month_val))
                    
                    summary_data["actual_days"] = actual_days
                    summary_data["ot_converted_hours"] = ot_converted
                    summary_data["daily_rate"] = daily_rate
                    summary_data["total_amount"] = total_amount
                
                summaries[sid] = summary_data
            else:
                # Calculate defaults
                actual_days = calc_actual_days
                ot_converted = calc_ot_converted
                paid_leave_days = 0.0

                if s["manday_rate"] is not None and s["manday_rate"] > 0:
                    daily_rate = s["manday_rate"]
                elif s["monthly_rate"] is not None and s["monthly_rate"] > 0:
                    daily_rate = s["monthly_rate"] / std_days_default if std_days_default > 0 else 0.0
                else:
                    daily_rate = 0.0

                total_days = actual_days + paid_leave_days
                work_amt = round(total_days * daily_rate)
                ot_rate = daily_rate / 8.0
                ot_amt = round(ot_converted * ot_rate)
                total_amount = work_amt + ot_amt

                cur.execute("""
                    INSERT INTO monthly_attendance_summary (
                        staff_id, month, standard_days, actual_days, paid_leave_days,
                        ot_converted_hours, daily_rate, total_amount, locked, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, datetime('now'), datetime('now'))
                """, (sid, month_val, std_days_default, actual_days, paid_leave_days, ot_converted, daily_rate, total_amount))
                
                summaries[sid] = {
                    "standard_days": std_days_default,
                    "actual_days": actual_days,
                    "paid_leave_days": paid_leave_days,
                    "ot_converted_hours": ot_converted,
                    "daily_rate": daily_rate,
                    "total_amount": total_amount,
                    "locked": 0,
                    "manual_work_hours": None,
                    "manual_ot_hours": None
                }
        
        conn.commit()
    finally:
        conn.close()

    # Dropdowns HTML
    vendor_opts = ['<option value="">-- All Vendors --</option>']
    for v in vendors:
        sel = "selected" if vendor_filter == v["id"] else ""
        vendor_opts.append(f'<option value="{v["id"]}" {sel}>{escape(v["company_name"])}</option>')

    contract_opts = ['<option value="">-- All Contracts --</option>']
    for c in contracts:
        sel = "selected" if contract_filter == c["id"] else ""
        contract_opts.append(f'<option value="{c["id"]}" {sel}>{escape(c["framework_no"])}</option>')

    # Rows HTML
    trs = []
    total_billing_all = 0.0

    for s in locked_staff:
        sid = s["id"]
        sum_data = summaries[sid]
        
        is_m_locked = sum_data.get("locked", 0) == 1
        disabled_attr = "disabled" if is_m_locked else ""
        
        # Lock/unlock URL parameters
        act_qs = f"staff_id={sid}&month={month_val}&vendor_id={vendor_filter or ''}&contract_id={contract_filter or ''}&q={urllib.parse.quote(q_filter)}"
        
        if is_m_locked:
            m_lock_label = '🔒 <b style="color:#b00020;">Locked</b>'
            m_lock_action_html = f"""
            <div style="margin-top: 4px;">
              <a href="/attendance/monthly/unlock?{act_qs}" style="font-size: 9px; color: #b00020; background: #fff5f6; border: 1px solid #f1c0c6; padding: 2px 4px; border-radius: 4px; display: inline-block; font-weight: bold; text-decoration: none;">🔓 Unlock</a>
            </div>
            """
        else:
            m_lock_label = '<span class="muted" style="font-size: 9px;">Unlocked</span>'
            m_lock_action_html = f"""
            <div style="margin-top: 4px;">
              <a href="/attendance/monthly/lock?{act_qs}" style="font-size: 9px; color: #137333; background: #e6f4ea; border: 1px solid #b4e3be; padding: 2px 4px; border-radius: 4px; display: inline-block; font-weight: bold; text-decoration: none;">🔒 Lock Payroll</a>
            </div>
            """

        # Rate Label
        if s["manday_rate"] is not None and s["manday_rate"] > 0:
            rate_label = f"Daily: {fmt_money(s['manday_rate'])}"
        elif s["monthly_rate"] is not None and s["monthly_rate"] > 0:
            rate_label = f"Monthly: {fmt_money(s['monthly_rate'])}"
        else:
            rate_label = '<span class="muted">Not configured</span>'

        # Annual Leave Remaining
        tot_pl = s["paid_leave_total_hours"] or 0.0
        used_pl = s["paid_leave_used_hours"] or 0.0
        rem_pl_hours = tot_pl - used_pl
        rem_pl_days = rem_pl_hours / 8.0

        # Calculations
        pl = sum_data["paid_leave_days"]
        act = sum_data["actual_days"]
        daily_rate = sum_data["daily_rate"]
        ot_hours = sum_data["ot_converted_hours"]
        
        # Get raw hours for display
        raw_w, raw_ot = raw_hours_map.get(sid, (0.0, 0.0))

        work_pay = round((act + pl) * daily_rate)
        ot_pay = round(ot_hours * (daily_rate / 8.0))
        total_pay = sum_data["total_amount"]

        total_billing_all += total_pay

        trs.append(f"""
        <tr>
          <td>{sid}</td>
          <td>
            <b>{escape(s["full_name_vi"])}</b>
            <div class="muted" style="font-size:9px;">{escape(s["contract_no"])}</div>
            {m_lock_action_html}
          </td>
          <td>
            {escape(s["vendor_name"] or "")}
          </td>
          <td style="font-size:11px;">
            {escape(s["work_shift"] or "Not set")}
            <div class="muted" style="font-size:10px;">{rate_label}</div>
            <div style="margin-top:2px;">{m_lock_label}</div>
          </td>
          <!-- Standard days (editable) -->
          <td>
            <input type="number" step="0.5" name="std_{sid}" value="{sum_data['standard_days']:.1f}" {disabled_attr}
                   style="width: 55px; padding: 4px; font-size:12px; text-align:center;">
          </td>
          <!-- Actual days (read-only) -->
          <td style="text-align:center; font-weight:bold;">
            {sum_data['actual_days']:.2f}
          </td>
          <!-- Paid leave days (editable) -->
          <td>
            <input type="number" step="0.5" name="pl_{sid}" value="{sum_data['paid_leave_days']:.1f}" {disabled_attr}
                   style="width: 55px; padding: 4px; font-size:12px; text-align:center;">
            <div class="muted" style="font-size: 9px; margin-top:2px;">Remaining: {rem_pl_days:.2f} days</div>
          </td>
          <!-- OT converted hours (editable) -->
          <td>
            <input type="number" step="0.01" name="ot_{sid}" value="{sum_data['ot_converted_hours']:.2f}" {disabled_attr}
                   style="width: 65px; padding: 4px; font-size:12px; text-align:center;">
          </td>
          <!-- Hours Worked (Raw Hours) -->
          <td style="text-align:center; font-size:11px; font-family:monospace; line-height:1.3; vertical-align:middle;">
            <div>Work: {raw_w:.2f}h</div>
            <div style="color:#666;">OT: {raw_ot:.2f}h</div>
          </td>
          <!-- Daily rate (display) -->
          <td style="text-align:right; font-family:monospace;">
            {int(round(sum_data['daily_rate'])):,}
          </td>
          <!-- Total billing amount (display breakdown) -->
          <td style="text-align:right; font-family:monospace; line-height:1.3; font-size:11px;">
            <div style="color: #666;">Work: {int(work_pay):,}</div>
            <div style="color: #666;">OT: {int(ot_pay):,}</div>
            <div style="font-weight:bold; color:#0b57d0; font-size:12px; margin-top:2px; border-top:1px dashed #ddd; padding-top:2px;">
              Total: {int(total_pay):,} VND
            </div>
          </td>
        </tr>
        """)

    error_html = f"<div class='card danger'><b>Error:</b> {escape(error_msg)}</div>" if error_msg else ""
    success_html = f"<div class='card success' style='border-color:#b4e3be; background:#f4fbf6; color:#137333; padding:12px; border-radius:8px; margin-bottom:16px;'><b>Success:</b> {escape(success_msg)}</div>" if success_msg else ""

    sub_nav = f"""
    <div class="actions" style="margin-bottom: 14px; border-bottom: 1px solid #ddd; padding-bottom: 8px;">
      <a href="/attendance?month={month_val}&vendor_id={vendor_filter or ''}&contract_id={contract_filter or ''}&q={escape(q_filter)}" style="margin-right: 18px; font-weight: bold; color:#666; text-decoration:none;">📅 Daily Attendance</a>
      <a href="/attendance/monthly?month={month_val}&vendor_id={vendor_filter or ''}&contract_id={contract_filter or ''}&q={escape(q_filter)}" style="margin-right: 18px; font-weight: bold; color:#0b57d0; border-bottom: 2px solid #0b57d0; padding-bottom: 8px;">💵 Monthly Payroll & Payment</a>
      <a href="/attendance/import-bulk" style="font-weight: bold; color:#666; text-decoration:none;">📤 Bulk Import Face Logs</a>
    </div>
    """

    body = f"""
    {sub_nav}
    {error_html}
    {success_html}

    <!-- 1. Filters -->
    <div class="card">
      <form method="GET" action="/attendance/monthly" class="filters" style="margin: 0;">
        <div>
          <div class="label">Payment Month</div>
          <input type="month" name="month" value="{month_val}" onchange="this.form.submit()">
        </div>
        <div>
          <div class="label">Vendor</div>
          <select name="vendor_id" onchange="this.form.submit()">
            {''.join(vendor_opts)}
          </select>
        </div>
        <div>
          <div class="label">Framework Contract</div>
          <select name="contract_id" onchange="this.form.submit()">
            {''.join(contract_opts)}
          </select>
        </div>
        <div>
          <div class="label">Search staff</div>
          <input type="text" name="q" placeholder="Enter staff name..." value="{escape(q_filter)}">
        </div>
        <div class="actions">
          <button type="submit">Filter</button>
          <a class="muted" href="/attendance/monthly">Reset</a>
        </div>
      </form>
    </div>

    <!-- 2. Summary sheet form -->
    <form method="POST" action="/attendance/monthly/save">
      <input type="hidden" name="month" value="{month_val}">
      <input type="hidden" name="vendor_id" value="{vendor_filter or ''}">
      <input type="hidden" name="contract_id" value="{contract_filter or ''}">
      <input type="hidden" name="q" value="{escape(q_filter)}">

      <div class="card" style="padding:0; overflow-x:auto;">
        <table style="margin:0;">
          <thead>
            <tr>
              <th>ID</th>
              <th>Full Name</th>
              <th>Vendor</th>
              <th>Shift / Baseline Rate</th>
              <th style="width:75px; text-align:center;">Standard Days</th>
              <th style="width:75px; text-align:center;">Actual Days</th>
              <th style="width:75px; text-align:center;">Paid Leave</th>
              <th style="width:75px; text-align:center;">Converted OT Hours (x1.5)</th>
              <th style="text-align:center;">Hours Worked<br><span style="font-weight:normal; font-size:9px; color:#666;">(Work / Raw OT)</span></th>
              <th style="text-align:right;">Daily Rate</th>
              <th style="text-align:right;">Monthly Wages</th>
            </tr>
          </thead>
          <tbody>
            {''.join(trs) if trs else '<tr><td colspan="11" class="muted" style="padding:15px;">No staff with locked daily attendance matches the filter for this month. Please lock daily attendance first.</td></tr>'}
          </tbody>
        </table>
      </div>

      {f'''
      <div style="display:flex; justify-content:space-between; align-items:center; margin-top:20px;">
        <div class="actions">
          <button type="submit" style="background:#0b57d0; color:#fff; border-color:#0b57d0; font-weight:600; padding:10px 24px;">Save Calculations</button>
          <a href="/attendance/monthly/export?month={month_val}&vendor_id={vendor_filter or ''}&contract_id={contract_filter or ''}&q={escape(q_filter)}" class="btn btn-secondary" style="padding:10px 20px;">Export to Excel (CSV)</a>
        </div>
        <div style="font-size:18px; font-weight:bold; color:#111;">
          Total Monthly Payment: <span style="color:#0b57d0; font-size:20px;">{int(round(total_billing_all)):,} VND</span>
        </div>
      </div>
      ''' if trs else ''}
    </form>
    """
    
    return layout(f"Monthly Payroll - Month {month:02d}/{year:04d}", body)


def handle_attendance_monthly_save_post(handler):
    length = int(handler.headers.get("Content-Length", 0))
    raw = handler.rfile.read(length).decode("utf-8", errors="ignore")
    import urllib.parse
    form = urllib.parse.parse_qs(raw, keep_blank_values=True)

    month_val = form.get("month", [""])[0].strip()
    vendor_id = form.get("vendor_id", [""])[0].strip()
    contract_id = form.get("contract_id", [""])[0].strip()
    q = form.get("q", [""])[0].strip()
    
    redirect_url = f"/attendance/monthly?month={month_val}&vendor_id={vendor_id}&contract_id={contract_id}&q={q}"

    updates = {} # sid -> {"std": val, "pl": val, "ot": val}
    for key, vals in form.items():
        if key.startswith("std_"):
            sid = int(key.split("_")[1])
            updates.setdefault(sid, {})["std"] = to_xml_float(vals[0]) or 0.0
        elif key.startswith("pl_"):
            sid = int(key.split("_")[1])
            updates.setdefault(sid, {})["pl"] = to_xml_float(vals[0]) or 0.0
        elif key.startswith("ot_"):
            sid = int(key.split("_")[1])
            updates.setdefault(sid, {})["ot"] = to_xml_float(vals[0]) or 0.0

    conn = db_connect()
    try:
        # Load locks for this month
        locks_rows = conn.execute("SELECT staff_id FROM monthly_attendance_summary WHERE month=? AND locked=1", (month_val,)).fetchall()
        locked_staff_ids = {r["staff_id"] for r in locks_rows}

        cur = conn.cursor()
        
        # Load staff rates and paid leave balances
        staff_data = {}
        staff_rows = conn.execute("""
            SELECT id, full_name_vi, monthly_rate, manday_rate, paid_leave_total_hours, paid_leave_used_hours
            FROM contract_staff
        """).fetchall()
        for s in staff_rows:
            staff_data[s["id"]] = s

        # Perform validation for each updated staff
        for sid, vals in updates.items():
            if sid in locked_staff_ids:
                continue # Skip locked staff member from validation checks
            s = staff_data[sid]
            pl_days = vals.get("pl", 0.0)
            
            # Annual Leave remaining validation
            tot_pl = s["paid_leave_total_hours"] or 0.0
            used_pl = s["paid_leave_used_hours"] or 0.0
            rem_pl_hours = tot_pl - used_pl
            
            pl_hours_input = pl_days * 8.0
            if pl_hours_input > rem_pl_hours:
                rem_days = rem_pl_hours / 8.0
                err_msg = f"Paid leave days ({pl_days:.1f} days) for employee '{s['full_name_vi']}' exceeds remaining balance (only {rem_days:.2f} days remaining)."
                send_html(handler, page_monthly_attendance(
                    {"month": month_val, "vendor_id": vendor_id, "contract_id": contract_id, "q": q},
                    error_msg=err_msg
                ))
                return

        # Perform updates
        for sid, vals in updates.items():
            if sid in locked_staff_ids:
                continue # Skip locked staff member from saving monthly summary updates
            s = staff_data[sid]
            std = vals.get("std", 0.0)
            pl = vals.get("pl", 0.0)
            ot = vals.get("ot", 0.0)
            
            # Check if manual_work_hours is set in monthly summary
            summary_row = conn.execute("""
                SELECT manual_work_hours FROM monthly_attendance_summary
                WHERE staff_id=? AND month=?
            """, (sid, month_val)).fetchone()
            
            manual_w = summary_row["manual_work_hours"] if summary_row else None
            
            if manual_w is not None:
                actual_days = manual_w / 8.0
            else:
                actual_days, _ = get_attendance_actual_days_and_ot(conn, sid, month_val)

            # Calculate daily rate
            if s["manday_rate"] is not None and s["manday_rate"] > 0:
                daily_rate = s["manday_rate"]
            elif s["monthly_rate"] is not None and s["monthly_rate"] > 0:
                daily_rate = s["monthly_rate"] / std if std > 0 else 0.0
            else:
                daily_rate = 0.0

            # Recalculate amount
            total_days = actual_days + pl
            work_amt = round(total_days * daily_rate)
            ot_rate = daily_rate / 8.0
            ot_amt = round(ot * ot_rate)
            total_amount = work_amt + ot_amt

            cur.execute("""
                UPDATE monthly_attendance_summary
                SET standard_days=?, paid_leave_days=?, ot_converted_hours=?, daily_rate=?, total_amount=?, updated_at=datetime('now')
                WHERE staff_id=? AND month=?
            """, (std, pl, ot, daily_rate, total_amount, sid, month_val))

        conn.commit()
    finally:
        conn.close()

    # Success redirection
    redirect(handler, redirect_url)


def handle_attendance_monthly_lock_get(handler):
    parsed = urllib.parse.urlparse(handler.path)
    qs = urllib.parse.parse_qs(parsed.query)

    sid = parse_int_or_none(qs.get("staff_id", [""])[0])
    month_val = (qs.get("month", [""])[0] or "").strip()
    
    vendor_id = qs.get("vendor_id", [""])[0].strip()
    contract_id = qs.get("contract_id", [""])[0].strip()
    q = qs.get("q", [""])[0].strip()
    
    redirect_url = f"/attendance/monthly?month={month_val}&vendor_id={vendor_id}&contract_id={contract_id}&q={q}"

    if sid and month_val:
        conn = db_connect()
        try:
            # Verify daily attendance is locked
            daily_locked = conn.execute("""
                SELECT 1 FROM attendance_locks
                WHERE staff_id=? AND month=? AND locked=1
            """, (sid, month_val)).fetchone()
            if not daily_locked:
                send_html(handler, page_monthly_attendance(
                    {"month": month_val, "vendor_id": parse_int_or_none(vendor_id), "contract_id": parse_int_or_none(contract_id), "q": q},
                    error_msg="Cannot lock monthly payroll because daily attendance is not locked."
                ))
                return

            conn.execute("""
                UPDATE monthly_attendance_summary
                SET locked=1, updated_at=datetime('now')
                WHERE staff_id=? AND month=?
            """, (sid, month_val))
            conn.commit()
        finally:
            conn.close()

    redirect(handler, redirect_url)


def handle_attendance_monthly_unlock_get(handler):
    parsed = urllib.parse.urlparse(handler.path)
    qs = urllib.parse.parse_qs(parsed.query)

    sid = parse_int_or_none(qs.get("staff_id", [""])[0])
    month_val = (qs.get("month", [""])[0] or "").strip()
    
    vendor_id = qs.get("vendor_id", [""])[0].strip()
    contract_id = qs.get("contract_id", [""])[0].strip()
    q = qs.get("q", [""])[0].strip()
    
    redirect_url = f"/attendance/monthly?month={month_val}&vendor_id={vendor_id}&contract_id={contract_id}&q={q}"

    if sid and month_val:
        conn = db_connect()
        try:
            conn.execute("""
                UPDATE monthly_attendance_summary
                SET locked=0, updated_at=datetime('now')
                WHERE staff_id=? AND month=?
            """, (sid, month_val))
            conn.commit()
        finally:
            conn.close()

    redirect(handler, redirect_url)


def send_json(handler, data_dict: dict, status=200):
    import json
    data = json.dumps(data_dict).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def handle_attendance_save_cell_post(handler):
    try:
        length = int(handler.headers.get("Content-Length", 0))
        raw = handler.rfile.read(length).decode("utf-8", errors="ignore")
        import json
        data = json.loads(raw)
        
        staff_id = parse_int_or_none(data.get("staff_id"))
        date_str = (data.get("date") or "").strip()
        field_type = (data.get("type") or "").strip()
        val_raw = data.get("value")
        
        if not staff_id or not date_str or field_type not in ("w", "ot"):
            send_json(handler, {"status": "error", "message": "Invalid parameters"}, status=400)
            return
            
        parts = date_str.split("-")
        if len(parts) != 3:
            send_json(handler, {"status": "error", "message": "Invalid date format"}, status=400)
            return
        month_val = f"{parts[0]}-{parts[1]}"
        
        conn = db_connect()
        try:
            # Check daily lock
            locked_daily = conn.execute("""
                SELECT 1 FROM attendance_locks
                WHERE staff_id=? AND month=? AND locked=1
            """, (staff_id, month_val)).fetchone()
            if locked_daily:
                send_json(handler, {"status": "error", "message": "This staff member's daily attendance for this month is locked."}, status=403)
                return
                
            # Check monthly lock
            locked_monthly = conn.execute("""
                SELECT 1 FROM monthly_attendance_summary
                WHERE staff_id=? AND month=? AND locked=1
            """, (staff_id, month_val)).fetchone()
            if locked_monthly:
                send_json(handler, {"status": "error", "message": "This staff member's monthly payroll for this month is locked."}, status=403)
                return
                
            if isinstance(val_raw, (int, float)):
                val = float(val_raw)
            else:
                val = to_xml_float(val_raw) if val_raw not in (None, "") else 0.0
            if val is None:
                val = 0.0
                
            existing = conn.execute("""
                SELECT work_hours, ot_hours FROM attendance
                WHERE staff_id=? AND date=?
            """, (staff_id, date_str)).fetchone()
            
            work_hours = val if field_type == "w" else (existing["work_hours"] if existing else 0.0)
            ot_hours = val if field_type == "ot" else (existing["ot_hours"] if existing else 0.0)
            
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO attendance (staff_id, date, work_hours, ot_hours, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(staff_id, date) DO UPDATE SET
                    work_hours=excluded.work_hours,
                    ot_hours=excluded.ot_hours,
                    updated_at=datetime('now')
            """, (staff_id, date_str, work_hours, ot_hours))
            conn.commit()
            
            send_json(handler, {"status": "ok"})
        finally:
            conn.close()
            
    except Exception as e:
        send_json(handler, {"status": "error", "message": str(e)}, status=500)


def handle_attendance_monthly_export_get(handler):
    import csv
    import io
    import urllib.parse
    
    parsed = urllib.parse.urlparse(handler.path)
    qs = urllib.parse.parse_qs(parsed.query)
    
    month_val = qs.get("month", [""])[0].strip()
    if not month_val:
        month_val = date.today().strftime("%Y-%m")
        
    try:
        year = int(month_val.split("-")[0])
        month = int(month_val.split("-")[1])
    except Exception:
        today = date.today()
        year, month = today.year, today.month
        month_val = today.strftime("%Y-%m")

    vendor_filter = parse_int_or_none(qs.get("vendor_id", [""])[0])
    contract_filter = parse_int_or_none(qs.get("contract_id", [""])[0])
    q_filter = qs.get("q", [""])[0].strip()

    conn = db_connect()
    try:
        # Build SQL where clause
        where = ["(s.status IS NULL OR s.status <> 'inactive')", "l.month = ?", "l.locked = 1"]
        params = [month_val]

        if vendor_filter is not None:
            where.append("s.vendor_id = ?")
            params.append(vendor_filter)
        if contract_filter is not None:
            where.append("s.contract_id = ?")
            params.append(contract_filter)
        if q_filter:
            where.append("s.full_name_vi LIKE ?")
            params.append(f"%{q_filter}%")

        where_sql = "WHERE " + " AND ".join(where)

        locked_staff = conn.execute(f"""
            SELECT s.id, s.full_name_vi, s.ot, s.work_shift, s.monthly_rate, s.manday_rate,
                   COALESCE(v.company_name, v.company_name_vi) AS vendor_name,
                   c.framework_no AS contract_no
            FROM contract_staff s
            JOIN vendors v ON v.id=s.vendor_id
            JOIN contracts c ON c.id=s.contract_id
            JOIN attendance_locks l ON l.staff_id=s.id
            {where_sql}
            ORDER BY s.full_name_vi ASC
        """, params).fetchall()

        # Get summaries
        summaries = {}
        for s in locked_staff:
            sid = s["id"]
            row = conn.execute("""
                SELECT standard_days, actual_days, paid_leave_days, ot_converted_hours, daily_rate, total_amount, locked
                FROM monthly_attendance_summary
                WHERE staff_id=? AND month=?
            """, (sid, month_val)).fetchone()
            if row:
                summaries[sid] = dict(row)

        # Get raw work and OT hours
        num_days = calendar.monthrange(year, month)[1]
        month_start = f"{year:04d}-{month:02d}-01"
        month_end = f"{year:04d}-{month:02d}-{num_days:02d}"
        
        raw_hours_rows = conn.execute("""
            SELECT staff_id, SUM(work_hours) AS sum_w, SUM(ot_hours) AS sum_ot
            FROM attendance
            WHERE date >= ? AND date <= ?
            GROUP BY staff_id
        """, (month_start, month_end)).fetchall()
        raw_hours_map = {r["staff_id"]: (r["sum_w"] or 0.0, r["sum_ot"] or 0.0) for r in raw_hours_rows}

    finally:
        conn.close()

    # Generate CSV content
    output = io.StringIO()
    # Write UTF-8 BOM
    output.write('\ufeff')
    writer = csv.writer(output, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
    
    # Headers
    writer.writerow([
        "Staff ID", "Full Name", "Vendor", "Contract No", "Shift", "OT (Yes/No)",
        "Standard Days", "Actual Days", "Paid Leave Days", "Converted OT Hours (x1.5)",
        "Raw Work Hours", "Raw OT Hours", "Daily Rate (VND)", "Work Wage (VND)",
        "OT Wage (VND)", "Total Wage (VND)", "Status"
    ])
    
    for s in locked_staff:
        sid = s["id"]
        sum_data = summaries.get(sid)
        if not sum_data:
            continue
            
        pl = sum_data["paid_leave_days"]
        act = sum_data["actual_days"]
        daily_rate = sum_data["daily_rate"]
        ot_hours = sum_data["ot_converted_hours"]
        total_pay = sum_data["total_amount"]
        is_locked = "Locked" if sum_data["locked"] == 1 else "Unlocked"
        
        raw_w, raw_ot = raw_hours_map.get(sid, (0.0, 0.0))
        work_pay = round((act + pl) * daily_rate)
        ot_pay = round(ot_hours * (daily_rate / 8.0))
        
        writer.writerow([
            sid,
            s["full_name_vi"],
            s["vendor_name"],
            s["contract_no"],
            s["work_shift"] or "",
            "Yes" if s["ot"] == 1 else "No",
            f"{sum_data['standard_days']:.1f}",
            f"{act:.2f}",
            f"{pl:.1f}",
            f"{ot_hours:.2f}",
            f"{raw_w:.2f}",
            f"{raw_ot:.2f}",
            f"{int(round(daily_rate))}",
            f"{work_pay}",
            f"{ot_pay}",
            f"{int(round(total_pay))}",
            is_locked
        ])
        
    csv_bytes = output.getvalue().encode("utf-8")
    
    handler.send_response(200)
    handler.send_header("Content-Type", "text/csv; charset=utf-8")
    handler.send_header("Content-Length", str(len(csv_bytes)))
    handler.send_header("Content-Disposition", f'attachment; filename="Monthly_Payroll_{month_val}.csv"')
    handler.end_headers()
    handler.wfile.write(csv_bytes)


def page_attendance_import_bulk(handler, error_msg=None, success_msg=None, unmatched_names=None, locked_names=None, imported_names=None):
    today = date.today()
    month_val = today.strftime("%Y-%m")
    
    error_html = f"<div class='card danger'><b>Error:</b> {escape(error_msg)}</div>" if error_msg else ""
    success_html = f"<div class='card success' style='border-color:#b4e3be; background:#f4fbf6; color:#137333; padding:12px; border-radius:8px; margin-bottom:16px;'><b>Success:</b> {escape(success_msg)}</div>" if success_msg else ""
    
    unmatched_html = ""
    if unmatched_names:
        unmatched_html = f"""
        <div class="card warning" style="border-left: 4px solid var(--warning); padding: 15px; margin-top: 15px;">
          <h4 style="margin: 0 0 8px 0; color: var(--warning);">⚠️ Skip: Không tìm thấy nhân sự trong DB ({len(unmatched_names)})</h4>
          <ul style="margin: 0; padding-left: 20px; font-size: 13px; color: var(--text-secondary); max-height: 200px; overflow-y: auto;">
            {"".join([f"<li>{escape(name)}</li>" for name in unmatched_names])}
          </ul>
        </div>
        """
        
    locked_html = ""
    if locked_names:
        locked_html = f"""
        <div class="card danger" style="border-left: 4px solid var(--danger); padding: 15px; margin-top: 15px;">
          <h4 style="margin: 0 0 8px 0; color: var(--danger);">🔒 Skip: Nhân sự đã bị khóa bảng công trong tháng ({len(locked_names)})</h4>
          <ul style="margin: 0; padding-left: 20px; font-size: 13px; color: var(--text-secondary); max-height: 200px; overflow-y: auto;">
            {"".join([f"<li>{escape(name)}</li>" for name in locked_names])}
          </ul>
        </div>
        """
        
    imported_html = ""
    if imported_names:
        imported_html = f"""
        <div class="card success" style="border-left: 4px solid var(--success); padding: 15px; margin-top: 15px;">
          <h4 style="margin: 0 0 8px 0; color: var(--success);">✓ Đã import thành công ({len(imported_names)})</h4>
          <ul style="margin: 0; padding-left: 20px; font-size: 13px; color: var(--text-secondary); max-height: 200px; overflow-y: auto;">
            {"".join([f"<li>{escape(name)}</li>" for name in imported_names])}
          </ul>
        </div>
        """
    
    sub_nav = f"""
    <div class="actions" style="margin-bottom: 14px; border-bottom: 1px solid #ddd; padding-bottom: 8px;">
      <a href="/attendance?month={month_val}" style="margin-right: 18px; font-weight: bold; color:#666; text-decoration:none;">📅 Daily Attendance</a>
      <a href="/attendance/monthly?month={month_val}" style="margin-right: 18px; font-weight: bold; color:#666; text-decoration:none;">💵 Monthly Payroll & Payment</a>
      <a href="/attendance/import-bulk" style="font-weight: bold; color:#0b57d0; border-bottom: 2px solid #0b57d0; padding-bottom: 8px;">📤 Bulk Import Face Logs</a>
    </div>
    """
    
    body = f"""
    {sub_nav}
    {error_html}
    {success_html}
    {imported_html}
    {locked_html}
    {unmatched_html}

    <div class="card" style="margin-top: 15px;">
      <h3 style="margin-top: 0;">Import dữ liệu chấm công từ Thư mục</h3>
      <p class="muted" style="margin-bottom: 20px;">
        Hệ thống sẽ tự động quét tất cả tệp <code>.csv</code> trong thư mục được chọn hoặc nhập, bóc tách tên nhân viên từ cột <code>User</code> (ví dụ: <code>378(Can Duy Hung)</code>) và đối khớp với cơ sở dữ liệu.
      </p>

      <form method="POST" action="/attendance/import-bulk" enctype="multipart/form-data">
        <div style="margin-bottom: 16px; max-width: 320px;">
          <div class="label">Chọn Tháng Đối Soát Chấm Công</div>
          <input type="month" name="month" value="{month_val}" required style="width: 100%;">
        </div>

        <div style="margin-bottom: 20px; padding: 16px; border: 1px dashed var(--border); border-radius: 8px; background: #fafafa;">
          <h4 style="margin:0 0 12px 0;">Cách 1: Chọn thư mục trực tiếp từ trình duyệt (Upload Folder)</h4>
          <input type="file" name="files" webkitdirectory directory multiple style="width: 100%; padding: 6px; border: 1px solid var(--border); border-radius: 6px; background: #fff;">
          <div class="muted" style="margin-top: 6px;">Trình duyệt sẽ tự động upload toàn bộ các file CSV chấm công trong thư mục bạn chọn.</div>
        </div>

        <div style="margin-bottom: 24px; padding: 16px; border: 1px dashed var(--border); border-radius: 8px; background: #fafafa;">
          <h4 style="margin:0 0 12px 0;">Cách 2: Nhập đường dẫn thư mục tuyệt đối trên Server</h4>
          <input type="text" name="local_path" placeholder="Ví dụ: /Users/username/data/attendance_logs" style="width: 100%;">
          <div class="muted" style="margin-top: 6px;">Dùng khi file chấm công đã có sẵn trên máy chủ chạy phần mềm.</div>
        </div>

        <div>
          <button type="submit" style="background:#0b57d0; color:#fff; border-color:#0b57d0; font-weight:600; padding: 10px 24px;">Bắt đầu Import thư mục</button>
        </div>
      </form>
    </div>
    """
    return layout("Bulk Import Attendance", body)


def handle_attendance_import_bulk_post(handler):
    form = parse_multipart_attendance(handler)
    month_val = form.get("month", [""])[0].strip()
    
    if not month_val:
        send_html(handler, page_attendance_import_bulk(handler, error_msg="Vui lòng chọn tháng đối soát."))
        return
        
    raw_records = []
    
    # 1. Option 1: Browser folder upload
    file_list = form.get("files", [])
    valid_files = [f for f in file_list if isinstance(f, dict) and f.get("filename") and f["filename"].lower().endswith(".csv") and len(f.get("content", b"")) > 0]
    
    if valid_files:
        for f_info in valid_files:
            records = parse_attendance_csv(f_info["content"])
            raw_records.extend(records)
    else:
        # Option 2: Server local path
        local_path_raw = form.get("local_path", [""])[0].strip()
        if local_path_raw:
            p_obj = Path(local_path_raw)
            if not p_obj.exists() or not p_obj.is_dir():
                send_html(handler, page_attendance_import_bulk(handler, error_msg=f"Đường dẫn thư mục không tồn tại hoặc không phải thư mục: {local_path_raw}"))
                return
            csv_files = list(p_obj.glob("*.csv"))
            if not csv_files:
                send_html(handler, page_attendance_import_bulk(handler, error_msg=f"Không tìm thấy file .csv nào trong thư mục: {local_path_raw}"))
                return
            for path in csv_files:
                try:
                    content = path.read_bytes()
                    records = parse_attendance_csv(content)
                    raw_records.extend(records)
                except Exception:
                    pass
                    
    if not raw_records:
        send_html(handler, page_attendance_import_bulk(handler, error_msg="Vui lòng chọn thư mục upload từ trình duyệt hoặc nhập đường dẫn thư mục tuyệt đối trên Server chứa file CSV hợp lệ."))
        return
        
    # Group timestamps by (cleaned_name, date_str)
    user_date_timestamps = {}
    for name, ts_str in raw_records:
        dt = parse_dt(ts_str)
        if not dt:
            continue
        # Only process logs that fall within the selected month!
        ts_month = dt.strftime("%Y-%m")
        if ts_month != month_val:
            continue
            
        d_str = dt.strftime("%Y-%m-%d")
        user_date_timestamps.setdefault(name, {}).setdefault(d_str, []).append(dt)
        
    if not user_date_timestamps:
        send_html(handler, page_attendance_import_bulk(handler, error_msg=f"Không tìm thấy log chấm công nào thuộc tháng đã chọn ({month_val}) trong các file CSV."))
        return

    # 2. Fetch all active staff
    conn = db_connect()
    try:
        staff_rows = conn.execute("""
            SELECT id, full_name_vi, ot, work_shift
            FROM contract_staff
            WHERE status IS NULL OR status <> 'inactive'
        """).fetchall()
        
        # Build normalized name mapping: norm_name -> staff_row
        staff_map = {}
        for s in staff_rows:
            norm = remove_accents(s["full_name_vi"])
            staff_map[norm] = s
            
        # Load existing locked staff for this month
        locks_rows = conn.execute("SELECT staff_id FROM attendance_locks WHERE month=? AND locked=1", (month_val,)).fetchall()
        locked_staff_ids = {r["staff_id"] for r in locks_rows}
        
        # Results reports
        imported_names = []
        locked_names = []
        unmatched_names = set()
        
        ok_count = 0
        cur = conn.cursor()
        
        # 3. Process logs
        for raw_name, date_map in user_date_timestamps.items():
            # Match name
            norm_raw_name = remove_accents(raw_name)
            if norm_raw_name not in staff_map:
                unmatched_names.add(raw_name)
                continue
                
            s = staff_map[norm_raw_name]
            sid = s["id"]
            full_name = s["full_name_vi"]
            
            # Check lock
            if sid in locked_staff_ids:
                locked_names.append(f"{full_name} (ID: {sid})")
                continue
                
            # Process daily entries
            staff_ok_count = 0
            for d_str, dts in date_map.items():
                if not dts:
                    continue
                dts.sort()
                
                check_in_dt = dts[0]
                check_out_dt = dts[-1]
                
                check_in_str = check_in_dt.strftime("%H:%M")
                check_out_str = check_out_dt.strftime("%H:%M")
                
                # Duration
                dur_hours = (check_out_dt - check_in_dt).total_seconds() / 3600.0
                
                # Check lunch break (12:00 -> 13:00)
                if check_in_dt.hour < 12 and check_out_dt.hour >= 13:
                    net_hours = dur_hours - 1.0
                elif dur_hours > 4.0:
                    net_hours = dur_hours - 1.0
                else:
                    net_hours = dur_hours
                    
                net_hours = max(0.0, net_hours)
                
                std_limit = 8.0
                work_hours = min(std_limit, net_hours)
                ot_hours = 0.0
                
                # OT Calculation
                if s["ot"] == 1:
                    shift_out_hour = 17.0
                    shift_str = s["work_shift"] or ""
                    if " - " in shift_str:
                        try:
                            out_part = shift_str.split(" - ")[1]
                            h_part, m_part = map(int, out_part.split(":"))
                            shift_out_hour = h_part + (m_part / 60.0)
                        except Exception:
                            pass
                            
                    check_out_hour = check_out_dt.hour + (check_out_dt.minute / 60.0)
                    if check_out_hour > shift_out_hour:
                        ot_hours = check_out_hour - shift_out_hour
                        ot_hours = round(ot_hours, 1)
                        ot_hours = max(0.0, ot_hours)
                        
                work_hours = round(work_hours, 1)
                
                # Save to database
                cur.execute("""
                    INSERT INTO attendance (staff_id, date, check_in, check_out, work_hours, ot_hours, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                    ON CONFLICT(staff_id, date) DO UPDATE SET
                        check_in=excluded.check_in,
                        check_out=excluded.check_out,
                        work_hours=excluded.work_hours,
                        ot_hours=excluded.ot_hours,
                        updated_at=datetime('now')
                """, (sid, d_str, check_in_str, check_out_str, work_hours, ot_hours))
                
                staff_ok_count += 1
                
            if staff_ok_count > 0:
                ok_count += staff_ok_count
                imported_names.append(f"{full_name} (ID: {sid}) - {staff_ok_count} ngày công")
                
        conn.commit()
    finally:
        conn.close()
        
    success_msg = f"Đã hoàn thành xử lý file nhận diện khuôn mặt hàng loạt. Tổng cộng import thành công {ok_count} dòng ghi nhận công."
    send_html(handler, page_attendance_import_bulk(
        handler, 
        success_msg=success_msg,
        imported_names=imported_names,
        locked_names=locked_names,
        unmatched_names=sorted(list(unmatched_names))
    ))


