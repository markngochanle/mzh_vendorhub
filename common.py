# common.py
# Shared helpers for server (no extra libraries)

import sys
import os
import sqlite3
import configparser
import urllib.parse
from html import escape
from datetime import datetime
from pathlib import Path

# Support PyInstaller frozen bundle vs local development
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
else:
    APP_DIR = Path(__file__).resolve().parent
    BUNDLE_DIR = APP_DIR

CONFIG_FILE = APP_DIR / "config.ini"


def load_config():
    """
    Load host, port, db_path with priority:
    1. Environment variables (HOST, PORT, DB_PATH)
    2. config.ini ([server] host, port; [database] path or [server] db_path)
    3. Defaults (127.0.0.1, 8800, db.sqlite3)
    """
    config = configparser.ConfigParser()
    default_host = "127.0.0.1"
    default_port = 8800
    default_db = str(APP_DIR / "db.sqlite3")

    if CONFIG_FILE.exists():
        try:
            config.read(str(CONFIG_FILE), encoding="utf-8")
        except Exception:
            pass

    cfg_host = None
    cfg_port = None
    cfg_db = None

    if config.has_section("server"):
        cfg_host = config.get("server", "host", fallback=None)
        cfg_port = config.get("server", "port", fallback=None)
        cfg_db = config.get("server", "db_path", fallback=None)

    if config.has_section("database"):
        if not cfg_db:
            cfg_db = config.get("database", "path", fallback=None) or config.get("database", "db_path", fallback=None)

    if cfg_db:
        p = Path(cfg_db)
        if not p.is_absolute():
            cfg_db = str((APP_DIR / p).resolve())

    env_host = os.environ.get("HOST")
    env_port = os.environ.get("PORT")
    env_db = os.environ.get("DB_PATH")

    host = env_host or cfg_host or default_host
    try:
        port = int(env_port or cfg_port or default_port)
    except (ValueError, TypeError):
        port = default_port

    db_path = env_db or cfg_db or default_db

    return host, port, db_path


HOST, PORT, DB_PATH = load_config()
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

        # -------- Fixed Price & Contract Classification Migrations --------
        ensure_column(conn, "contracts", "contract_type", "TEXT NOT NULL DEFAULT 'FRAMEWORK'")
        ensure_column(conn, "contracts", "billing_type", "TEXT NOT NULL DEFAULT 'TM'")
        ensure_column(conn, "contracts", "recurring_fee", "REAL NULL")
        ensure_column(conn, "contracts", "recurring_period", "TEXT NOT NULL DEFAULT 'MONTHLY'")
        ensure_column(conn, "contracts", "renewal_type", "TEXT NOT NULL DEFAULT 'MANUAL'")
        ensure_column(conn, "contracts", "renewal_notice_days", "INTEGER NOT NULL DEFAULT 60")
        ensure_column(conn, "contracts", "renewal_period_months", "INTEGER NULL")
        ensure_column(conn, "contracts", "renewal_note", "TEXT NULL")
        ensure_column(conn, "contracts", "last_renewed_at", "TEXT NULL")
        ensure_column(conn, "contracts", "contract_summary", "TEXT NULL")
        ensure_column(conn, "contract_annexes", "billing_type", "TEXT NOT NULL DEFAULT 'TM'")
        ensure_column(conn, "contract_annexes", "recurring_fee", "REAL NULL")
        ensure_column(conn, "contract_annexes", "recurring_period", "TEXT NOT NULL DEFAULT 'MONTHLY'")

        # -------- contract_milestones --------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS contract_milestones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contract_id INTEGER NOT NULL,
                annex_id INTEGER NULL,
                milestone_name TEXT NOT NULL,
                milestone_type TEXT NOT NULL DEFAULT 'DELIVERY',
                percentage REAL NULL,
                amount REAL NOT NULL DEFAULT 0.0,
                planned_date TEXT NULL,
                actual_date TEXT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                acceptance_doc_no TEXT NULL,
                invoice_id INTEGER NULL,
                cashout_date TEXT NULL,
                note TEXT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(contract_id) REFERENCES contracts(id),
                FOREIGN KEY(annex_id) REFERENCES contract_annexes(id),
                FOREIGN KEY(invoice_id) REFERENCES invoices(id)
            )
        """)
        conn.commit()

        # -------- recurring_payouts --------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS recurring_payouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contract_id INTEGER NOT NULL,
                annex_id INTEGER NULL,
                service_month TEXT NOT NULL,
                amount REAL NOT NULL DEFAULT 0.0,
                status TEXT NOT NULL DEFAULT 'PENDING',
                invoice_id INTEGER NULL,
                cashout_date TEXT NULL,
                note TEXT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(contract_id) REFERENCES contracts(id),
                FOREIGN KEY(annex_id) REFERENCES contract_annexes(id),
                FOREIGN KEY(invoice_id) REFERENCES invoices(id),
                UNIQUE(contract_id, annex_id, service_month)
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

        ensure_column(conn, "invoices", "milestone_id", "INTEGER NULL")

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
                paid_leave_total_hours REAL NULL DEFAULT 0.0,
                carried_over_leave_hours REAL NULL DEFAULT 0.0,
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
        ensure_column(conn, "contract_staff_links", "carried_over_leave_hours", "REAL NULL DEFAULT 0.0")

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

      <div class="nav-dropdown">
        <a href="/contracts" class="nav-link nav-dropdown-toggle">Contracts & Vendors <span style="font-size: 10px; margin-left: 2px;">▾</span></a>
        <div class="nav-dropdown-menu">
          <a href="/vendors" class="nav-dropdown-item">🏢 Vendors</a>
          <a href="/contracts" class="nav-dropdown-item">📄 Contracts & Annexes</a>
          <a href="/contracts/references" class="nav-dropdown-item">🏷️ Reference Numbers</a>
        </div>
      </div>

      <div class="nav-dropdown">
        <a href="/projects" class="nav-link nav-dropdown-toggle">Projects & Resources <span style="font-size: 10px; margin-left: 2px;">▾</span></a>
        <div class="nav-dropdown-menu">
          <a href="/projects" class="nav-dropdown-item">📁 Projects</a>
          <a href="/projects/assign#add-staff-section" class="nav-dropdown-item">👤 Assign Staff to Project</a>
          <a href="/staff" class="nav-dropdown-item">👥 Staff List</a>
          <div style="border-top: 1px solid #f1f5f9; margin: 4px 0;"></div>
          <a href="/attendance" class="nav-dropdown-item">📅 Monthly Timesheet</a>
          <a href="/attendance/monthly" class="nav-dropdown-item">🔒 Monthly Payroll Lock</a>
          <a href="/attendance/acceptance" class="nav-dropdown-item">📝 T&M Acceptance</a>
          <div style="border-top: 1px solid #f1f5f9; margin: 4px 0;"></div>
          <a href="/staff/shifts" class="nav-dropdown-item">⏰ Work Shifts Settings</a>
        </div>
      </div>

      <div class="nav-dropdown">
        <a href="/payments" class="nav-link nav-dropdown-toggle">Payments & Invoices <span style="font-size: 10px; margin-left: 2px;">▾</span></a>
        <div class="nav-dropdown-menu">
          <a href="/payments" class="nav-dropdown-item">📊 Cash-out Dashboard</a>
          <a href="/" class="nav-dropdown-item">🧾 Invoices & Reconciliation</a>
          <div style="border-top: 1px solid #f1f5f9; margin: 4px 0;"></div>
          <a href="/payments?type=tm" class="nav-dropdown-item">💵 Timesheet & Payroll (T&M)</a>
          <a href="/payments/fixed-price" class="nav-dropdown-item">🎯 Fixed Price (Milestones)</a>
          <a href="/payments/recurring" class="nav-dropdown-item">🌐 Recurring Services (Internet/SaaS)</a>
          <div style="border-top: 1px solid #f1f5f9; margin: 4px 0;"></div>
          <a href="/invoice/new" class="nav-dropdown-item">📥 Import Invoice</a>
        </div>
      </div>

      <div class="nav-dropdown">
        <a href="/audit-logs" class="nav-link nav-dropdown-toggle">System & Tools <span style="font-size: 10px; margin-left: 2px;">▾</span></a>
        <div class="nav-dropdown-menu">
          <a href="/audit-logs" class="nav-dropdown-item">📋 Audit Logs</a>
          <a href="/unit-tests" class="nav-dropdown-item">🧪 Unit Test Runner</a>
          <a href="/playwright" class="nav-dropdown-item">🎭 UAT Playwright Runner</a>
        </div>
      </div>
    </div>
    """
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} - Mizuho IT Outsourcing Vendor Hub</title>
  <link rel="icon" type="image/png" href="/logo.png">
  <link rel="shortcut icon" type="image/png" href="/logo.png">
  <link rel="apple-touch-icon" href="/logo.png">
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
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
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
      padding: 12px 24px;
      box-shadow: var(--shadow-sm);
    }}
    .logo-area {{
      display: flex;
      align-items: center;
      gap: 14px;
    }}
    .logo-icon {{
      font-size: 24px;
    }}
    .logo-title {{
      font-size: 20px;
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
    .tag-active {{
      border-color: #a7f3d0;
      background: #ecfdf5;
      color: #047857;
    }}
    .tag-info {{
      border-color: #bae6fd;
      background: #e0f2fe;
      color: #0369a1;
    }}
    .tag-warning {{
      border-color: #fde68a;
      background: #fef3c7;
      color: #b45309;
    }}
    .tag-purple {{
      border-color: #ddd6fe;
      background: #f5f3ff;
      color: #6d28d9;
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
      <a href="/" style="display:flex; align-items:center; gap:14px; text-decoration:none;">
        <img src="/logo.png" alt="Mizuho Logo" style="height:64px; width:auto; max-width:96px; object-fit:contain; border-radius:6px; display:inline-block; vertical-align:middle;">
        <h1 class="logo-title">Mizuho IT Outsourcing Vendor Hub</h1>
      </a>
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
      const path = window.location.pathname;
      document.querySelectorAll('.nav-dropdown').forEach(dd => {{
        const toggle = dd.querySelector('.nav-dropdown-toggle');
        const items = Array.from(dd.querySelectorAll('.nav-dropdown-item')).map(a => a.getAttribute('href').split('#')[0].split('?')[0]);
        const toggleHref = toggle ? toggle.getAttribute('href').split('?')[0] : '';
        const isMatch = items.some(h => (h === '/' ? path === '/' : (path === h || (h !== '/' && path.startsWith(h))))) ||
                        (toggleHref && (toggleHref === '/' ? path === '/' : (path === toggleHref || (toggleHref !== '/' && path.startsWith(toggleHref)))));
        if (isMatch && toggle) {{
          toggle.classList.add('active');
        }}
      }});
      document.querySelectorAll('.nav-container > .nav-link').forEach(link => {{
        const href = link.getAttribute('href').split('?')[0];
        if (href === path || (href !== '/' && path.startsWith(href))) {{
          link.classList.add('active');
        }}
      }});
      document.querySelectorAll('.nav-dropdown-item').forEach(item => {{
        const href = item.getAttribute('href').split('#')[0].split('?')[0];
        if (href === path || (href === '/' && path === '/') || (href !== '/' && path.startsWith(href))) {{
          item.style.fontWeight = '700';
          item.style.color = 'var(--primary)';
          item.style.backgroundColor = '#f1f5f9';
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

  <!-- jsPDF Local Library (Offline Closed Environment) -->
  <script src="/static/js/jspdf.umd.min.js"></script>

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


def send_bytes(handler, data: bytes, content_type: str = "image/png", status=200):
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "public, max-age=86400")
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


def get_milestones_for_contract(conn: sqlite3.Connection, contract_id: int, annex_id: int | None = None) -> list:
    if annex_id is not None:
        return conn.execute("""
            SELECT m.*, i.shdon, i.khhdon, i.tg_tttbso
            FROM contract_milestones m
            LEFT JOIN invoices i ON i.id = m.invoice_id
            WHERE m.contract_id = ? AND m.annex_id = ?
            ORDER BY m.planned_date ASC, m.id ASC
        """, (contract_id, annex_id)).fetchall()
    else:
        return conn.execute("""
            SELECT m.*, i.shdon, i.khhdon, i.tg_tttbso
            FROM contract_milestones m
            LEFT JOIN invoices i ON i.id = m.invoice_id
            WHERE m.contract_id = ? AND m.annex_id IS NULL
            ORDER BY m.planned_date ASC, m.id ASC
        """, (contract_id,)).fetchall()


def get_staff_previous_unused_leave(conn: sqlite3.Connection, staff_id: int, joining_date: str | None = None, exclude_link_id: int | None = None):
    """
    Finds the most recent link of staff_id prior to `joining_date`
    and computes the unused leave from that link.
    Returns: (unused_hours: float, prev_link: sqlite3.Row or None)
    """
    if not joining_date:
        joining_date = datetime.now().strftime("%Y-%m-%d")

    query = """
        SELECT l.*, a.annex_name
        FROM contract_staff_links l
        LEFT JOIN contract_annexes a ON a.id = l.annex_id
        WHERE l.staff_id = ?
    """
    params = [staff_id]
    if exclude_link_id:
        query += " AND l.id <> ?"
        params.append(exclude_link_id)
    if joining_date:
        query += " AND (l.tentative_leaving_date <= ? OR (l.joining_date < ? AND (l.tentative_leaving_date IS NULL OR l.tentative_leaving_date = '')))"
        params.extend([joining_date, joining_date])
    query += " ORDER BY COALESCE(l.joining_date, '') DESC, l.id DESC LIMIT 1"

    prev_link = conn.execute(query, params).fetchone()
    if not prev_link:
        return 0.0, None

    carried = 0.0
    if "carried_over_leave_hours" in prev_link.keys():
        carried = prev_link["carried_over_leave_hours"] or 0.0
    budget = (prev_link["paid_leave_total_hours"] or 0.0) + carried

    link_start_m = (prev_link["joining_date"] or "1970-01-01")[:7]
    link_end_m = (prev_link["tentative_leaving_date"] or "9999-12")[:7]
    used_row = conn.execute("""
        SELECT SUM(paid_leave_days) * 8.0 AS used_hours
        FROM monthly_attendance_summary
        WHERE staff_id = ? AND month >= ? AND month <= ?
    """, (staff_id, link_start_m, link_end_m)).fetchone()
    used = (used_row["used_hours"] or 0.0) if used_row else 0.0
    unused = max(0.0, budget - used)
    return unused, prev_link


def get_staff_leave_status(conn: sqlite3.Connection, staff_id: int, as_of_month: str | None = None) -> dict:
    """
    Calculates leave status for a staff member as of a given month (YYYY-MM).
    Distinguishes between total contract leave and active available leave.
    """
    if not as_of_month:
        as_of_month = datetime.now().strftime("%Y-%m")
    m_start = f"{as_of_month}-01"
    m_end = f"{as_of_month}-31"

    s = conn.execute("SELECT * FROM contract_staff WHERE id = ?", (staff_id,)).fetchone()
    if not s:
        return {
            "staff_id": staff_id,
            "as_of_month": as_of_month,
            "contract_total_hours": 0.0,
            "active_budget_hours": 0.0,
            "active_used_hours": 0.0,
            "active_used_other_hours": 0.0,
            "active_remaining_hours": 0.0,
            "total_used_hours": 0.0,
            "current_link_id": None
        }

    links = conn.execute("""
        SELECT * FROM contract_staff_links 
        WHERE staff_id = ? 
        ORDER BY COALESCE(joining_date, '') ASC, id ASC
    """, (staff_id,)).fetchall()

    # Total contract leave across all links
    total_contract_hours = sum((l["paid_leave_total_hours"] or 0.0) for l in links)
    if not links or total_contract_hours == 0.0:
        total_contract_hours = s["paid_leave_total_hours"] or 0.0

    # Total used across all history
    tot_used_row = conn.execute("""
        SELECT SUM(paid_leave_days) * 8.0 AS used_hours
        FROM monthly_attendance_summary
        WHERE staff_id = ?
    """, (staff_id,)).fetchone()
    total_used_hours = tot_used_row["used_hours"] if (tot_used_row and tot_used_row["used_hours"] is not None) else (s["paid_leave_used_hours"] or 0.0)

    # Active link in as_of_month
    active_links = [
        l for l in links
        if (l["joining_date"] or "") <= m_end and (not l["tentative_leaving_date"] or l["tentative_leaving_date"] >= m_start)
    ]

    current_link = active_links[-1] if active_links else None
    if not current_link:
        # Fallback to the most recent link that started on or before m_end
        past_links = [l for l in links if (l["joining_date"] or "") <= m_end]
        if past_links:
            current_link = past_links[-1]

    if current_link:
        carried = 0.0
        if "carried_over_leave_hours" in current_link.keys():
            carried = current_link["carried_over_leave_hours"] or 0.0
        active_budget = (current_link["paid_leave_total_hours"] or 0.0) + carried

        # If link has 0.0 budget and only 1 link exists, fallback to staff.paid_leave_total_hours if available
        if active_budget == 0.0 and len(links) == 1 and (s["paid_leave_total_hours"] or 0.0) > 0:
            active_budget = s["paid_leave_total_hours"] or 0.0

        link_start_m = (current_link["joining_date"] or "1970-01-01")[:7]
        link_end_m = (current_link["tentative_leaving_date"] or "9999-12")[:7]

        # Leave used in this link period up to as_of_month
        row = conn.execute("""
            SELECT SUM(paid_leave_days) * 8.0 AS used_hours
            FROM monthly_attendance_summary
            WHERE staff_id = ? AND month >= ? AND month <= ?
        """, (staff_id, link_start_m, min(link_end_m, as_of_month))).fetchone()
        active_used = (row["used_hours"] or 0.0) if row else 0.0

        # Leave used in other months of this link (excluding as_of_month)
        row_other = conn.execute("""
            SELECT SUM(paid_leave_days) * 8.0 AS used_hours
            FROM monthly_attendance_summary
            WHERE staff_id = ? AND month >= ? AND month <= ? AND month <> ?
        """, (staff_id, link_start_m, min(link_end_m, as_of_month), as_of_month)).fetchone()
        active_used_other = (row_other["used_hours"] or 0.0) if row_other else 0.0

        active_rem = max(0.0, active_budget - active_used)
    else:
        # If no link at all or legacy test data
        active_budget = s["paid_leave_total_hours"] or 0.0
        active_used = total_used_hours
        active_rem = max(0.0, active_budget - active_used)
        active_used_other = total_used_hours

    return {
        "staff_id": staff_id,
        "as_of_month": as_of_month,
        "contract_total_hours": total_contract_hours,
        "active_budget_hours": active_budget,
        "active_used_hours": active_used,
        "active_used_other_hours": active_used_other if current_link else total_used_hours,
        "active_remaining_hours": active_rem,
        "total_used_hours": total_used_hours,
        "current_link_id": current_link["id"] if current_link else None
    }


