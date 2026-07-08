from html import escape
from common import (
    db_connect, layout, LIST_LIMIT, now_iso,
    read_post_form, redirect, send_html, safe_return_to
)

# All TEXT fields to preserve leading zeros
# NOTE: We add Vietnamese name/address first (recommended for VN invoices).
VENDOR_TEXT_FIELDS = [
    ("company_name_vi", "Company Name (VI)"),
    ("address_vi", "Address (VI)"),
    ("short_name", "Short Name"),

    ("company_name", "Company Name (EN/Other)"),
    ("address", "Address (EN/Other)"),

    ("tax_id", "Tax ID"),
    ("tel", "TEL"),
    ("bank_name", "Bank Name"),
    ("bank_address", "Bank Address"),
    ("account_name", "Account Name"),
    ("account_number", "Account Number"),
    ("account_currency", "Account Currency"),
]


def parse_yes_no(value: str) -> int:
    v = (value or "").strip().lower()
    if v in ("1", "yes", "true", "y", "on"):
        return 1
    return 0


def page_vendors_list(q: str, status: str, *, return_to: str):
    q = (q or "").strip()
    status = (status or "active").strip().lower()  # active | deactive | all
    if status not in ("active", "deactive", "all"):
        status = "active"

    where = []
    params = []

    if status == "active":
        where.append("is_active = 1")
    elif status == "deactive":
        where.append("is_active = 0")

    if q:
        where.append("""(
            company_name_vi LIKE ? OR address_vi LIKE ?
            OR company_name LIKE ? OR address LIKE ?
            OR tax_id LIKE ? OR tel LIKE ?
            OR bank_name LIKE ? OR bank_address LIKE ?
            OR account_name LIKE ? OR account_number LIKE ?
            OR account_currency LIKE ?
        )""")
        like = f"%{q}%"
        params.extend([like] * 11)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    conn = db_connect()
    try:
        rows = conn.execute(f"""
            SELECT *
            FROM vendors
            {where_sql}
            ORDER BY is_active DESC, company_name_vi ASC, company_name ASC, id DESC
            LIMIT ?
        """, params + [LIST_LIMIT]).fetchall()

        count_row = conn.execute(f"SELECT COUNT(*) AS c FROM vendors {where_sql}", params).fetchone()
        total = int(count_row["c"]) if count_row else 0
    finally:
        conn.close()

    filter_html = f"""
    <div class="card">
      <form class="filters" method="GET" action="/vendors">
        <div style="min-width:320px;">
          <div class="label">Search Vendor</div>
          <input type="text" name="q" placeholder="Name VI/Tax ID/TEL/Account..." value="{escape(q)}" style="width:100%;">
        </div>

        <div>
          <div class="label">Status</div>
          <select name="status">
            <option value="active" {"selected" if status=="active" else ""}>Active</option>
            <option value="deactive" {"selected" if status=="deactive" else ""}>Deactive</option>
            <option value="all" {"selected" if status=="all" else ""}>All</option>
          </select>
        </div>

        <div class="actions">
          <button type="submit">Filter</button>
          <a class="muted" href="/vendors">Reset</a>
          <a href="/vendor/new"><button class="btn-secondary" type="button">+ Add Vendor</button></a>
        </div>
      </form>

      <div class="muted">Total: {total}, displayed: {len(rows)} (limit {LIST_LIMIT})</div>
    </div>
    """

    trs = []
    for idx, r in enumerate(rows, 1):
        tag = ""
        if int(r["is_active"]) == 0:
            tag = ' <span class="tag tag-deactive">Deactive</span>'
        purchasing = "Yes" if int(r["purchasing"] or 0) == 1 else "No"

        deactivate_form = f"""
          <form class="inline" method="POST" action="/vendor/deactivate"
                onsubmit="return confirm('Deactive vendor ID={r["id"]}?');"
                style="margin:0; display:inline-block;">
            <input type="hidden" name="id" value="{r["id"]}">
            <input type="hidden" name="return_to" value="{escape(return_to)}">
            <button class="btn-danger" type="submit" style="font-size:11px; padding: 4px 8px; margin-top:2px;">Deactive</button>
          </form>
        """

        restore_form = f"""
          <form class="inline" method="POST" action="/vendor/restore"
                onsubmit="return confirm('Restore vendor ID={r["id"]}?');"
                style="margin:0; display:inline-block;">
            <input type="hidden" name="id" value="{r["id"]}">
            <input type="hidden" name="return_to" value="{escape(return_to)}">
            <button type="submit" class="btn-secondary" style="font-size:11px; padding: 4px 8px; margin-top:2px;">Restore</button>
          </form>
        """

        actions = f'<a href="/vendor/edit?id={r["id"]}" style="text-decoration:none;"><button type="button" class="btn-secondary" style="font-size:11px; padding: 4px 8px; margin-top:2px;">Edit</button></a>'
        if int(r["is_active"]) == 1:
            actions += " " + deactivate_form
        else:
            actions += " " + restore_form

        acct_line = (r["account_number"] or "")
        cur_line = (r["account_currency"] or "").strip()
        if cur_line:
            acct_line = f"{acct_line} - {cur_line}" if acct_line else cur_line

        # Prefer EN fields for display
        display_name = r["company_name"] or r["company_name_vi"] or ""
        display_addr = r["address"] or r["address_vi"] or ""

        trs.append(f"""
        <tr>
          <td>{idx}</td>
          <td>
            <a href="/vendor/edit?id={r["id"]}">{escape(display_name)}</a>{tag}
            <div class="muted">{escape(display_addr)}</div>
            <div class="muted">Tax ID: {escape(r["tax_id"] or "")}</div>
          </td>
          <td>{escape(r["short_name"] or "")}</td>
          <td>{escape(r["tel"] or "")}</td>
          <td>
            {escape(r["bank_name"] or "")}
            <div class="muted">{escape(r["bank_address"] or "")}</div>
          </td>
          <td>
            {escape(r["account_name"] or "")}
            <div class="muted">{escape(acct_line)}</div>
          </td>
          <td>{escape(purchasing)}</td>
          <td>
            <div class="actions" style="gap:6px; flex-wrap:nowrap; display:flex; align-items:center;">
              {actions}
            </div>
          </td>
        </tr>
        """)

    body = f"""
    {filter_html}
    <table>
      <thead>
        <tr>
          <th>No.</th>
          <th>Vendor</th>
          <th>Short Name</th>
          <th>TEL</th>
          <th>Bank</th>
          <th>Account</th>
          <th>Purchasing</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {''.join(trs) if trs else '<tr><td colspan="8" class="muted">No vendors</td></tr>'}
      </tbody>
    </table>
    """
    return layout("Vendor Management", body)
def page_vendor_form(mode: str, vendor, error_msg: str | None = None):
    if mode not in ("new", "edit"):
        mode = "new"

    def getv(key):
        if vendor is None:
            return ""
        x = vendor[key]
        return "" if x is None else str(x)

    title = "Add Vendor" if mode == "new" else f"Edit Vendor #{vendor['id']}"
    action = "/vendor/create" if mode == "new" else "/vendor/update"

    error_html = f'<div class="card danger"><b>Error:</b> {escape(error_msg)}</div>' if error_msg else ""

    inputs = []
    for key, label in VENDOR_TEXT_FIELDS:
        inputs.append(f"""
          <div>
            <div class="label">{escape(label)} (text)</div>
            <input type="text" name="{escape(key)}" value="{escape(getv(key))}" style="width:100%;" />
          </div>
        """)

    purchasing_val = "0"
    if mode == "edit":
        purchasing_val = "1" if int(vendor["purchasing"] or 0) == 1 else "0"

    purchasing_html = f"""
      <div>
        <div class="label">Purchasing (Yes/No)</div>
        <select name="purchasing">
          <option value="0" {"selected" if purchasing_val=="0" else ""}>No</option>
          <option value="1" {"selected" if purchasing_val=="1" else ""}>Yes</option>
        </select>
      </div>
    """

    status_tag = ""
    if mode == "edit":
        is_active = int(vendor["is_active"])
        status_tag = '<span class="tag">Active</span>' if is_active == 1 else '<span class="tag tag-deactive">Deactive</span>'

    hidden_id = f'<input type="hidden" name="id" value="{vendor["id"]}">' if mode == "edit" else ""

    body = f"""
    {error_html}

    <div class="card">
      <div class="actions" style="margin-bottom:10px;">
        <a href="/vendors">← Vendors</a>
      </div>

      <div class="muted" style="margin-bottom:10px;">
        {status_tag if status_tag else ""}
      </div>

      <form method="POST" action="{action}">
        {hidden_id}

        <div class="grid">
          {''.join(inputs)}
          {purchasing_html}
        </div>

        <div class="actions" style="margin-top:14px;">
          <button type="submit">Save</button>
          <a class="muted" href="/vendors">Cancel</a>
        </div>

        <div class="muted" style="margin-top:10px;">
          Note: Tax ID/TEL/Account Number are all <b>text</b> to preserve leading zeros.<br>
          For matching Vietnamese invoices, please fill out <b>Company Name (VI)</b> and <b>Address (VI)</b>.
        </div>
      </form>
    </div>
    """
    return layout(title, body)


def handle_vendor_create_post(handler):
    form = read_post_form(handler)
    data = {k: (form.get(k, [""])[0] or "").strip() for k, _ in VENDOR_TEXT_FIELDS}
    purchasing = parse_yes_no(form.get("purchasing", ["0"])[0])

    conn = db_connect()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO vendors (
              company_name_vi, address_vi, short_name,
              company_name, address,
              tax_id, tel,
              bank_name, bank_address,
              account_name, account_number, account_currency,
              purchasing,
              is_active, deleted_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, NULL, ?, ?)
        """, (
            data["company_name_vi"], data["address_vi"], data["short_name"],
            data["company_name"], data["address"],
            data["tax_id"], data["tel"],
            data["bank_name"], data["bank_address"],
            data["account_name"], data["account_number"], data["account_currency"],
            purchasing,
            now_iso(), now_iso()
        ))
        conn.commit()
        new_id = cur.lastrowid
    finally:
        conn.close()

    redirect(handler, f"/vendor/edit?id={new_id}")


def handle_vendor_update_post(handler):
    form = read_post_form(handler)
    vendor_id_raw = (form.get("id", [""])[0] or "").strip()
    if not vendor_id_raw.isdigit():
        send_html(handler, layout("Error", "<div class='card danger'>Missing or invalid vendor ID</div>"), status=400)
        return
    vendor_id = int(vendor_id_raw)

    data = {k: (form.get(k, [""])[0] or "").strip() for k, _ in VENDOR_TEXT_FIELDS}
    purchasing = parse_yes_no(form.get("purchasing", ["0"])[0])

    conn = db_connect()
    try:
        cur = conn.cursor()
        row = cur.execute("SELECT id FROM vendors WHERE id=?", (vendor_id,)).fetchone()
        if not row:
            send_html(handler, layout("Not Found", f"<div class='card'>Vendor ID={vendor_id} not found. <a href='/vendors'>Back</a></div>"), status=404)
            return

        cur.execute("""
            UPDATE vendors
            SET company_name_vi=?,
                address_vi=?,
                short_name=?,
                company_name=?,
                address=?,
                tax_id=?,
                tel=?,
                bank_name=?,
                bank_address=?,
                account_name=?,
                account_number=?,
                account_currency=?,
                purchasing=?,
                updated_at=?
            WHERE id=?
        """, (
            data["company_name_vi"], data["address_vi"], data["short_name"],
            data["company_name"], data["address"],
            data["tax_id"], data["tel"],
            data["bank_name"], data["bank_address"],
            data["account_name"], data["account_number"], data["account_currency"],
            purchasing,
            now_iso(), vendor_id
        ))
        conn.commit()
    finally:
        conn.close()

    redirect(handler, f"/vendor/edit?id={vendor_id}")


def handle_vendor_deactivate_post(handler):
    form = read_post_form(handler)
    vendor_id_raw = (form.get("id", [""])[0] or "").strip()
    return_to = safe_return_to((form.get("return_to", [""])[0] or "").strip())

    if not vendor_id_raw.isdigit():
        send_html(handler, layout("Error", "<div class='card danger'>Missing or invalid vendor ID</div>"), status=400)
        return
    vendor_id = int(vendor_id_raw)

    conn = db_connect()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE vendors
            SET is_active=0,
                deleted_at=?,
                updated_at=?
            WHERE id=?
        """, (now_iso(), now_iso(), vendor_id))
        conn.commit()
    finally:
        conn.close()

    redirect(handler, return_to)
def handle_vendor_restore_post(handler):
    form = read_post_form(handler)
    vendor_id_raw = (form.get("id", [""])[0] or "").strip()
    return_to = safe_return_to((form.get("return_to", [""])[0] or "").strip())

    if not vendor_id_raw.isdigit():
        send_html(handler, layout("Error", "<div class='card danger'>Missing or invalid vendor ID</div>"), status=400)
        return
    vendor_id = int(vendor_id_raw)

    conn = db_connect()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE vendors
            SET is_active=1,
                deleted_at=NULL,
                updated_at=?
            WHERE id=?
        """, (now_iso(), vendor_id))
        conn.commit()
    finally:
        conn.close()

    redirect(handler, return_to)