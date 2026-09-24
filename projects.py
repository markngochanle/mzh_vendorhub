# projects.py
import calendar
import csv
import io
import urllib.parse
from html import escape
from datetime import datetime

from common import (
    db_connect, layout, read_post_form, redirect, send_html, now_iso, log_action, fmt_money
)

def page_projects_list(error_msg: str | None = None, success_msg: str | None = None):
    conn = db_connect()
    try:
        projects = conn.execute("""
            SELECT * FROM projects 
            ORDER BY is_active DESC, short_name ASC, id DESC
        """).fetchall()
    finally:
        conn.close()

    error_html = f'<div class="card danger"><b>Error:</b> {escape(error_msg)}</div>' if error_msg else ""
    success_html = f'<div class="card success"><b>Success:</b> {escape(success_msg)}</div>' if success_msg else ""

    body = f"""
    {error_html}
    {success_html}

    <div class="card" style="margin-bottom: 24px;">
      <h3 style="margin-top: 0; margin-bottom: 16px;">Add New Project</h3>
      <form method="POST" action="/project/create">
        <div class="grid">
          <div>
            <div class="label">Short Name (required)</div>
            <input type="text" name="short_name" placeholder="e.g. MZH-Hub" style="width: 100%;" required>
          </div>
          <div>
            <div class="label">Full Name (required)</div>
            <input type="text" name="full_name" placeholder="e.g. Mizuho Vendor Hub System" style="width: 100%;" required>
          </div>
          <div>
            <div class="label">IT Outsourcing Budget</div>
            <input type="number" step="0.01" name="it_outsourcing_budget" placeholder="e.g. 50000.00" style="width: 100%;">
          </div>
          <div>
            <div class="label">OS Start Date</div>
            <input type="date" name="os_start_date" style="width: 100%;">
          </div>
          <div>
            <div class="label">OS End Date</div>
            <input type="date" name="os_end_date" style="width: 100%;">
          </div>
        </div>
        <div class="actions" style="margin-top: 20px;">
          <button type="submit" class="btn-primary">Create Project</button>
        </div>
      </form>
    </div>

    <div class="card">
      <h3 style="margin-top: 0; margin-bottom: 16px;">Projects List</h3>
      <table>
        <thead>
          <tr>
            <th>No.</th>
            <th>Short Name</th>
            <th>Full Name</th>
            <th>IT Outsourcing Budget</th>
            <th>OS Start Date</th>
            <th>OS End Date</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
    """

    if not projects:
      body += """
          <tr>
            <td colspan="8" style="text-align: center; color: var(--text-muted);">No projects found.</td>
          </tr>
      """
    else:
      for idx, p in enumerate(projects, 1):
          budget_str = f"{float(p['it_outsourcing_budget']):,.2f} VND" if p['it_outsourcing_budget'] is not None else "N/A"
          is_active = int(p['is_active'] or 0) == 1
          
          if is_active:
              status_badge = '<div class="tag" style="background:#e6f4ea; border-color:#b4e3be; color:#137333; margin:0;">Active</div>'
              action_btn = f"""
              <form method="POST" action="/project/delete" class="inline" onsubmit="return confirm('Are you sure you want to close project: {escape(p['short_name'])}?');" style="margin:0; display:inline-block;">
                <input type="hidden" name="id" value="{p['id']}">
                <button type="submit" class="btn-danger" style="font-size:12px; padding: 4px 8px; background:#f59e0b; border-color:#d97706;">Close</button>
              </form>
              """
          else:
              status_badge = '<div class="tag" style="background:#f1f5f9; border-color:#cbd5e1; color:#475569; margin:0;">Closed</div>'
              action_btn = f"""
              <form method="POST" action="/project/restore" class="inline" onsubmit="return confirm('Are you sure you want to reopen project: {escape(p['short_name'])}?');" style="margin:0; display:inline-block;">
                <input type="hidden" name="id" value="{p['id']}">
                <button type="submit" class="btn-primary" style="font-size:12px; padding: 4px 8px; background:#10b981; border-color:#059669;">Reopen</button>
              </form>
              """
              
          body += f"""
          <tr>
            <td>{idx}</td>
            <td style="font-weight: 600;"><a href="/projects/assign?project_id={p['id']}" style="color: var(--primary); font-weight: bold; text-decoration: underline;">{escape(p['short_name'] or '')}</a></td>
            <td>{escape(p['full_name'] or '')}</td>
            <td>{escape(budget_str)}</td>
            <td>{escape(p['os_start_date'] or 'N/A')}</td>
            <td>{escape(p['os_end_date'] or 'N/A')}</td>
            <td>{status_badge}</td>
            <td>
              {action_btn}
              <a href="/project/edit?id={p['id']}" class="btn" style="font-size:12px; padding: 4px 8px; margin-left: 4px; background:#4f46e5; border-color:#4f46e5; color:#fff;">Edit</a>
              <a href="/projects/assign?project_id={p['id']}" class="btn" style="font-size:12px; padding: 4px 8px; margin-left: 4px;">Assignments</a>
            </td>
          </tr>
          """

    body += """
        </tbody>
      </table>
    </div>
    """

    return layout("Projects Management", body)

def handle_project_create_post(handler):
    from urllib.parse import urlparse, parse_qs
    parsed_path = urlparse(handler.path)
    query_params = parse_qs(parsed_path.query)
    redirect_to = query_params.get("redirect_to", [None])[0]

    form = read_post_form(handler)
    short_name = (form.get("short_name", [""])[0] or "").strip()
    full_name = (form.get("full_name", [""])[0] or "").strip()
    it_outsourcing_budget_raw = (form.get("it_outsourcing_budget", [""])[0] or "").strip()
    os_start_date = (form.get("os_start_date", [""])[0] or "").strip() or None
    os_end_date = (form.get("os_end_date", [""])[0] or "").strip() or None

    if not short_name or not full_name:
        if redirect_to:
            send_html(handler, page_projects_assign(error_msg="Short Name and Full Name are required."), status=400)
        else:
            send_html(handler, page_projects_list(error_msg="Short Name and Full Name are required."), status=400)
        return

    it_outsourcing_budget = None
    if it_outsourcing_budget_raw:
        try:
            it_outsourcing_budget = float(it_outsourcing_budget_raw)
        except ValueError:
            if redirect_to:
                send_html(handler, page_projects_assign(error_msg="IT Outsourcing Budget must be a number."), status=400)
            else:
                send_html(handler, page_projects_list(error_msg="IT Outsourcing Budget must be a number."), status=400)
            return

    conn = db_connect()
    new_project_id = None
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO projects (short_name, full_name, it_outsourcing_budget, os_start_date, os_end_date, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)
        """, (short_name, full_name, it_outsourcing_budget, os_start_date, os_end_date, now_iso(), now_iso()))
        new_project_id = cur.lastrowid
        log_action(cur, "CREATE_PROJECT", "projects", new_project_id, f"Created new project '{short_name}' - {full_name}")
        conn.commit()
    finally:
        conn.close()

    if redirect_to:
        connector = "&" if "?" in redirect_to else "?"
        if new_project_id:
            redirect(handler, f"{redirect_to}{connector}project_id={new_project_id}&success_msg=Project created successfully.")
        else:
            redirect(handler, f"{redirect_to}{connector}success_msg=Project created successfully.")
    else:
        redirect(handler, "/projects")

def handle_project_delete_post(handler):
    form = read_post_form(handler)
    project_id_raw = (form.get("id", [""])[0] or "").strip()

    if not project_id_raw.isdigit():
        send_html(handler, page_projects_list(error_msg="Invalid Project ID."), status=400)
        return

    project_id = int(project_id_raw)

    conn = db_connect()
    try:
        # Get project name first for log
        p_row = conn.execute("SELECT short_name FROM projects WHERE id=?", (project_id,)).fetchone()
        p_name = p_row["short_name"] if p_row else f"ID {project_id}"
        
        cur = conn.cursor()
        cur.execute("UPDATE projects SET is_active = 0, updated_at = ? WHERE id = ?", (now_iso(), project_id))
        log_action(cur, "CLOSE_PROJECT", "projects", project_id, f"Closed project '{p_name}'")
        conn.commit()
    finally:
        conn.close()

    redirect(handler, "/projects")


def handle_project_restore_post(handler):
    form = read_post_form(handler)
    project_id_raw = (form.get("id", [""])[0] or "").strip()

    if not project_id_raw.isdigit():
        send_html(handler, page_projects_list(error_msg="Invalid Project ID."), status=400)
        return

    project_id = int(project_id_raw)

    conn = db_connect()
    try:
        # Get project name first for log
        p_row = conn.execute("SELECT short_name FROM projects WHERE id=?", (project_id,)).fetchone()
        p_name = p_row["short_name"] if p_row else f"ID {project_id}"
        
        cur = conn.cursor()
        cur.execute("UPDATE projects SET is_active = 1, updated_at = ? WHERE id = ?", (now_iso(), project_id))
        log_action(cur, "REOPEN_PROJECT", "projects", project_id, f"Reopened project '{p_name}'")
        conn.commit()
    finally:
        conn.close()

    redirect(handler, "/projects")


def page_projects_assign(selected_month: str | None = None, selected_project_id: str | None = None, selected_vendor_id: str | None = None, error_msg: str | None = None, success_msg: str | None = None):
    js_staff_avail = "{}"
    # Default to current month if not specified
    if not selected_month:
        selected_month = datetime.now().strftime("%Y-%m")

    conn = db_connect()
    try:
        # 1. Get projects (active first, then closed)
        projects_list = conn.execute("SELECT * FROM projects ORDER BY is_active DESC, short_name ASC").fetchall()
        
        # 2. Get active vendor sellers (purchasing=0) for filtering
        vendors = conn.execute("""
            SELECT id, company_name, company_name_vi 
            FROM vendors 
            WHERE is_active=1 AND purchasing=0 
            ORDER BY company_name ASC, company_name_vi ASC
        """).fetchall()

        # Check if project_id is valid (including closed projects for historical assignments management)
        project_row = None
        if selected_project_id and str(selected_project_id).isdigit():
            project_row = conn.execute("SELECT * FROM projects WHERE id=?", (int(selected_project_id),)).fetchone()

        # Determine months, staffs and assignments for the selected project
        months = []
        staffs = []
        assignments_map = {}
        available_staffs = []

        if project_row:
            start_date_str = project_row["os_start_date"]
            end_date_str = project_row["os_end_date"]
            if start_date_str and end_date_str:
                try:
                    start = datetime.strptime(start_date_str.strip(), "%Y-%m-%d")
                    end = datetime.strptime(end_date_str.strip(), "%Y-%m-%d")
                    
                    current = datetime(start.year, start.month, 1)
                    limit = datetime(end.year, end.month, 1)
                    
                    while current <= limit:
                        months.append(current.strftime("%Y-%m"))
                        if current.month == 12:
                            current = datetime(current.year + 1, 1, 1)
                        else:
                            current = datetime(current.year, current.month + 1, 1)
                except Exception:
                    pass

            if not months:
                # Default fallback: current month and 5 months ahead
                now = datetime.now()
                current = datetime(now.year, now.month, 1)
                for _ in range(6):
                    months.append(current.strftime("%Y-%m"))
                    if current.month == 12:
                        current = datetime(current.year + 1, 1, 1)
                    else:
                        current = datetime(current.year, current.month + 1, 1)

            # Get staffs that are already assigned to this project in any month
            staff_params = [project_row["id"]]
            staff_where = [
                "cs.id IN (SELECT DISTINCT staff_id FROM project_staff_assignments WHERE project_id = ?)"
            ]
            if selected_vendor_id and str(selected_vendor_id).isdigit():
                staff_where.append("cs.vendor_id = ?")
                staff_params.append(int(selected_vendor_id))

            staffs = conn.execute(f"""
                SELECT cs.id, cs.full_name_vi, cs.status, latest_link.joining_date, latest_link.tentative_leaving_date,
                       COALESCE(v.company_name, v.company_name_vi) AS vendor_name, cs.vendor_id
                FROM contract_staff cs
                JOIN vendors v ON v.id = cs.vendor_id
                LEFT JOIN (
                    SELECT staff_id, joining_date, tentative_leaving_date
                    FROM contract_staff_links l1
                    WHERE l1.joining_date = (
                        SELECT MAX(l2.joining_date)
                        FROM contract_staff_links l2
                        WHERE l2.staff_id = l1.staff_id
                    )
                ) latest_link ON latest_link.staff_id = cs.id
                WHERE {" AND ".join(staff_where)}
                ORDER BY v.company_name ASC, cs.full_name_vi ASC
            """, staff_params).fetchall()

            # Get existing assignments for the listed months
            if months:
                placeholders = ",".join("?" for _ in months)
                assign_rows = conn.execute(f"""
                    SELECT psa.staff_id, psa.month, psa.project_id, p.short_name AS project_name
                    FROM project_staff_assignments psa
                    JOIN projects p ON p.id = psa.project_id
                    WHERE psa.month IN ({placeholders})
                """, months).fetchall()
                for ar in assign_rows:
                    assignments_map[(ar["staff_id"], ar["month"])] = (ar["project_id"], ar["project_name"])

            # Get available staffs who are not yet assigned to this project
            avail_params = [project_row["id"]]
            avail_where = [
                "cs.id NOT IN (SELECT DISTINCT staff_id FROM project_staff_assignments WHERE project_id = ?)",
                "(cs.status IS NULL OR TRIM(cs.status) = '')"
            ]
            if selected_vendor_id and str(selected_vendor_id).isdigit():
                avail_where.append("cs.vendor_id = ?")
                avail_params.append(int(selected_vendor_id))

            available_staffs = conn.execute(f"""
                SELECT cs.id, cs.full_name_vi, latest_link.joining_date, latest_link.tentative_leaving_date,
                       COALESCE(v.company_name, v.company_name_vi) AS vendor_name
                FROM contract_staff cs
                JOIN vendors v ON v.id = cs.vendor_id
                LEFT JOIN (
                    SELECT staff_id, joining_date, tentative_leaving_date
                    FROM contract_staff_links l1
                    WHERE l1.joining_date = (
                        SELECT MAX(l2.joining_date)
                        FROM contract_staff_links l2
                        WHERE l2.staff_id = l1.staff_id
                    )
                ) latest_link ON latest_link.staff_id = cs.id
                WHERE {" AND ".join(avail_where)}
                ORDER BY cs.full_name_vi ASC
            """, avail_params).fetchall()

            # Query all contract links for listed staff and available staff
            staff_ids = set([s["id"] for s in staffs] + [s["id"] for s in available_staffs])
            staff_links_map = {}
            if staff_ids:
                placeholders = ",".join("?" for _ in staff_ids)
                links_rows = conn.execute(f"""
                    SELECT staff_id, joining_date, tentative_leaving_date
                    FROM contract_staff_links
                    WHERE staff_id IN ({placeholders})
                """, list(staff_ids)).fetchall()
                for lr in links_rows:
                    staff_links_map.setdefault(lr["staff_id"], []).append(lr)

            # Query busy months of available staff
            avail_ids = [s["id"] for s in available_staffs]
            staff_busy_map = {}
            if avail_ids:
                placeholders = ",".join("?" for _ in avail_ids)
                busy_rows = conn.execute(f"""
                    SELECT psa.staff_id, psa.month, p.short_name AS project_name
                    FROM project_staff_assignments psa
                    JOIN projects p ON p.id = psa.project_id
                    WHERE psa.staff_id IN ({placeholders})
                """, avail_ids).fetchall()
                for br in busy_rows:
                    sid = br["staff_id"]
                    if sid not in staff_busy_map:
                        staff_busy_map[sid] = {}
                    staff_busy_map[sid][br["month"]] = br["project_name"]

            # Query monthly attendance summaries for assigned staffs
            summary_map = {}
            if staffs and months:
                assigned_staff_ids = [s["id"] for s in staffs]
                s_placeholders = ",".join("?" for _ in assigned_staff_ids)
                m_placeholders = ",".join("?" for _ in months)
                sum_rows = conn.execute(f"""
                    SELECT staff_id, month, total_amount, locked
                    FROM monthly_attendance_summary
                    WHERE staff_id IN ({s_placeholders}) AND month IN ({m_placeholders})
                """, assigned_staff_ids + months).fetchall()
                for sr in sum_rows:
                    summary_map[(sr["staff_id"], sr["month"])] = (sr["locked"], sr["total_amount"])

            import json
            client_avail_data = {}
            for s in available_staffs:
                sid = s["id"]
                client_avail_data[sid] = {
                    "joining_date": s["joining_date"],
                    "leaving_date": s["tentative_leaving_date"],
                    "busy": staff_busy_map.get(sid, {})
                }
            js_staff_avail = json.dumps(client_avail_data)
            
    finally:
        conn.close()

    error_html = f'<div class="card danger"><b>Error:</b> {escape(error_msg)}</div>' if error_msg else ""
    success_html = f'<div class="card success"><b>Success:</b> {escape(success_msg)}</div>' if success_msg else ""

    # Build Project Options
    project_opts = ['<option value="">-- select project --</option>']
    for p in projects_list:
        sel = "selected" if selected_project_id and str(p['id']) == str(selected_project_id) else ""
        closed_suffix = " (Closed)" if int(p['is_active'] or 0) == 0 else ""
        project_opts.append(f'<option value="{p["id"]}" {sel}>{escape(p["short_name"])}{closed_suffix} - {escape(p["full_name"])}</option>')

    # Build Vendor Options for Filtering
    vendor_opts = ['<option value="">-- all companies --</option>']
    for v in vendors:
        v_name = v['company_name'] or v['company_name_vi']
        sel = "selected" if selected_vendor_id and str(v['id']) == str(selected_vendor_id) else ""
        vendor_opts.append(f'<option value="{v["id"]}" {sel}>{escape(v_name)}</option>')

    # Filters Form
    filters_html = f"""
    <div style="margin-bottom: 24px;">
      <div class="card" style="margin: 0; padding: 18px;">
        <h3 style="margin-top: 0; margin-bottom: 16px;">Staff Assignments Filters</h3>
        <form class="filters" method="GET" action="/projects/assign" style="display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-end;">
          <div style="flex: 1; min-width: 250px;">
            <div class="label">Project (Required)</div>
            <select name="project_id" onchange="this.form.submit()" style="width: 100%;" required>
              {''.join(project_opts)}
            </select>
          </div>
          <div style="flex: 1; min-width: 250px;">
            <div class="label">Filter by Company (Optional)</div>
            <select name="vendor_id" onchange="this.form.submit()" style="width: 100%;">
              {''.join(vendor_opts)}
            </select>
          </div>
          <div>
            <button type="submit" style="padding: 8px 20px;">Apply Filters</button>
          </div>
        </form>
      </div>
    </div>
    """

    add_staff_form_html = ""
    payment_matrix_html = ""
    # Build Matrix Table
    if not project_row:
        matrix_html = f"""
        <div class="card" style="text-align: center; padding: 40px; color: var(--text-muted);">
          <svg style="width: 48px; height: 48px; fill: var(--text-muted); margin-bottom: 12px;" viewBox="0 0 24 24"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-2 10H7v-2h10v2zm0-4H7V7h10v2zm0 8H7v-2h10v2z"/></svg>
          <p style="font-weight: 500; font-size: 15px; margin: 0;">Please select a Project from the filter above to manage monthly staff assignments.</p>
        </div>
        """
    else:
        # Filter available staff to only include those who have at least one month compatible/available in this project
        filtered_available_staffs = []
        for s in available_staffs:
            is_any_month_available = False
            for m in months:
                try:
                    yr, mn = map(int, m.split('-'))
                    _, last_day_num = calendar.monthrange(yr, mn)
                    first_day_str = f"{m}-01"
                    last_day_str = f"{m}-{last_day_num:02d}"
                except Exception:
                    continue

                # Check active range (onboard / offboard)
                s_links = staff_links_map.get(s["id"], [])
                if s_links:
                    onboarded_and_not_left = any(
                        (not lr["joining_date"] or lr["joining_date"] <= last_day_str) and
                        (not lr["tentative_leaving_date"] or lr["tentative_leaving_date"] >= first_day_str)
                        for lr in s_links
                    )
                else:
                    onboarded_and_not_left = (not s["joining_date"] or s["joining_date"] <= last_day_str) and (not s["tentative_leaving_date"] or s["tentative_leaving_date"] >= first_day_str)

                # Check busy project in month m
                is_busy = staff_busy_map.get(s["id"], {}).get(m) is not None

                if onboarded_and_not_left and not is_busy:
                    is_any_month_available = True
                    break

            if is_any_month_available:
                filtered_available_staffs.append(s)

        # Build options for available staff
        avail_opts = ['<option value="">-- select staff member --</option>']
        for s in filtered_available_staffs:
            avail_opts.append(f'<option value="{s["id"]}">{escape(s["full_name_vi"])} ({escape(s["vendor_name"])})</option>')
            
        # Months checkbox for form (disabled by default until staff is selected)
        avail_months_checkboxes = []
        for m in months:
            avail_months_checkboxes.append(f"""
            <label style="display: inline-flex; align-items: center; gap: 6px; cursor: not-allowed; opacity: 0.5; background: #f1f5f9; padding: 6px 12px; border-radius: 6px; border: 1px solid var(--border); font-size: 13px; font-weight: 500;" title="Please select a staff member first">
              <input type="checkbox" name="months" value="{m}" style="margin: 0;" disabled>
              {m}
            </label>
            """)

        add_staff_form_html = f"""
        <div class="card" id="add-staff-section" style="margin-bottom: 24px;">
          <h3 style="margin-top: 0; margin-bottom: 16px;">Add New Staff member to Project</h3>
          <form method="POST" action="/project/assign/create">
            <input type="hidden" name="project_id" value="{project_row["id"]}">
            <div style="margin-bottom: 16px;">
              <div class="label">Select Staff member to add</div>
              <select id="add_staff_select" name="staff_id" style="width: 100%;" required>
                {''.join(avail_opts)}
              </select>
            </div>
            
            <div style="margin-bottom: 16px;">
              <div class="label">Select initial months to assign (at least one month is required)</div>
              <div style="display: flex; gap: 12px; flex-wrap: wrap; padding: 12px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg-main);">
                {''.join(avail_months_checkboxes) if avail_months_checkboxes else '<span class="muted">No months available for this project.</span>'}
              </div>
            </div>
            
            <div class="actions">
              <button type="submit" class="btn-primary">Add Staff to Project</button>
            </div>
          </form>
        </div>
        """

        # Build headers
        th_months = "".join(f'<th style="text-align: center; min-width: 80px; font-size: 12px; font-weight: 600;">{m}</th>' for m in months)
        
        # Build rows
        trs = []
        if not staffs:
            colspan = 3 + len(months)
            trs.append(f'<tr><td colspan="{colspan}" style="text-align: center; color: var(--text-muted); padding: 20px;">No staff members found matching the filters.</td></tr>')
        else:
            for idx, s in enumerate(staffs, 1):
                td_months = []
                for m in months:
                    # check if active
                    try:
                        yr, mn = map(int, m.split('-'))
                        _, last_day_num = calendar.monthrange(yr, mn)
                        first_day_str = f"{m}-01"
                        last_day_str = f"{m}-{last_day_num:02d}"
                    except Exception:
                        td_months.append('<td style="text-align: center;">-</td>')
                        continue

                    s_links = staff_links_map.get(s["id"], [])
                    if s_links:
                        is_active = any(
                            (not lr["joining_date"] or lr["joining_date"] <= last_day_str) and
                            (not lr["tentative_leaving_date"] or lr["tentative_leaving_date"] >= first_day_str)
                            for lr in s_links
                        )
                    elif s["joining_date"]:
                        is_active = (s["joining_date"] <= last_day_str) and (not s["tentative_leaving_date"] or s["tentative_leaving_date"] >= first_day_str)
                    else:
                        is_active = True

                    if not is_active and (s["id"], m) in assignments_map:
                        is_active = True

                    if not is_active:
                        td_months.append('<td style="text-align: center; background: var(--bg-main); color: var(--text-muted); font-size: 11px;" title="Staff is inactive in this month">Inactive</td>')
                    else:
                        assigned_info = assignments_map.get((s["id"], m))
                        if assigned_info:
                            assigned_pid, assigned_pname = assigned_info
                            if assigned_pid == project_row["id"]:
                                td_months.append(f"""
                                <td style="text-align: center; background: #ecfdf5; border-color: #bbf7d0;">
                                  <input type="checkbox" 
                                         class="assign-matrix-cb" 
                                         data-staff-id="{s['id']}" 
                                         data-project-id="{project_row['id']}" 
                                         data-month="{m}" 
                                         checked
                                         style="width: 18px; height: 18px; cursor: pointer;">
                                </td>
                                """)
                            else:
                                td_months.append(f"""
                                <td style="text-align: center; background: #fff1f2; color: #b91c1c; font-size: 11px; font-weight: 500;" title="Assigned to {escape(assigned_pname)}">
                                  {escape(assigned_pname)}
                                </td>
                                """)
                        else:
                            td_months.append(f"""
                            <td style="text-align: center;">
                              <input type="checkbox" 
                                     class="assign-matrix-cb" 
                                     data-staff-id="{s['id']}" 
                                     data-project-id="{project_row['id']}" 
                                     data-month="{m}" 
                                     style="width: 18px; height: 18px; cursor: pointer;">
                            </td>
                            """)

                td_months_str = "".join(td_months)
                st_status = (s["status"] or "").strip().lower() if "status" in s.keys() else ""
                status_tag = ' <span class="tag tag-deactive" style="font-size:10px; margin-left:4px;">Inactive</span>' if st_status == "inactive" else ""
                trs.append(f"""
                <tr>
                  <td>{idx}</td>
                  <td style="font-weight: 600; color: var(--text-main);">{escape(s['full_name_vi'])}{status_tag}</td>
                  <td><span class="muted" style="font-size: 12px;">{escape(s['vendor_name'])}</span></td>
                  {td_months_str}
                </tr>
                """)

        matrix_html = f"""
        <div class="card" style="padding: 0; overflow-x: auto;">
          <div style="padding: 16px 20px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; background: #f8fafc;">
            <div>
              <h4 style="margin: 0; font-size: 16px; color: var(--primary);">{escape(project_row['short_name'])} - {escape(project_row['full_name'])}</h4>
              <p style="margin: 4px 0 0 0; font-size: 12px; color: var(--text-muted);">
                OS Period: {escape(project_row['os_start_date'] or 'N/A')} to {escape(project_row['os_end_date'] or 'N/A')}
              </p>
            </div>
            <div style="font-size: 12px; background: #e0f2fe; color: #0369a1; padding: 4px 10px; border-radius: 6px; font-weight: 500;">
              Active in this project
            </div>
          </div>
          <table style="width: 100%; border-collapse: collapse; margin: 0; min-width: 800px;">
            <thead>
              <tr style="background: #f8fafc; border-bottom: 1px solid var(--border);">
                <th style="width: 50px;">No.</th>
                <th>Staff Name</th>
                <th>Company (Vendor)</th>
                {th_months}
              </tr>
            </thead>
            <tbody>
              {"".join(trs)}
            </tbody>
          </table>
        </div>
        """
        payment_th_months = "".join(f'<th style="text-align: right; min-width: 110px; font-size: 12px; font-weight: 600;">{m}</th>' for m in months)
        payment_trs = []
        month_totals = {m: 0.0 for m in months}
        grand_total = 0.0

        if not staffs:
            colspan = 4 + len(months)
            payment_trs.append(f'<tr><td colspan="{colspan}" style="text-align: center; color: var(--text-muted); padding: 20px;">No staff members found matching the filters.</td></tr>')
        else:
            for idx, s in enumerate(staffs, 1):
                td_payments = []
                staff_total = 0.0
                for m in months:
                    assigned_info = assignments_map.get((s["id"], m))
                    if assigned_info and assigned_info[0] == project_row["id"]:
                        sum_info = summary_map.get((s["id"], m))
                        if sum_info:
                            locked, amt = sum_info
                            if locked == 1:
                                amt_val = amt or 0.0
                                staff_total += amt_val
                                month_totals[m] += amt_val
                                grand_total += amt_val
                                td_payments.append(f"""
                                <td style="text-align: right; font-weight: 600; color: #047857; background: #ecfdf5; font-size: 12px;">
                                  🔒 {escape(fmt_money(amt_val))}
                                </td>
                                """)
                            else:
                                td_payments.append("""
                                <td style="text-align: center; background: #fffbeb; color: #b45309; font-size: 11px;" title="Monthly Payroll & Payment is not locked yet">
                                  ⚠️ Unlocked
                                </td>
                                """)
                        else:
                            td_payments.append('<td style="text-align: center; color: var(--text-muted); font-size: 11px;">-</td>')
                    else:
                        td_payments.append('<td style="text-align: center; color: var(--text-muted); font-size: 11px;">-</td>')

                staff_total_str = fmt_money(staff_total) if staff_total > 0 else "-"
                td_payments_str = "".join(td_payments)
                payment_trs.append(f"""
                <tr>
                  <td>{idx}</td>
                  <td style="font-weight: 600; color: var(--text-main);">{escape(s['full_name_vi'])}</td>
                  <td><span class="muted" style="font-size: 12px;">{escape(s['vendor_name'])}</span></td>
                  {td_payments_str}
                  <td style="text-align: right; font-weight: 700; color: #047857; font-size: 12px; background: #f8fafc;">{escape(staff_total_str)}</td>
                </tr>
                """)

        tfoot_month_tds = []
        for m in months:
            m_tot = month_totals[m]
            m_tot_str = fmt_money(m_tot) if m_tot > 0 else "-"
            tfoot_month_tds.append(f'<td style="text-align: right; font-weight: 700; color: #047857; font-size: 12px;">{escape(m_tot_str)}</td>')

        grand_total_str = fmt_money(grand_total) if grand_total > 0 else "-"

        export_url = f"/projects/assign/export?project_id={project_row['id']}" + (f"&vendor_id={selected_vendor_id}" if selected_vendor_id else "")
        payment_matrix_html = f"""
        <div class="card" style="padding: 0; overflow-x: auto; margin-top: 24px;">
          <div style="padding: 16px 20px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; background: #f8fafc;">
            <div>
              <h4 style="margin: 0; font-size: 16px; color: var(--primary);">🔒 Locked Monthly Payroll & Payment Matrix (VND)</h4>
              <p style="margin: 4px 0 0 0; font-size: 12px; color: var(--text-muted);">
                Displays monthly payment amounts per staff for project <b>{escape(project_row['short_name'])}</b> based on locked monthly attendance & payroll records.
              </p>
            </div>
            <div style="display: flex; align-items: center; gap: 10px;">
              <a href="{export_url}" 
                 class="btn-secondary" 
                 style="display: inline-flex; align-items: center; gap: 6px; font-size: 12px; text-decoration: none; padding: 5px 12px; background: #ffffff; border: 1px solid var(--border); border-radius: 6px; color: var(--text-main); font-weight: 500;" 
                 title="Export Payment Matrix to CSV">
                <svg style="width: 14px; height: 14px; fill: currentColor;" viewBox="0 0 24 24"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>
                Export CSV
              </a>
              <div style="font-size: 12px; background: #ecfdf5; color: #047857; padding: 4px 10px; border-radius: 6px; font-weight: 500;">
                Locked Records Only
              </div>
            </div>
          </div>
          <table style="width: 100%; border-collapse: collapse; margin: 0; min-width: 800px;">
            <thead>
              <tr style="background: #f8fafc; border-bottom: 1px solid var(--border);">
                <th style="width: 50px;">No.</th>
                <th>Staff Name</th>
                <th>Company (Vendor)</th>
                {payment_th_months}
                <th style="text-align: right; min-width: 110px; font-size: 12px; font-weight: 700;">Total (VND)</th>
              </tr>
            </thead>
            <tbody>
              {"".join(payment_trs)}
            </tbody>
            <tfoot>
              <tr style="background: #f1f5f9; font-weight: bold; border-top: 2px solid var(--border);">
                <td colspan="3" style="text-align: right; font-weight: 700;">Total Payment:</td>
                {"".join(tfoot_month_tds)}
                <td style="text-align: right; color: #047857; font-weight: 700; font-size: 13px; background: #e6fffa;">{escape(grand_total_str)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
        """

    body = f"""
    {error_html}
    {success_html}

    {filters_html}
    {add_staff_form_html}
    {matrix_html}
    {payment_matrix_html}

    <script>
      (function() {{
        // Attach change listener to all matrix checkboxes
        document.querySelectorAll('.assign-matrix-cb').forEach(cb => {{
          cb.addEventListener('change', function() {{
            const staffId = this.getAttribute('data-staff-id');
            const projectId = this.getAttribute('data-project-id');
            const month = this.getAttribute('data-month');
            const assign = this.checked ? 1 : 0;

            // Visual feedback - disable during AJAX
            const originalDisabled = this.disabled;
            this.disabled = true;
            
            const cell = this.closest('td');
            const originalBackground = cell.style.background;
            cell.style.background = '#f1f5f9';

            fetch('/api/projects/toggle-assignment', {{
              method: 'POST',
              headers: {{
                'Content-Type': 'application/x-www-form-urlencoded',
              }},
              body: 'project_id=' + encodeURIComponent(projectId) + 
                    '&staff_id=' + encodeURIComponent(staffId) + 
                    '&month=' + encodeURIComponent(month) + 
                    '&assign=' + encodeURIComponent(assign)
            }})
            .then(res => res.json())
            .then(data => {{
              this.disabled = originalDisabled;
              if (data.status === 'ok') {{
                if (assign === 1) {{
                  cell.style.background = '#ecfdf5';
                  cell.style.borderColor = '#bbf7d0';
                }} else {{
                  cell.style.background = '';
                  cell.style.borderColor = '';
                }}
              }} else {{
                alert(data.message || 'Failed to update assignment.');
                this.checked = !this.checked; // revert
                cell.style.background = originalBackground;
              }}
            }})
            .catch(err => {{
              this.disabled = originalDisabled;
              alert('Network error. Failed to save assignment.');
              this.checked = !this.checked; // revert
              cell.style.background = originalBackground;
            }});
          }});
        }});

        // Dynamic availability alignment for Add Staff form checkboxes
        const staffSel = document.getElementById('add_staff_select');
        const monthsCbs = document.querySelectorAll('input[name="months"]');
        const availData = {js_staff_avail};

        if (staffSel) {{
          staffSel.addEventListener('change', function() {{
            const sid = this.value;
            if (!sid) {{
              monthsCbs.forEach(cb => {{
                cb.disabled = true;
                cb.checked = false;
                const lbl = cb.closest('label');
                lbl.style.opacity = '0.5';
                lbl.style.cursor = 'not-allowed';
                lbl.title = 'Please select a staff member first';
                const statusSpan = lbl.querySelector('.avail-status');
                if (statusSpan) statusSpan.remove();
              }});
              return;
            }}

            const info = availData[sid];
            if (!info) return;

            const joining = info.joining_date;
            const leaving = info.leaving_date;
            const busy = info.busy || {{}};

            monthsCbs.forEach(cb => {{
              const m = cb.value;
              let disableReason = "";

              if (joining) {{
                const jMonth = joining.substring(0, 7);
                if (m < jMonth) {{
                  disableReason = "Not onboarded";
                }}
              }}

              if (!disableReason && leaving) {{
                const lMonth = leaving.substring(0, 7);
                if (m > lMonth) {{
                  disableReason = "Contract expired";
                }}
              }}

              if (!disableReason && busy[m]) {{
                disableReason = "Busy: " + busy[m];
              }}

              const lbl = cb.closest('label');
              let statusSpan = lbl.querySelector('.avail-status');
              if (statusSpan) statusSpan.remove();

              if (disableReason) {{
                cb.disabled = true;
                cb.checked = false;
                lbl.style.opacity = '0.5';
                lbl.style.cursor = 'not-allowed';
                lbl.title = disableReason;
                
                const span = document.createElement('span');
                span.className = 'avail-status';
                span.style.fontSize = '10px';
                span.style.color = '#ef4444';
                span.style.marginLeft = '4px';
                span.style.fontWeight = 'bold';
                span.innerText = '(' + disableReason + ')';
                lbl.appendChild(span);
              }} else {{
                cb.disabled = false;
                lbl.style.opacity = '1';
                lbl.style.cursor = 'pointer';
                lbl.title = '';
              }}
            }});
          }});
          
          staffSel.dispatchEvent(new Event('change'));
        }}
      }})();
    </script>
    """

    return layout(f"Project Staff Assignments", body)

def handle_project_assign_create_post(handler):
    form = read_post_form(handler)
    project_id_raw = (form.get("project_id", [""])[0] or "").strip()
    staff_id_raw = (form.get("staff_id", [""])[0] or "").strip()
    months = form.get("months", [])

    if not project_id_raw.isdigit() or not staff_id_raw.isdigit() or not months:
        send_html(handler, page_projects_assign(error_msg="Project, Staff, and at least one Month are required."), status=400)
        return

    project_id = int(project_id_raw)
    staff_id = int(staff_id_raw)

    conn = db_connect()
    try:
        # Validate for each month first to ensure transaction consistency
        for month in months:
            month = month.strip()
            if not month:
                continue

            year, m = map(int, month.split('-'))
            _, last_day = calendar.monthrange(year, m)
            first_day_str = f"{month}-01"
            last_day_str = f"{month}-{last_day:02d}"

            staff_ok = conn.execute("""
                SELECT 1 FROM contract_staff s
                JOIN contract_staff_links l ON l.staff_id = s.id
                WHERE s.id = ? 
                  AND l.joining_date <= ?
                  AND (l.tentative_leaving_date IS NULL OR l.tentative_leaving_date = '' OR l.tentative_leaving_date >= ?)
            """, (staff_id, last_day_str, first_day_str)).fetchone()

            if not staff_ok:
                send_html(handler, page_projects_assign(month, error_msg=f"Staff member is not active or has left in the month {month}."), status=400)
                return

            # Double check assignment uniqueness
            exists = conn.execute("""
                SELECT p.short_name FROM project_staff_assignments a
                JOIN projects p ON p.id = a.project_id
                WHERE a.staff_id = ? AND a.month = ?
            """, (staff_id, month)).fetchone()

            if exists:
                send_html(handler, page_projects_assign(month, error_msg=f"Staff member is already assigned to project '{exists['short_name']}' in {month}."), status=400)
                return

        # Get names for log
        p_row = conn.execute("SELECT short_name FROM projects WHERE id=?", (project_id,)).fetchone()
        s_row = conn.execute("SELECT full_name_vi FROM contract_staff WHERE id=?", (staff_id,)).fetchone()
        p_name = p_row["short_name"] if p_row else f"ID {project_id}"
        s_name = s_row["full_name_vi"] if s_row else f"ID {staff_id}"

        # Perform insertion for all selected months
        cur = conn.cursor()
        for month in months:
            month = month.strip()
            if not month:
                continue
            cur.execute("""
                INSERT INTO project_staff_assignments (project_id, staff_id, month, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (project_id, staff_id, month, now_iso(), now_iso()))
            new_assign_id = cur.lastrowid
            log_action(cur, "ASSIGN_STAFF", "project_staff_assignments", new_assign_id, f"Assigned staff '{s_name}' to project '{p_name}' for month {month}")
        conn.commit()
    except Exception as e:
        send_html(handler, page_projects_assign(error_msg=f"Database error: {str(e)}"), status=500)
        return
    finally:
        conn.close()

    first_month = months[0] if months else ""
    redirect(handler, f"/projects/assign?month={first_month}&project_id={project_id}")

def handle_project_assign_delete_post(handler):
    form = read_post_form(handler)
    assignment_id_raw = (form.get("id", [""])[0] or "").strip()
    month = (form.get("month", [""])[0] or "").strip()

    if not assignment_id_raw.isdigit():
        send_html(handler, page_projects_assign(month, error_msg="Invalid Assignment ID."), status=400)
        return

    assignment_id = int(assignment_id_raw)

    conn = db_connect()
    try:
        conn.execute("DELETE FROM project_staff_assignments WHERE id = ?", (assignment_id,))
        conn.commit()
    finally:
        conn.close()

    redirect(handler, f"/projects/assign?month={month}")

def handle_available_staff_ajax(handler):
    # Parse query string for ?months=2026-05,2026-06
    from urllib.parse import urlparse, parse_qs
    import json
    
    parsed = urlparse(handler.path)
    qs = parse_qs(parsed.query)
    months_str = qs.get("months", [""])[0]
    
    if not months_str:
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.end_headers()
        handler.wfile.write(json.dumps([]).encode('utf-8'))
        return

    months = [m.strip() for m in months_str.split(",") if m.strip()]
    
    conn = db_connect()
    try:
        common_staff_ids = None
        staff_details = {}
        
        for month_str in months:
            try:
                year, m = map(int, month_str.split('-'))
                _, last_day = calendar.monthrange(year, m)
                first_day_str = f"{month_str}-01"
                last_day_str = f"{month_str}-{last_day:02d}"
            except Exception:
                continue
                
            rows = conn.execute("""
                SELECT s.id, s.full_name_vi, s.position,
                       COALESCE(v.company_name, v.company_name_vi) AS vendor_name
                FROM contract_staff s
                JOIN vendors v ON v.id = s.vendor_id
                JOIN contract_staff_links l ON l.staff_id = s.id
                WHERE (s.status IS NULL OR TRIM(s.status) = '')
                  AND l.joining_date <= ?
                  AND (l.tentative_leaving_date IS NULL OR l.tentative_leaving_date = '' OR l.tentative_leaving_date >= ?)
                  AND s.id NOT IN (
                      SELECT staff_id FROM project_staff_assignments WHERE month = ?
                  )
            """, (last_day_str, first_day_str, month_str)).fetchall()
            
            current_ids = set()
            for r in rows:
                current_ids.add(r['id'])
                staff_details[r['id']] = {
                    "id": r['id'],
                    "full_name_vi": r['full_name_vi'],
                    "vendor_name": r['vendor_name'],
                    "position": r['position'] or "No position"
                }
                
            if common_staff_ids is None:
                common_staff_ids = current_ids
            else:
                common_staff_ids = common_staff_ids.intersection(current_ids)
                
            if not common_staff_ids:
                break
                
        result = []
        if common_staff_ids:
            for s_id in sorted(common_staff_ids):
                result.append(staff_details[s_id])
                
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.end_headers()
        handler.wfile.write(json.dumps(result).encode('utf-8'))
        
    except Exception as e:
        handler.send_response(500)
        handler.send_header("Content-Type", "application/json")
        handler.end_headers()
        handler.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
    finally:
        conn.close()


def handle_project_toggle_assignment_ajax(handler):
    form = read_post_form(handler)
    project_id_raw = (form.get("project_id", [""])[0] or "").strip()
    staff_id_raw = (form.get("staff_id", [""])[0] or "").strip()
    month = (form.get("month", [""])[0] or "").strip()
    assign_raw = (form.get("assign", [""])[0] or "").strip()
    
    import json
    
    if not project_id_raw.isdigit() or not staff_id_raw.isdigit() or not month or not assign_raw.isdigit():
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.end_headers()
        handler.wfile.write(json.dumps({"status": "error", "message": "Missing or invalid parameters"}).encode('utf-8'))
        return

    project_id = int(project_id_raw)
    staff_id = int(staff_id_raw)
    assign = int(assign_raw) # 1=Assign, 0=Unassign
    
    conn = db_connect()
    try:
        if assign == 1:
            # Validate active
            year, m = map(int, month.split('-'))
            _, last_day = calendar.monthrange(year, m)
            first_day_str = f"{month}-01"
            last_day_str = f"{month}-{last_day:02d}"

            staff_ok = conn.execute("""
                SELECT 1 FROM contract_staff s
                JOIN contract_staff_links l ON l.staff_id = s.id
                WHERE s.id = ? 
                  AND l.joining_date <= ?
                  AND (l.tentative_leaving_date IS NULL OR l.tentative_leaving_date = '' OR l.tentative_leaving_date >= ?)
            """, (staff_id, last_day_str, first_day_str)).fetchone()

            if not staff_ok:
                handler.send_response(200)
                handler.send_header("Content-Type", "application/json")
                handler.end_headers()
                handler.wfile.write(json.dumps({"status": "error", "message": "Staff member is not active in this month"}).encode('utf-8'))
                return

            # Validate duplicate
            exists = conn.execute("""
                SELECT p.short_name FROM project_staff_assignments a
                JOIN projects p ON p.id = a.project_id
                WHERE a.staff_id = ? AND a.month = ?
            """, (staff_id, month)).fetchone()

            if exists:
                handler.send_response(200)
                handler.send_header("Content-Type", "application/json")
                handler.end_headers()
                handler.wfile.write(json.dumps({"status": "error", "message": f"Staff member is already assigned to project '{exists['short_name']}' in {month}"}).encode('utf-8'))
                return

            # Get names for log
            p_row = conn.execute("SELECT short_name FROM projects WHERE id=?", (project_id,)).fetchone()
            s_row = conn.execute("SELECT full_name_vi FROM contract_staff WHERE id=?", (staff_id,)).fetchone()
            p_name = p_row["short_name"] if p_row else f"ID {project_id}"
            s_name = s_row["full_name_vi"] if s_row else f"ID {staff_id}"

            # Insert
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO project_staff_assignments (project_id, staff_id, month, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (project_id, staff_id, month, now_iso(), now_iso()))
            new_assign_id = cur.lastrowid
            log_action(cur, "ASSIGN_STAFF", "project_staff_assignments", new_assign_id, f"Assigned staff '{s_name}' to project '{p_name}' for month {month}")
            conn.commit()
            
        else:
            # Get names for log
            p_row = conn.execute("SELECT short_name FROM projects WHERE id=?", (project_id,)).fetchone()
            s_row = conn.execute("SELECT full_name_vi FROM contract_staff WHERE id=?", (staff_id,)).fetchone()
            p_name = p_row["short_name"] if p_row else f"ID {project_id}"
            s_name = s_row["full_name_vi"] if s_row else f"ID {staff_id}"

            # Delete
            cur = conn.cursor()
            cur.execute("""
                DELETE FROM project_staff_assignments 
                WHERE project_id = ? AND staff_id = ? AND month = ?
            """, (project_id, staff_id, month))
            log_action(cur, "UNASSIGN_STAFF", "project_staff_assignments", None, f"Unassigned staff '{s_name}' from project '{p_name}' for month {month}")
            conn.commit()
            
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.end_headers()
        handler.wfile.write(json.dumps({"status": "ok"}).encode('utf-8'))
        
    except Exception as e:
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.end_headers()
        handler.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
    finally:
        conn.close()


def page_project_edit(project_id: int, error_msg: str | None = None):
    conn = db_connect()
    try:
        project = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not project:
            return layout("Error", f"<div class='card danger'>Project ID={project_id} not found. <a href='/projects'>Back to Projects</a></div>")

        # 1. Fetch assignments
        assignments = conn.execute("""
            SELECT staff_id, month 
            FROM project_staff_assignments 
            WHERE project_id = ?
        """, (project_id,)).fetchall()

        payroll_table_html = ""
        if assignments:
            staff_ids = list({a["staff_id"] for a in assignments})
            
            # Fetch links
            placeholders = ",".join("?" for _ in staff_ids)
            links = conn.execute(f"""
                SELECT id, staff_id, contract_id, annex_id, joining_date, tentative_leaving_date
                FROM contract_staff_links
                WHERE staff_id IN ({placeholders})
            """, staff_ids).fetchall()
            
            contract_ids = list({lnk["contract_id"] for lnk in links})
            contracts_map = {}
            if contract_ids:
                c_placeholders = ",".join("?" for _ in contract_ids)
                contracts_data = conn.execute(f"""
                    SELECT id, framework_no, framework_name, start_date, end_date
                    FROM contracts
                    WHERE id IN ({c_placeholders})
                """, contract_ids).fetchall()
                contracts_map = {c["id"]: c for c in contracts_data}
                
            annex_ids = list({lnk["annex_id"] for lnk in links if lnk["annex_id"] is not None})
            annexes_map = {}
            if annex_ids:
                a_placeholders = ",".join("?" for _ in annex_ids)
                annexes_data = conn.execute(f"""
                    SELECT id, contract_id, annex_name, start_date, end_date
                    FROM contract_annexes
                    WHERE id IN ({a_placeholders})
                """, annex_ids).fetchall()
                annexes_map = {a["id"]: a for a in annexes_data}
                
            summaries_rows = conn.execute(f"""
                SELECT staff_id, month, total_amount
                FROM monthly_attendance_summary
                WHERE staff_id IN ({placeholders})
            """, staff_ids).fetchall()
            summaries_map = {(s["staff_id"], s["month"]): s["total_amount"] for s in summaries_rows}
            
            def get_active_link(staff_id, month_str):
                try:
                    yr, mn = map(int, month_str.split("-"))
                    month_start = f"{yr:04d}-{mn:02d}-01"
                    month_end = f"{yr:04d}-{mn:02d}-{calendar.monthrange(yr, mn)[1]:02d}"
                except Exception:
                    return None
                
                for lnk in links:
                    if lnk["staff_id"] != staff_id:
                        continue
                    join_date = lnk["joining_date"] or "0000-00-00"
                    if join_date == "":
                        join_date = "0000-00-00"
                    leave_date = lnk["tentative_leaving_date"] or "9999-12-31"
                    if leave_date == "":
                        leave_date = "9999-12-31"
                    if join_date <= month_end and leave_date >= month_start:
                        return lnk
                return None
                
            def generate_months(start_date_str, end_date_str):
                if not start_date_str:
                    return []
                try:
                    s_yr, s_mn = map(int, start_date_str.split("-")[:2])
                    if end_date_str:
                        e_yr, e_mn = map(int, end_date_str.split("-")[:2])
                    else:
                        e_yr, e_mn = s_yr, s_mn + 11
                except Exception:
                    return []
                res = []
                curr_yr, curr_mn = s_yr, s_mn
                while (curr_yr < e_yr) or (curr_yr == e_yr and curr_mn <= e_mn):
                    res.append(f"{curr_yr:04d}-{curr_mn:02d}")
                    curr_mn += 1
                    if curr_mn > 12:
                        curr_mn = 1
                        curr_yr += 1
                return res

            # Determine all months in scope
            all_months_set = set()
            for a in assignments:
                all_months_set.add(a["month"])
            for c in contracts_map.values():
                for m in generate_months(c["start_date"], c["end_date"]):
                    all_months_set.add(m)
            for a in annexes_map.values():
                for m in generate_months(a["start_date"], a["end_date"]):
                    all_months_set.add(m)
            
            sorted_all_months = sorted(list(all_months_set))
            
            # Populate grid data
            grid_data = {} # (contract_id, annex_id) -> {month: amount}
            row_names = {}
            
            for a in assignments:
                sid = a["staff_id"]
                m = a["month"]
                lnk = get_active_link(sid, m)
                if lnk:
                    c_id = lnk["contract_id"]
                    a_id = lnk["annex_id"]
                else:
                    c_id = "unknown"
                    a_id = None
                
                key = (c_id, a_id)
                if key not in grid_data:
                    grid_data[key] = {mon: 0.0 for mon in sorted_all_months}
                    if c_id == "unknown":
                        row_names[key] = "Unknown Contract"
                    else:
                        c_info = contracts_map.get(c_id)
                        c_no = c_info["framework_no"] if c_info else f"ID {c_id}"
                        if a_id is not None:
                            a_info = annexes_map.get(a_id)
                            a_name = a_info["annex_name"] if a_info else f"PL ID {a_id}"
                            row_names[key] = f"Annex: {a_name} (Contract: {c_no})"
                        else:
                            row_names[key] = f"Framework Contract: {c_no} (Main Section)"
                
                amt = summaries_map.get((sid, m), 0.0)
                grid_data[key][m] += amt
                
            if grid_data:
                col_totals = {mon: 0.0 for mon in sorted_all_months}
                grand_total = 0.0
                
                th_elements = "".join(f"<th style='text-align:right; min-width:80px;'>{m}</th>" for m in sorted_all_months)
                
                trs = []
                sorted_keys = sorted(grid_data.keys(), key=lambda k: row_names[k])
                for key in sorted_keys:
                    name = row_names[key]
                    amounts = grid_data[key]
                    row_total = sum(amounts.values())
                    grand_total += row_total
                    
                    td_elements = []
                    for m in sorted_all_months:
                        val = amounts[m]
                        col_totals[m] += val
                        val_str = f"{int(round(val)):,}" if val > 0 else "-"
                        td_elements.append(f"<td style='text-align:right; padding:10px 8px;'>{val_str}</td>")
                        
                    row_total_str = f"{int(round(row_total)):,}" if row_total > 0 else "0"
                    trs.append(f"""
                    <tr style="border-bottom:1px solid var(--border);">
                      <td style="padding:10px 8px; font-weight:600; color:var(--primary);">{escape(name)}</td>
                      {"".join(td_elements)}
                      <td style="text-align:right; padding:10px 8px; font-weight:bold; background:#f8fafc;">{row_total_str}</td>
                    </tr>
                    """)
                    
                footer_tds = []
                for m in sorted_all_months:
                    val = col_totals[m]
                    val_str = f"{int(round(val)):,}" if val > 0 else "0"
                    footer_tds.append(f"<td style='text-align:right; padding:10px 8px; font-weight:bold;'>{val_str}</td>")
                    
                grand_total_str = f"{int(round(grand_total)):,}"
                th_elements = "".join(f'<th style="text-align:right; font-size:12px; width:90px; padding:10px 8px; color:var(--text-muted);">{m}</th>' for m in sorted_all_months)
                
                payroll_table_html = f"""
                <div class="card" style="margin-top: 24px; padding:0; overflow-x:auto;">
                  <div style="padding: 16px 20px; border-bottom: 1px solid var(--border); background: #f8fafc;">
                    <h3 style="margin: 0; color: var(--text-primary); font-size:16px;">Payroll Report by Contract / Annex</h3>
                    <p style="margin: 4px 0 0 0; font-size: 12px; color: var(--text-muted);">
                      Summary of actual payments based on monthly attendance allocated to this project.
                    </p>
                  </div>
                  <table style="width:100%; border-collapse:collapse; margin:0; border:none; min-width:600px;">
                    <thead>
                      <tr style="background:#f8fafc; border-bottom:1px solid var(--border);">
                        <th style="text-align:left; padding:10px 8px; font-size:12px; color:var(--text-muted); width:200px;">Contract / Annex</th>
                        {th_elements}
                        <th style="text-align:right; padding:10px 8px; font-size:12px; color:var(--text-muted); width:100px; background:#f8fafc;">Total</th>
                      </tr>
                    </thead>
                    <tbody>
                      {"".join(trs)}
                    </tbody>
                    <tfoot>
                      <tr style="background:#f8fafc; border-top:1px solid var(--border); font-weight: bold;">
                        <td style="padding:10px 8px; font-size:12px; color:var(--text-primary);">Monthly Total</td>
                        {"".join(footer_tds)}
                        <td style="text-align:right; padding:10px 8px; color:var(--primary); background:#f8fafc;">{grand_total_str}</td>
                      </tr>
                    </tfoot>
                  </table>
                  <div style="padding: 16px 20px; border-top: 1px solid var(--border); display: flex; justify-content: flex-end; align-items: center; background: #f8fafc;">
                    <span style="font-size:14px; font-weight:bold; color:var(--text-primary);">Total Paid Amount:&nbsp;<span style="color:var(--primary); font-size:16px;">{grand_total_str} VND</span></span>
                  </div>
                </div>
                """
            else:
                payroll_table_html = f"""
                <div class="card" style="margin-top: 24px; padding:0; overflow-x:auto;">
                  <div style="padding: 16px 20px; border-bottom: 1px solid var(--border); background: #f8fafc;">
                    <h3 style="margin: 0; color: var(--text-primary); font-size:16px;">Payroll Report by Contract / Annex</h3>
                    <p style="margin: 4px 0 0 0; font-size: 12px; color: var(--text-muted);">
                      Summary of actual payments based on monthly attendance allocated to this project.
                    </p>
                  </div>
                  <div style="text-align: center; padding: 20px; color: var(--text-muted);">
                    No payroll or staff assignment data found for this project.
                  </div>
                </div>
                """
        else:
            payroll_table_html = f"""
            <div class="card" style="margin-top: 24px; padding:0; overflow-x:auto;">
              <div style="padding: 16px 20px; border-bottom: 1px solid var(--border); background: #f8fafc;">
                <h3 style="margin: 0; color: var(--text-primary); font-size:16px;">Payroll Report by Contract / Annex</h3>
                <p style="margin: 4px 0 0 0; font-size: 12px; color: var(--text-muted);">
                  Summary of actual payments based on monthly attendance allocated to this project.
                </p>
              </div>
              <div style="text-align: center; padding: 20px; color: var(--text-muted);">
                No payroll or staff assignment data found for this project.
              </div>
            </div>
            """
    finally:
        conn.close()

    error_html = f'<div class="card danger"><b>Error:</b> {escape(error_msg)}</div>' if error_msg else ""
    
    budget_val = f"{project['it_outsourcing_budget']:.2f}" if project['it_outsourcing_budget'] is not None else ""
    start_val = project['os_start_date'] or ""
    end_val = project['os_end_date'] or ""

    body = f"""
    <div style="margin-bottom: 24px;">
      <a href="/projects">← Back to Projects</a>
    </div>

    <div class="card" style="max-width: 600px; margin: 0 auto; padding: 18px;">
      <h3 style="margin-top: 0; margin-bottom: 16px;">Edit Project</h3>
      {error_html}
      <form method="POST" action="/project/update">
        <input type="hidden" name="id" value="{project['id']}">
        
        <div style="margin-bottom: 12px;">
          <div class="label">Short Name (required)</div>
          <input type="text" name="short_name" value="{escape(project['short_name'] or '')}" style="width: 100%;" required>
        </div>

        <div style="margin-bottom: 12px;">
          <div class="label">Full Name (required)</div>
          <input type="text" name="full_name" value="{escape(project['full_name'] or '')}" style="width: 100%;" required>
        </div>

        <div style="margin-bottom: 12px;">
          <div class="label">IT Outsourcing Budget</div>
          <input type="number" step="0.01" name="it_outsourcing_budget" value="{budget_val}" style="width: 100%;">
        </div>

        <div class="grid" style="grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 16px;">
          <div>
            <div class="label">OS Start Date</div>
            <input type="date" name="os_start_date" value="{start_val}" style="width: 100%;">
          </div>
          <div>
            <div class="label">OS End Date</div>
            <input type="date" name="os_end_date" value="{end_val}" style="width: 100%;">
          </div>
        </div>

        <div class="actions" style="margin-top: 20px;">
          <button type="submit" class="btn-primary">Save Changes</button>
          <a href="/projects" class="btn btn-secondary" style="margin-left: 8px;">Cancel</a>
        </div>
      </form>
    </div>
    
    {payroll_table_html}
    """
    return layout(f"Edit Project: {escape(project['short_name'])}", body)


def handle_project_update_post(handler):
    form = read_post_form(handler)
    project_id_raw = (form.get("id", [""])[0] or "").strip()
    
    if not project_id_raw.isdigit():
        send_html(handler, layout("Error", "<div class='card danger'>Invalid Project ID</div>"), status=400)
        return

    project_id = int(project_id_raw)
    short_name = (form.get("short_name", [""])[0] or "").strip()
    full_name = (form.get("full_name", [""])[0] or "").strip()
    it_outsourcing_budget_raw = (form.get("it_outsourcing_budget", [""])[0] or "").strip()
    os_start_date = (form.get("os_start_date", [""])[0] or "").strip() or None
    os_end_date = (form.get("os_end_date", [""])[0] or "").strip() or None

    if not short_name or not full_name:
        send_html(handler, page_project_edit(project_id, "Short Name and Full Name are required."), status=400)
        return

    it_outsourcing_budget = None
    if it_outsourcing_budget_raw:
        try:
            it_outsourcing_budget = float(it_outsourcing_budget_raw.replace(",", ""))
        except ValueError:
            pass

    conn = db_connect()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE projects
            SET short_name = ?,
                full_name = ?,
                it_outsourcing_budget = ?,
                os_start_date = ?,
                os_end_date = ?,
                updated_at = ?
            WHERE id = ?
        """, (short_name, full_name, it_outsourcing_budget, os_start_date, os_end_date, now_iso(), project_id))
        log_action(cur, "UPDATE_PROJECT", "projects", project_id, f"Updated project '{short_name}': {full_name}")
        conn.commit()
    except Exception as e:
        send_html(handler, page_project_edit(project_id, f"Database error: {str(e)}"), status=500)
        return
    finally:
        conn.close()

    redirect(handler, "/projects")


def handle_projects_assign_export_csv(handler):
    parsed = urllib.parse.urlparse(handler.path)
    qs = urllib.parse.parse_qs(parsed.query)

    project_id_raw = qs.get("project_id", [""])[0]
    vendor_id_raw = qs.get("vendor_id", [""])[0]

    if not project_id_raw.isdigit():
        send_html(handler, layout("Error", "<div class='card danger'>Invalid or missing Project ID</div>"), status=400)
        return

    project_id = int(project_id_raw)
    selected_vendor_id = vendor_id_raw if vendor_id_raw.isdigit() else None

    conn = db_connect()
    try:
        project_row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not project_row:
            send_html(handler, layout("Error", "<div class='card danger'>Project not found</div>"), status=404)
            return

        months = []
        start_date_str = project_row["os_start_date"]
        end_date_str = project_row["os_end_date"]
        if start_date_str and end_date_str:
            try:
                start = datetime.strptime(start_date_str.strip(), "%Y-%m-%d")
                end = datetime.strptime(end_date_str.strip(), "%Y-%m-%d")
                current = datetime(start.year, start.month, 1)
                limit = datetime(end.year, end.month, 1)
                while current <= limit:
                    months.append(current.strftime("%Y-%m"))
                    if current.month == 12:
                        current = datetime(current.year + 1, 1, 1)
                    else:
                        current = datetime(current.year, current.month + 1, 1)
            except Exception:
                pass

        if not months:
            now = datetime.now()
            current = datetime(now.year, now.month, 1)
            for _ in range(6):
                months.append(current.strftime("%Y-%m"))
                if current.month == 12:
                    current = datetime(current.year + 1, 1, 1)
                else:
                    current = datetime(current.year, current.month + 1, 1)

        staff_params = [project_id]
        staff_where = [
            "cs.id IN (SELECT DISTINCT staff_id FROM project_staff_assignments WHERE project_id = ?)"
        ]
        if selected_vendor_id:
            staff_where.append("cs.vendor_id = ?")
            staff_params.append(int(selected_vendor_id))

        staffs = conn.execute(f"""
            SELECT cs.id, cs.full_name_vi, cs.status,
                   COALESCE(v.company_name, v.company_name_vi) AS vendor_name
            FROM contract_staff cs
            JOIN vendors v ON v.id = cs.vendor_id
            WHERE {" AND ".join(staff_where)}
            ORDER BY v.company_name ASC, cs.full_name_vi ASC
        """, staff_params).fetchall()

        assignments_map = {}
        if months:
            placeholders = ",".join("?" for _ in months)
            assign_rows = conn.execute(f"""
                SELECT psa.staff_id, psa.month, psa.project_id
                FROM project_staff_assignments psa
                WHERE psa.month IN ({placeholders})
            """, months).fetchall()
            for ar in assign_rows:
                assignments_map[(ar["staff_id"], ar["month"])] = ar["project_id"]

        summary_map = {}
        if staffs and months:
            assigned_staff_ids = [s["id"] for s in staffs]
            s_placeholders = ",".join("?" for _ in assigned_staff_ids)
            m_placeholders = ",".join("?" for _ in months)
            sum_rows = conn.execute(f"""
                SELECT staff_id, month, total_amount, locked
                FROM monthly_attendance_summary
                WHERE staff_id IN ({s_placeholders}) AND month IN ({m_placeholders})
            """, assigned_staff_ids + months).fetchall()
            for sr in sum_rows:
                summary_map[(sr["staff_id"], sr["month"])] = (sr["locked"], sr["total_amount"])

    finally:
        conn.close()

    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)

    writer.writerow(["Project Short Name", project_row["short_name"]])
    writer.writerow(["Project Full Name", project_row["full_name"]])
    writer.writerow(["OS Period", f"{project_row['os_start_date'] or 'N/A'} to {project_row['os_end_date'] or 'N/A'}"])
    writer.writerow([])

    header = ["No.", "Staff Name", "Company (Vendor)"] + months + ["Total Locked Payment (VND)"]
    writer.writerow(header)

    month_totals = {m: 0.0 for m in months}
    grand_total = 0.0

    for idx, s in enumerate(staffs, 1):
        st_name = s["full_name_vi"] + (" (Inactive)" if (s["status"] or "").strip().lower() == "inactive" else "")
        row = [idx, st_name, s["vendor_name"]]
        staff_total = 0.0
        for m in months:
            assigned_pid = assignments_map.get((s["id"], m))
            if assigned_pid == project_id:
                sum_info = summary_map.get((s["id"], m))
                if sum_info:
                    locked, amt = sum_info
                    if locked == 1:
                        amt_val = amt or 0.0
                        staff_total += amt_val
                        month_totals[m] += amt_val
                        grand_total += amt_val
                        row.append(f"{amt_val:,.2f}")
                    else:
                        row.append("Unlocked")
                else:
                    row.append("-")
            else:
                row.append("-")
        row.append(f"{staff_total:,.2f}" if staff_total > 0 else "-")
        writer.writerow(row)

    total_row = ["", "Total Locked Payment (VND)", ""]
    for m in months:
        m_tot = month_totals[m]
        total_row.append(f"{m_tot:,.2f}" if m_tot > 0 else "-")
    total_row.append(f"{grand_total:,.2f}" if grand_total > 0 else "-")
    writer.writerow(total_row)

    csv_bytes = output.getvalue().encode("utf-8")

    clean_short_name = "".join(c for c in (project_row["short_name"] or "Project") if c.isalnum() or c in ("-", "_")).strip()
    fn = f"Payroll_Matrix_{clean_short_name}_{months[0]}_to_{months[-1]}.csv"

    handler.send_response(200)
    handler.send_header("Content-Type", "text/csv; charset=utf-8")
    handler.send_header("Content-Length", str(len(csv_bytes)))
    handler.send_header("Content-Disposition", f'attachment; filename="{fn}"')
    handler.end_headers()
    handler.wfile.write(csv_bytes)
