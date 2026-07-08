# invoices.py
# Invoice pages + logic highlight buyer/seller mismatch vs vendors
# Compare using Vietnamese fields:
#   - Buyer  vs vendor(purchasing=1, active)  using (company_name_vi, tax_id, address_vi)
#   - Seller vs vendor(purchasing=0, active)  using (company_name_vi, tax_id, address_vi)

from datetime import date, datetime
from html import escape
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
import json
import calendar

from common import (
    db_connect, layout, parse_int_or_none, fmt_money,
    LIST_LIMIT, read_post_form, send_html, redirect, safe_return_to, now_iso
)


# -------------------- Normalization (IMPORTANT) --------------------
def norm_text(s: str | None) -> str:
    """
    Normalize VN text for reliable comparison:
    - strip
    - Unicode NFC normalization (handles Vietnamese composed/decomposed forms)
    - replace NBSP with space
    - remove zero-width characters + BOM
    - collapse multiple whitespace
    - case-insensitive (casefold)
    """
    if s is None:
        return ""
    s = s.strip()

    # normalize unicode
    s = unicodedata.normalize("NFC", s)

    # normalize spaces + remove invisible characters
    s = s.replace("\u00A0", " ")  # NBSP -> space
    s = s.replace("\u200B", "")   # zero-width space
    s = s.replace("\u200C", "")   # zero-width non-joiner
    s = s.replace("\u200D", "")   # zero-width joiner
    s = s.replace("\ufeff", "")   # BOM

    # collapse whitespace
    s = " ".join(s.split())

    return s.casefold()


def norm_tax(s: str | None) -> str:
    """
    Normalize Tax ID as TEXT:
    - keep leading zeros
    - remove ALL whitespace
    - Unicode NFC
    """
    if s is None:
        return ""
    s = s.strip()
    s = unicodedata.normalize("NFC", s)
    s = s.replace("\u00A0", " ").replace("\ufeff", "")
    s = "".join(s.split())  # remove all whitespace
    return s


# -------------------- Vendor matching sets --------------------
def build_vendor_sets(conn):
    """
    Build 2 sets for O(1) match:
      buyer_vendor_set  = purchasing=1 (Yes), is_active=1
      seller_vendor_set = purchasing=0 (No),  is_active=1

    Key format: (name_vi_norm, tax_norm, address_vi_norm)
    """
    rows = conn.execute("""
        SELECT company_name_vi, tax_id, address_vi, purchasing
        FROM vendors
        WHERE is_active = 1
    """).fetchall()

    buyer_set = set()
    seller_set = set()

    for r in rows:
        key = (
            norm_text(r["company_name_vi"]),
            norm_tax(r["tax_id"]),
            norm_text(r["address_vi"]),
        )
        if int(r["purchasing"] or 0) == 1:
            buyer_set.add(key)
        else:
            seller_set.add(key)

    return buyer_set, seller_set


def match_party(party_name, party_tax, party_addr, vendor_set: set[tuple[str, str, str]]):
    """
    Must match ALL 3 fields exactly after normalization.
    If any field missing/blank => mismatch.
    """
    name_n = norm_text(party_name)
    tax_n = norm_tax(party_tax)
    addr_n = norm_text(party_addr)

    if not name_n or not tax_n or not addr_n:
        return False, "Missing Name/Tax ID/Address"

    key = (name_n, tax_n, addr_n)
    if key in vendor_set:
        return True, "OK"

    return False, "Does not match vendor (VI name/address + Tax ID)"


def check_invoice_payroll_reconciliation(conn, contract_no_str, year, month, invoice_amount):
    """
    Reconciliation check: Compare invoice total payment amount with the sum of staff monthly payroll amount.
    Returns: (status, locked_sum, all_sum, message)
      status: 'ok', 'mismatch', 'no_payroll', 'no_contract'
    """
    if not contract_no_str or year is None or month is None:
        return 'no_payroll', 0.0, 0.0, "Missing contract number or service month."

    month_str = f"{year:04d}-{month:02d}"
    contract_no_clean = contract_no_str.strip()

    # Query staff belonging to a contract with this framework_no
    staff_by_contract = conn.execute("""
        SELECT s.id 
        FROM contract_staff s
        JOIN contracts c ON c.id = s.contract_id
        WHERE LOWER(TRIM(c.framework_no)) = ?
    """, (contract_no_clean.lower(),)).fetchall()

    # Query staff belonging to an annex with this annex_name
    staff_by_annex = conn.execute("""
        SELECT s.id 
        FROM contract_staff s
        JOIN contract_annexes a ON a.id = s.annex_id
        WHERE LOWER(TRIM(a.annex_name)) = ?
    """, (contract_no_clean.lower(),)).fetchall()

    staff_ids = [r["id"] for r in (staff_by_contract + staff_by_annex)]

    if not staff_ids:
        # Fallback to partial matches
        staff_by_contract_like = conn.execute("""
            SELECT s.id 
            FROM contract_staff s
            JOIN contracts c ON c.id = s.contract_id
            WHERE c.framework_no LIKE ?
        """, (f"%{contract_no_clean}%",)).fetchall()

        staff_by_annex_like = conn.execute("""
            SELECT s.id 
            FROM contract_staff s
            JOIN contract_annexes a ON a.id = s.annex_id
            WHERE a.annex_name LIKE ?
        """, (f"%{contract_no_clean}%",)).fetchall()

        staff_ids = [r["id"] for r in (staff_by_contract_like + staff_by_annex_like)]

    if not staff_ids:
        return 'no_contract', 0.0, 0.0, f"No matching contract or annex found for '{contract_no_str}'."

    placeholders = ",".join("?" for _ in staff_ids)

    # Sum locked payroll
    locked_row = conn.execute(f"""
        SELECT SUM(total_amount) AS total 
        FROM monthly_attendance_summary
        WHERE month = ? AND locked = 1 AND staff_id IN ({placeholders})
    """, [month_str] + staff_ids).fetchone()

    locked_sum = float(locked_row["total"] or 0.0)

    # Sum all payroll (locked or unlocked)
    all_row = conn.execute(f"""
        SELECT SUM(total_amount) AS total 
        FROM monthly_attendance_summary
        WHERE month = ? AND staff_id IN ({placeholders})
    """, [month_str] + staff_ids).fetchone()

    all_sum = float(all_row["total"] or 0.0)

    inv_amt_val = float(invoice_amount or 0.0)

    if locked_sum > 0 and abs(locked_sum - inv_amt_val) < 1.0:
        return 'ok', locked_sum, all_sum, "Locked monthly payroll matches invoice amount exactly."
    elif locked_sum > 0:
        return 'mismatch', locked_sum, all_sum, f"Locked payroll sum ({fmt_money(locked_sum)} VND) does not match invoice amount ({fmt_money(inv_amt_val)} VND)."
    else:
        if all_sum > 0:
            return 'no_payroll', 0.0, all_sum, f"Found unlocked payroll sum ({fmt_money(all_sum)} VND) for this period, but it is not locked yet."
        else:
            return 'no_payroll', 0.0, 0.0, "No monthly payroll records found for this contract/annex in this month."


def get_mgs_details(conn, inv) -> tuple[str, str, str, str, str, str]:
    contract_no_clean = (inv["contract_no"] or "").strip()
    year = inv["service_year"]
    month = inv["service_month"]
    
    ref_num = ""
    tax_id = (inv["seller_mst"] or "").strip()
    vendor_en_name = ""
    amt_str = fmt_money(inv["tg_tttbso"])
    currency = (inv["dvtte"] or "VND").strip()
    inv_no = (inv["shdon"] or "").strip()
    
    if year is not None and month is not None:
        month_str = f"{year:04d}-{month:02d}"
        
        # 1. Tìm Reference Number
        c_row = conn.execute("""
            SELECT id FROM contracts 
            WHERE LOWER(TRIM(framework_no)) = ? AND is_active = 1
        """, (contract_no_clean.lower(),)).fetchone()
        
        if c_row:
            cid = c_row["id"]
            has_annex = conn.execute("""
                SELECT id FROM contract_annexes 
                WHERE contract_id = ? AND is_active = 1
            """, (cid,)).fetchone()
            
            if not has_annex:
                ref_row = conn.execute("""
                    SELECT reference_number FROM contract_references
                    WHERE contract_id = ? AND annex_id = 0 AND month = ?
                """, (cid, month_str)).fetchone()
                if ref_row:
                    ref_num = ref_row["reference_number"]
            else:
                ref_row = conn.execute("""
                    SELECT reference_number FROM contract_references
                    WHERE contract_id = ? AND month = ? AND annex_id > 0
                    LIMIT 1
                """, (cid, month_str)).fetchone()
                if ref_row:
                    ref_num = ref_row["reference_number"]
        else:
            a_row = conn.execute("""
                SELECT contract_id, id FROM contract_annexes
                WHERE LOWER(TRIM(annex_name)) = ? AND is_active = 1
            """, (contract_no_clean.lower(),)).fetchone()
            if a_row:
                ref_row = conn.execute("""
                    SELECT reference_number FROM contract_references
                    WHERE contract_id = ? AND annex_id = ? AND month = ?
                """, (a_row["contract_id"], a_row["id"], month_str)).fetchone()
                if ref_row:
                    ref_num = ref_row["reference_number"]

    # 2. Tìm English Name và Short Name của Vendor
    vendor_short_name = ""
    if tax_id:
        v_row = conn.execute("""
            SELECT company_name, short_name FROM vendors 
            WHERE LOWER(TRIM(tax_id)) = ? AND is_active = 1
        """, (tax_id.lower(),)).fetchone()
        if v_row:
            vendor_en_name = v_row["company_name"] or ""
            vendor_short_name = v_row["short_name"] or ""
            
    if not vendor_en_name:
        vendor_en_name = inv["seller_name"] or ""
    if not vendor_short_name:
        vendor_short_name = vendor_en_name

    # 3. Tính chuỗi tháng năm định dạng MMYYYY
    mmyyyy = ""
    if year is not None and month is not None:
        mmyyyy = f"{month:02d}{year:04d}"

    return ref_num, tax_id, vendor_en_name, amt_str, currency, inv_no, vendor_short_name, mmyyyy


def format_date_mgs(date_str):
    if not date_str:
        return ""
    try:
        dt = datetime.strptime(date_str.strip(), "%Y-%m-%d")
        return dt.strftime("%d-%b-%Y")
    except Exception:
        return date_str


def get_service_period(year, month):
    if not year or not month:
        return ""
    try:
        month_name = datetime(year, month, 1).strftime("%b")
        last_day = calendar.monthrange(year, month)[1]
        year_short = datetime(year, month, 1).strftime("%y")
        return f"From 1-{month_name}-{year_short} to {last_day}-{month_name}-{year_short}"
    except Exception:
        return ""


def get_mgs_data_dict(conn, inv) -> dict:
    contract_no = (inv["contract_no"] or "").strip()
    year = inv["service_year"]
    month = inv["service_month"]
    inv_no = (inv["shdon"] or "").strip()
    invoice_date_formatted = format_date_mgs(inv["nlap"])
    service_period = get_service_period(year, month)
    
    buyer_id = None
    seller_id = None
    
    resolved_framework_no = ""
    resolved_annex_name = ""
    
    if contract_no:
        c_row = conn.execute("""
            SELECT id, framework_no, buyer_vendor_id, seller_vendor_id FROM contracts 
            WHERE LOWER(TRIM(framework_no)) = ? AND is_active = 1
        """, (contract_no.lower(),)).fetchone()
        
        if c_row:
            buyer_id = c_row["buyer_vendor_id"]
            seller_id = c_row["seller_vendor_id"]
            resolved_framework_no = c_row["framework_no"]
            
            # Check if there is an annex for this month from contract_references
            if year is not None and month is not None:
                month_str = f"{year:04d}-{month:02d}"
                ref_row = conn.execute("""
                    SELECT annex_id FROM contract_references
                    WHERE contract_id = ? AND month = ? AND annex_id > 0
                    LIMIT 1
                """, (c_row["id"], month_str)).fetchone()
                if ref_row:
                    annex_row = conn.execute("SELECT annex_name FROM contract_annexes WHERE id = ?", (ref_row["annex_id"],)).fetchone()
                    if annex_row:
                        resolved_annex_name = annex_row["annex_name"]
            
            # Fallback if no reference record: check date ranges of active annexes
            if not resolved_annex_name and year is not None and month is not None:
                annexes = conn.execute("SELECT id, annex_name, start_date, end_date FROM contract_annexes WHERE contract_id = ? AND is_active = 1", (c_row["id"],)).fetchall()
                target_date = date(year, month, 15) # middle of the month
                for annex in annexes:
                    try:
                        s_dt = datetime.strptime(annex["start_date"], "%Y-%m-%d").date() if annex["start_date"] else None
                        e_dt = datetime.strptime(annex["end_date"], "%Y-%m-%d").date() if annex["end_date"] else None
                        if s_dt and e_dt:
                            if s_dt <= target_date <= e_dt:
                                resolved_annex_name = annex["annex_name"]
                                break
                        elif s_dt and not e_dt:
                            if s_dt <= target_date:
                                resolved_annex_name = annex["annex_name"]
                                break
                    except Exception:
                        pass
        else:
            a_row = conn.execute("""
                SELECT id, contract_id, annex_name FROM contract_annexes
                WHERE LOWER(TRIM(annex_name)) = ? AND is_active = 1
            """, (contract_no.lower(),)).fetchone()
            if a_row:
                resolved_annex_name = a_row["annex_name"]
                c_row2 = conn.execute("""
                    SELECT framework_no, buyer_vendor_id, seller_vendor_id FROM contracts 
                    WHERE id = ?
                """, (a_row["contract_id"],)).fetchone()
                if c_row2:
                    buyer_id = c_row2["buyer_vendor_id"]
                    seller_id = c_row2["seller_vendor_id"]
                    resolved_framework_no = c_row2["framework_no"]
                    
    # Fallback if both are empty but contract_no is present
    if contract_no and not resolved_framework_no and not resolved_annex_name:
        resolved_framework_no = contract_no

    seller_mst = (inv["seller_mst"] or "").strip()
    if not seller_id and seller_mst:
        v_row = conn.execute("SELECT id FROM vendors WHERE LOWER(TRIM(tax_id)) = ? AND purchasing = 0 AND is_active = 1", (seller_mst.lower(),)).fetchone()
        if v_row:
            seller_id = v_row["id"]
            
    if not buyer_id:
        b_row = conn.execute("SELECT id FROM vendors WHERE purchasing = 1 AND is_active = 1 LIMIT 1").fetchone()
        if b_row:
            buyer_id = b_row["id"]

    vendor_details = {
        "company_name": inv["seller_name"] or "",
        "tax_id": seller_mst,
        "address": inv["seller_address"] or "",
        "tel": "",
        "bank_name": "",
        "bank_address": "",
        "account_name": "",
        "account_number": "",
        "account_currency": "",
        "short_name": ""
    }
    if seller_id:
        s_row = conn.execute("""
            SELECT company_name, tax_id, address, tel, bank_name, bank_address, account_name, account_number, account_currency, short_name 
            FROM vendors WHERE id = ?
        """, (seller_id,)).fetchone()
        if s_row:
            for k in vendor_details.keys():
                if s_row[k] is not None:
                    vendor_details[k] = str(s_row[k]).strip()
                    
    buyer_details = {
        "company_name": inv["buyer_name"] or "",
        "tax_id": (inv["buyer_mst"] or "").strip(),
        "address": inv["buyer_address"] or ""
    }
    if buyer_id:
        b_row = conn.execute("""
            SELECT company_name, tax_id, address 
            FROM vendors WHERE id = ?
        """, (buyer_id,)).fetchone()
        if b_row:
            for k in buyer_details.keys():
                if b_row[k] is not None:
                    buyer_details[k] = str(b_row[k]).strip()

    ref_num, _, _, _, _, _, short_name, mmyyyy = get_mgs_details(conn, inv)
    if not vendor_details["short_name"]:
        vendor_details["short_name"] = short_name

    currency = (inv["dvtte"] or "VND").strip()
    
    def fmt_val(val):
        if val is None or val == "":
            return "-"
        try:
            return f"{float(val):,.2f}"
        except Exception:
            return str(val)

    tax_row = conn.execute("SELECT tsuat FROM invoice_tax_lines WHERE invoice_id = ? LIMIT 1", (inv["id"],)).fetchone()
    vat_rate = tax_row["tsuat"] if tax_row else ""
    if not vat_rate:
        try:
            tcthue = float(inv["tg_tcthue"] or 0)
            tthue = float(inv["tg_tthue"] or 0)
            if tcthue > 0 and tthue > 0:
                vat_rate = f"{int(round((tthue / tcthue) * 100))}%"
        except Exception:
            pass
            
    vat_amt_str = fmt_val(inv["tg_tthue"])
    if vat_amt_str == "0.00" or not inv["tg_tthue"]:
        vat_amt_str = "-"
        
    vat_rate_str = vat_rate if vat_rate else "-"
    if vat_amt_str == "-":
        vat_rate_str = "-"

    # Format the contract and annex text for PDF
    contract_display = ""
    if resolved_framework_no and resolved_annex_name:
        contract_display = f"{resolved_framework_no} and {resolved_annex_name}"
    elif resolved_framework_no:
        contract_display = resolved_framework_no
    elif resolved_annex_name:
        contract_display = resolved_annex_name

    content_of_work = "Software development service"
    if contract_display:
        content_of_work = f"Software development service (According to Contract Number: {contract_display})"

    return {
        "id": inv["id"],
        "sent_to_mgs": int(inv["sent_to_mgs"] or 0),
        "vendor": vendor_details,
        "buyer": buyer_details,
        "contract_no": contract_display,
        "ref_num": ref_num,
        "service_period": service_period,
        "content_of_work": content_of_work,
        "currency": currency,
        "invoice_no": inv_no,
        "invoice_date": invoice_date_formatted,
        "invoice_amount": fmt_val(inv["tg_tcthue"]),
        "invoice_vat_rate": vat_rate_str,
        "invoice_vat_amount": vat_amt_str,
        "total_amount": fmt_val(inv["tg_tttbso"]),
        "mmyyyy": mmyyyy
    }


# -------------------- Pages --------------------
def page_invoices_list(filters: dict, *, return_to: str):
    def val(x):
        return "" if x is None else str(x)

    year_raw = filters.get("year")
    month_raw = filters.get("month")
    day_raw = filters.get("day")
    q_raw = filters.get("q")

    # Default year only when first open "/" with no params at all
    if year_raw is None and month_raw is None and day_raw is None and q_raw is None:
        today = date.today()
        year_raw = str(today.year)
        month_raw = ""
        day_raw = ""

    year = parse_int_or_none(year_raw)
    month = parse_int_or_none(month_raw)
    day = parse_int_or_none(day_raw)
    q = (q_raw or "").strip()

    where = []
    params = []

    if year is not None:
        where.append("service_year = ?")
        params.append(year)
    if month is not None:
        where.append("service_month = ?")
        params.append(month)
    if day is not None:
        where.append("service_day = ?")
        params.append(day)

    if q:
        where.append("""(
            khhdon LIKE ? OR shdon LIKE ? OR seller_name LIKE ? OR seller_mst LIKE ?
            OR buyer_name LIKE ? OR buyer_mst LIKE ? OR contract_no LIKE ?
        )""")
        like = f"%{q}%"
        params.extend([like, like, like, like, like, like, like])

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    conn = db_connect()
    try:
        buyer_vendor_set, seller_vendor_set = build_vendor_sets(conn)

        rows = conn.execute(f"""
            SELECT
              id,
              service_year, service_month, service_day,
              contract_no,
              khhdon, shdon, nlap, dvtte,
              seller_name, seller_mst, seller_address,
              buyer_name, buyer_mst, buyer_address,
              tg_tcthue, tg_tthue, tg_tttbso,
              sent_to_mgs, force_match
            FROM invoices
            {where_sql}
            ORDER BY nlap DESC, id DESC
            LIMIT ?
        """, params + [LIST_LIMIT]).fetchall()

        count_row = conn.execute(f"SELECT COUNT(*) AS c FROM invoices {where_sql}", params).fetchone()
        total = int(count_row["c"]) if count_row else 0

        # Build list rows with reconciliation status
        trs = []
        for r in rows:
            svc = f"{val(r['service_year'])}-{val(r['service_month'])}-{val(r['service_day'])}".strip("-")
            if svc in ("", "--"):
                svc = ""

            # Compare invoice parties with vendors
            buyer_ok, buyer_reason = match_party(
                r["buyer_name"], r["buyer_mst"], r["buyer_address"], buyer_vendor_set
            )
            safe_seller_name = r["seller_name"]
            seller_ok, seller_reason = match_party(
                safe_seller_name, r["seller_mst"], r["seller_address"], seller_vendor_set
            )

            seller_class = "" if seller_ok else "cell-mismatch"
            seller_title = ""
            if not seller_ok:
                seller_title = f' title="{escape(seller_reason)} | Seller vs Vendor(purchasing=No)"'

            buyer_class = "" if buyer_ok else "cell-mismatch"
            buyer_title = ""
            if not buyer_ok:
                buyer_title = f' title="{escape(buyer_reason)} | Buyer vs Vendor(purchasing=1)"'

            # Reconciliation check
            recon_status, locked_sum, all_sum, recon_msg = check_invoice_payroll_reconciliation(
                conn, r["contract_no"], r["service_year"], r["service_month"], r["tg_tttbso"]
            )

            is_force_match = int(r["force_match"] or 0) == 1
            is_matched_natural = (recon_status == 'ok') and buyer_ok and seller_ok
            is_matched = is_force_match or is_matched_natural

            recon_badge_html = ""
            if is_force_match:
                recon_badge_html = f'<div class="tag" style="background:#f3e8ff; border-color:#d8b4fe; color:#6b21a8; margin-left:0; margin-top:4px; display:block; width:fit-content; font-size:10px;" title="Forced matched by user">✓ Force Matched</div>'
            elif recon_status == 'ok':
                recon_badge_html = f'<div class="tag" style="background:#e6f4ea; border-color:#b4e3be; color:#137333; margin-left:0; margin-top:4px; display:block; width:fit-content; font-size:10px;" title="{escape(recon_msg)}">✓ Match</div>'
            elif recon_status == 'mismatch':
                recon_badge_html = f'<div class="tag tag-deactive" style="margin-left:0; margin-top:4px; display:block; width:fit-content; font-size:10px;" title="{escape(recon_msg)}">⚠️ Mismatch ({fmt_money(locked_sum)})</div>'
            elif recon_status == 'no_payroll' and all_sum > 0:
                recon_badge_html = f'<div class="tag" style="background:#fffbeb; border-color:#fde68a; color:#b45309; margin-left:0; margin-top:4px; display:block; width:fit-content; font-size:10px;" title="{escape(recon_msg)}">⚠️ Unlocked ({fmt_money(all_sum)})</div>'
            elif recon_status == 'no_payroll':
                recon_badge_html = f'<div class="tag" style="background:#f1f5f9; border-color:#e2e8f0; color:#64748b; margin-left:0; margin-top:4px; display:block; width:fit-content; font-size:10px;" title="{escape(recon_msg)}">No payroll</div>'
            elif recon_status == 'no_contract':
                recon_badge_html = f'<div class="tag" style="background:#f1f5f9; border-color:#e2e8f0; color:#64748b; margin-left:0; margin-top:4px; display:block; width:fit-content; font-size:10px;" title="{escape(recon_msg)}">No contract</div>'

            # MGS Details
            mgs_data = get_mgs_data_dict(conn, r)
            mgs_json = json.dumps(mgs_data)
            is_sent = int(r["sent_to_mgs"] or 0) == 1
            
            disabled_attr = "disabled" if (not is_matched or is_sent) else ""
            btn_style = "background:#10b981; color:#fff; border-color:#10b981;" if is_sent else ""
            btn_text = "To MGS (Sent)" if is_sent else "To MGS"
            
            onclick_js = f"showMgsModal('{escape(mgs_json)}')"
            
            mgs_btn = f'<button type="button" id="mgs-btn-{r["id"]}" class="btn-secondary" style="font-size:11px; padding: 4px 8px; margin-top:2px; {btn_style}" onclick="{onclick_js}" {disabled_attr}>{btn_text}</button>'

            delete_form = f"""
              <form class="inline" method="POST" action="/delete-invoice"
                    onsubmit="return confirm('Delete invoice ID={r["id"]} ({escape(r["khhdon"] or "")}/{escape(r["shdon"] or "")}) ?');"
                    style="margin:0; display:inline-block;">
                <input type="hidden" name="id" value="{r["id"]}">
                <input type="hidden" name="return_to" value="{escape(return_to)}">
                <button class="btn-danger" type="submit" style="font-size:11px; padding: 4px 8px; margin-top:2px;">Delete</button>
              </form>
            """

            force_btn = ""
            if not is_sent:
                if is_force_match:
                    force_btn = f"""
                      <form class="inline" method="POST" action="/invoice/force-match" style="margin:0; display:inline-block;">
                        <input type="hidden" name="id" value="{r["id"]}">
                        <input type="hidden" name="value" value="0">
                        <input type="hidden" name="return_to" value="{escape(return_to)}">
                        <button class="btn-secondary" type="submit" style="font-size:11px; padding: 4px 8px; margin-top:2px; background:#fff; color:#6b21a8; border-color:#d8b4fe;">Unforce</button>
                      </form>
                    """
                elif not is_matched_natural:
                    force_btn = f"""
                      <form class="inline" method="POST" action="/invoice/force-match" style="margin:0; display:inline-block;">
                        <input type="hidden" name="id" value="{r["id"]}">
                        <input type="hidden" name="value" value="1">
                        <input type="hidden" name="return_to" value="{escape(return_to)}">
                        <button class="btn-secondary" type="submit" style="font-size:11px; padding: 4px 8px; margin-top:2px; background:#f3e8ff; color:#6b21a8; border-color:#d8b4fe;">Force Match</button>
                      </form>
                    """

            trs.append(f"""
            <tr>
              <td>{r["id"]}</td>
              <td>
                <a href="/invoice?id={r["id"]}">
                  {escape(r["khhdon"] or "")} / {escape(r["shdon"] or "")}
                </a>
                <div class="muted">Issued: {escape(r["nlap"] or "")}</div>
              </td>
              <td>{escape(svc)}</td>
              <td>
                <b>{escape(r["contract_no"] or "")}</b>
                {recon_badge_html}
              </td>

              <td class="{seller_class}"{seller_title}>
                {escape(r["seller_name"] or "")}
                <div class="muted">{escape(r["seller_mst"] or "")}</div>
              </td>

              <td class="{buyer_class}"{buyer_title}>
                {escape(r["buyer_name"] or "")}
                <div class="muted">{escape(r["buyer_mst"] or "")}</div>
              </td>

              <td>{escape(fmt_money(r["tg_tttbso"], r["dvtte"]))}</td>

              <td>
                <div class="actions" style="gap:6px; flex-wrap:nowrap; display:flex; align-items:center;">
                  <a href="/edit-invoice?id={r["id"]}" style="text-decoration:none;"><button type="button" class="btn-secondary" style="font-size:11px; padding: 4px 8px; margin-top:2px;">Edit</button></a>
                  {delete_form}
                  {force_btn}
                  {mgs_btn}
                </div>
              </td>
            </tr>
            """)

    finally:
        conn.close()

    filter_html = f"""
    <form class="filters" method="GET" action="/">
      <div>
        <div class="label">Service Year</div>
        <input type="number" name="year" placeholder="YYYY" value="{escape(val(year))}">
      </div>
      <div>
        <div class="label">Month</div>
        <input type="number" name="month" placeholder="MM" value="{escape(val(month))}">
      </div>
      <div>
        <div class="label">Day</div>
        <input type="number" name="day" placeholder="DD" value="{escape(val(day))}">
      </div>
      <div style="min-width:320px;">
        <div class="label">Search (Series/Invoice No/Tax ID/Name/Contract)</div>
        <input type="text" name="q" placeholder="Enter keywords..." value="{escape(q)}" style="width:100%;">
      </div>
      <div class="actions">
        <button type="submit">Filter</button>
        <a class="muted" href="/">This Year</a>
        <a class="muted" href="/?year=&month=&day=&q=">Show All</a>
        <a href="/invoice/new"><button class="btn-secondary" type="button">+ Import Invoice</button></a>
      </div>
    </form>
    """

    body = f"""
      {filter_html}

      <div class="muted" style="margin-bottom:10px;">
        Total DB: {total} invoices. Displayed: {len(rows)} (limit {LIST_LIMIT})
      </div>

      <div class="muted" style="margin-bottom:10px;">
        Reconciliation (all 3 fields required): <b>VI Name + VI Address + Tax ID</b><br>
        Buyer ↔ Vendor <code>purchasing=Yes</code> (active)<br>
        Seller ↔ Vendor <code>purchasing=No</code> (active)<br>
        Pink highlighted cells = missing or mismatch. Hover over to see the reason.
      </div>

      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Series / Invoice No</th>
            <th>Service Date</th>
            <th>Contract No</th>
            <th>Seller</th>
            <th>Buyer</th>
            <th>Total Payment</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {''.join(trs) if trs else '<tr><td colspan="8" class="muted">No data</td></tr>'}
        </tbody>
      </table>
    """
    return layout("Invoices List", body)

def page_invoice_detail(invoice_id: int):
    conn = db_connect()
    try:
        inv = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
        if not inv:
            return layout("Not Found", f"<div class='card'>Invoice ID={invoice_id} not found. <a href='/'>Back</a></div>")

        tax_lines = conn.execute("""
            SELECT tsuat, thtien, tthue
            FROM invoice_tax_lines
            WHERE invoice_id=?
            ORDER BY id ASC
        """, (invoice_id,)).fetchall()

        # Run reconciliation check
        recon_status, locked_sum, all_sum, recon_msg = check_invoice_payroll_reconciliation(
            conn, inv["contract_no"], inv["service_year"], inv["service_month"], inv["tg_tttbso"]
        )

        buyer_vendor_set, seller_vendor_set = build_vendor_sets(conn)
        mgs_data = get_mgs_data_dict(conn, inv)
    finally:
        conn.close()

    buyer_ok, _ = match_party(inv["buyer_name"], inv["buyer_mst"], inv["buyer_address"], buyer_vendor_set)
    seller_ok, _ = match_party(inv["seller_name"], inv["seller_mst"], inv["seller_address"], seller_vendor_set)
    is_force_match = int(inv["force_match"] or 0) == 1
    is_matched_natural = (recon_status == 'ok') and buyer_ok and seller_ok
    is_matched = is_force_match or is_matched_natural
    is_sent = int(inv["sent_to_mgs"] or 0) == 1
    
    disabled_attr = "disabled" if (not is_matched or is_sent) else ""
    btn_style = "background:#10b981; color:#fff; border-color:#10b981;" if is_sent else "background:var(--primary); color:#fff; border-color:var(--primary);"
    btn_text = "To MGS (Sent)" if is_sent else "To MGS"
    
    mgs_json = json.dumps(mgs_data)
    onclick_js = f"showMgsModal('{escape(mgs_json)}')"
    mgs_btn = f'<button type="button" id="mgs-btn-{inv["id"]}" class="btn" style="{btn_style}" onclick="{onclick_js}" {disabled_attr}>{btn_text}</button>'

    def v(key):
        x = inv[key]
        return "" if x is None else str(x)

    svc = f"{v('service_year')}-{v('service_month')}-{v('service_day')}".strip("-")
    if svc in ("", "--"):
        svc = ""

    tax_rows = []
    for t in tax_lines:
        tax_rows.append(f"""
          <tr>
            <td>{escape(t["tsuat"] or "")}</td>
            <td>{escape(fmt_money(t["thtien"], inv["dvtte"]))}</td>
            <td>{escape(fmt_money(t["tthue"], inv["dvtte"]))}</td>
          </tr>
        """)

    delete_form = f"""
      <form class="inline" method="POST" action="/delete-invoice"
            onsubmit="return confirm('Delete invoice ID={invoice_id} ({escape(inv["khhdon"] or "")}/{escape(inv["shdon"] or "")}) ?');">
        <input type="hidden" name="id" value="{invoice_id}">
        <input type="hidden" name="return_to" value="/">
        <button class="btn-danger" type="submit">Delete Invoice</button>
      </form>
    """

    recon_style = ""
    if is_force_match:
        recon_style = "border-left: 4px solid #8b5cf6; background: #faf5ff; color: #5b21b6; border-color: #e9d5ff;"
        recon_title = "✓ Force Matched by User"
    elif recon_status == 'ok':
        recon_style = "border-left: 4px solid #10b981; background: #f0fdf4; color: #166534; border-color: #bbf7d0;"
        recon_title = "✓ Monthly Payroll Reconciled"
    elif recon_status == 'mismatch':
        recon_style = "border-left: 4px solid #ef4444; background: #fef2f2; color: #991b1b; border-color: #fca5a5;"
        recon_title = "⚠️ Mismatch Warning"
    elif recon_status == 'no_payroll' and all_sum > 0:
        recon_style = "border-left: 4px solid #f59e0b; background: #fffbeb; color: #92400e; border-color: #fde68a;"
        recon_title = "⚠️ Unlocked Payroll Warning"
    else:
        recon_style = "border-left: 4px solid #94a3b8; background: #f1f5f9; color: #475569; border-color: #cbd5e1;"
        recon_title = "ℹ️ No Payroll Found"

    recon_card_html = f"""
    <div class="card" style="{recon_style} padding: 16px; margin-bottom: 20px; border-radius: 8px;">
      <h3 style="margin-top: 0; margin-bottom: 6px; font-size: 15px; font-weight: 700;">{recon_title}</h3>
      <div style="font-size: 13.5px; line-height: 1.5;">{escape(recon_msg)}</div>
      <div class="muted" style="margin-top: 6px; font-size: 11px; color: inherit; opacity: 0.85;">
        Invoice month: {inv['service_year']}-{inv['service_month']:02d} | 
        Invoice amount: {fmt_money(inv['tg_tttbso'])} | 
        Total locked payroll: {fmt_money(locked_sum)} | 
        Total unlocked payroll: {fmt_money(all_sum)}
      </div>
    </div>
    """

    force_btn = ""
    if not is_sent:
        if is_force_match:
            force_btn = f"""
              <form class="inline" method="POST" action="/invoice/force-match" style="margin:0; display:inline-block;">
                <input type="hidden" name="id" value="{invoice_id}">
                <input type="hidden" name="value" value="0">
                <input type="hidden" name="return_to" value="/invoice?id={invoice_id}">
                <button class="btn" type="submit" style="background:#fff; color:#6b21a8; border-color:#d8b4fe;">Unforce Match</button>
              </form>
            """
        elif not is_matched_natural:
            force_btn = f"""
              <form class="inline" method="POST" action="/invoice/force-match" style="margin:0; display:inline-block;">
                <input type="hidden" name="id" value="{invoice_id}">
                <input type="hidden" name="value" value="1">
                <input type="hidden" name="return_to" value="/invoice?id={invoice_id}">
                <button class="btn" type="submit" style="background:#f3e8ff; color:#6b21a8; border-color:#d8b4fe;">Force Match</button>
              </form>
            """

    body = f"""
    <div class="actions" style="margin-bottom:14px; display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
      <a href="/">← Invoices List</a>
      <a href="/edit-invoice?id={invoice_id}" class="btn">Edit Data</a>
      <a href="/raw?id={invoice_id}" class="btn">View Raw XML</a>
      {delete_form}
      {force_btn}
      {mgs_btn}
    </div>

    {recon_card_html}

    <div class="card">
      <div class="grid">
        <div><div class="label">KHHDon</div><div class="value">{escape(v("khhdon"))}</div></div>
        <div><div class="label">SHDon</div><div class="value">{escape(v("shdon"))}</div></div>
        <div><div class="label">NLap</div><div class="value">{escape(v("nlap"))}</div></div>
        <div><div class="label">DVTTe</div><div class="value">{escape(v("dvtte"))}</div></div>

        <div><div class="label">Service Date</div><div class="value">{escape(svc)}</div></div>
        <div><div class="label">Contract No</div><div class="value">{escape(v("contract_no"))}</div></div>

        <div><div class="label">Seller</div><div class="value">{escape(v("seller_name"))}</div></div>
        <div><div class="label">Seller Tax ID</div><div class="value">{escape(v("seller_mst"))}</div></div>

        <div><div class="label">Buyer</div><div class="value">{escape(v("buyer_name"))}</div></div>
        <div><div class="label">Buyer Tax ID</div><div class="value">{escape(v("buyer_mst"))}</div></div>

        <div style="grid-column:1 / -1;">
          <div class="label">Seller Address</div><div class="value">{escape(v("seller_address"))}</div>
        </div>
        <div style="grid-column:1 / -1;">
          <div class="label">Buyer Address</div><div class="value">{escape(v("buyer_address"))}</div>
        </div>

        <div><div class="label">TgTCThue</div><div class="value">{escape(fmt_money(inv["tg_tcthue"], inv["dvtte"]))}</div></div>
        <div><div class="label">TgTThue</div><div class="value">{escape(fmt_money(inv["tg_tthue"], inv["dvtte"]))}</div></div>
        <div><div class="label">TTCKTMai</div><div class="value">{escape(fmt_money(inv["ttcktmai"], inv["dvtte"]))}</div></div>
        <div><div class="label">TgTTTBSo</div><div class="value">{escape(fmt_money(inv["tg_tttbso"], inv["dvtte"]))}</div></div>
      </div>
    </div>

    <div class="muted" style="margin: 10px 0 8px;">THTTLTSuat / LTSuat: {len(tax_lines)} lines</div>
    <table>
      <thead><tr><th>TSuat</th><th>ThTien</th><th>TThue</th></tr></thead>
      <tbody>
        {''.join(tax_rows) if tax_rows else '<tr><td colspan="3" class="muted">None</td></tr>'}
      </tbody>
    </table>
    """
    return layout(f"Invoice Details #{invoice_id}", body)


def page_edit_invoice(invoice_id: int, error_msg: str | None = None):
    conn = db_connect()
    try:
        inv = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
        if not inv:
            return layout("Not Found", f"<div class='card'>Invoice ID={invoice_id} not found. <a href='/'>Back</a></div>")
    finally:
        conn.close()

    def v(key):
        x = inv[key]
        return "" if x is None else str(x)

    error_html = f"<div class='card danger'><b>Error:</b> {escape(error_msg)}</div>" if error_msg else ""

    body = f"""
    {error_html}
    <div class="card">
      <div class="actions" style="margin-bottom:10px;">
        <a href="/invoice?id={invoice_id}">← Back to Details</a>
        <a href="/">Invoices List</a>
      </div>

      <div class="muted" style="margin-bottom:10px;">
        Invoice: <b>{escape(v("khhdon"))} / {escape(v("shdon"))}</b> (read-only)
      </div>

      <form method="POST" action="/edit-invoice">
        <input type="hidden" name="id" value="{invoice_id}">

        <div class="grid">
          <div>
            <div class="label">Service Year (nullable)</div>
            <input type="number" name="service_year" placeholder="YYYY" value="{escape(v("service_year"))}">
          </div>
          <div>
            <div class="label">Month (nullable)</div>
            <input type="number" name="service_month" placeholder="MM" value="{escape(v("service_month"))}">
          </div>
          <div>
            <div class="label">Day (nullable)</div>
            <input type="number" name="service_day" placeholder="DD" value="{escape(v("service_day"))}">
          </div>
          <div>
            <div class="label">Contract No (nullable)</div>
            <input type="text" name="contract_no" value="{escape(v("contract_no"))}" style="width:100%;">
          </div>
        </div>

        <div class="actions" style="margin-top:14px;">
          <button type="submit">Save</button>
          <a class="muted" href="/invoice?id={invoice_id}">Cancel</a>
        </div>
      </form>
    </div>
    """
    return layout(f"Edit Invoice #{invoice_id}", body)


def handle_edit_invoice_post(handler):
    form = read_post_form(handler)
    invoice_id_raw = (form.get("id", [""])[0] or "").strip()
    if not invoice_id_raw.isdigit():
        send_html(handler, layout("Error", "<div class='card danger'>Missing or invalid ID</div>"), status=400)
        return

    invoice_id = int(invoice_id_raw)
    sy = parse_int_or_none(form.get("service_year", [""])[0])
    sm = parse_int_or_none(form.get("service_month", [""])[0])
    sd = parse_int_or_none(form.get("service_day", [""])[0])

    contract_no = (form.get("contract_no", [""])[0] or "").strip()
    contract_no = contract_no if contract_no != "" else None

    if sm is not None and not (1 <= sm <= 12):
        send_html(handler, page_edit_invoice(invoice_id, "Month must be between 1 and 12, or empty"))
        return
    if sd is not None and not (1 <= sd <= 31):
        send_html(handler, page_edit_invoice(invoice_id, "Day must be between 1 and 31, or empty"))
        return
    if sy is not None and not (1900 <= sy <= 2100):
        send_html(handler, page_edit_invoice(invoice_id, "Year should be between 1900 and 2100, or empty"))
        return

    conn = db_connect()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE invoices
            SET service_year=?, service_month=?, service_day=?, contract_no=?
            WHERE id=?
        """, (sy, sm, sd, contract_no, invoice_id))
        conn.commit()
    finally:
        conn.close()

    redirect(handler, f"/invoice?id={invoice_id}")


def handle_delete_invoice_post(handler):
    form = read_post_form(handler)
    invoice_id_raw = (form.get("id", [""])[0] or "").strip()
    return_to = safe_return_to((form.get("return_to", [""])[0] or "").strip())

    if not invoice_id_raw.isdigit():
        send_html(handler, layout("Error", "<div class='card danger'>Missing or invalid ID</div>"), status=400)
        return

    invoice_id = int(invoice_id_raw)

    conn = db_connect()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM invoice_tax_lines WHERE invoice_id=?", (invoice_id,))
        cur.execute("DELETE FROM invoices WHERE id=?", (invoice_id,))
        conn.commit()
    finally:
        conn.close()

    redirect(handler, return_to)


def page_raw_xml(invoice_id: int):
    conn = db_connect()
    try:
        row = conn.execute("SELECT khhdon, shdon, raw_xml FROM invoices WHERE id=?", (invoice_id,)).fetchone()
        if not row:
            return layout("Not Found", f"<div class='card'>Invoice ID={invoice_id} not found. <a href='/'>Back</a></div>")
        raw = row["raw_xml"] or ""
    finally:
        conn.close()

    body = f"""
    <div class="card">
      <div class="actions" style="margin-bottom:10px;">
        <a href="/invoice?id={invoice_id}">← Back to Details</a>
        <a href="/">Invoices List</a>
      </div>
      <div class="muted">Raw XML: <b>{escape(row["khhdon"] or "")} / {escape(row["shdon"] or "")}</b></div>
      <div style="margin-top:10px;">
        <textarea readonly>{escape(raw)}</textarea>
      </div>
    </div>
    """
    return layout(f"Raw XML #{invoice_id}", body)


# -------------------- XML Parsing & Import Helpers --------------------
def get_xml_text(parent, path: str, default=None):
    if parent is None:
        return default
    el = parent.find(path)
    if el is None or el.text is None:
        return default
    return el.text.strip()


def to_xml_float(s: str | None):
    if s is None:
        return None
    s = s.strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_xml_bytes(xml_bytes: bytes, filename: str) -> tuple[dict, list[dict]]:
    root = ET.fromstring(xml_bytes)
    dlh = root.find("./DLHDon")
    if dlh is None:
        raise ValueError("Thiếu thẻ <DLHDon>")

    tt = dlh.find("./TTChung")
    nd = dlh.find("./NDHDon")
    if tt is None or nd is None:
        raise ValueError("Thiếu thẻ <TTChung> hoặc <NDHDon>")

    khhdon = get_xml_text(tt, "./KHHDon")
    shdon = get_xml_text(tt, "./SHDon")
    nlap = get_xml_text(tt, "./NLap")
    dvtte = get_xml_text(tt, "./DVTTe", default="VND")

    nban = nd.find("./NBan")
    nmua = nd.find("./NMua")
    ttoan = nd.find("./TToan")

    seller_name = get_xml_text(nban, "./Ten") if nban is not None else None
    seller_mst = get_xml_text(nban, "./MST") if nban is not None else None
    seller_address = get_xml_text(nban, "./DChi") if nban is not None else None

    buyer_name = get_xml_text(nmua, "./Ten") if nmua is not None else None
    buyer_mst = get_xml_text(nmua, "./MST") if nmua is not None else None
    buyer_address = get_xml_text(nmua, "./DChi") if nmua is not None else None
    buyer_bank_name = get_xml_text(nmua, "./HVTNMHang") if nmua is not None else None

    tg_tcthue = to_xml_float(get_xml_text(ttoan, "./TgTCThue")) if ttoan is not None else None
    tg_tthue = to_xml_float(get_xml_text(ttoan, "./TgTThue")) if ttoan is not None else None
    ttcktmai = to_xml_float(get_xml_text(ttoan, "./TTCKTMai")) if ttoan is not None else None
    tg_tttbso = to_xml_float(get_xml_text(ttoan, "./TgTTTBSo")) if ttoan is not None else None

    tax_lines = []
    if ttoan is not None:
        for lt in ttoan.findall("./THTTLTSuat/LTSuat"):
            tax_lines.append({
                "tsuat": get_xml_text(lt, "./TSuat"),
                "thtien": to_xml_float(get_xml_text(lt, "./ThTien")),
                "tthue": to_xml_float(get_xml_text(lt, "./TThue")),
            })

    invoice = {
        "khhdon": khhdon,
        "shdon": shdon,
        "nlap": nlap,
        "dvtte": dvtte,

        "seller_name": seller_name,
        "seller_mst": seller_mst,
        "seller_address": seller_address,

        "buyer_name": buyer_name,
        "buyer_mst": buyer_mst,
        "buyer_address": buyer_address,
        "buyer_bank_name": buyer_bank_name,

        "tg_tcthue": tg_tcthue,
        "tg_tthue": tg_tthue,
        "ttcktmai": ttcktmai,
        "tg_tttbso": tg_tttbso,

        "raw_xml": xml_bytes.decode("utf-8", errors="ignore"),
    }

    return invoice, tax_lines


def iter_local_xml_files(path: Path):
    if path.is_file():
        yield path
        return

    if path.is_dir():
        exts = {".xml"}
        for p in sorted(path.rglob("*")):
            if p.is_file() and p.suffix.lower() in exts:
                yield p
        return

    raise FileNotFoundError(f"Đường dẫn không tồn tại: {path}")


def db_insert_or_duplicate(
    conn,
    invoice: dict,
    *,
    service_year,
    service_month,
    service_day,
    contract_no,
    source_path: str
) -> tuple[int, bool]:
    khhdon = (invoice.get("khhdon") or "").strip()
    shdon = (invoice.get("shdon") or "").strip()

    if not khhdon or not shdon:
        raise ValueError("Thiếu KHHDon hoặc SHDon trong XML")

    cur = conn.cursor()
    row = cur.execute(
        "SELECT id FROM invoices WHERE khhdon=? AND shdon=?",
        (khhdon, shdon)
    ).fetchone()

    if row:
        return row[0], True

    cur.execute("""
        INSERT INTO invoices (
            service_year, service_month, service_day, contract_no,
            khhdon, shdon, nlap, dvtte,
            seller_name, seller_mst, seller_address,
            buyer_name, buyer_mst, buyer_address, buyer_bank_name,
            tg_tcthue, tg_tthue, ttcktmai, tg_tttbso,
            source_path, raw_xml
        )
        VALUES (
            ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?
        )
    """, (
        service_year, service_month, service_day, contract_no,
        invoice["khhdon"], invoice["shdon"], invoice["nlap"], invoice["dvtte"],
        invoice["seller_name"], invoice["seller_mst"], invoice["seller_address"],
        invoice["buyer_name"], invoice["buyer_mst"], invoice["buyer_address"], invoice["buyer_bank_name"],
        invoice["tg_tcthue"], invoice["tg_tthue"], invoice["ttcktmai"], invoice["tg_tttbso"],
        source_path, invoice["raw_xml"],
    ))
    return cur.lastrowid, False


def db_replace_tax_lines(conn, invoice_id: int, tax_lines: list[dict]):
    cur = conn.cursor()
    cur.execute("DELETE FROM invoice_tax_lines WHERE invoice_id=?", (invoice_id,))
    cur.executemany("""
        INSERT INTO invoice_tax_lines (invoice_id, tsuat, thtien, tthue)
        VALUES (?, ?, ?, ?)
    """, [
        (invoice_id, tl.get("tsuat"), tl.get("thtien"), tl.get("tthue"))
        for tl in tax_lines
    ])


# -------------------- Manual Multipart Form Parser --------------------
def parse_multipart(handler):
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


# -------------------- Pages & Post Handlers --------------------
def page_new_invoice(error_msg: str | None = None):
    error_html = f"<div class='card danger'><b>Error:</b> {escape(error_msg)}</div>" if error_msg else ""
    
    body = f"""
    {error_html}
    <div class="card">
      <div class="actions" style="margin-bottom:10px;">
        <a href="/">← Back to List</a>
      </div>
      
      <form method="POST" action="/invoice/create" enctype="multipart/form-data">
        
        <h3>Service & Contract Information (Applies to all imported invoices)</h3>
        <div class="grid">
          <div>
            <div class="label">Service Year (service_year)</div>
            <input type="number" name="service_year" placeholder="YYYY">
          </div>
          <div>
            <div class="label">Month (service_month)</div>
            <input type="number" name="service_month" placeholder="MM">
          </div>
          <div>
            <div class="label">Day (service_day)</div>
            <input type="number" name="service_day" placeholder="DD">
          </div>
          <div>
            <div class="label">Contract No (contract_no)</div>
            <input type="text" name="contract_no" placeholder="e.g. MHB/FPT/2025/001" style="width:100%;">
          </div>
        </div>

        <h3 style="margin-top: 24px;">Invoice Import Method</h3>
        <div style="margin-bottom: 16px; display: flex; gap: 20px;">
          <label>
            <input type="radio" name="import_type" value="file" checked onclick="switchImportType('file')">
            Upload file from computer
          </label>
          <label>
            <input type="radio" name="import_type" value="path" onclick="switchImportType('path')">
            Local path on server (File/Directory)
          </label>
          <label>
            <input type="radio" name="import_type" value="paste" onclick="switchImportType('paste')">
            Paste XML content
          </label>
        </div>

        <!-- Section 1: Upload File -->
        <div id="sec-file">
          <div class="label" style="margin-bottom: 8px;">Select one or more XML invoice files</div>
          <input type="file" name="xml_files" multiple accept=".xml" style="width: 100%; border: 1px dashed #ccc; padding: 20px; border-radius: 8px; background: #fafafa;">
        </div>

        <!-- Section 2: Local Path -->
        <div id="sec-path" style="display: none;">
          <div class="label" style="margin-bottom: 8px;">Full path to the XML file or XML directory on the server</div>
          <input type="text" name="local_path" placeholder="e.g. /Users/.../sample_xmls" style="width: 100%;">
        </div>

        <!-- Section 3: Paste XML -->
        <div id="sec-paste" style="display: none;">
          <div class="label" style="margin-bottom: 8px;">Paste XML invoice code below</div>
          <textarea name="xml_content" placeholder="&lt;HDon&gt;...&lt;/HDon&gt;"></textarea>
        </div>

        <div class="actions" style="margin-top:24px;">
          <button type="submit" style="background: #0b57d0; color: #fff; border-color: #0b57d0; font-weight: 600; padding: 10px 20px;">Import Invoice</button>
          <a class="muted" href="/">Cancel</a>
        </div>
      </form>
    </div>

    <script>
      function switchImportType(type) {{
        document.getElementById('sec-file').style.display = type === 'file' ? 'block' : 'none';
        document.getElementById('sec-path').style.display = type === 'path' ? 'block' : 'none';
        document.getElementById('sec-paste').style.display = type === 'paste' ? 'block' : 'none';
      }}
    </script>
    """
    return layout("Import New Invoice", body)


def handle_new_invoice_post(handler):
    form = parse_multipart(handler)
    if not form:
        send_html(handler, page_new_invoice("Valid form data was not received."))
        return

    # Extract common fields
    sy_raw = form.get("service_year", [""])[0].strip()
    sm_raw = form.get("service_month", [""])[0].strip()
    sd_raw = form.get("service_day", [""])[0].strip()
    contract_no = form.get("contract_no", [""])[0].strip()
    import_type = form.get("import_type", ["file"])[0].strip()

    service_year = parse_int_or_none(sy_raw)
    service_month = parse_int_or_none(sm_raw)
    service_day = parse_int_or_none(sd_raw)
    contract_no = contract_no if contract_no != "" else None

    # Validate dates
    if service_month is not None and not (1 <= service_month <= 12):
        send_html(handler, page_new_invoice("Month must be between 1 and 12, or empty"))
        return
    if service_day is not None and not (1 <= service_day <= 31):
        send_html(handler, page_new_invoice("Day must be between 1 and 31, or empty"))
        return
    if service_year is not None and not (1900 <= service_year <= 2100):
        send_html(handler, page_new_invoice("Year should be between 1900 and 2100, or empty"))
        return

    # Collect XML items to process: list of tuples (filename/source, xml_bytes)
    xml_items = []

    if import_type == "file":
        uploaded_files = form.get("xml_files", [])
        valid_files = [f for f in uploaded_files if f.get("filename") and len(f.get("content", b"")) > 0]
        if not valid_files:
            send_html(handler, page_new_invoice("Please select at least one XML file to upload."))
            return
        for f in valid_files:
            xml_items.append((f["filename"], f["content"]))

    elif import_type == "path":
        local_path_raw = form.get("local_path", [""])[0].strip()
        if not local_path_raw:
            send_html(handler, page_new_invoice("Please enter the directory or XML file path."))
            return
        
        path_obj = Path(local_path_raw)
        if not path_obj.exists():
            send_html(handler, page_new_invoice(f"Path does not exist on server: {local_path_raw}"))
            return
        
        try:
            for xml_file in iter_local_xml_files(path_obj):
                try:
                    xml_bytes = xml_file.read_bytes()
                    xml_items.append((str(xml_file), xml_bytes))
                except Exception as ex:
                    pass
        except Exception as e:
            send_html(handler, page_new_invoice(f"Error traversing path: {str(e)}"))
            return

        if not xml_items:
            send_html(handler, page_new_invoice(f"No XML files found at path: {local_path_raw}"))
            return

    elif import_type == "paste":
        xml_content_raw = form.get("xml_content", [""])[0].strip()
        if not xml_content_raw:
            send_html(handler, page_new_invoice("Please paste the XML invoice code."))
            return
        xml_items.append(("Pasted from Clipboard", xml_content_raw.encode("utf-8")))
    
    else:
        send_html(handler, page_new_invoice("Invalid import method."))
        return

    # Process XML items
    conn = db_connect()
    results = []
    
    try:
        for source_name, xml_bytes in xml_items:
            try:
                # 1. Parse XML
                invoice, tax_lines = parse_xml_bytes(xml_bytes, source_name)
                
                # 2. Insert or duplicate check
                invoice_id, is_dup = db_insert_or_duplicate(
                    conn,
                    invoice,
                    service_year=service_year,
                    service_month=service_month,
                    service_day=service_day,
                    contract_no=contract_no,
                    source_path=source_name
                )
                
                if is_dup:
                    results.append({
                        "source": source_name,
                        "status": "DUPLICATE",
                        "detail": f"Invoice Series={invoice['khhdon']} No={invoice['shdon']} already exists (ID={invoice_id})",
                        "id": invoice_id
                    })
                    continue

                # 3. Save tax lines
                db_replace_tax_lines(conn, invoice_id, tax_lines)
                conn.commit()

                results.append({
                    "source": source_name,
                    "status": "OK",
                    "detail": f"Successfully imported Series={invoice['khhdon']} No={invoice['shdon']} (Tax rates: {', '.join(tl.get('tsuat','') for tl in tax_lines)})",
                    "id": invoice_id
                })

            except Exception as e:
                conn.rollback()
                results.append({
                    "source": source_name,
                    "status": "ERROR",
                    "detail": str(e),
                    "id": None
                })
    finally:
        conn.close()

    # Generate results page
    result_rows = []
    success_count = 0
    dup_count = 0
    fail_count = 0

    for res in results:
        status_class = ""
        if res["status"] == "OK":
            status_class = "tag"
            success_count += 1
            source_link = f"<a href='/invoice?id={res['id']}'>{escape(res['source'])}</a>"
        elif res["status"] == "DUPLICATE":
            status_class = "tag tag-deactive"
            dup_count += 1
            source_link = f"<a href='/invoice?id={res['id']}'>{escape(res['source'])}</a>"
        else:
            status_class = "tag tag-deactive"
            fail_count += 1
            source_link = escape(res["source"])

        result_rows.append(f"""
        <tr>
          <td>{source_link}</td>
          <td><span class="{status_class}" style="font-weight:bold;">{res["status"]}</span></td>
          <td>{escape(res["detail"])}</td>
        </tr>
        """)

    summary_html = f"""
    <div class="card">
      <h2>Import Results</h2>
      <div style="margin-bottom:14px; font-size:16px;">
        Success: <b style="color:green;">{success_count}</b> | 
        Duplicate: <b style="color:orange;">{dup_count}</b> | 
        Error: <b style="color:red;">{fail_count}</b>
      </div>
      
      <table>
        <thead>
          <tr>
            <th>Source / File</th>
            <th>Status</th>
            <th>Details</th>
          </tr>
        </thead>
        <tbody>
          {''.join(result_rows)}
        </tbody>
      </table>

      <div class="actions" style="margin-top:20px;">
        <a href="/"><button type="button" style="background:#0b57d0; color:#fff; border-color:#0b57d0; font-weight:600;">Invoices List</button></a>
        <a href="/invoice/new"><button type="button" class="btn-secondary">Import More Invoices</button></a>
      </div>
    </div>
    """
    send_html(handler, layout("Invoice Import Results", summary_html))


def handle_toggle_mgs_sent_ajax(handler):
    import json
    length = int(handler.headers.get("Content-Length", 0))
    body = handler.rfile.read(length).decode("utf-8", errors="ignore")
    
    try:
        data = json.loads(body)
    except Exception:
        # Fallback to form URL encoded if not JSON
        import urllib.parse
        try:
            params = urllib.parse.parse_qs(body)
            data = {k: v[0] for k, v in params.items()}
        except Exception:
            send_html(handler, json.dumps({"status": "error", "message": "Invalid request body"}), status=400)
            return
            
    invoice_id = data.get("id")
    sent = data.get("sent")
    
    if invoice_id is None or sent is None:
        send_html(handler, json.dumps({"status": "error", "message": "Missing parameters"}), status=400)
        return
        
    try:
        invoice_id = int(invoice_id)
        sent = int(sent)
    except ValueError:
        send_html(handler, json.dumps({"status": "error", "message": "Invalid ID or sent format"}), status=400)
        return

    conn = db_connect()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE invoices SET sent_to_mgs = ?, updated_at = datetime('now') WHERE id = ?", (sent, invoice_id))
        conn.commit()
        send_html(handler, json.dumps({"status": "ok"}), status=200)
    except Exception as e:
        send_html(handler, json.dumps({"status": "error", "message": str(e)}), status=500)
    finally:
        conn.close()


def handle_force_match_post(handler):
    form = read_post_form(handler)
    invoice_id_raw = (form.get("id", [""])[0] or "").strip()
    val_raw = (form.get("value", [""])[0] or "").strip()
    return_to = safe_return_to((form.get("return_to", [""])[0] or "").strip())

    if not invoice_id_raw.isdigit() or not val_raw.isdigit():
        send_html(handler, layout("Error", "<div class='card danger'>Missing or invalid parameters</div>"), status=400)
        return

    invoice_id = int(invoice_id_raw)
    val = int(val_raw)

    conn = db_connect()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE invoices SET force_match=?, updated_at=? WHERE id=?", (val, now_iso(), invoice_id))
        conn.commit()
    finally:
        conn.close()

    redirect(handler, return_to)