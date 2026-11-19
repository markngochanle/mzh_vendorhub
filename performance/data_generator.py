"""
Enterprise-Scale Synthetic Data Generator for Load & Stress Testing.
Generates realistic enterprise datasets (vendors, contracts, annexes, staff, leaves, attendance, invoices).
"""

import os
import sqlite3
import random
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from pathlib import Path

from common import init_db
from performance.config import PERF_DB_PATH


VIETNAMESE_FIRST_NAMES = ["Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Huỳnh", "Phan", "Vũ", "Võ", "Đặng", "Bùi", "Đỗ", "Hồ", "Ngô", "Dương", "Lý"]
VIETNAMESE_MIDDLE_NAMES = ["Văn", "Thị", "Hữu", "Đức", "Minh", "Quốc", "Anh", "Thanh", "Xuân", "Thành", "Ngọc", "Hải", "Tuấn"]
VIETNAMESE_LAST_NAMES = ["An", "Bình", "Cường", "Dũng", "Giang", "Hải", "Khoa", "Linh", "Minh", "Nam", "Phong", "Quân", "Sơn", "Tâm", "Tuấn", "Việt", "Phương", "Hương", "Mai", "Trang"]

POSITIONS = [
    "Senior Python Engineer", "Fullstack Developer", "DevOps Engineer", "Frontend Specialist",
    "QA Lead", "Automation QA Engineer", "Solution Architect", "Scrum Master",
    "Project Manager", "Data Engineer", "Security Consultant", "Business Analyst"
]

VENDOR_NAMES = [
    "FPT Software Co., Ltd", "CMC Global Technology JSC", "TMA Solutions Vietnam",
    "VTI Cloud Services JSC", "NashTech Vietnam", "KMS Technology Vietnam",
    "NTT Data Vietnam", "Fujitsu Software Technologies", "KDDI Vietnam Corporation",
    "Hitachi Digital Services", "Viettel Enterprise Solutions", "VNPT IT Telecom",
    "Mori Capital Technology", "Tokyo Tech Solutions", "RikkeiSoft Corporation"
]


class SyntheticDataGenerator:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = str(db_path or PERF_DB_PATH)

    def _random_name(self) -> str:
        return f"{random.choice(VIETNAMESE_FIRST_NAMES)} {random.choice(VIETNAMESE_MIDDLE_NAMES)} {random.choice(VIETNAMESE_LAST_NAMES)}"

    def generate(self, scale: str = "medium", verbose: bool = False) -> Dict[str, Any]:
        """
        Generates enterprise synthetic data.
        Scales:
          - 'small':  15 vendors, 50 contracts, 150 annexes, 300 staff, 1,000 invoices
          - 'medium': 35 vendors, 150 contracts, 500 annexes, 1,000 staff, 4,000 invoices
          - 'large':  75 vendors, 400 contracts, 1,500 annexes, 3,000 staff, 12,000 invoices
        """
        scale_configs = {
            "small": {"vendors": 15, "contracts": 50, "annexes_per_c": 3, "staff": 300, "invoices": 1000},
            "medium": {"vendors": 35, "contracts": 150, "annexes_per_c": 4, "staff": 1000, "invoices": 4000},
            "large": {"vendors": 75, "contracts": 400, "annexes_per_c": 4, "staff": 3000, "invoices": 12000},
        }
        cfg = scale_configs.get(scale, scale_configs["medium"])

        # Reset destination DB file
        dest_path = Path(self.db_path)
        if dest_path.exists():
            dest_path.unlink()

        # Connect and initialize schema using common.init_db
        import common
        saved_db_path = common.DB_PATH
        common.DB_PATH = self.db_path
        try:
            common.init_db()
        finally:
            common.DB_PATH = saved_db_path

        # Reopen cursor on freshly initialized db
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("PRAGMA synchronous = OFF")
        cur.execute("PRAGMA journal_mode = MEMORY")

        counts: Dict[str, int] = {}

        # 1. Vendors (1 Buyer, N Sellers)
        vendors_data = [
            ("Mizuho Bank Ltd. - Hanoi Branch", "CornerStone Building, 16 Phan Chu Trinh", "Chi nhánh Ngân hàng Mizuho Hà Nội", "Tòa nhà CornerStone, 16 Phan Chu Trinh", "MIZUHO", "0101234567", "024-3933-3111", "Mizuho Bank", "Hanoi", "Mizuho Bank Ltd", "100029384", "VND", 1, 1, None)
        ]
        for i in range(1, cfg["vendors"] + 1):
            name = VENDOR_NAMES[(i - 1) % len(VENDOR_NAMES)] + (f" #{i}" if i > len(VENDOR_NAMES) else "")
            short = f"VND-{i:03d}"
            tax = f"010{random.randint(1000000, 9999999)}"
            vendors_data.append((
                name, f"{random.randint(10, 500)} Duy Tan, Cau Giay, Hanoi",
                name, f"{random.randint(10, 500)} Phố Duy Tân, Cầu Giấy, Hà Nội",
                short, tax, "024-3888-9999", "Techcombank", "Hanoi Branch", name, f"98765432{i:03d}", "VND",
                0, 1, None
            ))

        cur.executemany("""
            INSERT INTO vendors (
                company_name, address, company_name_vi, address_vi, short_name,
                tax_id, tel, bank_name, bank_address, account_name, account_number, account_currency,
                purchasing, is_active, deleted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, vendors_data)
        counts["vendors"] = len(vendors_data)

        # 2. Contracts
        contracts_data = []
        for c_idx in range(1, cfg["contracts"] + 1):
            seller_id = random.randint(2, len(vendors_data))
            framework_no = f"MIZ-CTR-2026-{c_idx:04d}"
            framework_name = f"Enterprise IT SOW {c_idx}"
            b_type = random.choice(["TM", "FIXED_PRICE", "RECURRING"])
            c_val = random.choice([500_000_000, 1_200_000_000, 3_500_000_000, 8_000_000_000])
            contracts_data.append((
                1, seller_id, framework_no, framework_name,
                "2025-01-01", "2025-01-01", "2027-12-31",
                1, None, c_val, "FRAMEWORK", b_type, "2025-01-01", 50_000_000 if b_type == "RECURRING" else None,
                "MONTHLY", "MANUAL", 60, 12, None, None, f"Standard IT Contract {c_idx}", 0
            ))

        cur.executemany("""
            INSERT INTO contracts (
                buyer_vendor_id, seller_vendor_id, framework_no, framework_name,
                signed_date, start_date, end_date,
                is_active, deleted_at, contract_value, contract_type, billing_type,
                signed_date, recurring_fee, recurring_period, renewal_type,
                renewal_notice_days, renewal_period_months, renewal_note, last_renewed_at,
                contract_summary, is_usage_based
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, contracts_data)
        counts["contracts"] = len(contracts_data)

        # 3. Contract Annexes
        annexes_data = []
        annex_id_seq = 1
        for c_idx in range(1, cfg["contracts"] + 1):
            for a_sub in range(1, cfg["annexes_per_c"] + 1):
                annex_name = f"Annex {a_sub:02d} - Phase {a_sub}"
                b_type = random.choice(["TM", "FIXED_PRICE", "RECURRING"])
                annexes_data.append((
                    c_idx, annex_name, "2025-01-15", "2025-01-15", "2026-12-31",
                    1, None, 250_000_000 * a_sub, "2026-03-31", b_type, None, "MONTHLY", 0
                ))
                annex_id_seq += 1

        cur.executemany("""
            INSERT INTO contract_annexes (
                contract_id, annex_name, signed_date, start_date, end_date,
                is_active, deleted_at, value, cashout_date, billing_type,
                recurring_fee, recurring_period, is_usage_based
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, annexes_data)
        counts["annexes"] = len(annexes_data)

        # 4. Contract Staff
        staff_data = []
        for s_idx in range(1, cfg["staff"] + 1):
            vendor_id = random.randint(2, len(vendors_data))
            name = self._random_name()
            pos = random.choice(POSITIONS)
            tot_h = random.choice([8.0, 16.0, 24.0, 40.0, 80.0, 96.0])
            used_h = random.choice([0.0, 8.0, 16.0, 24.0])
            staff_data.append((
                name, vendor_id, pos, "2025-01-01", "2027-12-31",
                tot_h, used_h, 1, "active", "Standard 8h Shift"
            ))

        cur.executemany("""
            INSERT INTO contract_staff (
                full_name_vi, vendor_id, position, joining_date, tentative_leaving_date,
                paid_leave_total_hours, paid_leave_used_hours, ot, status, work_shift
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, staff_data)
        counts["staff"] = len(staff_data)

        # 5. Contract Staff Links
        links_data = []
        for s_id in range(1, cfg["staff"] + 1):
            contract_id = random.randint(1, cfg["contracts"])
            annex_id = random.randint(1, len(annexes_data))
            m_rate = random.choice([35_000_000, 50_000_000, 75_000_000, 110_000_000])
            d_rate = round(m_rate / 22, 0)
            tot_leave_h = random.choice([16.0, 24.0, 32.0, 48.0])
            carry_h = random.choice([0.0, 8.0, 16.0])
            links_data.append((
                s_id, contract_id, annex_id, m_rate, d_rate,
                "2025-01-01", "2026-12-31", tot_leave_h, carry_h
            ))

        cur.executemany("""
            INSERT INTO contract_staff_links (
                staff_id, contract_id, annex_id, monthly_rate, manday_rate,
                joining_date, tentative_leaving_date, paid_leave_total_hours, carried_over_leave_hours
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, links_data)
        counts["staff_links"] = len(links_data)

        # 6. Monthly Attendance Summary
        months = ["2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03"]
        mas_data = []
        for s_id in range(1, min(cfg["staff"] + 1, 500)):
            for m in months:
                std = 22.0
                act = random.choice([20.0, 21.0, 22.0])
                pl = std - act
                d_rate = 2_500_000.0
                tot = act * d_rate
                mas_data.append((s_id, m, std, act, pl, 0.0, d_rate, tot, 1))

        cur.executemany("""
            INSERT INTO monthly_attendance_summary (
                staff_id, month, standard_days, actual_days, paid_leave_days,
                ot_converted_hours, daily_rate, total_amount, locked
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, mas_data)
        counts["monthly_attendance"] = len(mas_data)

        # 7. Invoices & Tax Lines
        invoices_data = []
        tax_lines_data = []
        for inv_idx in range(1, cfg["invoices"] + 1):
            seller_idx = random.randint(1, len(vendors_data) - 1)
            seller_name = vendors_data[seller_idx][0]
            seller_mst = vendors_data[seller_idx][5]
            subtotal = random.choice([25_000_000, 80_000_000, 150_000_000, 400_000_000])
            tax = subtotal * 0.10
            total = subtotal + tax
            fy = random.choice([2025, 2026])
            fm = random.randint(1, 12)
            c_no = f"MIZ-CTR-2026-{(inv_idx % cfg['contracts']) + 1:04d}"
            invoices_data.append((
                f"INV_{inv_idx:05d}.xml", datetime.now().isoformat(), "1C26TUU", f"INV-{inv_idx:06d}",
                f"{fy}-{fm:02d}-15", "VND", seller_name, seller_mst, "Hanoi, Vietnam",
                vendors_data[0][0], vendors_data[0][5], vendors_data[0][1], "Mizuho Bank",
                subtotal, tax, 0.0, total, fy, fm, 15, c_no,
                1, f"Generated Synthetic Invoice {inv_idx}"
            ))
            tax_lines_data.append((inv_idx, "10%", subtotal, tax))

        cur.executemany("""
            INSERT INTO invoices (
                file_name, imported_at, khhdon, shdon, nlap, dvtte,
                seller_name, seller_mst, seller_address,
                buyer_name, buyer_mst, buyer_address, buyer_bank_name,
                tg_tcthue, tg_tthue, ttcktmai, tg_tttbso,
                service_year, service_month, service_day, contract_no,
                sent_to_mgs, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, invoices_data)
        counts["invoices"] = len(invoices_data)

        cur.executemany("""
            INSERT INTO invoice_tax_lines (invoice_id, tsuat, thtien, tthue)
            VALUES (?, ?, ?, ?)
        """, tax_lines_data)
        counts["tax_lines"] = len(tax_lines_data)

        # 8. Milestones & Recurring Payouts
        milestones_data = []
        for m_idx in range(1, 300):
            c_id = (m_idx % cfg["contracts"]) + 1
            amt = random.choice([50_000_000, 120_000_000, 250_000_000])
            milestones_data.append((
                c_id, 1, f"Milestone M{m_idx}", "DELIVERY", 20.0, amt,
                "2026-06-30", "2026-06-28", "PAID", f"ACC-{m_idx:04d}", 1, "2026-07-05", "Completed"
            ))

        cur.executemany("""
            INSERT INTO contract_milestones (
                contract_id, annex_id, milestone_name, milestone_type, percentage,
                amount, planned_date, actual_date, status, acceptance_doc_no,
                invoice_id, cashout_date, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, milestones_data)
        counts["milestones"] = len(milestones_data)

        # Commit and clean up
        conn.commit()
        conn.close()

        file_size_mb = round(Path(self.db_path).stat().st_size / (1024 * 1024), 2)
        counts["db_size_mb"] = file_size_mb

        if verbose:
            print(f"[DataGen] Created synthetic enterprise dataset at {self.db_path} ({file_size_mb} MB)")
            for k, v in counts.items():
                print(f"  - {k}: {v}")

        return counts
