# dump_data.py
import os
import sqlite3
from pathlib import Path

DB_PATH = str(Path(__file__).resolve().with_name("db.sqlite3"))
XML_DIR = Path(__file__).resolve().with_name("sample_xmls")

# ----------------- XML templates -----------------
FPT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<HDon>
  <DLHDon>
    <TTChung>
      <KHHDon>1C26TUU</KHHDon>
      <SHDon>0001234</SHDon>
      <NLap>2026-05-31</NLap>
      <DVTTe>VND</DVTTe>
    </TTChung>
    <NDHDon>
      <NBan>
        <Ten>CÔNG TY TNHH PHẦN MỀM FPT</Ten>
        <MST>0102135934</MST>
        <DChi>Tòa nhà FPT, Phố Duy Tân, Phường Dịch Vọng Hậu, Quận Cầu Giấy, Hà Nội, Việt Nam</DChi>
      </NBan>
      <NMua>
        <Ten>CÔNG TY TNHH NGÂN HÀNG MIZUHO - CHI NHÁNH HÀ NỘI</Ten>
        <MST>0100234567</MST>
        <DChi>Tầng 4, Tòa nhà CornerStone, 16 Phan Chu Trinh, Quận Hoàn Kiếm, Hà Nội, Việt Nam</DChi>
        <HVTNMHang>Ngân hàng Mizuho</HVTNMHang>
      </NMua>
      <TToan>
        <TgTCThue>45000000</TgTCThue>
        <TgTThue>3600000</TgTThue>
        <TTCKTMai>0</TTCKTMai>
        <TgTTTBSo>48600000</TgTTTBSo>
        <THTTLTSuat>
          <LTSuat>
            <TSuat>8%</TSuat>
            <ThTien>45000000</ThTien>
            <TThue>3600000</TThue>
          </LTSuat>
        </THTTLTSuat>
      </TToan>
    </NDHDon>
  </DLHDon>
</HDon>
"""

CMC_XML = """<?xml version="1.0" encoding="UTF-8"?>
<HDon>
  <DLHDon>
    <TTChung>
      <KHHDon>1C26TVY</KHHDon>
      <SHDon>0000567</SHDon>
      <NLap>2026-06-15</NLap>
      <DVTTe>VND</DVTTe>
    </TTChung>
    <NDHDon>
      <NBan>
        <Ten>TỔNG CÔNG TY CÔNG NGHỆ VÀ GIẢI PHÁP CMC - CÔNG TY CỔ PHẦN</Ten>
        <MST>0102715694</MST>
        <DChi>Tầng 11, Tòa nhà CMC, Phố Duy Tân, Phường Dịch Vọng Hậu, Quận Cầu Giấy, Hà Nội, Việt Nam</DChi>
      </NBan>
      <NMua>
        <Ten>CÔNG TY TNHH NGÂN HÀNG MIZUHO - CHI NHÁNH HÀ NỘI</Ten>
        <MST>0100234567</MST>
        <DChi>Tầng 4, Tòa nhà CornerStone, 16 Phan Chu Trinh, Quận Hoàn Kiếm, Hà Nội, Việt Nam</DChi>
        <HVTNMHang>Ngân hàng Mizuho</HVTNMHang>
      </NMua>
      <TToan>
        <TgTCThue>70000000</TgTCThue>
        <TgTThue>7000000</TgTThue>
        <TTCKTMai>0</TTCKTMai>
        <TgTTTBSo>77000000</TgTTTBSo>
        <THTTLTSuat>
          <LTSuat>
            <TSuat>10%</TSuat>
            <ThTien>70000000</ThTien>
            <TThue>7000000</TThue>
          </LTSuat>
        </THTTLTSuat>
      </TToan>
    </NDHDon>
  </DLHDon>
</HDon>
"""

RIKKEI_MISMATCH_XML = """<?xml version="1.0" encoding="UTF-8"?>
<HDon>
  <DLHDon>
    <TTChung>
      <KHHDon>1C26TRK</KHHDon>
      <SHDon>0008899</SHDon>
      <NLap>2026-06-30</NLap>
      <DVTTe>VND</DVTTe>
    </TTChung>
    <NDHDon>
      <NBan>
        <Ten>CÔNG TY CP RIKKEISOFT</Ten>
        <MST>0105847055</MST>
        <DChi>Toà nhà Handico, Mễ Trì, Quận Nam Từ Liêm, Hà Nội, Việt Nam</DChi>
      </NBan>
      <NMua>
        <Ten>NGÂN HÀNG MIZUHO - HANOI BRANCH</Ten>
        <MST>0100234567</MST>
        <DChi>16 Phan Chu Trinh, Hoàn Kiếm, Hà Nội</DChi>
        <HVTNMHang>Ngân hàng Mizuho</HVTNMHang>
      </NMua>
      <TToan>
        <TgTCThue>120000000</TgTCThue>
        <TgTThue>12000000</TgTThue>
        <TTCKTMai>0</TTCKTMai>
        <TgTTTBSo>132000000</TgTTTBSo>
        <THTTLTSuat>
          <LTSuat>
            <TSuat>10%</TSuat>
            <ThTien>120000000</ThTien>
            <TThue>12000000</TThue>
          </LTSuat>
        </THTTLTSuat>
      </TToan>
    </NDHDon>
  </DLHDon>
</HDon>
"""


def ensure_column(conn, table: str, column: str, col_def: str):
    cur = conn.cursor()
    try:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
        conn.commit()
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            return
        raise


def init_db(conn):
    cur = conn.cursor()
    
    # 1. Vendors
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
    ensure_column(conn, "vendors", "account_currency", "TEXT")
    ensure_column(conn, "vendors", "purchasing", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "vendors", "company_name_vi", "TEXT")
    ensure_column(conn, "vendors", "address_vi", "TEXT")
    ensure_column(conn, "vendors", "short_name", "TEXT")

    # 2. Contracts (framework)
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

    # 3. Contract Annexes
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

    # 4. Contract Staff (HR)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS contract_staff (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name_vi TEXT NOT NULL,
            vendor_id INTEGER NOT NULL,        -- vendor (purchasing=0)
            project_name TEXT NULL,            -- free text (Project)
            position TEXT NULL,
            contract_id INTEGER NOT NULL,      -- framework contract
            annex_id INTEGER NULL,             -- optional; must belong to contract_id if set
            joining_date TEXT NULL,            -- YYYY-MM-DD
            tentative_leaving_date TEXT NULL,  -- YYYY-MM-DD
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
    ensure_column(conn, "contract_staff", "project_name", "TEXT")
    ensure_column(conn, "contract_staff", "work_shift", "TEXT")

    # 5. Attendance
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

    # 6. Attendance Locks
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

    # 7. Monthly Attendance Summary
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

    # 8. Invoices
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
    ensure_column(conn, "invoices", "khhdon", "TEXT")
    ensure_column(conn, "invoices", "service_year", "INTEGER NULL")
    ensure_column(conn, "invoices", "service_month", "INTEGER NULL")
    ensure_column(conn, "invoices", "service_day", "INTEGER NULL")
    ensure_column(conn, "invoices", "contract_no", "TEXT NULL")
    ensure_column(conn, "invoices", "sent_to_mgs", "INTEGER NOT NULL DEFAULT 0")
    try:
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_invoices_khhdon_shdon ON invoices(khhdon, shdon)")
    except sqlite3.IntegrityError:
        pass

    # 9. Invoice Tax Lines
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
    conn.commit()

    # 10. Contract References
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
    ensure_column(conn, "contract_references", "locked", "INTEGER NOT NULL DEFAULT 0")

    conn.commit()


def main():
    print(f"Connecting to database at: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    cur = conn.cursor()

    # Clear existing data to make it clean and deterministic
    print("Clearing existing records...")
    tables_to_clear = [
        "invoice_tax_lines",
        "invoices",
        "contract_references",
        "monthly_attendance_summary",
        "attendance_locks",
        "attendance",
        "contract_staff",
        "contract_annexes",
        "contracts",
        "vendors"
    ]
    for table in tables_to_clear:
        cur.execute(f"DELETE FROM {table}")
    
    # Reset AUTOINCREMENT keys
    try:
        cur.execute("DELETE FROM sqlite_sequence WHERE name IN (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", tuple(tables_to_clear))
    except sqlite3.OperationalError:
        pass
    
    conn.commit()

    # ----------------- 1. Insert Vendors -----------------
    print("Inserting mock Vendors...")
    
    # Mizuho (Buyer: purchasing=1)
    cur.execute("""
        INSERT INTO vendors (
            company_name_vi, address_vi, short_name, company_name, address,
            tax_id, tel, bank_name, bank_address, account_name, account_number, account_currency,
            purchasing, is_active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1)
    """, (
        "CÔNG TY TNHH NGÂN HÀNG MIZUHO - CHI NHÁNH HÀ NỘI",
        "Tầng 4, Tòa nhà CornerStone, 16 Phan Chu Trinh, Quận Hoàn Kiếm, Hà Nội, Việt Nam",
        "MIZUHO",
        "Mizuho Bank, Ltd. - Hanoi Branch",
        "4th Floor, CornerStone Building, 16 Phan Chu Trinh, Hoan Kiem District, Hanoi, Vietnam",
        "0100234567",
        "02439368888",
        "Mizuho Bank, Ltd. - Hanoi Branch",
        "16 Phan Chu Trinh, Hoan Kiem, Hanoi",
        "MIZUHO BANK HANOI",
        "1000000123",
        "VND"
    ))
    buyer_id = cur.lastrowid

    # FPT Software (Seller: purchasing=0)
    cur.execute("""
        INSERT INTO vendors (
            company_name_vi, address_vi, short_name, company_name, address,
            tax_id, tel, bank_name, bank_address, account_name, account_number, account_currency,
            purchasing, is_active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1)
    """, (
        "CÔNG TY TNHH PHẦN MỀM FPT",
        "Tòa nhà FPT, Phố Duy Tân, Phường Dịch Vọng Hậu, Quận Cầu Giấy, Hà Nội, Việt Nam",
        "FPT",
        "FPT Software Company Limited",
        "FPT Building, Duy Tan Street, Dich Vong Hau Ward, Cau Giay District, Hanoi, Vietnam",
        "0102135934",
        "02437689048",
        "Ngân hàng TMCP Ngoại thương Việt Nam - Chi nhánh Hà Nội (Vietcombank)",
        "31-33 Ngô Quyền, Hoàn Kiếm, Hà Nội",
        "CONG TY TNHH PHAN MEM FPT",
        "0011001234567",
        "VND"
    ))
    fpt_id = cur.lastrowid

    # CMC TS (Seller: purchasing=0)
    cur.execute("""
        INSERT INTO vendors (
            company_name_vi, address_vi, short_name, company_name, address,
            tax_id, tel, bank_name, bank_address, account_name, account_number, account_currency,
            purchasing, is_active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1)
    """, (
        "TỔNG CÔNG TY CÔNG NGHỆ VÀ GIẢI PHÁP CMC - CÔNG TY CỔ PHẦN",
        "Tầng 11, Tòa nhà CMC, Phố Duy Tân, Phường Dịch Vọng Hậu, Quận Cầu Giấy, Hà Nội, Việt Nam",
        "CMC",
        "CMC Technology and Solution Joint Stock Company",
        "11th Floor, CMC Tower, Duy Tan Street, Dich Vong Hau Ward, Cau Giay District, Hanoi, Vietnam",
        "0102715694",
        "02437958686",
        "Ngân hàng TMCP Đầu tư và Phát triển Việt Nam - Chi nhánh Hà Thành (BIDV)",
        "74 Thợ Nhuộm, Hoàn Kiếm, Hà Nội",
        "TONG CONG TY CONG NGHE VA GIAI PHAP CMC",
        "12310000987654",
        "VND"
    ))
    cmc_id = cur.lastrowid

    # Rikkeisoft (Seller: purchasing=0)
    cur.execute("""
        INSERT INTO vendors (
            company_name_vi, address_vi, short_name, company_name, address,
            tax_id, tel, bank_name, bank_address, account_name, account_number, account_currency,
            purchasing, is_active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1)
    """, (
        "CÔNG TY CỔ PHẦN RIKKEISOFT",
        "Tầng 21, Tòa nhà Handico, Khu đô thị mới Mễ Trì, Phường Mễ Trì, Quận Nam Từ Liêm, Hà Nội, Việt Nam",
        "RIKKEI",
        "Rikkeisoft Joint Stock Company",
        "21st Floor, Handico Tower, Me Tri New Urban Area, Nam Tu Liem District, Hanoi, Vietnam",
        "0105847055",
        "02462754488",
        "Ngân hàng TMCP Kỹ thương Việt Nam (Techcombank)",
        "191 Bà Triệu, Hai Bà Trưng, Hà Nội",
        "CONG TY CO PHAN RIKKEISOFT",
        "19028888999999",
        "VND"
    ))
    rikkei_id = cur.lastrowid

    # ----------------- 2. Insert Contracts -----------------
    print("Inserting mock Contracts...")
    
    # Contract 1: Mizuho & FPT
    cur.execute("""
        INSERT INTO contracts (
            buyer_vendor_id, seller_vendor_id, framework_no, framework_name, start_date, end_date, is_active
        ) VALUES (?, ?, ?, ?, ?, ?, 1)
    """, (
        buyer_id, fpt_id, "MHB/FPT/2025/001",
        "Hợp đồng khung cung cấp dịch vụ phát triển phần mềm và hỗ trợ vận hành hệ thống",
        "2025-01-01", "2026-12-31"
    ))
    contract_fpt_id = cur.lastrowid

    # Contract 2: Mizuho & CMC
    cur.execute("""
        INSERT INTO contracts (
            buyer_vendor_id, seller_vendor_id, framework_no, framework_name, start_date, end_date, is_active
        ) VALUES (?, ?, ?, ?, ?, ?, 1)
    """, (
        buyer_id, cmc_id, "MHB/CMC/2026/002",
        "Hợp đồng khung cung cấp dịch vụ hạ tầng mạng và bảo mật CNTT",
        "2026-01-01", "2027-12-31"
    ))
    contract_cmc_id = cur.lastrowid

    # ----------------- 3. Insert Contract Annexes -----------------
    print("Inserting mock Contract Annexes...")
    
    # Annex 1 for FPT
    cur.execute("""
        INSERT INTO contract_annexes (
            contract_id, annex_name, start_date, end_date, is_active
        ) VALUES (?, ?, ?, ?, 1)
    """, (
        contract_fpt_id,
        "Phụ lục số 01 - Bổ sung nhân sự giai đoạn Core Banking Upgrade",
        "2025-06-01", "2026-05-31"
    ))
    annex_fpt_1_id = cur.lastrowid

    # Annex 2 for FPT
    cur.execute("""
        INSERT INTO contract_annexes (
            contract_id, annex_name, start_date, end_date, is_active
        ) VALUES (?, ?, ?, ?, 1)
    """, (
        contract_fpt_id,
        "Phụ lục số 02 - Điều chỉnh đơn giá nhân sự năm 2026",
        "2026-01-01", "2026-12-31"
    ))
    annex_fpt_2_id = cur.lastrowid

    # Annex 1 for CMC
    cur.execute("""
        INSERT INTO contract_annexes (
            contract_id, annex_name, start_date, end_date, is_active
        ) VALUES (?, ?, ?, ?, 1)
    """, (
        contract_cmc_id,
        "Phụ lục số 01 - Triển khai nâng cấp hệ thống Firewall",
        "2026-02-15", "2026-08-15"
    ))
    annex_cmc_1_id = cur.lastrowid

    # ----------------- 4. Insert Staff -----------------
    print("Inserting mock Contract Staff...")

    # Staff 1: FPT / Annex 1 (Active/Worked in 2025-2026)
    cur.execute("""
        INSERT INTO contract_staff (
            full_name_vi, vendor_id, project_name, position, contract_id, annex_id,
            joining_date, tentative_leaving_date, monthly_rate, manday_rate,
            paid_leave_total_hours, paid_leave_used_hours, ot, status, work_shift
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
    """, (
        "Nguyễn Văn An", fpt_id, "Core Banking Migration", "Senior Developer (Python/SQL)",
        contract_fpt_id, annex_fpt_1_id, "2025-06-01", "2026-05-31",
        45000000.0, 2000000.0, 12.0, 4.0, 1, "8:00 - 17:00"
    ))

    # Staff 2: FPT / Annex 2 (Active in 2026)
    cur.execute("""
        INSERT INTO contract_staff (
            full_name_vi, vendor_id, project_name, position, contract_id, annex_id,
            joining_date, tentative_leaving_date, monthly_rate, manday_rate,
            paid_leave_total_hours, paid_leave_used_hours, ot, status, work_shift
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
    """, (
        "Trần Thị Bình", fpt_id, "Data Warehousing", "Business Analyst",
        contract_fpt_id, annex_fpt_2_id, "2026-01-01", "2026-12-31",
        38000000.0, 1700000.0, 12.0, 0.0, 0, "8:30 - 17:30"
    ))

    # Staff 3: CMC / Annex 1
    cur.execute("""
        INSERT INTO contract_staff (
            full_name_vi, vendor_id, project_name, position, contract_id, annex_id,
            joining_date, tentative_leaving_date, monthly_rate, manday_rate,
            paid_leave_total_hours, paid_leave_used_hours, ot, status, work_shift
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
    """, (
        "Lê Hoàng Long", cmc_id, "Network Security Upgrade", "Network Engineer",
        contract_cmc_id, annex_cmc_1_id, "2026-02-15", "2026-08-15",
        35000000.0, 1600000.0, 6.0, 2.0, 1, "8:30 - 17:30"
    ))

    # Staff 4: FPT (Direct framework contract, no annex)
    cur.execute("""
        INSERT INTO contract_staff (
            full_name_vi, vendor_id, project_name, position, contract_id, annex_id,
            joining_date, tentative_leaving_date, monthly_rate, manday_rate,
            paid_leave_total_hours, paid_leave_used_hours, ot, status, work_shift
        ) VALUES (?, ?, ?, ?, ?, NULL, ?, NULL, ?, ?, ?, ?, ?, NULL, ?)
    """, (
        "Phạm Minh Đức", fpt_id, "IT Helpdesk & Operations", "Support Engineer",
        contract_fpt_id, "2025-01-01", 22000000.0, 1000000.0, 24.0, 8.0, 0, "8:00 - 17:00"
    ))

    # ----------------- 5. Create Sample XML files -----------------
    print("Generating sample XML files under sample_xmls/ ...")
    XML_DIR.mkdir(exist_ok=True)
    
    (XML_DIR / "invoice_fpt.xml").write_text(FPT_XML, encoding="utf-8")
    (XML_DIR / "invoice_cmc.xml").write_text(CMC_XML, encoding="utf-8")
    (XML_DIR / "invoice_rikkei_mismatch.xml").write_text(RIKKEI_MISMATCH_XML, encoding="utf-8")

    # ----------------- 6. Insert Invoices & Tax Lines -----------------
    print("Inserting mock Invoices & Tax Lines...")

    # Invoice 1: FPT (Perfect match)
    cur.execute("""
        INSERT INTO invoices (
            service_year, service_month, service_day, contract_no,
            khhdon, shdon, nlap, dvtte,
            seller_name, seller_mst, seller_address,
            buyer_name, buyer_mst, buyer_address, buyer_bank_name,
            tg_tcthue, tg_tthue, ttcktmai, tg_tttbso,
            source_path, raw_xml
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        2026, 5, 31, "MHB/FPT/2025/001",
        "1C26TUU", "0001234", "2026-05-31", "VND",
        "CÔNG TY TNHH PHẦN MỀM FPT", "0102135934", "Tòa nhà FPT, Phố Duy Tân, Phường Dịch Vọng Hậu, Quận Cầu Giấy, Hà Nội, Việt Nam",
        "CÔNG TY TNHH NGÂN HÀNG MIZUHO - CHI NHÁNH HÀ NỘI", "0100234567", "Tầng 4, Tòa nhà CornerStone, 16 Phan Chu Trinh, Quận Hoàn Kiếm, Hà Nội, Việt Nam", "Ngân hàng Mizuho",
        45000000.0, 3600000.0, 0.0, 48600000.0,
        "sample_xmls/invoice_fpt.xml", FPT_XML
    ))
    inv_fpt_id = cur.lastrowid
    
    cur.execute("""
        INSERT INTO invoice_tax_lines (invoice_id, tsuat, thtien, tthue)
        VALUES (?, ?, ?, ?)
    """, (inv_fpt_id, "8%", 45000000.0, 3600000.0))

    # Invoice 2: CMC (Perfect match)
    cur.execute("""
        INSERT INTO invoices (
            service_year, service_month, service_day, contract_no,
            khhdon, shdon, nlap, dvtte,
            seller_name, seller_mst, seller_address,
            buyer_name, buyer_mst, buyer_address, buyer_bank_name,
            tg_tcthue, tg_tthue, ttcktmai, tg_tttbso,
            source_path, raw_xml
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        2026, 6, 15, "MHB/CMC/2026/002",
        "1C26TVY", "0000567", "2026-06-15", "VND",
        "TỔNG CÔNG TY CÔNG NGHỆ VÀ GIẢI PHÁP CMC - CÔNG TY CỔ PHẦN", "0102715694", "Tầng 11, Tòa nhà CMC, Phố Duy Tân, Phường Dịch Vọng Hậu, Quận Cầu Giấy, Hà Nội, Việt Nam",
        "CÔNG TY TNHH NGÂN HÀNG MIZUHO - CHI NHÁNH HÀ NỘI", "0100234567", "Tầng 4, Tòa nhà CornerStone, 16 Phan Chu Trinh, Quận Hoàn Kiếm, Hà Nội, Việt Nam", "Ngân hàng Mizuho",
        70000000.0, 7000000.0, 0.0, 77000000.0,
        "sample_xmls/invoice_cmc.xml", CMC_XML
    ))
    inv_cmc_id = cur.lastrowid

    cur.execute("""
        INSERT INTO invoice_tax_lines (invoice_id, tsuat, thtien, tthue)
        VALUES (?, ?, ?, ?)
    """, (inv_cmc_id, "10%", 70000000.0, 7000000.0))

    # Invoice 3: Rikkeisoft (Mismatch)
    cur.execute("""
        INSERT INTO invoices (
            service_year, service_month, service_day, contract_no,
            khhdon, shdon, nlap, dvtte,
            seller_name, seller_mst, seller_address,
            buyer_name, buyer_mst, buyer_address, buyer_bank_name,
            tg_tcthue, tg_tthue, ttcktmai, tg_tttbso,
            source_path, raw_xml
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        2026, 6, 30, "",
        "1C26TRK", "0008899", "2026-06-30", "VND",
        "CÔNG TY CP RIKKEISOFT", "0105847055", "Toà nhà Handico, Mễ Trì, Quận Nam Từ Liêm, Hà Nội, Việt Nam",
        "NGÂN HÀNG MIZUHO - HANOI BRANCH", "0100234567", "16 Phan Chu Trinh, Hoàn Kiếm, Hà Nội", "Ngân hàng Mizuho",
        120000000.0, 12000000.0, 0.0, 132000000.0,
        "sample_xmls/invoice_rikkei_mismatch.xml", RIKKEI_MISMATCH_XML
    ))
    inv_rikkei_id = cur.lastrowid

    cur.execute("""
        INSERT INTO invoice_tax_lines (invoice_id, tsuat, thtien, tthue)
        VALUES (?, ?, ?, ?)
    """, (inv_rikkei_id, "10%", 120000000.0, 12000000.0))

    # ----------------- 7. Insert Contract References -----------------
    print("Inserting mock Contract References...")
    
    # FPT Annex 2: '2026-06' and '2026-07'
    cur.execute("""
        INSERT INTO contract_references (contract_id, annex_id, month, reference_number)
        VALUES (?, ?, '2026-06', 'REF-FPT-002-JUN')
    """, (contract_fpt_id, annex_fpt_2_id))
    cur.execute("""
        INSERT INTO contract_references (contract_id, annex_id, month, reference_number)
        VALUES (?, ?, '2026-07', 'REF-FPT-002-JUL')
    """, (contract_fpt_id, annex_fpt_2_id))
    
    # CMC Annex 1: '2026-06' and '2026-07'
    cur.execute("""
        INSERT INTO contract_references (contract_id, annex_id, month, reference_number)
        VALUES (?, ?, '2026-06', 'REF-CMC-001-JUN')
    """, (contract_cmc_id, annex_cmc_1_id))
    cur.execute("""
        INSERT INTO contract_references (contract_id, annex_id, month, reference_number)
        VALUES (?, ?, '2026-07', 'REF-CMC-001-JUL')
    """, (contract_cmc_id, annex_cmc_1_id))
    
    # FPT Framework (direct, no annex - annex_id = 0): '2026-06' and '2026-07'
    cur.execute("""
        INSERT INTO contract_references (contract_id, annex_id, month, reference_number)
        VALUES (?, 0, '2026-06', 'REF-FPT-FW-JUN')
    """, (contract_fpt_id,))
    cur.execute("""
        INSERT INTO contract_references (contract_id, annex_id, month, reference_number)
        VALUES (?, 0, '2026-07', 'REF-FPT-FW-JUL')
    """, (contract_fpt_id,))

    # ----------------- 8. Insert Daily Attendance & Locks -----------------
    print("Inserting mock Daily Attendance logs & Locks...")
    from datetime import date
    
    active_staff_ids = [2, 3, 4]
    
    for d in range(1, 31):
        day_date = date(2026, 6, d)
        is_weekend = day_date.weekday() in (5, 6)
        if not is_weekend:
            for sid in active_staff_ids:
                cur.execute("""
                    INSERT INTO attendance (staff_id, date, work_hours, ot_hours)
                    VALUES (?, ?, 8.0, 0.0)
                """, (sid, f"2026-06-{d:02d}"))
                
    for sid in active_staff_ids:
        cur.execute("""
            INSERT INTO attendance_locks (staff_id, month, locked)
            VALUES (?, '2026-06', 1)
        """, (sid,))
        
    conn.commit()
    conn.close()
    print("Database seeding completed successfully!")


if __name__ == "__main__":
    main()
