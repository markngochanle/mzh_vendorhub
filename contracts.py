# contracts.py

from html import escape
from common import (
    db_connect, layout, LIST_LIMIT, now_iso,
    read_post_form, redirect, send_html, safe_return_to, log_action
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
                    onsubmit="return confirm('Xóa logic hợp đồng #{r["id"]}?');"
                    style="margin:0; display:inline-block;">
                <input type="hidden" name="id" value="{r["id"]}">
                <input type="hidden" name="return_to" value="{escape(return_to)}">
                <button class="btn-danger" type="submit" style="font-size:11px; padding: 4px 8px; margin-top:2px;">Delete</button>
              </form>
            """
        else:
            actions += f"""
              <form class="inline" method="POST" action="/contract/restore"
                    onsubmit="return confirm('Restore hợp đồng #{r["id"]}?');"
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
            actions = f'<a href="/annex/edit?id={a["id"]}" style="text-decoration:none;"><button type="button" class="btn-secondary" style="font-size:11px; padding: 4px 8px; margin-top:2px;">Edit</button></a>'
            if int(a["is_active"]) == 1:
                actions += f"""
                  <form class="inline" method="POST" action="/annex/delete"
                        onsubmit="return confirm('Xóa logic phụ lục #{a["id"]}?');"
                        style="margin:0; display:inline-block;">
                    <input type="hidden" name="id" value="{a["id"]}">
                    <input type="hidden" name="return_to" value="/contract/edit?id={contract_row["id"]}">
                    <button class="btn-danger" type="submit" style="font-size:11px; padding: 4px 8px; margin-top:2px;">Delete</button>
                  </form>
                """
            else:
                actions += f"""
                  <form class="inline" method="POST" action="/annex/restore"
                        onsubmit="return confirm('Restore phụ lục #{a["id"]}?');"
                        style="margin:0; display:inline-block;">
                    <input type="hidden" name="id" value="{a["id"]}">
                    <input type="hidden" name="return_to" value="/contract/edit?id={contract_row["id"]}">
                    <button type="submit" class="btn-secondary" style="font-size:11px; padding: 4px 8px; margin-top:2px;">Restore</button>
                  </form>
                """

            val_display = f"{int(round(a['value'])):,}" if a["value"] is not None else '<span class="muted">Not set</span>'
            annex_trs.append(f"""
              <tr>
                <td>{idx}</td>
                <td>{escape(a["annex_name"] or "")} {tag}</td>
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
            <div class="label">Start date (HĐ khung)</div>
            <input type="date" name="start_date" value="{escape(gv("start_date"))}" style="width:100%;">
          </div>

          <div>
            <div class="label">End date (HĐ khung)</div>
            <input type="date" name="end_date" value="{escape(gv("end_date"))}" style="width:100%;">
          </div>
        </div>

        <div class="actions" style="margin-top:14px;">
          <button type="submit">Save</button>
          <a class="muted" href="/contracts">Cancel</a>
        </div>
      </form>
    </div>

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
            <div class="label">Start date (Phụ lục)</div>
            <input type="date" name="start_date" value="{escape(gv("start_date"))}" style="width:100%;">
          </div>
          <div>
            <div class="label">End date (Phụ lục)</div>
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
        log_action(cur, "CREATE_CONTRACT", "contracts", new_id, f"Tạo hợp đồng khung mới '{framework_no}' - {framework_name}")
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
        log_action(cur, "UPDATE_CONTRACT", "contracts", int(cid), f"Cập nhật hợp đồng khung '{framework_no}' - {framework_name}")
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
        log_action(cur, "DEACTIVATE_CONTRACT", "contracts", int(cid), f"Hủy kích hoạt hợp đồng khung '{c_name}'")
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
        log_action(cur, "RESTORE_CONTRACT", "contracts", int(cid), f"Khôi phục hoạt động hợp đồng khung '{c_name}'")
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
        log_action(cur, "CREATE_ANNEX", "contract_annexes", new_annex_id, f"Tạo phụ lục mới '{annex_name}' thuộc hợp đồng khung '{c_name}'")
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
        log_action(cur, "UPDATE_ANNEX", "contract_annexes", int(aid), f"Cập nhật phụ lục '{annex_name}' thuộc hợp đồng khung '{c_name}'")
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
        log_action(cur, "DEACTIVATE_ANNEX", "contract_annexes", int(aid), f"Hủy kích hoạt phụ lục '{a_name}'")
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
        log_action(cur, "RESTORE_ANNEX", "contract_annexes", int(aid), f"Khôi phục hoạt động phụ lục '{a_name}'")
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


def page_contract_references():
    conn = db_connect()
    try:
        # Load all active contracts
        contracts_rows = conn.execute("""
            SELECT c.id, c.framework_no, c.framework_name, c.start_date, c.end_date,
                   COALESCE(sv.company_name, sv.company_name_vi) AS seller_name
            FROM contracts c
            JOIN vendors sv ON sv.id = c.seller_vendor_id
            WHERE c.is_active = 1
            ORDER BY c.framework_no ASC
        """).fetchall()

        # Load all active annexes
        annexes_rows = conn.execute("""
            SELECT id, contract_id, annex_name, start_date, end_date
            FROM contract_annexes
            WHERE is_active = 1
            ORDER BY id ASC
        """).fetchall()
        
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
            months = get_months_between(c["start_date"], c["end_date"])
            
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
                         placeholder="Nhập Ref No..." style="width: 100%; padding: 6px 10px; font-size: 12px; border-radius: 6px; {input_style}">
                </div>
                """)

            inputs_html = "".join(inputs) if inputs else "<div class='muted' style='padding: 8px;'>Hợp đồng này chưa có start/end date hợp lệ.</div>"
            
            cards_html.append(f"""
            <div class="card" style="margin-bottom: 20px; border-left: 4px solid var(--primary);">
              <div style="display: flex; justify-content: space-between; align-items: start; border-bottom: 1px solid var(--border); padding-bottom: 10px; margin-bottom: 10px;">
                <div>
                  <h4 style="margin: 0 0 4px 0; color: var(--text-primary);">Hợp đồng khung: {escape(c["framework_no"])}</h4>
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
                annex_id = a["id"]
                months = get_months_between(a["start_date"], a["end_date"])
                
                inputs = []
                for m in months:
                    val, is_locked = refs_map.get((cid, annex_id, m)) or ("", 0)
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
                    <div class="ref-input-group" id="ref-group-{cid}-{annex_id}-{m}" style="display: inline-block; margin: 8px; width: 140px; vertical-align: top;">
                      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 2px;">
                        <div class="label" style="font-size: 11px; color: var(--text-secondary);">{m_display} {f'<span style="color:#10b981; font-weight:bold; font-size:9px;">(Sent MGS)</span>' if is_sent else ''}</div>
                        <button type="button" class="lock-toggle-btn" data-contract-id="{cid}" data-annex-id="{annex_id}" data-month="{m}" data-locked="{is_locked}" title="{lock_title}" style="background:none; border:none; cursor:pointer; padding:0; font-size:12px; line-height:1;">
                          {lock_icon}
                        </button>
                      </div>
                      <input type="text" class="ref-input" id="ref-input-{cid}-{annex_id}-{m}" data-contract-id="{cid}" data-annex-id="{annex_id}" data-month="{m}" value="{escape(val)}" {input_attrs}
                             placeholder="Nhập Ref No..." style="width: 100%; padding: 6px 10px; font-size: 12px; border-radius: 6px; {input_style}">
                    </div>
                    """)

                inputs_html = "".join(inputs) if inputs else "<div class='muted' style='padding: 8px;'>Phụ lục này chưa có start/end date hợp lệ.</div>"

                cards_html.append(f"""
                <div class="card" style="margin-bottom: 20px; border-left: 4px solid #06b6d4;">
                  <div style="display: flex; justify-content: space-between; align-items: start; border-bottom: 1px solid var(--border); padding-bottom: 10px; margin-bottom: 10px;">
                    <div>
                      <h4 style="margin: 0 0 4px 0; color: var(--text-primary);">Hợp đồng khung: {escape(c["framework_no"])}</h4>
                      <span style="font-weight: 600; color: #0891b2; font-size: 13px;">➔ Phụ lục: {escape(a["annex_name"] or "")}</span>
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

    cards_str = "".join(cards_html) if cards_html else "<div class='card muted'>Không có hợp đồng khung hoặc phụ lục nào hoạt động.</div>"

    sub_nav = """
    <div class="actions" style="margin-bottom: 14px; border-bottom: 1px solid #ddd; padding-bottom: 8px;">
      <a href="/contracts" style="margin-right: 18px; font-weight: bold; color:#666; text-decoration:none;">📑 Contracts List</a>
      <a href="/contracts/references" style="font-weight: bold; color:#0b57d0; border-bottom: 2px solid #0b57d0; padding-bottom: 8px;">🔑 Reference Numbers</a>
    </div>
    """

    body_html = f"""
    {sub_nav}
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
      <h2 style="margin: 0;">Quản lý Reference Number theo tháng</h2>
      <span class="muted">Dữ liệu được tự động lưu khi nhập xong. Sử dụng biểu tượng khóa để tránh thay đổi nhầm.</span>
    </div>
    
    <div class="references-container">
      {cards_str}
    </div>

    <script>
      (function() {{
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
                return res.json().then(err => {{ throw new Error(err.message || 'Lỗi khi lưu Reference Number'); }});
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
                throw new Error(data.message || 'Lỗi khi lưu');
              }}
            }})
            .catch(err => {{
              targetCell.style.borderColor = '#ef4444'; // Red border for error
              targetCell.style.background = '#fef2f2';
              alert('Lỗi: ' + err.message);
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
                alert('Lỗi: ' + data.message);
              }}
            }})
            .catch(err => {{
              alert('Lỗi kết nối: ' + err);
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