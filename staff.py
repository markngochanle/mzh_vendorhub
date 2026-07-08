# staff.py
from html import escape

from common import (
    db_connect, layout, LIST_LIMIT, now_iso,
    read_post_form, redirect, send_html
)


def to_float_or_none(s: str | None):
    if s is None:
        return None
    s = s.strip()
    if s == "":
        return None
    s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


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
        SELECT id, contract_id, annex_name, start_date, end_date
        FROM contract_annexes
        WHERE is_active=1
        ORDER BY contract_id DESC, id DESC
    """).fetchall()


def vendor_label(r):
    name = (r["company_name"] or r["company_name_vi"] or "").strip()
    tax = (r["tax_id"] or "").strip()
    return f"{name} ({tax})" if tax else name


def contract_label(r):
    no = (r["framework_no"] or "").strip()
    nm = (r["framework_name"] or "").strip()
    label = no if no else f"Contract#{r['id']}"
    if nm:
        label += f" | {nm}"
    return label


def check_no_overlap(conn, staff_id_exclude, vendor_id: int, full_name_vi: str,
                     joining_date: str, leaving_date: str | None):
    """
    Enforce no-overlap for same (vendor_id + full_name_vi).

    Range:
      start = joining_date (required)
      end   = leaving_date or '9999-12-31'

    Overlap condition:
      existing_start <= new_end AND new_start <= existing_end
    """
    new_start = joining_date
    new_end = leaving_date or "9999-12-31"

    # Params for SQL below
    params = [vendor_id, full_name_vi.strip()]

    exclude_sql = ""
    if staff_id_exclude is not None:
        exclude_sql = "AND id <> ?"
        params.append(int(staff_id_exclude))

    params.extend([new_end, new_start])

    sql = f"""
        SELECT id, joining_date, tentative_leaving_date, contract_id, annex_id
        FROM contract_staff
        WHERE vendor_id = ?
          AND LOWER(TRIM(full_name_vi)) = LOWER(TRIM(?))
          {exclude_sql}
          AND COALESCE(tentative_leaving_date, '9999-12-31') >= ?
          AND COALESCE(joining_date, '0001-01-01') <= ?
        LIMIT 1
    """

    row = conn.execute(sql, params).fetchone()
    if row:
        ex_end = row["tentative_leaving_date"] or "9999-12-31"
        msg = (
            f"Overlap with staff_id={row['id']} "
            f"(existing {row['joining_date']} → {ex_end}), "
            f"contract_id={row['contract_id']}, annex_id={row['annex_id']}"
        )
        return False, msg

    return True, None


def page_staff_list(q: str, vendor_id: str, contract_id: str, status: str, *, return_to: str):
    q = (q or "").strip()
    vendor_id = (vendor_id or "").strip()
    contract_id = (contract_id or "").strip()
    status = (status or "active").strip().lower()  # active|inactive|all
    if status not in ("active", "inactive", "all"):
        status = "active"

    where = []
    params = []

    if vendor_id.isdigit():
        where.append("s.vendor_id = ?")
        params.append(int(vendor_id))

    if contract_id.isdigit():
        where.append("s.contract_id = ?")
        params.append(int(contract_id))

    if status == "active":
        where.append("(s.status IS NULL OR TRIM(s.status) = '')")
    elif status == "inactive":
        where.append("LOWER(TRIM(IFNULL(s.status,''))) = 'inactive'")

    if q:
        where.append("(s.full_name_vi LIKE ? OR s.position LIKE ? OR s.project_name LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like])

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    conn = db_connect()
    try:
        vendors = load_vendors_for_staff(conn)
        contracts = load_contracts(conn)

        rows = conn.execute(f"""
            SELECT
              s.*,
              COALESCE(v.company_name, v.company_name_vi) AS vendor_name,
              v.tax_id AS vendor_tax,
              c.framework_no,
              a.annex_name
            FROM contract_staff s
            JOIN vendors v ON v.id = s.vendor_id
            JOIN contracts c ON c.id = s.contract_id
            LEFT JOIN contract_annexes a ON a.id = s.annex_id
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
          <a href="/staff/new"><button class="btn-secondary" type="button">+ Add Staff</button></a>
        </div>
      </form>
    </div>

    <script>
      (function() {{
        const vendorSel = document.getElementById('vendor_id');
        const contractSel = document.getElementById('contract_id');
        if (vendorSel && contractSel) {{
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
          }}

          vendorSel.addEventListener('change', filterContract);
          filterContract();
        }}
      }})();
    </script>

    <table>
      <thead>
        <tr>
          <th>ID</th>
          <th>Name (VI)</th>
          <th>Vendor</th>
          <th>Project</th>
          <th>Position</th>
          <th>Framework / Annex</th>
          <th>Joining</th>
          <th>Leaving (tentative)</th>
          <th>Monthly Rate</th>
          <th>Man-day Rate</th>
          <th>Paid leave (total/used)</th>
          <th>OT</th>
          <th>Status</th>
          <th>Action</th>
        </tr>
      </thead>
      <tbody>
    """
    for r in rows:
        ot = "Yes" if int(r["ot"] or 0) == 1 else "No"
        st = (r["status"] or "").strip()

        body += f"""
        <tr>
          <td>{r["id"]}</td>
          <td><a href="/staff/edit?id={r["id"]}">{escape(r["full_name_vi"] or "")}</a></td>
          <td>{escape(r["vendor_name"] or "")}<div class="muted">{escape(r["vendor_tax"] or "")}</div></td>
          <td>{escape(r["project_name"] or "")}</td>
          <td>{escape(r["position"] or "")}</td>
          <td>{escape(r["framework_no"] or "")}<div class="muted">{escape(r["annex_name"] or "")}</div></td>
          <td>{escape(r["joining_date"] or "")}</td>
          <td>{escape(r["tentative_leaving_date"] or "")}</td>
          <td>{escape("" if r["monthly_rate"] is None else f"{float(r['monthly_rate']):,.2f}")}</td>
          <td>{escape("" if r["manday_rate"] is None else f"{float(r['manday_rate']):,.2f}")}</td>
          <td>{escape("" if r["paid_leave_total_hours"] is None else str(r["paid_leave_total_hours"]))}
              /
              {escape("" if r["paid_leave_used_hours"] is None else str(r["paid_leave_used_hours"]))}
          </td>
          <td>{escape(ot)}</td>
          <td>{escape(st)}</td>
          <td><a href="/staff/edit?id={r["id"]}" style="text-decoration:none;"><button type="button" class="btn-secondary" style="font-size:11px; padding: 4px 8px; margin-top:2px;">Edit</button></a></td>
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
        contracts = load_contracts(conn)
        annexes = load_annexes(conn)
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

    vendor_selected = gv("vendor_id")
    contract_selected = gv("contract_id")
    annex_selected = gv("annex_id")

    vendor_opts = ['<option value="">-- select vendor --</option>']
    for v in vendors:
        sel = "selected" if vendor_selected and str(v["id"]) == vendor_selected else ""
        vendor_opts.append(f'<option value="{v["id"]}" {sel}>{escape(vendor_label(v))}</option>')

    contract_opts = ['<option value="">-- select framework contract --</option>']
    for c in contracts:
        sel = "selected" if contract_selected and str(c["id"]) == contract_selected else ""
        contract_opts.append(f'<option value="{c["id"]}" data-vendor-id="{c["seller_vendor_id"]}" {sel}>{escape(contract_label(c))}</option>')

    annex_opts = ['<option value="">(none)</option>']
    for a in annexes:
        sel = "selected" if annex_selected and str(a["id"]) == annex_selected else ""
        label = (a["annex_name"] or f"Annex#{a['id']}").strip()
        period = ""
        if (a["start_date"] or "") or (a["end_date"] or ""):
            period = f" ({a['start_date'] or ''}→{a['end_date'] or ''})"
        annex_opts.append(
            f'<option value="{a["id"]}" data-contract-id="{a["contract_id"]}" {sel}>{escape(label + period)}</option>'
        )

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
            <div class="label">Project (free text)</div>
            <input type="text" name="project_name" value="{escape(gv("project_name"))}" style="width:100%;">
          </div>

          <div>
            <div class="label">Position</div>
            <input type="text" name="position" value="{escape(gv("position"))}" style="width:100%;">
          </div>

          <div>
            <div class="label">Joining (required)</div>
            <input type="date" name="joining_date" value="{escape(gv("joining_date"))}" style="width:100%;">
          </div>

          <div>
            <div class="label">Tentative Leaving Date</div>
            <input type="date" name="tentative_leaving_date" value="{escape(gv("tentative_leaving_date"))}" style="width:100%;">
          </div>

          <div>
            <div class="label">Framework Contract</div>
            <select id="contract_id" name="contract_id" style="width:100%;">
              {''.join(contract_opts)}
            </select>
          </div>

          <div>
            <div class="label">Annex (filtered by Framework)</div>
            <select id="annex_id" name="annex_id" style="width:100%;">
              {''.join(annex_opts)}
            </select>
            <div class="muted" style="margin-top:6px;">
              Select framework contract first, the annex list will filter automatically.
            </div>
          </div>

          <div>
            <div class="label">Monthly Rate</div>
            <input type="text" name="monthly_rate" value="{escape(gv("monthly_rate"))}" style="width:100%;" placeholder="e.g. 11428571.00">
          </div>

          <div>
            <div class="label">Man-day Rate</div>
            <input type="text" name="manday_rate" value="{escape(gv("manday_rate"))}" style="width:100%;">
          </div>

          <div>
            <div class="label">Paid leave (hour) - Total</div>
            <input type="text" name="paid_leave_total_hours" value="{escape(gv("paid_leave_total_hours"))}" style="width:100%;">
          </div>

          <div>
            <div class="label">Paid leave (hour) - Actual used</div>
            <input type="text" name="paid_leave_used_hours" value="{escape(gv("paid_leave_used_hours"))}" style="width:100%;">
          </div>

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
              opt.hidden = false; // -- select framework contract --
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
          const cId = contractSel.value;
          const opts = annexSel.querySelectorAll('option');
          let hasSelectedVisible = false;

          opts.forEach((opt) => {{
            const optContract = opt.getAttribute('data-contract-id');
            if (!optContract) {{
              opt.hidden = false; // (none)
              return;
            }}
            opt.hidden = (cId && optContract !== cId);
            if (!opt.hidden && opt.selected) {{
              hasSelectedVisible = true;
            }}
          }});

          if (!hasSelectedVisible) {{
            annexSel.value = "";
          }}
        }}

        vendorSel.addEventListener('change', filterContract);
        contractSel.addEventListener('change', filterAnnex);
        filterContract();
      }})();
    </script>
    """
    return layout(title, body)
def handle_staff_create_post(handler):
    form = read_post_form(handler)

    full_name_vi = (form.get("full_name_vi", [""])[0] or "").strip()
    vendor_id = (form.get("vendor_id", [""])[0] or "").strip()
    project_name = (form.get("project_name", [""])[0] or "").strip() or None
    position = (form.get("position", [""])[0] or "").strip() or None

    contract_id = (form.get("contract_id", [""])[0] or "").strip()
    annex_id = (form.get("annex_id", [""])[0] or "").strip()

    joining_date = (form.get("joining_date", [""])[0] or "").strip() or None
    leaving_date = (form.get("tentative_leaving_date", [""])[0] or "").strip() or None

    monthly_rate = to_float_or_none(form.get("monthly_rate", [""])[0])
    manday_rate = to_float_or_none(form.get("manday_rate", [""])[0])
    pl_total = to_float_or_none(form.get("paid_leave_total_hours", [""])[0])
    pl_used = to_float_or_none(form.get("paid_leave_used_hours", [""])[0])

    ot = (form.get("ot", ["0"])[0] or "0").strip()
    ot = 1 if ot == "1" else 0

    status = (form.get("status", [""])[0] or "").strip()
    status = status if status else None

    work_shift = (form.get("work_shift", [""])[0] or "").strip() or None
    return_to = (form.get("return_to", ["/staff"])[0] or "").strip() or "/staff"

    # validation
    if not full_name_vi:
        send_html(handler, layout("Error", "<div class='card danger'>Name (VI) is required</div>"), status=400)
        return
    if not vendor_id.isdigit():
        send_html(handler, layout("Error", "<div class='card danger'>Vendor is required</div>"), status=400)
        return
    if not contract_id.isdigit():
        send_html(handler, layout("Error", "<div class='card danger'>Framework contract is required</div>"), status=400)
        return
    if not joining_date:
        send_html(handler, layout("Error", "<div class='card danger'>Joining date is required (for overlap check)</div>"), status=400)
        return

    annex_id_int = int(annex_id) if annex_id.isdigit() else None

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

        c_ok = cur.execute("SELECT 1 FROM contracts WHERE id=? AND is_active=1", (int(contract_id),)).fetchone()
        if not c_ok:
            send_html(handler, layout("Error", "<div class='card danger'>Framework contract not found or deleted</div>"), status=400)
            return

        # annex must belong to contract_id
        if annex_id_int is not None:
            a_ok = cur.execute("""
                SELECT 1 FROM contract_annexes
                WHERE id=? AND contract_id=? AND is_active=1
            """, (annex_id_int, int(contract_id))).fetchone()
            if not a_ok:
                send_html(handler, layout("Error", "<div class='card danger'>Annex not valid for selected framework contract</div>"), status=400)
                return

        # no overlap check
        ok, msg = check_no_overlap(
            conn,
            staff_id_exclude=None,
            vendor_id=int(vendor_id),
            full_name_vi=full_name_vi,
            joining_date=joining_date,
            leaving_date=leaving_date
        )
        if not ok:
            send_html(handler, layout("Error", f"<div class='card danger'>{escape(msg)}</div>"), status=400)
            return

        cur.execute("""
            INSERT INTO contract_staff (
                full_name_vi, vendor_id, project_name, position,
                contract_id, annex_id,
                joining_date, tentative_leaving_date,
                monthly_rate, manday_rate,
                paid_leave_total_hours, paid_leave_used_hours,
                ot, status, work_shift,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            full_name_vi, int(vendor_id), project_name, position,
            int(contract_id), annex_id_int,
            joining_date, leaving_date,
            monthly_rate, manday_rate,
            pl_total, pl_used,
            ot, status, work_shift,
            now_iso(), now_iso()
        ))
        conn.commit()
        new_id = cur.lastrowid
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
    project_name = (form.get("project_name", [""])[0] or "").strip() or None
    position = (form.get("position", [""])[0] or "").strip() or None

    contract_id = (form.get("contract_id", [""])[0] or "").strip()
    annex_id = (form.get("annex_id", [""])[0] or "").strip()

    joining_date = (form.get("joining_date", [""])[0] or "").strip() or None
    leaving_date = (form.get("tentative_leaving_date", [""])[0] or "").strip() or None

    monthly_rate = to_float_or_none(form.get("monthly_rate", [""])[0])
    manday_rate = to_float_or_none(form.get("manday_rate", [""])[0])
    pl_total = to_float_or_none(form.get("paid_leave_total_hours", [""])[0])
    pl_used = to_float_or_none(form.get("paid_leave_used_hours", [""])[0])

    ot = (form.get("ot", ["0"])[0] or "0").strip()
    ot = 1 if ot == "1" else 0

    status = (form.get("status", [""])[0] or "").strip()
    status = status if status else None

    work_shift = (form.get("work_shift", [""])[0] or "").strip() or None
    return_to = (form.get("return_to", ["/staff"])[0] or "").strip() or "/staff"

    if not full_name_vi:
        send_html(handler, layout("Error", "<div class='card danger'>Name (VI) is required</div>"), status=400)
        return
    if not vendor_id.isdigit() or not contract_id.isdigit():
        send_html(handler, layout("Error", "<div class='card danger'>Vendor/Framework contract is required</div>"), status=400)
        return
    if not joining_date:
        send_html(handler, layout("Error", "<div class='card danger'>Joining date is required (for overlap check)</div>"), status=400)
        return

    annex_id_int = int(annex_id) if annex_id.isdigit() else None

    conn = db_connect()
    try:
        cur = conn.cursor()

        row = cur.execute("SELECT id FROM contract_staff WHERE id=?", (int(sid),)).fetchone()
        if not row:
            send_html(handler, layout("Not found", "<div class='card'>Staff not found</div>"), status=404)
            return

        v_ok = cur.execute("""
            SELECT 1 FROM vendors WHERE id=? AND is_active=1 AND purchasing=0
        """, (int(vendor_id),)).fetchone()
        c_ok = cur.execute("SELECT 1 FROM contracts WHERE id=? AND is_active=1", (int(contract_id),)).fetchone()
        if not v_ok or not c_ok:
            send_html(handler, layout("Error", "<div class='card danger'>Vendor/Contract not found or inactive</div>"), status=400)
            return

        if annex_id_int is not None:
            a_ok = cur.execute("""
                SELECT 1 FROM contract_annexes
                WHERE id=? AND contract_id=? AND is_active=1
            """, (annex_id_int, int(contract_id))).fetchone()
            if not a_ok:
                send_html(handler, layout("Error", "<div class='card danger'>Annex not valid for selected framework contract</div>"), status=400)
                return

        ok, msg = check_no_overlap(
            conn,
            staff_id_exclude=int(sid),
            vendor_id=int(vendor_id),
            full_name_vi=full_name_vi,
            joining_date=joining_date,
            leaving_date=leaving_date
        )
        if not ok:
            send_html(handler, layout("Error", f"<div class='card danger'>{escape(msg)}</div>"), status=400)
            return

        cur.execute("""
            UPDATE contract_staff
            SET full_name_vi=?,
                vendor_id=?,
                project_name=?,
                position=?,
                contract_id=?,
                annex_id=?,
                joining_date=?,
                tentative_leaving_date=?,
                monthly_rate=?,
                manday_rate=?,
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
            project_name,
            position,
            int(contract_id),
            annex_id_int,
            joining_date,
            leaving_date,
            monthly_rate,
            manday_rate,
            pl_total,
            pl_used,
            ot,
            status,
            work_shift,
            now_iso(),
            int(sid)
        ))
        conn.commit()
    finally:
        conn.close()

    redirect(handler, return_to)


def page_staff_shifts():
    conn = db_connect()
    try:
        rows = conn.execute("""
            SELECT s.id, s.full_name_vi, s.project_name, s.position, s.ot, s.work_shift,
                   COALESCE(v.company_name, v.company_name_vi) AS vendor_name,
                   c.framework_no AS contract_no
            FROM contract_staff s
            JOIN vendors v ON v.id=s.vendor_id
            JOIN contracts c ON c.id=s.contract_id
            WHERE s.status IS NULL OR s.status <> 'inactive'
            ORDER BY s.id DESC
        """).fetchall()
    finally:
        conn.close()

    trs = []
    for r in rows:
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
          <td>{r["id"]}</td>
          <td><b>{escape(r["full_name_vi"])}</b></td>
          <td>{escape(r["vendor_name"] or "")}</td>
          <td>{escape(r["project_name"] or "")} <div class="muted">{escape(r["position"] or "")}</div></td>
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
            <th>ID</th>
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