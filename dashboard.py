# dashboard.py

import sqlite3
import json
from datetime import datetime, date
from html import escape

from common import db_connect, layout, send_html, fmt_money
from invoices import check_invoice_payroll_reconciliation, match_party, build_vendor_sets


def page_dashboard(handler):
    conn = db_connect()
    try:
        # 1. Total counts and calculations
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
        
        for r in invoices_rows:
            buyer_ok, _ = match_party(r["buyer_name"], r["buyer_mst"], r["buyer_address"], buyer_vendor_set)
            seller_ok, _ = match_party(r["seller_name"], r["seller_mst"], r["seller_address"], seller_vendor_set)
            
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

        # 2. Staff metrics
        today_str = date.today().strftime("%Y-%m-%d")
        vendor_staff_rows = conn.execute("""
            SELECT v.short_name, COUNT(DISTINCT s.full_name_vi) as staff_count
            FROM vendors v
            LEFT JOIN contract_staff s ON v.id = s.vendor_id 
                AND (s.status IS NULL OR s.status != 'inactive')
                AND (s.joining_date IS NULL OR s.joining_date <= ?)
                AND (s.tentative_leaving_date IS NULL OR s.tentative_leaving_date >= ?)
            WHERE v.purchasing = 0 AND v.is_active = 1
            GROUP BY v.id
            ORDER BY staff_count DESC
        """, (today_str, today_str)).fetchall()
        
        vendor_staff_labels = [r["short_name"] or "Unknown" for r in vendor_staff_rows]
        vendor_staff_data = [r["staff_count"] for r in vendor_staff_rows]
        total_active_staff = sum(vendor_staff_data)
        
        # 3. Expirations within 30 days (1 month)
        today = date.today()
        expiring_contracts = []
        
        # Load active contracts expiring within 30 days
        all_contracts = conn.execute("SELECT id, framework_no, framework_name, end_date FROM contracts WHERE is_active = 1").fetchall()
        for c in all_contracts:
            if c["end_date"]:
                try:
                    ed = datetime.strptime(c["end_date"].strip(), "%Y-%m-%d").date()
                    delta = (ed - today).days
                    if delta <= 30:
                        expiring_contracts.append({
                            "id": c["id"],
                            "framework_no": c["framework_no"],
                            "framework_name": c["framework_name"],
                            "end_date": c["end_date"],
                            "days_left": delta,
                            "display_no": c["framework_no"],
                            "display_name": c["framework_name"] or "Framework Contract",
                            "type": "contract"
                        })
                except Exception:
                    pass

        # Load active annexes expiring within 30 days
        all_annexes = conn.execute("""
            SELECT ca.id, ca.contract_id, ca.annex_name, ca.end_date, c.framework_no, c.framework_name
            FROM contract_annexes ca
            JOIN contracts c ON c.id = ca.contract_id
            WHERE ca.is_active = 1
        """).fetchall()
        for a in all_annexes:
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
                            "type": "annex"
                        })
                except Exception:
                    pass

        # Sort expiring contracts/annexes by days_left
        expiring_contracts.sort(key=lambda x: x["days_left"])

    finally:
        conn.close()

    # Construct hover tooltip text listing all expiring contracts/annexes
    tooltip_lines = []
    if expiring_contracts:
        for ec in expiring_contracts:
            status_desc = f"Expired {abs(ec['days_left'])} days ago" if ec["days_left"] < 0 else f"{ec['days_left']} days left"
            if ec["type"] == "annex":
                line = f"- Phụ lục: {ec['framework_no']} - {ec['framework_name'] or 'Framework Contract'} ({ec['annex_name']}) [End: {ec['end_date']}, {status_desc}]"
            else:
                line = f"- Hợp đồng khung: {ec['framework_no']} - {ec['framework_name'] or 'Framework Contract'} [End: {ec['end_date']}, {status_desc}]"
            tooltip_lines.append(line)
    else:
        tooltip_lines.append("No expiring contracts or annexes in the next 30 days.")
    tooltip_text = "\n".join(tooltip_lines)

    # Formatted KPI text
    kpi_invoices = f"{len(invoices_rows)} Invoices"
    
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

    # Render expiring contracts list HTML
    exp_rows_html = []
    if expiring_contracts:
        for ec in expiring_contracts:
            status_style = "color:#dc2626; font-weight:bold;" if ec["days_left"] < 0 else "color:#ea580c; font-weight:bold;"
            status_text = f"Expired ({abs(ec['days_left'])} days ago)" if ec["days_left"] < 0 else f"Expiring in {ec['days_left']} days"
            exp_rows_html.append(f"""
            <div style="padding:10px; border-bottom:1px solid var(--border); display:flex; justify-content:space-between; align-items:center; font-size:13px;">
              <div>
                <a href="/contract/edit?id={ec['id']}"><strong>{escape(ec['display_no'])}</strong></a>
                <div class="muted" style="font-size:11px;">{escape(ec['display_name'])}</div>
              </div>
              <div style="text-align:right;">
                <div style="font-size:11px; color:var(--text-muted);">End: {escape(ec['end_date'])}</div>
                <span style="{status_style}">{status_text}</span>
              </div>
            </div>
            """)
    else:
        exp_rows_html.append('<div class="muted" style="padding:20px; text-align:center; font-size:13px;">✓ No contracts or annexes expiring in the next 30 days.</div>')

    # Main dashboard body HTML
    dashboard_html = f"""
    <!-- Chart.js CDN -->
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>

    <div style="margin-bottom: 24px;">
      <h2 style="margin: 0 0 6px 0; color: var(--text-primary);">Dashboard</h2>
      <p style="margin: 0; color: var(--text-muted); font-size: 14px;">Real-time overview of invoices, reconciliation status, vendor workforce, and contract lifecycles.</p>
    </div>

    <!-- KPI Grid -->
    <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap:18px; margin-bottom:24px;">
      
      <div class="card" style="margin:0; padding:18px; border-left:4px solid var(--primary); display:flex; align-items:center; gap:16px;">
        <div style="font-size:32px; background:var(--bg-main); padding:8px; border-radius:8px;">📄</div>
        <div>
          <div style="font-size:12px; color:var(--text-muted); font-weight:600; text-transform:uppercase; margin-bottom:4px;">Total Invoices</div>
          <div style="font-size:20px; font-weight:700; color:var(--text-primary);">{kpi_invoices}</div>
        </div>
      </div>

      <div class="card" style="margin:0; padding:18px; border-left:4px solid #10b981; display:flex; align-items:center; gap:16px;">
        <div style="font-size:32px; background:var(--bg-main); padding:8px; border-radius:8px;">💰</div>
        <div>
          <div style="font-size:12px; color:var(--text-muted); font-weight:600; text-transform:uppercase; margin-bottom:4px;">Total Amount</div>
          <div style="font-size:16px; font-weight:700; color:var(--text-primary);">{kpi_value_vnd}</div>
          <div style="font-size:11px; color:var(--text-muted); margin-top:2px;">{kpi_value_other}</div>
        </div>
      </div>

      <div class="card" style="margin:0; padding:18px; border-left:4px solid #0ea5e9; display:flex; align-items:center; gap:16px;">
        <div style="font-size:32px; background:var(--bg-main); padding:8px; border-radius:8px;">👥</div>
        <div>
          <div style="font-size:12px; color:var(--text-muted); font-weight:600; text-transform:uppercase; margin-bottom:4px;">Active Staff</div>
          <div style="font-size:20px; font-weight:700; color:var(--text-primary);">{kpi_staff}</div>
        </div>
      </div>

      <div class="card" title="{escape(tooltip_text)}" style="margin:0; padding:18px; border-left:4px solid {'#ef4444' if expiring_contracts else '#f59e0b'}; display:flex; align-items:center; gap:16px; cursor:help;">
        <div style="font-size:32px; background:var(--bg-main); padding:8px; border-radius:8px;">⚠️</div>
        <div>
          <div style="font-size:12px; color:var(--text-muted); font-weight:600; text-transform:uppercase; margin-bottom:4px;">Contract/Annex alert</div>
          <div style="font-size:20px; font-weight:700; color:{'#ef4444' if expiring_contracts else 'var(--text-primary)'};">{kpi_expirations}</div>
        </div>
      </div>

    </div>

    <!-- Charts Row 1 -->
    <div style="display:grid; grid-template-columns: 1fr 1fr; gap:20px; margin-bottom:24px; min-height:350px; flex-wrap:wrap;">
      
      <!-- Left: Reconciliation Status -->
      <div class="card" style="margin:0; display:flex; flex-direction:column; padding:18px;">
        <h3 style="margin:0 0 14px 0; font-size:15px; border-bottom:1px solid var(--border); padding-bottom:8px;">Reconciliation Overview</h3>
        <div style="display:flex; align-items:center; justify-content:space-around; flex:1; gap:10px;">
          <div style="width:180px; height:180px; position:relative;">
            <canvas id="reconChart"></canvas>
          </div>
          <div style="font-size:12px; display:flex; flex-direction:column; gap:8px;">
            <div style="display:flex; align-items:center; gap:8px;"><span style="width:12px; height:12px; border-radius:3px; background:#10b981; display:inline-block;"></span><strong>Matched:</strong> {status_counts["Matched"]}</div>
            <div style="display:flex; align-items:center; gap:8px;"><span style="width:12px; height:12px; border-radius:3px; background:#ef4444; display:inline-block;"></span><strong>Mismatch:</strong> {status_counts["Mismatch"]}</div>
            <div style="display:flex; align-items:center; gap:8px;"><span style="width:12px; height:12px; border-radius:3px; background:#f59e0b; display:inline-block;"></span><strong>No Payroll:</strong> {status_counts["No Payroll"]}</div>
            <div style="display:flex; align-items:center; gap:8px;"><span style="width:12px; height:12px; border-radius:3px; background:#6b7280; display:inline-block;"></span><strong>No Contract:</strong> {status_counts["No Contract"]}</div>
          </div>
        </div>
      </div>

      <!-- Right: Staff Count per Vendor -->
      <div class="card" style="margin:0; display:flex; flex-direction:column; padding:18px;">
        <h3 style="margin:0 0 14px 0; font-size:15px; border-bottom:1px solid var(--border); padding-bottom:8px;">Staff Count by Vendor</h3>
        <div style="flex:1; position:relative; display:flex; align-items:center; justify-content:center;">
          <canvas id="staffChart" style="max-height:220px;"></canvas>
        </div>
      </div>

    </div>

    <!-- Row 2 -->
    <div style="display:grid; grid-template-columns: 2fr 1fr; gap:20px; margin-bottom:24px; min-height:300px;">
      
      <!-- Left: Billing Trend -->
      <div class="card" style="margin:0; display:flex; flex-direction:column; padding:18px;">
        <h3 style="margin:0 0 14px 0; font-size:15px; border-bottom:1px solid var(--border); padding-bottom:8px;">VND Invoice Value Trend (by Service Month)</h3>
        <div style="flex:1; position:relative; display:flex; align-items:center; justify-content:center;">
          <canvas id="trendChart" style="max-height:220px;"></canvas>
        </div>
      </div>

      <!-- Right: Expirations -->
      <div class="card" style="margin:0; display:flex; flex-direction:column; padding:18px;">
        <h3 style="margin:0 0 10px 0; font-size:15px; border-bottom:1px solid var(--border); padding-bottom:8px;">Upcoming Contract/Annex Expirations</h3>
        <div style="flex:1; overflow-y:auto; max-height:230px;">
          {''.join(exp_rows_html)}
        </div>
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

      // 2. Staff Count Chart
      new Chart(document.getElementById('staffChart'), {{
        type: 'bar',
        data: {{
          labels: {js_staff_labels},
          datasets: [{{
            label: 'Active Staff',
            data: {js_staff_data},
            backgroundColor: '#3b82f6',
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
    </script>
    """
    send_html(handler, layout("Dashboard", dashboard_html))
