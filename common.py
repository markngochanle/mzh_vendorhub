# common.py
# Shared helpers for server (no extra libraries)

import sqlite3
import urllib.parse
from html import escape
from datetime import datetime
from pathlib import Path

DB_PATH = str(Path(__file__).resolve().with_name("db.sqlite3"))

HOST = "127.0.0.1"
PORT = 8800
LIST_LIMIT = 2000


# -------------------- DB --------------------
def db_connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_column(conn: sqlite3.Connection, table: str, column: str, col_def: str):
    """
    Add column if missing (SQLite-friendly).
    """
    cur = conn.cursor()
    try:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
        conn.commit()
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            return
        raise


def init_db():
    """
    Ensure tables exist + migrations:
      - vendors (+ company_name_vi/address_vi, purchasing)
      - contracts (framework)
      - contract_annexes
      - contract_staff (HR)
    """
    conn = db_connect()
    try:
        cur = conn.cursor()

        # -------- vendors --------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS vendors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                company_name     TEXT,
                address          TEXT,
                company_name_vi  TEXT,
                address_vi       TEXT,
                short_name       TEXT,

                tax_id           TEXT,
                tel              TEXT,
                bank_name        TEXT,
                bank_address     TEXT,
                account_name     TEXT,
                account_number   TEXT,
                account_currency TEXT,

                purchasing INTEGER NOT NULL DEFAULT 0, -- 1=Yes, 0=No

                is_active INTEGER NOT NULL DEFAULT 1,
                deleted_at TEXT NULL,

                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.commit()

        # migrations for existing DBs
        ensure_column(conn, "vendors", "account_currency", "TEXT")
        ensure_column(conn, "vendors", "purchasing", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "vendors", "company_name_vi", "TEXT")
        ensure_column(conn, "vendors", "address_vi", "TEXT")
        ensure_column(conn, "vendors", "short_name", "TEXT")

        # -------- contracts (framework) --------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS contracts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                buyer_vendor_id  INTEGER NOT NULL, -- purchasing=1 vendor
                seller_vendor_id INTEGER NOT NULL, -- purchasing=0 vendor

                framework_no   TEXT,
                framework_name TEXT,

                start_date TEXT NULL, -- YYYY-MM-DD
                end_date   TEXT NULL, -- YYYY-MM-DD

                is_active INTEGER NOT NULL DEFAULT 1,
                deleted_at TEXT NULL,

                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),

                FOREIGN KEY(buyer_vendor_id) REFERENCES vendors(id),
                FOREIGN KEY(seller_vendor_id) REFERENCES vendors(id)
            )
        """)
        conn.commit()

        # -------- contract annexes --------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS contract_annexes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                contract_id INTEGER NOT NULL,
                annex_name TEXT,

                start_date TEXT NULL,
                end_date   TEXT NULL,

                is_active INTEGER NOT NULL DEFAULT 1,
                deleted_at TEXT NULL,

                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),

                FOREIGN KEY(contract_id) REFERENCES contracts(id)
            )
        """)
        conn.commit()

        # -------- contract staff (HR) --------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS contract_staff (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                full_name_vi TEXT NOT NULL,
                vendor_id INTEGER NOT NULL,        -- vendor (purchasing=0)

                project_name TEXT NULL,            -- free text (Project)
                position TEXT NULL,

                contract_id INTEGER NOT NULL,      -- framework contract
                annex_id INTEGER NULL,             -- optional; must belong to contract_id if set

                joining_date TEXT NULL,            -- YYYY-MM-DD (required by app to check overlap)
                tentative_leaving_date TEXT NULL,  -- YYYY-MM-DD (nullable)

                monthly_rate REAL NULL,
                manday_rate REAL NULL,

                paid_leave_total_hours REAL NULL,
                paid_leave_used_hours REAL NULL,

                ot INTEGER NOT NULL DEFAULT 0,     -- 1=Yes, 0=No
                status TEXT NULL,                  -- NULL/"" or "inactive"

                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),

                FOREIGN KEY(vendor_id) REFERENCES vendors(id),
                FOREIGN KEY(contract_id) REFERENCES contracts(id),
                FOREIGN KEY(annex_id) REFERENCES contract_annexes(id)
            )
        """)
        conn.commit()

        # -------- attendance --------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                staff_id INTEGER NOT NULL,
                date TEXT NOT NULL, -- YYYY-MM-DD
                check_in TEXT NULL,
                check_out TEXT NULL,
                work_hours REAL NOT NULL DEFAULT 0.0,
                ot_hours REAL NOT NULL DEFAULT 0.0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(staff_id) REFERENCES contract_staff(id),
                UNIQUE(staff_id, date)
            )
        """)
        conn.commit()

        # -------- attendance_locks --------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS attendance_locks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                staff_id INTEGER NOT NULL,
                month TEXT NOT NULL, -- YYYY-MM
                locked INTEGER NOT NULL DEFAULT 1,
                locked_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(staff_id) REFERENCES contract_staff(id),
                UNIQUE(staff_id, month)
            )
        """)
        conn.commit()

        # -------- monthly_attendance_summary --------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS monthly_attendance_summary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                staff_id INTEGER NOT NULL,
                month TEXT NOT NULL, -- YYYY-MM
                standard_days REAL NOT NULL,
                actual_days REAL NOT NULL,
                paid_leave_days REAL NOT NULL DEFAULT 0.0,
                ot_converted_hours REAL NOT NULL DEFAULT 0.0,
                daily_rate REAL NOT NULL DEFAULT 0.0,
                total_amount REAL NOT NULL DEFAULT 0.0,
                locked INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(staff_id) REFERENCES contract_staff(id),
                UNIQUE(staff_id, month)
            )
        """)
        conn.commit()

        try:
            cur.execute("ALTER TABLE monthly_attendance_summary ADD COLUMN locked INTEGER NOT NULL DEFAULT 0")
            conn.commit()
        except sqlite3.OperationalError:
            pass

        try:
            cur.execute("ALTER TABLE monthly_attendance_summary ADD COLUMN manual_work_hours REAL")
            conn.commit()
        except sqlite3.OperationalError:
            pass

        try:
            cur.execute("ALTER TABLE monthly_attendance_summary ADD COLUMN manual_ot_hours REAL")
            conn.commit()
        except sqlite3.OperationalError:
            pass

        try:
            cur.execute("ALTER TABLE contracts ADD COLUMN contract_value REAL")
            conn.commit()
        except sqlite3.OperationalError:
            pass

        try:
            cur.execute("ALTER TABLE contract_annexes ADD COLUMN value REAL")
            conn.commit()
        except sqlite3.OperationalError:
            pass

        # -------- invoices --------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_name TEXT,
                imported_at TEXT,
                
                khhdon TEXT,
                shdon TEXT,
                nlap TEXT,
                dvtte TEXT,
                
                seller_name TEXT,
                seller_mst TEXT,
                seller_address TEXT,
                
                buyer_name TEXT,
                buyer_mst TEXT,
                buyer_address TEXT,
                buyer_bank_name TEXT,
                
                tg_tcthue REAL,
                tg_tthue REAL,
                ttcktmai REAL,
                tg_tttbso REAL,
                
                service_year INTEGER,
                service_month INTEGER,
                service_day INTEGER,
                contract_no TEXT,

                source_path TEXT,
                raw_xml TEXT,
                note TEXT,
                sent_to_mgs INTEGER NOT NULL DEFAULT 0,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        conn.commit()

        try:
            cur.execute("ALTER TABLE invoices ADD COLUMN force_match INTEGER NOT NULL DEFAULT 0")
            conn.commit()
        except sqlite3.OperationalError:
            pass

        # -------- invoice_tax_lines --------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS invoice_tax_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER,
                tsuat TEXT,
                thtien REAL,
                tthue REAL,
                FOREIGN KEY(invoice_id) REFERENCES invoices(id)
            )
        """)
        # -------- contract_references --------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS contract_references (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contract_id INTEGER NOT NULL,
                annex_id INTEGER NOT NULL DEFAULT 0,
                month TEXT NOT NULL,
                reference_number TEXT,
                locked INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(contract_id) REFERENCES contracts(id),
                UNIQUE(contract_id, annex_id, month)
            )
        """)
        conn.commit()

        # migrations for existing DBs
        ensure_column(conn, "contract_staff", "project_name", "TEXT")
        ensure_column(conn, "contract_staff", "work_shift", "TEXT")
        ensure_column(conn, "invoices", "sent_to_mgs", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "contract_references", "locked", "INTEGER NOT NULL DEFAULT 0")

    finally:
        conn.close()


# -------------------- HTTP/HTML helpers --------------------
def layout(title: str, body_html: str):
    """
    NOTE:
    This function returns an f-string.
    In f-strings, literal "{" must be written as "{{" (and "}" as "}}").
    Browser output will have normal CSS braces.
    """
    nav = """
    <div class="nav-container">
      <a href="/dashboard" class="nav-link">Dashboard</a>
      <a href="/" class="nav-link">Invoices</a>
      <a href="/vendors" class="nav-link">Vendors</a>
      <a href="/contracts" class="nav-link">Contracts</a>
      <a href="/staff" class="nav-link">Staff</a>
      <a href="/attendance" class="nav-link">Attendance</a>
    </div>
    """
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} - Mizuho IT Outsourcing Vendor Hub</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {{
      --primary: #4f46e5;
      --primary-hover: #4338ca;
      --bg-main: #f8fafc;
      --bg-card: #ffffff;
      --text-primary: #0f172a;
      --text-secondary: #475569;
      --text-muted: #64748b;
      --border: #e2e8f0;
      --success: #166534;
      --success-bg: #f0fdf4;
      --success-border: #bbf7d0;
      --danger: #991b1b;
      --danger-bg: #fef2f2;
      --danger-border: #fca5a5;
      --warning: #92400e;
      --warning-bg: #fffbeb;
      --warning-border: #fde68a;
      --shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
      --shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.1), 0 1px 2px -1px rgba(0, 0, 0, 0.1);
      --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -2px rgba(0, 0, 0, 0.1);
    }}

    * {{ box-sizing: border-box; }}
    
    body {{
      font-family: 'Plus Jakarta Sans', system-ui, -apple-system, sans-serif;
      margin: 0;
      padding: 0;
      background-color: var(--bg-main);
      color: var(--text-primary);
      line-height: 1.5;
    }}

    a {{
      color: var(--primary);
      text-decoration: none;
      transition: color 0.15s ease;
    }}
    a:hover {{
      color: var(--primary-hover);
      text-decoration: underline;
    }}

    .container {{
      max-width: 1440px;
      margin: 0 auto;
      padding: 24px;
    }}

    /* Global Header */
    .header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 1px solid var(--border);
      background: var(--bg-card);
      padding: 16px 24px;
      box-shadow: var(--shadow-sm);
    }}
    .logo-area {{
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .logo-icon {{
      font-size: 24px;
    }}
    .logo-title {{
      font-size: 18px;
      font-weight: 700;
      margin: 0;
      background: linear-gradient(135deg, #4f46e5 0%, #06b6d4 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }}
    .db-indicator {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      font-size: 12px;
      font-weight: 500;
      color: var(--text-secondary);
      background: var(--bg-main);
      padding: 6px 14px;
      border-radius: 999px;
      border: 1px solid var(--border);
    }}
    .pulse {{
      width: 8px;
      height: 8px;
      background: #10b981;
      border-radius: 50%;
      box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7);
      animation: pulse 2s infinite;
    }}
    @keyframes pulse {{
      0% {{ transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }}
      70% {{ transform: scale(1); box-shadow: 0 0 0 6px rgba(16, 185, 129, 0); }}
      100% {{ transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }}
    }}

    /* Global Navigation */
    .nav-container {{
      display: flex;
      gap: 4px;
      margin: 8px 0 20px 0;
      padding: 4px;
      background: #e2e8f0;
      border-radius: 10px;
      width: fit-content;
    }}
    .nav-link {{
      display: inline-block;
      padding: 8px 18px;
      color: var(--text-secondary);
      font-weight: 600;
      font-size: 14px;
      border-radius: 8px;
      transition: all 0.15s ease;
      text-decoration: none !important;
    }}
    .nav-link:hover {{
      color: var(--text-primary);
      background: rgba(255, 255, 255, 0.4);
    }}
    .nav-link.active {{
      color: var(--primary);
      background: var(--bg-card);
      box-shadow: var(--shadow-sm);
    }}

    .muted {{
      color: var(--text-muted);
      font-size: 13px;
    }}

    /* Tables styling */
    table {{
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      margin: 16px 0;
      border-radius: 12px;
      overflow: hidden;
      border: 1px solid var(--border);
    }}
    th {{
      background: #f8fafc;
      color: var(--text-primary);
      font-weight: 600;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      padding: 12px 16px;
      border-bottom: 1px solid var(--border);
      border-right: 1px solid var(--border);
    }}
    th:last-child {{
      border-right: none;
    }}
    td {{
      padding: 12px 16px;
      color: var(--text-primary);
      font-size: 14px;
      border-bottom: 1px solid var(--border);
      border-right: 1px solid var(--border);
      background: var(--bg-card);
      vertical-align: middle;
    }}
    td:last-child {{
      border-right: none;
    }}
    tr:last-child td {{
      border-bottom: none;
    }}
    tr:hover td {{
      background: #fafafc;
    }}
    /* Daily grid hover overrides */
    tr:hover td.sticky-col1, tr:hover td.sticky-col2 {{
      background: #f1f5f9 !important;
    }}

    /* Cards */
    .card {{
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 20px;
      margin-bottom: 20px;
      box-shadow: var(--shadow-sm);
    }}
    .card.danger {{
      background: var(--danger-bg);
      border-color: var(--danger-border);
      color: var(--danger);
    }}
    .card.success {{
      background: var(--success-bg);
      border-color: var(--success-border);
      color: var(--success);
    }}

    /* Layout & Grids */
    .grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px 24px;
    }}
    .label {{
      color: var(--text-secondary);
      font-size: 12px;
      font-weight: 600;
      margin-bottom: 6px;
    }}
    .value {{
      font-weight: 600;
      font-size: 15px;
    }}

    /* Filters form */
    .filters {{
      margin: 0;
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      align-items: flex-end;
    }}

    /* Input elements */
    input[type="text"], input[type="number"], input[type="date"], input[type="month"], select {{
      padding: 8px 12px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--bg-card);
      color: var(--text-primary);
      font-size: 14px;
      font-family: inherit;
      transition: all 0.15s ease;
      min-width: 120px;
    }}
    input[type="text"]:focus, input[type="number"]:focus, input[type="date"]:focus, input[type="month"]:focus, select:focus, textarea:focus {{
      outline: none;
      border-color: var(--primary);
      box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.12);
    }}
    input[type="number"] {{
      width: 100px;
    }}

    /* Buttons */
    button, .btn {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      padding: 8px 16px;
      font-weight: 600;
      font-size: 14px;
      border-radius: 8px;
      border: 1px solid var(--border);
      background: var(--bg-card);
      color: var(--text-primary);
      cursor: pointer;
      transition: all 0.15s ease;
      user-select: none;
      text-decoration: none !important;
    }}
    button:hover, .btn:hover {{
      background: #fafafa;
      border-color: #cbd5e1;
    }}
    button:active, .btn:active {{
      transform: translateY(1px);
    }}
    
    button[type="submit"]:not(.btn-secondary):not(.btn-danger), .btn-primary {{
      background: var(--primary);
      color: #ffffff;
      border-color: var(--primary);
    }}
    button[type="submit"]:not(.btn-secondary):not(.btn-danger):hover, .btn-primary:hover {{
      background: var(--primary-hover);
      border-color: var(--primary-hover);
      box-shadow: 0 4px 10px rgba(79, 70, 229, 0.15);
      color: #ffffff;
    }}

    .btn-danger {{
      background: var(--danger-bg);
      color: var(--danger);
      border-color: var(--danger-border);
    }}
    .btn-danger:hover {{
      background: #fee2e2;
      border-color: #f87171;
    }}

    .btn-secondary {{
      background: #f1f5f9;
      border-color: var(--border);
      color: var(--text-secondary);
    }}
    .btn-secondary:hover {{
      background: #e2e8f0;
      border-color: #cbd5e1;
    }}

    .cell-mismatch {{
      background: var(--danger-bg) !important;
      border-color: var(--danger-border) !important;
    }}

    textarea {{
      width: 100%;
      min-height: 200px;
      padding: 12px;
      border: 1px solid var(--border);
      border-radius: 8px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 13px;
      line-height: 1.5;
    }}

    form.inline {{
      display: inline;
      margin: 0;
    }}

    .tag {{
      display: inline-block;
      padding: 3px 10px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 600;
      border: 1px solid var(--border);
      background: var(--bg-main);
      color: var(--text-secondary);
      margin-left: 8px;
    }}
    .tag-deactive {{
      border-color: var(--danger-border);
      background: var(--danger-bg);
      color: var(--danger);
    }}
    
    .actions {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      align-items: center;
    }}
  </style>
</head>
<body>
  <div class="header">
    <div class="logo-area">
      <span class="logo-icon">💼</span>
      <h1 class="logo-title">Mizuho IT Outsourcing Vendor Hub</h1>
    </div>
    <div class="db-indicator">
      <span class="pulse"></span>
      <span>DB: {escape(DB_PATH)}</span>
    </div>
  </div>
  
  <div class="container">
    {nav}
    {body_html}
  </div>

  <script>
    window.addEventListener('DOMContentLoaded', () => {{
      // Auto-set active navigation links
      document.querySelectorAll('.nav-link').forEach(link => {{
        const path = window.location.pathname;
        const href = link.getAttribute('href');
        if (path === href || (href !== '/' && path.startsWith(href))) {{
          link.classList.add('active');
        }}
      }});

      // Show native alert for success cards
      const successDiv = document.querySelector('.card.success');
      if (successDiv) {{
        alert(successDiv.innerText.replace("Success:", "").trim());
      }}
    }});

    window.addEventListener('submit', (e) => {{
      if (e.defaultPrevented) return;
      const btns = e.target.querySelectorAll('button[type="submit"]');
      btns.forEach(btn => {{
        setTimeout(() => {{
          if (e.defaultPrevented) return;
          btn.disabled = true;
          btn.innerText = 'Processing...';
        }}, 50);
      }});
    }});
  </script>

  <!-- jsPDF CDN Library -->
  <script src="https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js"></script>

  <!-- MGS Invoice Modal -->
  <div id="mgs-modal" style="display:none; position:fixed; z-index:9999; left:0; top:0; width:100%; height:100%; background:rgba(0,0,0,0.5); align-items:center; justify-content:center;">
    <div style="background:#fff; padding:24px; border-radius:12px; max-width:600px; width:90%; box-shadow:var(--shadow-md); position:relative;">
      <div style="display:flex; align-items:center; gap:12px; margin-bottom:14px; border-bottom:1px solid var(--border); padding-bottom:10px;">
        <h3 style="margin:0; color:var(--text-primary); font-size:16px;">MGS Invoice Processing Request</h3>
      </div>
      <textarea id="mgs-text" style="width:100%; height:180px; font-family:monospace; font-size:13px; margin-bottom:16px; padding:10px; border:1px solid var(--border); border-radius:6px; resize:none;" readonly></textarea>
      <div style="display:flex; align-items:center; gap:8px; margin-bottom:16px;">
        <input type="checkbox" id="mgs-sent-checkbox" style="width:16px; height:16px; min-width:auto; cursor:pointer;" onchange="toggleMgsSentState()">
        <label for="mgs-sent-checkbox" style="font-size:13px; color:var(--text-secondary); cursor:pointer; user-select:none;">I have sent this request to MGS (ticking will disable & color button green)</label>
      </div>
      <div style="display:flex; justify-content:flex-end; gap:10px;">
        <button onclick="downloadMgsPdf()" style="background:#0284c7; color:#fff; border-color:#0284c7;">Download PDF</button>
        <button onclick="copyMgsText()" style="background:var(--primary); color:#fff; border-color:var(--primary);">Copy to Clipboard</button>
        <button onclick="closeMgsModal()" class="btn-secondary">Close</button>
      </div>
    </div>
  </div>

  <script>
    function getBase64Image(imgUrl, callback) {{
      const img = new Image();
      img.src = imgUrl;
      img.crossOrigin = 'Anonymous';
      img.onload = function() {{
        const canvas = document.createElement('canvas');
        canvas.width = img.width;
        canvas.height = img.height;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0);
        const dataURL = canvas.toDataURL('image/png');
        callback(dataURL);
      }};
      img.onerror = function() {{
        callback(null);
      }};
    }}

    let currentMgsData = null;

    function downloadMgsPdf() {{
      if (!currentMgsData) return;
      
      const {{ jsPDF }} = window.jspdf;
      const doc = new jsPDF({{
        orientation: "portrait",
        unit: "mm",
        format: "a4"
      }});
      
      doc.setFont("times", "normal");
      
      // Top Left Vendor Info
      doc.setFontSize(9);
      let y = 15;
      
      doc.text("Company Name:", 20, y);
      doc.text(currentMgsData.vendor.company_name, 50, y);
      y += 5;
      
      doc.text("Tax ID:", 20, y);
      doc.text(currentMgsData.vendor.tax_id, 50, y);
      y += 5;
      
      doc.text("Address:", 20, y);
      const vAddrLines = doc.splitTextToSize(currentMgsData.vendor.address, 135);
      doc.text(vAddrLines, 50, y);
      y += 5 * vAddrLines.length;
      
      doc.text("TEL:", 20, y);
      doc.text(currentMgsData.vendor.tel || "", 50, y);
      
      // Title
      doc.setFont("times", "bolditalic");
      doc.setFontSize(16);
      doc.text("REQUEST FOR PAYMENT", 105, 45, {{ align: "center" }});
      
      // Date
      doc.setFont("times", "normal");
      doc.setFontSize(10);
      doc.text(`Date:  ${{currentMgsData.invoice_date}}`, 190, 58, {{ align: "right" }});
      
      // Buyer Info
      let bY = 66;
      doc.text("To:", 20, bY);
      doc.setFont("times", "bold");
      doc.text(currentMgsData.buyer.company_name, 50, bY);
      bY += 5;
      
      doc.setFont("times", "normal");
      doc.text("To Address:", 20, bY);
      doc.setFont("times", "bold");
      const bAddrLines = doc.splitTextToSize(currentMgsData.buyer.address, 135);
      doc.text(bAddrLines, 50, bY);
      bY += 5 * bAddrLines.length;
      
      doc.setFont("times", "normal");
      doc.text("Mizuho Tax ID:", 20, bY);
      doc.setFont("times", "bold");
      doc.text(currentMgsData.buyer.tax_id, 50, bY);
      
      // Intro
      doc.setFont("times", "normal");
      let introY = bY + 10;
      doc.text("We would like to request for payment as follows:", 20, introY);
      
      // Table starts
      let tableY = introY + 5;
      
      const rows = [
        ["Contract Number", currentMgsData.contract_no, false, 8],
        ["Reference Number", currentMgsData.ref_num, false, 8],
        ["Service Period", currentMgsData.service_period, false, 8],
        ["Content of Work", currentMgsData.content_of_work, false, 14],
        ["Payment Currency", currentMgsData.currency, false, 8],
        ["Invoice Number", currentMgsData.invoice_no, true, 8],
        ["Invoice Date", currentMgsData.invoice_date, true, 8],
        ["Invoice Amount", currentMgsData.invoice_amount, true, 8],
        ["Invoice VAT", currentMgsData.invoice_vat_rate, true, 8],
        ["Invoice VAT Amount", currentMgsData.invoice_vat_amount, true, 8],
        ["Total Invoice Amount", currentMgsData.total_amount, true, 8],
        ["Remittance Detail", "", false, 42]
      ];
      
      let currentY = tableY;
      doc.setLineWidth(0.3);
      
      let totalTableHeight = rows.reduce((sum, row) => sum + row[3], 0);
      doc.line(20, tableY, 20, tableY + totalTableHeight); // Left border
      doc.line(55, tableY, 55, tableY + totalTableHeight); // Middle border
      doc.line(190, tableY, 190, tableY + totalTableHeight); // Right border
      
      doc.line(20, tableY, 190, tableY); // Top horizontal border
      
      rows.forEach((row, index) => {{
        const label = row[0];
        const val = row[1];
        const rightAlign = row[2];
        const h = row[3];
        
        doc.line(20, currentY + h, 190, currentY + h);
        
        doc.setFont("times", "normal");
        doc.setFontSize(9);
        let textY = currentY + (h / 2) + 1;
        if (label === "Remittance Detail") {{
          textY = currentY + 5;
        }}
        doc.text(label, 22, textY);
        
        if (label === "Remittance Detail") {{
          doc.setFont("times", "normal");
          let rY = currentY + 5;
          doc.text("Transfer to:", 57, rY);
          rY += 5;
          doc.text(`Bank Name: ${{currentMgsData.vendor.bank_name}}`, 57, rY);
          rY += 5;
          doc.text(`Bank Address: ${{currentMgsData.vendor.bank_address}}`, 57, rY);
          rY += 5;
          doc.text(`Vendor Remit Adderss: ${{currentMgsData.vendor.address}}`, 57, rY);
          rY += 5;
          doc.text(`Account Name: ${{currentMgsData.vendor.account_name}}`, 57, rY);
          rY += 5;
          doc.text(`Account number: ${{currentMgsData.vendor.account_number}}`, 57, rY);
          rY += 5;
          doc.text(`Account Currency: ${{currentMgsData.vendor.account_currency || currentMgsData.currency}}`, 57, rY);
        }} else {{
          if (rightAlign) {{
            doc.text(val || "-", 188, textY, {{ align: "right" }});
          }} else {{
            const valLines = doc.splitTextToSize(val || "", 131);
            let valY = currentY + (h / 2) - ((valLines.length - 1) * 2.5) + 1;
            if (h === 14) valY = currentY + 5;
            doc.text(valLines, 57, valY);
          }}
        }}
        
        currentY += h;
      }});
      
      doc.setLineWidth(0.5);
      doc.line(20, currentY + 3, 190, currentY + 3);
      doc.line(20, currentY + 4, 190, currentY + 4);
      
      let filename = "mgs_request.pdf";
      if (currentMgsData.ref_num || currentMgsData.vendor.short_name || currentMgsData.mmyyyy) {{
        const refClean = (currentMgsData.ref_num || 'noref').trim().replace(/\\s+/g, '_').replace(/[^a-zA-Z0-9-_]/g, '');
        const snClean = (currentMgsData.vendor.short_name || 'nocop').trim().replace(/\\s+/g, '_').replace(/[^a-zA-Z0-9-_]/g, '');
        const dateClean = (currentMgsData.mmyyyy || 'nodate').trim().replace(/[^0-9]/g, '');
        filename = `invoice_${{refClean}}_${{snClean}}_${{dateClean}}.pdf`;
      }}
      
      doc.save(filename);
    }}

    function showMgsModal(dataJson) {{
      const data = JSON.parse(dataJson);
      currentMgsData = data;
      
      const text = `Subject: INV99999 || ${{data.vendor.company_name}} || Hanoi Branch

Hi Team,

Requesting you to kindly process the Invoice with below details    
                                                                                                        
[Reference Number]: ${{data.ref_num}}    
[Tax ID]: ${{data.vendor.tax_id}}        
[Company Name]: ${{data.vendor.company_name}}               
[Invoice amount]: ${{data.total_amount}}     
[Currency]: ${{data.currency}}
[Invoice Number]: ${{data.invoice_no}}`;
      document.getElementById('mgs-text').value = text;
      document.getElementById('mgs-sent-checkbox').checked = (data.sent_to_mgs === 1);
      document.getElementById('mgs-modal').style.display = 'flex';
    }}
    function closeMgsModal() {{
      document.getElementById('mgs-modal').style.display = 'none';
    }}
    function toggleMgsSentState() {{
      if (!currentMgsData) return;
      const isChecked = document.getElementById('mgs-sent-checkbox').checked;
      const invoiceId = currentMgsData.id;
      
      fetch('/api/invoice/toggle-mgs-sent', {{
        method: 'POST',
        headers: {{
          'Content-Type': 'application/json',
        }},
        body: JSON.stringify({{ id: invoiceId, sent: isChecked ? 1 : 0 }})
      }})
      .then(response => response.json())
      .then(data => {{
        if (data.status === 'ok') {{
          const btn = document.getElementById('mgs-btn-' + invoiceId);
          if (btn) {{
            if (isChecked) {{
              btn.style.background = '#10b981';
              btn.style.color = '#fff';
              btn.style.borderColor = '#10b981';
              btn.disabled = true;
              btn.innerText = 'To MGS (Sent)';
            }} else {{
              btn.style.background = '';
              btn.style.color = '';
              btn.style.borderColor = '';
              btn.disabled = false;
              btn.innerText = 'To MGS';
            }}
          }}
          currentMgsData.sent_to_mgs = isChecked ? 1 : 0;
        }} else {{
          alert('Error saving state: ' + data.message);
          document.getElementById('mgs-sent-checkbox').checked = !isChecked;
        }}
      }})
      .catch(err => {{
        alert('Connection error: ' + err);
        document.getElementById('mgs-sent-checkbox').checked = !isChecked;
      }});
    }}
    function copyMgsText() {{
      const txt = document.getElementById('mgs-text');
      txt.select();
      document.execCommand('copy');
      alert('Copied to clipboard!');
    }}
  </script>
</body>
</html>
"""


def send_html(handler, html_text: str, status=200):
    data = html_text.encode("utf-8", errors="ignore")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def redirect(handler, location: str):
    handler.send_response(302)
    handler.send_header("Location", location)
    handler.end_headers()


def read_post_form(handler):
    length = int(handler.headers.get("Content-Length", "0") or "0")
    raw = handler.rfile.read(length).decode("utf-8", errors="ignore")
    return urllib.parse.parse_qs(raw, keep_blank_values=True)


def safe_return_to(s: str | None) -> str:
    if not s:
        return "/"
    s = s.strip()
    if not s.startswith("/"):
        return "/"
    return s


def parse_int_or_none(s):
    if s is None:
        return None
    s = str(s).strip()
    if s == "":
        return None
    try:
        return int(s)
    except ValueError:
        return None


def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def fmt_money(amount, currency: str | None = None):
    if amount is None:
        return ""
    try:
        s = f"{float(amount):,.2f}"
    except (ValueError, TypeError):
        s = str(amount)
    return f"{s} {currency}" if currency else s
