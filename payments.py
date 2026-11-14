# payments.py
# Centralized payment management views:
#   1. Fixed Price (Milestones) dashboard: /payments/fixed-price
#   2. Recurring Services (Internet/SaaS/Utilities) dashboard: /payments/recurring
#   3. Handlers for recurring cashout actions

from html import escape
from datetime import datetime, date
import calendar
import urllib.parse

from common import (
    db_connect, layout, LIST_LIMIT, now_iso,
    read_post_form, redirect, send_html, safe_return_to, log_action
)

def render_payments_tabs(active_tab: str) -> str:
    """Renders the top navigation sub-bar for Payments."""
    tabs = [
        ("/payments", "📊 Dashboard", active_tab == "dashboard"),
        ("/payments/fixed-price", "🎯 Fixed Price (Milestones)", active_tab == "fixed_price"),
        ("/payments/recurring", "🌐 Recurring Services (Internet / SaaS)", active_tab == "recurring"),
    ]
    links = []
    for url, label, is_active in tabs:
        if is_active:
            links.append(f'<a href="{url}" style="margin-right: 18px; font-weight: bold; color:#0b57d0; border-bottom: 2px solid #0b57d0; padding-bottom: 8px; text-decoration:none;">{label}</a>')
        else:
            links.append(f'<a href="{url}" style="margin-right: 18px; font-weight: 500; color:#64748b; text-decoration:none; padding-bottom: 8px;">{label}</a>')
    
    return f"""
    <div class="actions" style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom: 18px; border-bottom: 1px solid #e2e8f0; padding-bottom: 8px;">
      <div style="display:flex; align-items:center; flex-wrap:wrap;">
        {''.join(links)}
      </div>
      <div>
        <a href="/attendance" style="font-size:12px; font-weight:600; color:#475569; text-decoration:none;" title="View Timesheet & Monthly Payroll">📅 Timesheet & Attendance →</a>
      </div>
    </div>
    """


def page_payments_dashboard(filters: dict) -> str:
    """Payments Dashboard view: renders T&M Cash-out overview."""
    from attendance import page_attendance_payout
    return page_attendance_payout(filters)


# ==============================================================================
# 1. FIXED PRICE (MILESTONES) DASHBOARD
# ==============================================================================
def page_payments_fixed_price(q: str = "", vendor_id: str = "", milestone_type: str = "", status: str = "", *, return_to: str = "/payments/fixed-price"):
    q = (q or "").strip()
    vendor_id = (vendor_id or "").strip()
    milestone_type = (milestone_type or "").strip().upper()
    status = (status or "").strip().upper()

    conn = db_connect()
    try:
        # Load vendors list for filter dropdown
        sellers = conn.execute("""
            SELECT id, company_name, company_name_vi, tax_id
            FROM vendors
            WHERE is_active = 1 AND purchasing = 0
            ORDER BY company_name ASC, company_name_vi ASC
        """).fetchall()

        where = ["c.is_active = 1"]
        params = []

        if q:
            like = f"%{q}%"
            where.append("""(
                m.milestone_name LIKE ? OR m.acceptance_doc_no LIKE ? OR m.note LIKE ?
                OR c.framework_no LIKE ? OR c.framework_name LIKE ?
                OR sv.company_name LIKE ? OR sv.company_name_vi LIKE ? OR sv.tax_id LIKE ?
                OR a.annex_name LIKE ?
            )""")
            params.extend([like, like, like, like, like, like, like, like, like])

        if vendor_id.isdigit():
            where.append("c.seller_vendor_id = ?")
            params.append(int(vendor_id))

        if milestone_type in ("ADVANCE", "DELIVERY", "ACCEPTANCE", "WARRANTY"):
            where.append("m.milestone_type = ?")
            params.append(milestone_type)

        today_str = now_iso()[:10]

        if status == "PAID":
            where.append("(m.status = 'PAID' OR (m.cashout_date IS NOT NULL AND m.cashout_date != ''))")
        elif status == "PENDING":
            where.append("m.status = 'PENDING' AND (m.cashout_date IS NULL OR m.cashout_date = '')")
        elif status == "OVERDUE":
            where.append("m.planned_date < ? AND (m.actual_date IS NULL OR m.actual_date = '') AND m.status != 'PAID' AND (m.cashout_date IS NULL OR m.cashout_date = '')")
            params.append(today_str)
        elif status in ("ACCEPTED", "INVOICED"):
            where.append("m.status = ? AND (m.cashout_date IS NULL OR m.cashout_date = '')")
            params.append(status)

        where_sql = "WHERE " + " AND ".join(where)

        query = f"""
            SELECT
                m.*,
                c.id AS contract_id, c.framework_no, c.framework_name, c.contract_type, c.contract_value,
                a.id AS annex_id, a.annex_name, a.value AS annex_value,
                COALESCE(sv.company_name, sv.company_name_vi) AS seller_name, sv.tax_id AS seller_tax,
                inv.shdon, inv.tg_tttbso AS inv_amount
            FROM contract_milestones m
            JOIN contracts c ON c.id = m.contract_id
            LEFT JOIN contract_annexes a ON a.id = m.annex_id
            JOIN vendors sv ON sv.id = c.seller_vendor_id
            LEFT JOIN invoices inv ON inv.id = m.invoice_id
            {where_sql}
            ORDER BY m.planned_date ASC, m.id DESC
            LIMIT ?
        """
        rows = conn.execute(query, params + [LIST_LIMIT]).fetchall()

        # Aggregate summary metrics across all Fixed Price contracts
        metrics = conn.execute("""
            SELECT
                COUNT(DISTINCT c.id) AS total_contracts,
                COUNT(m.id) AS total_milestones,
                COALESCE(SUM(m.amount), 0.0) AS total_amount,
                COALESCE(SUM(CASE WHEN m.status = 'PAID' OR (m.cashout_date IS NOT NULL AND m.cashout_date != '') THEN m.amount ELSE 0 END), 0.0) AS paid_amount,
                COUNT(CASE WHEN m.planned_date < ? AND (m.actual_date IS NULL OR m.actual_date = '') AND m.status != 'PAID' AND (m.cashout_date IS NULL OR m.cashout_date = '') THEN 1 END) AS overdue_count
            FROM contract_milestones m
            JOIN contracts c ON c.id = m.contract_id
            WHERE c.is_active = 1
        """, (today_str,)).fetchone()

    finally:
        conn.close()

    total_contracts = metrics["total_contracts"] if metrics else 0
    total_amount = float(metrics["total_amount"] if metrics else 0.0)
    paid_amount = float(metrics["paid_amount"] if metrics else 0.0)
    pending_amount = max(0.0, total_amount - paid_amount)
    overdue_count = metrics["overdue_count"] if metrics else 0

    # Vendor select options
    seller_opts = ['<option value="">All Vendors</option>']
    for s in sellers:
        s_name = (s["company_name"] or s["company_name_vi"] or "").strip()
        s_tax = (s["tax_id"] or "").strip()
        label = f"{s_name} ({s_tax})" if s_tax else s_name
        sel = "selected" if str(s["id"]) == vendor_id else ""
        seller_opts.append(f'<option value="{s["id"]}" {sel}>{escape(label)}</option>')

    filter_card = f"""
    <div class="card" style="margin-bottom: 16px;">
      <form class="filters" method="GET" action="/payments/fixed-price">
        <div style="min-width:260px;">
          <div class="label">Search</div>
          <input type="text" name="q" placeholder="Milestone / Contract / Vendor / Doc No..." value="{escape(q)}" style="width:100%;">
        </div>
        <div style="min-width:200px;">
          <div class="label">Vendor</div>
          <select name="vendor_id" style="width:100%;">
            {''.join(seller_opts)}
          </select>
        </div>
        <div>
          <div class="label">Type</div>
          <select name="milestone_type">
            <option value="">All Types</option>
            <option value="ADVANCE" {"selected" if milestone_type=="ADVANCE" else ""}>Advance</option>
            <option value="DELIVERY" {"selected" if milestone_type=="DELIVERY" else ""}>Delivery</option>
            <option value="ACCEPTANCE" {"selected" if milestone_type=="ACCEPTANCE" else ""}>Acceptance</option>
            <option value="WARRANTY" {"selected" if milestone_type=="WARRANTY" else ""}>Warranty</option>
          </select>
        </div>
        <div>
          <div class="label">Status</div>
          <select name="status">
            <option value="">All Statuses</option>
            <option value="OVERDUE" {"selected" if status=="OVERDUE" else ""}>⚠️ Overdue</option>
            <option value="PENDING" {"selected" if status=="PENDING" else ""}>Pending</option>
            <option value="ACCEPTED" {"selected" if status=="ACCEPTED" else ""}>Accepted</option>
            <option value="INVOICED" {"selected" if status=="INVOICED" else ""}>Invoiced</option>
            <option value="PAID" {"selected" if status=="PAID" else ""}>Paid</option>
          </select>
        </div>
        <div class="actions" style="display:flex; align-items:center; width:100%; gap:10px; margin-top:8px;">
          <button type="submit">Filter</button>
          <a class="muted" href="/payments/fixed-price">Reset</a>
          <a href="/invoice/new" style="margin-left:auto; text-decoration:none;"><button class="btn-secondary" type="button" style="color:#0b57d0; border-color:#0b57d0; font-weight:600;">📄 + Import Invoice</button></a>
        </div>
      </form>
    </div>
    """

    trs = []
    today_str = now_iso()[:10]

    for idx, r in enumerate(rows, 1):
        type_badge = {
            "ADVANCE": '<span class="tag tag-info">Advance</span>',
            "DELIVERY": '<span class="tag tag-warning">Delivery</span>',
            "ACCEPTANCE": '<span class="tag tag-active">Acceptance</span>',
            "WARRANTY": '<span class="tag tag-purple">Warranty</span>',
        }.get(r["milestone_type"], '<span class="tag">Other</span>')

        is_paid = r["status"] == "PAID" or bool(r["cashout_date"] and str(r["cashout_date"]).strip())
        status_badge = {
            "PENDING": '<span class="tag">Pending</span>',
            "ACCEPTED": '<span class="tag tag-active">Accepted</span>',
            "INVOICED": '<span class="tag tag-info">Invoiced</span>',
            "PAID": '<span class="tag tag-active" style="background:#047857; color:#fff; border-color:#047857;">✓ Paid</span>',
        }.get("PAID" if is_paid else r["status"], '<span class="tag">Pending</span>')

        # Check overdue status
        is_overdue = False
        overdue_badge = ""
        if r["planned_date"] and not is_paid and not r["actual_date"]:
            if r["planned_date"] < today_str:
                is_overdue = True
                try:
                    p_d = datetime.strptime(r["planned_date"], "%Y-%m-%d").date()
                    t_d = datetime.strptime(today_str, "%Y-%m-%d").date()
                    days = (t_d - p_d).days
                    p_date_str = r["planned_date"]
                    overdue_badge = f'<div style="margin-top:2px;"><span class="tag tag-danger" style="font-size:10px; padding:1px 5px;" title="Planned for {p_date_str}, overdue by {days} days">⚠️ Overdue {days}d</span></div>'
                except Exception:
                    overdue_badge = '<div style="margin-top:2px;"><span class="tag tag-danger" style="font-size:10px; padding:1px 5px;">⚠️ Overdue</span></div>'

        # Contract or annex title link
        if r["annex_id"]:
            parent_link = f"""
            <a href="/annex/edit?id={r['annex_id']}"><b>{escape(r['annex_name'] or 'Annex')}</b></a>
            <div class="muted" style="font-size:11px;">Contract: <a href="/contract/edit?id={r['contract_id']}">{escape(r['framework_no'] or '')}</a></div>
            """
        else:
            parent_link = f"""
            <a href="/contract/edit?id={r['contract_id']}"><b>{escape(r['framework_no'] or 'Contract')}</b></a>
            <div class="muted" style="font-size:11px;">{escape(r['framework_name'] or '')}</div>
            """

        pct_disp = f"{r['percentage']:.1f}%" if r["percentage"] is not None else "-"
        amt_disp = f"{float(r['amount']):,.0f}" if r["amount"] is not None else "0"

        # Linked invoice & Import invoice for this milestone
        contract_target = r["annex_name"] if r["annex_id"] else r["framework_no"]
        import_inv_url = f"/invoice/new?billing_type=FIXED_PRICE&contract_no={urllib.parse.quote(contract_target or '')}&milestone_id={r['id']}&return_to={urllib.parse.quote(return_to)}"

        # Reconciliation check
        recon_badge = ""
        inv_amt = float(r["inv_amount"] or 0)
        mile_amt = float(r["amount"] or 0)
        if r["invoice_id"] and r["inv_amount"] is not None:
            diff = inv_amt - mile_amt
            if abs(diff) < 1.0:
                recon_badge = '<span class="tag tag-active" style="font-size:10px; padding:1px 5px;" title="Invoice amount matches milestone exactly">✓ Matched</span>'
            elif diff > 0:
                recon_badge = f'<span class="tag tag-danger" style="font-size:10px; padding:1px 5px;" title="Invoice ({inv_amt:,.0f}) exceeds milestone ({mile_amt:,.0f}) by {diff:,.0f} VND">⚠️ Mismatch: +{diff:,.0f} VND</span>'
            else:
                recon_badge = f'<span class="tag tag-warning" style="font-size:10px; padding:1px 5px;" title="Invoice ({inv_amt:,.0f}) is less than milestone ({mile_amt:,.0f}) by {abs(diff):,.0f} VND">⚠️ Mismatch: -{abs(diff):,.0f} VND</span>'

        if r["shdon"]:
            inv_display = f"""
            <div>
              <a href="/invoice?id={r['invoice_id']}"><b>{escape(r['shdon'])}</b></a>
              <div class="muted" style="font-size:11px; font-family:monospace;">{inv_amt:,.0f} VND</div>
              {f"<div style='margin-top:2px;'>{recon_badge}</div>" if recon_badge else ""}
              <div style="margin-top:2px;">
                <a href="{import_inv_url}" style="font-size:10px; color:#2563eb; text-decoration:none;" title="Import replacement invoice">↺ Re-import</a>
              </div>
            </div>
            """
        elif r["invoice_id"]:
            inv_display = f"""
            <div>
              <a href="/invoice?id={r['invoice_id']}">Invoice #{r['invoice_id']}</a>
              <div class="muted" style="font-size:11px; font-family:monospace;">{inv_amt:,.0f} VND</div>
              {f"<div style='margin-top:2px;'>{recon_badge}</div>" if recon_badge else ""}
              <div style="margin-top:2px;">
                <a href="{import_inv_url}" style="font-size:10px; color:#2563eb; text-decoration:none;" title="Import replacement invoice">↺ Re-import</a>
              </div>
            </div>
            """
        else:
            inv_display = f"""
            <a href="{import_inv_url}" class="btn-secondary" style="font-size:11px; padding:3px 8px; text-decoration:none; display:inline-flex; align-items:center; gap:4px; font-weight:600; color:#0b57d0; border-color:#0b57d0; background:#f0f7ff; border-radius:6px; white-space:nowrap;" title="Import Invoice for this milestone">
              📥 Import Invoice
            </a>
            """

        # Cashout control
        if is_paid and r["cashout_date"]:
            cashout_html = f"""
            <div style="font-size:11px; font-weight:600; color:var(--success);">
              {escape(r['cashout_date'])}
              <form class="inline" method="POST" action="/contract/milestone/cashout" style="display:inline; margin-left:4px;">
                <input type="hidden" name="id" value="{r['id']}">
                <input type="hidden" name="cashout_date" value="">
                <input type="hidden" name="return_to" value="{escape(return_to)}">
                <button type="submit" title="Cancel cashout date" style="background:none; border:none; color:var(--danger); font-size:11px; cursor:pointer; padding:0;">✕</button>
              </form>
            </div>
            """
        else:
            cashout_html = f"""
            <form class="inline" method="POST" action="/contract/milestone/cashout" style="display:flex; align-items:center; gap:4px;">
              <input type="hidden" name="id" value="{r['id']}">
              <input type="hidden" name="return_to" value="{escape(return_to)}">
              <input type="date" name="cashout_date" value="{today_str}" style="font-size:11px; padding:2px 4px; width:110px;" required>
              <button type="submit" class="btn-secondary" style="font-size:10px; padding:2px 6px;">Cashout</button>
            </form>
            """

        trs.append(f"""
        <tr>
          <td>{idx}</td>
          <td>{parent_link}</td>
          <td>
            <b>{escape(r['seller_name'] or '')}</b>
            <div class="muted" style="font-size:11px;">{escape(r['seller_tax'] or '')}</div>
          </td>
          <td>
            <b>{escape(r['milestone_name'])}</b>
            {f"<div class='muted' style='font-size:11px;'>Doc: <code>{escape(r['acceptance_doc_no'])}</code></div>" if r['acceptance_doc_no'] else ""}
            {f"<div class='muted' style='font-size:11px;'>{escape(r['note'])}</div>" if r['note'] else ""}
          </td>
          <td>{type_badge}</td>
          <td style="text-align:right; font-family:monospace;">{pct_disp}</td>
          <td style="text-align:right; font-family:monospace; font-weight:600;">{amt_disp}</td>
          <td style="font-size:11px;">
            <div>Plan: <span style="{'color:var(--danger); font-weight:600;' if is_overdue else ''}">{escape(r['planned_date'] or '-')}</span></div>
            {f"<div style='color:var(--success); font-weight:500;'>Act: {escape(r['actual_date'])}</div>" if r['actual_date'] else ""}
            {overdue_badge}
          </td>
          <td style="font-size:11px;">{inv_display}</td>
          <td>{cashout_html}</td>
          <td>{status_badge}</td>
        </tr>
        """)

    body = f"""
    {render_payments_tabs("fixed_price")}

    <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap:14px; margin-bottom:16px;">
      <div class="card" style="padding:14px;">
        <div class="muted" style="font-size:12px;">Active Fixed Price Contracts</div>
        <b style="font-size:18px;">{total_contracts}</b>
      </div>
      <div class="card" style="padding:14px;">
        <div class="muted" style="font-size:12px;">Total Milestones Committed</div>
        <b style="font-size:18px; color:#0b57d0; font-family:monospace;">{int(round(total_amount)):,} VND</b>
      </div>
      <div class="card" style="padding:14px;">
        <div class="muted" style="font-size:12px;">Paid to Date (Cashout)</div>
        <b style="font-size:18px; color:var(--success); font-family:monospace;">{int(round(paid_amount)):,} VND</b>
      </div>
      <div class="card" style="padding:14px;">
        <div class="muted" style="font-size:12px;">Remaining Pending Payment</div>
        <b style="font-size:18px; color:var(--danger); font-family:monospace;">{int(round(pending_amount)):,} VND</b>
        {f'<div style="font-size:11px; color:var(--danger); font-weight:600; margin-top:3px;"><a href="/payments/fixed-price?status=OVERDUE" style="color:var(--danger); text-decoration:underline;">⚠️ {overdue_count} overdue milestone{"s" if overdue_count > 1 else ""}</a></div>' if overdue_count > 0 else ""}
      </div>
    </div>

    {filter_card}

    <table>
      <thead>
        <tr>
          <th>No.</th>
          <th>Contract / Annex</th>
          <th>Vendor (Seller)</th>
          <th>Milestone Name</th>
          <th>Type</th>
          <th style="text-align:right;">%</th>
          <th style="text-align:right;">Amount (VND)</th>
          <th>Schedule</th>
          <th>Invoice</th>
          <th>Cashout Date</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {''.join(trs) if trs else '<tr><td colspan="11" class="muted" style="text-align:center; padding:18px;">No milestones found matching criteria.</td></tr>'}
      </tbody>
    </table>
    """
    return layout("Fixed Price Payments", body)


# ==============================================================================
# 2. RECURRING SERVICES DASHBOARD (Internet, SaaS, Maintenance)
# ==============================================================================
def page_payments_recurring(month: str | None = None, q: str = "", vendor_id: str = "", *, return_to: str | None = None):
    # Default to current month YYYY-MM
    now = datetime.now()
    if not month or len(month) != 7 or "-" not in month:
        month = f"{now.year:04d}-{now.month:02d}"

    q = (q or "").strip()
    vendor_id = (vendor_id or "").strip()
    return_to = return_to or f"/payments/recurring?month={month}"

    # Calculate previous and next months
    year_int, month_int = int(month[:4]), int(month[5:7])
    if month_int == 1:
        prev_month = f"{year_int - 1:04d}-12"
    else:
        prev_month = f"{year_int:04d}-{month_int - 1:02d}"

    if month_int == 12:
        next_month = f"{year_int + 1:04d}-01"
    else:
        next_month = f"{year_int:04d}-{month_int + 1:02d}"

    conn = db_connect()
    try:
        # Load vendors list for filter dropdown
        sellers = conn.execute("""
            SELECT id, company_name, company_name_vi, tax_id
            FROM vendors
            WHERE is_active = 1 AND purchasing = 0
            ORDER BY company_name ASC, company_name_vi ASC
        """).fetchall()

        # Load all recurring contracts (standalone or framework)
        c_where = ["c.is_active = 1", "c.billing_type = 'RECURRING'"]
        c_params = []
        if q:
            like = f"%{q}%"
            c_where.append("""(
                c.framework_no LIKE ? OR c.framework_name LIKE ?
                OR sv.company_name LIKE ? OR sv.company_name_vi LIKE ? OR sv.tax_id LIKE ?
            )""")
            c_params.extend([like, like, like, like, like])
        if vendor_id.isdigit():
            c_where.append("c.seller_vendor_id = ?")
            c_params.append(int(vendor_id))

        contracts_rows = conn.execute(f"""
            SELECT
                c.id, c.framework_no, c.framework_name, c.contract_type, c.contract_value,
                c.recurring_fee, c.recurring_period, c.start_date, c.end_date,
                COALESCE(bv.company_name, bv.company_name_vi) AS buyer_name, bv.tax_id AS buyer_tax,
                COALESCE(sv.company_name, sv.company_name_vi) AS seller_name, sv.tax_id AS seller_tax,
                sv.id AS seller_vendor_id
            FROM contracts c
            JOIN vendors bv ON bv.id = c.buyer_vendor_id
            JOIN vendors sv ON sv.id = c.seller_vendor_id
            WHERE {' AND '.join(c_where)}
            ORDER BY c.id DESC
        """, c_params).fetchall()

        # Load all recurring annexes
        a_where = ["a.is_active = 1", "a.billing_type = 'RECURRING'", "c.is_active = 1"]
        a_params = []
        if q:
            like = f"%{q}%"
            a_where.append("""(
                a.annex_name LIKE ? OR c.framework_no LIKE ? OR c.framework_name LIKE ?
                OR sv.company_name LIKE ? OR sv.company_name_vi LIKE ? OR sv.tax_id LIKE ?
            )""")
            a_params.extend([like, like, like, like, like, like])
        if vendor_id.isdigit():
            a_where.append("c.seller_vendor_id = ?")
            a_params.append(int(vendor_id))

        annexes_rows = conn.execute(f"""
            SELECT
                a.id AS annex_id, a.annex_name, a.value AS annex_value,
                a.recurring_fee, a.recurring_period, a.start_date, a.end_date,
                c.id AS contract_id, c.framework_no, c.framework_name,
                COALESCE(bv.company_name, bv.company_name_vi) AS buyer_name, bv.tax_id AS buyer_tax,
                COALESCE(sv.company_name, sv.company_name_vi) AS seller_name, sv.tax_id AS seller_tax,
                sv.id AS seller_vendor_id
            FROM contract_annexes a
            JOIN contracts c ON c.id = a.contract_id
            JOIN vendors bv ON bv.id = c.buyer_vendor_id
            JOIN vendors sv ON sv.id = c.seller_vendor_id
            WHERE {' AND '.join(a_where)}
            ORDER BY a.id DESC
        """, a_params).fetchall()

        # Load payouts for the selected month
        payouts = conn.execute("""
            SELECT * FROM recurring_payouts
            WHERE service_month = ?
        """, (month,)).fetchall()

        # Load invoices that might match for this month (service month/year matches, or invoice date in this month)
        invoices = conn.execute("""
            SELECT id, shdon, tg_tttbso, nlap, seller_mst, seller_name, contract_no
            FROM invoices
            WHERE (service_year = ? AND service_month = ?)
                OR (nlap LIKE ?)
        """, (year_int, month_int, f"{month}%")).fetchall()

    finally:
        conn.close()

    # Index payouts by (contract_id, annex_id)
    payout_map = {}
    for p in payouts:
        key = (p["contract_id"], p["annex_id"])
        payout_map[key] = p

    # Items to display in the recurring table
    items = []

    # Add standalone or direct contracts
    for c in contracts_rows:
        # Check validity for the selected service month
        in_period = True
        if c["start_date"] and str(c["start_date"])[:7] > month:
            in_period = False
        if c["end_date"] and str(c["end_date"])[:7] < month:
            in_period = False

        has_payout = (c["id"], None) in payout_map
        if not in_period and not has_payout:
            continue

        fee = c["recurring_fee"] if (c["recurring_fee"] is not None and c["recurring_fee"] > 0) else (c["contract_value"] or 0.0)
        items.append({
            "is_annex": False,
            "contract_id": c["id"],
            "annex_id": None,
            "no": c["framework_no"],
            "contract_target": c["framework_no"],
            "name": c["framework_name"],
            "buyer": f"{c['buyer_name']} ({c['buyer_tax']})",
            "seller": f"{c['seller_name']} ({c['seller_tax']})",
            "seller_vendor_id": c["seller_vendor_id"],
            "fee": float(fee),
            "period": c["recurring_period"] or "MONTHLY",
            "start_date": c["start_date"],
            "end_date": c["end_date"],
            "is_expired": not in_period,
        })

    # Add annexes
    for a in annexes_rows:
        in_period = True
        if a["start_date"] and str(a["start_date"])[:7] > month:
            in_period = False
        if a["end_date"] and str(a["end_date"])[:7] < month:
            in_period = False

        has_payout = (a["contract_id"], a["annex_id"]) in payout_map
        if not in_period and not has_payout:
            continue

        fee = a["recurring_fee"] if (a["recurring_fee"] is not None and a["recurring_fee"] > 0) else (a["annex_value"] or 0.0)
        items.append({
            "is_annex": True,
            "contract_id": a["contract_id"],
            "annex_id": a["annex_id"],
            "no": f"{a['framework_no']} / {a['annex_name']}",
            "contract_target": a["annex_name"],
            "name": a["annex_name"],
            "buyer": f"{a['buyer_name']} ({a['buyer_tax']})",
            "seller": f"{a['seller_name']} ({a['seller_tax']})",
            "seller_vendor_id": a["seller_vendor_id"],
            "fee": float(fee),
            "period": a["recurring_period"] or "MONTHLY",
            "start_date": a["start_date"],
            "end_date": a["end_date"],
            "is_expired": not in_period,
        })

    # Calculate metrics for the month
    total_services = len(items)
    monthly_commitment = sum(it["fee"] for it in items)
    paid_sum = 0.0
    today_str = now_iso()[:10]

    trs = []
    for idx, it in enumerate(items, 1):
        key = (it["contract_id"], it["annex_id"])
        payout = payout_map.get(key)

        is_paid = bool(payout and payout["status"] == "PAID" and payout["cashout_date"])
        if is_paid:
            paid_sum += it["fee"]

        # Try to find matched invoice
        matched_inv = None
        for inv in invoices:
            c_no_clean = (inv["contract_no"] or "").strip().lower()
            it_no_clean = (it["no"] or "").strip().lower()
            c_target_clean = (it.get("contract_target") or "").strip().lower()
            if c_no_clean and (c_no_clean == it_no_clean or c_no_clean == c_target_clean or c_no_clean in it_no_clean or it_no_clean in c_no_clean):
                matched_inv = inv
                break

        # Quick import invoice URL for this recurring service month
        contract_target = it.get("contract_target") or it["no"]
        import_inv_url = f"/invoice/new?billing_type=RECURRING&contract_no={urllib.parse.quote(contract_target or '')}&service_year={year_int}&service_month={month_int}&return_to={urllib.parse.quote(return_to)}"

        if matched_inv:
            inv_amt = float(matched_inv["tg_tttbso"] or 0)
            fee_amt = float(it["fee"] or 0)
            diff = inv_amt - fee_amt
            if abs(diff) < 1.0:
                recon_badge = '<span class="tag tag-active" style="font-size:10px; padding:1px 5px;" title="Invoice amount matches recurring fee exactly">✓ Matched Fee</span>'
            elif diff > 0:
                recon_badge = f'<span class="tag tag-danger" style="font-size:10px; padding:1px 5px;" title="Invoice ({inv_amt:,.0f}) exceeds recurring fee ({fee_amt:,.0f}) by {diff:,.0f} VND">⚠️ Mismatch: +{diff:,.0f} VND</span>'
            else:
                recon_badge = f'<span class="tag tag-warning" style="font-size:10px; padding:1px 5px;" title="Invoice ({inv_amt:,.0f}) is less than recurring fee ({fee_amt:,.0f}) by {abs(diff):,.0f} VND">⚠️ Mismatch: -{abs(diff):,.0f} VND</span>'

            inv_display = f"""
            <div>
              <a href="/invoice?id={matched_inv['id']}"><b>{escape(matched_inv['shdon'] or 'Inv')}</b></a>
              <div class="muted" style="font-size:11px; font-family:monospace;">{inv_amt:,.0f} VND</div>
              <div style="margin-top:2px;">{recon_badge}</div>
              <div style="margin-top:2px;">
                <a href="{import_inv_url}" style="font-size:10px; color:#2563eb; text-decoration:none;" title="Import replacement invoice">↺ Re-import</a>
              </div>
            </div>
            """
        else:
            inv_display = f"""
            <div>
              <span class="muted" style="font-size:11px; display:block; margin-bottom:3px;">No invoice linked</span>
              <a href="{import_inv_url}" class="btn-secondary" style="font-size:11px; padding:2px 8px; text-decoration:none; display:inline-flex; align-items:center; gap:4px; font-weight:600; color:#0b57d0; border-color:#0b57d0; background:#f0f7ff; border-radius:6px; white-space:nowrap;" title="Import Invoice for this service month">
                📥 Import Invoice
              </a>
            </div>
            """

        # Cashout controls
        if is_paid:
            cashout_html = f"""
            <div style="font-size:11px; font-weight:600; color:var(--success);">
              ✓ Paid on {escape(payout['cashout_date'])}
              <form class="inline" method="POST" action="/payments/recurring/cashout" style="display:inline; margin-left:4px;">
                <input type="hidden" name="contract_id" value="{it['contract_id']}">
                <input type="hidden" name="annex_id" value="{it['annex_id'] or ''}">
                <input type="hidden" name="service_month" value="{month}">
                <input type="hidden" name="action" value="cancel">
                <input type="hidden" name="return_to" value="{escape(return_to)}">
                <button type="submit" title="Cancel payment" style="background:none; border:none; color:var(--danger); font-size:11px; cursor:pointer; padding:0;">✕</button>
              </form>
            </div>
            """
            status_badge = '<span class="tag tag-active" style="background:#047857; color:#fff; border-color:#047857;">✓ Paid</span>'
        else:
            cashout_html = f"""
            <form class="inline" method="POST" action="/payments/recurring/cashout" style="display:flex; align-items:center; gap:4px;">
              <input type="hidden" name="contract_id" value="{it['contract_id']}">
              <input type="hidden" name="annex_id" value="{it['annex_id'] or ''}">
              <input type="hidden" name="service_month" value="{month}">
              <input type="hidden" name="amount" value="{int(round(it['fee']))}">
              <input type="hidden" name="action" value="pay">
              <input type="hidden" name="return_to" value="{escape(return_to)}">
              <input type="date" name="cashout_date" value="{today_str}" style="font-size:11px; padding:2px 4px; width:110px;" required>
              <button type="submit" class="btn-secondary" style="font-size:10px; padding:2px 6px;">Cashout</button>
            </form>
            """
            status_badge = '<span class="tag tag-warning">Pending Payment</span>'

        edit_url = f"/annex/edit?id={it['annex_id']}" if it["is_annex"] else f"/contract/edit?id={it['contract_id']}"

        trs.append(f"""
        <tr>
          <td>{idx}</td>
          <td>
            <a href="{edit_url}"><b>{escape(it['no'] or '')}</b></a>
            <div class="muted" style="font-size:11px;">{escape(it['name'] or '')}</div>
          </td>
          <td>{escape(it['seller'])}</td>
          <td><span class="tag tag-info">{escape(it['period'])}</span></td>
          <td style="text-align:right; font-family:monospace; font-weight:600;">{it['fee']:,.0f} VND</td>
          <td style="font-size:11px;">{escape(it['start_date'] or '')} → {escape(it['end_date'] or '')}</td>
          <td>{inv_display}</td>
          <td>{cashout_html}</td>
          <td>{status_badge}</td>
          <td>
            <a href="{edit_url}"><button type="button" class="btn-secondary" style="font-size:11px; padding:3px 8px;">Edit</button></a>
          </td>
        </tr>
        """)

    remaining_sum = max(0.0, monthly_commitment - paid_sum)

    # Vendor select options for Recurring
    seller_opts = ['<option value="">All Vendors</option>']
    for s in sellers:
        s_name = (s["company_name"] or s["company_name_vi"] or "").strip()
        s_tax = (s["tax_id"] or "").strip()
        label = f"{s_name} ({s_tax})" if s_tax else s_name
        sel = "selected" if str(s["id"]) == vendor_id else ""
        seller_opts.append(f'<option value="{s["id"]}" {sel}>{escape(label)}</option>')

    filter_html = f"""
    <div class="card" style="margin-bottom: 16px;">
      <form class="filters" method="GET" action="/payments/recurring" style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
        <div style="display:flex; align-items:center; gap:8px;">
          <a href="/payments/recurring?month={prev_month}&q={escape(q)}&vendor_id={vendor_id}"><button class="btn-secondary" type="button">← {prev_month}</button></a>
          <input type="month" name="month" value="{month}" onchange="this.form.submit()" style="font-weight:600; font-size:14px; padding:4px 8px;">
          <a href="/payments/recurring?month={next_month}&q={escape(q)}&vendor_id={vendor_id}"><button class="btn-secondary" type="button">{next_month} →</button></a>
        </div>
        <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
          <select name="vendor_id" onchange="this.form.submit()" style="min-width:180px;">
            {''.join(seller_opts)}
          </select>
          <input type="text" name="q" placeholder="Search service / contract / vendor..." value="{escape(q)}" style="min-width:220px;">
          <button type="submit">Filter</button>
          <a class="muted" href="/payments/recurring?month={month}">Reset</a>
          <a href="/invoice/new" style="text-decoration:none;"><button class="btn-secondary" type="button" style="color:#0b57d0; border-color:#0b57d0; font-weight:600;">📄 + Import Invoice</button></a>
        </div>
      </form>
    </div>
    """

    body = f"""
    {render_payments_tabs("recurring")}

    <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap:14px; margin-bottom:16px;">
      <div class="card" style="padding:14px;">
        <div class="muted" style="font-size:12px;">Active Recurring Services</div>
        <b style="font-size:18px;">{total_services}</b>
      </div>
      <div class="card" style="padding:14px;">
        <div class="muted" style="font-size:12px;">Commitment for {month}</div>
        <b style="font-size:18px; color:#0b57d0; font-family:monospace;">{int(round(monthly_commitment)):,} VND</b>
      </div>
      <div class="card" style="padding:14px;">
        <div class="muted" style="font-size:12px;">Paid for {month} (Cashout)</div>
        <b style="font-size:18px; color:var(--success); font-family:monospace;">{int(round(paid_sum)):,} VND</b>
      </div>
      <div class="card" style="padding:14px;">
        <div class="muted" style="font-size:12px;">Pending for {month}</div>
        <b style="font-size:18px; color:var(--danger); font-family:monospace;">{int(round(remaining_sum)):,} VND</b>
      </div>
    </div>

    {filter_html}

    <table>
      <thead>
        <tr>
          <th>No.</th>
          <th>Service / Contract</th>
          <th>Vendor (Seller)</th>
          <th>Billing Period</th>
          <th style="text-align:right;">Monthly Fee (VND)</th>
          <th>Validity Period</th>
          <th>Invoice for {month}</th>
          <th>Cashout</th>
          <th>Status</th>
          <th>Action</th>
        </tr>
      </thead>
      <tbody>
        {''.join(trs) if trs else '<tr><td colspan="10" class="muted" style="text-align:center; padding:18px;">No recurring contracts found. Set contract or annex Billing Type to "Recurring" to manage them here.</td></tr>'}
      </tbody>
    </table>
    """
    return layout(f"Recurring Services - {month}", body)


# ==============================================================================
# 3. RECURRING CASHOUT POST HANDLER
# ==============================================================================
def handle_recurring_cashout_post(handler):
    form = read_post_form(handler)
    contract_id_raw = (form.get("contract_id", [""])[0] or "").strip()
    annex_id_raw = (form.get("annex_id", [""])[0] or "").strip()
    service_month = (form.get("service_month", [""])[0] or "").strip()
    cashout_date = (form.get("cashout_date", [""])[0] or "").strip() or None
    amount_raw = (form.get("amount", ["0"])[0] or "0").strip()
    action = (form.get("action", ["pay"])[0] or "pay").strip().lower()
    return_to = safe_return_to((form.get("return_to", [""])[0] or f"/payments/recurring?month={service_month}").strip())

    if not contract_id_raw.isdigit() or not service_month:
        send_html(handler, layout("Error", "<div class='card danger'>Missing contract ID or service month.</div>"), status=400)
        return

    contract_id = int(contract_id_raw)
    annex_id = int(annex_id_raw) if annex_id_raw.isdigit() else None
    try:
        amount = float(amount_raw.replace(",", ""))
    except ValueError:
        amount = 0.0

    conn = db_connect()
    try:
        cur = conn.cursor()

        # Check existing payout record
        if annex_id is not None:
            existing = cur.execute("""
                SELECT id FROM recurring_payouts
                WHERE contract_id = ? AND annex_id = ? AND service_month = ?
            """, (contract_id, annex_id, service_month)).fetchone()
        else:
            existing = cur.execute("""
                SELECT id FROM recurring_payouts
                WHERE contract_id = ? AND annex_id IS NULL AND service_month = ?
            """, (contract_id, service_month)).fetchone()

        if action == "cancel":
            if existing:
                cur.execute("DELETE FROM recurring_payouts WHERE id = ?", (existing["id"],))
                log_action(cur, "CANCEL_RECURRING_CASHOUT", "recurring_payouts", existing["id"], f"Cancelled recurring cashout for contract #{contract_id} (Month: {service_month})")
        else:
            # Validate service month against contract validity
            c_row = cur.execute("SELECT start_date, end_date FROM contracts WHERE id = ?", (contract_id,)).fetchone()
            a_row = None
            if annex_id is not None:
                a_row = cur.execute("SELECT start_date, end_date FROM contract_annexes WHERE id = ?", (annex_id,)).fetchone()

            s_date = (a_row and a_row["start_date"]) or (c_row and c_row["start_date"])
            e_date = (a_row and a_row["end_date"]) or (c_row and c_row["end_date"])

            if s_date and service_month < str(s_date)[:7]:
                send_html(handler, layout("Error", f"<div class='card danger'>Cannot record payment: Service month {service_month} is prior to contract start date ({s_date}).</div>"), status=400)
                return
            if e_date and service_month > str(e_date)[:7]:
                send_html(handler, layout("Error", f"<div class='card danger'>Cannot record payment: Contract expired on {e_date}. Service month {service_month} does not exist for this contract. Please renew first.</div>"), status=400)
                return

            # Pay / cashout
            if existing:
                cur.execute("""
                    UPDATE recurring_payouts
                    SET status = 'PAID', cashout_date = ?, amount = ?, updated_at = ?
                    WHERE id = ?
                """, (cashout_date or now_iso()[:10], amount, now_iso(), existing["id"]))
                pid = existing["id"]
            else:
                cur.execute("""
                    INSERT INTO recurring_payouts (
                        contract_id, annex_id, service_month, amount, status, cashout_date, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, 'PAID', ?, ?, ?)
                """, (contract_id, annex_id, service_month, amount, cashout_date or now_iso()[:10], now_iso(), now_iso()))
                pid = cur.lastrowid

            log_action(cur, "RECURRING_CASHOUT", "recurring_payouts", pid, f"Recorded recurring cashout of {amount:,.0f} VND for contract #{contract_id} (Month: {service_month})")

        conn.commit()
    finally:
        conn.close()

    redirect(handler, return_to)
