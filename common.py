# common.py
# Shared helpers for server (no extra libraries)

import sqlite3
import urllib.parse
from html import escape
from datetime import datetime
from pathlib import Path

import os
DB_PATH = os.environ.get("DB_PATH", str(Path(__file__).resolve().with_name("db.sqlite3")))

HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", "8800"))
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

                position TEXT NULL,
                joining_date TEXT NULL,
                tentative_leaving_date TEXT NULL,

                paid_leave_total_hours REAL NULL,
                paid_leave_used_hours REAL NULL,

                ot INTEGER NOT NULL DEFAULT 0,     -- 1=Yes, 0=No
                status TEXT NULL,                  -- NULL/"" or "inactive"

                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),

                FOREIGN KEY(vendor_id) REFERENCES vendors(id)
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

        try:
            cur.execute("ALTER TABLE contract_annexes ADD COLUMN cashout_date TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass

        # -------- annex_cashouts --------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS annex_cashouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                annex_id INTEGER NOT NULL,
                month TEXT NOT NULL,
                cashout_date TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(annex_id) REFERENCES contract_annexes(id),
                UNIQUE(annex_id, month)
            )
        """)
        conn.commit()

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

        # -------- contract staff contract links --------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS contract_staff_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                staff_id INTEGER NOT NULL,
                contract_id INTEGER NOT NULL,
                annex_id INTEGER NULL,
                monthly_rate REAL NULL,
                manday_rate REAL NULL,
                joining_date TEXT NULL,
                tentative_leaving_date TEXT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(staff_id) REFERENCES contract_staff(id),
                FOREIGN KEY(contract_id) REFERENCES contracts(id),
                FOREIGN KEY(annex_id) REFERENCES contract_annexes(id)
            )
        """)
        conn.commit()

        # -------- projects --------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                short_name TEXT NOT NULL,
                full_name TEXT NOT NULL,
                it_outsourcing_budget REAL,
                os_start_date TEXT,
                os_end_date TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.commit()

        # -------- project_staff_assignments --------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS project_staff_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                staff_id INTEGER NOT NULL,
                month TEXT NOT NULL, -- YYYY-MM
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(project_id) REFERENCES projects(id),
                FOREIGN KEY(staff_id) REFERENCES contract_staff(id),
                UNIQUE(staff_id, month)
            )
        """)
        conn.commit()

        # -------- audit_logs --------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                table_name TEXT,
                record_id INTEGER,
                description TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.commit()

        # -------- migrations & column checks for existing DBs --------
        ensure_column(conn, "vendors", "company_name_vi", "TEXT")
        ensure_column(conn, "vendors", "address_vi", "TEXT")
        ensure_column(conn, "vendors", "short_name", "TEXT")
        ensure_column(conn, "vendors", "account_currency", "TEXT")
        ensure_column(conn, "vendors", "purchasing", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "vendors", "is_active", "INTEGER NOT NULL DEFAULT 1")
        ensure_column(conn, "vendors", "deleted_at", "TEXT")

        ensure_column(conn, "contracts", "contract_value", "REAL")
        ensure_column(conn, "contracts", "is_active", "INTEGER NOT NULL DEFAULT 1")
        ensure_column(conn, "contracts", "deleted_at", "TEXT")

        ensure_column(conn, "contract_annexes", "value", "REAL")
        ensure_column(conn, "contract_annexes", "is_active", "INTEGER NOT NULL DEFAULT 1")
        ensure_column(conn, "contract_annexes", "deleted_at", "TEXT")

        ensure_column(conn, "contract_staff", "work_shift", "TEXT")
        ensure_column(conn, "contract_staff", "joining_date", "TEXT")
        ensure_column(conn, "contract_staff", "tentative_leaving_date", "TEXT")
        ensure_column(conn, "contract_staff", "paid_leave_total_hours", "REAL")
        ensure_column(conn, "contract_staff", "paid_leave_used_hours", "REAL")
        ensure_column(conn, "contract_staff", "ot", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "contract_staff", "status", "TEXT")

        ensure_column(conn, "contract_staff_links", "joining_date", "TEXT")
        ensure_column(conn, "contract_staff_links", "tentative_leaving_date", "TEXT")
        ensure_column(conn, "contract_staff_links", "paid_leave_total_hours", "REAL NULL DEFAULT 0.0")

        ensure_column(conn, "monthly_attendance_summary", "locked", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "monthly_attendance_summary", "manual_work_hours", "REAL")
        ensure_column(conn, "monthly_attendance_summary", "manual_ot_hours", "REAL")

        ensure_column(conn, "invoices", "sent_to_mgs", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "invoices", "force_match", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "invoices", "note", "TEXT")

        ensure_column(conn, "contract_references", "locked", "INTEGER NOT NULL DEFAULT 0")

        ensure_column(conn, "projects", "it_outsourcing_budget", "REAL")
        ensure_column(conn, "projects", "os_start_date", "TEXT")
        ensure_column(conn, "projects", "os_end_date", "TEXT")
        ensure_column(conn, "projects", "is_active", "INTEGER NOT NULL DEFAULT 1")

        # Indexes for query speed
        cur.execute("CREATE INDEX IF NOT EXISTS idx_psa_proj_staff ON project_staff_assignments(project_id, staff_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_psa_month ON project_staff_assignments(month)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_mas_staff_month ON monthly_attendance_summary(staff_id, month)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_csl_staff ON contract_staff_links(staff_id)")
        conn.commit()

        # Check table columns of contract_staff to see if migration is needed
        table_cols = [r["name"] for r in cur.execute("PRAGMA table_info(contract_staff)").fetchall()]
        if "contract_id" in table_cols:
            # First ensure contract_staff_links count
            links_count = cur.execute("SELECT COUNT(*) AS c FROM contract_staff_links").fetchone()["c"]
            if links_count == 0:
                # Migrate old staff contracts data to contract_staff_links
                old_rows = cur.execute("SELECT id, contract_id, annex_id, monthly_rate, manday_rate, joining_date, tentative_leaving_date, created_at, updated_at FROM contract_staff").fetchall()
                for r in old_rows:
                    if r["contract_id"] is not None:
                        cur.execute("""
                            INSERT INTO contract_staff_links (staff_id, contract_id, annex_id, monthly_rate, manday_rate, joining_date, tentative_leaving_date, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (r["id"], r["contract_id"], r["annex_id"], r["monthly_rate"], r["manday_rate"], r["joining_date"], r["tentative_leaving_date"], r["created_at"], r["updated_at"]))
                conn.commit()

            # Safely rebuild the contract_staff table to drop the legacy columns (to avoid foreign key constraint check failures on ALTER TABLE DROP COLUMN)
            try:
                cur.execute("PRAGMA foreign_keys = OFF;")
                cur.execute("ALTER TABLE contract_staff RENAME TO contract_staff_old;")
                cur.execute("""
                    CREATE TABLE contract_staff (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        full_name_vi TEXT NOT NULL,
                        vendor_id INTEGER NOT NULL,        -- vendor (purchasing=0)
                        position TEXT NULL,
                        joining_date TEXT NULL,
                        tentative_leaving_date TEXT NULL,
                        paid_leave_total_hours REAL NULL,
                        paid_leave_used_hours REAL NULL,
                        ot INTEGER NOT NULL DEFAULT 0,     -- 1=Yes, 0=No
                        status TEXT NULL,                  -- NULL/"" or "inactive"
                        created_at TEXT NOT NULL DEFAULT (datetime('now')),
                        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                        work_shift TEXT,
                        FOREIGN KEY(vendor_id) REFERENCES vendors(id)
                    );
                """)
                cur.execute("""
                    INSERT INTO contract_staff (
                        id, full_name_vi, vendor_id, position, joining_date, tentative_leaving_date,
                        paid_leave_total_hours, paid_leave_used_hours,
                        ot, status, created_at, updated_at, work_shift
                    )
                    SELECT 
                        id, full_name_vi, vendor_id, position, joining_date, tentative_leaving_date,
                        paid_leave_total_hours, paid_leave_used_hours,
                        ot, status, created_at, updated_at, work_shift
                    FROM contract_staff_old;
                """)
                cur.execute("DROP TABLE contract_staff_old;")
                conn.commit()
            except Exception as e:
                conn.rollback()
                print(f"Error rebuilding contract_staff table: {e}")
                raise e
            finally:
                try:
                    cur.execute("PRAGMA foreign_keys = ON;")
                except:
                    pass

    finally:
        conn.close()


def log_action(conn_or_cursor, action: str, table_name: str | None = None, record_id: int | None = None, description: str = ""):
    try:
        conn_or_cursor.execute("""
            INSERT INTO audit_logs (action, table_name, record_id, description, created_at)
            VALUES (?, ?, ?, ?, datetime('now', 'localtime'))
        """, (action, table_name, record_id, description))
    except Exception as e:
        print(f"Failed to write audit log: {e}")


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
      <div class="nav-dropdown">
        <a href="/staff" class="nav-link nav-dropdown-toggle">Staff <span style="font-size: 10px; margin-left: 2px;">▾</span></a>
        <div class="nav-dropdown-menu">
          <a href="/projects/assign#add-staff-section" class="nav-dropdown-item">Assign Staff to Project</a>
        </div>
      </div>
      <a href="/projects" class="nav-link">Projects</a>
      <a href="/attendance" class="nav-link">Timesheet & Payroll</a>
      <a href="/audit-logs" class="nav-link">Audit Logs</a>
      <a href="/playwright" class="nav-link">UAT Runner</a>
      <a href="/unit-tests" class="nav-link">Unit Tests</a>
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

    .nav-dropdown {{
      position: relative;
      display: inline-block;
    }}
    .nav-dropdown-toggle {{
      display: inline-flex;
      align-items: center;
      gap: 4px;
      cursor: pointer;
    }}
    .nav-dropdown-menu {{
      display: none;
      position: absolute;
      top: 100%;
      left: 0;
      min-width: 220px;
      background: #ffffff;
      border: 1px solid var(--border);
      border-radius: 8px;
      box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -4px rgba(0, 0, 0, 0.1);
      padding: 6px 0;
      z-index: 99999;
      margin: 0;
    }}
    .nav-dropdown-menu::before {{
      content: "";
      position: absolute;
      top: -12px;
      left: 0;
      right: 0;
      height: 12px;
      background: transparent;
    }}
    .nav-dropdown:hover .nav-dropdown-menu,
    .nav-dropdown:focus-within .nav-dropdown-menu {{
      display: block;
    }}
    .nav-dropdown-item {{
      display: block;
      padding: 10px 18px;
      color: var(--text-primary);
      font-weight: 500;
      font-size: 13px;
      text-decoration: none !important;
      transition: background 0.15s ease, color 0.15s ease;
      cursor: pointer;
    }}
    .nav-dropdown-item:hover {{
      background: #f1f5f9;
      color: var(--primary);
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

  <!-- MGS Invoice Modal with Live PDF Preview -->
  <div id="mgs-modal" style="display:none; position:fixed; z-index:9999; left:0; top:0; width:100%; height:100%; background:rgba(0,0,0,0.6); align-items:center; justify-content:center; padding:20px; box-sizing:border-box;">
    <div style="background:#fff; border-radius:12px; max-width:880px; width:100%; max-height:92vh; display:flex; flex-direction:column; box-shadow:0 20px 25px -5px rgba(0,0,0,0.2), 0 10px 10px -5px rgba(0,0,0,0.04); position:relative; overflow:hidden;">
      
      <!-- Modal Header -->
      <div style="display:flex; align-items:center; justify-content:space-between; padding:14px 20px; border-bottom:1px solid var(--border); background:#f8fafc;">
        <div style="display:flex; align-items:center; gap:8px;">
          <span style="font-size:18px;">📧</span>
          <h3 style="margin:0; color:var(--text-primary); font-size:16px; font-weight:700;">MGS Invoice Processing & Document Preview</h3>
        </div>
        <button type="button" onclick="closeMgsModal()" style="background:none; border:none; font-size:20px; cursor:pointer; color:var(--text-muted); padding:0 4px; line-height:1;">✕</button>
      </div>

      <!-- Modal Body (Scrollable) -->
      <div style="padding:18px 20px; overflow-y:auto; flex:1;">
        
        <!-- Section 1: Email Notification Content -->
        <div style="margin-bottom:20px; background:#f8fafc; border:1px solid var(--border); border-radius:8px; padding:14px;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
            <label style="font-weight:700; font-size:13px; color:var(--text-primary); display:flex; align-items:center; gap:6px;">
              <span>✉️ Email Content (To MGS Team)</span>
            </label>
            <button type="button" onclick="copyMgsText()" class="btn-secondary" style="font-size:11px; padding:3px 10px; display:inline-flex; align-items:center; gap:4px; font-weight:600;">
              📋 Copy Email Content
            </button>
          </div>
          <textarea id="mgs-text" style="width:100%; height:130px; font-family:monospace; font-size:12px; padding:10px; border:1px solid var(--border); border-radius:6px; resize:vertical; background:#fff; color:#1e293b; line-height:1.45; box-sizing:border-box;" readonly></textarea>
          
          <div style="display:flex; align-items:center; gap:8px; margin-top:10px;">
            <input type="checkbox" id="mgs-sent-checkbox" style="width:16px; height:16px; min-width:auto; cursor:pointer;" onchange="toggleMgsSentState()">
            <label for="mgs-sent-checkbox" style="font-size:13px; color:var(--text-secondary); cursor:pointer; user-select:none; font-weight:500;">I have sent this request to MGS (ticking will disable & color button green)</label>
          </div>
        </div>

        <!-- Section 2: PDF Document Live Preview -->
        <div>
          <style>
            .mgs-editable {{
              cursor: text;
              border-radius: 3px;
              padding: 1px 4px;
              transition: background 0.15s, outline 0.15s;
              outline: 1px dashed transparent;
            }}
            .mgs-editable:hover {{
              background-color: #f1f5f9;
              outline: 1px dashed #64748b;
            }}
            .mgs-editable:focus {{
              background-color: #eff6ff;
              outline: 2px solid #2563eb;
              box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.15);
            }}
            @media print {{
              .mgs-editable {{
                outline: none !important;
                background: transparent !important;
              }}
            }}
          </style>

          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; padding:0 2px;">
            <div>
              <span style="font-weight:700; font-size:14px; color:var(--text-primary); display:flex; align-items:center; gap:6px;">
                <span>📄 Request For Payment Cover Sheet (Live Document Preview)</span>
              </span>
              <div class="muted" style="font-size:12px;">Pre-rendering exact document layout. Verify all details below before downloading PDF.</div>
            </div>
            <div style="display:flex; gap:8px;">
              <button type="button" onclick="printMgsPreview()" class="btn-secondary" style="font-size:11px; padding:4px 10px; display:inline-flex; align-items:center; gap:4px;">
                🖨️ Print Preview
              </button>
              <button type="button" onclick="downloadMgsPdf()" style="background:#0284c7; color:#fff; border-color:#0284c7; font-size:11px; padding:4px 12px; display:inline-flex; align-items:center; gap:4px; font-weight:600;">
                📥 Download PDF
              </button>
            </div>
          </div>

          <!-- Banner with instruction and Reset button -->
          <div style="background:#f0fdf4; border:1px solid #bbf7d0; border-radius:6px; padding:6px 12px; margin-bottom:10px; display:flex; align-items:center; justify-content:space-between; font-size:12px; color:#166534;">
            <div style="display:flex; align-items:center; gap:6px;">
              <span>✏️</span>
              <span><b>Interactive Preview:</b> Click directly on any text below to edit. Changes apply only to exported PDF / Print without altering database records.</span>
            </div>
            <button type="button" onclick="resetMgsPreview()" class="btn-secondary" style="font-size:11px; padding:2px 8px; background:#fff; color:#1e293b; border-color:#cbd5e1; white-space:nowrap; cursor:pointer;" title="Revert all edits back to original database values">
              ↺ Reset to Original
            </button>
          </div>

          <!-- A4 Paper Visual Preview Container -->
          <div id="mgs-pdf-preview" style="background:#fff; border:1px solid #cbd5e1; border-radius:6px; box-shadow:0 4px 6px -1px rgba(0,0,0,0.06); padding:28px 32px; font-family:'Times New Roman', Times, Georgia, serif; color:#0f172a; font-size:13px; line-height:1.45;">
            <!-- Rendered dynamically by renderMgsPdfPreview(data) -->
          </div>
        </div>

      </div>

      <!-- Modal Footer -->
      <div style="display:flex; justify-content:space-between; align-items:center; padding:12px 20px; border-top:1px solid var(--border); background:#f8fafc;">
        <span class="muted" style="font-size:11px;">⚠️ Check recipient bank and remittance details carefully before approval.</span>
        <div style="display:flex; gap:8px;">
          <button type="button" onclick="downloadMgsPdf()" style="background:#0284c7; color:#fff; border-color:#0284c7; font-weight:600; display:inline-flex; align-items:center; gap:5px; font-size:12px; padding:5px 14px;">
            📥 Download PDF
          </button>
          <button type="button" onclick="copyMgsText()" style="background:var(--primary); color:#fff; border-color:var(--primary); font-weight:600; font-size:12px; padding:5px 14px;">
            📋 Copy Email
          </button>
          <button type="button" onclick="closeMgsModal()" class="btn-secondary" style="font-size:12px; padding:5px 14px;">Close</button>
        </div>
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

    function getEditedMgsData() {{
      if (!currentMgsData) return null;
      const getText = (id, fallback) => {{
        const el = document.getElementById(id);
        if (!el) return (fallback || "");
        const txt = el.innerText !== undefined ? el.innerText : el.textContent;
        const res = (txt || "").trim();
        return (res === "-" && fallback && fallback !== "-") ? fallback : res;
      }};
      
      const v = currentMgsData.vendor || {{}};
      const b = currentMgsData.buyer || {{}};
      
      return Object.assign({{}}, currentMgsData, {{
        contract_no: getText('mgs-val-contract-no', currentMgsData.contract_no),
        ref_num: getText('mgs-val-ref-num', currentMgsData.ref_num),
        service_period: getText('mgs-val-service-period', currentMgsData.service_period),
        content_of_work: getText('mgs-val-content-of-work', currentMgsData.content_of_work),
        currency: getText('mgs-val-currency', currentMgsData.currency),
        invoice_no: getText('mgs-val-invoice-no', currentMgsData.invoice_no),
        invoice_date: getText('mgs-val-invoice-date', currentMgsData.invoice_date) || getText('mgs-val-date', currentMgsData.invoice_date),
        invoice_amount: getText('mgs-val-invoice-amount', currentMgsData.invoice_amount),
        invoice_vat_rate: getText('mgs-val-invoice-vat-rate', currentMgsData.invoice_vat_rate),
        invoice_vat_amount: getText('mgs-val-invoice-vat-amount', currentMgsData.invoice_vat_amount),
        total_amount: getText('mgs-val-total-amount', currentMgsData.total_amount),
        vendor: Object.assign({{}}, v, {{
          company_name: getText('mgs-val-v-company', v.company_name),
          tax_id: getText('mgs-val-v-taxid', v.tax_id),
          tel: getText('mgs-val-v-tel', v.tel),
          bank_name: getText('mgs-val-bank-name', v.bank_name),
          bank_address: getText('mgs-val-bank-address', v.bank_address),
          address: getText('mgs-val-remit-address', v.address) || getText('mgs-val-v-address', v.address),
          account_name: getText('mgs-val-account-name', v.account_name),
          account_number: getText('mgs-val-account-number', v.account_number),
          account_currency: getText('mgs-val-account-currency', v.account_currency || currentMgsData.currency)
        }}),
        buyer: Object.assign({{}}, b, {{
          company_name: getText('mgs-val-b-company', b.company_name),
          address: getText('mgs-val-b-address', b.address),
          tax_id: getText('mgs-val-b-taxid', b.tax_id)
        }})
      }});
    }}

    function downloadMgsPdf() {{
      if (!currentMgsData) return;
      const activeData = getEditedMgsData() || currentMgsData;
      
      const {{ jsPDF }} = window.jspdf;
      const doc = new jsPDF({{
        orientation: "portrait",
        unit: "mm",
        format: "a4"
      }});
      
      const v = activeData.vendor || {{}};
      const b = activeData.buyer || {{}};
      
      // Top Left Vendor Info
      doc.setFont("times", "normal");
      doc.setFontSize(9);
      let y = 14;
      
      doc.text("Company Name:", 20, y);
      const vCompLines = doc.splitTextToSize(v.company_name || "-", 135);
      doc.text(vCompLines, 50, y);
      y += 4.5 * Math.max(1, vCompLines.length);
      
      doc.text("Tax ID:", 20, y);
      doc.text(v.tax_id || "-", 50, y);
      y += 4.5;
      
      doc.text("Address:", 20, y);
      const vAddrLines = doc.splitTextToSize(v.address || "-", 135);
      doc.text(vAddrLines, 50, y);
      y += 4.5 * Math.max(1, vAddrLines.length);
      
      doc.text("TEL:", 20, y);
      doc.text(v.tel || "-", 50, y);
      y += 4.5;
      
      // Title
      doc.setFont("times", "bolditalic");
      doc.setFontSize(16);
      let titleY = Math.max(y + 7, 42);
      doc.text("REQUEST FOR PAYMENT", 105, titleY, {{ align: "center" }});
      
      // Date
      doc.setFont("times", "normal");
      doc.setFontSize(10);
      let dateY = titleY + 8;
      doc.text(`Date:  ${{activeData.invoice_date || "-"}}`, 190, dateY, {{ align: "right" }});
      
      // Buyer Info
      let bY = dateY + 6;
      doc.setFont("times", "normal");
      doc.setFontSize(9);
      
      doc.text("To:", 20, bY);
      doc.setFont("times", "bold");
      const bCompLines = doc.splitTextToSize(b.company_name || "-", 135);
      doc.text(bCompLines, 50, bY);
      bY += 4.5 * Math.max(1, bCompLines.length);
      
      doc.setFont("times", "normal");
      doc.text("To Address:", 20, bY);
      doc.setFont("times", "bold");
      const bAddrLines = doc.splitTextToSize(b.address || "-", 135);
      doc.text(bAddrLines, 50, bY);
      bY += 4.5 * Math.max(1, bAddrLines.length);
      
      doc.setFont("times", "normal");
      doc.text("Mizuho Tax ID:", 20, bY);
      doc.setFont("times", "bold");
      doc.text(b.tax_id || "-", 50, bY);
      bY += 4.5;
      
      // Intro
      doc.setFont("times", "normal");
      let introY = bY + 7;
      doc.text("We would like to request for payment as follows:", 20, introY);
      
      let tableY = introY + 4;
      
      // Prepare remittance detail items and split lines with max width 130mm
      const curr = v.account_currency || activeData.currency || "-";
      const remitSections = [
        {{ text: "Transfer to:", bold: true }},
        {{ text: `Bank Name: ${{v.bank_name || "-"}}`, bold: false }},
        {{ text: `Bank Address: ${{v.bank_address || "-"}}`, bold: false }},
        {{ text: `Vendor Remit Address: ${{v.address || "-"}}`, bold: false }},
        {{ text: `Account Name: ${{v.account_name || "-"}}`, bold: false }},
        {{ text: `Account number: ${{v.account_number || "-"}}`, bold: false }},
        {{ text: `Account Currency: ${{curr}}`, bold: false }}
      ];
      
      let remitLines = [];
      remitSections.forEach(sec => {{
        if (sec.bold) {{
          remitLines.push({{ text: sec.text, bold: true }});
        }} else {{
          const splitted = doc.splitTextToSize(sec.text, 130);
          splitted.forEach(l => {{
            remitLines.push({{ text: l, bold: false }});
          }});
        }}
      }});
      
      const remitH = Math.max(38, (remitLines.length * 4.3) + 4);
      
      // Rows definition
      const rawRows = [
        {{ label: "Contract Number", val: activeData.contract_no, rightAlign: false, bold: false }},
        {{ label: "Reference Number", val: activeData.ref_num, rightAlign: false, bold: false }},
        {{ label: "Service Period", val: activeData.service_period, rightAlign: false, bold: false }},
        {{ label: "Content of Work", val: activeData.content_of_work, rightAlign: false, bold: false }},
        {{ label: "Payment Currency", val: activeData.currency, rightAlign: false, bold: false }},
        {{ label: "Invoice Number", val: activeData.invoice_no, rightAlign: true, bold: false }},
        {{ label: "Invoice Date", val: activeData.invoice_date, rightAlign: true, bold: false }},
        {{ label: "Invoice Amount", val: activeData.invoice_amount, rightAlign: true, bold: false }},
        {{ label: "Invoice VAT", val: activeData.invoice_vat_rate, rightAlign: true, bold: false }},
        {{ label: "Invoice VAT Amount", val: activeData.invoice_vat_amount, rightAlign: true, bold: false }},
        {{ label: "Total Invoice Amount", val: activeData.total_amount, rightAlign: true, bold: true }},
        {{ label: "Remittance Detail", val: null, rightAlign: false, isRemittance: true }}
      ];
      
      const processedRows = rawRows.map(r => {{
        if (r.isRemittance) {{
          return Object.assign({{}}, r, {{ h: remitH }});
        }}
        const valStr = String(r.val || "-");
        let lines = [];
        if (r.rightAlign) {{
          lines = [valStr];
        }} else {{
          lines = doc.splitTextToSize(valStr, 130);
        }}
        const h = Math.max(7.5, (lines.length * 4.3) + 3.2);
        return Object.assign({{}}, r, {{ lines: lines, h: h }});
      }});
      
      doc.setLineWidth(0.3);
      doc.line(20, tableY, 190, tableY); // Top horizontal border
      
      let currentY = tableY;
      
      processedRows.forEach(r => {{
        const nextY = currentY + r.h;
        doc.line(20, nextY, 190, nextY); // Row bottom border
        
        doc.setFont("times", r.bold ? "bold" : "normal");
        doc.setFontSize(9);
        
        let labelY = (r.h > 8) ? (currentY + 4.5) : (currentY + (r.h / 2) + 1.2);
        doc.text(r.label, 22, labelY);
        
        if (r.isRemittance) {{
          let rY = currentY + 4.5;
          remitLines.forEach(rl => {{
            doc.setFont("times", rl.bold ? "bold" : "normal");
            doc.text(rl.text, 57, rY);
            rY += 4.3;
          }});
        }} else {{
          if (r.rightAlign) {{
            let numY = currentY + (r.h / 2) + 1.2;
            doc.text(r.lines[0], 188, numY, {{ align: "right" }});
          }} else {{
            let valY = (r.lines.length > 1) ? (currentY + 4.5) : (currentY + (r.h / 2) + 1.2);
            r.lines.forEach(l => {{
              doc.text(l, 57, valY);
              valY += 4.3;
            }});
          }}
        }}
        
        currentY = nextY;
      }});
      
      // Vertical borders
      doc.line(20, tableY, 20, currentY); // Left border
      doc.line(55, tableY, 55, currentY); // Middle divider
      doc.line(190, tableY, 190, currentY); // Right border
      
      // Double bottom border
      doc.setLineWidth(0.5);
      doc.line(20, currentY + 2.5, 190, currentY + 2.5);
      doc.line(20, currentY + 3.5, 190, currentY + 3.5);
      
      function cleanFilenamePart(s) {{
        if (!s) return "";
        return String(s).trim()
          .replace(/[\\\\/]+/g, "-")
          .replace(/\\s+/g, "_")
          .replace(/[:*?"<>|]/g, "")
          .replace(/_+/g, "_")
          .replace(/^[-_]+|[-_]+$/g, "");
      }}

      const refClean = cleanFilenamePart(activeData.ref_num) || 'noref';
      const snClean = cleanFilenamePart(v.short_name) || 'nocop';

      let contractPart = '';
      let annexPart = '';

      if (activeData.contract_no && activeData.contract_no !== (currentMgsData && currentMgsData.contract_no)) {{
        // User edited the contract number directly on the popup preview
        contractPart = cleanFilenamePart(activeData.contract_no);
      }} else {{
        const fNo = activeData.framework_no || activeData.contract_no || '';
        const aName = activeData.annex_name || '';
        contractPart = cleanFilenamePart(fNo);
        if (aName && aName.trim().toLowerCase() !== fNo.trim().toLowerCase()) {{
          annexPart = cleanFilenamePart(aName);
        }}
      }}

      if (!contractPart) {{
        contractPart = 'nocontract';
      }}

      const dateClean = (activeData.mmyyyy || '').trim().replace(/[^0-9]/g, '');

      // Formula: invoice_[refClean]_[snClean]_[ten hop dong khung]_[ten phu luc neu co]_[thang dich vu neu co].pdf
      const filenameParts = ['invoice', refClean, snClean, contractPart];
      if (annexPart) {{
        filenameParts.push(annexPart);
      }}
      if (dateClean) {{
        filenameParts.push(dateClean);
      }}
      const filename = filenameParts.join('_') + '.pdf';
      
      doc.save(filename);
    }}

    function escapeHtml(str) {{
      if (str === null || str === undefined) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }}

    function resetMgsPreview() {{
      if (currentMgsData) {{
        renderMgsPdfPreview(currentMgsData);
      }}
    }}

    function renderMgsPdfPreview(data) {{
      const v = data.vendor || {{}};
      const b = data.buyer || {{}};
      const container = document.getElementById('mgs-pdf-preview');
      if (!container) return;

      container.innerHTML = `
        <div style="font-family:'Times New Roman', Times, Georgia, serif; color:#000; line-height:1.45; font-size:13px;">
          <!-- Top Left Vendor Details -->
          <div style="margin-bottom:18px;">
            <table style="width:100%; border:none; border-collapse:collapse; margin:0 0 10px 0; font-size:12px;">
              <tr>
                <td style="width:115px; border:none; padding:1px 0; color:#475569;">Company Name:</td>
                <td style="border:none; padding:1px 0;"><span id="mgs-val-v-company" class="mgs-editable" contenteditable="true" spellcheck="false" title="Click to edit" style="font-weight:600; color:#0f172a;">${{escapeHtml(v.company_name || '-')}}</span></td>
              </tr>
              <tr>
                <td style="width:115px; border:none; padding:1px 0; color:#475569;">Tax ID:</td>
                <td style="border:none; padding:1px 0;"><span id="mgs-val-v-taxid" class="mgs-editable" contenteditable="true" spellcheck="false" title="Click to edit" style="color:#0f172a;">${{escapeHtml(v.tax_id || '-')}}</span></td>
              </tr>
              <tr>
                <td style="border:none; padding:1px 0; color:#475569; vertical-align:top;">Address:</td>
                <td style="border:none; padding:1px 0;"><span id="mgs-val-v-address" class="mgs-editable" contenteditable="true" spellcheck="false" title="Click to edit" style="color:#0f172a;">${{escapeHtml(v.address || '-')}}</span></td>
              </tr>
              <tr>
                <td style="border:none; padding:1px 0; color:#475569;">TEL:</td>
                <td style="border:none; padding:1px 0;"><span id="mgs-val-v-tel" class="mgs-editable" contenteditable="true" spellcheck="false" title="Click to edit" style="color:#0f172a;">${{escapeHtml(v.tel || '-')}}</span></td>
              </tr>
            </table>
          </div>

          <!-- Document Title -->
          <div style="text-align:center; margin:22px 0 16px 0;">
            <div style="font-size:19px; font-weight:bold; font-style:italic; letter-spacing:0.5px; text-transform:uppercase;">REQUEST FOR PAYMENT</div>
          </div>

          <!-- Date -->
          <div style="text-align:right; margin-bottom:14px; font-size:13px;">
            <b>Date:</b> &nbsp; <span id="mgs-val-date" class="mgs-editable" contenteditable="true" spellcheck="false" title="Click to edit">${{escapeHtml(data.invoice_date || '-')}}</span>
          </div>

          <!-- Buyer Details -->
          <div style="margin-bottom:16px;">
            <table style="width:100%; border:none; border-collapse:collapse; margin:0 0 10px 0; font-size:13px;">
              <tr>
                <td style="width:115px; border:none; padding:2px 0; color:#475569;">To:</td>
                <td style="border:none; padding:2px 0;"><span id="mgs-val-b-company" class="mgs-editable" contenteditable="true" spellcheck="false" title="Click to edit" style="font-weight:bold; color:#0f172a;">${{escapeHtml(b.company_name || '-')}}</span></td>
              </tr>
              <tr>
                <td style="border:none; padding:2px 0; color:#475569; vertical-align:top;">To Address:</td>
                <td style="border:none; padding:2px 0;"><span id="mgs-val-b-address" class="mgs-editable" contenteditable="true" spellcheck="false" title="Click to edit" style="font-weight:bold; color:#0f172a;">${{escapeHtml(b.address || '-')}}</span></td>
              </tr>
              <tr>
                <td style="border:none; padding:2px 0; color:#475569;">Mizuho Tax ID:</td>
                <td style="border:none; padding:2px 0;"><span id="mgs-val-b-taxid" class="mgs-editable" contenteditable="true" spellcheck="false" title="Click to edit" style="font-weight:bold; color:#0f172a;">${{escapeHtml(b.tax_id || '-')}}</span></td>
              </tr>
            </table>
          </div>

          <!-- Intro statement -->
          <div style="margin-bottom:10px; font-size:13px;">
            We would like to request for payment as follows:
          </div>

          <!-- Main Table -->
          <table style="width:100%; border-collapse:collapse; border:1px solid #000; margin:0 0 4px 0; font-size:12.5px;">
            <tbody>
              <tr>
                <td style="width:34%; border:1px solid #000; padding:6px 10px;">Contract Number</td>
                <td id="mgs-val-contract-no" class="mgs-editable" contenteditable="true" spellcheck="false" title="Click to edit" style="border:1px solid #000; padding:6px 10px;">${{escapeHtml(data.contract_no || '-')}}</td>
              </tr>
              <tr>
                <td style="width:34%; border:1px solid #000; padding:6px 10px;">Reference Number</td>
                <td id="mgs-val-ref-num" class="mgs-editable" contenteditable="true" spellcheck="false" title="Click to edit" style="border:1px solid #000; padding:6px 10px;">${{escapeHtml(data.ref_num || '-')}}</td>
              </tr>
              <tr>
                <td style="border:1px solid #000; padding:6px 10px;">Service Period</td>
                <td id="mgs-val-service-period" class="mgs-editable" contenteditable="true" spellcheck="false" title="Click to edit" style="border:1px solid #000; padding:6px 10px;">${{escapeHtml(data.service_period || '-')}}</td>
              </tr>
              <tr>
                <td style="border:1px solid #000; padding:6px 10px;">Content of Work</td>
                <td id="mgs-val-content-of-work" class="mgs-editable" contenteditable="true" spellcheck="false" title="Click to edit" style="border:1px solid #000; padding:6px 10px;">${{escapeHtml(data.content_of_work || '-')}}</td>
              </tr>
              <tr>
                <td style="border:1px solid #000; padding:6px 10px;">Payment Currency</td>
                <td id="mgs-val-currency" class="mgs-editable" contenteditable="true" spellcheck="false" title="Click to edit" style="border:1px solid #000; padding:6px 10px;">${{escapeHtml(data.currency || '-')}}</td>
              </tr>
              <tr>
                <td style="border:1px solid #000; padding:6px 10px;">Invoice Number</td>
                <td id="mgs-val-invoice-no" class="mgs-editable" contenteditable="true" spellcheck="false" title="Click to edit" style="border:1px solid #000; padding:6px 10px; text-align:right; font-family:monospace; font-size:13px;">${{escapeHtml(data.invoice_no || '-')}}</td>
              </tr>
              <tr>
                <td style="border:1px solid #000; padding:6px 10px;">Invoice Date</td>
                <td id="mgs-val-invoice-date" class="mgs-editable" contenteditable="true" spellcheck="false" title="Click to edit" style="border:1px solid #000; padding:6px 10px; text-align:right;">${{escapeHtml(data.invoice_date || '-')}}</td>
              </tr>
              <tr>
                <td style="border:1px solid #000; padding:6px 10px;">Invoice Amount</td>
                <td id="mgs-val-invoice-amount" class="mgs-editable" contenteditable="true" spellcheck="false" title="Click to edit" style="border:1px solid #000; padding:6px 10px; text-align:right; font-family:monospace; font-size:13px;">${{escapeHtml(data.invoice_amount || '-')}}</td>
              </tr>
              <tr>
                <td style="border:1px solid #000; padding:6px 10px;">Invoice VAT</td>
                <td id="mgs-val-invoice-vat-rate" class="mgs-editable" contenteditable="true" spellcheck="false" title="Click to edit" style="border:1px solid #000; padding:6px 10px; text-align:right;">${{escapeHtml(data.invoice_vat_rate || '-')}}</td>
              </tr>
              <tr>
                <td style="border:1px solid #000; padding:6px 10px;">Invoice VAT Amount</td>
                <td id="mgs-val-invoice-vat-amount" class="mgs-editable" contenteditable="true" spellcheck="false" title="Click to edit" style="border:1px solid #000; padding:6px 10px; text-align:right; font-family:monospace; font-size:13px;">${{escapeHtml(data.invoice_vat_amount || '-')}}</td>
              </tr>
              <tr style="background:#f8fafc;">
                <td style="border:1px solid #000; padding:7px 10px; font-weight:bold;">Total Invoice Amount</td>
                <td id="mgs-val-total-amount" class="mgs-editable" contenteditable="true" spellcheck="false" title="Click to edit" style="border:1px solid #000; padding:7px 10px; text-align:right; font-weight:bold; font-family:monospace; font-size:13.5px;">${{escapeHtml(data.total_amount || '-')}}</td>
              </tr>
              <tr>
                <td style="border:1px solid #000; padding:8px 10px; vertical-align:top;">Remittance Detail</td>
                <td style="border:1px solid #000; padding:8px 10px; line-height:1.6;">
                  <div style="font-weight:600; margin-bottom:3px;">Transfer to:</div>
                  <div>Bank Name: <b id="mgs-val-bank-name" class="mgs-editable" contenteditable="true" spellcheck="false" title="Click to edit">${{escapeHtml(v.bank_name || '-')}}</b></div>
                  <div>Bank Address: <span id="mgs-val-bank-address" class="mgs-editable" contenteditable="true" spellcheck="false" title="Click to edit">${{escapeHtml(v.bank_address || '-')}}</span></div>
                  <div>Vendor Remit Address: <span id="mgs-val-remit-address" class="mgs-editable" contenteditable="true" spellcheck="false" title="Click to edit">${{escapeHtml(v.address || '-')}}</span></div>
                  <div>Account Name: <b id="mgs-val-account-name" class="mgs-editable" contenteditable="true" spellcheck="false" title="Click to edit">${{escapeHtml(v.account_name || '-')}}</b></div>
                  <div>Account number: <b id="mgs-val-account-number" class="mgs-editable" contenteditable="true" spellcheck="false" title="Click to edit">${{escapeHtml(v.account_number || '-')}}</b></div>
                  <div>Account Currency: <span id="mgs-val-account-currency" class="mgs-editable" contenteditable="true" spellcheck="false" title="Click to edit">${{escapeHtml(v.account_currency || data.currency || '-')}}</span></div>
                </td>
              </tr>
            </tbody>
          </table>
          <!-- Double border line under table -->
          <div style="border-top:1px solid #000; border-bottom:1px solid #000; height:2px; margin-top:3px;"></div>
        </div>
      `;
    }}

    function printMgsPreview() {{
      const previewEl = document.getElementById('mgs-pdf-preview');
      if (!previewEl) return;
      const printWindow = window.open('', '_blank', 'width=850,height=1000');
      if (!printWindow) {{
        alert('Please allow popups to print the preview document.');
        return;
      }}
      printWindow.document.write(`<!doctype html>
<html>
<head>
  <title>MGS Payment Request Preview</title>
  <style>
    body {{ font-family: 'Times New Roman', Times, Georgia, serif; padding: 40px; color: #000; font-size: 13px; line-height: 1.45; }}
    table {{ border-collapse: collapse; width: 100%; }}
    .mgs-editable {{ outline: none !important; background: transparent !important; }}
    @media print {{
      body {{ padding: 0; }}
      .mgs-editable {{ outline: none !important; background: transparent !important; }}
    }}
  </style>
</head>
<body>
  ${{previewEl.innerHTML}}
</body>
</html>`);
      printWindow.document.close();
      printWindow.focus();
      setTimeout(function() {{
        printWindow.print();
      }}, 300);
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
      renderMgsPdfPreview(data);
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
          window.location.reload();
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


def to_float_or_none(s: str | None):
    if s is None:
        return None
    s = str(s).strip()
    if s == "":
        return None
    s = s.replace(",", "")
    try:
        return float(s)
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
