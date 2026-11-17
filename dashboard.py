# dashboard.py

import sqlite3
import json
from datetime import datetime, date
from html import escape

from common import db_connect, layout, send_html, fmt_money
from invoices import check_invoice_payroll_reconciliation, match_party, build_vendor_sets
from attendance import parse_shift_times, parse_time_minutes


def page_dashboard(handler):
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(handler.path)
    qs = parse_qs(parsed.query)
    
    start_month = qs.get("start_month", [""])[0].strip()
    end_month = qs.get("end_month", [""])[0].strip()
    vendor_id = qs.get("vendor_id", [""])[0].strip()
    project_id = qs.get("project_id", [""])[0].strip()

    conn = db_connect()
    try:
        # Load vendors and projects for filter dropdowns
        all_vendors_list = conn.execute("SELECT id, short_name, company_name FROM vendors WHERE is_active = 1").fetchall()
        vendor_opts = []
        for v in all_vendors_list:
            v_name = v["short_name"] or v["company_name"] or f"Vendor ID {v['id']}"
            sel = "selected" if vendor_id and str(v["id"]) == vendor_id else ""
            vendor_opts.append(f'<option value="{v["id"]}" {sel}>{escape(v_name)}</option>')
        vendor_options_html = "\n".join(vendor_opts)

        all_projects_list = conn.execute("SELECT id, short_name, full_name FROM projects WHERE is_active = 1").fetchall()
        project_opts = []
        for p in all_projects_list:
            p_name = p["short_name"] or p["full_name"] or f"Project ID {p['id']}"
            sel = "selected" if project_id and str(p["id"]) == project_id else ""
            project_opts.append(f'<option value="{p["id"]}" {sel}>{escape(p_name)}</option>')
        project_options_html = "\n".join(project_opts)

        # 1. Total counts and calculations (filtered invoices)
        invoices_rows = conn.execute("SELECT * FROM invoices").fetchall()
        buyer_vendor_set, seller_vendor_set = build_vendor_sets(conn)
        
        status_counts = {
            "Matched": 0,
            "Mismatch": 0,
            "No Payroll": 0,
            "No Contract": 0
        }
        
        total_value_by_currency = {}
        monthly_trend = {}  # key: "YYYY-MM", val: amount in VND
        
        filtered_invoices_count = 0
        
        for r in invoices_rows:
            # 1. Period filter
            if r["service_year"] and r["service_month"]:
                mon_str = f"{r['service_year']:04d}-{r['service_month']:02d}"
                if start_month and mon_str < start_month:
                    continue
                if end_month and mon_str > end_month:
                    continue
            
            buyer_ok, buyer_vid = match_party(r["buyer_name"], r["buyer_mst"], r["buyer_address"], buyer_vendor_set)
            seller_ok, seller_vid = match_party(r["seller_name"], r["seller_mst"], r["seller_address"], seller_vendor_set)

            # 2. Vendor filter
            if vendor_id and str(seller_vid) != vendor_id:
                continue
                
            # 3. Project filter
            if project_id:
                linked_contracts = conn.execute("""
                    SELECT DISTINCT c.framework_no
                    FROM project_staff_assignments psa
                    JOIN contract_staff_links l ON l.staff_id = psa.staff_id
                    JOIN contracts c ON c.id = l.contract_id
                    WHERE psa.project_id = ?
                """, (project_id,)).fetchall()
                linked_contract_nos = {c["framework_no"] for c in linked_contracts if c["framework_no"]}
                
                inv_c_no = (r["contract_no"] or "").strip()
                if inv_c_no not in linked_contract_nos:
                    continue
            
            filtered_invoices_count += 1
            
            recon_status, _, _, _ = check_invoice_payroll_reconciliation(
                conn, r["contract_no"], r["service_year"], r["service_month"], r["tg_tttbso"]
            )
            
            is_matched = (recon_status == 'ok') and buyer_ok and seller_ok
            if is_matched:
                status_counts["Matched"] += 1
            elif recon_status == 'mismatch':
                status_counts["Mismatch"] += 1
            elif recon_status == 'no_payroll':
                status_counts["No Payroll"] += 1
            elif recon_status == 'no_contract':
                status_counts["No Contract"] += 1
            else:
                status_counts["No Payroll"] += 1
                
            # Currency Totals
            curr = (r["dvtte"] or "VND").strip().upper()
            val_amt = float(r["tg_tttbso"] or 0)
            total_value_by_currency[curr] = total_value_by_currency.get(curr, 0) + val_amt
            
            # Monthly Trend (VND only for consistency in chart)
            if curr == "VND" and r["service_year"] and r["service_month"]:
                month_key = f"{r['service_year']:04d}-{r['service_month']:02d}"
                monthly_trend[month_key] = monthly_trend.get(month_key, 0) + val_amt

        # 2. Staff metrics (filtered)
        today_str = date.today().strftime("%Y-%m-%d")
        staff_where = ["v.purchasing = 0", "v.is_active = 1"]
        staff_params = [today_str, today_str]
        
        if vendor_id:
            staff_where.append("v.id = ?")
            staff_params.append(vendor_id)
            
        if project_id:
            ref_month = today_str[:7]
            if start_month or end_month:
                period_cond = []
                period_params = []
                if start_month:
                    period_cond.append("psa.month >= ?")
                    period_params.append(start_month)
                if end_month:
                    period_cond.append("psa.month <= ?")
                    period_params.append(end_month)
                period_sql = " AND ".join(period_cond)
                
                staff_where.append(f"""
                    EXISTS (
                        SELECT 1 FROM project_staff_assignments psa
                        WHERE psa.staff_id = s.id AND psa.project_id = ? AND {period_sql}
                    )
                """)
                staff_params.append(project_id)
                staff_params.extend(period_params)
            else:
                staff_where.append("""
                    EXISTS (
                        SELECT 1 FROM project_staff_assignments psa
                        WHERE psa.staff_id = s.id AND psa.project_id = ? AND psa.month = ?
                    )
                """)
                staff_params.extend([project_id, ref_month])
                
        staff_where_sql = "WHERE " + " AND ".join(staff_where)
        
        vendor_staff_rows = conn.execute(f"""
            SELECT v.short_name, COUNT(DISTINCT s.full_name_vi) as staff_count
            FROM vendors v
            LEFT JOIN contract_staff s ON v.id = s.vendor_id 
                AND (s.status IS NULL OR s.status != 'inactive')
                AND EXISTS (
                    SELECT 1 FROM contract_staff_links l
                    WHERE l.staff_id = s.id
                      AND l.joining_date <= ?
                      AND (l.tentative_leaving_date IS NULL OR l.tentative_leaving_date = '' OR l.tentative_leaving_date >= ?)
                )
            {staff_where_sql}
            GROUP BY v.id
            ORDER BY staff_count DESC
        """, staff_params).fetchall()
        
        vendor_staff_labels = [r["short_name"] or "Unknown" for r in vendor_staff_rows]
        vendor_staff_data = [r["staff_count"] for r in vendor_staff_rows]
        total_active_staff = sum(vendor_staff_data)
        active_vendor_count = len([c for c in vendor_staff_data if c > 0])

        # 3. Expirations within notice window / 30 days (filtered)
        today = date.today()
        expiring_contracts = []
        
        all_contracts = conn.execute("""
            SELECT id, framework_no, framework_name, start_date, end_date, seller_vendor_id,
                   contract_type, billing_type, renewal_type, renewal_notice_days, renewal_period_months
            FROM contracts
            WHERE is_active = 1
        """).fetchall()
        for c in all_contracts:
            if vendor_id and str(c["seller_vendor_id"]) != vendor_id:
                continue
            if project_id:
                has_proj_link = conn.execute("""
                    SELECT 1 FROM project_staff_assignments psa
                    JOIN contract_staff_links l ON l.staff_id = psa.staff_id
                    WHERE psa.project_id = ? AND l.contract_id = ?
                    LIMIT 1
                """, (project_id, c["id"])).fetchone()
                if not has_proj_link:
                    continue
            
            if c["end_date"]:
                try:
                    ed = datetime.strptime(c["end_date"].strip(), "%Y-%m-%d").date()
                    delta = (ed - today).days
                    c_type = (c["contract_type"] or "FRAMEWORK").upper()
                    b_type = (c["billing_type"] or "TM").upper()
                    is_standalone_rec = (c_type == "STANDALONE" and b_type == "RECURRING")
                    notice_days = c["renewal_notice_days"] if (is_standalone_rec and c["renewal_notice_days"] is not None and c["renewal_notice_days"] > 0) else 60
                    threshold = max(30, notice_days) if is_standalone_rec else 30
                    if delta <= threshold:
                        expiring_contracts.append({
                            "id": c["id"],
                            "framework_no": c["framework_no"],
                            "framework_name": c["framework_name"],
                            "start_date": c["start_date"],
                            "end_date": c["end_date"],
                            "days_left": delta,
                            "display_no": c["framework_no"],
                            "display_name": c["framework_name"] or "Framework Contract",
                            "type": "contract",
                            "contract_type": c_type,
                            "billing_type": b_type,
                            "renewal_type": (c["renewal_type"] or "MANUAL").upper() if is_standalone_rec else "NONE",
                            "renewal_notice_days": notice_days,
                            "renewal_period_months": c["renewal_period_months"]
                        })
                except Exception:
                    pass

        # Load active annexes expiring within 30 days
        all_annexes = conn.execute("""
            SELECT ca.id, ca.contract_id, ca.annex_name, ca.end_date, c.framework_no, c.framework_name, c.seller_vendor_id
            FROM contract_annexes ca
            JOIN contracts c ON c.id = ca.contract_id
            WHERE ca.is_active = 1
        """).fetchall()
        for a in all_annexes:
            if vendor_id and str(a["seller_vendor_id"]) != vendor_id:
                continue
            if project_id:
                has_proj_link = conn.execute("""
                    SELECT 1 FROM project_staff_assignments psa
                    JOIN contract_staff_links l ON l.staff_id = psa.staff_id
                    WHERE psa.project_id = ? AND l.contract_id = ?
                    LIMIT 1
                """, (project_id, a["contract_id"])).fetchone()
                if not has_proj_link:
                    continue
                    
            if a["end_date"]:
                try:
                    ed = datetime.strptime(a["end_date"].strip(), "%Y-%m-%d").date()
                    delta = (ed - today).days
                    if delta <= 30:
                        expiring_contracts.append({
                            "id": a["contract_id"],
                            "framework_no": a["framework_no"],
                            "framework_name": a["framework_name"],
                            "annex_name": a["annex_name"],
                            "end_date": a["end_date"],
                            "days_left": delta,
                            "display_no": f"{a['framework_no']} - {a['annex_name']}",
                            "display_name": "Contract Annex",
                            "type": "annex",
                            "renewal_type": "NONE"
                        })
                except Exception:
                    pass

        expiring_contracts.sort(key=lambda x: x["days_left"])

        auto_renew_count = sum(1 for ec in expiring_contracts if ec.get("renewal_type") == "AUTO")
        manual_renew_count = sum(1 for ec in expiring_contracts if ec.get("renewal_type") == "MANUAL")
        annex_exp_count = sum(1 for ec in expiring_contracts if ec.get("type") == "annex")

        # 4. Workforce Attendance & Punctuality Analytics
        att_where = []
        att_params = []
        punct_period_desc = ""

        if start_month:
            att_where.append("a.date >= ?")
            att_params.append(f"{start_month}-01")
        if end_month:
            try:
                ey, em = int(end_month[:4]), int(end_month[5:7])
                next_m_str = f"{ey+1:04d}-01-01" if em == 12 else f"{ey:04d}-{em+1:02d}-01"
            except Exception:
                next_m_str = f"{end_month}-31"
            att_where.append("a.date < ?")
            att_params.append(next_m_str)

        if vendor_id:
            att_where.append("s.vendor_id = ?")
            att_params.append(vendor_id)

        if project_id:
            att_where.append("""
                EXISTS (
                    SELECT 1 FROM project_staff_assignments psa
                    WHERE psa.staff_id = s.id AND psa.project_id = ?
                )
            """)
            att_params.append(project_id)

        if not start_month and not end_month:
            latest_att_row = conn.execute("SELECT strftime('%Y-%m', date) as m FROM attendance ORDER BY date DESC LIMIT 1").fetchone()
            if latest_att_row and latest_att_row["m"]:
                target_m = latest_att_row["m"]
                att_where.append("strftime('%Y-%m', a.date) = ?")
                att_params.append(target_m)
                punct_period_desc = target_m
            else:
                punct_period_desc = today_str[:7]
        elif start_month and end_month:
            punct_period_desc = f"{start_month} ~ {end_month}"
        elif start_month:
            punct_period_desc = f"From {start_month}"
        elif end_month:
            punct_period_desc = f"Until {end_month}"

        att_where_sql = ("WHERE " + " AND ".join(att_where)) if att_where else ""

        att_punches = conn.execute(f"""
            SELECT a.check_in, a.check_out, s.work_shift
            FROM attendance a
            JOIN contract_staff s ON s.id = a.staff_id
            {att_where_sql}
        """, att_params).fetchall()

        punct_ontime = 0
        punct_late = 0
        punct_early = 0
        punct_both = 0
        punct_absent = 0

        for r in att_punches:
            cin_raw = r["check_in"]
            cout_raw = r["check_out"]
            if not cin_raw and not cout_raw:
                punct_absent += 1
                continue
            cin = parse_time_minutes(cin_raw)
            cout = parse_time_minutes(cout_raw)
            s_start, s_end = parse_shift_times(r["work_shift"])
            is_late = cin is not None and cin > s_start
            is_early = cout is not None and cout < s_end

            if is_late and is_early:
                punct_both += 1
            elif is_late:
                punct_late += 1
            elif is_early:
                punct_early += 1
            else:
                punct_ontime += 1

        total_attended_shifts = punct_ontime + punct_late + punct_early + punct_both
        punctuality_rate = (punct_ontime / total_attended_shifts * 100) if total_attended_shifts > 0 else 100.0
        punct_late_total = punct_late + punct_both
        punct_early_total = punct_early + punct_both

        # 5. Multi-Model Financial Spend Analysis (T&M, Fixed Price, Recurring)
        # 5a. Time & Material (T&M) Payroll
        tm_where = []
        tm_params = []
        if vendor_id:
            tm_where.append("cs.vendor_id = ?")
            tm_params.append(vendor_id)
        if project_id:
            tm_where.append("""
                EXISTS (
                    SELECT 1 FROM project_staff_assignments psa
                    WHERE psa.staff_id = mas.staff_id AND psa.month = mas.month AND psa.project_id = ?
                )
            """)
            tm_params.append(project_id)
        if start_month:
            tm_where.append("mas.month >= ?")
            tm_params.append(start_month)
        if end_month:
            tm_where.append("mas.month <= ?")
            tm_params.append(end_month)
        tm_where_sql = ("WHERE " + " AND ".join(tm_where)) if tm_where else ""

        tm_sum_row = conn.execute(f"""
            SELECT COALESCE(SUM(mas.total_amount), 0.0) AS tm_total
            FROM monthly_attendance_summary mas
            JOIN contract_staff cs ON cs.id = mas.staff_id
            {tm_where_sql}
        """, tm_params).fetchone()
        tm_total = float(tm_sum_row["tm_total"] if tm_sum_row else 0.0)

        # 5b. Fixed Price (Milestones)
        fp_where = ["c.is_active = 1"]
        fp_params = []
        if vendor_id:
            fp_where.append("c.seller_vendor_id = ?")
            fp_params.append(vendor_id)
        if start_month:
            fp_where.append("COALESCE(m.actual_date, m.planned_date) >= ?")
            fp_params.append(f"{start_month}-01")
        if end_month:
            try:
                ey, em = int(end_month[:4]), int(end_month[5:7])
                next_m_str = f"{ey+1:04d}-01-01" if em == 12 else f"{ey:04d}-{em+1:02d}-01"
            except Exception:
                next_m_str = f"{end_month}-31"
            fp_where.append("COALESCE(m.actual_date, m.planned_date) < ?")
            fp_params.append(next_m_str)
        fp_where_sql = "WHERE " + " AND ".join(fp_where)

        fp_sum_row = conn.execute(f"""
            SELECT 
                COALESCE(SUM(m.amount), 0.0) AS fp_total,
                COALESCE(SUM(CASE WHEN m.status = 'PAID' OR (m.cashout_date IS NOT NULL AND m.cashout_date != '') THEN m.amount ELSE 0.0 END), 0.0) AS fp_paid
            FROM contract_milestones m
            JOIN contracts c ON c.id = m.contract_id
            {fp_where_sql}
        """, fp_params).fetchone()
        fp_total = float(fp_sum_row["fp_total"] if fp_sum_row else 0.0)
        fp_paid = float(fp_sum_row["fp_paid"] if fp_sum_row else 0.0)

        # 5c. Recurring Services
        rec_where = ["c.is_active = 1"]
        rec_params = []
        if vendor_id:
            rec_where.append("c.seller_vendor_id = ?")
            rec_params.append(vendor_id)
        if start_month:
            rec_where.append("rp.service_month >= ?")
            rec_params.append(start_month)
        if end_month:
            rec_where.append("rp.service_month <= ?")
            rec_params.append(end_month)
        rec_where_sql = "WHERE " + " AND ".join(rec_where)

        rec_sum_row = conn.execute(f"""
            SELECT 
                COALESCE(SUM(rp.amount), 0.0) AS rec_total,
                COALESCE(SUM(CASE WHEN rp.status = 'PAID' OR (rp.cashout_date IS NOT NULL AND rp.cashout_date != '') THEN rp.amount ELSE 0.0 END), 0.0) AS rec_paid
            FROM recurring_payouts rp
            JOIN contracts c ON c.id = rp.contract_id
            {rec_where_sql}
        """, rec_params).fetchone()
        rec_total = float(rec_sum_row["rec_total"] if rec_sum_row else 0.0)
        rec_paid = float(rec_sum_row["rec_paid"] if rec_sum_row else 0.0)

        # 5d. Executed Cash-out for T&M
        tm_co_where = []
        tm_co_params = []
        if vendor_id:
            tm_co_where.append("cs.vendor_id = ?")
            tm_co_params.append(vendor_id)
        if start_month:
            tm_co_where.append("mas.month >= ?")
            tm_co_params.append(start_month)
        if end_month:
            tm_co_where.append("mas.month <= ?")
            tm_co_params.append(end_month)
        tm_co_where_extra = (" AND " + " AND ".join(tm_co_where)) if tm_co_where else ""

        tm_co_row = conn.execute(f"""
            SELECT COALESCE(SUM(mas.total_amount), 0.0) AS tm_cashout
            FROM monthly_attendance_summary mas
            JOIN contract_staff cs ON cs.id = mas.staff_id
            WHERE EXISTS (
                SELECT 1 FROM contract_staff_links l
                JOIN contract_annexes a ON a.contract_id = l.contract_id
                JOIN annex_cashouts ac ON ac.annex_id = a.id AND ac.month = mas.month
                WHERE l.staff_id = mas.staff_id
            )
            {tm_co_where_extra}
        """, tm_co_params).fetchone()
        tm_cashout = float(tm_co_row["tm_cashout"] if tm_co_row else 0.0)

        total_multi_spend = tm_total + fp_total + rec_total
        total_cashout_executed = tm_cashout + fp_paid + rec_paid

        # 6. Project Budget Utilization data (filtered)
        proj_where = []
        proj_params = []
        if project_id:
            proj_where.append("p.id = ?")
            proj_params.append(project_id)
            
        proj_where_sql = ("WHERE " + " AND ".join(proj_where)) if proj_where else ""
        
        project_budget_rows = conn.execute(f"""
            SELECT 
                p.id AS project_id,
                p.short_name,
                p.full_name,
                p.it_outsourcing_budget,
                p.is_active
            FROM projects p
            {proj_where_sql}
            ORDER BY p.is_active DESC, p.short_name ASC
        """, proj_params).fetchall()
        
        project_budget_data = []
        for p in project_budget_rows:
            mas_where = ["psa.project_id = ?"]
            mas_params = [p["project_id"]]
            
            if vendor_id:
                mas_where.append("cs.vendor_id = ?")
                mas_params.append(vendor_id)
                
            if start_month:
                mas_where.append("mas.month >= ?")
                mas_params.append(start_month)
                
            if end_month:
                mas_where.append("mas.month <= ?")
                mas_params.append(end_month)
                
            mas_where_sql = "WHERE " + " AND ".join(mas_where)
            
            paid_row = conn.execute(f"""
                SELECT COALESCE(SUM(mas.total_amount), 0) AS total_paid
                FROM project_staff_assignments psa
                JOIN contract_staff cs ON cs.id = psa.staff_id
                JOIN monthly_attendance_summary mas ON mas.staff_id = psa.staff_id AND mas.month = psa.month
                {mas_where_sql}
            """, mas_params).fetchone()
            
            total_paid = paid_row["total_paid"] if paid_row else 0.0
            
            project_budget_data.append({
                "project_id": p["project_id"],
                "short_name": p["short_name"],
                "full_name": p["full_name"],
                "it_outsourcing_budget": p["it_outsourcing_budget"],
                "is_active": p["is_active"],
                "total_paid": total_paid
            })

        # 7. Vendor Cost Share data (filtered)
        v_cost_where = ["v.purchasing = 0", "v.is_active = 1"]
        v_cost_params = []
        
        if vendor_id:
            v_cost_where.append("v.id = ?")
            v_cost_params.append(vendor_id)
            
        if project_id:
            v_cost_where.append("""
                EXISTS (
                    SELECT 1 FROM project_staff_assignments psa
                    WHERE psa.staff_id = cs.id AND psa.month = mas.month AND psa.project_id = ?
                )
            """)
            v_cost_params.append(project_id)
            
        if start_month:
            v_cost_where.append("mas.month >= ?")
            v_cost_params.append(start_month)
            
        if end_month:
            v_cost_where.append("mas.month <= ?")
            v_cost_params.append(end_month)
            
        v_cost_where_sql = " AND ".join(v_cost_where)
        
        vendor_costs = conn.execute(f"""
            SELECT 
                v.short_name,
                COALESCE(SUM(mas.total_amount), 0) AS total_cost
            FROM vendors v
            JOIN contract_staff cs ON cs.vendor_id = v.id
            JOIN monthly_attendance_summary mas ON mas.staff_id = cs.id
            WHERE {v_cost_where_sql}
            GROUP BY v.id
            ORDER BY total_cost DESC
        """, v_cost_params).fetchall()

        # 8. Payroll Trend by Month (filtered)
        payroll_where = []
        payroll_params = []
        
        if vendor_id:
            payroll_where.append("cs.vendor_id = ?")
            payroll_params.append(vendor_id)
            
        if project_id:
            payroll_where.append("""
                EXISTS (
                    SELECT 1 FROM project_staff_assignments psa
                    WHERE psa.staff_id = mas.staff_id AND psa.month = mas.month AND psa.project_id = ?
                )
            """)
            payroll_params.append(project_id)
            
        if start_month:
            payroll_where.append("mas.month >= ?")
            payroll_params.append(start_month)
            
        if end_month:
            payroll_where.append("mas.month <= ?")
            payroll_params.append(end_month)
            
        payroll_where_sql = ("WHERE " + " AND ".join(payroll_where)) if payroll_where else ""
        
        payroll_trend_rows = conn.execute(f"""
            SELECT mas.month, SUM(mas.total_amount) AS total_payroll
            FROM monthly_attendance_summary mas
            JOIN contract_staff cs ON cs.id = mas.staff_id
            {payroll_where_sql}
            GROUP BY mas.month
            ORDER BY mas.month ASC
        """, payroll_params).fetchall()
        
        payroll_trend = {r["month"]: r["total_payroll"] for r in payroll_trend_rows}

    finally:
        conn.close()

    # Construct hover tooltip text listing all expiring contracts/annexes
    tooltip_lines = []
    if expiring_contracts:
        for ec in expiring_contracts:
            status_desc = f"Expired {abs(ec['days_left'])} days ago" if ec["days_left"] < 0 else f"{ec['days_left']} days left"
            if ec["type"] == "annex":
                line = f"- Annex: {ec['framework_no']} - {ec['framework_name'] or 'Framework Contract'} ({ec['annex_name']}) [End: {ec['end_date']}, {status_desc}]"
            else:
                line = f"- Framework Contract: {ec['framework_no']} - {ec['framework_name'] or 'Framework Contract'} [End: {ec['end_date']}, {status_desc}]"
            tooltip_lines.append(line)
    else:
        tooltip_lines.append("No expiring contracts or annexes in the next 30 days.")
    tooltip_text = "\n".join(tooltip_lines)

    # Formatted KPI text
    kpi_invoices = f"{filtered_invoices_count} Invoices"
    
    vnd_total = total_value_by_currency.get("VND", 0)
    kpi_value_vnd = f"{fmt_money(vnd_total, 'VND')}"
    
    other_currs = [f"{fmt_money(v, k)}" for k, v in total_value_by_currency.items() if k != "VND"]
    kpi_value_other = " | ".join(other_currs) if other_currs else "0.00 USD"
    
    kpi_staff = f"{total_active_staff} Active Staff"
    kpi_expirations = f"{len(expiring_contracts)} Alert(s)"
    
    # Sort monthly trend chronologically
    sorted_months = sorted(monthly_trend.keys())
    monthly_trend_labels = sorted_months
    monthly_trend_data = [monthly_trend[m] for m in sorted_months]

    # Convert Python metrics to JSON strings for Javascript Chart.js
    js_recon_labels = json.dumps(list(status_counts.keys()))
    js_recon_data = json.dumps(list(status_counts.values()))
    
    js_staff_labels = json.dumps(vendor_staff_labels)
    js_staff_data = json.dumps(vendor_staff_data)
    
    js_trend_labels = json.dumps(monthly_trend_labels)
    js_trend_data = json.dumps(monthly_trend_data)

    sorted_pay_months = sorted(payroll_trend.keys())
    js_payroll_labels = json.dumps(sorted_pay_months)
    js_payroll_data = json.dumps([payroll_trend[m] for m in sorted_pay_months])

    # Multi-Model Spend Chart Data
    spend_model_labels = ["T&M Payroll", "Fixed Price (Milestones)", "Recurring Services"]
    spend_model_data = [tm_total, fp_total, rec_total]
    js_spend_labels = json.dumps(spend_model_labels)
    js_spend_data = json.dumps(spend_model_data)

    # Attendance & Punctuality Chart Data
    punct_chart_labels = ["On-Time", "Late Arrival", "Early Departure", "Both Late & Early"]
    punct_chart_data = [punct_ontime, punct_late, punct_early, punct_both]
    js_punct_labels = json.dumps(punct_chart_labels)
    js_punct_data = json.dumps(punct_chart_data)

    # Format project budget rows and chart data
    project_rows_html = []
    chart_proj_labels = []
    chart_proj_budget = []
    chart_proj_paid = []
    
    for pr in project_budget_data:
        budget = pr["it_outsourcing_budget"]
        paid = pr["total_paid"]
        is_proj_active = int(pr["is_active"] or 0) == 1
        display_short_name = pr["short_name"] + " (Closed)" if not is_proj_active else pr["short_name"]
        
        budget_txt = f"{fmt_money(budget, 'VND')}" if budget is not None else "N/A"
        paid_txt = f"{fmt_money(paid, 'VND')}"
        
        if budget is not None:
            remaining = budget - paid
            remaining_txt = f"{fmt_money(remaining, 'VND')}"
            usage_pct = (paid / budget * 100) if budget > 0 else 0
            
            # Save for Chart
            chart_proj_labels.append(display_short_name)
            chart_proj_budget.append(budget)
            chart_proj_paid.append(paid)
        else:
            remaining_txt = "N/A"
            usage_pct = 0
            
        if budget is not None:
            if usage_pct > 100:
                bar_color = "#dc2626"
                status_badge = '<span class="tag tag-danger" style="background:#ef4444; color:#fff; font-size:10px; font-weight:700;">Over Budget</span>'
            elif usage_pct > 90:
                bar_color = "#ea580c"
                status_badge = '<span class="tag tag-warning" style="font-size:10px; font-weight:600;">Critical (&gt;90%)</span>'
            elif usage_pct > 75:
                bar_color = "#f59e0b"
                status_badge = '<span class="tag tag-warning" style="font-size:10px; font-weight:600;">Warning (&gt;75%)</span>'
            else:
                bar_color = "#10b981"
                status_badge = '<span class="tag tag-success" style="font-size:10px; font-weight:600;">Healthy</span>'
                
            usage_bar = f"""
            <div style="display: flex; align-items: center; gap: 8px;">
              <div style="flex: 1; background: #e2e8f0; height: 6px; border-radius: 3px; overflow: hidden; min-width: 60px;">
                <div style="background: {bar_color}; width: {min(usage_pct, 100):.1f}%; height: 100%; border-radius: 3px;"></div>
              </div>
              <span style="font-size: 11px; font-weight: 600; color: var(--text-secondary); min-width: 38px; text-align: right;">{usage_pct:.1f}%</span>
            </div>
            """
        else:
            usage_bar = '<span class="muted" style="font-size:11px;">N/A</span>'
            status_badge = '<span class="tag" style="background:#f1f5f9; color:#64748b; font-size:10px;">No Budget</span>'
            
        project_rows_html.append(f"""
        <tr style="border-bottom: 1px solid var(--border);">
          <td style="padding: 10px 8px; border: none; background: transparent;">
            <strong>{escape(display_short_name)}</strong>
            <div class="muted" style="font-size: 11px; margin-top: 1px;">{escape(pr['full_name'])}</div>
          </td>
          <td style="padding: 10px 8px; text-align: right; border: none; background: transparent; font-size: 13px; font-weight: 500;">{budget_txt}</td>
          <td style="padding: 10px 8px; text-align: right; border: none; background: transparent; font-size: 13px; font-weight: 500; color: var(--primary);">{paid_txt}</td>
          <td style="padding: 10px 8px; text-align: right; border: none; background: transparent; font-size: 13px; font-weight: 500; color: {'#dc2626' if (budget is not None and remaining < 0) else 'var(--text-primary)'};">{remaining_txt}</td>
          <td style="padding: 10px 8px; border: none; background: transparent;">{usage_bar}</td>
          <td style="padding: 10px 8px; text-align: center; border: none; background: transparent;">{status_badge}</td>
        </tr>
        """)
        
    js_proj_labels = json.dumps(chart_proj_labels)
    js_proj_budget = json.dumps(chart_proj_budget)
    js_proj_paid = json.dumps(chart_proj_paid)

    # Format vendor cost share labels/data
    vendor_cost_labels = [r["short_name"] or "Unknown" for r in vendor_costs if r["total_cost"] > 0]
    vendor_cost_data = [r["total_cost"] for r in vendor_costs if r["total_cost"] > 0]
    js_vendor_cost_labels = json.dumps(vendor_cost_labels)
    js_vendor_cost_data = json.dumps(vendor_cost_data)

    # Render expiring contracts list HTML
    exp_rows_html = []
    if expiring_contracts:
        for ec in expiring_contracts:
            days_left = ec["days_left"]
            status_style = "color:#dc2626; font-weight:bold;" if days_left < 0 else "color:#ea580c; font-weight:bold;"
            if days_left < 0:
                status_text = f"Expired ({abs(days_left)} days ago)"
            else:
                status_text = f"Expiring in {days_left} days"

            badge_html = ""
            action_html = ""
            if ec.get("type") == "contract" and ec.get("contract_type") == "STANDALONE" and ec.get("billing_type") == "RECURRING":
                ren_type = ec.get("renewal_type", "MANUAL")
                if ren_type == "AUTO":
                    badge_html = '<span class="tag tag-purple" style="font-size:10px; margin-left:4px;">Auto-Renew</span>'
                elif ren_type == "MANUAL":
                    badge_html = '<span class="tag tag-info" style="font-size:10px; margin-left:4px;">Manual-Renew</span>'
                else:
                    badge_html = '<span class="tag" style="background:#f1f5f9; color:#64748b; font-size:10px; margin-left:4px;">Non-Renewable</span>'

                if ren_type != "NONE" and days_left >= 0:
                    status_text = f"⚠️ Renewal Due ({days_left}d)"
                    status_style = "color:#b45309; font-weight:600;"

                action_html = f'<a href="/contract/edit?id={ec["id"]}" style="font-size:11px; color:var(--primary); font-weight:600; text-decoration:none; margin-left:6px;" title="Review & Renew">Renew ↗</a>'
            elif ec.get("type") == "annex":
                badge_html = '<span class="tag tag-teal" style="font-size:10px; margin-left:4px;">Annex</span>'
            else:
                badge_html = '<span class="tag tag-info" style="font-size:10px; margin-left:4px;">Framework</span>'

            exp_rows_html.append(f"""
            <div style="padding:10px; border-bottom:1px solid var(--border); display:flex; justify-content:space-between; align-items:center; font-size:13px;">
              <div>
                <a href="/contract/edit?id={ec['id']}"><strong>{escape(ec['display_no'])}</strong></a>
                {badge_html}
                <div class="muted" style="font-size:11px;">{escape(ec['display_name'])}</div>
              </div>
              <div style="text-align:right;">
                <div style="font-size:11px; color:var(--text-muted);">End: {escape(ec['end_date'])} {action_html}</div>
                <span style="{status_style}">{status_text}</span>
              </div>
            </div>
            """)
    else:
        exp_rows_html.append('<div class="muted" style="padding:20px; text-align:center; font-size:13px;">✓ No upcoming contract or annex expirations.</div>')

    # Filter section HTML
    filter_html = f"""
    <div class="card" style="margin-bottom: 24px;">
      <form class="filters" method="GET" action="/dashboard" style="display: flex; gap: 16px; flex-wrap: wrap; align-items: flex-end; margin: 0;">
        <div style="flex: 1; min-width: 140px;">
          <div class="label" style="font-size: 11px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; margin-bottom: 4px;">Start Month</div>
          <input type="month" name="start_month" value="{escape(start_month)}" style="width: 100%; height: 36px; padding: 6px 12px; border: 1px solid var(--border); border-radius: 6px; box-sizing: border-box;">
        </div>
        <div style="flex: 1; min-width: 140px;">
          <div class="label" style="font-size: 11px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; margin-bottom: 4px;">End Month</div>
          <input type="month" name="end_month" value="{escape(end_month)}" style="width: 100%; height: 36px; padding: 6px 12px; border: 1px solid var(--border); border-radius: 6px; box-sizing: border-box;">
        </div>
        <div style="flex: 1.5; min-width: 180px;">
          <div class="label" style="font-size: 11px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; margin-bottom: 4px;">Vendor</div>
          <select name="vendor_id" style="width: 100%; height: 36px; padding: 6px 12px; border: 1px solid var(--border); border-radius: 6px; box-sizing: border-box; background: white;">
            <option value="">-- All Vendors --</option>
            {vendor_options_html}
          </select>
        </div>
        <div style="flex: 1.5; min-width: 180px;">
          <div class="label" style="font-size: 11px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; margin-bottom: 4px;">Project</div>
          <select name="project_id" style="width: 100%; height: 36px; padding: 6px 12px; border: 1px solid var(--border); border-radius: 6px; box-sizing: border-box; background: white;">
            <option value="">-- All Projects --</option>
            {project_options_html}
          </select>
        </div>
        <div style="display: flex; gap: 8px; align-items: center; height: 36px;">
          <button type="submit" style="height: 36px; padding: 0 16px; font-weight: 600; background: var(--primary); color: white; border: none; border-radius: 6px; cursor: pointer;">Filter</button>
          <a href="/dashboard" style="height: 36px; line-height: 34px; padding: 0 16px; font-weight: 600; border: 1px solid var(--border); border-radius: 6px; text-decoration: none; color: var(--text-muted); box-sizing: border-box; display: inline-block;">Reset</a>
        </div>
      </form>
    </div>
    """

    # Main dashboard body HTML
    dashboard_html = f"""
    <!-- Chart.js Local Library (Offline Closed Environment) -->
    <script src="/static/js/chart.umd.min.js"></script>

    <div style="margin-bottom: 24px;">
      <h2 style="margin: 0 0 6px 0; color: var(--text-primary);">Dashboard</h2>
      <p style="margin: 0; color: var(--text-muted); font-size: 14px;">Real-time executive overview of workforce operations, multi-model spend, contract lifecycles, and financial cash-outs.</p>
    </div>

    {filter_html}

    <!-- Executive KPI Grid (4 Core Pillars of Mizuho VMS) -->
    <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap:18px; margin-bottom:24px;">
      
      <!-- Card 1: Active Workforce -->
      <div class="card" style="margin:0; padding:18px; border-left:4px solid var(--primary); display:flex; align-items:center; gap:16px;">
        <div style="font-size:32px; background:var(--bg-main); padding:8px; border-radius:8px;">👥</div>
        <div style="flex:1;">
          <div style="font-size:12px; color:var(--text-muted); font-weight:600; text-transform:uppercase; margin-bottom:4px;">Active Staff</div>
          <div style="font-size:20px; font-weight:700; color:var(--text-primary);">{kpi_staff}</div>
          <div style="font-size:11px; color:#16a34a; font-weight:600; margin-top:3px;">100% active annex coverage ({active_vendor_count} vendors)</div>
        </div>
      </div>

      <!-- Card 2: Attendance Punctuality -->
      <div class="card" style="margin:0; padding:18px; border-left:4px solid #10b981; display:flex; align-items:center; gap:16px;">
        <div style="font-size:32px; background:var(--bg-main); padding:8px; border-radius:8px;">⏱️</div>
        <div style="flex:1;">
          <div style="font-size:12px; color:var(--text-muted); font-weight:600; text-transform:uppercase; margin-bottom:4px;">Workforce Punctuality</div>
          <div style="font-size:20px; font-weight:700; color:{'#16a34a' if punctuality_rate >= 80 else ('#d97706' if punctuality_rate >= 60 else '#dc2626')};">{punctuality_rate:.1f}% On-Time</div>
          <div style="font-size:11px; color:var(--text-muted); margin-top:3px;">{punct_late_total} late · {punct_early_total} early out ({punct_period_desc})</div>
        </div>
      </div>

      <!-- Card 3: Multi-Model Spend -->
      <div class="card" style="margin:0; padding:18px; border-left:4px solid #6366f1; display:flex; align-items:center; gap:16px;">
        <div style="font-size:32px; background:var(--bg-main); padding:8px; border-radius:8px;">💰</div>
        <div style="flex:1;">
          <div style="font-size:12px; color:var(--text-muted); font-weight:600; text-transform:uppercase; margin-bottom:4px;">Total Invoices &amp; Spend</div>
          <div style="font-size:16px; font-weight:700; color:var(--text-primary);">{kpi_value_vnd}</div>
          <div style="font-size:11px; color:var(--text-muted); margin-top:2px;">T&amp;M: {fmt_money(tm_total, 'VND')} · FP: {fmt_money(fp_total, 'VND')} · Rec: {fmt_money(rec_total, 'VND')}</div>
          <div style="font-size:11px; color:var(--text-muted); margin-top:1px;">{kpi_value_other} | Cash-out: {fmt_money(total_cashout_executed, 'VND')}</div>
        </div>
      </div>

      <!-- Card 4: Contract Renewals & Expirations -->
      <div class="card" title="{escape(tooltip_text)}" style="margin:0; padding:18px; border-left:4px solid {'#ef4444' if expiring_contracts else '#f59e0b'}; display:flex; align-items:center; gap:16px; cursor:help;">
        <div style="font-size:32px; background:var(--bg-main); padding:8px; border-radius:8px;">⚠️</div>
        <div style="flex:1;">
          <div style="font-size:12px; color:var(--text-muted); font-weight:600; text-transform:uppercase; margin-bottom:4px;">Contract/Annex alert</div>
          <div style="font-size:20px; font-weight:700; color:{'#ef4444' if expiring_contracts else 'var(--text-primary)'};">{kpi_expirations}</div>
          <div style="font-size:11px; color:var(--text-muted); margin-top:3px;">{auto_renew_count} Auto · {manual_renew_count} Manual · {annex_exp_count} Annexes</div>
        </div>
      </div>

    </div>

    <!-- Visual Row 1: Operations, Spend Distribution & Compliance -->
    <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap:20px; margin-bottom:24px; min-height:350px;">
      
      <!-- Left: Reconciliation Status -->
      <div class="card" style="margin:0; display:flex; flex-direction:column; padding:18px;">
        <h3 style="margin:0 0 14px 0; font-size:15px; border-bottom:1px solid var(--border); padding-bottom:8px;">Invoice Reconciliation Status</h3>
        <div style="display:flex; align-items:center; justify-content:space-around; flex:1; gap:10px;">
          <div style="width:130px; height:130px; position:relative;">
            <canvas id="reconChart"></canvas>
          </div>
          <div style="font-size:11px; display:flex; flex-direction:column; gap:6px;">
            <div style="display:flex; align-items:center; gap:6px;"><span style="width:10px; height:10px; border-radius:2px; background:#10b981; display:inline-block;"></span><strong>Matched:</strong> {status_counts["Matched"]}</div>
            <div style="display:flex; align-items:center; gap:6px;"><span style="width:10px; height:10px; border-radius:2px; background:#ef4444; display:inline-block;"></span><strong>Mismatch:</strong> {status_counts["Mismatch"]}</div>
            <div style="display:flex; align-items:center; gap:6px;"><span style="width:10px; height:10px; border-radius:2px; background:#f59e0b; display:inline-block;"></span><strong>No Payroll:</strong> {status_counts["No Payroll"]}</div>
            <div style="display:flex; align-items:center; gap:6px;"><span style="width:10px; height:10px; border-radius:2px; background:#6b7280; display:inline-block;"></span><strong>No Contract:</strong> {status_counts["No Contract"]}</div>
          </div>
        </div>
      </div>

      <!-- Middle: Multi-Model Spend Distribution -->
      <div class="card" style="margin:0; display:flex; flex-direction:column; padding:18px;">
        <h3 style="margin:0 0 14px 0; font-size:15px; border-bottom:1px solid var(--border); padding-bottom:8px;">Multi-Model Spend Distribution</h3>
        <div style="display:flex; align-items:center; justify-content:space-around; flex:1; gap:10px;">
          <div style="width:130px; height:130px; position:relative;">
            <canvas id="spendModelChart"></canvas>
          </div>
          <div style="font-size:11px; display:flex; flex-direction:column; gap:6px;">
            <div style="display:flex; align-items:center; gap:6px;">
              <span style="width:10px; height:10px; border-radius:2px; background:var(--primary); display:inline-block;"></span>
              <strong>T&amp;M:</strong> {(tm_total / total_multi_spend * 100) if total_multi_spend > 0 else 0:.1f}% ({fmt_money(tm_total, 'VND')})
            </div>
            <div style="display:flex; align-items:center; gap:6px;">
              <span style="width:10px; height:10px; border-radius:2px; background:#6366f1; display:inline-block;"></span>
              <strong>Fixed Price:</strong> {(fp_total / total_multi_spend * 100) if total_multi_spend > 0 else 0:.1f}% ({fmt_money(fp_total, 'VND')})
            </div>
            <div style="display:flex; align-items:center; gap:6px;">
              <span style="width:10px; height:10px; border-radius:2px; background:#10b981; display:inline-block;"></span>
              <strong>Recurring:</strong> {(rec_total / total_multi_spend * 100) if total_multi_spend > 0 else 0:.1f}% ({fmt_money(rec_total, 'VND')})
            </div>
          </div>
        </div>
      </div>

      <!-- Right: Attendance & Punctuality Compliance -->
      <div class="card" style="margin:0; display:flex; flex-direction:column; padding:18px;">
        <h3 style="margin:0 0 14px 0; font-size:15px; border-bottom:1px solid var(--border); padding-bottom:8px;">Attendance &amp; Punctuality Compliance</h3>
        <div style="display:flex; align-items:center; justify-content:space-around; flex:1; gap:10px;">
          <div style="width:130px; height:130px; position:relative;">
            <canvas id="punctualityChart"></canvas>
          </div>
          <div style="font-size:11px; display:flex; flex-direction:column; gap:6px;">
            <div style="display:flex; align-items:center; gap:6px;">
              <span style="width:10px; height:10px; border-radius:2px; background:#10b981; display:inline-block;"></span>
              <strong>On-Time:</strong> {punct_ontime} ({punctuality_rate:.1f}%)
            </div>
            <div style="display:flex; align-items:center; gap:6px;">
              <span style="width:10px; height:10px; border-radius:2px; background:#facc15; display:inline-block;"></span>
              <strong>Late In:</strong> {punct_late}
            </div>
            <div style="display:flex; align-items:center; gap:6px;">
              <span style="width:10px; height:10px; border-radius:2px; background:#ef4444; display:inline-block;"></span>
              <strong>Early Out:</strong> {punct_early}
            </div>
            <div style="display:flex; align-items:center; gap:6px;">
              <span style="width:10px; height:10px; border-radius:2px; background:#ea580c; display:inline-block;"></span>
              <strong>Late &amp; Early:</strong> {punct_both}
            </div>
          </div>
        </div>
      </div>

    </div>

    <!-- Visual Row 2: Financial Trends & Vendor Cost Share -->
    <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap:20px; margin-bottom:24px; min-height:300px;">
      
      <!-- Left: Invoicing Trend -->
      <div class="card" style="margin:0; display:flex; flex-direction:column; padding:18px;">
        <h3 style="margin:0 0 14px 0; font-size:15px; border-bottom:1px solid var(--border); padding-bottom:8px;">VND Invoice Value Trend (by Service Month)</h3>
        <div style="flex:1; position:relative; display:flex; align-items:center; justify-content:center;">
          <canvas id="trendChart" style="max-height:220px;"></canvas>
        </div>
      </div>

      <!-- Middle: Payroll Trend -->
      <div class="card" style="margin:0; display:flex; flex-direction:column; padding:18px;">
        <h3 style="margin:0 0 14px 0; font-size:15px; border-bottom:1px solid var(--border); padding-bottom:8px;">VND Payroll Trend (by Month)</h3>
        <div style="flex:1; position:relative; display:flex; align-items:center; justify-content:center;">
          <canvas id="payrollTrendChart" style="max-height:220px;"></canvas>
        </div>
      </div>

      <!-- Right: Vendor Cost Share -->
      <div class="card" style="margin:0; display:flex; flex-direction:column; padding:18px;">
        <h3 style="margin:0 0 14px 0; font-size:15px; border-bottom:1px solid var(--border); padding-bottom:8px;">Vendor Cost Distribution</h3>
        <div style="display:flex; align-items:center; justify-content:space-around; flex:1; gap:10px;">
          <div style="width:130px; height:130px; position:relative;">
            <canvas id="vendorCostChart"></canvas>
          </div>
          <div id="vendorCostLegend" style="font-size:11px; display:flex; flex-direction:column; gap:6px; max-height:160px; overflow-y:auto; padding-left: 4px;">
            <!-- Populated dynamically by JS -->
          </div>
        </div>
      </div>

    </div>

    <!-- Visual Row 3: Staff Headcount, Project Budget vs Spent & Contract Expirations -->
    <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap:20px; margin-bottom:24px; min-height:300px;">
      
      <!-- Left: Staff Count per Vendor -->
      <div class="card" style="margin:0; display:flex; flex-direction:column; padding:18px;">
        <h3 style="margin:0 0 14px 0; font-size:15px; border-bottom:1px solid var(--border); padding-bottom:8px;">Staff Count by Vendor</h3>
        <div style="flex:1; position:relative; display:flex; align-items:center; justify-content:center;">
          <canvas id="staffChart" style="max-height:220px;"></canvas>
        </div>
      </div>

      <!-- Middle: Project Budget vs Spent Chart -->
      <div class="card" style="margin:0; display:flex; flex-direction:column; padding:18px;">
        <h3 style="margin:0 0 14px 0; font-size:15px; border-bottom:1px solid var(--border); padding-bottom:8px;">Project Budget vs Spent</h3>
        <div style="flex:1; position:relative; display:flex; align-items:center; justify-content:center;">
          <canvas id="budgetChart" style="max-height:220px;"></canvas>
        </div>
      </div>

      <!-- Right: Expirations & Renewals -->
      <div class="card" style="margin:0; display:flex; flex-direction:column; padding:18px;">
        <h3 style="margin:0 0 10px 0; font-size:15px; border-bottom:1px solid var(--border); padding-bottom:8px;">Upcoming Contract/Annex Expirations</h3>
        <div style="flex:1; overflow-y:auto; max-height:230px;">
          {''.join(exp_rows_html)}
        </div>
      </div>

    </div>

    <!-- Visual Row 4: Project Budget Utilization Table -->
    <div class="card" style="margin-bottom:24px; padding:18px;">
      <h3 style="margin:0 0 14px 0; font-size:15px; border-bottom:1px solid var(--border); padding-bottom:8px;">Project Budget Utilization</h3>
      <div style="overflow-x:auto;">
        <table style="width:100%; border-collapse:collapse; margin:0; min-width:650px; border:none;">
          <thead>
            <tr style="background:#f8fafc; border-bottom:1px solid var(--border);">
              <th style="text-align:left; padding:8px; border:none; font-size:12px;">Project</th>
              <th style="text-align:right; padding:8px; border:none; font-size:12px;">Total Budget</th>
              <th style="text-align:right; padding:8px; border:none; font-size:12px;">Paid Amount</th>
              <th style="text-align:right; padding:8px; border:none; font-size:12px;">Remaining</th>
              <th style="text-align:left; padding:8px; border:none; font-size:12px; width:150px;">Usage %</th>
              <th style="text-align:center; padding:8px; border:none; font-size:12px; width:110px;">Status</th>
            </tr>
          </thead>
          <tbody>
            {"".join(project_rows_html) if project_rows_html else '<tr><td colspan="6" style="text-align:center; color:var(--text-muted); padding:20px;">No projects found.</td></tr>'}
          </tbody>
        </table>
      </div>
    </div>

    <script>
      // 1. Reconciliation Chart
      new Chart(document.getElementById('reconChart'), {{
        type: 'doughnut',
        data: {{
          labels: {js_recon_labels},
          datasets: [{{
            data: {js_recon_data},
            backgroundColor: ['#10b981', '#ef4444', '#f59e0b', '#6b7280'],
            borderWidth: 1
          }}]
        }},
        options: {{
          plugins: {{
            legend: {{ display: false }}
          }},
          responsive: true,
          maintainAspectRatio: false,
          cutout: '65%'
        }}
      }});

      // 1b. Multi-Model Spend Chart
      new Chart(document.getElementById('spendModelChart'), {{
        type: 'doughnut',
        data: {{
          labels: {js_spend_labels},
          datasets: [{{
            data: {js_spend_data},
            backgroundColor: ['#183181', '#6366f1', '#10b981'],
            borderWidth: 1
          }}]
        }},
        options: {{
          plugins: {{
            legend: {{ display: false }}
          }},
          responsive: true,
          maintainAspectRatio: false,
          cutout: '65%'
        }}
      }});

      // 1c. Attendance & Punctuality Chart
      new Chart(document.getElementById('punctualityChart'), {{
        type: 'doughnut',
        data: {{
          labels: {js_punct_labels},
          datasets: [{{
            data: {js_punct_data},
            backgroundColor: ['#10b981', '#facc15', '#ef4444', '#ea580c'],
            borderWidth: 1
          }}]
        }},
        options: {{
          plugins: {{
            legend: {{ display: false }}
          }},
          responsive: true,
          maintainAspectRatio: false,
          cutout: '65%'
        }}
      }});

      // 2. Staff Count Chart
      new Chart(document.getElementById('staffChart'), {{
        type: 'bar',
        data: {{
          labels: {js_staff_labels},
          datasets: [{{
            label: 'Active Staff',
            data: {js_staff_data},
            backgroundColor: '#183181',
            borderRadius: 4
          }}]
        }},
        options: {{
          responsive: true,
          maintainAspectRatio: false,
          plugins: {{
            legend: {{ display: false }}
          }},
          scales: {{
            y: {{
              beginAtZero: true,
              ticks: {{ stepSize: 1 }}
            }}
          }}
        }}
      }});

      // 3. Billing Trend Chart
      new Chart(document.getElementById('trendChart'), {{
        type: 'line',
        data: {{
          labels: {js_trend_labels},
          datasets: [{{
            label: 'Total Billing (VND)',
            data: {js_trend_data},
            borderColor: '#6366f1',
            backgroundColor: 'rgba(99, 102, 241, 0.1)',
            fill: true,
            tension: 0.2,
            borderWidth: 2,
            pointRadius: 4,
            pointBackgroundColor: '#6366f1'
          }}]
        }},
        options: {{
          responsive: true,
          maintainAspectRatio: false,
          plugins: {{
            legend: {{ display: false }}
          }},
          scales: {{
            y: {{
              beginAtZero: true,
              ticks: {{
                callback: function(value) {{
                  if (value >= 1e9) return (value / 1e9).toFixed(1) + 'B';
                  if (value >= 1e6) return (value / 1e6).toFixed(0) + 'M';
                  return value;
                }}
              }}
            }}
          }}
        }}
      }});

      // 3b. Payroll Trend Chart
      new Chart(document.getElementById('payrollTrendChart'), {{
        type: 'line',
        data: {{
          labels: {js_payroll_labels},
          datasets: [{{
            label: 'Total Payroll (VND)',
            data: {js_payroll_data},
            borderColor: '#10b981',
            backgroundColor: 'rgba(16, 185, 129, 0.1)',
            fill: true,
            tension: 0.2,
            borderWidth: 2,
            pointRadius: 4,
            pointBackgroundColor: '#10b981'
          }}]
        }},
        options: {{
          responsive: true,
          maintainAspectRatio: false,
          plugins: {{
            legend: {{ display: false }}
          }},
          scales: {{
            y: {{
              beginAtZero: true,
              ticks: {{
                callback: function(value) {{
                  if (value >= 1e9) return (value / 1e9).toFixed(1) + 'B';
                  if (value >= 1e6) return (value / 1e6).toFixed(0) + 'M';
                  return value;
                }}
              }}
            }}
          }}
        }}
      }});

      // 4. Project Budget Chart
      new Chart(document.getElementById('budgetChart'), {{
        type: 'bar',
        data: {{
          labels: {js_proj_labels},
          datasets: [
            {{
              label: 'Budget',
              data: {js_proj_budget},
              backgroundColor: '#cbd5e1',
              borderRadius: 4
            }},
            {{
              label: 'Spent',
              data: {js_proj_paid},
              backgroundColor: '#183181',
              borderRadius: 4
            }}
          ]
        }},
        options: {{
          responsive: true,
          maintainAspectRatio: false,
          plugins: {{
            legend: {{
              position: 'bottom',
              labels: {{ boxWidth: 12, font: {{ size: 10 }} }}
            }}
          }},
          scales: {{
            y: {{
              beginAtZero: true,
              ticks: {{
                callback: function(value) {{
                  if (value >= 1e9) return (value / 1e9).toFixed(1) + 'B';
                  if (value >= 1e6) return (value / 1e6).toFixed(0) + 'M';
                  return value;
                }}
              }}
            }}
          }}
        }}
      }});

      // 5. Vendor Cost Share Chart
      const costLabels = {js_vendor_cost_labels};
      const costData = {js_vendor_cost_data};
      const costColors = ['#183181', '#6366f1', '#10b981', '#3b82f6', '#f59e0b', '#ec4899', '#8b5cf6'];
      
      new Chart(document.getElementById('vendorCostChart'), {{
        type: 'pie',
        data: {{
          labels: costLabels,
          datasets: [{{
            data: costData,
            backgroundColor: costColors.slice(0, costLabels.length),
            borderWidth: 1
          }}]
        }},
        options: {{
          plugins: {{
            legend: {{ display: false }}
          }},
          responsive: true,
          maintainAspectRatio: false
        }}
      }});
      
      // Populate legend
      const legendDiv = document.getElementById('vendorCostLegend');
      if (costLabels.length === 0) {{
        legendDiv.innerHTML = '<span class="muted" style="font-size:11px;">No cost data available</span>';
      }} else {{
        let legendHtml = '';
        const total = costData.reduce((a, b) => a + b, 0);
        costLabels.forEach((label, idx) => {{
          const val = costData[idx];
          const pct = total > 0 ? ((val / total) * 100).toFixed(1) : 0;
          const color = costColors[idx % costColors.length];
          let valTxt = val >= 1e9 ? (val / 1e9).toFixed(2) + 'B' : (val / 1e6).toFixed(1) + 'M';
          legendHtml += `<div style="display:flex; align-items:center; gap:6px;"><span style="width:10px; height:10px; border-radius:2px; background:${{color}}; display:inline-block;"></span><strong>${{label}}:</strong> ${{pct}}% (${{valTxt}})</div>`;
        }});
        legendDiv.innerHTML = legendHtml;
      }}
    </script>
    """
    send_html(handler, layout("Dashboard", dashboard_html))
