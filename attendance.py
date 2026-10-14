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
    annex_filter = parse_int_or_none(filters.get("annex_id"))
    q_filter = (filters.get("q") or "").strip()

    conn = db_connect()
    try:
        if vendor_filter is not None and contract_filter is not None:
            c_row = conn.execute("SELECT 1 FROM contracts WHERE id=? AND seller_vendor_id=?", (contract_filter, vendor_filter)).fetchone()
            if not c_row:
                contract_filter = None

        if contract_filter is not None and annex_filter is not None:
            a_row = conn.execute("SELECT 1 FROM contract_annexes WHERE id=? AND contract_id=?", (annex_filter, contract_filter)).fetchone()
            if not a_row:
                annex_filter = None

        # Load vendors (purchasing=0)
        vendors = conn.execute("SELECT id, COALESCE(company_name, company_name_vi) AS company_name, tax_id FROM vendors WHERE is_active=1 AND purchasing=0").fetchall()
        
        # Load contracts
        if vendor_filter is not None:
            contracts = conn.execute("SELECT id, framework_no, framework_name FROM contracts WHERE is_active=1 AND seller_vendor_id=?", (vendor_filter,)).fetchall()
        else:
            contracts = conn.execute("SELECT id, framework_no, framework_name FROM contracts WHERE is_active=1").fetchall()

        # Load annexes
        annexes = conn.execute("SELECT a.id, a.contract_id, a.annex_name, c.seller_vendor_id FROM contract_annexes a JOIN contracts c ON c.id = a.contract_id WHERE a.is_active=1 AND a.deleted_at IS NULL").fetchall()

        # Build SQL where
        first_day_str = f"{month_val}-01"
        last_day_str = f"{month_val}-{num_days:02d}"

        where = []
        join_params = [last_day_str, first_day_str]
        params = []

        if vendor_filter is not None:
            where.append("s.vendor_id = ?")
            params.append(vendor_filter)
        if contract_filter is not None:
            where.append("l.contract_id = ?")
            params.append(contract_filter)
        if annex_filter is not None:
            where.append("l.annex_id = ?")
            params.append(annex_filter)
        if q_filter:
            where.append("s.full_name_vi LIKE ?")
            params.append(f"%{q_filter}%")

        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        # Load staff active in month or having records in month
        staff_list = conn.execute(f"""
            SELECT s.id, s.full_name_vi, s.status, s.ot, s.work_shift,
                   COALESCE(v.company_name, v.company_name_vi) AS vendor_name,
                   c.framework_no AS contract_no,
                   an.annex_name
            FROM contract_staff s
            JOIN vendors v ON v.id=s.vendor_id
            JOIN contract_staff_links l ON l.staff_id = s.id 
                AND l.joining_date <= ? 
                AND (l.tentative_leaving_date IS NULL OR l.tentative_leaving_date = '' OR l.tentative_leaving_date >= ?)
            JOIN contracts c ON c.id=l.contract_id
            LEFT JOIN contract_annexes an ON an.id=l.annex_id
            {where_sql}
            ORDER BY vendor_name ASC, s.full_name_vi ASC
        """, join_params + params).fetchall()

        # Load staff for Import section
        import_staff_list = conn.execute(f"""
            SELECT s.id, s.full_name_vi, s.work_shift, s.ot, COALESCE(v.company_name, v.company_name_vi) AS company_name
            FROM contract_staff s
            JOIN vendors v ON v.id = s.vendor_id
            JOIN contract_staff_links l ON l.staff_id = s.id 
                AND l.joining_date <= ? 
                AND (l.tentative_leaving_date IS NULL OR l.tentative_leaving_date = '' OR l.tentative_leaving_date >= ?)
            {where_sql}
            ORDER BY company_name ASC, s.full_name_vi ASC
        """, join_params + params).fetchall()

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
    for idx, s in enumerate(staff_list, 1):
        sid = s["id"]
        
        is_locked = sid in locked_staff_ids
        disabled_attr = "disabled" if is_locked else ""
        
        # Lock/unlock URL parameters
        act_qs = f"staff_id={sid}&month={month_val}&vendor_id={vendor_filter or ''}&contract_id={contract_filter or ''}&annex_id={annex_filter or ''}&q={urllib.parse.quote(q_filter)}"
        
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
          <td class="sticky-col1" style="font-size: 11px; text-align: center;">{idx}</td>
          <td class="sticky-col2" style="font-size: 12px;">
            <b>{escape(s["full_name_vi"])}</b>{f' <span class="tag tag-deactive" style="font-size:9px; padding:1px 4px;">Inactive</span>' if ("status" in s.keys() and s["status"] and s["status"].strip().lower() == "inactive") else ""}
            <div class="muted" style="font-size: 9px;">{escape(s["contract_no"])}{f' - {escape(s["annex_name"])}' if s["annex_name"] else ''}</div>
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
      <a href="/attendance?month={month_val}&vendor_id={vendor_filter or ''}&contract_id={contract_filter or ''}&annex_id={annex_filter or ''}&q={escape(q_filter)}" style="margin-right: 18px; font-weight: bold; color:#0b57d0; border-bottom: 2px solid #0b57d0; padding-bottom: 8px;">📅 Daily Attendance</a>
      <a href="/attendance/monthly?month={month_val}&vendor_id={vendor_filter or ''}&contract_id={contract_filter or ''}&annex_id={annex_filter or ''}&q={escape(q_filter)}" style="margin-right: 18px; font-weight: bold; color:#666; text-decoration:none;">💵 Monthly Payroll</a>
      <a href="/attendance/acceptance?month={month_val}&vendor_id={vendor_filter or ''}&contract_id={contract_filter or ''}&annex_id={annex_filter or ''}&q={escape(q_filter)}" style="margin-right: 18px; font-weight: bold; color:#666; text-decoration:none;">📜 Attendance Acceptance</a>
      <a href="/attendance/cashout" style="margin-right: 18px; font-weight: bold; color:#666; text-decoration:none;">💰 Cash-out</a>
    </div>
    """

    annex_opts = ['<option value="">-- All Annexes --</option>']
    for a in annexes:
        sel = "selected" if annex_filter == a["id"] else ""
        annex_opts.append(f'<option value="{a["id"]}" data-contract-id="{a["contract_id"]}" data-vendor-id="{a["seller_vendor_id"]}" {sel}>{escape(a["annex_name"])}</option>')

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
          <select id="vendor_id" name="vendor_id" onchange="this.form.submit()">
            {''.join(vendor_opts)}
          </select>
        </div>
        <div>
          <div class="label">Framework Contract</div>
          <select id="contract_id" name="contract_id" onchange="this.form.submit()">
            {''.join(contract_opts)}
          </select>
        </div>
        <div>
          <div class="label">Annex (filtered by Framework)</div>
          <select id="annex_id" name="annex_id" onchange="this.form.submit()">
            {''.join(annex_opts)}
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
        <input type="hidden" name="annex_id" value="{annex_filter or ''}">
        <input type="hidden" name="q" value="{escape(q_filter)}">
        
        <div style="max-height: 250px; overflow-y: auto; border: 1px solid var(--border); border-radius: 8px; margin-bottom: 12px; background: #fff; box-shadow: var(--shadow-sm);">
          <table style="width: 100%; border: none; margin: 0; border-collapse: collapse;">
            <thead>
              <tr style="background: #f1f5f9;">
                <th style="padding: 8px 12px; text-align: left; font-size: 11px; text-transform: uppercase; border-bottom: 1px solid var(--border); border-right: none;">No.</th>
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
                <td style="padding: 8px 12px; font-size: 12px; color: var(--text-muted); border-right: none;">{idx}</td>
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
                    else (f'<a href="/attendance/clear?staff_id={st["id"]}&month={month_val}&vendor_id={vendor_filter or ""}&contract_id={contract_filter or ""}&annex_id={annex_filter or ""}&q={urllib.parse.quote(q_filter)}" class="btn btn-danger" style="font-size: 11px; padding: 4px 8px; line-height: 1;" onclick="return confirm(\'Delete all daily logs for {escape(st["full_name_vi"])} in {month_val}?\')">🗑️ Clear Logs</a>'
                          if st["id"] in att_map else '<span class="muted" style="font-size:11px;">No daily logs</span>')
                   )}
                </td>
              </tr>
              ''' for idx, st in enumerate(import_staff_list, 1)]) if import_staff_list else '<tr><td colspan="6" class="muted" style="padding:15px; text-align:center;">No active staff with valid contract in this month</td></tr>'}
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
      <input type="hidden" name="annex_id" value="{annex_filter or ''}">
      <input type="hidden" name="q" value="{escape(q_filter)}">

      <div class="spreadsheet-container">
        <table>
          <thead>
            <tr>
              <th rowspan="2" class="sticky-col1" style="text-align: center; vertical-align: middle;">No.</th>
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

        // Dynamic filtering of Annexes based on Vendor and Contract
        const vendorSel = document.getElementById('vendor_id');
        const contractSel = document.getElementById('contract_id');
        const annexSel = document.getElementById('annex_id');

        function filterAnnex() {{
          if (!vendorSel || !contractSel || !annexSel) return;
          const vId = vendorSel.value;
          const cId = contractSel.value;
          const opts = annexSel.querySelectorAll('option');
          let hasSelectedVisible = false;

          opts.forEach((opt) => {{
            const optContract = opt.getAttribute('data-contract-id');
            const optVendor = opt.getAttribute('data-vendor-id');
            if (!optContract && !optVendor) {{
              opt.hidden = false;
              return;
            }}

            let show = true;
            if (vId && optVendor && optVendor !== vId) {{
              show = false;
            }}
            if (cId && optContract && optContract !== cId) {{
              show = false;
            }}

            opt.hidden = !show;
            if (show && opt.selected) {{
              hasSelectedVisible = true;
            }}
          }});

          if (!hasSelectedVisible) {{
            annexSel.value = "";
          }}
        }}

        if (contractSel) contractSel.addEventListener('change', filterAnnex);
        filterAnnex();
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
    annex_id = form.get("annex_id", [""])[0].strip()
    q = form.get("q", [""])[0].strip()
    
    redirect_url = f"/attendance?month={month_val}&vendor_id={vendor_id}&contract_id={contract_id}&annex_id={annex_id}&q={q}"

    conn = db_connect()
    try:
        staff_rows = conn.execute("""
            SELECT id, full_name_vi, ot, work_shift 
            FROM contract_staff
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
    annex_id = form.get("annex_id", [""])[0].strip()
    q = form.get("q", [""])[0].strip()
    
    redirect_url = f"/attendance?month={month_val}&vendor_id={vendor_id}&contract_id={contract_id}&annex_id={annex_id}&q={q}"

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
                # Load staff rates for this month
                staff_data = {}
                staff_rows = conn.execute("""
                    SELECT s.id, l.monthly_rate, l.manday_rate 
                    FROM contract_staff s
                    JOIN contract_staff_links l ON l.staff_id = s.id 
                        AND l.joining_date <= ? 
                        AND (l.tentative_leaving_date IS NULL OR l.tentative_leaving_date = '' OR l.tentative_leaving_date >= ?)
                """, (month_end_date, month_start_date)).fetchall()
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
    annex_id = qs.get("annex_id", [""])[0].strip()
    q = qs.get("q", [""])[0].strip()
    
    redirect_url = f"/attendance?month={month_val}&vendor_id={vendor_id}&contract_id={contract_id}&annex_id={annex_id}&q={q}"

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
    annex_id = qs.get("annex_id", [""])[0].strip()
    q = qs.get("q", [""])[0].strip()
    
    redirect_url = f"/attendance?month={month_val}&vendor_id={vendor_id}&contract_id={contract_id}&annex_id={annex_id}&q={q}"

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
                    {"month": month_val, "vendor_id": parse_int_or_none(vendor_id), "contract_id": parse_int_or_none(contract_id), "annex_id": parse_int_or_none(annex_id), "q": q},
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
    annex_id = qs.get("annex_id", [""])[0].strip()
    q = qs.get("q", [""])[0].strip()
    
    redirect_url = f"/attendance?month={month_val}&vendor_id={vendor_id}&contract_id={contract_id}&annex_id={annex_id}&q={q}"

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
                    {"month": month_val, "vendor_id": parse_int_or_none(vendor_id), "contract_id": parse_int_or_none(contract_id), "annex_id": parse_int_or_none(annex_id), "q": q},
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
                    {"month": month_val, "vendor_id": parse_int_or_none(vendor_id), "contract_id": parse_int_or_none(contract_id), "annex_id": parse_int_or_none(annex_id), "q": q},
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
                    {"month": month_val, "vendor_id": parse_int_or_none(vendor_id), "contract_id": parse_int_or_none(contract_id), "annex_id": parse_int_or_none(annex_id), "q": q},
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
                {"month": month_val, "vendor_id": parse_int_or_none(vendor_id), "contract_id": parse_int_or_none(contract_id), "annex_id": parse_int_or_none(annex_id), "q": q},
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


def parse_int_list(val) -> list[int]:
    if not val:
        return []
    if isinstance(val, (int, str)):
        val = [val]
    res = []
    for item in val:
        if isinstance(item, int):
            res.append(item)
        elif isinstance(item, str):
            for sub in item.split(","):
                sub = sub.strip()
                if sub.isdigit():
                    res.append(int(sub))
    return res


def parse_str_list(val) -> list[str]:
    if not val:
        return []
    if isinstance(val, str):
        val = [val]
    res = []
    for item in val:
        if isinstance(item, str):
            for sub in item.split(","):
                sub = sub.strip()
                if sub:
                    res.append(sub)
    return res


def build_filter_qs(months: list[str], vendor_filters: list[int], contract_filters: list[int], annex_filters: list[int], q_filter: str) -> str:
    parts = []
    for m in months:
        parts.append(f"month={urllib.parse.quote(m)}")
    for v in vendor_filters:
        parts.append(f"vendor_id={v}")
    for c in contract_filters:
        parts.append(f"contract_id={c}")
    for a in annex_filters:
        parts.append(f"annex_id={a}")
    if q_filter:
        parts.append(f"q={urllib.parse.quote(q_filter)}")
    return "&".join(parts)


def render_multiselect_dropdown(container_id: str, name: str, options: list[dict], selected_values: list, default_label: str, on_change_js: str = "") -> str:
    """
    options: list of dicts with keys: 'value', 'label', 'data_attrs' (dict)
    selected_values: list of selected option values (as strings or ints)
    """
    str_selected = [str(v) for v in selected_values]
    
    selected_labels = []
    for opt in options:
        if str(opt['value']) in str_selected:
            selected_labels.append(opt['label'])
            
    if not selected_labels:
        button_text = default_label
    elif len(selected_labels) == 1:
        button_text = selected_labels[0]
    else:
        button_text = f"{len(selected_labels)} selected ({', '.join(selected_labels[:2])}{'...' if len(selected_labels) > 2 else ''})"

    items_html = []
    for opt in options:
        val_str = str(opt['value'])
        is_checked = "checked" if val_str in str_selected else ""
        data_attrs_dict = opt.get('data_attrs', {})
        data_attrs_str = " ".join([f'data-{k.replace("_", "-")}="{escape(str(v))}"' for k, v in data_attrs_dict.items()])
        items_html.append(f"""
        <div class="ms-option-item" {data_attrs_str}>
          <input type="checkbox" name="{name}" value="{escape(val_str)}" {is_checked} data-label="{escape(opt['label'])}" onchange="updateMsText('{container_id}', '{escape(default_label)}'); {on_change_js}">
          <span>{escape(opt['label'])}</span>
        </div>
        """)

    return f"""
    <div class="ms-container" id="{container_id}">
      <div class="ms-button" tabindex="0" onclick="toggleMs('{container_id}', event)">
        <span class="ms-label">{escape(button_text)}</span>
        <span class="ms-arrow">▼</span>
      </div>
      <div class="ms-dropdown">
        <div class="ms-actions">
          <span onclick="selectAllMs('{container_id}', true, '{escape(default_label)}'); {on_change_js}">Select All</span>
          <span onclick="selectAllMs('{container_id}', false, '{escape(default_label)}'); {on_change_js}">Clear All</span>
        </div>
        <div class="ms-options">
          {''.join(items_html)}
        </div>
      </div>
    </div>
    """


def page_monthly_attendance(filters: dict, error_msg: str | None = None, success_msg: str | None = None):
    months = parse_str_list(filters.get("month"))
    if not months:
        today = date.today()
        months = [today.strftime("%Y-%m")]

    vendor_filters = parse_int_list(filters.get("vendor_id"))
    contract_filters = parse_int_list(filters.get("contract_id"))
    annex_filters = parse_int_list(filters.get("annex_id"))
    q_filter = (filters.get("q") or "").strip()

    all_month_dates = []
    for m_str in months:
        try:
            y, m = int(m_str.split("-")[0]), int(m_str.split("-")[1])
            num_days = calendar.monthrange(y, m)[1]
            all_month_dates.append((m_str, y, m, f"{y:04d}-{m:02d}-01", f"{y:04d}-{m:02d}-{num_days:02d}"))
        except Exception:
            continue

    if not all_month_dates:
        today = date.today()
        m_str = today.strftime("%Y-%m")
        y, m = today.year, today.month
        num_days = calendar.monthrange(y, m)[1]
        all_month_dates.append((m_str, y, m, f"{y:04d}-{m:02d}-01", f"{y:04d}-{m:02d}-{num_days:02d}"))
        months = [m_str]

    min_start = min(d[3] for d in all_month_dates)
    max_end = max(d[4] for d in all_month_dates)

    conn = db_connect()
    try:
        cur = conn.cursor()

        # Load vendors, contracts, and annexes
        vendors = conn.execute("SELECT id, COALESCE(company_name, company_name_vi) AS company_name FROM vendors WHERE is_active=1 AND purchasing=0 ORDER BY company_name ASC").fetchall()
        contracts = conn.execute("SELECT id, framework_no, seller_vendor_id FROM contracts WHERE is_active=1 ORDER BY framework_no ASC").fetchall()
        annexes = conn.execute("SELECT a.id, a.contract_id, a.annex_name, c.seller_vendor_id FROM contract_annexes a JOIN contracts c ON c.id = a.contract_id WHERE a.is_active=1 AND a.deleted_at IS NULL ORDER BY a.annex_name ASC").fetchall()

        # Get all available months from DB for the month dropdown
        db_months = conn.execute("""
            SELECT DISTINCT month FROM attendance_locks
            UNION
            SELECT DISTINCT month FROM monthly_attendance_summary
            UNION
            SELECT DISTINCT strftime('%Y-%m', date) FROM attendance
            ORDER BY month DESC
        """).fetchall()
        available_months = sorted(list(set([r[0] for r in db_months if r[0]] + months)), reverse=True)
        if not available_months:
            available_months = [date.today().strftime("%Y-%m")]

        # Build SQL to load staff WHOSE ATTENDANCE IS LOCKED for selected months
        where = ["l.locked = 1"]
        params = []

        m_placeholders = ", ".join(["?"] * len(months))
        where.append(f"l.month IN ({m_placeholders})")
        params.extend(months)

        if vendor_filters:
            v_placeholders = ", ".join(["?"] * len(vendor_filters))
            where.append(f"s.vendor_id IN ({v_placeholders})")
            params.extend(vendor_filters)

        if contract_filters:
            c_placeholders = ", ".join(["?"] * len(contract_filters))
            where.append(f"lnk.contract_id IN ({c_placeholders})")
            params.extend(contract_filters)

        if annex_filters:
            a_placeholders = ", ".join(["?"] * len(annex_filters))
            where.append(f"lnk.annex_id IN ({a_placeholders})")
            params.extend(annex_filters)

        if q_filter:
            where.append("s.full_name_vi LIKE ?")
            params.append(f"%{q_filter}%")

        where_sql = "WHERE " + " AND ".join(where)

        locked_staff = conn.execute(f"""
            SELECT s.id, s.full_name_vi, s.ot, s.work_shift, lnk.monthly_rate, lnk.manday_rate,
                   s.paid_leave_total_hours, s.paid_leave_used_hours,
                   COALESCE(v.company_name, v.company_name_vi) AS vendor_name,
                   c.framework_no AS contract_no,
                   an.annex_name,
                   l.month AS lock_month
            FROM contract_staff s
            JOIN vendors v ON v.id=s.vendor_id
            JOIN contract_staff_links lnk ON lnk.staff_id = s.id
                AND lnk.joining_date <= ?
                AND (lnk.tentative_leaving_date IS NULL OR lnk.tentative_leaving_date = '' OR lnk.tentative_leaving_date >= ?)
            JOIN contracts c ON c.id=lnk.contract_id
            JOIN attendance_locks l ON l.staff_id=s.id
            LEFT JOIN contract_annexes an ON an.id=lnk.annex_id
            {where_sql}
            ORDER BY l.month DESC, vendor_name ASC, s.full_name_vi ASC
        """, [max_end, min_start] + params).fetchall()

        # Load raw work & OT hours from daily logs
        raw_hours_rows = conn.execute("""
            SELECT staff_id, strftime('%Y-%m', date) AS month_str, SUM(work_hours) AS sum_w, SUM(ot_hours) AS sum_ot
            FROM attendance
            WHERE date >= ? AND date <= ?
            GROUP BY staff_id, strftime('%Y-%m', date)
        """, (min_start, max_end)).fetchall()
        raw_hours_map = {(r["staff_id"], r["month_str"]): (r["sum_w"] or 0.0, r["sum_ot"] or 0.0) for r in raw_hours_rows}

        summaries = {}
        for s in locked_staff:
            sid = s["id"]
            m_val = s["lock_month"]
            try:
                y_val, m_val_int = int(m_val.split("-")[0]), int(m_val.split("-")[1])
            except Exception:
                y_val, m_val_int = date.today().year, date.today().month

            std_days_default = get_standard_working_days(y_val, m_val_int)
            row = conn.execute("""
                SELECT standard_days, actual_days, paid_leave_days, ot_converted_hours, daily_rate, total_amount, locked, manual_work_hours, manual_ot_hours
                FROM monthly_attendance_summary
                WHERE staff_id=? AND month=?
            """, (sid, m_val)).fetchone()

            sum_w, sum_ot = raw_hours_map.get((sid, m_val), (0.0, 0.0))
            calc_actual_days = sum_w / 8.0
            calc_ot_converted = sum_ot * 1.5

            if row:
                summary_data = dict(row)
                if summary_data["locked"] == 0:
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
                    """, (actual_days, ot_converted, daily_rate, total_amount, sid, m_val))

                    summary_data["actual_days"] = actual_days
                    summary_data["ot_converted_hours"] = ot_converted
                    summary_data["daily_rate"] = daily_rate
                    summary_data["total_amount"] = total_amount

                summaries[(sid, m_val)] = summary_data
            else:
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
                """, (sid, m_val, std_days_default, actual_days, paid_leave_days, ot_converted, daily_rate, total_amount))

                summaries[(sid, m_val)] = {
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

    # Build options for multi-select dropdowns
    month_options = [{"value": m_str, "label": f"Month {m_str[5:7]}/{m_str[:4]}"} for m_str in available_months]
    month_dropdown_html = render_multiselect_dropdown("ms-month", "month", month_options, months, "-- All Months --")

    vendor_options = [{"value": v["id"], "label": v["company_name"]} for v in vendors]
    vendor_dropdown_html = render_multiselect_dropdown("ms-vendor", "vendor_id", vendor_options, vendor_filters, "-- All Vendors --", "filterCascadingDropdowns()")

    contract_options = [{"value": c["id"], "label": c["framework_no"], "data_attrs": {"vendor_id": c["seller_vendor_id"] if "seller_vendor_id" in c.keys() else ""}} for c in contracts]
    contract_dropdown_html = render_multiselect_dropdown("ms-contract", "contract_id", contract_options, contract_filters, "-- All Contracts --", "filterCascadingDropdowns()")

    annex_options = [{"value": a["id"], "label": a["annex_name"], "data_attrs": {"contract_id": a["contract_id"], "vendor_id": a["seller_vendor_id"]}} for a in annexes]
    annex_dropdown_html = render_multiselect_dropdown("ms-annex", "annex_id", annex_options, annex_filters, "-- All Annexes --")

    # Build table rows
    trs = []
    total_billing_all = 0.0
    filter_qs = build_filter_qs(months, vendor_filters, contract_filters, annex_filters, q_filter)

    for idx, s in enumerate(locked_staff, 1):
        sid = s["id"]
        m_val = s["lock_month"]
        sum_data = summaries[(sid, m_val)]

        is_m_locked = sum_data.get("locked", 0) == 1
        disabled_attr = "disabled" if is_m_locked else ""

        act_qs = f"staff_id={sid}&month={m_val}&" + filter_qs

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

        if s["manday_rate"] is not None and s["manday_rate"] > 0:
            rate_label = f"Daily: {fmt_money(s['manday_rate'])}"
        elif s["monthly_rate"] is not None and s["monthly_rate"] > 0:
            rate_label = f"Monthly: {fmt_money(s['monthly_rate'])}"
        else:
            rate_label = '<span class="muted">Not configured</span>'

        tot_pl = s["paid_leave_total_hours"] or 0.0
        used_pl = s["paid_leave_used_hours"] or 0.0
        rem_pl_hours = tot_pl - used_pl
        rem_pl_days = rem_pl_hours / 8.0

        pl = sum_data["paid_leave_days"]
        act = sum_data["actual_days"]
        daily_rate = sum_data["daily_rate"]
        ot_hours = sum_data["ot_converted_hours"]

        raw_w, raw_ot = raw_hours_map.get((sid, m_val), (0.0, 0.0))

        manual_w = sum_data.get("manual_work_hours")
        manual_ot = sum_data.get("manual_ot_hours")

        display_w = manual_w if manual_w is not None else raw_w
        display_ot = manual_ot if manual_ot is not None else raw_ot

        w_style = "color:#0b57d0; font-weight:bold;" if manual_w is not None else "color:#333;"
        ot_style = "color:#b00020; font-weight:bold;" if manual_ot is not None else "color:#333;"

        work_pay = round((act + pl) * daily_rate)
        ot_pay = round(ot_hours * (daily_rate / 8.0))
        total_pay = sum_data["total_amount"]
        total_billing_all += total_pay

        contract_info = escape(s["contract_no"])
        if s["annex_name"]:
            contract_info += f" / {escape(s['annex_name'])}"

        m_badge = f"{m_val[5:7]}/{m_val[:4]}"

        trs.append(f"""
        <tr>
          <td style="text-align:center;">{idx}</td>
          <td>
            <div style="font-weight:600;">{escape(s['full_name_vi'])}</div>
            <div style="font-size:11px; color:#666; margin-top:2px;">
              OT Eligible: <b>{'Yes' if s['ot'] == 1 else 'No'}</b>
            </div>
            {m_lock_action_html}
          </td>
          <td>{escape(s['vendor_name'])}</td>
          <td><span class="tag" style="background:#e0e7ff; color:#3730a3; font-weight:bold;">{m_badge}</span></td>
          <td>
            <div style="font-size:12px;">{contract_info}</div>
            <div style="font-size:11px; color:#666; margin-top:2px;">{rate_label}</div>
          </td>
          <td style="text-align:center;">
            <input type="number" step="0.5" min="0" name="std_{sid}_{m_val}" value="{sum_data['standard_days']:.1f}" {disabled_attr}
                   style="width: 55px; padding: 4px; font-size:12px; text-align:center;">
          </td>
          <td style="text-align:center; font-family:monospace; font-size:13px; font-weight:bold; color:#0b57d0;">
            {act:.2f}
          </td>
          <td style="text-align:center;">
            <input type="number" step="0.5" min="0" name="pl_{sid}_{m_val}" value="{pl:.1f}" {disabled_attr}
                   style="width: 55px; padding: 4px; font-size:12px; text-align:center;"
                   title="Remaining balance: {rem_pl_days:.2f} days ({rem_pl_hours:.1f}h)">
            <div style="font-size:9px; color:#666; margin-top:2px;" title="Total: {tot_pl:.1f}h, Used: {used_pl:.1f}h">
              Rem: {rem_pl_days:.1f}d
            </div>
          </td>
          <td style="text-align:center;">
            <input type="number" step="0.1" min="0" name="ot_{sid}_{m_val}" value="{ot_hours:.2f}" {disabled_attr}
                   style="width: 65px; padding: 4px; font-size:12px; text-align:center;">
          </td>
          <td style="text-align:center; font-size:11px; font-family:monospace; line-height:1.3; vertical-align:middle;">
            <div style="margin-bottom: 2px;">
              <span style="{w_style}" title="{f'Raw log: {raw_w:.2f}h' if manual_w is not None else ''}">Work: {display_w:.2f}h{f' *' if manual_w is not None else ''}</span>
            </div>
            <div>
              <span style="{ot_style}" title="{f'Raw log: {raw_ot:.2f}h' if manual_ot is not None else ''}">OT: {display_ot:.2f}h{f' *' if manual_ot is not None else ''}</span>
            </div>
          </td>
          <td style="text-align:right; font-family:monospace;">
            {int(round(sum_data['daily_rate'])):,}
          </td>
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
      <a href="/attendance?{filter_qs}" style="margin-right: 18px; font-weight: bold; color:#666; text-decoration:none;">📅 Daily Attendance</a>
      <a href="/attendance/monthly?{filter_qs}" style="margin-right: 18px; font-weight: bold; color:#0b57d0; border-bottom: 2px solid #0b57d0; padding-bottom: 8px;">💵 Monthly Payroll</a>
      <a href="/attendance/acceptance?{filter_qs}" style="margin-right: 18px; font-weight: bold; color:#666; text-decoration:none;">📜 Attendance Acceptance</a>
      <a href="/attendance/cashout" style="margin-right: 18px; font-weight: bold; color:#666; text-decoration:none;">💰 Cash-out</a>
    </div>
    """

    body = f"""
    <style>
      .ms-container {{
        position: relative;
        display: inline-block;
        min-width: 170px;
      }}
      .ms-button {{
        padding: 8px 12px;
        border: 1px solid var(--border);
        border-radius: 8px;
        background: var(--bg-card);
        color: var(--text-primary);
        font-size: 14px;
        font-family: inherit;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        user-select: none;
        min-height: 38px;
        transition: all 0.15s ease;
      }}
      .ms-button:hover {{
        border-color: #cbd5e1;
      }}
      .ms-button:focus {{
        outline: none;
        border-color: var(--primary);
        box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.12);
      }}
      .ms-label {{
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        max-width: 180px;
        font-size: 13px;
        font-weight: 500;
      }}
      .ms-arrow {{
        font-size: 10px;
        color: var(--text-muted);
        transition: transform 0.2s;
      }}
      .ms-container.open .ms-arrow {{
        transform: rotate(180deg);
      }}
      .ms-dropdown {{
        display: none;
        position: absolute;
        top: calc(100% + 4px);
        left: 0;
        z-index: 1000;
        min-width: 230px;
        max-width: 340px;
        background: #ffffff;
        border: 1px solid var(--border);
        border-radius: 8px;
        box-shadow: var(--shadow-md);
        padding: 6px 0;
        max-height: 260px;
        overflow-y: auto;
      }}
      .ms-container.open .ms-dropdown {{
        display: block;
      }}
      .ms-option-item {{
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 6px 12px;
        font-size: 13px;
        color: var(--text-primary);
        cursor: pointer;
        user-select: none;
        transition: background 0.1s;
      }}
      .ms-option-item:hover {{
        background: #f1f5f9;
      }}
      .ms-option-item input[type="checkbox"] {{
        min-width: auto;
        width: 15px;
        height: 15px;
        cursor: pointer;
      }}
      .ms-option-item[hidden] {{
        display: none !important;
      }}
      .ms-actions {{
        padding: 4px 12px 6px 12px;
        border-bottom: 1px solid var(--border);
        margin-bottom: 4px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-size: 12px;
      }}
      .ms-actions span {{
        color: var(--primary);
        font-weight: 600;
        cursor: pointer;
      }}
      .ms-actions span:hover {{
        text-decoration: underline;
      }}
    </style>

    {sub_nav}
    {error_html}
    {success_html}

    <!-- 1. Filters -->
    <div class="card">
      <form method="GET" action="/attendance/monthly" class="filters" style="margin: 0;">
        <div>
          <div class="label">Payment Month</div>
          {month_dropdown_html}
        </div>
        <div>
          <div class="label">Vendor</div>
          {vendor_dropdown_html}
        </div>
        <div>
          <div class="label">Framework Contract</div>
          {contract_dropdown_html}
        </div>
        <div>
          <div class="label">Annex (filtered by Framework)</div>
          {annex_dropdown_html}
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
      {''.join([f'<input type="hidden" name="month" value="{escape(m)}">' for m in months])}
      {''.join([f'<input type="hidden" name="vendor_id" value="{v}">' for v in vendor_filters])}
      {''.join([f'<input type="hidden" name="contract_id" value="{c}">' for c in contract_filters])}
      {''.join([f'<input type="hidden" name="annex_id" value="{a}">' for a in annex_filters])}
      <input type="hidden" name="q" value="{escape(q_filter)}">

      <div class="card" style="padding:0; overflow-x:auto;">
        <table style="margin:0;">
          <thead>
            <tr>
              <th>No.</th>
              <th>Full Name</th>
              <th>Vendor</th>
              <th>Month</th>
              <th>Shift / Baseline Rate</th>
              <th style="width:75px; text-align:center;">Standard Days</th>
              <th style="width:75px; text-align:center;">Actual Days</th>
              <th style="width:75px; text-align:center;">Paid Leave</th>
              <th style="width:75px; text-align:center;">Converted OT Hours (x1.5)</th>
              <th style="text-align:center;">Hours Worked<br><span style="font-weight:normal; font-size:9px; color:#666;">(Work / OT)</span></th>
              <th style="text-align:right;">Daily Rate</th>
              <th style="text-align:right;">Monthly Wages</th>
            </tr>
          </thead>
          <tbody>
            {''.join(trs) if trs else '<tr><td colspan="12" class="muted" style="padding:15px;">No staff with locked daily attendance matches the filter for the selected month(s). Please lock daily attendance first.</td></tr>'}
          </tbody>
        </table>
      </div>

      {f'''
      <div style="display:flex; justify-content:space-between; align-items:center; margin-top:20px;">
        <div class="actions" style="display:flex; gap:10px; align-items:center;">
          <button type="submit" style="background:#0b57d0; color:#fff; border-color:#0b57d0; font-weight:600; padding:10px 24px;">Save Calculations</button>
          <a href="/attendance/monthly/export?{filter_qs}" class="btn btn-secondary" style="padding:10px 20px;">Export Excel (CSV)</a>
        </div>
        <div style="font-size:18px; font-weight:bold; color:#111;">
          Total Monthly Payment: <span style="color:#0b57d0; font-size:20px;">{int(round(total_billing_all)):,} VND</span>
        </div>
      </div>
      ''' if trs else ''}
    </form>

    <script>
      function toggleMs(id, event) {{
        if (event) event.stopPropagation();
        const el = document.getElementById(id);
        const isOpen = el.classList.contains('open');
        document.querySelectorAll('.ms-container').forEach(c => c.classList.remove('open'));
        if (!isOpen) {{
          el.classList.add('open');
        }}
      }}

      document.addEventListener('click', function(e) {{
        if (!e.target.closest('.ms-container')) {{
          document.querySelectorAll('.ms-container').forEach(c => c.classList.remove('open'));
        }}
      }});

      function updateMsText(id, defaultText) {{
        const container = document.getElementById(id);
        if (!container) return;
        const items = container.querySelectorAll('.ms-options .ms-option-item');
        const checked = [];
        items.forEach(item => {{
          if (!item.hidden && item.style.display !== 'none') {{
            const cb = item.querySelector('input[type="checkbox"]');
            if (cb && cb.checked) {{
              checked.push(cb);
            }}
          }}
        }});
        const labelSpan = container.querySelector('.ms-label');
        if (checked.length === 0) {{
          labelSpan.innerText = defaultText;
        }} else if (checked.length === 1) {{
          labelSpan.innerText = checked[0].dataset.label || checked[0].value;
        }} else {{
          const labels = checked.map(cb => cb.dataset.label || cb.value);
          labelSpan.innerText = checked.length + ' selected (' + labels.slice(0, 2).join(', ') + (labels.length > 2 ? '...' : '') + ')';
        }}
      }}

      function selectAllMs(id, selectAll, defaultText) {{
        const container = document.getElementById(id);
        if (!container) return;
        const items = container.querySelectorAll('.ms-option-item');
        items.forEach(item => {{
          if (item.style.display !== 'none' && !item.hidden) {{
            const cb = item.querySelector('input[type="checkbox"]');
            if (cb) cb.checked = selectAll;
          }}
        }});
        updateMsText(id, defaultText);
        if (id === 'ms-contract' || id === 'ms-vendor') {{
          filterCascadingDropdowns();
        }}
      }}

      function filterCascadingDropdowns() {{
        const vendorCbs = document.querySelectorAll('#ms-vendor .ms-options input[type="checkbox"]:checked');
        const selectedVendors = Array.from(vendorCbs).map(cb => cb.value);

        // 1. Filter Framework Contracts based on selected Vendor(s)
        const contractItems = document.querySelectorAll('#ms-contract .ms-option-item');
        contractItems.forEach(item => {{
          const optVendor = item.getAttribute('data-vendor-id');
          let show = true;
          if (selectedVendors.length > 0 && optVendor && !selectedVendors.includes(optVendor)) {{
            show = false;
          }}
          item.hidden = !show;
          item.style.display = show ? 'flex' : 'none';
          if (!show) {{
            const cb = item.querySelector('input[type="checkbox"]');
            if (cb) cb.checked = false;
          }}
        }});
        updateMsText('ms-contract', '-- All Contracts --');

        // 2. Filter Annexes based on selected Vendor(s) and Framework Contract(s)
        const contractCbs = document.querySelectorAll('#ms-contract .ms-options input[type="checkbox"]:checked');
        const selectedContracts = Array.from(contractCbs).map(cb => cb.value);

        const annexItems = document.querySelectorAll('#ms-annex .ms-option-item');
        annexItems.forEach(item => {{
          const optVendor = item.getAttribute('data-vendor-id');
          const optContract = item.getAttribute('data-contract-id');
          
          let show = true;
          if (selectedVendors.length > 0 && optVendor && !selectedVendors.includes(optVendor)) {{
            show = false;
          }}
          if (selectedContracts.length > 0 && optContract && !selectedContracts.includes(optContract)) {{
            show = false;
          }}
          
          item.hidden = !show;
          item.style.display = show ? 'flex' : 'none';
          if (!show) {{
            const cb = item.querySelector('input[type="checkbox"]');
            if (cb) cb.checked = false;
          }}
        }});
        updateMsText('ms-annex', '-- All Annexes --');
      }}
      
      document.addEventListener('DOMContentLoaded', filterCascadingDropdowns);
    </script>
    """
    
    first_month = months[0] if months else f"{date.today().month:02d}/{date.today().year:04d}"
    return layout(f"Monthly Payroll - Month {first_month}", body)


def page_attendance_acceptance(filters: dict, error_msg: str | None = None, success_msg: str | None = None) -> str:
    m_raw = filters.get("month")
    if isinstance(m_raw, list):
        month_val = m_raw[0].strip() if m_raw and isinstance(m_raw[0], str) else ""
    elif isinstance(m_raw, str):
        month_val = m_raw.strip()
    else:
        month_val = ""

    if not month_val:
        month_val = date.today().strftime("%Y-%m")

    try:
        y_val, m_val_int = map(int, month_val.split("-"))
    except Exception:
        today = date.today()
        y_val, m_val_int = today.year, today.month
        month_val = today.strftime("%Y-%m")

    num_days = calendar.monthrange(y_val, m_val_int)[1]
    month_start_date = f"{y_val:04d}-{m_val_int:02d}-01"
    month_end_date = f"{y_val:04d}-{m_val_int:02d}-{num_days:02d}"

    v_raw = filters.get("vendor_id")
    if isinstance(v_raw, list):
        v_raw = v_raw[0] if v_raw else None
    vendor_filter = parse_int_or_none(v_raw)

    c_raw = filters.get("contract_id")
    if isinstance(c_raw, list):
        c_raw = c_raw[0] if c_raw else None
    contract_filter = parse_int_or_none(c_raw)

    a_raw = filters.get("annex_id")
    if isinstance(a_raw, list):
        a_raw = a_raw[0] if a_raw else None
    annex_filter = parse_int_or_none(a_raw)

    q_raw = filters.get("q")
    if isinstance(q_raw, list):
        q_filter = q_raw[0].strip() if q_raw and isinstance(q_raw[0], str) else ""
    elif isinstance(q_raw, str):
        q_filter = q_raw.strip()
    else:
        q_filter = ""

    conn = db_connect()
    try:
        if vendor_filter is not None and contract_filter is not None:
            c_row = conn.execute("SELECT 1 FROM contracts WHERE id=? AND seller_vendor_id=?", (contract_filter, vendor_filter)).fetchone()
            if not c_row:
                contract_filter = None

        if contract_filter is not None and annex_filter is not None:
            a_row = conn.execute("SELECT 1 FROM contract_annexes WHERE id=? AND contract_id=?", (annex_filter, contract_filter)).fetchone()
            if not a_row:
                annex_filter = None

        vendors = conn.execute("SELECT id, COALESCE(company_name, company_name_vi) AS company_name FROM vendors WHERE is_active=1 AND purchasing=0 ORDER BY company_name ASC").fetchall()

        if vendor_filter is not None:
            contracts = conn.execute("SELECT id, framework_no, framework_name FROM contracts WHERE is_active=1 AND seller_vendor_id=? ORDER BY framework_no ASC", (vendor_filter,)).fetchall()
        else:
            contracts = conn.execute("SELECT id, framework_no, framework_name FROM contracts WHERE is_active=1 ORDER BY framework_no ASC").fetchall()

        annexes = conn.execute("SELECT a.id, a.contract_id, a.annex_name, c.seller_vendor_id FROM contract_annexes a JOIN contracts c ON c.id = a.contract_id WHERE a.is_active=1 AND a.deleted_at IS NULL ORDER BY a.annex_name ASC").fetchall()

        annex_sql = """
            SELECT a.id AS annex_id, a.annex_name, a.start_date, a.end_date,
                   c.id AS contract_id, c.framework_no, c.framework_name,
                   v.id AS vendor_id, COALESCE(v.company_name, v.company_name_vi) AS vendor_name,
                   v.tax_id, COALESCE(v.address, v.address_vi) AS address_vi, v.tel
            FROM contract_annexes a
            JOIN contracts c ON c.id = a.contract_id
            JOIN vendors v ON v.id = c.seller_vendor_id
            WHERE a.is_active = 1 AND a.deleted_at IS NULL
        """
        params = []
        if annex_filter is not None:
            annex_sql += " AND a.id = ?"
            params.append(annex_filter)
        if contract_filter is not None:
            annex_sql += " AND c.id = ?"
            params.append(contract_filter)
        if vendor_filter is not None:
            annex_sql += " AND v.id = ?"
            params.append(vendor_filter)

        annex_sql += " ORDER BY v.company_name_vi, c.framework_no, a.annex_name"
        annex_list = conn.execute(annex_sql, params).fetchall()

        conn.execute("""
            CREATE TABLE IF NOT EXISTS annex_cashouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                annex_id INTEGER NOT NULL,
                month TEXT NOT NULL,
                cashout_date TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(annex_id) REFERENCES contract_annexes(id),
                UNIQUE(annex_id, month)
            )
        """)
        cashout_rows = conn.execute("SELECT annex_id, cashout_date FROM annex_cashouts WHERE month = ?", (month_val,)).fetchall()
        cashout_map = {r["annex_id"]: r["cashout_date"] for r in cashout_rows}

        # Query all invoices for current service year and month
        inv_rows = conn.execute("""
            SELECT id, shdon, khhdon, nlap, service_year, service_month, contract_no, seller_mst
            FROM invoices
            WHERE (service_year = ? AND service_month = ?)
               OR (service_year IS NULL AND strftime('%Y-%m', nlap) = ?)
        """, (y_val, m_val_int, month_val)).fetchall()

        annex_cards = []
        for a in annex_list:
            aid = a["annex_id"]
            
            staff_sql = """
                SELECT DISTINCT s.id, s.full_name_vi, s.position, l.monthly_rate, l.manday_rate
                FROM contract_staff_links l
                JOIN contract_staff s ON s.id = l.staff_id
                WHERE l.annex_id = ?
                  AND (l.joining_date IS NULL OR l.joining_date = '' OR l.joining_date <= ?)
                  AND (l.tentative_leaving_date IS NULL OR l.tentative_leaving_date = '' OR l.tentative_leaving_date >= ?)
                  AND (
                      EXISTS (SELECT 1 FROM attendance att WHERE att.staff_id = s.id AND strftime('%Y-%m', att.date) = ?)
                      OR EXISTS (SELECT 1 FROM monthly_attendance_summary mas WHERE mas.staff_id = s.id AND mas.month = ?)
                  )
            """
            staff_params = [aid, month_end_date, month_start_date, month_val, month_val]
            if q_filter:
                staff_sql += " AND s.full_name_vi LIKE ?"
                staff_params.append(f"%{q_filter}%")
            staff_sql += " ORDER BY s.full_name_vi"

            staff_rows = conn.execute(staff_sql, staff_params).fetchall()
            staff_ids = [s["id"] for s in staff_rows]

            # Fetch ALL active staff linked to this annex via contract during target month
            all_linked_rows = conn.execute("""
                SELECT DISTINCT s.id
                FROM contract_staff_links l
                JOIN contract_staff s ON s.id = l.staff_id
                WHERE l.annex_id = ?
                  AND (l.joining_date IS NULL OR l.joining_date = '' OR l.joining_date <= ?)
                  AND (l.tentative_leaving_date IS NULL OR l.tentative_leaving_date = '' OR l.tentative_leaving_date >= ?)
            """, (aid, month_end_date, month_start_date)).fetchall()
            all_linked_ids = [r["id"] for r in all_linked_rows]

            daily_lock_map = {}
            monthly_lock_map = {}
            if all_linked_ids:
                s_ph = ", ".join(["?"] * len(all_linked_ids))
                d_rows = conn.execute(f"""
                    SELECT staff_id FROM attendance_locks
                    WHERE month = ? AND staff_id IN ({s_ph}) AND locked = 1
                """, [month_val] + all_linked_ids).fetchall()
                daily_lock_map = {r["staff_id"]: True for r in d_rows}

                m_rows = conn.execute(f"""
                    SELECT staff_id FROM monthly_attendance_summary
                    WHERE month = ? AND staff_id IN ({s_ph}) AND locked = 1
                """, [month_val] + all_linked_ids).fetchall()
                monthly_lock_map = {r["staff_id"]: True for r in m_rows}

            is_fully_locked = (
                len(all_linked_ids) > 0 and
                all(daily_lock_map.get(sid, False) and monthly_lock_map.get(sid, False) for sid in all_linked_ids)
            )

            # Attendance Acceptance only displays annexes if ALL contract staff are fully locked in both Daily Attendance and Monthly Payroll
            if not is_fully_locked:
                continue

            staff_trs = []
            tot_wages = 0.0
            for idx, s in enumerate(staff_rows, 1):
                sid = s["id"]
                s_lock_badge = '<span style="color:#137333; font-weight:bold;">🔒 Locked</span>'

                sum_row = conn.execute("""
                    SELECT actual_days, ot_converted_hours, daily_rate, total_amount
                    FROM monthly_attendance_summary
                    WHERE staff_id = ? AND month = ?
                """, (sid, month_val)).fetchone()

                act_d = sum_row["actual_days"] if sum_row else 0.0
                ot_h = sum_row["ot_converted_hours"] if sum_row else 0.0
                wages = sum_row["total_amount"] if sum_row else 0.0
                tot_wages += wages

                staff_trs.append(f"""
                <tr>
                  <td style="text-align:center;">{idx}</td>
                  <td><b>{escape(s['full_name_vi'])}</b></td>
                  <td>{escape(s['position'] or '')}</td>
                  <td style="text-align:center;">{s_lock_badge}</td>
                  <td style="text-align:right; font-family:monospace;">{act_d * 8.0:.1f} hrs</td>
                  <td style="text-align:right; font-family:monospace;">{ot_h:.1f} hrs</td>
                  <td style="text-align:right; font-family:monospace; font-weight:bold;">{int(round(wages)):,} VND</td>
                </tr>
                """)

            cashout_date = cashout_map.get(aid)
            if cashout_date:
                badge_html = f'<span class="badge-cashed-out" style="background:#e6f4ea; color:#137333; border:1px solid #b4e3be; padding:4px 12px; border-radius:12px; font-weight:bold; font-size:13px;" title="Cashed out on {escape(cashout_date)}">💸 CASHED OUT ({escape(cashout_date)})</span>'
                cashout_btn_html = f"""
                <button type="button" class="btn" onclick="openCashoutModal({aid}, '{escape(a['annex_name'])}', '{month_val}', '{escape(cashout_date)}')" style="background:#f8fafc; color:#0b57d0; border:1px solid #0b57d0; font-size:13px; font-weight:600; padding:6px 14px; border-radius:6px; cursor:pointer; display:inline-flex; align-items:center; gap:6px; white-space:nowrap; box-shadow:0 1px 2px rgba(0,0,0,0.05);" title="Edit Cash-out date (current: {escape(cashout_date)})">
                  ✏️ Edit Cash-out
                </button>
                """
            else:
                badge_html = ''
                cashout_btn_html = f"""
                <button type="button" class="btn" onclick="openCashoutModal({aid}, '{escape(a['annex_name'])}', '{month_val}', '')" style="background:#fff; color:#0b57d0; border:1px solid #0b57d0; font-size:13px; font-weight:600; padding:6px 14px; border-radius:6px; cursor:pointer; display:inline-flex; align-items:center; gap:6px; white-space:nowrap; box-shadow:0 1px 2px rgba(0,0,0,0.05);" title="Set Cash-out date for {escape(a['annex_name'])}">
                  💰 Cash-out
                </button>
                """

            # Check if invoice for this annex and month has already been imported
            def _norm_mst(s):
                return (s or "").replace("-", "").replace(" ", "").strip().lower()

            target_mst = _norm_mst(a["tax_id"])
            a_name = (a["annex_name"] or "").strip().lower()
            f_no = (a["framework_no"] or "").strip().lower()

            imported_inv = None
            for inv in inv_rows:
                inv_mst = _norm_mst(inv["seller_mst"])
                if target_mst and inv_mst and target_mst != inv_mst:
                    continue

                c_no = (inv["contract_no"] or "").strip().lower()
                if not c_no:
                    continue

                if a_name and (c_no == a_name or a_name in c_no or c_no in a_name):
                    imported_inv = inv
                    break
                if f_no and (c_no == f_no or f_no in c_no):
                    imported_inv = inv
                    break

            if imported_inv:
                inv_shdon = imported_inv["shdon"] or ""
                inv_id = imported_inv["id"]
                view_link = f' <a href="/invoice?id={inv_id}" style="color:#0b57d0; font-size:12px; font-weight:600; text-decoration:none;" title="View invoice #{escape(inv_shdon)}">[View Inv #{escape(inv_shdon)}]</a>'
                import_btn_html = f"""
                <span style="display:inline-flex; align-items:center; gap:6px;">
                  <button type="button" class="btn" disabled style="background:#f1f5f9; color:#94a3b8; border:1px solid #cbd5e1; font-size:13px; font-weight:600; padding:6px 14px; border-radius:6px; cursor:not-allowed; display:inline-flex; align-items:center; gap:6px; white-space:nowrap;" title="Invoice for month {month_val} of {escape(a['annex_name'])} has been imported (Inv No: {escape(inv_shdon)}).">
                    🔒 Invoice Imported
                  </button>
                  {view_link}
                </span>
                """
            else:
                import_btn_html = f"""
                <a href="/invoice/new?service_year={y_val}&service_month={m_val_int:02d}&contract_no={urllib.parse.quote(a['annex_name'])}&annex={urllib.parse.quote(a['annex_name'])}&return_month={month_val}&from=acceptance" class="btn" style="background:#0b57d0; color:#fff; font-size:13px; font-weight:600; padding:6px 14px; border-radius:6px; text-decoration:none; display:inline-flex; align-items:center; gap:6px; white-space:nowrap; box-shadow:0 1px 2px rgba(0,0,0,0.05);" title="Import invoice for {escape(a['annex_name'])}">
                  📥 Import Invoice
                </a>
                """

            btn_html = f"""
            <a href="/attendance/timesheet?annex_id={aid}&month={month_val}" target="_blank" class="btn" style="background:#0b57d0; color:#fff; font-weight:bold; padding:8px 18px; border-radius:6px; text-decoration:none; display:inline-flex; align-items:center; gap:6px;">
              📄 Print / Export BBNT PDF (A4 Landscape)
            </a>
            """

            annex_cards.append(f"""
            <div class="card" style="margin-bottom:24px; border:1px solid #cbd5e1; border-radius:12px; padding:20px; background:#fff; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
              <div style="display:flex; justify-content:space-between; align-items:flex-start; border-bottom:1px solid #f1f5f9; padding-bottom:12px; margin-bottom:16px;">
                <div>
                  <h3 style="margin:0 0 6px 0; font-size:16px; color:#0f172a;">
                    {escape(a['vendor_name'])} - <span style="color:#0b57d0;">{escape(a['annex_name'])}</span> ({escape(a['framework_no'])})
                  </h3>
                  <div style="font-size:13px; color:#475569; line-height:1.4;">
                    <span><b>Tax Code:</b> {escape(a['tax_id'] or 'N/A')}</span> | 
                    <span><b>Address:</b> {escape(a['address_vi'] or 'N/A')}</span> | 
                    <span><b>TEL:</b> {escape(a['tel'] or 'N/A')}</span>
                  </div>
                </div>
                <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap; justify-content:flex-end;">
                  {badge_html}
                  {cashout_btn_html}
                  {import_btn_html}
                </div>
              </div>

              <div style="margin-bottom:16px;">
                <table style="width:100%; border-collapse:collapse; font-size:13px;">
                  <thead>
                    <tr style="background:#f8fafc;">
                      <th style="width:40px; text-align:center;">No.</th>
                      <th style="text-align:left;">Full Name</th>
                      <th style="text-align:left;">Position</th>
                      <th style="text-align:center;">Attendance Status</th>
                      <th style="text-align:right;">Standard Hours</th>
                      <th style="text-align:right;">OT Hours</th>
                      <th style="text-align:right;">Total Amount (VND)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {''.join(staff_trs) if staff_trs else '<tr><td colspan="7" style="text-align:center; padding:12px; color:#64748b;">No staff members assigned to this Annex.</td></tr>'}
                  </tbody>
                </table>
              </div>

              <div style="display:flex; justify-content:space-between; align-items:center; background:#f8fafc; padding:12px 16px; border-radius:8px; border:1px solid #e2e8f0;">
                <div>{btn_html}</div>
                <div style="text-align:right; font-size:14px; color:#334155;">
                  Total Amount: <b style="color:#0b57d0; font-size:17px; font-family:monospace;">{int(round(tot_wages)):,} VND</b>
                </div>
              </div>
            </div>
            """)

        vendor_opts = ['<option value="">-- All Vendors --</option>']
        for v in vendors:
            sel = "selected" if vendor_filter == v["id"] else ""
            vendor_opts.append(f'<option value="{v["id"]}" {sel}>{escape(v["company_name"])}</option>')

        contract_opts = ['<option value="">-- All Contracts --</option>']
        for c in contracts:
            sel = "selected" if contract_filter == c["id"] else ""
            contract_opts.append(f'<option value="{c["id"]}" {sel}>{escape(c["framework_no"])}</option>')

        annex_opts = ['<option value="">-- All Annexes --</option>']
        for a in annexes:
            sel = "selected" if annex_filter == a["id"] else ""
            annex_opts.append(f'<option value="{a["id"]}" data-contract-id="{a["contract_id"]}" data-vendor-id="{a["seller_vendor_id"]}" {sel}>{escape(a["annex_name"])}</option>')

    finally:
        conn.close()

    act_qs = f"month={month_val}&vendor_id={vendor_filter or ''}&contract_id={contract_filter or ''}&annex_id={annex_filter or ''}&q={urllib.parse.quote(q_filter)}"

    sub_nav = f"""
    <div class="actions" style="margin-bottom: 14px; border-bottom: 1px solid #ddd; padding-bottom: 8px;">
      <a href="/attendance?{act_qs}" style="margin-right: 18px; font-weight: bold; color:#666; text-decoration:none;">📅 Daily Attendance</a>
      <a href="/attendance/monthly?{act_qs}" style="margin-right: 18px; font-weight: bold; color:#666; text-decoration:none;">💵 Monthly Payroll</a>
      <a href="/attendance/acceptance?{act_qs}" style="margin-right: 18px; font-weight: bold; color:#0b57d0; border-bottom: 2px solid #0b57d0; padding-bottom: 8px;">📜 Attendance Acceptance</a>
      <a href="/attendance/cashout" style="margin-right: 18px; font-weight: bold; color:#666; text-decoration:none;">💰 Cash-out</a>
    </div>
    """

    filter_card = f"""
    <div class="card">
      <form method="GET" action="/attendance/acceptance" class="filters" style="margin: 0;">
        <div>
          <div class="label">Attendance Month</div>
          <input type="month" name="month" value="{month_val}" onchange="this.form.submit()">
        </div>
        <div>
          <div class="label">Vendor</div>
          <select id="vendor_id" name="vendor_id" onchange="this.form.submit()">
            {''.join(vendor_opts)}
          </select>
        </div>
        <div>
          <div class="label">Framework Contract</div>
          <select id="contract_id" name="contract_id" onchange="this.form.submit()">
            {''.join(contract_opts)}
          </select>
        </div>
        <div>
          <div class="label">Annex (filtered by Framework)</div>
          <select id="annex_id" name="annex_id" onchange="this.form.submit()">
            {''.join(annex_opts)}
          </select>
        </div>
        <div>
          <div class="label">Search staff</div>
          <input type="text" name="q" placeholder="Enter staff name..." value="{escape(q_filter)}">
        </div>
        <div class="actions">
          <button type="submit">Filter</button>
          <a class="muted" href="/attendance/acceptance">Reset</a>
        </div>
      </form>
    </div>
    """

    error_html = f"<div class='card danger' style='margin-bottom:16px;'><b>Error:</b> {escape(error_msg)}</div>" if error_msg else ""
    success_html = f"<div class='card success' style='border-color:#b4e3be; background:#f4fbf6; color:#137333; padding:12px; border-radius:8px; margin-bottom:16px;'><b>Success:</b> {escape(success_msg)}</div>" if success_msg else ""

    modal_html = f"""
    <!-- Cash-out Modal -->
    <div id="cashoutModal" style="display:none; position:fixed; z-index:99999; left:0; top:0; width:100%; height:100%; background-color:rgba(0,0,0,0.45); backdrop-filter:blur(2px); align-items:center; justify-content:center;">
      <div style="background:#fff; border-radius:12px; width:92%; max-width:440px; box-shadow:0 20px 25px -5px rgba(0,0,0,0.1), 0 8px 10px -6px rgba(0,0,0,0.1); border:1px solid #e2e8f0; overflow:hidden;">
        <div style="display:flex; justify-content:space-between; align-items:center; padding:16px 20px; border-bottom:1px solid #f1f5f9; background:#f8fafc;">
          <h3 id="modalTitle" style="margin:0; font-size:16px; font-weight:700; color:#0f172a;">💰 Cash-out Date</h3>
          <button type="button" onclick="closeCashoutModal()" style="background:none; border:none; font-size:22px; cursor:pointer; color:#64748b; line-height:1; padding:0 4px;">&times;</button>
        </div>
        
        <form method="POST" action="/attendance/acceptance/cashout" style="margin:0; padding:20px;">
          <input type="hidden" name="annex_id" id="modalAnnexId" value="">
          <input type="hidden" name="month" id="modalMonth" value="">
          <input type="hidden" name="return_url" value="/attendance/acceptance?{act_qs}">
          
          <div style="margin-bottom:16px;">
            <div style="font-size:13px; color:#64748b; margin-bottom:4px;">Annex: <b id="modalAnnexName" style="color:#0f172a;"></b></div>
            <div style="font-size:13px; color:#64748b;">Month: <b id="modalMonthText" style="color:#0f172a;"></b></div>
          </div>
          
          <div style="margin-bottom:20px;">
            <label for="modalCashoutDate" style="display:block; font-size:13px; font-weight:600; color:#334155; margin-bottom:6px;">
              Cash-out Date: <span style="color:#dc2626;">*</span>
            </label>
            <input type="date" name="cashout_date" id="modalCashoutDate" required style="width:100%; box-sizing:border-box; padding:9px 12px; border:1px solid #cbd5e1; border-radius:6px; font-size:14px; font-family:inherit;">
          </div>
          
          <div style="display:flex; justify-content:space-between; align-items:center; gap:10px; border-top:1px solid #f1f5f9; padding-top:16px;">
            <div id="modalRemoveBtnContainer">
              <button type="submit" name="action" value="clear" style="background:#fff; color:#dc2626; border:1px solid #fca5a5; padding:8px 14px; border-radius:6px; font-size:13px; font-weight:600; cursor:pointer;" onclick="return confirm('Are you sure you want to remove the cash-out date?');">
                🗑️ Clear
              </button>
            </div>
            <div style="display:flex; gap:10px; margin-left:auto;">
              <button type="button" onclick="closeCashoutModal()" class="btn-secondary" style="padding:8px 16px; border-radius:6px; font-size:13px; font-weight:600; cursor:pointer; border:1px solid #cbd5e1; background:#fff; color:#475569;">
                Cancel
              </button>
              <button type="submit" name="action" value="save" style="background:#0b57d0; color:#fff; border:none; padding:8px 20px; border-radius:6px; font-size:13px; font-weight:600; cursor:pointer; box-shadow:0 1px 2px rgba(0,0,0,0.05);">
                Save
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>

    <script>
    function openCashoutModal(annexId, annexName, monthVal, currentDate) {{
      document.getElementById('modalAnnexId').value = annexId;
      document.getElementById('modalAnnexName').textContent = annexName;
      document.getElementById('modalMonth').value = monthVal;
      document.getElementById('modalMonthText').textContent = monthVal;
      
      var dateInput = document.getElementById('modalCashoutDate');
      var titleEl = document.getElementById('modalTitle');
      var removeBtn = document.getElementById('modalRemoveBtnContainer');
      
      if (currentDate) {{
        titleEl.textContent = '✏️ Edit Cash-out Date';
        dateInput.value = currentDate;
        removeBtn.style.display = 'block';
      }} else {{
        titleEl.textContent = '💰 Set Cash-out Date';
        var today = new Date().toISOString().split('T')[0];
        dateInput.value = today;
        removeBtn.style.display = 'none';
      }}
      
      var modal = document.getElementById('cashoutModal');
      modal.style.display = 'flex';
    }}

    function closeCashoutModal() {{
      document.getElementById('cashoutModal').style.display = 'none';
    }}

    window.addEventListener('click', function(event) {{
      var modal = document.getElementById('cashoutModal');
      if (event.target === modal) {{
        modal.style.display = 'none';
      }}
    }});
    </script>
    """

    body = f"""
    {sub_nav}
    {error_html}
    {success_html}
    {filter_card}

    {''.join(annex_cards) if annex_cards else '<div class="card"><p class="muted">No annexes match the current filter.</p></div>'}
    {modal_html}
    """

    return layout("Attendance Acceptance", body)


def handle_attendance_cashout_post(handler):
    length = int(handler.headers.get("Content-Length", 0))
    raw = handler.rfile.read(length).decode("utf-8", errors="ignore")
    import urllib.parse
    form = urllib.parse.parse_qs(raw, keep_blank_values=True)

    annex_id_raw = form.get("annex_id", [""])[0].strip()
    month_val = form.get("month", [""])[0].strip()
    cashout_date = form.get("cashout_date", [""])[0].strip()
    action = form.get("action", ["save"])[0].strip()
    return_url = form.get("return_url", [""])[0].strip()

    if not return_url:
        return_url = f"/attendance/acceptance?month={urllib.parse.quote(month_val)}" if month_val else "/attendance/acceptance"

    annex_id = parse_int_or_none(annex_id_raw)
    if not annex_id:
        redirect(handler, return_url)
        return

    conn = db_connect()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS annex_cashouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                annex_id INTEGER NOT NULL,
                month TEXT NOT NULL,
                cashout_date TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(annex_id) REFERENCES contract_annexes(id),
                UNIQUE(annex_id, month)
            )
        """)

        if action == "clear" or not cashout_date:
            conn.execute("DELETE FROM annex_cashouts WHERE annex_id = ? AND month = ?", (annex_id, month_val))
            try:
                conn.execute("UPDATE contract_annexes SET cashout_date = NULL WHERE id = ?", (annex_id,))
            except sqlite3.OperationalError:
                pass
            conn.commit()
        else:
            conn.execute("""
                INSERT INTO annex_cashouts (annex_id, month, cashout_date, created_at, updated_at)
                VALUES (?, ?, ?, datetime('now'), datetime('now'))
                ON CONFLICT(annex_id, month) DO UPDATE SET
                    cashout_date = excluded.cashout_date,
                    updated_at = datetime('now')
            """, (annex_id, month_val, cashout_date))
            try:
                conn.execute("UPDATE contract_annexes SET cashout_date = ? WHERE id = ?", (cashout_date, annex_id))
            except sqlite3.OperationalError:
                pass
            conn.commit()
    finally:
        conn.close()

    redirect(handler, return_url)


def get_payout_data(conn, fy: int, status_filter: str, vendor_filter: int | None, q_filter: str):
    q1_months = [f"{fy:04d}-04", f"{fy:04d}-05", f"{fy:04d}-06"]
    q2_months = [f"{fy:04d}-07", f"{fy:04d}-08", f"{fy:04d}-09"]
    q3_months = [f"{fy:04d}-10", f"{fy:04d}-11", f"{fy:04d}-12"]
    q4_months = [f"{fy+1:04d}-01", f"{fy+1:04d}-02", f"{fy+1:04d}-03"]
    fy_months = q1_months + q2_months + q3_months + q4_months

    fy_start_date = f"{fy:04d}-04-01"
    fy_end_date = f"{fy+1:04d}-03-31"

    month_info = {
        f"{fy:04d}-04": {"num": "04", "name": "Apr", "quarter": "Q1", "sub": f"04/{fy}"},
        f"{fy:04d}-05": {"num": "05", "name": "May", "quarter": "Q1", "sub": f"05/{fy}"},
        f"{fy:04d}-06": {"num": "06", "name": "Jun", "quarter": "Q1", "sub": f"06/{fy}"},
        f"{fy:04d}-07": {"num": "07", "name": "Jul", "quarter": "Q2", "sub": f"07/{fy}"},
        f"{fy:04d}-08": {"num": "08", "name": "Aug", "quarter": "Q2", "sub": f"08/{fy}"},
        f"{fy:04d}-09": {"num": "09", "name": "Sep", "quarter": "Q2", "sub": f"09/{fy}"},
        f"{fy:04d}-10": {"num": "10", "name": "Oct", "quarter": "Q3", "sub": f"10/{fy}"},
        f"{fy:04d}-11": {"num": "11", "name": "Nov", "quarter": "Q3", "sub": f"11/{fy}"},
        f"{fy:04d}-12": {"num": "12", "name": "Dec", "quarter": "Q3", "sub": f"12/{fy}"},
        f"{fy+1:04d}-01": {"num": "01", "name": "Jan", "quarter": "Q4", "sub": f"01/{fy+1}"},
        f"{fy+1:04d}-02": {"num": "02", "name": "Feb", "quarter": "Q4", "sub": f"02/{fy+1}"},
        f"{fy+1:04d}-03": {"num": "03", "name": "Mar", "quarter": "Q4", "sub": f"03/{fy+1}"},
    }

    annex_sql = """
        SELECT 
            a.id as annex_id,
            a.annex_name,
            c.id as contract_id,
            c.framework_no,
            v.id as vendor_id,
            v.company_name,
            v.short_name,
            v.tax_id
        FROM contract_annexes a
        JOIN contracts c ON a.contract_id = c.id
        JOIN vendors v ON c.seller_vendor_id = v.id
        WHERE a.deleted_at IS NULL AND c.deleted_at IS NULL AND v.deleted_at IS NULL
    """
    annex_params = []
    if vendor_filter:
        annex_sql += " AND v.id = ?"
        annex_params.append(vendor_filter)
    if q_filter:
        annex_sql += " AND (v.company_name LIKE ? OR a.annex_name LIKE ? OR c.framework_no LIKE ?)"
        annex_params.extend([f"%{q_filter}%", f"%{q_filter}%", f"%{q_filter}%"])
    annex_sql += " ORDER BY v.company_name COLLATE NOCASE ASC, c.framework_no ASC, a.annex_name ASC"
    annex_rows = conn.execute(annex_sql, annex_params).fetchall()

    # Query all cashouts occurring strictly within this Fiscal Year (April 1 to March 31)
    co_rows = conn.execute("""
        SELECT annex_id, month, cashout_date 
        FROM annex_cashouts 
        WHERE cashout_date IS NOT NULL 
          AND trim(cashout_date) != ''
          AND cashout_date >= ? 
          AND cashout_date <= ?
    """, (fy_start_date, fy_end_date)).fetchall()

    # Group cashout disbursements into their payment calendar month: (annex_id, cashout_month)
    cashout_by_month = {}
    for r in co_rows:
        aid = r["annex_id"]
        c_date = (r["cashout_date"] or "").strip()
        co_month = c_date[:7]
        sm = r["month"]
        if co_month in fy_months:
            cashout_by_month.setdefault((aid, co_month), []).append({
                "service_month": sm,
                "cashout_date": c_date
            })

    # Service months that need wages queried: all fy_months + any service month cashed out in this FY
    needed_service_months = list(set(fy_months) | {r["month"] for r in co_rows if r["month"]})
    ph = ", ".join(["?"] * len(needed_service_months))

    w_rows = conn.execute(f"""
        SELECT l.annex_id, s.month, sum(s.total_amount) as total_wages
        FROM monthly_attendance_summary s
        JOIN contract_staff cs ON cs.id = s.staff_id
        JOIN contract_staff_links l ON l.staff_id = cs.id
        WHERE s.month IN ({ph})
        GROUP BY l.annex_id, s.month
    """, needed_service_months).fetchall()
    wages_map = {(r["annex_id"], r["month"]): float(r["total_wages"] or 0.0) for r in w_rows}

    # Invoices for fallback if wages not found
    inv_rows = conn.execute("""
        SELECT seller_mst, contract_no, service_year, service_month, tg_tttbso
        FROM invoices
        WHERE service_year IS NOT NULL AND service_month IS NOT NULL
    """).fetchall()

    def _norm_code(s):
        return (s or "").replace("-", "").replace(" ", "").strip().lower()

    inv_map = {}
    for inv in inv_rows:
        c_no = _norm_code(inv["contract_no"])
        s_mst = _norm_code(inv["seller_mst"])
        m_str = f"{inv['service_year']:04d}-{inv['service_month']:02d}"
        if c_no and m_str in needed_service_months:
            inv_map[(c_no, s_mst, m_str)] = float(inv["tg_tttbso"] or 0.0)

    def get_service_amount(aid, aname, taxid, sm):
        amt = wages_map.get((aid, sm), 0.0)
        if amt == 0.0:
            a_code = _norm_code(aname)
            tax_code = _norm_code(taxid)
            if (a_code, tax_code, sm) in inv_map:
                amt = inv_map[(a_code, tax_code, sm)]
            elif (a_code, "", sm) in inv_map:
                amt = inv_map[(a_code, "", sm)]
        return amt

    filtered_rows = []
    for a in annex_rows:
        aid = a["annex_id"]
        a_name = a["annex_name"]
        a_tax = a["tax_id"]

        months_data = {}
        row_payroll_total = 0.0
        row_cashout_total = 0.0
        q_payroll = {"Q1": 0.0, "Q2": 0.0, "Q3": 0.0, "Q4": 0.0}
        q_cashout = {"Q1": 0.0, "Q2": 0.0, "Q3": 0.0, "Q4": 0.0}

        for m in fy_months:
            # Concept 1: Payroll - locked payroll amount for service month m
            p_amt = get_service_amount(aid, a_name, a_tax, m)

            # Concept 2: Cash-out - actual payment disbursed to vendor in month m (based on cashout_date)
            co_items = cashout_by_month.get((aid, m), [])
            co_amt = 0.0
            c_dates = []
            for item in co_items:
                c_amt = get_service_amount(aid, a_name, a_tax, item["service_month"])
                co_amt += c_amt
                c_dates.append(item["cashout_date"])

            c_date_str = ", ".join(sorted(list(set(c_dates)))) if c_dates else ""

            q_name = month_info[m]["quarter"]
            q_payroll[q_name] += p_amt
            q_cashout[q_name] += co_amt

            row_payroll_total += p_amt
            row_cashout_total += co_amt

            months_data[m] = {
                "payroll": p_amt,
                "cashout": co_amt,
                "cashout_dates": c_dates,
                "cashout_date_str": c_date_str,
                "amount": co_amt if co_amt > 0 else p_amt,
                "cashout_date": c_dates[0] if c_dates else None
            }

        has_payroll = row_payroll_total > 0
        has_cashout = row_cashout_total > 0
        has_activity = has_payroll or has_cashout

        if status_filter in ("cashout_only", "cashed_out") and not has_cashout:
            continue
        elif status_filter == "payroll_only" and not has_payroll:
            continue
        elif status_filter in ("all_active", "with_cashout", "with_payout") and not has_activity:
            continue

        filtered_rows.append({
            "annex": a,
            "months": months_data,
            "q_payroll": q_payroll,
            "q_cashout": q_cashout,
            "q_totals": q_cashout,
            "row_payroll_total": row_payroll_total,
            "row_cashout_total": row_cashout_total,
            "row_total": row_cashout_total if row_cashout_total > 0 else row_payroll_total,
            "has_cashout": has_cashout,
            "has_payroll": has_payroll,
            "has_payout": has_activity
        })

    col_payroll_totals = {m: 0.0 for m in fy_months}
    col_cashout_totals = {m: 0.0 for m in fy_months}
    q_col_payroll_totals = {"Q1": 0.0, "Q2": 0.0, "Q3": 0.0, "Q4": 0.0}
    q_col_cashout_totals = {"Q1": 0.0, "Q2": 0.0, "Q3": 0.0, "Q4": 0.0}
    grand_payroll_total = 0.0
    grand_cashout_total = 0.0

    for item in filtered_rows:
        grand_payroll_total += item["row_payroll_total"]
        grand_cashout_total += item["row_cashout_total"]

        for q_k in ("Q1", "Q2", "Q3", "Q4"):
            q_col_payroll_totals[q_k] += item["q_payroll"][q_k]
            q_col_cashout_totals[q_k] += item["q_cashout"][q_k]

        for m in fy_months:
            col_payroll_totals[m] += item["months"][m]["payroll"]
            col_cashout_totals[m] += item["months"][m]["cashout"]

    return {
        "fy": fy,
        "fy_name": f"FY{str(fy)[-2:]}",
        "q1_months": q1_months,
        "q2_months": q2_months,
        "q3_months": q3_months,
        "q4_months": q4_months,
        "fy_months": fy_months,
        "month_info": month_info,
        "rows": filtered_rows,
        "col_payroll_totals": col_payroll_totals,
        "col_cashout_totals": col_cashout_totals,
        "col_totals": col_cashout_totals,
        "q_col_payroll_totals": q_col_payroll_totals,
        "q_col_cashout_totals": q_col_cashout_totals,
        "q_col_totals": q_col_cashout_totals,
        "grand_payroll_total": grand_payroll_total,
        "grand_cashout_total": grand_cashout_total,
        "grand_total": grand_cashout_total if grand_cashout_total > 0 else grand_payroll_total,
        "status_filter": status_filter
    }


def page_attendance_payout(filters: dict) -> str:
    today = date.today()
    default_fy = today.year if today.month >= 4 else today.year - 1

    fy_raw = filters.get("fy")
    if isinstance(fy_raw, list):
        fy_raw = fy_raw[0] if fy_raw else None
    try:
        fy = int(fy_raw) if fy_raw else default_fy
    except (ValueError, TypeError):
        fy = default_fy

    status_raw = filters.get("status")
    if isinstance(status_raw, list):
        status_filter = status_raw[0] if status_raw else "all_active"
    else:
        status_filter = status_raw or "all_active"

    if status_filter in ("cashout_only", "cashed_out"):
        status_filter = "cashout_only"
    elif status_filter == "payroll_only":
        status_filter = "payroll_only"
    elif status_filter == "all":
        status_filter = "all"
    else:
        status_filter = "all_active"

    vendor_raw = filters.get("vendor_id")
    if isinstance(vendor_raw, list):
        vendor_raw = vendor_raw[0] if vendor_raw else None
    vendor_filter = parse_int_or_none(vendor_raw)

    q_raw = filters.get("q")
    if isinstance(q_raw, list):
        q_raw = q_raw[0] if q_raw else ""
    q_filter = (q_raw or "").strip()

    conn = db_connect()
    try:
        vendors = conn.execute("SELECT id, company_name, short_name FROM vendors WHERE deleted_at IS NULL AND purchasing = 0 ORDER BY company_name").fetchall()
        data = get_payout_data(conn, fy, status_filter, vendor_filter, q_filter)
    finally:
        conn.close()

    # Sub-nav
    sub_nav = f"""
    <div class="actions" style="margin-bottom: 14px; border-bottom: 1px solid #ddd; padding-bottom: 8px;">
      <a href="/attendance" style="margin-right: 18px; font-weight: bold; color:#666; text-decoration:none;">📅 Daily Attendance</a>
      <a href="/attendance/monthly" style="margin-right: 18px; font-weight: bold; color:#666; text-decoration:none;">💵 Monthly Payroll</a>
      <a href="/attendance/acceptance" style="margin-right: 18px; font-weight: bold; color:#666; text-decoration:none;">📜 Attendance Acceptance</a>
      <a href="/attendance/cashout?fy={fy}&status={status_filter}&vendor_id={vendor_filter or ''}&q={urllib.parse.quote(q_filter)}" style="margin-right: 18px; font-weight: bold; color:#0b57d0; border-bottom: 2px solid #0b57d0; padding-bottom: 8px;">💰 Cash-out</a>
    </div>
    """

    # Status options
    status_options_html = [
        f'<option value="all_active" {"selected" if status_filter == "all_active" else ""}>All Active (Both Payroll & Cash-out)</option>',
        f'<option value="cashout_only" {"selected" if status_filter == "cashout_only" else ""}>Cash-out Only (Hide Payroll)</option>',
        f'<option value="payroll_only" {"selected" if status_filter == "payroll_only" else ""}>Payroll Only (Hide Cash-out)</option>',
        f'<option value="all" {"selected" if status_filter == "all" else ""}>All Annexes</option>',
    ]

    # Vendor options
    vendor_options_html = ['<option value="">-- All Vendors --</option>']
    for v in vendors:
        sel = "selected" if vendor_filter == v["id"] else ""
        v_title = v["short_name"] or v["company_name"] or f"Vendor #{v['id']}"
        vendor_options_html.append(f'<option value="{v["id"]}" {sel}>{escape(v_title)}</option>')

    # Export URL
    export_url = f"/attendance/cashout/export?fy={fy}&status={status_filter}&vendor_id={vendor_filter or ''}&q={urllib.parse.quote(q_filter)}"

    col_min_w = "140px" if status_filter in ("all_active", "all") else "115px"
    tbl_min_w = "1960px" if status_filter in ("all_active", "all") else "1600px"

    # Table rows
    table_rows_html = []
    for idx, r in enumerate(data["rows"], 1):
        a = r["annex"]
        c_name = a["company_name"] or "-"
        fn_no = a["framework_no"] or "-"
        an_name = a["annex_name"] or "-"

        m_cells = []
        for m in data["fy_months"]:
            cell_data = r["months"][m]
            p_amt = cell_data["payroll"]
            co_amt = cell_data["cashout"]
            c_date_str = cell_data["cashout_date_str"]

            border_style = ""
            if m in (data["q1_months"][0], data["q2_months"][0], data["q3_months"][0], data["q4_months"][0]):
                border_style += "border-left: 1px solid #cbd5e1; "
            if m in (data["q1_months"][-1], data["q2_months"][-1], data["q3_months"][-1], data["q4_months"][-1]):
                border_style += "border-right: 1px solid #cbd5e1; "

            p_str = f"{int(round(p_amt)):,}" if p_amt > 0 else "-"
            co_str = f"{int(round(co_amt)):,}" if co_amt > 0 else "-"

            p_color = "#1e293b" if p_amt > 0 else "#94a3b8"
            co_color = "#15803d" if co_amt > 0 else "#94a3b8"

            co_tooltip = f"Actual Cash-out Disbursed on {escape(c_date_str)}" if (co_amt > 0 and c_date_str) else "Actual Cash-out Disbursed"

            if status_filter == "cashout_only":
                # Hide Payroll completely
                if co_amt == 0:
                    cell_content = '<div style="text-align:right; color:#cbd5e1; font-weight:normal; white-space:nowrap;">-</div>'
                else:
                    cell_content = f"""
                    <div style="font-size:12px; line-height:1.4; white-space:nowrap;" title="{co_tooltip}">
                      <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; white-space:nowrap;">
                        <span style="font-size:10px; color:#166534; font-weight:600;">Cash-out:</span>
                        <span style="font-family:monospace; font-weight:700; color:#15803d;">{co_str}</span>
                      </div>
                    </div>
                    """
            elif status_filter == "payroll_only":
                # Hide Cash-out completely
                if p_amt == 0:
                    cell_content = '<div style="text-align:right; color:#cbd5e1; font-weight:normal; white-space:nowrap;">-</div>'
                else:
                    cell_content = f"""
                    <div style="font-size:12px; line-height:1.4; white-space:nowrap;" title="Monthly Payroll Locked">
                      <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; white-space:nowrap;">
                        <span style="font-size:10px; color:#64748b; font-weight:600;">Payroll:</span>
                        <span style="font-family:monospace; font-weight:600; color:#1e293b;">{p_str}</span>
                      </div>
                    </div>
                    """
            else:
                # Both: Line 1 Payroll, Line 2 Cash-out (strictly 2 lines, no wrapping, no cashout date text)
                if p_amt == 0 and co_amt == 0:
                    cell_content = '<div style="text-align:center; color:#cbd5e1; font-weight:normal; white-space:nowrap;">-</div>'
                else:
                    cell_content = f"""
                    <div style="font-size:11.5px; line-height:1.4; white-space:nowrap;">
                      <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; white-space:nowrap;" title="Monthly Payroll Locked">
                        <span style="font-size:10px; color:#64748b; font-weight:600;">Payroll:</span>
                        <span style="font-family:monospace; font-weight:600; color:{p_color};">{p_str}</span>
                      </div>
                      <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; white-space:nowrap; margin-top:3px;" title="{co_tooltip}">
                        <span style="font-size:10px; color:#166534; font-weight:600;">Cash-out:</span>
                        <span style="font-family:monospace; font-weight:700; color:{co_color};">{co_str}</span>
                      </div>
                    </div>
                    """

            m_cells.append(f'<td style="text-align:right; padding:6px 10px; min-width:{col_min_w}; vertical-align:middle; white-space:nowrap; {border_style}">{cell_content}</td>')

        row_p_str = f"{int(round(r['row_payroll_total'])):,}" if r['row_payroll_total'] > 0 else "-"
        row_co_str = f"{int(round(r['row_cashout_total'])):,}" if r['row_cashout_total'] > 0 else "-"

        if status_filter == "cashout_only":
            row_total_content = f"""
            <div style="font-size:12px; line-height:1.4; white-space:nowrap; text-align:right;">
              <span style="font-size:10px; color:#166534; font-weight:600;">Cash-out:</span>
              <b style="font-family:monospace; color:#15803d; margin-left:4px;">{row_co_str}</b>
            </div>
            """
        elif status_filter == "payroll_only":
            row_total_content = f"""
            <div style="font-size:12px; line-height:1.4; white-space:nowrap; text-align:right;">
              <span style="font-size:10px; color:#64748b; font-weight:600;">Payroll:</span>
              <b style="font-family:monospace; color:#1e293b; margin-left:4px;">{row_p_str}</b>
            </div>
            """
        else:
            row_total_content = f"""
            <div style="font-size:11.5px; line-height:1.4; white-space:nowrap;">
              <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; white-space:nowrap;" title="Total FY Payroll">
                <span style="font-size:10px; color:#64748b; font-weight:600;">Payroll:</span>
                <b style="font-family:monospace; color:#1e293b;">{row_p_str}</b>
              </div>
              <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; white-space:nowrap; margin-top:3px;" title="Total FY Cash-out">
                <span style="font-size:10px; color:#166534; font-weight:600;">Cash-out:</span>
                <b style="font-family:monospace; color:#15803d;">{row_co_str}</b>
              </div>
            </div>
            """

        table_rows_html.append(f"""
        <tr style="border-bottom: 1px solid #e2e8f0;">
          <td style="text-align:center; color:#64748b; font-size:12px; vertical-align:middle; white-space:nowrap;">{idx}</td>
          <td style="vertical-align:middle; white-space:nowrap;"><b>{escape(c_name)}</b></td>
          <td style="font-size:12px; color:#475569; vertical-align:middle; white-space:nowrap;">{escape(fn_no)}</td>
          <td style="vertical-align:middle; white-space:nowrap;"><span style="font-weight:600; color:#0b57d0;">{escape(an_name)}</span></td>
          {''.join(m_cells)}
          <td style="text-align:right; font-family:monospace; background:#f8fafc; border-left:2px solid #cbd5e1; padding:6px 10px; vertical-align:middle; white-space:nowrap; min-width:160px;">
            {row_total_content}
          </td>
        </tr>
        """)

    if not table_rows_html:
        table_rows_html.append(f"""
        <tr>
          <td colspan="17" style="text-align:center; padding:36px; color:#64748b; font-size:14px;">
            No annexes match the current filter in <b>{data['fy_name']}</b>.
          </td>
        </tr>
        """)

    # Bottom totals
    footer_cells = []
    for m in data["fy_months"]:
        col_p = data["col_payroll_totals"][m]
        col_co = data["col_cashout_totals"][m]
        col_p_str = f"{int(round(col_p)):,}" if col_p > 0 else "-"
        col_co_str = f"{int(round(col_co)):,}" if col_co > 0 else "-"

        border_style = ""
        if m in (data["q1_months"][0], data["q2_months"][0], data["q3_months"][0], data["q4_months"][0]):
            border_style += "border-left: 1px solid #cbd5e1; "
        if m in (data["q1_months"][-1], data["q2_months"][-1], data["q3_months"][-1], data["q4_months"][-1]):
            border_style += "border-right: 1px solid #cbd5e1; "

        if status_filter == "cashout_only":
            footer_content = f"""
            <div style="font-size:12px; text-align:right; white-space:nowrap;" title="Total Cash-out for month {m}">
              <span style="font-size:10px; color:#166534; font-weight:600;">CO:</span>
              <b style="color:#15803d; margin-left:4px;">{col_co_str}</b>
            </div>
            """
        elif status_filter == "payroll_only":
            footer_content = f"""
            <div style="font-size:12px; text-align:right; white-space:nowrap;" title="Total Payroll for month {m}">
              <span style="font-size:10px; color:#64748b; font-weight:600;">P:</span>
              <b style="color:#1e293b; margin-left:4px;">{col_p_str}</b>
            </div>
            """
        else:
            footer_content = f"""
            <div style="font-size:11.5px; line-height:1.4; white-space:nowrap;">
              <div style="display:flex; justify-content:space-between; align-items:center; gap:6px; color:#475569; white-space:nowrap;" title="Total Payroll for month {m}">
                <span style="font-size:10px; color:#64748b; font-weight:600;">P:</span>
                <b>{col_p_str}</b>
              </div>
              <div style="display:flex; justify-content:space-between; align-items:center; gap:6px; color:#15803d; margin-top:3px; white-space:nowrap;" title="Total Cash-out for month {m}">
                <span style="font-size:10px; color:#166534; font-weight:600;">CO:</span>
                <b>{col_co_str}</b>
              </div>
            </div>
            """

        footer_cells.append(f"""
        <td style="padding:8px 10px; font-family:monospace; min-width:{col_min_w}; vertical-align:middle; white-space:nowrap; {border_style}">
          {footer_content}
        </td>
        """)

    grand_p_str = f"{int(round(data['grand_payroll_total'])):,} VND"
    grand_co_str = f"{int(round(data['grand_cashout_total'])):,} VND"

    if status_filter == "cashout_only":
        summary_banner = f"""Total FY Cash-out: <span style="font-weight:bold; font-family:monospace; color:#15803d; font-size:15px;">{grand_co_str}</span>"""
        legend_html = f"""
        <div style="display:flex; align-items:center; gap:12px; font-size:11px; background:#f8fafc; padding:4px 10px; border-radius:6px; border:1px solid #e2e8f0;">
          <span style="font-size:9.5px; color:#166534; background:#dcfce7; padding:1px 4px; border-radius:3px; font-weight:600; border:1px solid #bbf7d0;">Cash-out</span>
          <span>Actual vendor disbursements (Payroll hidden)</span>
        </div>
        """
        grand_total_content = f"""
        <div style="font-size:12px; text-align:right; white-space:nowrap;" title="Grand Total FY Cash-out">
          <span style="font-size:10px; color:#166534; font-weight:600;">Cash-out:</span>
          <b style="color:#15803d; margin-left:4px; font-size:13px;">{grand_co_str}</b>
        </div>
        """
    elif status_filter == "payroll_only":
        summary_banner = f"""Total FY Payroll: <span style="font-weight:bold; font-family:monospace; color:#0f172a; font-size:15px;">{grand_p_str}</span>"""
        legend_html = f"""
        <div style="display:flex; align-items:center; gap:12px; font-size:11px; background:#f8fafc; padding:4px 10px; border-radius:6px; border:1px solid #e2e8f0;">
          <span style="font-size:9.5px; color:#64748b; background:#f1f5f9; padding:1px 4px; border-radius:3px; font-weight:600; border:1px solid #cbd5e1;">Payroll</span>
          <span>Locked monthly payroll accruals (Cash-out hidden)</span>
        </div>
        """
        grand_total_content = f"""
        <div style="font-size:12px; text-align:right; white-space:nowrap;" title="Grand Total FY Payroll">
          <span style="font-size:10px; color:#64748b; font-weight:600;">Payroll:</span>
          <b style="color:#1e293b; margin-left:4px; font-size:13px;">{grand_p_str}</b>
        </div>
        """
    else:
        summary_banner = f"""Total FY Payroll: <span style="font-weight:bold; font-family:monospace; color:#0f172a; font-size:14px;">{grand_p_str}</span>
        &nbsp;&bull;&nbsp;
        Total FY Cash-out: <span style="font-weight:bold; font-family:monospace; color:#15803d; font-size:15px;">{grand_co_str}</span>"""
        legend_html = f"""
        <div style="display:flex; align-items:center; gap:12px; font-size:11px; background:#f8fafc; padding:4px 10px; border-radius:6px; border:1px solid #e2e8f0;">
          <span style="display:inline-flex; align-items:center; gap:4px;">
            <span style="font-size:9.5px; color:#64748b; background:#f1f5f9; padding:1px 4px; border-radius:3px; font-weight:600; border:1px solid #cbd5e1;">Payroll</span>
            <span>Locked accrual (Line 1)</span>
          </span>
          <span style="display:inline-flex; align-items:center; gap:4px;">
            <span style="font-size:9.5px; color:#166534; background:#dcfce7; padding:1px 4px; border-radius:3px; font-weight:600; border:1px solid #bbf7d0;">Cash-out</span>
            <span>Vendor payment (Line 2)</span>
          </span>
        </div>
        """
        grand_total_content = f"""
        <div style="font-size:11.5px; line-height:1.4; white-space:nowrap;">
          <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; white-space:nowrap;" title="Grand Total FY Payroll">
            <span style="font-size:10px; color:#64748b; font-weight:600;">Payroll:</span>
            <span style="font-weight:bold; color:#1e293b;">{grand_p_str}</span>
          </div>
          <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; white-space:nowrap; margin-top:3px;" title="Grand Total FY Cash-out">
            <span style="font-size:10px; color:#166534; font-weight:600;">Cash-out:</span>
            <span style="font-weight:bold; color:#15803d;">{grand_co_str}</span>
          </div>
        </div>
        """

    body = f"""
    {sub_nav}

    <!-- Filters and Actions Card -->
    <div class="card" style="margin-bottom: 16px;">
      <div style="display:flex; justify-content:space-between; align-items:flex-end; flex-wrap:wrap; gap:16px;">
        <form method="GET" action="/attendance/cashout" id="filterForm" class="filters" style="margin:0; display:flex; flex-wrap:wrap; gap:14px; align-items:flex-end;">
          <!-- Fiscal Year Calendar & Year Picker -->
          <div style="position:relative;">
            <div class="label" style="font-weight:600; font-size:12px; margin-bottom:4px;">Fiscal Year (FY)</div>
            <div style="display:inline-flex; align-items:center; background:#fff; border:1px solid #cbd5e1; border-radius:6px; box-shadow:0 1px 2px rgba(0,0,0,0.04); overflow:hidden;">
              <button type="button" onclick="stepFY(-1)" title="Previous Fiscal Year (FY{str(fy-1)[-2:]})" style="background:#f8fafc; border:none; border-right:1px solid #cbd5e1; cursor:pointer; padding:7px 10px; color:#475569; font-size:12px; font-weight:bold; transition:background 0.15s;" onmouseover="this.style.background='#e2e8f0'" onmouseout="this.style.background='#f8fafc'">◀</button>
              <button type="button" id="fyPickerBtn" onclick="toggleFyCalendar(event)" style="background:#fff; border:none; cursor:pointer; font-weight:700; font-size:13px; color:#0f172a; display:inline-flex; align-items:center; gap:6px; padding:6px 12px; transition:background 0.15s;" onmouseover="this.style.background='#f8fafc'" onmouseout="this.style.background='#fff'" title="Click to open calendar and select year">
                <span>📅 <b>FY{str(fy)[-2:]}</b> ({fy})</span>
                <span style="font-size:11px; font-weight:normal; color:#64748b;">(01/04/{fy} &ndash; 31/03/{fy+1})</span>
                <span style="font-size:10px; color:#64748b;">▾</span>
              </button>
              <button type="button" onclick="stepFY(1)" title="Next Fiscal Year (FY{str(fy+1)[-2:]})" style="background:#f8fafc; border:none; border-left:1px solid #cbd5e1; cursor:pointer; padding:7px 10px; color:#475569; font-size:12px; font-weight:bold; transition:background 0.15s;" onmouseover="this.style.background='#e2e8f0'" onmouseout="this.style.background='#f8fafc'">▶</button>
            </div>
            <input type="hidden" name="fy" id="fyHiddenInput" value="{fy}">

            <!-- Interactive Calendar Year Picker Popup -->
            <div id="fyCalendarPopup" style="display:none; position:absolute; top:calc(100% + 6px); left:0; z-index:100; background:#fff; border:1px solid #cbd5e1; border-radius:10px; box-shadow:0 12px 28px rgba(0,0,0,0.15); width:290px; padding:14px;">
              <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; border-bottom:1px solid #e2e8f0; padding-bottom:8px;">
                <button type="button" onclick="navDecade(-1, event)" style="background:#f1f5f9; border:1px solid #cbd5e1; border-radius:4px; cursor:pointer; font-size:13px; font-weight:bold; color:#334155; padding:3px 9px;">‹</button>
                <span id="decadeTitle" style="font-weight:700; font-size:13px; color:#0f172a;"></span>
                <button type="button" onclick="navDecade(1, event)" style="background:#f1f5f9; border:1px solid #cbd5e1; border-radius:4px; cursor:pointer; font-size:13px; font-weight:bold; color:#334155; padding:3px 9px;">›</button>
              </div>
              <div id="yearGrid" style="display:grid; grid-template-columns:repeat(4, 1fr); gap:6px; margin-bottom:12px;">
                <!-- Generated by JS -->
              </div>
              <div style="border-top:1px solid #e2e8f0; padding-top:10px;">
                <div style="font-size:11px; color:#64748b; margin-bottom:4px; font-weight:600;">Or select from calendar month:</div>
                <input type="month" id="fyMonthPicker" onchange="pickMonthFY(this.value)" style="width:100%; box-sizing:border-box; padding:6px 10px; font-size:12px; border:1px solid #cbd5e1; border-radius:6px; background:#f8fafc;">
              </div>
            </div>
          </div>

          <div>
            <div class="label" style="font-weight:600; font-size:12px; margin-bottom:4px;">Status</div>
            <select name="status" onchange="this.form.submit()" style="padding:6px 12px; border:1px solid #cbd5e1; border-radius:6px; font-size:13px; background:#fff;">
              {''.join(status_options_html)}
            </select>
          </div>
          <div>
            <div class="label" style="font-weight:600; font-size:12px; margin-bottom:4px;">Vendor</div>
            <select name="vendor_id" onchange="this.form.submit()" style="padding:6px 12px; border:1px solid #cbd5e1; border-radius:6px; font-size:13px; background:#fff;">
              {''.join(vendor_options_html)}
            </select>
          </div>
          <div>
            <div class="label" style="font-weight:600; font-size:12px; margin-bottom:4px;">Search</div>
            <input type="text" name="q" value="{escape(q_filter)}" placeholder="Search vendor / annex..." style="padding:6px 10px; border:1px solid #cbd5e1; border-radius:6px; font-size:13px; width:180px;">
          </div>
          <div>
            <button type="submit" class="btn" style="padding:6px 14px; background:#4f46e5; color:#fff; border:none; border-radius:6px; font-size:13px; font-weight:600; cursor:pointer;">Filter</button>
          </div>
        </form>

        <div>
          <a href="{export_url}" class="btn" style="background:#137333; color:#fff; text-decoration:none; padding:7px 16px; border-radius:6px; font-size:13px; font-weight:600; display:inline-flex; align-items:center; gap:6px; box-shadow:0 1px 2px rgba(0,0,0,0.05);" title="Export this Cash-out report to CSV file">
            📥 Export to CSV
          </a>
        </div>
      </div>
    </div>

    <!-- Cash-out Table Card -->
    <div class="card" style="padding: 0; overflow: hidden;">
      <div style="padding:16px 20px; border-bottom:1px solid #e2e8f0; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">
        <div>
          <h3 style="margin:0; font-size:16px; color:#0f172a;">Fiscal Year Cash-out Overview - {data['fy_name']}</h3>
          <p style="margin:4px 0 0; font-size:12px; color:#64748b;">
            Period: 01/04/{fy} &rarr; 31/03/{fy+1} &bull; Ordered by Company Name &bull; Showing {len(data['rows'])} annexes
          </p>
        </div>
        <div style="display:flex; align-items:center; gap:20px; flex-wrap:wrap;">
          <div style="font-size:13px; color:#475569;">
            {summary_banner}
          </div>
          {legend_html}
        </div>
      </div>

      <div style="overflow-x: auto;">
        <table class="table" style="width:100%; border-collapse:collapse; min-width:{tbl_min_w}; font-size:13px; margin:0;">
          <thead>
            <tr style="background:#f1f5f9; border-bottom: 1px solid #cbd5e1;">
              <th rowspan="2" style="text-align:center; width:36px; vertical-align:middle; border-bottom: 2px solid #cbd5e1; white-space:nowrap;">#</th>
              <th rowspan="2" style="text-align:left; min-width:190px; vertical-align:middle; border-bottom: 2px solid #cbd5e1; white-space:nowrap;">Company (Vendor)</th>
              <th rowspan="2" style="text-align:left; min-width:160px; vertical-align:middle; border-bottom: 2px solid #cbd5e1; white-space:nowrap;">Framework Contract</th>
              <th rowspan="2" style="text-align:left; min-width:140px; vertical-align:middle; border-bottom: 2px solid #cbd5e1; white-space:nowrap;">Annex</th>
              <th colspan="3" style="text-align:center; background:#e0f2fe; color:#0369a1; border-left:1px solid #cbd5e1; border-right:1px solid #cbd5e1; font-weight:700; padding:8px;">Quarter 1 (Q1)</th>
              <th colspan="3" style="text-align:center; background:#fef3c7; color:#b45309; border-left:1px solid #cbd5e1; border-right:1px solid #cbd5e1; font-weight:700; padding:8px;">Quarter 2 (Q2)</th>
              <th colspan="3" style="text-align:center; background:#ede9fe; color:#6d28d9; border-left:1px solid #cbd5e1; border-right:1px solid #cbd5e1; font-weight:700; padding:8px;">Quarter 3 (Q3)</th>
              <th colspan="3" style="text-align:center; background:#dcfce7; color:#15803d; border-left:1px solid #cbd5e1; border-right:1px solid #cbd5e1; font-weight:700; padding:8px;">Quarter 4 (Q4)</th>
              <th rowspan="2" style="text-align:right; min-width:160px; background:#f8fafc; border-left:2px solid #cbd5e1; vertical-align:middle; font-weight:700; border-bottom: 2px solid #cbd5e1; white-space:nowrap;">Total {data['fy_name']}</th>
            </tr>
            <tr style="background:#f8fafc; border-bottom: 2px solid #cbd5e1; font-size:12px;">
              <!-- Q1 Months -->
              <th style="text-align:right; padding:6px 10px; min-width:{col_min_w}; border-left:1px solid #cbd5e1; white-space:nowrap;">Apr<br><span style="font-size:11px; font-weight:normal; color:#64748b;">(04/{fy})</span></th>
              <th style="text-align:right; padding:6px 10px; min-width:{col_min_w}; white-space:nowrap;">May<br><span style="font-size:11px; font-weight:normal; color:#64748b;">(05/{fy})</span></th>
              <th style="text-align:right; padding:6px 10px; min-width:{col_min_w}; border-right:1px solid #cbd5e1; white-space:nowrap;">Jun<br><span style="font-size:11px; font-weight:normal; color:#64748b;">(06/{fy})</span></th>
              <!-- Q2 Months -->
              <th style="text-align:right; padding:6px 10px; min-width:{col_min_w}; border-left:1px solid #cbd5e1; white-space:nowrap;">Jul<br><span style="font-size:11px; font-weight:normal; color:#64748b;">(07/{fy})</span></th>
              <th style="text-align:right; padding:6px 10px; min-width:{col_min_w}; white-space:nowrap;">Aug<br><span style="font-size:11px; font-weight:normal; color:#64748b;">(08/{fy})</span></th>
              <th style="text-align:right; padding:6px 10px; min-width:{col_min_w}; border-right:1px solid #cbd5e1; white-space:nowrap;">Sep<br><span style="font-size:11px; font-weight:normal; color:#64748b;">(09/{fy})</span></th>
              <!-- Q3 Months -->
              <th style="text-align:right; padding:6px 10px; min-width:{col_min_w}; border-left:1px solid #cbd5e1; white-space:nowrap;">Oct<br><span style="font-size:11px; font-weight:normal; color:#64748b;">(10/{fy})</span></th>
              <th style="text-align:right; padding:6px 10px; min-width:{col_min_w}; white-space:nowrap;">Nov<br><span style="font-size:11px; font-weight:normal; color:#64748b;">(11/{fy})</span></th>
              <th style="text-align:right; padding:6px 10px; min-width:{col_min_w}; border-right:1px solid #cbd5e1; white-space:nowrap;">Dec<br><span style="font-size:11px; font-weight:normal; color:#64748b;">(12/{fy})</span></th>
              <!-- Q4 Months -->
              <th style="text-align:right; padding:6px 10px; min-width:{col_min_w}; border-left:1px solid #cbd5e1; white-space:nowrap;">Jan<br><span style="font-size:11px; font-weight:normal; color:#64748b;">(01/{fy+1})</span></th>
              <th style="text-align:right; padding:6px 10px; min-width:{col_min_w}; white-space:nowrap;">Feb<br><span style="font-size:11px; font-weight:normal; color:#64748b;">(02/{fy+1})</span></th>
              <th style="text-align:right; padding:6px 10px; min-width:{col_min_w}; border-right:1px solid #cbd5e1; white-space:nowrap;">Mar<br><span style="font-size:11px; font-weight:normal; color:#64748b;">(03/{fy+1})</span></th>
            </tr>
          </thead>
          <tbody>
            {''.join(table_rows_html)}
          </tbody>
          <tfoot>
            <tr style="background:#f1f5f9; border-top:2px solid #64748b; font-weight:bold;">
              <td colspan="4" style="text-align:right; padding:10px 12px; font-weight:bold; vertical-align:middle; white-space:nowrap;">TOTAL:</td>
              {''.join(footer_cells)}
              <td style="text-align:right; padding:8px 10px; font-family:monospace; background:#e2e8f0; border-left:2px solid #cbd5e1; vertical-align:middle; min-width:160px; white-space:nowrap;">
                {grand_total_content}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>

    <!-- Calendar Year Picker Script -->
    <script>
    let selectedFY = {fy};
    let currentDecadeStart = Math.floor(selectedFY / 12) * 12;

    function renderYearGrid() {{
      const grid = document.getElementById('yearGrid');
      const title = document.getElementById('decadeTitle');
      if (!grid || !title) return;
      grid.innerHTML = '';
      const start = currentDecadeStart;
      const end = start + 11;
      title.textContent = `${{start}} - ${{end}}`;
      for (let y = start; y <= end; y++) {{
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.textContent = y;
        btn.style.padding = '8px 4px';
        btn.style.fontSize = '12px';
        btn.style.borderRadius = '6px';
        btn.style.cursor = 'pointer';
        btn.style.border = '1px solid ' + (y === selectedFY ? '#0b57d0' : '#e2e8f0');
        btn.style.background = (y === selectedFY ? '#0b57d0' : '#f8fafc');
        btn.style.color = (y === selectedFY ? '#fff' : '#1e293b');
        btn.style.fontWeight = (y === selectedFY ? '700' : '500');
        btn.onmouseover = function() {{ if (y !== selectedFY) this.style.background = '#e2e8f0'; }};
        btn.onmouseout = function() {{ if (y !== selectedFY) this.style.background = '#f8fafc'; }};
        btn.onclick = function(e) {{
          e.preventDefault();
          selectFY(y);
        }};
        grid.appendChild(btn);
      }}
    }}

    function navDecade(direction, e) {{
      if (e) e.stopPropagation();
      currentDecadeStart += direction * 12;
      renderYearGrid();
    }}

    function selectFY(year) {{
      const input = document.getElementById('fyHiddenInput');
      if (input) {{
        input.value = year;
        const popup = document.getElementById('fyCalendarPopup');
        if (popup) popup.style.display = 'none';
        input.form.submit();
      }}
    }}

    function stepFY(delta) {{
      const current = parseInt(document.getElementById('fyHiddenInput').value, 10) || selectedFY;
      selectFY(current + delta);
    }}

    function pickMonthFY(monthVal) {{
      if (!monthVal) return;
      const parts = monthVal.split('-');
      const y = parseInt(parts[0], 10);
      const m = parseInt(parts[1], 10);
      const derivedFy = (m >= 4) ? y : y - 1;
      selectFY(derivedFy);
    }}

    function toggleFyCalendar(e) {{
      if (e) e.stopPropagation();
      const popup = document.getElementById('fyCalendarPopup');
      if (!popup) return;
      if (popup.style.display === 'none' || !popup.style.display) {{
        currentDecadeStart = Math.floor(selectedFY / 12) * 12;
        renderYearGrid();
        popup.style.display = 'block';
      }} else {{
        popup.style.display = 'none';
      }}
    }}

    document.addEventListener('click', function(e) {{
      const popup = document.getElementById('fyCalendarPopup');
      const btn = document.getElementById('fyPickerBtn');
      if (popup && popup.style.display === 'block') {{
        if (!popup.contains(e.target) && (!btn || !btn.contains(e.target))) {{
          popup.style.display = 'none';
        }}
      }}
    }});
    </script>
    """

    return layout(f"Timesheet & Payroll - Cash-out {data['fy_name']}", body)


def handle_attendance_payout_export_get(handler):
    import csv
    import io
    import urllib.parse
    from datetime import datetime

    parsed = urllib.parse.urlparse(handler.path)
    qs = urllib.parse.parse_qs(parsed.query)

    today = date.today()
    default_fy = today.year if today.month >= 4 else today.year - 1

    fy_raw = qs.get("fy", [default_fy])[0]
    try:
        fy = int(fy_raw)
    except (ValueError, TypeError):
        fy = default_fy

    status_raw = qs.get("status", ["all_active"])[0]
    if status_raw in ("cashed_out", "cashout_only"):
        status_filter = "cashout_only"
    elif status_raw == "payroll_only":
        status_filter = "payroll_only"
    elif status_raw == "all":
        status_filter = "all"
    else:
        status_filter = "all_active"

    vendor_filter = parse_int_or_none(qs.get("vendor_id", [""])[0])
    q_filter = (qs.get("q", [""])[0] or "").strip()

    conn = db_connect()
    try:
        data = get_payout_data(conn, fy, status_filter, vendor_filter, q_filter)
    finally:
        conn.close()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([f"Mizuho IT Outsourcing - Cash-out Report {data['fy_name']} (01/04/{fy} - 31/03/{fy+1})"])
    writer.writerow([f"Filter: {status_filter} | Exported At: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"])
    writer.writerow([])

    if status_filter == "cashout_only":
        csv_header = [
            "No.", "Company", "Framework Contract", "Annex",
            f"Q1 - Apr (04/{fy}) Cash-out", f"Q1 - May (05/{fy}) Cash-out", f"Q1 - Jun (06/{fy}) Cash-out", "Q1 Cash-out Subtotal",
            f"Q2 - Jul (07/{fy}) Cash-out", f"Q2 - Aug (08/{fy}) Cash-out", f"Q2 - Sep (09/{fy}) Cash-out", "Q2 Cash-out Subtotal",
            f"Q3 - Oct (10/{fy}) Cash-out", f"Q3 - Nov (11/{fy}) Cash-out", f"Q3 - Dec (12/{fy}) Cash-out", "Q3 Cash-out Subtotal",
            f"Q4 - Jan (01/{fy+1}) Cash-out", f"Q4 - Feb (02/{fy+1}) Cash-out", f"Q4 - Mar (03/{fy+1}) Cash-out", "Q4 Cash-out Subtotal",
            f"Total FY Cash-out"
        ]
        writer.writerow(csv_header)
        for idx, r in enumerate(data["rows"], 1):
            a = r["annex"]
            row = [idx, a["company_name"] or "", a["framework_no"] or "", a["annex_name"] or ""]
            for m in data["q1_months"]: row.append(int(round(r["months"][m]["cashout"])))
            row.append(int(round(r["q_cashout"]["Q1"])))
            for m in data["q2_months"]: row.append(int(round(r["months"][m]["cashout"])))
            row.append(int(round(r["q_cashout"]["Q2"])))
            for m in data["q3_months"]: row.append(int(round(r["months"][m]["cashout"])))
            row.append(int(round(r["q_cashout"]["Q3"])))
            for m in data["q4_months"]: row.append(int(round(r["months"][m]["cashout"])))
            row.append(int(round(r["q_cashout"]["Q4"])))
            row.append(int(round(r["row_cashout_total"])))
            writer.writerow(row)

        tot_row = ["TOTAL", "", "", ""]
        for m in data["q1_months"]: tot_row.append(int(round(data["col_cashout_totals"][m])))
        tot_row.append(int(round(data["q_col_cashout_totals"]["Q1"])))
        for m in data["q2_months"]: tot_row.append(int(round(data["col_cashout_totals"][m])))
        tot_row.append(int(round(data["q_col_cashout_totals"]["Q2"])))
        for m in data["q3_months"]: tot_row.append(int(round(data["col_cashout_totals"][m])))
        tot_row.append(int(round(data["q_col_cashout_totals"]["Q3"])))
        for m in data["q4_months"]: tot_row.append(int(round(data["col_cashout_totals"][m])))
        tot_row.append(int(round(data["q_col_cashout_totals"]["Q4"])))
        tot_row.append(int(round(data["grand_cashout_total"])))
        writer.writerow(tot_row)

    elif status_filter == "payroll_only":
        csv_header = [
            "No.", "Company", "Framework Contract", "Annex",
            f"Q1 - Apr (04/{fy}) Payroll", f"Q1 - May (05/{fy}) Payroll", f"Q1 - Jun (06/{fy}) Payroll", "Q1 Payroll Subtotal",
            f"Q2 - Jul (07/{fy}) Payroll", f"Q2 - Aug (08/{fy}) Payroll", f"Q2 - Sep (09/{fy}) Payroll", "Q2 Payroll Subtotal",
            f"Q3 - Oct (10/{fy}) Payroll", f"Q3 - Nov (11/{fy}) Payroll", f"Q3 - Dec (12/{fy}) Payroll", "Q3 Payroll Subtotal",
            f"Q4 - Jan (01/{fy+1}) Payroll", f"Q4 - Feb (02/{fy+1}) Payroll", f"Q4 - Mar (03/{fy+1}) Payroll", "Q4 Payroll Subtotal",
            f"Total FY Payroll"
        ]
        writer.writerow(csv_header)
        for idx, r in enumerate(data["rows"], 1):
            a = r["annex"]
            row = [idx, a["company_name"] or "", a["framework_no"] or "", a["annex_name"] or ""]
            for m in data["q1_months"]: row.append(int(round(r["months"][m]["payroll"])))
            row.append(int(round(r["q_payroll"]["Q1"])))
            for m in data["q2_months"]: row.append(int(round(r["months"][m]["payroll"])))
            row.append(int(round(r["q_payroll"]["Q2"])))
            for m in data["q3_months"]: row.append(int(round(r["months"][m]["payroll"])))
            row.append(int(round(r["q_payroll"]["Q3"])))
            for m in data["q4_months"]: row.append(int(round(r["months"][m]["payroll"])))
            row.append(int(round(r["q_payroll"]["Q4"])))
            row.append(int(round(r["row_payroll_total"])))
            writer.writerow(row)

        tot_row = ["TOTAL", "", "", ""]
        for m in data["q1_months"]: tot_row.append(int(round(data["col_payroll_totals"][m])))
        tot_row.append(int(round(data["q_col_payroll_totals"]["Q1"])))
        for m in data["q2_months"]: tot_row.append(int(round(data["col_payroll_totals"][m])))
        tot_row.append(int(round(data["q_col_payroll_totals"]["Q2"])))
        for m in data["q3_months"]: tot_row.append(int(round(data["col_payroll_totals"][m])))
        tot_row.append(int(round(data["q_col_payroll_totals"]["Q3"])))
        for m in data["q4_months"]: tot_row.append(int(round(data["col_payroll_totals"][m])))
        tot_row.append(int(round(data["q_col_payroll_totals"]["Q4"])))
        tot_row.append(int(round(data["grand_payroll_total"])))
        writer.writerow(tot_row)

    else:
        # all_active or all
        csv_header = [
            "No.", "Company", "Framework Contract", "Annex",
            f"Q1 - Apr (04/{fy}) Payroll", f"Q1 - Apr (04/{fy}) Cash-out",
            f"Q1 - May (05/{fy}) Payroll", f"Q1 - May (05/{fy}) Cash-out",
            f"Q1 - Jun (06/{fy}) Payroll", f"Q1 - Jun (06/{fy}) Cash-out",
            "Q1 Payroll Subtotal", "Q1 Cash-out Subtotal",
            f"Q2 - Jul (07/{fy}) Payroll", f"Q2 - Jul (07/{fy}) Cash-out",
            f"Q2 - Aug (08/{fy}) Payroll", f"Q2 - Aug (08/{fy}) Cash-out",
            f"Q2 - Sep (09/{fy}) Payroll", f"Q2 - Sep (09/{fy}) Cash-out",
            "Q2 Payroll Subtotal", "Q2 Cash-out Subtotal",
            f"Q3 - Oct (10/{fy}) Payroll", f"Q3 - Oct (10/{fy}) Cash-out",
            f"Q3 - Nov (11/{fy}) Payroll", f"Q3 - Nov (11/{fy}) Cash-out",
            f"Q3 - Dec (12/{fy}) Payroll", f"Q3 - Dec (12/{fy}) Cash-out",
            "Q3 Payroll Subtotal", "Q3 Cash-out Subtotal",
            f"Q4 - Jan (01/{fy+1}) Payroll", f"Q4 - Jan (01/{fy+1}) Cash-out",
            f"Q4 - Feb (02/{fy+1}) Payroll", f"Q4 - Feb (02/{fy+1}) Cash-out",
            f"Q4 - Mar (03/{fy+1}) Payroll", f"Q4 - Mar (03/{fy+1}) Cash-out",
            "Q4 Payroll Subtotal", "Q4 Cash-out Subtotal",
            f"Total FY Payroll", f"Total FY Cash-out"
        ]
        writer.writerow(csv_header)

        for idx, r in enumerate(data["rows"], 1):
            a = r["annex"]
            row = [idx, a["company_name"] or "", a["framework_no"] or "", a["annex_name"] or ""]
            for m in data["q1_months"]:
                row.append(int(round(r["months"][m]["payroll"])))
                row.append(int(round(r["months"][m]["cashout"])))
            row.append(int(round(r["q_payroll"]["Q1"])))
            row.append(int(round(r["q_cashout"]["Q1"])))
            for m in data["q2_months"]:
                row.append(int(round(r["months"][m]["payroll"])))
                row.append(int(round(r["months"][m]["cashout"])))
            row.append(int(round(r["q_payroll"]["Q2"])))
            row.append(int(round(r["q_cashout"]["Q2"])))
            for m in data["q3_months"]:
                row.append(int(round(r["months"][m]["payroll"])))
                row.append(int(round(r["months"][m]["cashout"])))
            row.append(int(round(r["q_payroll"]["Q3"])))
            row.append(int(round(r["q_cashout"]["Q3"])))
            for m in data["q4_months"]:
                row.append(int(round(r["months"][m]["payroll"])))
                row.append(int(round(r["months"][m]["cashout"])))
            row.append(int(round(r["q_payroll"]["Q4"])))
            row.append(int(round(r["q_cashout"]["Q4"])))
            row.append(int(round(r["row_payroll_total"])))
            row.append(int(round(r["row_cashout_total"])))
            writer.writerow(row)

        tot_row = ["TOTAL", "", "", ""]
        for m in data["q1_months"]:
            tot_row.append(int(round(data["col_payroll_totals"][m])))
            tot_row.append(int(round(data["col_cashout_totals"][m])))
        tot_row.append(int(round(data["q_col_payroll_totals"]["Q1"])))
        tot_row.append(int(round(data["q_col_cashout_totals"]["Q1"])))
        for m in data["q2_months"]:
            tot_row.append(int(round(data["col_payroll_totals"][m])))
            tot_row.append(int(round(data["col_cashout_totals"][m])))
        tot_row.append(int(round(data["q_col_payroll_totals"]["Q2"])))
        tot_row.append(int(round(data["q_col_cashout_totals"]["Q2"])))
        for m in data["q3_months"]:
            tot_row.append(int(round(data["col_payroll_totals"][m])))
            tot_row.append(int(round(data["col_cashout_totals"][m])))
        tot_row.append(int(round(data["q_col_payroll_totals"]["Q3"])))
        tot_row.append(int(round(data["q_col_cashout_totals"]["Q3"])))
        for m in data["q4_months"]:
            tot_row.append(int(round(data["col_payroll_totals"][m])))
            tot_row.append(int(round(data["col_cashout_totals"][m])))
        tot_row.append(int(round(data["q_col_payroll_totals"]["Q4"])))
        tot_row.append(int(round(data["q_col_cashout_totals"]["Q4"])))
        tot_row.append(int(round(data["grand_payroll_total"])))
        tot_row.append(int(round(data["grand_cashout_total"])))
        writer.writerow(tot_row)

    csv_bytes = output.getvalue().encode("utf-8-sig")
    fn = f"cashout_{data['fy_name']}.csv"
    handler.send_response(200)
    handler.send_header("Content-Type", "text/csv; charset=utf-8")
    handler.send_header("Content-Length", str(len(csv_bytes)))
    handler.send_header("Content-Disposition", f'attachment; filename="{fn}"')
    handler.end_headers()
    handler.wfile.write(csv_bytes)


page_attendance_cashout = page_attendance_payout
handle_attendance_cashout_export_get = handle_attendance_payout_export_get


def handle_attendance_monthly_save_post(handler):
    length = int(handler.headers.get("Content-Length", 0))
    raw = handler.rfile.read(length).decode("utf-8", errors="ignore")
    import urllib.parse
    form = urllib.parse.parse_qs(raw, keep_blank_values=True)

    month_val = form.get("month", [""])[0].strip()
    vendor_id = form.get("vendor_id", [""])[0].strip()
    contract_id = form.get("contract_id", [""])[0].strip()
    annex_id = form.get("annex_id", [""])[0].strip()
    q = form.get("q", [""])[0].strip()
    
    redirect_url = f"/attendance/monthly?month={month_val}&vendor_id={vendor_id}&contract_id={contract_id}&annex_id={annex_id}&q={q}"

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
        
        # Fetch month start/end to resolve rates
        import calendar
        year_val, month_val_int = map(int, month_val.split("-"))
        month_start_date = f"{year_val:04d}-{month_val_int:02d}-01"
        month_end_date = f"{year_val:04d}-{month_val_int:02d}-{calendar.monthrange(year_val, month_val_int)[1]:02d}"

        # Load staff rates and paid leave balances
        staff_data = {}
        staff_rows = conn.execute("""
            SELECT s.id, s.full_name_vi, l.monthly_rate, l.manday_rate, s.paid_leave_total_hours, s.paid_leave_used_hours
            FROM contract_staff s
            JOIN contract_staff_links l ON l.staff_id = s.id
                AND l.joining_date <= ?
                AND (l.tentative_leaving_date IS NULL OR l.tentative_leaving_date = '' OR l.tentative_leaving_date >= ?)
        """, (month_end_date, month_start_date)).fetchall()
        for s in staff_rows:
            staff_data[s["id"]] = s

        # Perform validation for each updated staff
        for sid, vals in updates.items():
            if sid in locked_staff_ids:
                continue # Skip locked staff member from validation checks
            s = staff_data[sid]
            pl_days = vals.get("pl", 0.0)
            
            # Annual Leave remaining validation (sum other months' paid leave days and exclude current month)
            tot_pl = s["paid_leave_total_hours"] or 0.0
            used_other = conn.execute("""
                SELECT SUM(paid_leave_days) AS total_days 
                FROM monthly_attendance_summary
                WHERE staff_id = ? AND month <> ?
            """, (sid, month_val)).fetchone()
            used_pl_other_days = (used_other["total_days"] or 0.0) if used_other else 0.0
            used_pl_other_hours = used_pl_other_days * 8.0
            
            rem_pl_hours = tot_pl - used_pl_other_hours
            
            pl_hours_input = pl_days * 8.0
            if pl_hours_input > rem_pl_hours:
                rem_days = rem_pl_hours / 8.0
                err_msg = f"Paid leave days ({pl_days:.1f} days) for employee '{s['full_name_vi']}' exceeds remaining balance (only {rem_days:.2f} days remaining)."
                send_html(handler, page_monthly_attendance(
                    {"month": month_val, "vendor_id": vendor_id, "contract_id": contract_id, "annex_id": annex_id, "q": q},
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

            # Recalculate and update total used paid leave hours in contract_staff table across all months
            used_all = cur.execute("""
                SELECT SUM(paid_leave_days) AS total_days 
                FROM monthly_attendance_summary
                WHERE staff_id = ?
            """, (sid,)).fetchone()
            total_used_days = (used_all["total_days"] or 0.0) if used_all else 0.0
            total_used_hours = total_used_days * 8.0
            
            cur.execute("""
                UPDATE contract_staff
                SET paid_leave_used_hours = ?, updated_at = datetime('now')
                WHERE id = ?
            """, (total_used_hours, sid))

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
    annex_id = qs.get("annex_id", [""])[0].strip()
    q = qs.get("q", [""])[0].strip()
    
    redirect_url = f"/attendance/monthly?month={month_val}&vendor_id={vendor_id}&contract_id={contract_id}&annex_id={annex_id}&q={q}"

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
                    {"month": month_val, "vendor_id": parse_int_or_none(vendor_id), "contract_id": parse_int_or_none(contract_id), "annex_id": parse_int_or_none(annex_id), "q": q},
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
    annex_id = qs.get("annex_id", [""])[0].strip()
    q = qs.get("q", [""])[0].strip()
    
    redirect_url = f"/attendance/monthly?month={month_val}&vendor_id={vendor_id}&contract_id={contract_id}&annex_id={annex_id}&q={q}"

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
    
    months = parse_str_list(qs.get("month", []))
    if not months:
        months = [date.today().strftime("%Y-%m")]

    vendor_filters = parse_int_list(qs.get("vendor_id", []))
    contract_filters = parse_int_list(qs.get("contract_id", []))
    annex_filters = parse_int_list(qs.get("annex_id", []))
    q_filter = (qs.get("q", [""])[0] or "").strip()

    all_month_dates = []
    for m_str in months:
        try:
            y, m = int(m_str.split("-")[0]), int(m_str.split("-")[1])
            num_days = calendar.monthrange(y, m)[1]
            all_month_dates.append((m_str, y, m, f"{y:04d}-{m:02d}-01", f"{y:04d}-{m:02d}-{num_days:02d}"))
        except Exception:
            continue

    if not all_month_dates:
        today = date.today()
        m_str = today.strftime("%Y-%m")
        y, m = today.year, today.month
        num_days = calendar.monthrange(y, m)[1]
        all_month_dates.append((m_str, y, m, f"{y:04d}-{m:02d}-01", f"{y:04d}-{m:02d}-{num_days:02d}"))
        months = [m_str]

    min_start = min(d[3] for d in all_month_dates)
    max_end = max(d[4] for d in all_month_dates)

    conn = db_connect()
    try:
        where = ["l.locked = 1"]
        params = []

        m_placeholders = ", ".join(["?"] * len(months))
        where.append(f"l.month IN ({m_placeholders})")
        params.extend(months)

        if vendor_filters:
            v_placeholders = ", ".join(["?"] * len(vendor_filters))
            where.append(f"s.vendor_id IN ({v_placeholders})")
            params.extend(vendor_filters)

        if contract_filters:
            c_placeholders = ", ".join(["?"] * len(contract_filters))
            where.append(f"lnk.contract_id IN ({c_placeholders})")
            params.extend(contract_filters)

        if annex_filters:
            a_placeholders = ", ".join(["?"] * len(annex_filters))
            where.append(f"lnk.annex_id IN ({a_placeholders})")
            params.extend(annex_filters)

        if q_filter:
            where.append("s.full_name_vi LIKE ?")
            params.append(f"%{q_filter}%")

        where_sql = "WHERE " + " AND ".join(where)

        locked_staff = conn.execute(f"""
            SELECT s.id, s.full_name_vi, s.ot, s.work_shift, lnk.monthly_rate, lnk.manday_rate,
                   COALESCE(v.company_name, v.company_name_vi) AS vendor_name,
                   c.framework_no AS contract_no,
                   l.month AS lock_month
            FROM contract_staff s
            JOIN vendors v ON v.id=s.vendor_id
            JOIN contract_staff_links lnk ON lnk.staff_id = s.id
                AND lnk.joining_date <= ?
                AND (lnk.tentative_leaving_date IS NULL OR lnk.tentative_leaving_date = '' OR lnk.tentative_leaving_date >= ?)
            JOIN contracts c ON c.id=lnk.contract_id
            JOIN attendance_locks l ON l.staff_id=s.id
            {where_sql}
            ORDER BY l.month DESC, s.full_name_vi ASC
        """, [max_end, min_start] + params).fetchall()

        summaries = {}
        for s in locked_staff:
            sid = s["id"]
            m_val = s["lock_month"]
            row = conn.execute("""
                SELECT standard_days, actual_days, paid_leave_days, ot_converted_hours, daily_rate, total_amount, locked, manual_work_hours, manual_ot_hours
                FROM monthly_attendance_summary
                WHERE staff_id=? AND month=?
            """, (sid, m_val)).fetchone()
            if row:
                summaries[(sid, m_val)] = dict(row)

        raw_hours_rows = conn.execute("""
            SELECT staff_id, strftime('%Y-%m', date) AS month_str, SUM(work_hours) AS sum_w, SUM(ot_hours) AS sum_ot
            FROM attendance
            WHERE date >= ? AND date <= ?
            GROUP BY staff_id, strftime('%Y-%m', date)
        """, (min_start, max_end)).fetchall()
        raw_hours_map = {(r["staff_id"], r["month_str"]): (r["sum_w"] or 0.0, r["sum_ot"] or 0.0) for r in raw_hours_rows}

    finally:
        conn.close()

    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
    
    writer.writerow([
        "Staff ID", "Full Name", "Vendor", "Contract No", "Month", "Shift", "OT (Yes/No)",
        "Standard Days", "Actual Days", "Paid Leave Days", "Converted OT Hours (x1.5)",
        "Work Hours", "OT Hours", "Daily Rate (VND)", "Work Wage (VND)",
        "OT Wage (VND)", "Total Wage (VND)", "Status"
    ])
    
    for s in locked_staff:
        sid = s["id"]
        m_val = s["lock_month"]
        sum_data = summaries.get((sid, m_val))
        if not sum_data:
            continue
            
        pl = sum_data["paid_leave_days"]
        act = sum_data["actual_days"]
        daily_rate = sum_data["daily_rate"]
        ot_hours = sum_data["ot_converted_hours"]
        total_pay = sum_data["total_amount"]
        is_locked = "Locked" if sum_data["locked"] == 1 else "Unlocked"
        
        raw_w, raw_ot = raw_hours_map.get((sid, m_val), (0.0, 0.0))
        
        manual_w = sum_data.get("manual_work_hours")
        manual_ot = sum_data.get("manual_ot_hours")
        w_hours = manual_w if manual_w is not None else raw_w
        ot_hours_raw = manual_ot if manual_ot is not None else raw_ot

        work_pay = round((act + pl) * daily_rate)
        ot_pay = round(ot_hours * (daily_rate / 8.0))
        
        writer.writerow([
            sid,
            s["full_name_vi"],
            s["vendor_name"],
            s["contract_no"],
            m_val,
            s["work_shift"] or "",
            "Yes" if s["ot"] == 1 else "No",
            f"{sum_data['standard_days']:.1f}",
            f"{act:.2f}",
            f"{pl:.1f}",
            f"{ot_hours:.2f}",
            f"{w_hours:.2f}",
            f"{ot_hours_raw:.2f}",
            f"{int(round(daily_rate))}",
            f"{work_pay}",
            f"{ot_pay}",
            f"{int(round(total_pay))}",
            is_locked
        ])
        
    csv_bytes = output.getvalue().encode("utf-8")
    
    fn_month = "_".join(months[:2]) if len(months) <= 2 else f"{months[0]}_plus_{len(months)-1}_months"
    handler.send_response(200)
    handler.send_header("Content-Type", "text/csv; charset=utf-8")
    handler.send_header("Content-Length", str(len(csv_bytes)))
    handler.send_header("Content-Disposition", f'attachment; filename="Monthly_Payroll_{fn_month}.csv"')
    handler.end_headers()
    handler.wfile.write(csv_bytes)


def page_attendance_timesheet_report(filters: dict) -> str:
    months = parse_str_list(filters.get("month"))
    if not months:
        today = date.today()
        months = [today.strftime("%Y-%m")]
    m_val = months[0]

    try:
        y_val, m_val_int = map(int, m_val.split("-"))
    except Exception:
        today = date.today()
        y_val, m_val_int = today.year, today.month
        m_val = today.strftime("%Y-%m")

    num_days = calendar.monthrange(y_val, m_val_int)[1]
    days = list(range(1, num_days + 1))
    
    dt_month = date(y_val, m_val_int, 1)
    month_title_str = dt_month.strftime("%b-%Y")

    vendor_filters = parse_int_list(filters.get("vendor_id"))
    contract_filters = parse_int_list(filters.get("contract_id"))
    annex_filters = parse_int_list(filters.get("annex_id"))
    q_filter = (filters.get("q") or "").strip()

    month_start_date = f"{y_val:04d}-{m_val_int:02d}-01"
    month_end_date = f"{y_val:04d}-{m_val_int:02d}-{num_days:02d}"

    conn = db_connect()
    try:
        # Load matching annexes
        annex_sql = """
            SELECT a.id AS annex_id, a.annex_name, c.id AS contract_id, c.framework_no, c.framework_name,
                   v.id AS vendor_id, v.company_name, v.company_name_vi,
                   v.tax_id, v.address, v.address_vi, v.tel, v.account_name
            FROM contract_annexes a
            JOIN contracts c ON c.id = a.contract_id
            JOIN vendors v ON v.id = c.seller_vendor_id
            WHERE a.is_active = 1 AND a.deleted_at IS NULL
        """
        params = []
        if annex_filters:
            ph = ", ".join(["?"] * len(annex_filters))
            annex_sql += f" AND a.id IN ({ph})"
            params.extend(annex_filters)
        if contract_filters:
            ph = ", ".join(["?"] * len(contract_filters))
            annex_sql += f" AND c.id IN ({ph})"
            params.extend(contract_filters)
        if vendor_filters:
            ph = ", ".join(["?"] * len(vendor_filters))
            annex_sql += f" AND v.id IN ({ph})"
            params.extend(vendor_filters)

        annex_sql += " ORDER BY COALESCE(v.company_name, v.company_name_vi), c.framework_no, a.annex_name"
        target_annexes = conn.execute(annex_sql, params).fetchall()

        if not target_annexes:
            # Fallback if no annex filter matched
            target_annexes = conn.execute("""
                SELECT a.id AS annex_id, a.annex_name, c.id AS contract_id, c.framework_no, c.framework_name,
                       v.id AS vendor_id, v.company_name, v.company_name_vi,
                       v.tax_id, v.address, v.address_vi, v.tel, v.account_name
                FROM contract_annexes a
                JOIN contracts c ON c.id = a.contract_id
                JOIN vendors v ON v.id = c.seller_vendor_id
                WHERE a.is_active = 1 AND a.deleted_at IS NULL
                ORDER BY COALESCE(v.company_name, v.company_name_vi), c.framework_no, a.annex_name LIMIT 1
            """).fetchall()

        annex_pages_html = []
        unlocked_annexes = []

        for annex_row in target_annexes:
            aid = annex_row["annex_id"]
            v_name = annex_row["company_name"] or annex_row["company_name_vi"] or "Vendor Company"
            v_tax = annex_row["tax_id"] or "N/A"
            v_addr = annex_row["address"] or annex_row["address_vi"] or "N/A"
            v_tel = annex_row["tel"] or "N/A"
            f_no = annex_row["framework_no"] or ""
            a_name = annex_row["annex_name"] or ""

            # Fetch staff for this Annex who have attendance records for this month
            staff_rows = conn.execute("""
                SELECT DISTINCT s.id, s.full_name_vi, s.position, s.ot,
                       lnk.monthly_rate, lnk.manday_rate
                FROM contract_staff s
                JOIN contract_staff_links lnk ON lnk.staff_id = s.id
                WHERE lnk.annex_id = ?
                  AND lnk.joining_date <= ?
                  AND (lnk.tentative_leaving_date IS NULL OR lnk.tentative_leaving_date = '' OR lnk.tentative_leaving_date >= ?)
                  AND (
                      EXISTS (SELECT 1 FROM attendance att WHERE att.staff_id = s.id AND strftime('%Y-%m', att.date) = ?)
                      OR EXISTS (SELECT 1 FROM monthly_attendance_summary mas WHERE mas.staff_id = s.id AND mas.month = ?)
                  )
                ORDER BY s.full_name_vi ASC
            """, (aid, month_end_date, month_start_date, m_val, m_val)).fetchall()

            if not staff_rows:
                # Fallback to any staff assigned to this Annex with attendance in target month
                staff_rows = conn.execute("""
                    SELECT DISTINCT s.id, s.full_name_vi, s.position, s.ot,
                           lnk.monthly_rate, lnk.manday_rate
                    FROM contract_staff s
                    JOIN contract_staff_links lnk ON lnk.staff_id = s.id
                    WHERE lnk.annex_id = ?
                      AND (
                          EXISTS (SELECT 1 FROM attendance att WHERE att.staff_id = s.id AND strftime('%Y-%m', att.date) = ?)
                          OR EXISTS (SELECT 1 FROM monthly_attendance_summary mas WHERE mas.staff_id = s.id AND mas.month = ?)
                      )
                    ORDER BY s.full_name_vi ASC
                """, (aid, m_val, m_val)).fetchall()

            staff_ids = [s["id"] for s in staff_rows]

            # Fetch ALL active staff linked to this annex via contract during target month
            all_linked_rows = conn.execute("""
                SELECT DISTINCT s.id
                FROM contract_staff_links l
                JOIN contract_staff s ON s.id = l.staff_id
                WHERE l.annex_id = ?
                  AND (l.joining_date IS NULL OR l.joining_date = '' OR l.joining_date <= ?)
                  AND (l.tentative_leaving_date IS NULL OR l.tentative_leaving_date = '' OR l.tentative_leaving_date >= ?)
            """, (aid, month_end_date, month_start_date)).fetchall()
            all_linked_ids = [r["id"] for r in all_linked_rows]

            daily_lock_map = {}
            monthly_lock_map = {}
            daily_lock_time = ""
            if all_linked_ids:
                s_ph = ", ".join(["?"] * len(all_linked_ids))
                d_rows = conn.execute(f"""
                    SELECT staff_id, locked_at FROM attendance_locks
                    WHERE month = ? AND staff_id IN ({s_ph}) AND locked = 1
                """, [m_val] + all_linked_ids).fetchall()
                daily_lock_map = {r["staff_id"]: True for r in d_rows}
                lock_times = [r["locked_at"] for r in d_rows if r["locked_at"]]
                if lock_times:
                    daily_lock_time = max(lock_times)

                m_rows = conn.execute(f"""
                    SELECT staff_id FROM monthly_attendance_summary
                    WHERE month = ? AND staff_id IN ({s_ph}) AND locked = 1
                """, [m_val] + all_linked_ids).fetchall()
                monthly_lock_map = {r["staff_id"]: True for r in m_rows}

            is_fully_locked = (
                len(all_linked_ids) > 0 and
                all(daily_lock_map.get(sid, False) and monthly_lock_map.get(sid, False) for sid in all_linked_ids)
            )

            if not is_fully_locked:
                unlocked_annexes.append(f"{v_name} - {a_name}")
                if len(target_annexes) == 1:
                    return f"""<!DOCTYPE html>
                    <html>
                    <head>
                      <meta charset="utf-8">
                      <title>Cannot Export BBNT - Attendance & Payroll Not Locked</title>
                      <style>
                        body {{ font-family: sans-serif; background: #f8fafc; padding: 40px; margin: 0; }}
                        .card {{ max-width: 680px; margin: 0 auto; background: #fff; border-radius: 12px; padding: 24px; border-left: 6px solid #b00020; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }}
                      </style>
                    </head>
                    <body>
                      <div class="card">
                        <h2 style="color:#b00020; margin-top:0;">⚠️ Cannot Export Attendance Acceptance Report (PDF)</h2>
                        <p style="font-size:15px; color:#334155; line-height:1.6;">
                          Daily Attendance and Monthly Payroll for month <b>{month_title_str}</b> of <b>{escape(v_name)} - {escape(a_name)}</b> have not been fully <b>Locked</b>.
                          <br><br>
                          Requirement: Both Daily Attendance and Monthly Payroll must be locked before exporting BBNT PDF.
                        </p>
                        <a href="/attendance/acceptance?month={m_val}" style="display:inline-block; margin-top:12px; background:#0b57d0; color:#fff; padding:10px 20px; border-radius:6px; font-weight:bold; text-decoration:none;">← Back to Attendance Acceptance Page</a>
                      </div>
                    </body>
                    </html>"""
                continue

            att_map = {}
            summary_map = {}
            if staff_ids:
                s_placeholders = ", ".join(["?"] * len(staff_ids))
                att_rows = conn.execute(f"""
                    SELECT staff_id, strftime('%d', date) AS day_num, work_hours, ot_hours
                    FROM attendance
                    WHERE staff_id IN ({s_placeholders}) AND strftime('%Y-%m', date) = ?
                """, staff_ids + [m_val]).fetchall()
                for r in att_rows:
                    d_int = int(r["day_num"])
                    att_map[(r["staff_id"], d_int)] = {
                        "work_hours": r["work_hours"] or 0.0,
                        "ot_hours": r["ot_hours"] or 0.0
                    }

                sum_rows = conn.execute(f"""
                    SELECT staff_id, standard_days, actual_days, paid_leave_days, ot_converted_hours, daily_rate, total_amount
                    FROM monthly_attendance_summary
                    WHERE staff_id IN ({s_placeholders}) AND month = ?
                """, staff_ids + [m_val]).fetchall()
                for r in sum_rows:
                    summary_map[r["staff_id"]] = dict(r)

            std_days_in_m = get_standard_working_days(y_val, m_val_int)
            avg_monthly_rate = 65000000.0
            if staff_rows and staff_rows[0]["monthly_rate"]:
                avg_monthly_rate = staff_rows[0]["monthly_rate"]

            th_days_html = ""
            th_wday_html = ""
            for d in days:
                dt = date(y_val, m_val_int, d)
                w_name = dt.strftime("%a")
                is_wknd = dt.weekday() >= 5
                bg_style = "background-color:#94a3b8; color:#fff;" if is_wknd else ""
                th_wday_html += f'<th style="border:1px solid #000; padding:1px; width:20px; font-size:7pt; text-align:center; {bg_style}">{w_name}</th>'
                th_days_html += f'<th style="border:1px solid #000; padding:1px; width:20px; font-size:7pt; text-align:center; {bg_style}">{d:02d}</th>'

            sec1_trs = []
            sec1_tot_normal_hours = 0.0
            for idx, s in enumerate(staff_rows, 1):
                sid = s["id"]
                code_lbl = f"M{idx:02d}"
                tds = []
                row_tot_hours = 0.0
                for d in days:
                    dt = date(y_val, m_val_int, d)
                    if (sid, d) in att_map:
                        wh = att_map[(sid, d)]["work_hours"]
                    else:
                        staff_has_att = any((sid, day) in att_map for day in days)
                        wh = 8.0 if (not staff_has_att and not is_wknd) else 0.0
                    bg_style = "background-color:#cbd5e1;" if is_wknd else ""
                    val_lbl = f"{wh:.2f}" if wh > 0 else ""
                    if not is_wknd:
                        row_tot_hours += wh
                    tds.append(f'<td style="border:1px solid #000; padding:1px; text-align:center; font-size:7pt; {bg_style}">{val_lbl}</td>')

                sec1_tot_normal_hours += row_tot_hours
                leave_info = ""
                s_sum = summary_map.get(sid, {})
                if s_sum.get("paid_leave_days", 0) > 0:
                    leave_info = f"Annual leave: {s_sum['paid_leave_days'] * 8:.0f}h"

                sec1_trs.append(f"""
                <tr>
                  <td style="border:1px solid #000; padding:2px; text-align:center;">{idx}</td>
                  <td style="border:1px solid #000; padding:2px; text-align:center;">{code_lbl}</td>
                  <td style="border:1px solid #000; padding:2px; white-space:nowrap;">{escape(s['full_name_vi'])}</td>
                  {''.join(tds)}
                  <td style="border:1px solid #000; padding:2px; text-align:right; font-weight:bold;">{row_tot_hours:.2f}</td>
                  <td style="border:1px solid #000; padding:2px; font-size:7pt;">{escape(leave_info)}</td>
                </tr>
                """)

            sec2_trs = []
            sec2_tot_reg_ot = 0.0
            sec2_tot_wknd_ot = 0.0
            sec2_tot_hol_ot = 0.0
            for idx, s in enumerate(staff_rows, 1):
                sid = s["id"]
                code_lbl = f"M{idx:02d}"
                tds = []
                row_reg_ot = 0.0
                row_wknd_ot = 0.0
                row_hol_ot = 0.0
                for d in days:
                    dt = date(y_val, m_val_int, d)
                    is_wknd = dt.weekday() >= 5
                    att = att_map.get((sid, d), {})
                    oth = att.get("ot_hours", 0.0)
                    bg_style = "background-color:#cbd5e1;" if is_wknd else ""
                    val_lbl = f"{oth:.2f}" if oth > 0 else ""
                    if oth > 0:
                        if is_wknd:
                            row_wknd_ot += oth
                        else:
                            row_reg_ot += oth
                    tds.append(f'<td style="border:1px solid #000; padding:1px; text-align:center; font-size:7pt; {bg_style}">{val_lbl}</td>')

                sec2_tot_reg_ot += row_reg_ot
                sec2_tot_wknd_ot += row_wknd_ot
                sec2_tot_hol_ot += row_hol_ot

                sec2_trs.append(f"""
                <tr>
                  <td style="border:1px solid #000; padding:2px; text-align:center;">{idx}</td>
                  <td style="border:1px solid #000; padding:2px; text-align:center;">{code_lbl}</td>
                  <td style="border:1px solid #000; padding:2px; white-space:nowrap;">{escape(s['full_name_vi'])}</td>
                  {''.join(tds)}
                  <td style="border:1px solid #000; padding:2px; text-align:right;">{row_reg_ot:.2f}</td>
                  <td style="border:1px solid #000; padding:2px; text-align:right;">{row_wknd_ot:.2f}</td>
                  <td style="border:1px solid #000; padding:2px; text-align:right;">{row_hol_ot:.2f}</td>
                </tr>
                """)

            sec3_trs = []
            sec3_tot_norm_pay = 0.0
            sec3_tot_reg_ot_pay = 0.0
            sec3_tot_wknd_ot_pay = 0.0
            sec3_tot_hol_ot_pay = 0.0
            sec3_tot_all_pay = 0.0

            for idx, s in enumerate(staff_rows, 1):
                sid = s["id"]
                code_lbl = f"M{idx:02d}"
                s_sum = summary_map.get(sid, {})
                d_rate = s_sum.get("daily_rate", avg_monthly_rate / std_days_in_m if std_days_in_m > 0 else 0.0)
                h_rate = d_rate / 8.0

                std_days = s_sum.get("standard_days", std_days_in_m)
                act_days = s_sum.get("actual_days", std_days_in_m)
                pl_days = s_sum.get("paid_leave_days", 0.0)
                norm_pay = round((act_days + pl_days) * d_rate)

                m_rate_val = s["monthly_rate"] if "monthly_rate" in s.keys() else None
                d_rate_val = s["manday_rate"] if "manday_rate" in s.keys() else None
                if m_rate_val is not None and m_rate_val > 0:
                    unit_rate_val = m_rate_val
                elif d_rate_val is not None and d_rate_val > 0:
                    unit_rate_val = d_rate_val
                else:
                    unit_rate_val = d_rate

                reg_ot_h = 0.0
                wknd_ot_h = 0.0
                for d in days:
                    dt = date(y_val, m_val_int, d)
                    att = att_map.get((sid, d), {})
                    oth = att.get("ot_hours", 0.0)
                    if oth > 0:
                        if dt.weekday() >= 5:
                            wknd_ot_h += oth
                        else:
                            reg_ot_h += oth

                if s_sum and s_sum.get("ot_converted_hours") is not None and wknd_ot_h == 0:
                    reg_ot_pay = round(s_sum["ot_converted_hours"] * h_rate)
                else:
                    reg_ot_pay = round(reg_ot_h * h_rate * 1.5)
                wknd_ot_pay = round(wknd_ot_h * h_rate * 2.0)
                hol_ot_pay = 0.0
                calc_total = norm_pay + reg_ot_pay + wknd_ot_pay + hol_ot_pay
                total_pay = s_sum.get("total_amount") if (s_sum and s_sum.get("total_amount") is not None) else calc_total

                sec3_tot_norm_pay += norm_pay
                sec3_tot_reg_ot_pay += reg_ot_pay
                sec3_tot_wknd_ot_pay += wknd_ot_pay
                sec3_tot_hol_ot_pay += hol_ot_pay
                sec3_tot_all_pay += total_pay

                sec3_trs.append(f"""
                <tr>
                  <td style="border:1px solid #000; padding:3px; text-align:center;">{idx}</td>
                  <td style="border:1px solid #000; padding:3px; text-align:center;">{code_lbl}</td>
                  <td style="border:1px solid #000; padding:3px; white-space:nowrap;">{escape(s['full_name_vi'])}</td>
                  <td style="border:1px solid #000; padding:3px; text-align:right; font-family:monospace;">{std_days:.1f}</td>
                  <td style="border:1px solid #000; padding:3px; text-align:right; font-family:monospace;">{act_days:.1f}</td>
                  <td style="border:1px solid #000; padding:3px; text-align:right; font-family:monospace;">{pl_days:.1f}</td>
                  <td style="border:1px solid #000; padding:3px; text-align:right; font-family:monospace;">{unit_rate_val:,.0f}</td>
                  <td style="border:1px solid #000; padding:3px; text-align:right; font-family:monospace;">{reg_ot_pay:,.0f}</td>
                  <td style="border:1px solid #000; padding:3px; text-align:right; font-family:monospace;">{wknd_ot_pay:,.0f}</td>
                  <td style="border:1px solid #000; padding:3px; text-align:right; font-family:monospace;">{hol_ot_pay:,.0f}</td>
                  <td style="border:1px solid #000; padding:3px; text-align:right; font-family:monospace; font-weight:bold;">{total_pay:,.0f}</td>
                </tr>
                """)

            is_manday_annex = any((("manday_rate" in s.keys()) and s["manday_rate"] is not None and s["manday_rate"] > 0) for s in staff_rows)
            sec3_rate_header_lbl = "Unit Rate (Man-day)" if is_manday_annex else "Unit Rate (Man-month)"

            annex_pages_html.append(f"""
            <div class="annex-page-break" style="page-break-after: always; break-after: page; max-width: 1100px; margin: 0 auto 30px auto; background: #fff;">
              <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
                <div>
                  <div style="font-weight: bold; font-size: 11pt; text-transform: uppercase;">{escape(v_name)}</div>
                  <div style="font-size: 7.5pt; color: #333;">Tax Code: {escape(v_tax)}</div>
                  <div style="font-size: 7.5pt; color: #333;">Address: {escape(v_addr)} | Tel: {escape(v_tel)}</div>
                </div>
                <div style="text-align: right;">
                  <div style="font-weight: bold; font-size: 11pt;">MINUTES OF SERVICE ACCEPTANCE</div>
                  <div style="font-size: 8pt; font-weight: bold; margin-top: 2px;">Period: {month_title_str}</div>
                  <div style="font-size: 7.5pt; color: #333;">Framework No: {escape(f_no)} | Annex: {escape(a_name)}</div>
                </div>
              </div>

              <div style="border-bottom: 1px solid #000; margin-bottom: 10px;"></div>

              <div style="margin-bottom: 16px;">
                <div style="font-weight: bold; font-size: 9pt; margin-bottom: 4px;">1. Normal working hour report</div>
                <table style="font-size: 7.5pt;">
                  <thead>
                    <tr style="background: #f8fafc;">
                      <th style="width: 20px; padding: 2px;">No.</th>
                      <th style="width: 35px; padding: 2px;">Code</th>
                      <th style="width: 120px; padding: 2px; text-align: left;">Full Name</th>
                      {th_wday_html}
                      <th style="width: 45px; padding: 2px;">Total</th>
                      <th style="width: 120px; padding: 2px; text-align: left;">Annual leave</th>
                    </tr>
                    <tr style="background: #f8fafc;">
                      <th colspan="3" style="padding: 1px;">Date</th>
                      {th_days_html}
                      <th colspan="2" style="padding: 1px;"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {''.join(sec1_trs) if sec1_trs else '<tr><td colspan="37" style="text-align:center; padding:10px;">No staff records for this Annex.</td></tr>'}
                  </tbody>
                </table>
              </div>

              <div style="margin-bottom: 16px;">
                <div style="font-weight: bold; font-size: 9pt; margin-bottom: 4px;">2. Overtime working hour report</div>
                <table style="font-size: 7.5pt;">
                  <thead>
                    <tr style="background: #f8fafc;">
                      <th style="width: 20px; padding: 2px;" rowspan="2">No.</th>
                      <th style="width: 35px; padding: 2px;" rowspan="2">Code</th>
                      <th style="width: 120px; padding: 2px; text-align: left;" rowspan="2">Full Name</th>
                      {th_wday_html}
                      <th colspan="3" style="padding: 2px; text-align: center;">Total Overtime (Hours)</th>
                    </tr>
                    <tr style="background: #f8fafc;">
                      {th_days_html}
                      <th style="width: 35px; padding: 1px;">Regular</th>
                      <th style="width: 35px; padding: 1px;">Weekend</th>
                      <th style="width: 35px; padding: 1px;">Holiday</th>
                    </tr>
                  </thead>
                  <tbody>
                    {''.join(sec2_trs) if sec2_trs else '<tr><td colspan="38" style="text-align:center; padding:10px;">No overtime records for this Annex.</td></tr>'}
                  </tbody>
                </table>
              </div>

              <div style="margin-bottom: 20px;">
                <div style="font-weight: bold; font-size: 9pt; margin-bottom: 4px;">3. Service Fee calculation</div>
                <table style="font-size: 7.5pt;">
                  <thead>
                    <tr style="background: #f8fafc;">
                      <th style="width: 20px; padding: 3px;" rowspan="2">No.</th>
                      <th style="width: 35px; padding: 3px;" rowspan="2">Code</th>
                      <th style="width: 140px; padding: 3px; text-align: left;" rowspan="2">Full Name</th>
                      <th style="padding: 3px; text-align: right;" rowspan="2">Standard Days</th>
                      <th style="padding: 3px; text-align: right;" rowspan="2">Actual Days</th>
                      <th style="padding: 3px; text-align: right;" rowspan="2">Paid Leave</th>
                      <th style="padding: 3px; text-align: right;" rowspan="2">{sec3_rate_header_lbl}</th>
                      <th colspan="3" style="padding: 3px; text-align: center;">Overtime Pay</th>
                      <th style="padding: 3px; text-align: right;" rowspan="2">Total Amount (VND)</th>
                    </tr>
                    <tr style="background: #f8fafc;">
                      <th style="padding: 2px; text-align: right;">Regular Day (150%)</th>
                      <th style="padding: 2px; text-align: right;">Weekend Day (200%)</th>
                      <th style="padding: 2px; text-align: right;">Public Holiday (300%)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {''.join(sec3_trs) if sec3_trs else '<tr><td colspan="11" style="text-align:center; padding:10px;">No calculation records.</td></tr>'}
                  </tbody>
                  <tfoot>
                    <tr style="font-weight: bold; background: #f8fafc;">
                      <td colspan="10" style="border:1px solid #000; padding:3px; text-align:right;">Total Amount (VND):</td>
                      <td style="border:1px solid #000; padding:3px; text-align:right; font-family:monospace; color:#0b57d0;">{sec3_tot_all_pay:,.0f}</td>
                    </tr>
                  </tfoot>
                </table>
              </div>

              <div style="display: flex; justify-content: flex-start; margin-top: 24px; font-size: 8.5pt; text-align: center;">
                <div>
                  <div style="font-weight: bold; text-transform: uppercase;">MIZUHO BANK, LTD. HANOI BRANCH</div>
                  <div style="height: 75px;"></div>
                  <div style="font-weight: bold; border-top: 1px solid #000; width: 180px; margin: 0 auto; padding-top: 4px;">Authorized Signature</div>
                </div>
              </div>
            </div>
            """)

    finally:
        conn.close()

    if not annex_pages_html:
        return f"""<!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <title>Cannot Export BBNT</title>
          <style>body {{ font-family: sans-serif; background: #f8fafc; padding: 40px; }} .card {{ max-width: 600px; margin: 0 auto; background: #fff; padding: 24px; border-radius: 12px; border-left: 6px solid #b00020; }}</style>
        </head>
        <body>
          <div class="card">
            <h2 style="color:#b00020; margin-top:0;">⚠️ Cannot Export BBNT Report</h2>
            <p>No annexes with locked attendance match the filter for exporting BBNT report.</p>
            <a href="/attendance/acceptance?month={m_val}" style="display:inline-block; background:#0b57d0; color:#fff; padding:8px 16px; border-radius:6px; text-decoration:none; font-weight:bold;">← Back to Acceptance Page</a>
          </div>
        </body>
        </html>"""

    filter_qs = build_filter_qs(months, vendor_filters, contract_filters, annex_filters, q_filter)

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Timesheet BBNT Report - {month_title_str}</title>
  <style>
    @page {{
      size: A4 landscape;
      margin: 6mm 8mm;
    }}
    body {{
      font-family: 'Times New Roman', Times, serif;
      color: #000;
      background: #fff;
      margin: 0;
      padding: 10px;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    table {{
      border-collapse: collapse;
      width: 100%;
    }}
    th, td {{
      border: 1px solid #000;
      font-size: 8pt;
    }}
    .no-print {{
      display: flex;
      gap: 12px;
      align-items: center;
      justify-content: space-between;
      background: #f8fafc;
      padding: 12px 20px;
      border-bottom: 1px solid #cbd5e1;
      margin-bottom: 16px;
    }}
    @media print {{
      .no-print {{
        display: none !important;
      }}
      body {{
        padding: 0;
      }}
      .annex-page-break {{
        page-break-after: always;
        break-after: page;
      }}
    }}
  </style>
</head>
<body>

  <div class="no-print">
    <div style="display:flex; align-items:center; gap:12px;">
      <a href="/attendance/acceptance?{filter_qs}" style="text-decoration:none; color:#0b57d0; font-weight:bold; font-size:13px;">← Back to Attendance Acceptance Page</a>
      <h2 style="margin:0; font-size:16px; font-family:sans-serif;">Attendance Acceptance BBNT Report (A4 Landscape - {month_title_str})</h2>
    </div>
    <div style="display:flex; gap:10px;">
      <button onclick="window.print()" style="padding:8px 16px; background:#0b57d0; color:#fff; border:none; border-radius:6px; font-weight:bold; cursor:pointer;">🖨️ Print / Save PDF (A4 Landscape)</button>
    </div>
  </div>

  <div id="report-container">
    {''.join(annex_pages_html)}
  </div>

</body>
</html>"""
