# contracts.py

from html import escape
from common import (
    db_connect, layout, LIST_LIMIT, now_iso,
    read_post_form, redirect, send_html, safe_return_to, log_action, to_float_or_none
)

def vendor_label(row):
    # ưu tiên tiếng Anh
    name = (row["company_name"] or row["company_name_vi"] or "").strip()
    tax = (row["tax_id"] or "").strip()
    return f"{name} ({tax})" if tax else name

def load_vendor_options(purchasing: int):
    conn = db_connect()
    try:
        rows = conn.execute("""
            SELECT id, company_name, company_name_vi, tax_id
            FROM vendors
            WHERE is_active=1 AND purchasing=?
            ORDER BY company_name ASC, company_name_vi ASC, id DESC
        """, (purchasing,)).fetchall()
        return rows
    finally:
        conn.close()

def page_contracts_list(q: str, status: str, *, return_to: str):
    q = (q or "").strip()
    status = (status or "active").strip().lower()  # active|deleted|all
    if status not in ("active", "deleted", "all"):
        status = "active"

    where = []
    params = []

    if status == "active":
        where.append("c.is_active = 1")
    elif status == "deleted":
        where.append("c.is_active = 0")

    if q:
        where.append("""(
            c.framework_no LIKE ? OR c.framework_name LIKE ?
            OR bv.company_name_vi LIKE ? OR bv.company_name LIKE ? OR bv.tax_id LIKE ?
            OR sv.company_name_vi LIKE ? OR sv.company_name LIKE ? OR sv.tax_id LIKE ?
        )""")
        like = f"%{q}%"
        params += [like, like, like, like, like, like, like, like]

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    conn = db_connect()
    try:
        rows = conn.execute(f"""
            SELECT
              c.*,
              COALESCE(bv.company_name, bv.company_name_vi) AS buyer_name, bv.tax_id AS buyer_tax,
              COALESCE(sv.company_name, sv.company_name_vi) AS seller_name, sv.tax_id AS seller_tax,
              (SELECT COUNT(*) FROM contract_annexes a WHERE a.contract_id=c.id AND a.is_active=1) AS annex_count,
              (SELECT SUM(a.value) FROM contract_annexes a WHERE a.contract_id=c.id AND a.is_active=1) AS annexes_sum
            FROM contracts c
            JOIN vendors bv ON bv.id = c.buyer_vendor_id
            JOIN vendors sv ON sv.id = c.seller_vendor_id
            {where_sql}
            ORDER BY c.is_active DESC, c.id DESC
            LIMIT ?
        """, params + [LIST_LIMIT]).fetchall()
    finally:
        conn.close()

    filter_html = f"""
    <div class="card">
      <form class="filters" method="GET" action="/contracts">
        <div style="min-width:320px;">
          <div class="label">Search</div>
          <input type="text" name="q" placeholder="Contract No / Name / Tax ID..." value="{escape(q)}" style="width:100%;">
        </div>
        <div>
          <div class="label">Status</div>
          <select name="status">
            <option value="active" {"selected" if status=="active" else ""}>Active</option>
            <option value="deleted" {"selected" if status=="deleted" else ""}>Deleted</option>
            <option value="all" {"selected" if status=="all" else ""}>All</option>
          </select>
        </div>
        <div class="actions">
          <button type="submit">Filter</button>
          <a class="muted" href="/contracts">Reset</a>
          <a href="/contract/new"><button class="btn-secondary" type="button">+ Add Framework Contract</button></a>
        </div>
      </form>
    </div>
    """

    trs = []
    for idx, r in enumerate(rows, 1):
        tag = ""
        if int(r["is_active"]) == 0:
            tag = '<span class="tag tag-deactive">Deleted</span>'

        buyer = f"{(r['buyer_name'] or '').strip()} ({(r['buyer_tax'] or '').strip()})"
        seller = f"{(r['seller_name'] or '').strip()} ({(r['seller_tax'] or '').strip()})"

        # Determine value to display
        if r["contract_value"] is not None and r["contract_value"] > 0:
            val_display = f"{int(round(r['contract_value'])):,}"
        elif r["annexes_sum"] is not None and r["annexes_sum"] > 0:
            val_display = f"{int(round(r['annexes_sum'])):,} <span class='muted' style='font-size:10px;'>(sum of annexes)</span>"
        else:
            val_display = '<span class="muted">No value</span>'

        actions = f'<a href="/contract/edit?id={r["id"]}" style="text-decoration:none;"><button type="button" class="btn-secondary" style="font-size:11px; padding: 4px 8px; margin-top:2px;">Edit</button></a>'

        if int(r["is_active"]) == 1:
            actions += f"""
              <form class="inline" method="POST" action="/contract/delete"
                    onsubmit="return confirm('Deactivate framework contract #{r["id"]}?');"
                    style="margin:0; display:inline-block;">
                <input type="hidden" name="id" value="{r["id"]}">
                <input type="hidden" name="return_to" value="{escape(return_to)}">
                <button class="btn-danger" type="submit" style="font-size:11px; padding: 4px 8px; margin-top:2px;">Delete</button>
              </form>
            """
        else:
            actions += f"""
              <form class="inline" method="POST" action="/contract/restore"
                    onsubmit="return confirm('Restore framework contract #{r["id"]}?');"
                    style="margin:0; display:inline-block;">
                <input type="hidden" name="id" value="{r["id"]}">
                <input type="hidden" name="return_to" value="{escape(return_to)}">
                <button type="submit" class="btn-secondary" style="font-size:11px; padding: 4px 8px; margin-top:2px;">Restore</button>
              </form>
            """

        trs.append(f"""
        <tr>
          <td>{idx}</td>
          <td>
            <a href="/contract/edit?id={r["id"]}"><b>{escape(r["framework_no"] or "")}</b></a> {tag}
            <div class="muted">{escape(r["framework_name"] or "")}</div>
          </td>
          <td>{escape(buyer)}</td>
          <td>{escape(seller)}</td>
          <td>{escape(r["start_date"] or "")} → {escape(r["end_date"] or "")}</td>
          <td style="text-align:right; font-family:monospace;">{val_display}</td>
          <td>{r["annex_count"]}</td>
          <td>
            <div class="actions" style="gap:6px; flex-wrap:nowrap; display:flex; align-items:center;">
              {actions}
            </div>
          </td>
        </tr>
        """)

    sub_nav = """
    <div class="actions" style="margin-bottom: 14px; border-bottom: 1px solid #ddd; padding-bottom: 8px;">
      <a href="/contracts" style="margin-right: 18px; font-weight: bold; color:#0b57d0; border-bottom: 2px solid #0b57d0; padding-bottom: 8px;">📑 Contracts List</a>
      <a href="/contracts/references" style="font-weight: bold; color:#666; text-decoration:none;">🔑 Reference Numbers</a>
    </div>
    """

    body = f"""
    {sub_nav}
    {filter_html}
    <table>
      <thead>
        <tr>
          <th>No.</th>
          <th>Framework Contract</th>
          <th>Purchasing (Buyer)</th>
          <th>Vendor (Seller)</th>
          <th>Contract Period</th>
          <th style="text-align:right;">Value (VND)</th>
          <th>Annexes (Active)</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {''.join(trs) if trs else '<tr><td colspan="8" class="muted">No contracts</td></tr>'}
      </tbody>
    </table>
    """
    return layout("Contract Management", body)


def page_contract_form(mode: str, contract_row, annex_rows, error_msg: str | None = None):
    if mode not in ("new", "edit"):
        mode = "new"

    buyer_opts = load_vendor_options(1)  # purchasing=Yes
    seller_opts = load_vendor_options(0) # purchasing=No

    annex_sum = 0.0
    if mode == "edit" and annex_rows:
        for a in annex_rows:
            if int(a["is_active"]) == 1 and a["value"] is not None:
                annex_sum += float(a["value"])

    placeholder_val = f"Default (Annexes sum): {int(round(annex_sum))}" if annex_sum > 0 else "e.g. 5000000000"

    allocated_staff = []
    has_active_annex = False
    if mode == "edit" and contract_row:
        has_active_annex = any(int(a["is_active"]) == 1 for a in annex_rows)
        conn = db_connect()
        try:
            allocated_staff = conn.execute("""
                SELECT l.id AS link_id, l.staff_id, l.annex_id, l.monthly_rate, l.manday_rate, l.joining_date, l.tentative_leaving_date,
                       s.full_name_vi, s.position
                FROM contract_staff_links l
                JOIN contract_staff s ON s.id = l.staff_id
                WHERE l.contract_id = ?
            """, (contract_row["id"],)).fetchall()
        finally:
            conn.close()

    staff_for_contract = [s for s in allocated_staff if s["annex_id"] is None]
    staff_by_annex = {}
    for s in allocated_staff:
        if s["annex_id"] is not None:
            staff_by_annex.setdefault(s["annex_id"], []).append(s)

    def gv(key):
        if contract_row is None:
            return ""
        x = contract_row[key]
        return "" if x is None else str(x)

    title = "Add Framework Contract" if mode == "new" else f"Edit Contract #{contract_row['id']}"
    action = "/contract/create" if mode == "new" else "/contract/update"
    hidden_id = f'<input type="hidden" name="id" value="{contract_row["id"]}">' if mode == "edit" else ""

    error_html = f'<div class="card danger"><b>Error:</b> {escape(error_msg)}</div>' if error_msg else ""

    buyer_selected = gv("buyer_vendor_id")
    seller_selected = gv("seller_vendor_id")

    buyer_select = "\n".join(
        f'<option value="{r["id"]}" {"selected" if str(r["id"])==buyer_selected else ""}>{escape(vendor_label(r))}</option>'
        for r in buyer_opts
    )
    seller_select = "\n".join(
        f'<option value="{r["id"]}" {"selected" if str(r["id"])==seller_selected else ""}>{escape(vendor_label(r))}</option>'
        for r in seller_opts
    )
    # Annex list (only in edit)
    annex_html = ""
    if mode == "edit":
        annex_trs = []
        for idx, a in enumerate(annex_rows, 1):
            tag = "" if int(a["is_active"]) == 1 else '<span class="tag tag-deactive">Deleted</span>'
            
            # Fetch allocated staff for this annex
            annex_staff = staff_by_annex.get(a["id"], [])
            staff_list_html = ""
            if annex_staff:
                staff_items = []
                for s in annex_staff:
                    m_rate = f"{s['monthly_rate']:,.2f} VND" if s['monthly_rate'] is not None else "-"
                    staff_items.append(f"""
                    <div style="display:flex; justify-content:space-between; align-items:center; font-size:11px; background:#f1f5f9; padding:4px 8px; border-radius:4px; margin-top:4px;">
                      <span>👤 <b>{escape(s['full_name_vi'])}</b> ({escape(s['joining_date'] or '')} → {escape(s['tentative_leaving_date'] or 'Present')})</span>
                      <span style="color:var(--success); font-weight:600; margin-left:10px;">{m_rate}</span>
                      <div style="display:inline-flex; gap:6px; margin-left:10px;">
                        <a href="/contract/edit-staff-link?id={s['link_id']}" style="font-size:10px; color:var(--primary); text-decoration:none;">Edit</a>
                        <form class="inline" method="POST" action="/contract/remove-staff-link" onsubmit="return confirm('Remove staff from annex?');" style="margin:0; display:inline;">
                          <input type="hidden" name="link_id" value="{s['link_id']}">
                          <input type="hidden" name="return_to" value="/contract/edit?id={contract_row['id']}">
                          <button type="submit" style="background:none; border:none; color:var(--danger); font-size:10px; cursor:pointer; padding:0; display:inline;">Remove</button>
                        </form>
                      </div>
                    </div>
                    """)
                staff_list_html = f"<div style='margin-top:6px;'>{''.join(staff_items)}</div>"

            actions = f'<a href="/annex/edit?id={a["id"]}" style="text-decoration:none;"><button type="button" class="btn-secondary" style="font-size:11px; padding: 4px 8px; margin-top:2px;">Edit</button></a>'
            if int(a["is_active"]) == 1:
                actions += f"""
                  <a href="/contract/assign-staff?contract_id={contract_row['id']}&annex_id={a['id']}" style="text-decoration:none;">
                    <button type="button" class="btn-secondary" style="font-size:11px; padding: 4px 8px; margin-top:2px; color:var(--primary); border-color:var(--primary);">+ Allocate Staff</button>
                  </a>
                  <form class="inline" method="POST" action="/annex/delete"
                        onsubmit="return confirm('Deactivate annex #{a["id"]}?');"
                        style="margin:0; display:inline-block;">
                    <input type="hidden" name="id" value="{a["id"]}">
                    <input type="hidden" name="return_to" value="/contract/edit?id={contract_row['id']}">
                    <button class="btn-danger" type="submit" style="font-size:11px; padding: 4px 8px; margin-top:2px;">Delete</button>
                  </form>
                """
            else:
                actions += f"""
                  <form class="inline" method="POST" action="/annex/restore"
                        onsubmit="return confirm('Restore annex #{a["id"]}?');"
                        style="margin:0; display:inline-block;">
                    <input type="hidden" name="id" value="{a["id"]}">
                    <input type="hidden" name="return_to" value="/contract/edit?id={contract_row['id']}">
                    <button type="submit" class="btn-secondary" style="font-size:11px; padding: 4px 8px; margin-top:2px;">Restore</button>
                  </form>
                """

            val_display = f"{int(round(a['value'])):,}" if a["value"] is not None else '<span class="muted">Not set</span>'
            annex_trs.append(f"""
              <tr>
                <td>{idx}</td>
                <td>
                  <b>{escape(a["annex_name"] or "")}</b> {tag}
                  {staff_list_html}
                </td>
                <td>{escape(a["start_date"] or "")} → {escape(a["end_date"] or "")}</td>
                <td style="text-align:right; font-family:monospace;">{val_display}</td>
                <td>
                  <div class="actions" style="gap:6px; flex-wrap:nowrap; display:flex; align-items:center;">
                    {actions}
                  </div>
                </td>
              </tr>
            """)

        annex_html = f"""
        <div class="card">
          <div class="actions" style="margin-bottom:10px;">
            <b>Annexes</b>
            <a href="/annex/new?contract_id={contract_row["id"]}">
              <button class="btn-secondary" type="button">+ Add Annex</button>
            </a>
          </div>
          <table>
            <thead><tr><th>No.</th><th>Annex Name</th><th>Period</th><th style="text-align:right;">Value (VND)</th><th>Actions</th></tr></thead>
            <tbody>
              {''.join(annex_trs) if annex_trs else '<tr><td colspan="5" class="muted">No annexes</td></tr>'}
            </tbody>
          </table>

          <div class="muted" style="margin-top:10px;">
            Validity rule: If there is an active annex, the annex's period takes precedence; otherwise, the framework contract's period is used.
          </div>
        </div>
        """

    staff_block_html = ""
    if mode == "edit":
        if not has_active_annex:
            staff_trs = []
            for s_idx, s in enumerate(staff_for_contract, 1):
                m_rate = f"{s['monthly_rate']:,.2f} VND" if s['monthly_rate'] is not None else "-"
                d_rate = f"{s['manday_rate']:,.2f} VND" if s['manday_rate'] is not None else "-"
                actions = f"""
                  <a href="/contract/edit-staff-link?id={s['link_id']}" style="text-decoration:none;"><button type="button" class="btn-secondary" style="font-size:11px; padding: 4px 8px; margin-top:2px;">Edit</button></a>
                  <form class="inline" method="POST" action="/contract/remove-staff-link" onsubmit="return confirm('Remove staff from contract?');" style="margin:0; display:inline-block;">
                    <input type="hidden" name="link_id" value="{s['link_id']}">
                    <input type="hidden" name="return_to" value="/contract/edit?id={contract_row['id']}">
                    <button class="btn-danger" type="submit" style="font-size:11px; padding: 4px 8px; margin-top:2px;">Remove</button>
                  </form>
                """
                staff_trs.append(f"""
                <tr>
                  <td>{s_idx}</td>
                  <td><b>{escape(s['full_name_vi'])}</b><div class='muted'>{escape(s['position'] or '')}</div></td>
                  <td>{escape(s['joining_date'] or '')} → {escape(s['tentative_leaving_date'] or 'Present')}</td>
                  <td style="text-align:right;">{m_rate}</td>
                  <td style="text-align:right;">{d_rate}</td>
                  <td>{actions}</td>
                </tr>
                """)
            
            staff_block_html = f"""
            <div class="card">
              <div class="actions" style="margin-bottom:10px;">
                <b>Allocated Staff to Contract</b>
                <a href="/contract/assign-staff?contract_id={contract_row['id']}">
                  <button class="btn-secondary" type="button">+ Allocate Staff to Contract</button>
                </a>
              </div>
              <table style="width:100%; border-collapse:collapse; margin:0;">
                <thead>
                  <tr>
                    <th>No.</th>
                    <th>Staff Name</th>
                    <th>Period</th>
                    <th style="text-align:right;">Monthly Rate</th>
                    <th style="text-align:right;">Man-day Rate</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {''.join(staff_trs) if staff_trs else '<tr><td colspan="6" class="muted" style="text-align:center; padding:15px;">No staff allocated directly to contract.</td></tr>'}
                </tbody>
              </table>
            </div>
            """
        else:
            staff_block_html = f"""
            <div class="card" style="background:#f8fafc; border-color:#e2e8f0; padding:15px;">
              <span class="muted" style="font-size:13px; font-weight:500; color:var(--text-secondary);">
                ℹ️ This contract has annexes. Please allocate staff to each Annex below.
              </span>
            </div>
            """

    body = f"""
    {error_html}

    <div class="card">
      <div class="actions" style="margin-bottom:10px;">
        <a href="/contracts">← Contracts List</a>
      </div>

      <form method="POST" action="{action}">
        {hidden_id}

        <div class="grid">
          <div>
            <div class="label">Purchasing company (purchasing=Yes)</div>
            <select name="buyer_vendor_id" style="width:100%;">
              <option value="">-- select --</option>
              {buyer_select}
            </select>
          </div>

          <div>
            <div class="label">Vendor/Supplier (purchasing=No)</div>
            <select name="seller_vendor_id" style="width:100%;">
              <option value="">-- select --</option>
              {seller_select}
            </select>
          </div>

          <div>
            <div class="label">Framework Contract No</div>
            <input type="text" name="framework_no" value="{escape(gv("framework_no"))}" style="width:100%;">
          </div>

          <div>
            <div class="label">Framework Contract Name</div>
            <input type="text" name="framework_name" value="{escape(gv("framework_name"))}" style="width:100%;">
          </div>

          <div>
            <div class="label">Contract Value (VND)</div>
            <input type="number" name="contract_value" value="{escape(gv("contract_value"))}" style="width:100%;" placeholder="{placeholder_val}">
            {f'<div class="muted" style="margin-top:4px; font-size:11px;">Default (Annexes sum): <b>{int(round(annex_sum)):,} VND</b></div>' if annex_sum > 0 else ''}
          </div>

          <div>
            <div class="label">Start date (Framework)</div>
            <input type="date" name="start_date" value="{escape(gv("start_date"))}" style="width:100%;">
          </div>

          <div>
            <div class="label">End date (Framework)</div>
            <input type="date" name="end_date" value="{escape(gv("end_date"))}" style="width:100%;">
          </div>
        </div>

        <div class="actions" style="margin-top:14px;">
          <button type="submit">Save</button>
          <a class="muted" href="/contracts">Cancel</a>
        </div>
      </form>
    </div>

    {staff_block_html}
    {annex_html}
    """
    return layout(title, body)


def page_annex_form(mode: str, annex_row, contract_id: int, error_msg: str | None = None):
    if mode not in ("new", "edit"):
        mode = "new"

    def gv(key):
        if annex_row is None:
            return ""
        x = annex_row[key]
        return "" if x is None else str(x)

    title = "Add Annex" if mode == "new" else f"Edit Annex #{annex_row['id']}"
    action = "/annex/create" if mode == "new" else "/annex/update"
    hidden_id = f'<input type="hidden" name="id" value="{annex_row["id"]}">' if mode == "edit" else ""
    hidden_contract = f'<input type="hidden" name="contract_id" value="{contract_id}">'

    error_html = f'<div class="card danger"><b>Error:</b> {escape(error_msg)}</div>' if error_msg else ""

    body = f"""
    {error_html}
    <div class="card">
      <div class="actions" style="margin-bottom:10px;">
        <a href="/contract/edit?id={contract_id}">← Back to Contract</a>
      </div>

      <form method="POST" action="{action}">
        {hidden_id}
        {hidden_contract}

        <div class="grid">
          <div>
            <div class="label">Annex Name</div>
            <input type="text" name="annex_name" value="{escape(gv("annex_name"))}" style="width:100%;">
          </div>
          <div>
            <div class="label">Annex Value (VND)</div>
            <input type="number" step="1" name="value" value="{escape(gv("value"))}" style="width:100%;" placeholder="e.g. 500000000">
          </div>
          <div>
            <div class="label">Start date (Annex)</div>
            <input type="date" name="start_date" value="{escape(gv("start_date"))}" style="width:100%;">
          </div>
          <div>
            <div class="label">End date (Annex)</div>
            <input type="date" name="end_date" value="{escape(gv("end_date"))}" style="width:100%;">
          </div>
        </div>

        <div class="actions" style="margin-top:14px;">
          <button type="submit">Save</button>
          <a class="muted" href="/contract/edit?id={contract_id}">Cancel</a>
        </div>
      </form>
    </div>
    """
    return layout(title, body)
# -------------------- Handlers (POST) --------------------
def handle_contract_create_post(handler):
    form = read_post_form(handler)
    buyer_id = (form.get("buyer_vendor_id", [""])[0] or "").strip()
    seller_id = (form.get("seller_vendor_id", [""])[0] or "").strip()
    framework_no = (form.get("framework_no", [""])[0] or "").strip() or None
    framework_name = (form.get("framework_name", [""])[0] or "").strip() or None
    contract_value_raw = (form.get("contract_value", [""])[0] or "").strip()
    start_date = (form.get("start_date", [""])[0] or "").strip() or None
    end_date = (form.get("end_date", [""])[0] or "").strip() or None

    contract_value = None
    if contract_value_raw:
        try:
            contract_value = float(contract_value_raw.replace(",", ""))
        except ValueError:
            pass

    if not buyer_id.isdigit() or not seller_id.isdigit():
        send_html(handler, layout("Error", "<div class='card danger'>Invalid Buyer/Seller Vendor ID</div>"), status=400)
        return

    conn = db_connect()
    try:
        cur = conn.cursor()

        # validate buyer is purchasing=1, seller is purchasing=0 and active
        b_ok = cur.execute("SELECT 1 FROM vendors WHERE id=? AND is_active=1 AND purchasing=1", (int(buyer_id),)).fetchone()
        s_ok = cur.execute("SELECT 1 FROM vendors WHERE id=? AND is_active=1 AND purchasing=0", (int(seller_id),)).fetchone()
        if not b_ok or not s_ok:
            send_html(handler, layout("Error", "<div class='card danger'>Buyer/Seller vendor does not belong to the correct purchasing group or is deactivated</div>"), status=400)
            return

        cur.execute("""
            INSERT INTO contracts (
              buyer_vendor_id, seller_vendor_id,
              framework_no, framework_name, contract_value,
              start_date, end_date,
              is_active, deleted_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, NULL, ?, ?)
        """, (int(buyer_id), int(seller_id), framework_no, framework_name, contract_value, start_date, end_date, now_iso(), now_iso()))
        new_id = cur.lastrowid
        log_action(cur, "CREATE_CONTRACT", "contracts", new_id, f"Created new framework contract '{framework_no}' - {framework_name}")
        conn.commit()
    finally:
        conn.close()

    redirect(handler, f"/contract/edit?id={new_id}")


def handle_contract_update_post(handler):
    form = read_post_form(handler)
    cid = (form.get("id", [""])[0] or "").strip()
    if not cid.isdigit():
        send_html(handler, layout("Error", "<div class='card danger'>Invalid Contract ID</div>"), status=400)
        return

    buyer_id = (form.get("buyer_vendor_id", [""])[0] or "").strip()
    seller_id = (form.get("seller_vendor_id", [""])[0] or "").strip()
    framework_no = (form.get("framework_no", [""])[0] or "").strip() or None
    framework_name = (form.get("framework_name", [""])[0] or "").strip() or None
    contract_value_raw = (form.get("contract_value", [""])[0] or "").strip()
    start_date = (form.get("start_date", [""])[0] or "").strip() or None
    end_date = (form.get("end_date", [""])[0] or "").strip() or None

    contract_value = None
    if contract_value_raw:
        try:
            contract_value = float(contract_value_raw.replace(",", ""))
        except ValueError:
            pass

    if not buyer_id.isdigit() or not seller_id.isdigit():
        send_html(handler, layout("Error", "<div class='card danger'>Invalid Buyer/Seller Vendor ID</div>"), status=400)
        return

    conn = db_connect()
    try:
        cur = conn.cursor()

        row = cur.execute("SELECT id FROM contracts WHERE id=?", (int(cid),)).fetchone()
        if not row:
            send_html(handler, layout("Not Found", f"<div class='card'>Contract ID={cid} not found</div>"), status=404)
            return

        b_ok = cur.execute("SELECT 1 FROM vendors WHERE id=? AND is_active=1 AND purchasing=1", (int(buyer_id),)).fetchone()
        s_ok = cur.execute("SELECT 1 FROM vendors WHERE id=? AND is_active=1 AND purchasing=0", (int(seller_id),)).fetchone()
        if not b_ok or not s_ok:
            send_html(handler, layout("Error", "<div class='card danger'>Buyer/Seller vendor does not belong to the correct purchasing group or is deactivated</div>"), status=400)
            return

        cur.execute("""
            UPDATE contracts
            SET buyer_vendor_id=?,
                seller_vendor_id=?,
                framework_no=?,
                framework_name=?,
                contract_value=?,
                start_date=?,
                end_date=?,
                updated_at=?
            WHERE id=?
        """, (int(buyer_id), int(seller_id), framework_no, framework_name, contract_value, start_date, end_date, now_iso(), int(cid)))
        log_action(cur, "UPDATE_CONTRACT", "contracts", int(cid), f"Updated framework contract '{framework_no}' - {framework_name}")
        conn.commit()
    finally:
        conn.close()

    redirect(handler, f"/contract/edit?id={cid}")


def handle_contract_delete_post(handler):
    form = read_post_form(handler)
    cid = (form.get("id", [""])[0] or "").strip()
    return_to = safe_return_to((form.get("return_to", [""])[0] or "").strip())
    if not cid.isdigit():
        send_html(handler, layout("Error", "<div class='card danger'>Invalid Contract ID</div>"), status=400)
        return

    conn = db_connect()
    try:
        # Get framework no for log
        c_row = conn.execute("SELECT framework_no FROM contracts WHERE id=?", (int(cid),)).fetchone()
        c_name = c_row["framework_no"] if c_row else f"ID {cid}"

        cur = conn.cursor()
        cur.execute("UPDATE contracts SET is_active=0, deleted_at=?, updated_at=? WHERE id=?", (now_iso(), now_iso(), int(cid)))
        log_action(cur, "DEACTIVATE_CONTRACT", "contracts", int(cid), f"Deactivated framework contract '{c_name}'")
        conn.commit()
    finally:
        conn.close()

    redirect(handler, return_to)


def handle_contract_restore_post(handler):
    form = read_post_form(handler)
    cid = (form.get("id", [""])[0] or "").strip()
    return_to = safe_return_to((form.get("return_to", [""])[0] or "").strip())
    if not cid.isdigit():
        send_html(handler, layout("Error", "<div class='card danger'>Invalid Contract ID</div>"), status=400)
        return

    conn = db_connect()
    try:
        # Get framework no for log
        c_row = conn.execute("SELECT framework_no FROM contracts WHERE id=?", (int(cid),)).fetchone()
        c_name = c_row["framework_no"] if c_row else f"ID {cid}"

        cur = conn.cursor()
        cur.execute("UPDATE contracts SET is_active=1, deleted_at=NULL, updated_at=? WHERE id=?", (now_iso(), int(cid)))
        log_action(cur, "RESTORE_CONTRACT", "contracts", int(cid), f"Restored framework contract '{c_name}'")
        conn.commit()
    finally:
        conn.close()

    redirect(handler, return_to)


def handle_annex_create_post(handler):
    form = read_post_form(handler)
    contract_id = (form.get("contract_id", [""])[0] or "").strip()
    annex_name = (form.get("annex_name", [""])[0] or "").strip() or None
    start_date = (form.get("start_date", [""])[0] or "").strip() or None
    end_date = (form.get("end_date", [""])[0] or "").strip() or None
    value_raw = (form.get("value", [""])[0] or "").strip()
    value = None
    if value_raw:
        try:
            value = float(value_raw.replace(",", ""))
        except ValueError:
            pass

    if not contract_id.isdigit():
        send_html(handler, layout("Error", "<div class='card danger'>Invalid Contract ID</div>"), status=400)
        return

    conn = db_connect()
    try:
        cur = conn.cursor()
        row = cur.execute("SELECT id FROM contracts WHERE id=? AND is_active=1", (int(contract_id),)).fetchone()
        if not row:
            send_html(handler, layout("Error", "<div class='card danger'>Contract does not exist or has been deleted</div>"), status=400)
            return

        # Get contract framework no for log
        c_row = cur.execute("SELECT framework_no FROM contracts WHERE id=?", (int(contract_id),)).fetchone()
        c_name = c_row["framework_no"] if c_row else f"ID {contract_id}"

        cur.execute("""
            INSERT INTO contract_annexes (
              contract_id, annex_name, start_date, end_date, value,
              is_active, deleted_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 1, NULL, ?, ?)
        """, (int(contract_id), annex_name, start_date, end_date, value, now_iso(), now_iso()))
        new_annex_id = cur.lastrowid
        log_action(cur, "CREATE_ANNEX", "contract_annexes", new_annex_id, f"Created new annex '{annex_name}' for framework contract '{c_name}'")
        conn.commit()
    finally:
        conn.close()

    redirect(handler, f"/contract/edit?id={contract_id}")


def handle_annex_update_post(handler):
    form = read_post_form(handler)
    aid = (form.get("id", [""])[0] or "").strip()
    contract_id = (form.get("contract_id", [""])[0] or "").strip()
    annex_name = (form.get("annex_name", [""])[0] or "").strip() or None
    start_date = (form.get("start_date", [""])[0] or "").strip() or None
    end_date = (form.get("end_date", [""])[0] or "").strip() or None
    value_raw = (form.get("value", [""])[0] or "").strip()
    value = None
    if value_raw:
        try:
            value = float(value_raw.replace(",", ""))
        except ValueError:
            pass

    if not aid.isdigit() or not contract_id.isdigit():
        send_html(handler, layout("Error", "<div class='card danger'>Invalid ID</div>"), status=400)
        return

    conn = db_connect()
    try:
        cur = conn.cursor()
        row = cur.execute("SELECT id FROM contract_annexes WHERE id=?", (int(aid),)).fetchone()
        if not row:
            send_html(handler, layout("Not Found", f"<div class='card'>Annex ID={aid} not found</div>"), status=404)
            return

        # Get contract framework no for log
        c_row = cur.execute("SELECT framework_no FROM contracts WHERE id=?", (int(contract_id),)).fetchone()
        c_name = c_row["framework_no"] if c_row else f"ID {contract_id}"

        cur.execute("""
            UPDATE contract_annexes
            SET annex_name=?,
                start_date=?,
                end_date=?,
                value=?,
                updated_at=?
            WHERE id=?
        """, (annex_name, start_date, end_date, value, now_iso(), int(aid)))
        log_action(cur, "UPDATE_ANNEX", "contract_annexes", int(aid), f"Updated annex '{annex_name}' for framework contract '{c_name}'")
        conn.commit()
    finally:
        conn.close()

    redirect(handler, f"/contract/edit?id={contract_id}")


def handle_annex_delete_post(handler):
    form = read_post_form(handler)
    aid = (form.get("id", [""])[0] or "").strip()
    return_to = safe_return_to((form.get("return_to", [""])[0] or "").strip())
    if not aid.isdigit():
        send_html(handler, layout("Error", "<div class='card danger'>Invalid Annex ID</div>"), status=400)
        return

    conn = db_connect()
    try:
        # Get annex name for log
        a_row = conn.execute("SELECT annex_name FROM contract_annexes WHERE id=?", (int(aid),)).fetchone()
        a_name = a_row["annex_name"] if a_row else f"ID {aid}"

        cur = conn.cursor()
        cur.execute("UPDATE contract_annexes SET is_active=0, deleted_at=?, updated_at=? WHERE id=?", (now_iso(), now_iso(), int(aid)))
        log_action(cur, "DEACTIVATE_ANNEX", "contract_annexes", int(aid), f"Deactivated annex '{a_name}'")
        conn.commit()
    finally:
        conn.close()

    redirect(handler, return_to)


def handle_annex_restore_post(handler):
    form = read_post_form(handler)
    aid = (form.get("id", [""])[0] or "").strip()
    return_to = safe_return_to((form.get("return_to", [""])[0] or "").strip())
    if not aid.isdigit():
        send_html(handler, layout("Error", "<div class='card danger'>Invalid Annex ID</div>"), status=400)
        return

    conn = db_connect()
    try:
        # Get annex name for log
        a_row = conn.execute("SELECT annex_name FROM contract_annexes WHERE id=?", (int(aid),)).fetchone()
        a_name = a_row["annex_name"] if a_row else f"ID {aid}"

        cur = conn.cursor()
        cur.execute("UPDATE contract_annexes SET is_active=1, deleted_at=NULL, updated_at=? WHERE id=?", (now_iso(), int(aid)))
        log_action(cur, "RESTORE_ANNEX", "contract_annexes", int(aid), f"Restored annex '{a_name}'")
        conn.commit()
    finally:
        conn.close()

    redirect(handler, return_to)


def get_months_between(start_str: str | None, end_str: str | None) -> list[str]:
    if not start_str or not end_str:
        return []
    from datetime import datetime
    try:
        start_dt = datetime.strptime(start_str[:7], "%Y-%m")
        end_dt = datetime.strptime(end_str[:7], "%Y-%m")
    except Exception:
        return []
        
    months = []
    curr = start_dt
    limit = 240 # max 20 years
    count = 0
    while curr <= end_dt and count < limit:
        months.append(curr.strftime("%Y-%m"))
        if curr.month == 12:
            curr = datetime(curr.year + 1, 1, 1)
        else:
            curr = datetime(curr.year, curr.month + 1, 1)
        count += 1
    return months


def handle_save_reference_ajax(handler):
    import json
    length = int(handler.headers.get("Content-Length", 0))
    body = handler.rfile.read(length).decode("utf-8", errors="ignore")
    
    try:
        data = json.loads(body)
    except Exception:
        send_html(handler, json.dumps({"status": "error", "message": "Invalid JSON"}), status=400)
        return
        
    contract_id = data.get("contract_id")
    annex_id = data.get("annex_id")
    month = data.get("month")
    value = str(data.get("value", "")).strip()
    
    if not contract_id or annex_id is None or not month:
        send_html(handler, json.dumps({"status": "error", "message": "Missing parameters"}), status=400)
        return
        
    try:
        contract_id = int(contract_id)
        annex_id = int(annex_id)
    except ValueError:
        send_html(handler, json.dumps({"status": "error", "message": "Invalid ID format"}), status=400)
        return

    conn = db_connect()
    try:
        cur = conn.cursor()
        
        # Nếu nhập chuỗi trống -> xóa bản ghi cũ để sạch database
        if value == "":
            cur.execute("""
                DELETE FROM contract_references 
                WHERE contract_id=? AND annex_id=? AND month=?
            """, (contract_id, annex_id, month))
        else:
            cur.execute("""
                INSERT INTO contract_references (contract_id, annex_id, month, reference_number, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(contract_id, annex_id, month) DO UPDATE SET
                    reference_number=excluded.reference_number,
                    updated_at=datetime('now')
            """, (contract_id, annex_id, month, value))
            
        conn.commit()
        send_html(handler, json.dumps({"status": "ok"}))
    except Exception as e:
        send_html(handler, json.dumps({"status": "error", "message": str(e)}), status=500)
    finally:
        conn.close()


def page_contract_references(vendor_id="", contract_id="", annex_id="", month="", sent_mgs=""):
    def month_in_range(start_date, end_date, m_str):
        if not start_date or not m_str:
            return False
        s_m = start_date[:7]
        e_m = end_date[:7] if end_date else "9999-12"
        return s_m <= m_str <= e_m

    conn = db_connect()
    try:
        # Load vendors for filter dropdown
        vendors_filter = conn.execute("""
            SELECT id, short_name, company_name, company_name_vi 
            FROM vendors 
            WHERE is_active=1 AND purchasing=0 
            ORDER BY short_name ASC
        """).fetchall()

        # Load contracts for filter dropdown
        contracts_filter = conn.execute("""
            SELECT id, framework_no, seller_vendor_id 
            FROM contracts 
            WHERE is_active=1 
            ORDER BY framework_no ASC
        """).fetchall()

        # Load annexes for filter dropdown
        annexes_filter = conn.execute("""
            SELECT a.id, a.annex_name, c.framework_no, a.contract_id, c.seller_vendor_id 
            FROM contract_annexes a
            JOIN contracts c ON c.id = a.contract_id
            WHERE a.is_active=1 
            ORDER BY a.annex_name ASC
        """).fetchall()

        # Load filtered active contracts
        sql = """
            SELECT c.id, c.framework_no, c.framework_name, c.start_date, c.end_date,
                   COALESCE(sv.company_name, sv.company_name_vi) AS seller_name,
                   c.seller_vendor_id
            FROM contracts c
            JOIN vendors sv ON sv.id = c.seller_vendor_id
            WHERE c.is_active = 1
        """
        params = []
        if vendor_id:
            sql += " AND c.seller_vendor_id = ?"
            params.append(int(vendor_id))
        if contract_id:
            sql += " AND c.id = ?"
            params.append(int(contract_id))
        if annex_id:
            sql += " AND c.id = (SELECT contract_id FROM contract_annexes WHERE id = ?)"
            params.append(int(annex_id))
        sql += " ORDER BY c.framework_no ASC"
        contracts_rows = conn.execute(sql, params).fetchall()

        # Load filtered active annexes
        sql_a = """
            SELECT id, contract_id, annex_name, start_date, end_date
            FROM contract_annexes
            WHERE is_active = 1
        """
        params_a = []
        if annex_id:
            sql_a += " AND id = ?"
            params_a.append(int(annex_id))
        if contract_id:
            sql_a += " AND contract_id = ?"
            params_a.append(int(contract_id))
        if vendor_id:
            sql_a += " AND contract_id IN (SELECT id FROM contracts WHERE seller_vendor_id = ?)"
            params_a.append(int(vendor_id))
        sql_a += " ORDER BY id ASC"
        annexes_rows = conn.execute(sql_a, params_a).fetchall()
        
        # Nhóm các annex theo contract_id
        annexes_by_contract = {}
        for a in annexes_rows:
            annexes_by_contract.setdefault(a["contract_id"], []).append(a)

        # Load existing references
        refs_rows = conn.execute("""
            SELECT contract_id, annex_id, month, reference_number, locked
            FROM contract_references
        """).fetchall()
        
        # Create mapping refs_map[(contract_id, annex_id, month)] = (reference_number, locked)
        refs_map = {}
        for r in refs_rows:
            key = (r["contract_id"], r["annex_id"], r["month"])
            refs_map[key] = (r["reference_number"] or "", int(r["locked"] or 0))

        # Load sent MGS invoices
        sent_invoices = conn.execute("""
            SELECT LOWER(TRIM(contract_no)) AS c_no, service_year, service_month
            FROM invoices
            WHERE sent_to_mgs = 1
        """).fetchall()
        
        sent_set = set()
        for row in sent_invoices:
            if row["service_year"] is not None and row["service_month"] is not None:
                m_str = f"{row['service_year']:04d}-{row['service_month']:02d}"
                sent_set.add((row["c_no"], m_str))

    finally:
        conn.close()

    cards_html = []

    for c in contracts_rows:
        cid = c["id"]
        c_annexes = annexes_by_contract.get(cid, [])
        
        if not c_annexes:
            # Trường hợp 1: Không có phụ lục -> Hiển thị chính hợp đồng khung
            if month:
                if month_in_range(c["start_date"], c["end_date"], month):
                    months = [month]
                else:
                    months = []
            else:
                months = get_months_between(c["start_date"], c["end_date"])
                
            # Filter months list by sent_mgs
            filtered_months = []
            for m in months:
                is_sent = c["framework_no"] and (c["framework_no"].lower().strip(), m) in sent_set
                if sent_mgs == "yes":
                    if is_sent:
                        filtered_months.append(m)
                elif sent_mgs == "no":
                    if not is_sent:
                        filtered_months.append(m)
                else:
                    filtered_months.append(m)
            months = filtered_months

            if not months:
                continue

            inputs = []
            for m in months:
                val, is_locked = refs_map.get((cid, 0, m)) or ("", 0)
                m_parts = m.split("-")
                m_display = f"{m_parts[1]}/{m_parts[0]}"
                
                is_sent = c["framework_no"] and (c["framework_no"].lower().strip(), m) in sent_set
                
                lock_icon = "🔒" if is_locked == 1 else "🔓"
                lock_title = "Locked. Click to Unlock" if is_locked == 1 else "Unlocked. Click to Lock"
                input_attrs = "disabled" if is_locked == 1 else ""
                
                if is_sent:
                    input_style = "border: 1px solid #10b981; background: #ecfdf5; color: #065f46;"
                elif is_locked == 1:
                    input_style = "border: 1px solid var(--border); background: #f1f5f9; color: #64748b;"
                else:
                    input_style = "border: 1px solid var(--border);"
                
                inputs.append(f"""
                <div class="ref-input-group" id="ref-group-{cid}-0-{m}" style="display: inline-block; margin: 8px; width: 140px; vertical-align: top;">
                  <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 2px;">
                    <div class="label" style="font-size: 11px; color: var(--text-secondary);">{m_display} {f'<span style="color:#10b981; font-weight:bold; font-size:9px;">(Sent MGS)</span>' if is_sent else ''}</div>
                    <button type="button" class="lock-toggle-btn" data-contract-id="{cid}" data-annex-id="0" data-month="{m}" data-locked="{is_locked}" title="{lock_title}" style="background:none; border:none; cursor:pointer; padding:0; font-size:12px; line-height:1;">
                      {lock_icon}
                    </button>
                  </div>
                  <input type="text" class="ref-input" id="ref-input-{cid}-0-{m}" data-contract-id="{cid}" data-annex-id="0" data-month="{m}" value="{escape(val)}" {input_attrs}
                         placeholder="Enter Ref No..." style="width: 100%; padding: 6px 10px; font-size: 12px; border-radius: 6px; {input_style}">
                </div>
                """)

            inputs_html = "".join(inputs) if inputs else "<div class='muted' style='padding: 8px;'>This contract does not have a valid start/end date.</div>"
            
            cards_html.append(f"""
            <div class="card" style="margin-bottom: 20px; border-left: 4px solid var(--primary);">
              <div style="display: flex; justify-content: space-between; align-items: start; border-bottom: 1px solid var(--border); padding-bottom: 10px; margin-bottom: 10px;">
                <div>
                  <h4 style="margin: 0 0 4px 0; color: var(--text-primary);">Framework Contract: {escape(c["framework_no"])}</h4>
                  <span class="muted">{escape(c["framework_name"] or "")}</span>
                </div>
                <div style="text-align: right;">
                  <div style="font-size: 12px; font-weight: 600;">{escape(c["seller_name"])}</div>
                  <span class="tag" style="margin-left: 0; margin-top: 4px;">{c["start_date"] or "?"} ➔ {c["end_date"] or "?"}</span>
                </div>
              </div>
              <div style="display: flex; flex-wrap: wrap;">
                {inputs_html}
              </div>
            </div>
            """)
        else:
            # Trường hợp 2: Có phụ lục -> Hiển thị từng phụ lục của hợp đồng đó
            for a in c_annexes:
                a_id = a["id"]
                if month:
                    if month_in_range(a["start_date"], a["end_date"], month):
                        months = [month]
                    else:
                        months = []
                else:
                    months = get_months_between(a["start_date"], a["end_date"])
                
                # Filter months list by sent_mgs
                filtered_months = []
                for m in months:
                    is_sent = a["annex_name"] and (a["annex_name"].lower().strip(), m) in sent_set
                    if sent_mgs == "yes":
                        if is_sent:
                            filtered_months.append(m)
                    elif sent_mgs == "no":
                        if not is_sent:
                            filtered_months.append(m)
                    else:
                        filtered_months.append(m)
                months = filtered_months
                
                if not months:
                    continue

                inputs = []
                for m in months:
                    val, is_locked = refs_map.get((cid, a_id, m)) or ("", 0)
                    m_parts = m.split("-")
                    m_display = f"{m_parts[1]}/{m_parts[0]}"
                    
                    is_sent = a["annex_name"] and (a["annex_name"].lower().strip(), m) in sent_set
                    
                    lock_icon = "🔒" if is_locked == 1 else "🔓"
                    lock_title = "Locked. Click to Unlock" if is_locked == 1 else "Unlocked. Click to Lock"
                    input_attrs = "disabled" if is_locked == 1 else ""
                    
                    if is_sent:
                        input_style = "border: 1px solid #10b981; background: #ecfdf5; color: #065f46;"
                    elif is_locked == 1:
                        input_style = "border: 1px solid var(--border); background: #f1f5f9; color: #64748b;"
                    else:
                        input_style = "border: 1px solid var(--border);"
                    
                    inputs.append(f"""
                    <div class="ref-input-group" id="ref-group-{cid}-{a_id}-{m}" style="display: inline-block; margin: 8px; width: 140px; vertical-align: top;">
                      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 2px;">
                        <div class="label" style="font-size: 11px; color: var(--text-secondary);">{m_display} {f'<span style="color:#10b981; font-weight:bold; font-size:9px;">(Sent MGS)</span>' if is_sent else ''}</div>
                        <button type="button" class="lock-toggle-btn" data-contract-id="{cid}" data-annex-id="{a_id}" data-month="{m}" data-locked="{is_locked}" title="{lock_title}" style="background:none; border:none; cursor:pointer; padding:0; font-size:12px; line-height:1;">
                          {lock_icon}
                        </button>
                      </div>
                      <input type="text" class="ref-input" id="ref-input-{cid}-{a_id}-{m}" data-contract-id="{cid}" data-annex-id="{a_id}" data-month="{m}" value="{escape(val)}" {input_attrs}
                             placeholder="Enter Ref No..." style="width: 100%; padding: 6px 10px; font-size: 12px; border-radius: 6px; {input_style}">
                    </div>
                    """)

                inputs_html = "".join(inputs) if inputs else "<div class='muted' style='padding: 8px;'>This annex does not have a valid start/end date.</div>"

                cards_html.append(f"""
                <div class="card" style="margin-bottom: 20px; border-left: 4px solid #06b6d4;">
                  <div style="display: flex; justify-content: space-between; align-items: start; border-bottom: 1px solid var(--border); padding-bottom: 10px; margin-bottom: 10px;">
                    <div>
                      <h4 style="margin: 0 0 4px 0; color: var(--text-primary);">Framework Contract: {escape(c["framework_no"])}</h4>
                      <span style="font-weight: 600; color: #0891b2; font-size: 13px;">➔ Annex: {escape(a["annex_name"] or "")}</span>
                    </div>
                    <div style="text-align: right;">
                      <div style="font-size: 12px; font-weight: 600;">{escape(c["seller_name"])}</div>
                      <span class="tag" style="margin-left: 0; margin-top: 4px; border-color: #a5f3fc; background: #ecfeff; color: #0891b2;">{a["start_date"] or "?"} ➔ {a["end_date"] or "?"}</span>
                    </div>
                  </div>
                  <div style="display: flex; flex-wrap: wrap;">
                    {inputs_html}
                  </div>
                </div>
                """)

    import json
    contracts_json = json.dumps([
        {"id": ct["id"], "framework_no": ct["framework_no"], "seller_vendor_id": ct["seller_vendor_id"]}
        for ct in contracts_filter
    ])
    annexes_json = json.dumps([
        {"id": ax["id"], "annex_name": ax["annex_name"], "framework_no": ax["framework_no"], "contract_id": ax["contract_id"], "seller_vendor_id": ax["seller_vendor_id"]}
        for ax in annexes_filter
    ])

    cards_str = "".join(cards_html) if cards_html else "<div class='card muted'>No active framework contracts or annexes found.</div>"

    sub_nav = """
    <div class="actions" style="margin-bottom: 14px; border-bottom: 1px solid #ddd; padding-bottom: 8px;">
      <a href="/contracts" style="margin-right: 18px; font-weight: bold; color:#666; text-decoration:none;">📑 Contracts List</a>
      <a href="/contracts/references" style="font-weight: bold; color:#0b57d0; border-bottom: 2px solid #0b57d0; padding-bottom: 8px;">🔑 Reference Numbers</a>
    </div>
    """

    vendor_options = []
    for v in vendors_filter:
        selected = "selected" if vendor_id and str(v["id"]) == str(vendor_id) else ""
        label = v["short_name"] or v["company_name"] or v["company_name_vi"]
        vendor_options.append(f'<option value="{v["id"]}" {selected}>{escape(label)}</option>')

    contract_options = []
    for ct in contracts_filter:
        selected = "selected" if contract_id and str(ct["id"]) == str(contract_id) else ""
        contract_options.append(f'<option value="{ct["id"]}" {selected}>{escape(ct["framework_no"])}</option>')

    annex_options = []
    for ax in annexes_filter:
        selected = "selected" if annex_id and str(ax["id"]) == str(annex_id) else ""
        label = f"{ax['annex_name']} ({ax['framework_no']})"
        annex_options.append(f'<option value="{ax["id"]}" {selected}>{escape(label)}</option>')

    filter_form_html = f"""
    <form method="GET" action="/contracts/references" autocomplete="off" class="card" style="margin-bottom: 20px; padding: 16px; background: #fff; border: 1px solid var(--border);">
      <div style="display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-end;">
        <div style="flex: 1; min-width: 180px;">
          <label style="font-weight: 600; font-size: 13px; color: var(--text-secondary); display: block; margin-bottom: 6px;">Company (Seller)</label>
          <select name="vendor_id" style="width: 100%; padding: 8px 12px; border-radius: 6px; border: 1px solid var(--border); font-size: 13px;">
            <option value="">-- all companies --</option>
            {"".join(vendor_options)}
          </select>
        </div>
        <div style="flex: 1; min-width: 180px;">
          <label style="font-weight: 600; font-size: 13px; color: var(--text-secondary); display: block; margin-bottom: 6px;">Framework Contract</label>
          <select name="contract_id" style="width: 100%; padding: 8px 12px; border-radius: 6px; border: 1px solid var(--border); font-size: 13px;">
            <option value="">-- all contracts --</option>
            {"".join(contract_options)}
          </select>
        </div>
        <div style="flex: 1; min-width: 180px;">
          <label style="font-weight: 600; font-size: 13px; color: var(--text-secondary); display: block; margin-bottom: 6px;">Annex</label>
          <select name="annex_id" style="width: 100%; padding: 8px 12px; border-radius: 6px; border: 1px solid var(--border); font-size: 13px;">
            <option value="">-- all annexes --</option>
            {"".join(annex_options)}
          </select>
        </div>
        <div style="flex: 1; min-width: 140px;">
          <label style="font-weight: 600; font-size: 13px; color: var(--text-secondary); display: block; margin-bottom: 6px;">Month</label>
          <input type="month" name="month" value="{escape(month)}" style="width: 100%; padding: 7px 12px; border-radius: 6px; border: 1px solid var(--border); font-size: 13px;">
        </div>
        <div style="flex: 1; min-width: 140px;">
          <label style="font-weight: 600; font-size: 13px; color: var(--text-secondary); display: block; margin-bottom: 6px;">Sent MGS</label>
          <select name="sent_mgs" style="width: 100%; padding: 8px 12px; border-radius: 6px; border: 1px solid var(--border); font-size: 13px;">
            <option value="">-- all --</option>
            <option value="yes" {"selected" if sent_mgs == "yes" else ""}>Sent (Đã gửi)</option>
            <option value="no" {"selected" if sent_mgs == "no" else ""}>Not Sent (Chưa gửi)</option>
          </select>
        </div>
        <div style="display: flex; gap: 8px; margin-top: 8px;">
          <button type="submit" class="btn" style="padding: 8px 16px; font-weight: 600; background: var(--primary); color: white; border-color: var(--primary);">Filter</button>
          <a href="/contracts/references" class="btn btn-secondary" style="padding: 8px 16px; text-decoration: none; text-align: center; display: inline-block;">Clear</a>
        </div>
      </div>
    </form>
    """

    body_html = f"""
    {sub_nav}
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
      <h2 style="margin: 0;">Manage Reference Numbers by Month</h2>
      <span class="muted">Data is autosaved after entry. Use the lock icon to prevent accidental changes.</span>
    </div>
    
    {filter_form_html}
    
    <div class="references-container">
      {cards_str}
    </div>

    <script>
      (function() {{
        const contractsData = {contracts_json};
        const annexesData = {annexes_json};

        const companySel = document.querySelector('select[name="vendor_id"]');
        const contractSel = document.querySelector('select[name="contract_id"]');
        const annexSel = document.querySelector('select[name="annex_id"]');

        function updateDropdowns() {{
          if (!companySel || !contractSel || !annexSel) return;
          const selectedCompany = companySel.value;
          const selectedContract = contractSel.value;
          const selectedAnnex = annexSel.value;

          // 1. Update Contract options
          const currentContractVal = contractSel.value;
          contractSel.innerHTML = '<option value="">-- all contracts --</option>';
          contractsData.forEach(ct => {{
            if (!selectedCompany || String(ct.seller_vendor_id) === String(selectedCompany)) {{
              const opt = document.createElement('option');
              opt.value = ct.id;
              opt.innerText = ct.framework_no;
              if (String(ct.id) === String(currentContractVal)) {{
                opt.selected = true;
              }}
              contractSel.appendChild(opt);
            }}
          }});
          contractSel.value = currentContractVal;

          // 2. Update Annex options
          const currentAnnexVal = annexSel.value;
          annexSel.innerHTML = '<option value="">-- all annexes --</option>';
          annexesData.forEach(ax => {{
            const matchCompany = !selectedCompany || String(ax.seller_vendor_id) === String(selectedCompany);
            const matchContract = !selectedContract || String(ax.contract_id) === String(selectedContract);
            if (matchCompany && matchContract) {{
              const opt = document.createElement('option');
              opt.value = ax.id;
              opt.innerText = ax.annex_name + ' (' + ax.framework_no + ')';
              if (String(ax.id) === String(currentAnnexVal)) {{
                opt.selected = true;
              }}
              annexSel.appendChild(opt);
            }}
          }});
          annexSel.value = currentAnnexVal;
        }}

        if (companySel && contractSel && annexSel) {{
          companySel.addEventListener('change', function() {{
            contractSel.value = "";
            annexSel.value = "";
            updateDropdowns();
          }});

          contractSel.addEventListener('change', function() {{
            const contractId = this.value;
            if (contractId) {{
              const ct = contractsData.find(c => String(c.id) === String(contractId));
              if (ct) {{
                companySel.value = ct.seller_vendor_id;
              }}
            }}
            annexSel.value = "";
            updateDropdowns();
          }});

          annexSel.addEventListener('change', function() {{
            const annexId = this.value;
            if (annexId) {{
              const ax = annexesData.find(a => String(a.id) === String(annexId));
              if (ax) {{
                contractSel.value = ax.contract_id;
                companySel.value = ax.seller_vendor_id;
              }}
            }}
            updateDropdowns();
          }});

          // Run initially to apply default server-side selections
          updateDropdowns();
        }}

        // Save reference number on input change
        document.querySelectorAll('.ref-input').forEach(input => {{
          input.addEventListener('change', function() {{
            const contractId = this.getAttribute('data-contract-id');
            const annexId = this.getAttribute('data-annex-id');
            const month = this.getAttribute('data-month');
            const value = this.value.trim();
            const originalVal = this.defaultValue;
            const targetCell = this;

            // Change border color to signal saving
            targetCell.style.borderColor = '#4f46e5';
            targetCell.style.background = '#e0e7ff';

            fetch('/contracts/save-reference', {{
              method: 'POST',
              headers: {{
                'Content-Type': 'application/json'
              }},
              body: JSON.stringify({{
                contract_id: contractId,
                annex_id: annexId,
                month: month,
                value: value
              }})
            }})
            .then(res => {{
              if (!res.ok) {{
                return res.json().then(err => {{ throw new Error(err.message || 'Error saving Reference Number'); }});
              }}
              return res.json();
            }})
            .then(data => {{
              if (data.status === 'ok') {{
                targetCell.style.borderColor = '#10b981'; // Green border for success
                targetCell.style.background = '#ecfdf5';
                targetCell.defaultValue = value;
                setTimeout(() => {{
                  targetCell.style.borderColor = '';
                  targetCell.style.background = '';
                }}, 1000);
              }} else {{
                throw new Error(data.message || 'Error saving');
              }}
            }})
            .catch(err => {{
              targetCell.style.borderColor = '#ef4444'; // Red border for error
              targetCell.style.background = '#fef2f2';
              alert('Error: ' + err.message);
              targetCell.value = originalVal;
              setTimeout(() => {{
                targetCell.style.borderColor = '';
                targetCell.style.background = '';
              }}, 1500);
            }});
          }});
        }});

        // Lock / Unlock toggle
        document.querySelectorAll('.lock-toggle-btn').forEach(btn => {{
          btn.addEventListener('click', function() {{
            const contractId = this.getAttribute('data-contract-id');
            const annexId = this.getAttribute('data-annex-id');
            const month = this.getAttribute('data-month');
            const currentLocked = parseInt(this.getAttribute('data-locked') || '0');
            const newLocked = currentLocked === 1 ? 0 : 1;
            const targetBtn = this;
            const targetInput = document.getElementById(`ref-input-${{contractId}}-${{annexId}}-${{month}}`);

            fetch('/api/contracts/toggle-reference-lock', {{
              method: 'POST',
              headers: {{
                'Content-Type': 'application/json'
              }},
              body: JSON.stringify({{
                contract_id: contractId,
                annex_id: annexId,
                month: month,
                locked: newLocked
              }})
            }})
            .then(res => res.json())
            .then(data => {{
              if (data.status === 'ok') {{
                targetBtn.setAttribute('data-locked', newLocked);
                if (newLocked === 1) {{
                  targetBtn.innerText = '🔒';
                  targetBtn.title = 'Locked. Click to Unlock';
                  if (targetInput) {{
                    targetInput.disabled = true;
                    targetInput.style.background = '#f1f5f9';
                    targetInput.style.color = '#64748b';
                  }}
                }} else {{
                  targetBtn.innerText = '🔓';
                  targetBtn.title = 'Unlocked. Click to Lock';
                  if (targetInput) {{
                    targetInput.disabled = false;
                    targetInput.style.background = '';
                    targetInput.style.color = '';
                  }}
                }}
              }} else {{
                alert('Error: ' + data.message);
              }}
            }})
            .catch(err => {{
              alert('Connection error: ' + err);
            }});
          }});
        }});

      }})();
    </script>
    """
    
    return layout("Reference Numbers", body_html)


def handle_toggle_reference_lock_ajax(handler):
    import json
    length = int(handler.headers.get("Content-Length", 0))
    body = handler.rfile.read(length).decode("utf-8", errors="ignore")
    
    try:
        data = json.loads(body)
    except Exception:
        send_html(handler, json.dumps({"status": "error", "message": "Invalid JSON"}), status=400)
        return
        
    contract_id = data.get("contract_id")
    annex_id = data.get("annex_id")
    month = data.get("month")
    locked = data.get("locked")
    
    if not contract_id or annex_id is None or not month or locked is None:
        send_html(handler, json.dumps({"status": "error", "message": "Missing parameters"}), status=400)
        return
        
    try:
        contract_id = int(contract_id)
        annex_id = int(annex_id)
        locked = int(locked)
    except ValueError:
        send_html(handler, json.dumps({"status": "error", "message": "Invalid ID or locked format"}), status=400)
        return

    conn = db_connect()
    try:
        cur = conn.cursor()
        
        # Check if record exists. If not, insert with empty reference number
        row = cur.execute("""
            SELECT id FROM contract_references 
            WHERE contract_id=? AND annex_id=? AND month=?
        """, (contract_id, annex_id, month)).fetchone()
        
        if row:
            cur.execute("""
                UPDATE contract_references SET locked = ?, updated_at = datetime('now')
                WHERE contract_id=? AND annex_id=? AND month=?
            """, (locked, contract_id, annex_id, month))
        else:
            cur.execute("""
                INSERT INTO contract_references (contract_id, annex_id, month, reference_number, locked)
                VALUES (?, ?, ?, '', ?)
            """, (contract_id, annex_id, month, locked))
            
        conn.commit()
        send_html(handler, json.dumps({"status": "ok"}), status=200)
    except Exception as e:
        send_html(handler, json.dumps({"status": "error", "message": str(e)}), status=500)
    finally:
        conn.close()


def page_contract_assign_staff(contract_id: int, annex_id: int | None = None, link_id: int | None = None, error_msg: str | None = None, submitted_rows: list[dict] | None = None):
    conn = db_connect()
    try:
        cur = conn.cursor()
        
        # Load contract and vendor info
        contract = cur.execute("SELECT * FROM contracts WHERE id = ?", (contract_id,)).fetchone()
        if not contract:
            return layout("Error", "<div class='card danger'>Contract not found</div>")
            
        vendor_id = contract["seller_vendor_id"]
        vendor_row = cur.execute("SELECT company_name_vi, short_name FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
        vendor_name = vendor_row["company_name_vi"] if vendor_row else f"Vendor ID {vendor_id}"
        
        annex = None
        if annex_id:
            annex = cur.execute("SELECT * FROM contract_annexes WHERE id = ?", (annex_id,)).fetchone()
            
        link = None
        if link_id:
            link = cur.execute("SELECT * FROM contract_staff_links WHERE id = ?", (link_id,)).fetchone()
            
        # Get active staff of this vendor
        staff_rows = cur.execute("""
            SELECT id, full_name_vi, position, paid_leave_total_hours, paid_leave_used_hours
            FROM contract_staff
            WHERE vendor_id = ? AND (status IS NULL OR status <> 'inactive')
            ORDER BY full_name_vi ASC
        """, (vendor_id,)).fetchall()
        
    finally:
        conn.close()
        
    # Build staff dropdown
    staff_opts = ['<option value="">-- select staff --</option>']
    for s in staff_rows:
        tot_h = s["paid_leave_total_hours"] or 0.0
        used_h = s["paid_leave_used_hours"] or 0.0
        rem_h = tot_h - used_h
        rem_lbl = f"{rem_h/8.0:.1f}d remaining"
        staff_opts.append(f'<option value="{s["id"]}">{escape(s["full_name_vi"])} ({escape(s["position"] or "")} - {rem_lbl})</option>')
    staff_options_html = "".join(staff_opts)

    default_jdate = ""
    default_tdate = ""
    if annex:
        default_jdate = annex["start_date"] or contract["start_date"] or ""
        default_tdate = annex["end_date"] or contract["end_date"] or ""
    else:
        default_jdate = contract["start_date"] or ""
        default_tdate = contract["end_date"] or ""

    initial_rows = []
    if submitted_rows is not None and len(submitted_rows) > 0:
        initial_rows = submitted_rows
    elif link:
        initial_rows.append({
            "link_id": link["id"],
            "staff_id": link["staff_id"],
            "joining_date": link["joining_date"] or default_jdate,
            "tentative_leaving_date": link["tentative_leaving_date"] or default_tdate,
            "monthly_rate": link["monthly_rate"],
            "manday_rate": link["manday_rate"],
            "paid_leave_total_hours": link["paid_leave_total_hours"] if link["paid_leave_total_hours"] is not None else 0.0
        })
    else:
        initial_rows.append({
            "link_id": "",
            "staff_id": "",
            "joining_date": default_jdate,
            "tentative_leaving_date": default_tdate,
            "monthly_rate": "",
            "manday_rate": "",
            "paid_leave_total_hours": 0.0
        })

    import json
    initial_rows_json = json.dumps(initial_rows)

    title = "Edit Staff Allocation" if link else "Allocate Staff"
    header_lbl = f"Edit Staff Allocation to Contract No. {contract['framework_no']}" if link else f"Allocate Staff to Contract No. {contract['framework_no']}"
    if annex:
        header_lbl += f" (Annex: {annex['annex_name']})"
        
    error_html = f'<div class="card danger" style="margin-bottom:16px;"><b>Error:</b> {escape(error_msg)}</div>' if error_msg else ""
    
    body = f"""
    {error_html}
    <div class="card" style="padding: 20px;">
      <div class="actions" style="margin-bottom: 12px;">
        <a href="/contract/edit?id={contract_id}">← Back to Contract</a>
      </div>
      
      <h2 style="margin-top: 0; margin-bottom: 4px;">{escape(header_lbl)}</h2>
      <p class="muted" style="margin-top: 0; margin-bottom: 20px;">Vendor: <b>{escape(vendor_name)}</b></p>
      
      <form method="POST" action="/contract/assign-staff/save" id="allocation-form">
        <input type="hidden" name="contract_id" value="{contract_id}">
        <input type="hidden" name="annex_id" value="{annex_id or ''}">
        
        <div style="overflow-x: auto; margin-bottom: 16px;">
          <table id="alloc-table" style="width: 100%; border-collapse: collapse; min-width: 920px;">
            <thead>
              <tr style="background: #f8fafc; border-bottom: 2px solid var(--border); text-align: left;">
                <th style="width: 40px; text-align: center; padding: 8px;">#</th>
                <th style="min-width: 240px; padding: 8px;">Contract Staff Name <span style="color:var(--danger)">*</span></th>
                <th style="min-width: 140px; padding: 8px;">Onboarding Date <span style="color:var(--danger)">*</span></th>
                <th style="min-width: 140px; padding: 8px;">Leaving Date</th>
                <th style="min-width: 140px; padding: 8px;">Monthly Rate (VND)</th>
                <th style="min-width: 130px; padding: 8px;">Man-day Rate (VND)</th>
                <th style="min-width: 110px; padding: 8px;">Paid Leave (h)</th>
                <th style="width: 130px; text-align: center; padding: 8px;">Actions</th>
              </tr>
            </thead>
            <tbody id="alloc-tbody">
            </tbody>
          </table>
        </div>

        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--border);">
          <button type="button" class="btn-secondary" onclick="addAllocRow()" style="font-size: 13px; font-weight: 600; cursor: pointer; padding: 8px 16px;">
            ➕ Add Staff Row
          </button>

          <div class="actions" style="gap: 12px;">
            <button type="submit" class="btn-primary" style="font-size: 14px; padding: 8px 22px;">💾 Save Allocation</button>
            <a class="btn-secondary" href="/contract/edit?id={contract_id}" style="text-decoration:none; padding: 8px 16px;">Cancel</a>
          </div>
        </div>
      </form>
    </div>
    """

    script_js = """
    <script>
    const STAFF_OPTIONS_HTML = __STAFF_OPTIONS__;
    const DEFAULT_JDATE = __DEFAULT_JDATE__;
    const DEFAULT_TDATE = __DEFAULT_TDATE__;
    const INITIAL_ROWS = __INITIAL_ROWS__;

    function renderRow(data, index) {
      data = data || {};
      const tr = document.createElement("tr");
      tr.className = "alloc-row";
      tr.style.borderBottom = "1px solid var(--border)";
      
      const staffId = data.staff_id || "";
      const jDate = data.joining_date !== undefined ? data.joining_date : DEFAULT_JDATE;
      const tDate = data.tentative_leaving_date !== undefined ? data.tentative_leaving_date : DEFAULT_TDATE;
      const mRate = data.monthly_rate !== null && data.monthly_rate !== undefined ? data.monthly_rate : "";
      const dRate = data.manday_rate !== null && data.manday_rate !== undefined ? data.manday_rate : "";
      const plHours = data.paid_leave_total_hours !== null && data.paid_leave_total_hours !== undefined ? data.paid_leave_total_hours : "0";
      const linkId = data.link_id || "";

      tr.innerHTML = `
        <td style="text-align: center; font-weight: bold; color: var(--text-muted); padding: 6px;" class="row-num">${index}</td>
        <td style="padding: 6px;">
          <input type="hidden" name="link_id" value="${linkId}">
          <select name="staff_id" class="staff-select" style="width: 100%; font-size: 13px; padding: 6px;" required>
            ${STAFF_OPTIONS_HTML}
          </select>
        </td>
        <td style="padding: 6px;">
          <input type="date" name="joining_date" value="${jDate}" style="width: 100%; font-size: 13px; padding: 5px;" required>
        </td>
        <td style="padding: 6px;">
          <input type="date" name="tentative_leaving_date" value="${tDate}" style="width: 100%; font-size: 13px; padding: 5px;">
        </td>
        <td style="padding: 6px;">
          <input type="number" step="0.01" name="monthly_rate" value="${mRate}" placeholder="e.g. 45000000" style="width: 100%; font-size: 13px; padding: 5px;">
        </td>
        <td style="padding: 6px;">
          <input type="number" step="0.01" name="manday_rate" value="${dRate}" placeholder="e.g. 2000000" style="width: 100%; font-size: 13px; padding: 5px;">
        </td>
        <td style="padding: 6px;">
          <input type="number" step="0.5" name="paid_leave_total_hours" value="${plHours}" style="width: 100%; font-size: 13px; padding: 5px;">
        </td>
        <td style="text-align: center; white-space: nowrap; padding: 6px;">
          <button type="button" class="btn-secondary duplicate-btn" title="Duplicate this row" style="font-size: 11px; padding: 4px 8px; margin-right: 4px; cursor: pointer;">📋 Copy</button>
          <button type="button" class="btn-danger remove-btn" title="Remove row" style="font-size: 11px; padding: 4px 8px; cursor: pointer;">🗑️ Delete</button>
        </td>
      `;

      if (staffId) {
        const sel = tr.querySelector(".staff-select");
        if (sel) sel.value = staffId;
      }

      tr.querySelector(".duplicate-btn").addEventListener("click", function() {
        duplicateRow(tr);
      });

      tr.querySelector(".remove-btn").addEventListener("click", function() {
        removeRow(tr);
      });

      return tr;
    }

    function addAllocRow(data) {
      data = data || {};
      const tbody = document.getElementById("alloc-tbody");
      const count = tbody.children.length + 1;
      const newTr = renderRow(data, count);
      tbody.appendChild(newTr);
      updateRowNumbers();
    }

    function duplicateRow(sourceTr) {
      const staffId = sourceTr.querySelector('[name="staff_id"]').value;
      const jDate = sourceTr.querySelector('[name="joining_date"]').value;
      const tDate = sourceTr.querySelector('[name="tentative_leaving_date"]').value;
      const mRate = sourceTr.querySelector('[name="monthly_rate"]').value;
      const dRate = sourceTr.querySelector('[name="manday_rate"]').value;
      const plHours = sourceTr.querySelector('[name="paid_leave_total_hours"]').value;

      const newData = {
        staff_id: "", // reset staff_id so user selects next staff member
        joining_date: jDate,
        tentative_leaving_date: tDate,
        monthly_rate: mRate,
        manday_rate: dRate,
        paid_leave_total_hours: plHours,
        link_id: ""
      };

      const tbody = document.getElementById("alloc-tbody");
      const newTr = renderRow(newData, tbody.children.length + 1);
      sourceTr.after(newTr);
      updateRowNumbers();
    }

    function removeRow(tr) {
      const tbody = document.getElementById("alloc-tbody");
      if (tbody.children.length <= 1) {
        alert("At least one allocation row is required.");
        return;
      }
      tr.remove();
      updateRowNumbers();
    }

    function updateRowNumbers() {
      const rows = document.querySelectorAll("#alloc-tbody tr.alloc-row");
      rows.forEach((row, idx) => {
        const numTd = row.querySelector(".row-num");
        if (numTd) numTd.textContent = idx + 1;
      });
    }

    document.addEventListener("DOMContentLoaded", function() {
      if (INITIAL_ROWS && INITIAL_ROWS.length > 0) {
        INITIAL_ROWS.forEach(d => addAllocRow(d));
      } else {
        addAllocRow({});
      }
    });
    </script>
    """.replace("__STAFF_OPTIONS__", json.dumps(staff_options_html))\
       .replace("__DEFAULT_JDATE__", json.dumps(default_jdate))\
       .replace("__DEFAULT_TDATE__", json.dumps(default_tdate))\
       .replace("__INITIAL_ROWS__", initial_rows_json)

    return layout(title, body + script_js)


def handle_contract_assign_staff_save_post(handler):
    form = read_post_form(handler)
    
    contract_id = (form.get("contract_id", [""])[0] or "").strip()
    annex_id = (form.get("annex_id", [""])[0] or "").strip()
    
    if not contract_id.isdigit():
        send_html(handler, layout("Error", "<div class='card danger'>Invalid contract ID</div>"), status=400)
        return
        
    annex_id_int = int(annex_id) if annex_id.isdigit() else None
    
    staff_ids = form.get("staff_id", [])
    joining_dates = form.get("joining_date", [])
    tentative_leaving_dates = form.get("tentative_leaving_date", [])
    monthly_rates = form.get("monthly_rate", [])
    manday_rates = form.get("manday_rate", [])
    paid_leave_total_hours_list = form.get("paid_leave_total_hours", [])
    link_ids = form.get("link_id", [])
    
    submitted_rows = []
    num_rows = max(len(staff_ids), len(joining_dates), len(link_ids), 1)
    for i in range(num_rows):
        sid = (staff_ids[i] if i < len(staff_ids) else "").strip()
        jdate = (joining_dates[i] if i < len(joining_dates) else "").strip()
        tdate = (tentative_leaving_dates[i] if i < len(tentative_leaving_dates) else "").strip()
        m_rate = (monthly_rates[i] if i < len(monthly_rates) else "").strip()
        d_rate = (manday_rates[i] if i < len(manday_rates) else "").strip()
        pl_hours = (paid_leave_total_hours_list[i] if i < len(paid_leave_total_hours_list) else "").strip()
        lid = (link_ids[i] if i < len(link_ids) else "").strip()
        
        submitted_rows.append({
            "link_id": int(lid) if lid.isdigit() else "",
            "staff_id": int(sid) if sid.isdigit() else "",
            "joining_date": jdate,
            "tentative_leaving_date": tdate,
            "monthly_rate": to_float_or_none(m_rate),
            "manday_rate": to_float_or_none(d_rate),
            "paid_leave_total_hours": to_float_or_none(pl_hours) if to_float_or_none(pl_hours) is not None else 0.0
        })

    rows_to_save = [r for r in submitted_rows if r["staff_id"] and r["joining_date"]]
        
    if not rows_to_save:
        send_html(handler, page_contract_assign_staff(int(contract_id), annex_id=annex_id_int, error_msg="Please select at least one staff member and onboarding date.", submitted_rows=submitted_rows), status=400)
        return
        
    conn = db_connect()
    try:
        cur = conn.cursor()
        # Check in-batch overlaps for submitted rows
        for i in range(len(rows_to_save)):
            r1 = rows_to_save[i]
            s1 = r1["joining_date"]
            e1 = r1["tentative_leaving_date"] or "9999-12-31"
            for j in range(i + 1, len(rows_to_save)):
                r2 = rows_to_save[j]
                if r1["staff_id"] == r2["staff_id"]:
                    s2 = r2["joining_date"]
                    e2 = r2["tentative_leaving_date"] or "9999-12-31"
                    if s1 <= e2 and s2 <= e1:
                        s_row = cur.execute("SELECT full_name_vi FROM contract_staff WHERE id = ?", (r1["staff_id"],)).fetchone()
                        s_name = s_row["full_name_vi"] if s_row else f"ID {r1['staff_id']}"
                        msg = f"Duplicate allocation for staff '{s_name}' in submitted form (Row {i+1} and Row {j+1} have overlapping active periods: {r1['joining_date']} → {r1['tentative_leaving_date'] or 'Present'} vs {r2['joining_date']} → {r2['tentative_leaving_date'] or 'Present'})."
                        send_html(handler, page_contract_assign_staff(int(contract_id), annex_id=annex_id_int, error_msg=msg, submitted_rows=submitted_rows), status=400)
                        return

        from staff import check_no_overlap
        for r in rows_to_save:
            ok, msg = check_no_overlap(
                cur,
                link_id_exclude=r["link_id"],
                staff_id=r["staff_id"],
                joining_date=r["joining_date"],
                leaving_date=r["tentative_leaving_date"]
            )
            if not ok:
                send_html(handler, page_contract_assign_staff(int(contract_id), annex_id=annex_id_int, error_msg=msg, submitted_rows=submitted_rows), status=400)
                return
                
        affected_staff_ids = set()
        for r in rows_to_save:
            affected_staff_ids.add(r["staff_id"])
            if r["link_id"]:
                cur.execute("""
                    UPDATE contract_staff_links
                    SET joining_date = ?,
                        tentative_leaving_date = ?,
                        monthly_rate = ?,
                        manday_rate = ?,
                        paid_leave_total_hours = ?,
                        updated_at = ?
                    WHERE id = ?
                """, (r["joining_date"], r["tentative_leaving_date"], r["monthly_rate"], r["manday_rate"], r["paid_leave_total_hours"], now_iso(), r["link_id"]))
                log_action(cur, "UPDATE_CONTRACT_STAFF_LINK", "contract_staff_links", r["link_id"], f"Updated staff allocation ID {r['staff_id']} in contract ID {contract_id}")
            else:
                cur.execute("""
                    INSERT INTO contract_staff_links (staff_id, contract_id, annex_id, monthly_rate, manday_rate, joining_date, tentative_leaving_date, paid_leave_total_hours, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (r["staff_id"], int(contract_id), annex_id_int, r["monthly_rate"], r["manday_rate"], r["joining_date"], r["tentative_leaving_date"], r["paid_leave_total_hours"], now_iso(), now_iso()))
                new_id = cur.lastrowid
                log_action(cur, "CREATE_CONTRACT_STAFF_LINK", "contract_staff_links", new_id, f"Allocated staff ID {r['staff_id']} to contract ID {contract_id}")

        for sid in affected_staff_ids:
            cur.execute("""
                UPDATE contract_staff
                SET paid_leave_total_hours = COALESCE((
                    SELECT SUM(paid_leave_total_hours) FROM contract_staff_links WHERE staff_id = ?
                ), 0.0),
                updated_at = ?
                WHERE id = ?
            """, (sid, now_iso(), sid))
            
        conn.commit()
    finally:
        conn.close()
        
    redirect(handler, f"/contract/edit?id={contract_id}")


def handle_contract_remove_staff_link_post(handler):
    form = read_post_form(handler)
    link_id = (form.get("link_id", [""])[0] or "").strip()
    return_to = (form.get("return_to", ["/contracts"])[0] or "").strip()
    
    if not link_id.isdigit():
        send_html(handler, layout("Error", "<div class='card danger'>Invalid allocation ID</div>"), status=400)
        return
        
    conn = db_connect()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM contract_staff_links WHERE id = ?", (int(link_id),))
        log_action(cur, "DELETE_CONTRACT_STAFF_LINK", "contract_staff_links", int(link_id), f"Removed staff allocation from contract/annex")
        conn.commit()
    finally:
        conn.close()
        
    redirect(handler, return_to)