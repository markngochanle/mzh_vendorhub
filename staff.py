# staff.py
from html import escape
from datetime import datetime

from common import (
    db_connect, layout, LIST_LIMIT, now_iso,
    read_post_form, redirect, send_html, log_action, to_float_or_none
)


def load_vendors_for_staff(conn):
    # Vendor nhân sự: purchasing=0
    return conn.execute("""
        SELECT id, company_name, company_name_vi, tax_id
        FROM vendors
        WHERE is_active=1 AND purchasing=0
        ORDER BY company_name ASC, company_name_vi ASC, id DESC
    """).fetchall()


def load_contracts(conn):
    return conn.execute("""
        SELECT c.id, c.framework_no, c.framework_name, c.seller_vendor_id,
               COALESCE(bv.company_name, bv.company_name_vi) AS buyer_name,
               COALESCE(sv.company_name, sv.company_name_vi) AS seller_name
        FROM contracts c
        JOIN vendors bv ON bv.id=c.buyer_vendor_id
        JOIN vendors sv ON sv.id=c.seller_vendor_id
        WHERE c.is_active=1
        ORDER BY c.id DESC
    """).fetchall()


def load_annexes(conn):
    return conn.execute("""
        SELECT a.id, a.contract_id, a.annex_name, a.start_date, a.end_date, c.seller_vendor_id
        FROM contract_annexes a
        JOIN contracts c ON c.id = a.contract_id
        WHERE a.is_active=1 AND a.deleted_at IS NULL
        ORDER BY a.contract_id DESC, a.id DESC
    """).fetchall()


def vendor_label(r):
    name = (r["company_name"] or r["company_name_vi"] or "").strip()
    tax = (r["tax_id"] or "").strip()
    return f"{name} ({tax})" if tax else name


def contract_label(r):
    no = (r["framework_no"] or "").strip()
    label = no if no else f"Contract#{r['id']}"
    return label


def check_no_overlap(conn, link_id_exclude, staff_id: int,
                     joining_date: str, leaving_date: str | None):
    """
    Enforce no-overlap for the same staff_id across different contract links.

    Range:
      start = joining_date (required)
      end   = leaving_date or '9999-12-31'

    Overlap condition:
      existing_start <= new_end AND new_start <= existing_end
    """
    new_start = joining_date
    new_end = leaving_date or "9999-12-31"

    params = [staff_id]

    exclude_sql = ""
    if link_id_exclude is not None and str(link_id_exclude).isdigit():
        exclude_sql = "AND l.id <> ?"
        params.append(int(link_id_exclude))

    params.extend([new_end, new_start])

    sql = f"""
        SELECT l.id, l.joining_date, l.tentative_leaving_date, l.contract_id, l.annex_id,
               s.full_name_vi AS staff_name,
               c.framework_no AS contract_no,
               a.annex_name
        FROM contract_staff_links l
        JOIN contract_staff s ON s.id = l.staff_id
        LEFT JOIN contracts c ON c.id = l.contract_id
        LEFT JOIN contract_annexes a ON a.id = l.annex_id
        WHERE l.staff_id = ?
          {exclude_sql}
          AND COALESCE(l.joining_date, '0001-01-01') <= ?
          AND COALESCE(l.tentative_leaving_date, '9999-12-31') >= ?
        LIMIT 1
    """

    row = conn.execute(sql, params).fetchone()
    if row:
        staff_name = row["staff_name"] or f"ID {staff_id}"
        contract_info = f"Contract '{row['contract_no']}'" if row["contract_no"] else f"Contract ID {row['contract_id']}"
        if row["annex_name"]:
            contract_info += f" (Annex: '{row['annex_name']}')"
        ex_start = row["joining_date"] or "0000-00-00"
        ex_end = row["tentative_leaving_date"] or "Present"
        msg = f"Staff member '{staff_name}' is already allocated to {contract_info} during period ({ex_start} → {ex_end}). Active periods for the same staff member cannot overlap."
        return False, msg

    return True, None


def page_staff_list(q: str, vendor_id: str, contract_id: str, annex_id: str = "", status: str = "active", *, return_to: str):
    q = (q or "").strip()
    vendor_id = (vendor_id or "").strip()
    contract_id = (contract_id or "").strip()
    annex_id = (annex_id or "").strip()
    status = (status or "active").strip().lower()  # active|inactive|all
    if status not in ("active", "inactive", "all"):
        status = "active"

    where = []
    params = []

    if vendor_id.isdigit():
        where.append("s.vendor_id = ?")
        params.append(int(vendor_id))

    if contract_id.isdigit():
        where.append("s.id IN (SELECT staff_id FROM contract_staff_links WHERE contract_id = ?)")
        params.append(int(contract_id))

    if annex_id.isdigit():
        where.append("s.id IN (SELECT staff_id FROM contract_staff_links WHERE annex_id = ?)")
        params.append(int(annex_id))

    if status == "active":
        where.append("(s.status IS NULL OR TRIM(s.status) = '')")
    elif status == "inactive":
        where.append("LOWER(TRIM(IFNULL(s.status,''))) = 'inactive'")

    if q:
        where.append("(s.full_name_vi LIKE ? OR s.position LIKE ? OR p.short_name LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like])

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    conn = db_connect()
    try:
        # Retroactive Auto-Sync: update paid_leave_used_hours based on monthly_attendance_summary
        cur = conn.cursor()
        cur.execute("""
            UPDATE contract_staff
            SET paid_leave_used_hours = COALESCE((
                SELECT SUM(paid_leave_days) * 8.0
                FROM monthly_attendance_summary
                WHERE monthly_attendance_summary.staff_id = contract_staff.id
            ), 0.0)
        """)
        conn.commit()

        vendors = load_vendors_for_staff(conn)
        contracts = load_contracts(conn)
        annexes = load_annexes(conn)

        current_month = datetime.now().strftime("%Y-%m")
        rows = conn.execute(f"""
            SELECT
              s.*,
              COALESCE(v.company_name, v.company_name_vi) AS vendor_name,
              v.tax_id AS vendor_tax,
              c.framework_no,
              a.annex_name,
              latest_link.joining_date AS link_joining_date,
              latest_link.tentative_leaving_date AS link_leaving_date,
              latest_link.monthly_rate,
              latest_link.manday_rate,
              COALESCE(locked_pay.locked_payroll_total, 0.0) AS locked_payroll_total,
              p.id AS assigned_project_id,
              p.short_name AS assigned_project_name,
              latest_psa.max_month AS assigned_project_month
            FROM contract_staff s
            JOIN vendors v ON v.id = s.vendor_id
            LEFT JOIN (
                SELECT staff_id, contract_id, annex_id, monthly_rate, manday_rate, joining_date, tentative_leaving_date
                FROM contract_staff_links l1
                WHERE l1.joining_date = (
                    SELECT MAX(l2.joining_date)
                    FROM contract_staff_links l2
                    WHERE l2.staff_id = l1.staff_id
                )
            ) latest_link ON latest_link.staff_id = s.id
            LEFT JOIN contracts c ON c.id = latest_link.contract_id
            LEFT JOIN contract_annexes a ON a.id = latest_link.annex_id
            LEFT JOIN (
                SELECT staff_id, project_id, MAX(month) AS max_month
                FROM project_staff_assignments
                GROUP BY staff_id
            ) latest_psa ON latest_psa.staff_id = s.id
            LEFT JOIN projects p ON p.id = latest_psa.project_id
            LEFT JOIN (
                SELECT staff_id, SUM(total_amount) AS locked_payroll_total
                FROM monthly_attendance_summary
                WHERE locked = 1
                GROUP BY staff_id
            ) locked_pay ON locked_pay.staff_id = s.id
            {where_sql}
            ORDER BY s.id DESC
            LIMIT ?
        """, params + [LIST_LIMIT]).fetchall()
    finally:
        conn.close()

    vendor_opts = ['<option value="">-- all vendors --</option>']
    for v in vendors:
        sel = "selected" if vendor_id.isdigit() and int(vendor_id) == v["id"] else ""
        vendor_opts.append(f'<option value="{v["id"]}" {sel}>{escape(vendor_label(v))}</option>')

    contract_opts = ['<option value="">-- all contracts --</option>']
    for c in contracts:
        sel = "selected" if contract_id.isdigit() and int(contract_id) == c["id"] else ""
        contract_opts.append(f'<option value="{c["id"]}" data-vendor-id="{c["seller_vendor_id"]}" {sel}>{escape(contract_label(c))}</option>')

    annex_opts = ['<option value="">-- all annexes --</option>']
    for a in annexes:
        sel = "selected" if annex_id.isdigit() and int(annex_id) == a["id"] else ""
        annex_opts.append(f'<option value="{a["id"]}" data-contract-id="{a["contract_id"]}" data-vendor-id="{a["seller_vendor_id"]}" {sel}>{escape(a["annex_name"])}</option>')

    body = f"""
    <div class="card">
      <form class="filters" method="GET" action="/staff">
        <div style="min-width:260px;">
          <div class="label">Search</div>
          <input type="text" name="q" value="{escape(q)}" placeholder="Name / Position / Project" style="width:100%;">
        </div>

        <div style="min-width:280px;">
          <div class="label">Vendor</div>
          <select id="vendor_id" name="vendor_id" style="width:100%;">
            {''.join(vendor_opts)}
          </select>
        </div>

        <div style="min-width:280px;">
          <div class="label">Framework Contract</div>
          <select id="contract_id" name="contract_id" style="width:100%;">
            {''.join(contract_opts)}
          </select>
        </div>

        <div style="min-width:280px;">
          <div class="label">Annex (filtered by Framework)</div>
          <select id="annex_id" name="annex_id" style="width:100%;">
            {''.join(annex_opts)}
          </select>
        </div>

        <div>
          <div class="label">Status</div>
          <select name="status">
            <option value="active" {"selected" if status=="active" else ""}>Active (blank)</option>
            <option value="inactive" {"selected" if status=="inactive" else ""}>Inactive</option>
            <option value="all" {"selected" if status=="all" else ""}>All</option>
          </select>
        </div>

        <div class="actions">
          <button type="submit">Filter</button>
          <a class="muted" href="/staff">Reset</a>
          <a href="/staff/shifts"><button class="btn-secondary" type="button">Ca làm việc (Shifts)</button></a>
          <a href="/projects/assign"><button class="btn-secondary" type="button">Assign to Project</button></a>
          <a href="/staff/new"><button class="btn-secondary" type="button">+ Add Staff</button></a>
        </div>
      </form>
    </div>

    <script>
      (function() {{
        const vendorSel = document.getElementById('vendor_id');
        const contractSel = document.getElementById('contract_id');
        const annexSel = document.getElementById('annex_id');

        function filterContract() {{
          const vId = vendorSel.value;
          const opts = contractSel.querySelectorAll('option');
          let hasSelectedVisible = false;

          opts.forEach((opt) => {{
            const optVendor = opt.getAttribute('data-vendor-id');
            if (!optVendor) {{
              opt.hidden = false; // -- all contracts --
              return;
            }}
            opt.hidden = (vId && optVendor !== vId);
            if (!opt.hidden && opt.selected) {{
              hasSelectedVisible = true;
            }}
          }});

          if (!hasSelectedVisible) {{
            contractSel.value = "";
          }}
          filterAnnex();
        }}

        function filterAnnex() {{
          const vId = vendorSel.value;
          const cId = contractSel.value;
          const opts = annexSel.querySelectorAll('option');
          let hasSelectedVisible = false;

          opts.forEach((opt) => {{
            const optContract = opt.getAttribute('data-contract-id');
            const optVendor = opt.getAttribute('data-vendor-id');
            if (!optContract && !optVendor) {{
              opt.hidden = false; // -- all annexes --
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

        if (vendorSel) vendorSel.addEventListener('change', filterContract);
        if (contractSel) contractSel.addEventListener('change', filterAnnex);
        filterContract();
      }})();
    </script>

    <table>
      <thead>
        <tr>
          <th>No.</th>
          <th>Name (VI)</th>
          <th>Vendor</th>
          <th>Project</th>
          <th>Position</th>
          <th>Framework / Annex</th>
          <th>Joining</th>
          <th>Leaving (tentative)</th>
          <th>Monthly Rate</th>
          <th>Man-day Rate</th>
          <th>Locked Payroll</th>
          <th>Paid leave (total/used)</th>
          <th>OT</th>
          <th>Status</th>
          <th>Action</th>
        </tr>
      </thead>
      <tbody>
    """
    for idx, r in enumerate(rows, 1):
        ot = "Yes" if int(r["ot"] or 0) == 1 else "No"
        st = (r["status"] or "").strip()

        # Build Project column display with active assignment links
        if r["assigned_project_id"]:
            if r["assigned_project_month"] >= current_month:
                project_td = f"""<a href="/projects/assign?project_id={r['assigned_project_id']}&vendor_id={r['vendor_id']}" style="font-weight: 600; color: var(--primary);">{escape(r['assigned_project_name'])}</a>"""
            else:
                project_td = f"""
                <a href="/projects/assign?project_id={r['assigned_project_id']}&vendor_id={r['vendor_id']}" style="font-weight: 600; color: var(--text-muted);">{escape(r['assigned_project_name'])}</a>
                <div class="muted" style="font-size: 10px; margin-top: 2px;">(Last: {escape(r['assigned_project_month'])})</div>
                """
            assign_url = f"/projects/assign?project_id={r['assigned_project_id']}&vendor_id={r['vendor_id']}"
        else:
            project_td = f"""
            <span class="muted" style="font-size:11px;">(Not assigned)</span>
            <div style="margin-top: 2px;">
              <a href="/projects/assign?vendor_id={r['vendor_id']}" class="btn" style="font-size: 10px; padding: 2px 6px;">Assign Project</a>
            </div>
            """
            assign_url = f"/projects/assign?vendor_id={r['vendor_id']}"

        body += f"""
        <tr>
          <td>{idx}</td>
          <td><a href="/staff/edit?id={r["id"]}">{escape(r["full_name_vi"] or "")}</a></td>
          <td>{escape(r["vendor_name"] or "")}<div class="muted">{escape(r["vendor_tax"] or "")}</div></td>
          <td>{project_td}</td>
          <td>{escape(r["position"] or "")}</td>
          <td>{escape(r["framework_no"] or "")}<div class="muted">{escape(r["annex_name"] or "")}</div></td>
          <td>{escape(r["joining_date"] or "")}</td>
          <td>{escape(r["tentative_leaving_date"] or "")}</td>
          <td>{escape("" if r["monthly_rate"] is None else f"{float(r['monthly_rate']):,.2f}")}</td>
          <td>{escape("" if r["manday_rate"] is None else f"{float(r['manday_rate']):,.2f}")}</td>
          <td>{escape(f"{float(r['locked_payroll_total']):,.2f}" if float(r['locked_payroll_total']) > 0 else "-")}</td>
          <td>{escape("" if r["paid_leave_total_hours"] is None else str(r["paid_leave_total_hours"]))}
              /
              {escape("" if r["paid_leave_used_hours"] is None else str(r["paid_leave_used_hours"]))}
          </td>
          <td>{escape(ot)}</td>
          <td>{escape(st)}</td>
          <td>
            <div style="display: flex; flex-direction: column; gap: 4px; align-items: stretch; min-width: 90px;">
              <a href="/staff/edit?id={r["id"]}" style="text-decoration:none; width: 100%;"><button type="button" class="btn-secondary" style="font-size:11px; padding: 4px 8px; width: 100%;">Edit</button></a>
              <a href="{assign_url}" style="text-decoration:none; width: 100%;"><button type="button" class="btn-secondary" style="font-size:11px; padding: 4px 8px; width: 100%;">Assignments</button></a>
            </div>
          </td>
        </tr>
        """

    body += """
      </tbody>
    </table>
    """

    return layout("Contract Staff (HR)", body)


def page_staff_form(mode: str, staff_row, error_msg: str | None = None, return_to: str = "/staff"):
    if mode not in ("new", "edit"):
        mode = "new"

    conn = db_connect()
    try:
        vendors = load_vendors_for_staff(conn)
        
        matrix_projects = []
        active_months = []
        month_to_project = {}
        history_rows = []
        payroll_html = ""
        
        if mode == "edit" and staff_row:
            # 1. Fetch allocated contracts & annexes history
            history_rows = conn.execute("""
                SELECT l.id, l.monthly_rate, l.manday_rate, l.joining_date, l.tentative_leaving_date,
                       c.framework_no, c.framework_name, a.annex_name
                FROM contract_staff_links l
                JOIN contracts c ON c.id = l.contract_id
                LEFT JOIN contract_annexes a ON a.id = l.annex_id
                WHERE l.staff_id = ?
                ORDER BY l.joining_date DESC
            """, (staff_row["id"],)).fetchall()

            # 2. Get active months range from the contract staff links to draw Project Matrix
            # Find the min joining_date and max tentative_leaving_date across all links
            min_jd = None
            max_ld = None
            for h in history_rows:
                if h["joining_date"]:
                    if min_jd is None or h["joining_date"] < min_jd:
                        min_jd = h["joining_date"]
                if h["tentative_leaving_date"]:
                    if max_ld is None or h["tentative_leaving_date"] > max_ld:
                        max_ld = h["tentative_leaving_date"]

            if min_jd:
                from datetime import datetime, timedelta
                try:
                    start_dt = datetime.strptime(min_jd[:7], "%Y-%m")
                except Exception:
                    start_dt = None
                
                if start_dt:
                    if max_ld:
                        try:
                            end_dt = datetime.strptime(max_ld[:7], "%Y-%m")
                        except Exception:
                            end_dt = start_dt + timedelta(days=365)
                    else:
                        now = datetime.now()
                        end_dt = datetime(now.year, now.month, 1) + timedelta(days=180)
                    
                    # Generate list of months (max 24)
                    curr = datetime(start_dt.year, start_dt.month, 1)
                    limit = datetime(end_dt.year, end_dt.month, 1)
                    count = 0
                    while curr <= limit and count < 24:
                        active_months.append(curr.strftime("%Y-%m"))
                        if curr.month == 12:
                            curr = datetime(curr.year + 1, 1, 1)
                        else:
                            curr = datetime(curr.year, curr.month + 1, 1)
                        count += 1

            # 3. Get ONLY projects (both active and closed) that this staff is or was assigned to
            assigned_projects_rows = conn.execute("""
                SELECT DISTINCT p.id, p.short_name, p.full_name, p.is_active
                FROM project_staff_assignments a
                JOIN projects p ON p.id = a.project_id
                WHERE a.staff_id = ?
                ORDER BY p.is_active DESC, p.short_name ASC
            """, (staff_row["id"],)).fetchall()
            matrix_projects = [dict(p) for p in assigned_projects_rows]
            
            # 4. Get all assignments of this staff
            assign_rows = conn.execute("""
                SELECT a.project_id, a.month, p.short_name AS project_name
                FROM project_staff_assignments a
                JOIN projects p ON p.id = a.project_id
                WHERE a.staff_id = ?
            """, (staff_row["id"],)).fetchall()
            month_to_project = {r["month"]: (r["project_id"], r["project_name"]) for r in assign_rows}

            # 5. Fetch monthly payroll summary and group by project and month
            summaries_rows = conn.execute("""
                SELECT month, total_amount
                FROM monthly_attendance_summary
                WHERE staff_id = ?
            """, (staff_row["id"],)).fetchall()
            summaries_map = {r["month"]: r["total_amount"] for r in summaries_rows}

            all_months = list(active_months)
            for m in summaries_map.keys():
                if m not in all_months:
                    all_months.append(m)
            all_months.sort()

            projects_in_scope = {}
            for r in assign_rows:
                projects_in_scope[r["project_id"]] = r["project_name"]

            grid_data = {}
            row_names = {}
            for p_id, p_name in projects_in_scope.items():
                grid_data[p_id] = {m: 0.0 for m in all_months}
                row_names[p_id] = f"Project: {p_name}"

            has_unassigned = False
            for m in all_months:
                if m not in month_to_project and summaries_map.get(m, 0.0) > 0:
                    has_unassigned = True
                    break

            if has_unassigned:
                grid_data["unassigned"] = {m: 0.0 for m in all_months}
                row_names["unassigned"] = "No Project (Unassigned)"

            for m in all_months:
                amt = summaries_map.get(m, 0.0)
                if amt == 0.0:
                    continue
                if m in month_to_project:
                    p_id, _ = month_to_project[m]
                    if p_id in grid_data:
                        grid_data[p_id][m] = amt
                else:
                    if "unassigned" in grid_data:
                        grid_data["unassigned"][m] = amt

            if all_months and grid_data:
                col_totals = {m: 0.0 for m in all_months}
                grand_total = 0.0
                
                th_elements = "".join(f'<th style="text-align:right; font-size:12px; width:90px; padding:10px 8px; color:var(--text-muted);">{m}</th>' for m in all_months)
                
                trs = []
                sorted_keys = sorted(grid_data.keys(), key=lambda k: row_names[k])
                for key in sorted_keys:
                    name = row_names[key]
                    amounts = grid_data[key]
                    row_total = sum(amounts.values())
                    grand_total += row_total
                    
                    td_elements = []
                    for m in all_months:
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
                for m in all_months:
                    val = col_totals[m]
                    val_str = f"{int(round(val)):,}" if val > 0 else "0"
                    footer_tds.append(f"<td style='text-align:right; padding:10px 8px; font-weight:bold;'>{val_str}</td>")
                    
                grand_total_str = f"{int(round(grand_total)):,}"
                
                payroll_html = f"""
                <div class="card" style="margin-top: 24px; padding:0; overflow-x:auto;">
                  <div style="padding: 16px 20px; border-bottom: 1px solid var(--border); background: #f8fafc;">
                    <h3 style="margin: 0; color: var(--text-primary); font-size:16px;">Payroll Report by Project</h3>
                    <p style="margin: 4px 0 0 0; font-size: 12px; color: var(--text-muted);">
                      Summary of monthly payments received by this employee, grouped by project.
                    </p>
                  </div>
                  <table style="width:100%; border-collapse:collapse; margin:0; border:none; min-width:600px;">
                    <thead>
                      <tr style="background:#f8fafc; border-bottom:1px solid var(--border);">
                        <th style="text-align:left; padding:10px 8px; font-size:12px; color:var(--text-muted); width:150px;">Project</th>
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
                payroll_html = f"""
                <div class="card" style="margin-top: 24px; padding:0; overflow-x:auto;">
                  <div style="padding: 16px 20px; border-bottom: 1px solid var(--border); background: #f8fafc;">
                    <h3 style="margin: 0; color: var(--text-primary); font-size:16px;">Payroll Report by Project</h3>
                    <p style="margin: 4px 0 0 0; font-size: 12px; color: var(--text-muted);">
                      Summary of monthly payments received by this employee, grouped by project.
                    </p>
                  </div>
                  <div style="text-align: center; padding: 20px; color: var(--text-muted);">
                    No payroll or project assignment data found for this employee.
                  </div>
                </div>
                """
    finally:
        conn.close()

    def gv(key):
        if staff_row is None:
            return ""
        x = staff_row[key]
        return "" if x is None else str(x)

    title = "Add Staff" if mode == "new" else f"Edit Staff #{staff_row['id']}"
    action = "/staff/create" if mode == "new" else "/staff/update"
    hidden_id = f'<input type="hidden" name="id" value="{staff_row["id"]}">' if mode == "edit" else ""
    hidden_return = f'<input type="hidden" name="return_to" value="{escape(return_to)}">'

    error_html = f'<div class="card danger"><b>Error:</b> {escape(error_msg)}</div>' if error_msg else ""

    tot_pl_val = to_float_or_none(gv("paid_leave_total_hours")) or 0.0
    used_pl_val = to_float_or_none(gv("paid_leave_used_hours")) or 0.0
    rem_pl_val = max(0.0, tot_pl_val - used_pl_val)
    rem_days_val = rem_pl_val / 8.0

    joining_date_val = gv("joining_date")
    tentative_leaving_date_val = gv("tentative_leaving_date")
    date_attrs = ""
    date_note = ""

    vendor_selected = gv("vendor_id")
    vendor_opts = ['<option value="">-- select vendor --</option>']
    for v in vendors:
        sel = "selected" if vendor_selected and str(v["id"]) == vendor_selected else ""
        vendor_opts.append(f'<option value="{v["id"]}" {sel}>{escape(vendor_label(v))}</option>')

    ot_val = gv("ot")
    ot_val = "1" if str(ot_val) == "1" else "0"

    status_val = (gv("status") or "").strip().lower()
    status_opts = f"""
      <option value="" {"selected" if status_val=="" else ""}>(blank / active)</option>
      <option value="inactive" {"selected" if status_val=="inactive" else ""}>inactive</option>
    """

    work_shift_val = gv("work_shift")
    work_shift_opts = f"""
      <option value="" {"selected" if not work_shift_val else ""}>-- Not configured --</option>
      <option value="8:00 - 17:00" {"selected" if work_shift_val=="8:00 - 17:00" else ""}>8:00 - 17:00</option>
      <option value="8:30 - 17:30" {"selected" if work_shift_val=="8:30 - 17:30" else ""}>8:30 - 17:30</option>
    """
    body_fields_html = f"""
          <div>
            <div class="label">Paid leave (hour) - Total</div>
            <input type="text" name="paid_leave_total_hours" value="{escape(gv("paid_leave_total_hours"))}" style="width:100%; background:#f1f5f9;" readonly>
          </div>

          <div>
            <div class="label">Paid leave (hour) - Actual used</div>
            <input type="text" name="paid_leave_used_hours" value="{escape(gv("paid_leave_used_hours"))}" style="width:100%; background:#f1f5f9;" readonly>
          </div>

          <div>
            <div class="label">Paid leave (hour) - Remaining</div>
            <input type="text" value="{rem_pl_val:.1f} hrs ({rem_days_val:.2f} days)" style="width:100%; background:#e6f4ea; color:#137333; font-weight:bold;" readonly>
          </div>
    """

    assigned_projects_html = ""
    if mode == "edit" and active_months:
        th_months = "".join(f'<th style="text-align:center; font-size:12px; width:90px; padding:10px 8px; color:var(--text-muted);">{m}</th>' for m in active_months)
        
        trs = []
        for p in matrix_projects:
            p_id = p["id"]
            is_p_active = int(p["is_active"] or 0) == 1
            
            tds = []
            for m in active_months:
                assigned_info = month_to_project.get(m)
                
                if not is_p_active:
                    # Closed Project
                    if assigned_info and assigned_info[0] == p_id:
                        tds.append('<td style="text-align:center; background:#f1f5f9; color:#475569; font-size:14px; font-weight:bold;">✓</td>')
                    else:
                        tds.append('<td style="text-align:center; background:#fafafa;"></td>')
                else:
                    # Active Project
                    if assigned_info:
                        assigned_pid, assigned_pname = assigned_info
                        if assigned_pid == p_id:
                            tds.append(f"""
                            <td style="text-align: center; background: #ecfdf5; border-color: #bbf7d0;">
                              <input type="checkbox" 
                                     class="assign-matrix-cb" 
                                     data-staff-id="{staff_row['id']}" 
                                     data-project-id="{p_id}" 
                                     data-month="{m}" 
                                     checked
                                     style="width: 18px; height: 18px; cursor: pointer; margin: 0;">
                            </td>
                            """)
                        else:
                            tds.append(f"""
                            <td style="text-align: center; background: #fff1f2; color: #b91c1c; font-size: 11px; font-weight: 500;" title="Assigned to {escape(assigned_pname)}">
                              {escape(assigned_pname)}
                            </td>
                            """)
                    else:
                        tds.append(f"""
                        <td style="text-align: center;">
                          <input type="checkbox" 
                                 class="assign-matrix-cb" 
                                 data-staff-id="{staff_row['id']}" 
                                 data-project-id="{p_id}" 
                                 data-month="{m}" 
                                 style="width: 18px; height: 18px; cursor: pointer; margin: 0;">
                        </td>
                        """)
            
            p_label = f"{escape(p['short_name'])}"
            if not is_p_active:
                p_label += " <span class='muted' style='font-size:11px;'>(Closed)</span>"
                
            tds_str = "".join(tds)
            trs.append(f"""
            <tr style="border-bottom:1px solid var(--border);">
              <td style="padding:10px 8px; font-weight:600; color:var(--primary);">{p_label}</td>
              <td style="padding:10px 8px;"><div class="muted" style="font-size:11.5px; max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{escape(p['full_name'])}</div></td>
              {tds_str}
            </tr>
            """)
            
        assigned_projects_html = f"""
        <div class="card" style="margin-top: 24px; padding:0; overflow-x:auto;">
          <div style="padding: 16px 20px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; background: #f8fafc;">
            <div>
              <h3 style="margin: 0; color: var(--text-primary); font-size:16px;">Project Assignments Matrix</h3>
              <p style="margin: 4px 0 0 0; font-size: 12px; color: var(--text-muted);">
                Manage monthly staff project assignments. Each employee can only be assigned to a maximum of 1 project per month.
              </p>
            </div>
          </div>
          <table style="width:100%; border-collapse:collapse; margin:0; border:none; min-width:600px;">
            <thead>
              <tr style="background:#f8fafc; border-bottom:1px solid var(--border);">
                <th style="text-align:left; padding:10px 8px; font-size:12px; color:var(--text-muted); width:120px;">Short Name</th>
                <th style="text-align:left; padding:10px 8px; font-size:12px; color:var(--text-muted); width:180px;">Full Name</th>
                {th_months}
              </tr>
            </thead>
            <tbody>
              {"".join(trs) if trs else '<tr><td colspan="3" style="text-align:center; padding:20px; color:var(--text-muted);">No projects configured.</td></tr>'}
            </tbody>
          </table>
        </div>
        """

    history_html = ""
    if mode == "edit" and history_rows:
        history_trs = []
        for h_row in history_rows:
            annex_lbl = f"<div class='muted' style='font-size:11px;'>Annex: {escape(h_row['annex_name'] or '')}</div>" if h_row['annex_name'] else "<span class='muted'>-</span>"
            m_rate = f"{h_row['monthly_rate']:,.2f} VND" if h_row['monthly_rate'] is not None else "-"
            d_rate = f"{h_row['manday_rate']:,.2f} VND" if h_row['manday_rate'] is not None else "-"
            history_trs.append(f"""
            <tr style="border-bottom:1px solid var(--border);">
              <td style="padding:10px 8px;"><b>{escape(h_row['framework_no'] or '')}</b><div class='muted' style='font-size:11px;'>{escape(h_row['framework_name'] or '')}</div></td>
              <td style="padding:10px 8px;">{annex_lbl}</td>
              <td style="padding:10px 8px;">{escape(h_row['joining_date'] or '')} → {escape(h_row['tentative_leaving_date'] or 'Present')}</td>
              <td style="text-align:right; padding:10px 8px;">{m_rate}</td>
              <td style="text-align:right; padding:10px 8px;">{d_rate}</td>
            </tr>
            """)
            
        history_html = f"""
        <div class="card" style="margin-top: 24px; padding:0; overflow-x:auto;">
          <div style="padding: 16px 20px; border-bottom: 1px solid var(--border); background: #f8fafc;">
            <h3 style="margin: 0; color: var(--text-primary); font-size:16px;">Contract & Annex Allocations History</h3>
            <p style="margin: 4px 0 0 0; font-size: 12px; color: var(--text-muted);">
              Staff allocation history for contracts and annexes. To change this allocation, please visit the detail page of the corresponding contract or annex.
            </p>
          </div>
          <table style="width:100%; border-collapse:collapse; margin:0; border:none;">
            <thead>
              <tr style="background:#f8fafc; border-bottom:1px solid var(--border);">
                <th style="text-align:left; padding:10px 8px; font-size:12px; color:var(--text-muted);">Contract</th>
                <th style="text-align:left; padding:10px 8px; font-size:12px; color:var(--text-muted);">Annex</th>
                <th style="text-align:left; padding:10px 8px; font-size:12px; color:var(--text-muted);">Active Period</th>
                <th style="text-align:right; padding:10px 8px; font-size:12px; color:var(--text-muted);">Monthly Rate</th>
                <th style="text-align:right; padding:10px 8px; font-size:12px; color:var(--text-muted);">Man-day Rate</th>
              </tr>
            </thead>
            <tbody>
              {"".join(history_trs) if history_trs else '<tr><td colspan="5" style="text-align:center; padding:20px; color:var(--text-muted);">Not assigned to any contract yet.</td></tr>'}
            </tbody>
          </table>
        </div>
        """

    body = f"""
    {error_html}

    <div class="card">
      <div class="actions" style="margin-bottom:10px;">
        <a href="/staff">← Staff list</a>
      </div>

      <form method="POST" action="{action}">
        {hidden_id}
        {hidden_return}

        <div class="grid">
          <div>
            <div class="label">Name (fullname VI)</div>
            <input type="text" name="full_name_vi" value="{escape(gv("full_name_vi"))}" style="width:100%;">
          </div>

          <div>
            <div class="label">Vendor (purchasing=0)</div>
            <select id="vendor_id" name="vendor_id" style="width:100%;">
              {''.join(vendor_opts)}
            </select>
          </div>

          <div>
            <div class="label">Position</div>
            <input type="text" name="position" value="{escape(gv("position"))}" style="width:100%;">
          </div>

          <div>
            <div class="label">Start date (Latest allocation){date_note}</div>
            <input type="date" name="joining_date" value="{escape(joining_date_val)}" style="width:100%;" {date_attrs}>
          </div>

          <div>
            <div class="label">Tentative date (Latest allocation){date_note}</div>
            <input type="date" name="tentative_leaving_date" value="{escape(tentative_leaving_date_val)}" style="width:100%;" {date_attrs}>
          </div>

{body_fields_html}

          <div>
            <div class="label">OT</div>
            <select name="ot" style="width:100%;">
              <option value="0" {"selected" if ot_val=="0" else ""}>No</option>
              <option value="1" {"selected" if ot_val=="1" else ""}>Yes</option>
            </select>
          </div>

          <div>
            <div class="label">Work Shift</div>
            <select name="work_shift" style="width:100%;">
              {work_shift_opts}
            </select>
          </div>

          <div>
            <div class="label">Status</div>
            <select name="status" style="width:100%;">
              {status_opts}
            </select>
          </div>
        </div>

        <div class="actions" style="margin-top:14px;">
          <button type="submit">Save</button>
          <a class="muted" href="{escape(return_to)}">Cancel</a>
        </div>
      </form>
    </div>
    {history_html}
    {assigned_projects_html}
    {payroll_html}

    <script>
      (function() {{
        // Attach change listener to staff edit page matrix checkboxes
        document.querySelectorAll('.assign-matrix-cb').forEach(cb => {{
          cb.addEventListener('change', function() {{
            const staffId = this.getAttribute('data-staff-id');
            const projectId = this.getAttribute('data-project-id');
            const month = this.getAttribute('data-month');
            const assign = this.checked ? 1 : 0;
            
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
                window.location.reload();
              }} else {{
                alert(data.message || 'Failed to update assignment.');
                this.checked = !this.checked; // revert
                cell.style.background = originalBackground;
              }}
            }})
            .catch(err => {{
              this.disabled = originalDisabled;
              alert('Connection error: ' + err);
              this.checked = !this.checked; // revert
              cell.style.background = originalBackground;
            }});
          }});
        }});
      }})();
    </script>
    """
    return layout(title, body)
def handle_staff_create_post(handler):
    form = read_post_form(handler)

    full_name_vi = (form.get("full_name_vi", [""])[0] or "").strip()
    vendor_id = (form.get("vendor_id", [""])[0] or "").strip()
    position = (form.get("position", [""])[0] or "").strip() or None

    pl_total = to_float_or_none(form.get("paid_leave_total_hours", [""])[0])
    pl_used = to_float_or_none(form.get("paid_leave_used_hours", [""])[0])

    ot = (form.get("ot", ["0"])[0] or "0").strip()
    ot = 1 if ot == "1" else 0

    status = (form.get("status", [""])[0] or "").strip()
    status = status if status else None

    work_shift = (form.get("work_shift", [""])[0] or "").strip() or None
    joining_date = (form.get("joining_date", [""])[0] or "").strip() or None
    tentative_leaving_date = (form.get("tentative_leaving_date", [""])[0] or "").strip() or None
    return_to = (form.get("return_to", ["/staff"])[0] or "").strip() or "/staff"

    # validation
    if not full_name_vi:
        send_html(handler, layout("Error", "<div class='card danger'>Name (VI) is required</div>"), status=400)
        return
    if not vendor_id.isdigit():
        send_html(handler, layout("Error", "<div class='card danger'>Vendor is required</div>"), status=400)
        return

    conn = db_connect()
    try:
        cur = conn.cursor()

        # vendor must be active + purchasing=0
        v_ok = cur.execute("""
            SELECT 1 FROM vendors WHERE id=? AND is_active=1 AND purchasing=0
        """, (int(vendor_id),)).fetchone()
        if not v_ok:
            send_html(handler, layout("Error", "<div class='card danger'>Vendor not found/deactivated or not purchasing=0</div>"), status=400)
            return

        cur.execute("""
            INSERT INTO contract_staff (
                full_name_vi, vendor_id, position,
                joining_date, tentative_leaving_date,
                paid_leave_total_hours, paid_leave_used_hours,
                ot, status, work_shift,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            full_name_vi, int(vendor_id), position,
            joining_date, tentative_leaving_date,
            pl_total, pl_used,
            ot, status, work_shift,
            now_iso(), now_iso()
        ))
        new_id = cur.lastrowid
        # Get vendor short name for log
        v_row = cur.execute("SELECT short_name FROM vendors WHERE id=?", (int(vendor_id),)).fetchone()
        v_name = v_row["short_name"] if v_row else f"Vendor ID {vendor_id}"
        log_action(cur, "CREATE_STAFF", "contract_staff", new_id, f"Added new staff member '{full_name_vi}' belonging to vendor '{v_name}'")
        conn.commit()
    finally:
        conn.close()

    redirect(handler, return_to)


def handle_staff_update_post(handler):
    form = read_post_form(handler)
    sid = (form.get("id", [""])[0] or "").strip()
    if not sid.isdigit():
        send_html(handler, layout("Error", "<div class='card danger'>Invalid staff id</div>"), status=400)
        return

    full_name_vi = (form.get("full_name_vi", [""])[0] or "").strip()
    vendor_id = (form.get("vendor_id", [""])[0] or "").strip()
    position = (form.get("position", [""])[0] or "").strip() or None

    pl_total = to_float_or_none(form.get("paid_leave_total_hours", [""])[0])
    pl_used = to_float_or_none(form.get("paid_leave_used_hours", [""])[0])

    ot = (form.get("ot", ["0"])[0] or "0").strip()
    ot = 1 if ot == "1" else 0

    status = (form.get("status", [""])[0] or "").strip()
    status = status if status else None

    work_shift = (form.get("work_shift", [""])[0] or "").strip() or None
    joining_date = (form.get("joining_date", [""])[0] or "").strip() or None
    tentative_leaving_date = (form.get("tentative_leaving_date", [""])[0] or "").strip() or None
    return_to = (form.get("return_to", ["/staff"])[0] or "").strip() or "/staff"

    if not full_name_vi:
        send_html(handler, layout("Error", "<div class='card danger'>Name (VI) is required</div>"), status=400)
        return
    if not vendor_id.isdigit():
        send_html(handler, layout("Error", "<div class='card danger'>Vendor is required</div>"), status=400)
        return

    conn = db_connect()
    try:
        cur = conn.cursor()

        existing_staff = cur.execute("SELECT id, paid_leave_total_hours, paid_leave_used_hours FROM contract_staff WHERE id=?", (int(sid),)).fetchone()
        if not existing_staff:
            send_html(handler, layout("Not found", "<div class='card'>Staff not found</div>"), status=404)
            return
        if pl_total is None:
            pl_total = existing_staff["paid_leave_total_hours"]
        if pl_used is None:
            pl_used = existing_staff["paid_leave_used_hours"]

        v_ok = cur.execute("""
            SELECT 1 FROM vendors WHERE id=? AND is_active=1 AND purchasing=0
        """, (int(vendor_id),)).fetchone()
        if not v_ok:
            send_html(handler, layout("Error", "<div class='card danger'>Vendor not found or inactive</div>"), status=400)
            return

        cur.execute("""
            UPDATE contract_staff
            SET full_name_vi=?,
                vendor_id=?,
                position=?,
                joining_date=?,
                tentative_leaving_date=?,
                paid_leave_total_hours=?,
                paid_leave_used_hours=?,
                ot=?,
                status=?,
                work_shift=?,
                updated_at=?
            WHERE id=?
        """, (
            full_name_vi,
            int(vendor_id),
            position,
            joining_date,
            tentative_leaving_date,
            pl_total,
            pl_used,
            ot,
            status,
            work_shift,
            now_iso(),
            int(sid)
        ))
        log_action(cur, "UPDATE_STAFF", "contract_staff", int(sid), f"Updated staff info for '{full_name_vi}'")

        conn.commit()
    finally:
        conn.close()

    redirect(handler, return_to)


def page_staff_shifts():
    conn = db_connect()
    try:
        current_month = datetime.now().strftime("%Y-%m")
        rows = conn.execute("""
            SELECT s.id, s.full_name_vi, s.position, s.ot, s.work_shift,
                   COALESCE(v.company_name, v.company_name_vi) AS vendor_name,
                   c.framework_no AS contract_no,
                   p.short_name AS assigned_project_name,
                   latest_psa.max_month AS assigned_project_month,
                   p.id AS assigned_project_id
            FROM contract_staff s
            JOIN vendors v ON v.id=s.vendor_id
            LEFT JOIN (
                SELECT staff_id, contract_id
                FROM contract_staff_links l1
                WHERE l1.joining_date = (
                    SELECT MAX(l2.joining_date)
                    FROM contract_staff_links l2
                    WHERE l2.staff_id = l1.staff_id
                )
            ) latest_link ON latest_link.staff_id = s.id
            LEFT JOIN contracts c ON c.id=latest_link.contract_id
            LEFT JOIN (
                SELECT staff_id, project_id, MAX(month) AS max_month
                FROM project_staff_assignments
                GROUP BY staff_id
            ) latest_psa ON latest_psa.staff_id = s.id
            LEFT JOIN projects p ON p.id = latest_psa.project_id
            WHERE s.status IS NULL OR s.status <> 'inactive'
            ORDER BY s.id DESC
        """).fetchall()
    finally:
        conn.close()

    trs = []
    for idx, r in enumerate(rows, 1):
        ot_label = '<b style="color: green;">Yes (1)</b>' if r["ot"] == 1 else 'No (0)'
        
        shift_val = r["work_shift"] or ""
        if shift_val:
            shift_display = f"<b>{escape(shift_val)}</b>"
            shift_class = ""
        else:
            if r["ot"] == 1:
                shift_display = '<b style="color: #b00020;">Not configured (Required for OT calculations)</b>'
                shift_class = "cell-mismatch"
            else:
                shift_display = '<span class="muted">Not configured</span>'
                shift_class = ""

        edit_link = f'<a href="/staff/edit?id={r["id"]}&return_to=/staff/shifts" style="text-decoration:none;"><button type="button" class="btn-secondary" style="font-size:11px; padding: 4px 8px; margin-top:2px;">Edit shift</button></a>'

        trs.append(f"""
        <tr>
          <td>{idx}</td>
          <td><b>{escape(r["full_name_vi"])}</b></td>
          <td>{escape(r["vendor_name"] or "")}</td>
          <td>
            {f'<b style="color: var(--primary);">{escape(r["assigned_project_name"])}</b>' if r["assigned_project_id"] and r["assigned_project_month"] >= current_month else f'<span style="font-weight: 600; color: var(--text-muted);">{escape(r["assigned_project_name"])}</span><span class="muted" style="font-size: 10px; display: block; margin-top: 2px;">(Last: {escape(r["assigned_project_month"])})</span>' if r["assigned_project_id"] else '<span class="muted" style="font-size: 11px;">(Not assigned)</span>'}
            <div class="muted" style="margin-top:2px;">{escape(r["position"] or "")}</div>
          </td>
          <td>{ot_label}</td>
          <td class="{shift_class}">{shift_display}</td>
          <td>
            <div class="actions" style="gap:6px; flex-wrap:nowrap; display:flex; align-items:center;">
              {edit_link}
            </div>
          </td>
        </tr>
        """)

    body = f"""
    <div class="card">
      <div class="actions" style="margin-bottom:14px;">
        <a href="/staff">← Staff List</a>
      </div>

      <div class="muted" style="margin-bottom:12px;">
        Below is the list of all active contract staff at the bank.
        Each staff member should be assigned a work shift (<strong>8:00 - 17:00</strong> or <strong>8:30 - 17:30</strong>).
        For staff with <strong>OT = Yes</strong>, the work shift is required as a baseline for overtime (OT) calculations.
      </div>

      <table>
        <thead>
          <tr>
            <th>No.</th>
            <th>Full Name</th>
            <th>Vendor</th>
            <th>Project / Position</th>
            <th>OT?</th>
            <th>Work Shift</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          {''.join(trs) if trs else '<tr><td colspan="7" class="muted">No active staff found</td></tr>'}
        </tbody>
      </table>
    </div>
    """
    return layout("Staff Work Shifts Settings", body)