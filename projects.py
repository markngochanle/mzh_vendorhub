# projects.py
import calendar
from html import escape
from datetime import datetime

from common import (
    db_connect, layout, read_post_form, redirect, send_html, now_iso, log_action
)

def page_projects_list(error_msg: str | None = None, success_msg: str | None = None):
    conn = db_connect()
    try:
        projects = conn.execute("""
            SELECT * FROM projects 
            WHERE is_active = 1 
            ORDER BY short_name ASC, id DESC
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
      <h3 style="margin-top: 0; margin-bottom: 16px;">Active Projects List</h3>
      <table>
        <thead>
          <tr>
            <th>No.</th>
            <th>Short Name</th>
            <th>Full Name</th>
            <th>IT Outsourcing Budget</th>
            <th>OS Start Date</th>
            <th>OS End Date</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
    """

    if not projects:
      body += """
          <tr>
            <td colspan="7" style="text-align: center; color: var(--text-muted);">No active projects found.</td>
          </tr>
      """
    else:
      for idx, p in enumerate(projects, 1):
          budget_str = f"{float(p['it_outsourcing_budget']):,.2f} VND" if p['it_outsourcing_budget'] is not None else "N/A"
          body += f"""
          <tr>
            <td>{idx}</td>
            <td style="font-weight: 600; color: var(--primary);">{escape(p['short_name'] or '')}</td>
            <td>{escape(p['full_name'] or '')}</td>
            <td>{escape(budget_str)}</td>
            <td>{escape(p['os_start_date'] or 'N/A')}</td>
            <td>{escape(p['os_end_date'] or 'N/A')}</td>
            <td>
              <form method="POST" action="/project/delete" class="inline" onsubmit="return confirm('Are you sure you want to deactivate project: {escape(p['short_name'])}?');">
                <input type="hidden" name="id" value="{p['id']}">
                <button type="submit" class="btn-danger" style="font-size:12px; padding: 4px 8px;">Deactivate</button>
              </form>
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
        log_action(cur, "CREATE_PROJECT", "projects", new_project_id, f"Tạo dự án mới '{short_name}' - {full_name}")
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
        log_action(cur, "DEACTIVATE_PROJECT", "projects", project_id, f"Hủy kích hoạt dự án '{p_name}'")
        conn.commit()
    finally:
        conn.close()

    redirect(handler, "/projects")


def page_projects_assign(selected_month: str | None = None, selected_project_id: str | None = None, selected_vendor_id: str | None = None, error_msg: str | None = None, success_msg: str | None = None):
    # Default to current month if not specified
    if not selected_month:
        selected_month = datetime.now().strftime("%Y-%m")

    conn = db_connect()
    try:
        # 1. Get active projects
        projects_list = conn.execute("SELECT * FROM projects WHERE is_active=1 ORDER BY short_name ASC").fetchall()
        
        # 2. Get active vendor sellers (purchasing=0) for filtering
        vendors = conn.execute("""
            SELECT id, company_name, company_name_vi 
            FROM vendors 
            WHERE is_active=1 AND purchasing=0 
            ORDER BY company_name ASC, company_name_vi ASC
        """).fetchall()

        # Check if project_id is valid
        project_row = None
        if selected_project_id and str(selected_project_id).isdigit():
            project_row = conn.execute("SELECT * FROM projects WHERE id=? AND is_active=1", (int(selected_project_id),)).fetchone()

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
                "cs.id IN (SELECT DISTINCT staff_id FROM project_staff_assignments WHERE project_id = ?)",
                "(cs.status IS NULL OR TRIM(cs.status) = '')"
            ]
            if selected_vendor_id and str(selected_vendor_id).isdigit():
                staff_where.append("cs.vendor_id = ?")
                staff_params.append(int(selected_vendor_id))

            staffs = conn.execute(f"""
                SELECT cs.id, cs.full_name_vi, cs.joining_date, cs.tentative_leaving_date,
                       COALESCE(v.company_name, v.company_name_vi) AS vendor_name, cs.vendor_id
                FROM contract_staff cs
                JOIN vendors v ON v.id = cs.vendor_id
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
                SELECT cs.id, cs.full_name_vi,
                       COALESCE(v.company_name, v.company_name_vi) AS vendor_name
                FROM contract_staff cs
                JOIN vendors v ON v.id = cs.vendor_id
                WHERE {" AND ".join(avail_where)}
                ORDER BY cs.full_name_vi ASC
            """, avail_params).fetchall()

    finally:
        conn.close()

    error_html = f'<div class="card danger"><b>Error:</b> {escape(error_msg)}</div>' if error_msg else ""
    success_html = f'<div class="card success"><b>Success:</b> {escape(success_msg)}</div>' if success_msg else ""

    # Build Project Options
    project_opts = ['<option value="">-- select project --</option>']
    for p in projects_list:
        sel = "selected" if selected_project_id and str(p['id']) == str(selected_project_id) else ""
        project_opts.append(f'<option value="{p["id"]}" {sel}>{escape(p["short_name"])} - {escape(p["full_name"])}</option>')

    # Build Vendor Options for Filtering
    vendor_opts = ['<option value="">-- all companies --</option>']
    for v in vendors:
        v_name = v['company_name'] or v['company_name_vi']
        sel = "selected" if selected_vendor_id and str(v['id']) == str(selected_vendor_id) else ""
        vendor_opts.append(f'<option value="{v["id"]}" {sel}>{escape(v_name)}</option>')

    # Filters Form & Quick Create Project Form Grid
    filters_html = f"""
    <div style="display: grid; grid-template-columns: 1.2fr 1fr; gap: 20px; margin-bottom: 24px; align-items: stretch;">
      
      <!-- Left: Assignments Filter -->
      <div class="card" style="margin: 0; display: flex; flex-direction: column; justify-content: space-between; padding: 18px;">
        <div>
          <h3 style="margin-top: 0; margin-bottom: 16px;">Staff Assignments Filters</h3>
          <form class="filters" method="GET" action="/projects/assign" style="display: flex; flex-direction: column; gap: 12px;">
            <div>
              <div class="label">Project (Required)</div>
              <select name="project_id" onchange="this.form.submit()" style="width: 100%;" required>
                {''.join(project_opts)}
              </select>
            </div>
            <div>
              <div class="label">Filter by Company (Optional)</div>
              <select name="vendor_id" onchange="this.form.submit()" style="width: 100%;">
                {''.join(vendor_opts)}
              </select>
            </div>
            <div style="margin-top: 8px;">
              <button type="submit" style="width: 100%;">Apply Filters</button>
            </div>
          </form>
        </div>
      </div>

      <!-- Right: Quick Create New Project -->
      <div class="card" style="margin: 0; padding: 18px;">
        <h3 style="margin-top: 0; margin-bottom: 12px;">Quick Create New Project</h3>
        <form method="POST" action="/project/create?redirect_to=/projects/assign" style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px;">
          <div style="grid-column: span 2;">
            <div class="label" style="font-size: 11px;">Short Name (required)</div>
            <input type="text" name="short_name" placeholder="e.g. MZH-Hub" style="width: 100%; padding: 4px; font-size: 13px;" required>
          </div>
          <div style="grid-column: span 2;">
            <div class="label" style="font-size: 11px;">Full Name (required)</div>
            <input type="text" name="full_name" placeholder="e.g. Mizuho Vendor Hub System" style="width: 100%; padding: 4px; font-size: 13px;" required>
          </div>
          <div>
            <div class="label" style="font-size: 11px;">OS Start Date</div>
            <input type="date" name="os_start_date" style="width: 100%; padding: 3px; font-size: 12px;">
          </div>
          <div>
            <div class="label" style="font-size: 11px;">OS End Date</div>
            <input type="date" name="os_end_date" style="width: 100%; padding: 3px; font-size: 12px;">
          </div>
          <div style="grid-column: span 2;">
            <div class="label" style="font-size: 11px;">IT Outsourcing Budget</div>
            <input type="number" step="0.01" name="it_outsourcing_budget" placeholder="Budget in VND" style="width: 100%; padding: 4px; font-size: 13px;">
          </div>
          <div style="grid-column: span 2; margin-top: 6px;">
            <button type="submit" class="btn-primary" style="width: 100%; padding: 8px; font-size: 13px;">Create & Select Project</button>
          </div>
        </form>
      </div>

    </div>
    """

    add_staff_form_html = ""
    # Build Matrix Table
    if not project_row:
        matrix_html = f"""
        <div class="card" style="text-align: center; padding: 40px; color: var(--text-muted);">
          <svg style="width: 48px; height: 48px; fill: var(--text-muted); margin-bottom: 12px;" viewBox="0 0 24 24"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-2 10H7v-2h10v2zm0-4H7V7h10v2zm0 8H7v-2h10v2z"/></svg>
          <p style="font-weight: 500; font-size: 15px; margin: 0;">Please select a Project from the filter above to manage monthly staff assignments.</p>
        </div>
        """
    else:
        # Build options for available staff
        avail_opts = ['<option value="">-- select staff member --</option>']
        for s in available_staffs:
            avail_opts.append(f'<option value="{s["id"]}">{escape(s["full_name_vi"])} ({escape(s["vendor_name"])})</option>')
            
        # Months checkbox for form
        avail_months_checkboxes = []
        for m in months:
            avail_months_checkboxes.append(f"""
            <label style="display: inline-flex; align-items: center; gap: 6px; cursor: pointer; background: #f1f5f9; padding: 6px 12px; border-radius: 6px; border: 1px solid var(--border); font-size: 13px; font-weight: 500;">
              <input type="checkbox" name="months" value="{m}" style="margin: 0;">
              {m}
            </label>
            """)

        add_staff_form_html = f"""
        <div class="card" style="margin-bottom: 24px;">
          <h3 style="margin-top: 0; margin-bottom: 16px;">Add New Staff member to Project</h3>
          <form method="POST" action="/project/assign/create">
            <input type="hidden" name="project_id" value="{project_row["id"]}">
            <div style="margin-bottom: 16px;">
              <div class="label">Select Staff member to add</div>
              <select name="staff_id" style="width: 100%;" required>
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

                    is_active = (s["joining_date"] <= last_day_str) and (not s["tentative_leaving_date"] or s["tentative_leaving_date"] >= first_day_str)

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
                trs.append(f"""
                <tr>
                  <td>{idx}</td>
                  <td style="font-weight: 600; color: var(--text-main);">{escape(s['full_name_vi'])}</td>
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

    body = f"""
    {error_html}
    {success_html}

    {filters_html}
    {add_staff_form_html}
    {matrix_html}

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
                WHERE s.id = ? 
                  AND (s.status IS NULL OR TRIM(s.status) = '')
                  AND s.joining_date <= ?
                  AND (s.tentative_leaving_date IS NULL OR s.tentative_leaving_date = '' OR s.tentative_leaving_date >= ?)
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
            log_action(cur, "ASSIGN_STAFF", "project_staff_assignments", new_assign_id, f"Gán nhân sự '{s_name}' vào dự án '{p_name}' tháng {month}")
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
                WHERE (s.status IS NULL OR TRIM(s.status) = '')
                  AND s.joining_date <= ?
                  AND (s.tentative_leaving_date IS NULL OR s.tentative_leaving_date = '' OR s.tentative_leaving_date >= ?)
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
                WHERE s.id = ? 
                  AND (s.status IS NULL OR TRIM(s.status) = '')
                  AND s.joining_date <= ?
                  AND (s.tentative_leaving_date IS NULL OR s.tentative_leaving_date = '' OR s.tentative_leaving_date >= ?)
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
            log_action(cur, "ASSIGN_STAFF", "project_staff_assignments", new_assign_id, f"Gán nhân sự '{s_name}' vào dự án '{p_name}' tháng {month}")
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
            log_action(cur, "UNASSIGN_STAFF", "project_staff_assignments", None, f"Hủy gán nhân sự '{s_name}' khỏi dự án '{p_name}' tháng {month}")
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
