# test_app.py
import io
import os
import unittest
import sqlite3
import calendar
from pathlib import Path
from datetime import datetime, date

# Override database path to use a test database file
import common
TEST_DB_PATH = str(Path(__file__).resolve().with_name("unittest_db.sqlite3"))
os.environ["DB_PATH"] = TEST_DB_PATH
common.DB_PATH = TEST_DB_PATH

# Import modules to test
import vendors
import contracts
import staff
import invoices
import attendance
import server
import projects
import payments


class MockHeaders(dict):
    def get(self, key, default=None):
        for k, v in self.items():
            if k.lower() == key.lower():
                return v
        return default


class MockHandler:
    def __init__(self, path="/", headers=None, body=b""):
        self.path = path
        self.headers = MockHeaders()
        if headers:
            for k, v in headers.items():
                self.headers[k] = v
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.response_status = None
        self.response_headers = {}
        self.headers_ended = False

    def send_response(self, status):
        self.response_status = status

    def send_header(self, name, value):
        self.response_headers[name.lower()] = value

    def end_headers(self):
        self.headers_ended = True

    def get_output_text(self):
        return self.wfile.getvalue().decode("utf-8", errors="ignore")


class StubHandler(server.Handler):
    def __init__(self, path, method="GET", headers=None, body=b""):
        self.path = path
        self.command = method
        self.headers = MockHeaders()
        if headers:
            for k, v in headers.items():
                self.headers[k] = v
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.response_status = None
        self.response_headers = {}

    def send_response(self, status):
        self.response_status = status

    def send_header(self, name, value):
        self.response_headers[name.lower()] = value

    def end_headers(self):
        pass

    def get_output_text(self):
        return self.wfile.getvalue().decode("utf-8", errors="ignore")


class BaseTestCase(unittest.TestCase):
    def setUp(self):
        # Clean up database file before test
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except OSError:
                pass
        
        # Re-initialize test database
        common.init_db()
        self.conn = common.db_connect()
        self.setup_mock_data()

    def tearDown(self):
        self.conn.close()

    def setup_mock_data(self):
        cur = self.conn.cursor()
        
        # 1. Insert active Buyer vendor (purchasing = 1)
        cur.execute("""
            INSERT INTO vendors (company_name_vi, address_vi, tax_id, purchasing, is_active)
            VALUES ('NGÂN HÀNG MIZUHO', '16 PHAN CHU TRINH', '0100234567', 1, 1)
        """)
        self.buyer_id = cur.lastrowid

        # 2. Insert active Seller vendor (purchasing = 0)
        cur.execute("""
            INSERT INTO vendors (company_name_vi, address_vi, tax_id, purchasing, is_active)
            VALUES ('FPT SOFTWARE', 'DUY TÂN, CẦU GIẤY', '0102135934', 0, 1)
        """)
        self.seller_id = cur.lastrowid

        # 3. Insert Contract
        cur.execute("""
            INSERT INTO contracts (buyer_vendor_id, seller_vendor_id, framework_no, framework_name, start_date, end_date, is_active)
            VALUES (?, ?, 'MHB/FPT/2025/001', 'FPT Framework Contract', '2025-01-01', '2026-12-31', 1)
        """, (self.buyer_id, self.seller_id))
        self.contract_id = cur.lastrowid

        # 4. Insert Annex
        cur.execute("""
            INSERT INTO contract_annexes (contract_id, annex_name, start_date, end_date, is_active)
            VALUES (?, 'Phụ lục 1', '2025-06-01', '2026-05-31', 1)
        """, (self.contract_id,))
        self.annex_id = cur.lastrowid

        # 5. Insert Staff
        cur.execute("""
            INSERT INTO contract_staff (
                full_name_vi, vendor_id, position,
                paid_leave_total_hours, paid_leave_used_hours, ot, status, work_shift
            ) VALUES (?, ?, 'Developer', 12.0, 4.0, 1, NULL, '8:00 - 17:00')
        """, ('Nguyễn Văn An', self.seller_id))
        self.staff_id = cur.lastrowid

        # 6. Insert Contract Staff Link
        cur.execute("""
            INSERT INTO contract_staff_links (
                staff_id, contract_id, annex_id, monthly_rate, manday_rate, joining_date, tentative_leaving_date, created_at, updated_at
            ) VALUES (?, ?, ?, 45000000.0, 2000000.0, '2025-06-01', '2026-05-31', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """, (self.staff_id, self.contract_id, self.annex_id))

        self.conn.commit()


# ==================== 1. Test Common Helpers ====================
class TestCommon(BaseTestCase):
    def test_parse_int_or_none(self):
        self.assertEqual(common.parse_int_or_none("123"), 123)
        self.assertEqual(common.parse_int_or_none("  456  "), 456)
        self.assertIsNone(common.parse_int_or_none("abc"))
        self.assertIsNone(common.parse_int_or_none(None))
        self.assertIsNone(common.parse_int_or_none(""))

    def test_safe_return_to(self):
        self.assertEqual(common.safe_return_to("/vendors"), "/vendors")
        self.assertEqual(common.safe_return_to("http://hack.com"), "/")
        self.assertEqual(common.safe_return_to(None), "/")
        self.assertEqual(common.safe_return_to(""), "/")

    def test_fmt_money(self):
        self.assertEqual(common.fmt_money(1234567.89, "VND"), "1,234,567.89 VND")
        self.assertEqual(common.fmt_money(1000), "1,000.00")
        self.assertEqual(common.fmt_money(None), "")
        self.assertEqual(common.fmt_money("not-a-number"), "not-a-number")

    def test_now_iso(self):
        self.assertTrue(len(common.now_iso()) > 0)

    def test_redirect(self):
        handler = MockHandler()
        common.redirect(handler, "/test")
        self.assertEqual(handler.response_status, 302)
        self.assertEqual(handler.response_headers["location"], "/test")


# ==================== 2. Test Vendors CRUD ====================
class TestVendors(BaseTestCase):
    def test_page_vendors_list(self):
        html = vendors.page_vendors_list("", "active", return_to="/")
        self.assertIn("FPT SOFTWARE", html)
        self.assertIn("NGÂN HÀNG MIZUHO", html)

    def test_page_vendor_form(self):
        # new form
        html_new = vendors.page_vendor_form("new", None)
        self.assertIn("Add Vendor", html_new)
        
        # edit form
        row = self.conn.execute("SELECT * FROM vendors WHERE id=?", (self.seller_id,)).fetchone()
        html_edit = vendors.page_vendor_form("edit", row)
        self.assertIn("Edit Vendor", html_edit)
        self.assertIn("FPT SOFTWARE", html_edit)

    def test_handle_vendor_create_post(self):
        body = b"company_name_vi=CMC+TS&tax_id=0102715694&purchasing=0&is_active=1"
        handler = MockHandler(body=body, headers={"content-length": str(len(body))})
        vendors.handle_vendor_create_post(handler)
        
        self.assertEqual(handler.response_status, 302)
        
        # Verify db insert
        inserted = self.conn.execute("SELECT * FROM vendors WHERE tax_id='0102715694'").fetchone()
        self.assertIsNotNone(inserted)
        self.assertEqual(inserted["company_name_vi"], "CMC TS")

    def test_handle_vendor_update_post(self):
        body = f"id={self.seller_id}&company_name_vi=FPT+SOFTWARE+UPDATED&tax_id=0102135934&purchasing=0&is_active=1".encode()
        handler = MockHandler(body=body, headers={"content-length": str(len(body))})
        vendors.handle_vendor_update_post(handler)
        
        self.assertEqual(handler.response_status, 302)
        
        # Verify db update
        updated = self.conn.execute("SELECT * FROM vendors WHERE id=?", (self.seller_id,)).fetchone()
        self.assertEqual(updated["company_name_vi"], "FPT SOFTWARE UPDATED")

    def test_handle_vendor_deactivate_post(self):
        body = f"id={self.seller_id}".encode()
        handler = MockHandler(body=body, headers={"content-length": str(len(body))})
        vendors.handle_vendor_deactivate_post(handler)
        
        self.assertEqual(handler.response_status, 302)
        
        # Verify deactivate
        deactivated = self.conn.execute("SELECT is_active, deleted_at FROM vendors WHERE id=?", (self.seller_id,)).fetchone()
        self.assertEqual(deactivated["is_active"], 0)
        self.assertIsNotNone(deactivated["deleted_at"])

    def test_handle_vendor_restore_post(self):
        # First deactivate
        self.conn.execute("UPDATE vendors SET is_active=0, deleted_at='2026-07-04' WHERE id=?", (self.seller_id,))
        self.conn.commit()
        
        body = f"id={self.seller_id}".encode()
        handler = MockHandler(body=body, headers={"content-length": str(len(body))})
        vendors.handle_vendor_restore_post(handler)
        
        self.assertEqual(handler.response_status, 302)
        
        # Verify restore
        restored = self.conn.execute("SELECT is_active, deleted_at FROM vendors WHERE id=?", (self.seller_id,)).fetchone()
        self.assertEqual(restored["is_active"], 1)
        self.assertIsNone(restored["deleted_at"])


# ==================== 3. Test Contracts CRUD ====================
class TestContracts(BaseTestCase):
    def test_page_contracts_list(self):
        html = contracts.page_contracts_list("", "active", return_to="/")
        self.assertIn("MHB/FPT/2025/001", html)

    def test_page_contract_form(self):
        # new
        html_new = contracts.page_contract_form("new", None, [], None)
        self.assertIn("Add Framework Contract", html_new)
        
        # edit
        c = self.conn.execute("SELECT * FROM contracts WHERE id=?", (self.contract_id,)).fetchone()
        html_edit = contracts.page_contract_form("edit", c, [], None)
        self.assertIn("Edit Contract #", html_edit)

    def test_handle_contract_create_post(self):
        body = f"buyer_vendor_id={self.buyer_id}&seller_vendor_id={self.seller_id}&framework_no=MHB/NEW/2026&start_date=2026-01-01&end_date=2026-12-31".encode()
        handler = MockHandler(body=body, headers={"content-length": str(len(body))})
        contracts.handle_contract_create_post(handler)
        
        self.assertEqual(handler.response_status, 302)
        inserted = self.conn.execute("SELECT * FROM contracts WHERE framework_no='MHB/NEW/2026'").fetchone()
        self.assertIsNotNone(inserted)

    def test_handle_contract_update_post(self):
        body = f"id={self.contract_id}&buyer_vendor_id={self.buyer_id}&seller_vendor_id={self.seller_id}&framework_no=MHB/FPT/2025/UPDATED&start_date=2025-01-01&end_date=2026-12-31".encode()
        handler = MockHandler(body=body, headers={"content-length": str(len(body))})
        contracts.handle_contract_update_post(handler)
        
        self.assertEqual(handler.response_status, 302)
        updated = self.conn.execute("SELECT * FROM contracts WHERE id=?", (self.contract_id,)).fetchone()
        self.assertEqual(updated["framework_no"], "MHB/FPT/2025/UPDATED")

    def test_toggle_reference_lock_ajax(self):
        import json
        body = json.dumps({
            "contract_id": self.contract_id,
            "annex_id": 0,
            "month": "2026-06",
            "locked": 1
        }).encode()
        handler = MockHandler(body=body, headers={"content-length": str(len(body))})
        contracts.handle_toggle_reference_lock_ajax(handler)
        self.assertEqual(handler.response_status, 200)
        
        # Verify db state
        row = self.conn.execute("SELECT locked FROM contract_references WHERE contract_id=? AND annex_id=0 AND month='2026-06'", (self.contract_id,)).fetchone()
        self.assertEqual(row["locked"], 1)

    def test_handle_contract_delete_post(self):
        body = f"id={self.contract_id}".encode()
        handler = MockHandler(body=body, headers={"content-length": str(len(body))})
        contracts.handle_contract_delete_post(handler)
        
        self.assertEqual(handler.response_status, 302)
        deleted = self.conn.execute("SELECT is_active FROM contracts WHERE id=?", (self.contract_id,)).fetchone()
        self.assertEqual(deleted["is_active"], 0)

    def test_handle_contract_assign_staff_save_post_error_handling(self):
        # Test in-batch duplicate submission
        body = f"contract_id={self.contract_id}&link_id=&staff_id={self.staff_id}&joining_date=2025-01-01&monthly_rate=50000000&link_id=&staff_id={self.staff_id}&joining_date=2025-01-01&monthly_rate=60000000".encode()
        handler = MockHandler(body=body, headers={"content-length": str(len(body))})
        contracts.handle_contract_assign_staff_save_post(handler)
        self.assertEqual(handler.response_status, 400)
        out = handler.get_output_text()
        self.assertIn("Duplicate allocation", out)
        # Verify submitted rows (rates and dates) were preserved in returned form
        self.assertIn("50000000", out)
        self.assertIn("60000000", out)

    def test_contract_and_annex_values(self):
        # Create a contract with custom contract_value
        body = f"buyer_vendor_id={self.buyer_id}&seller_vendor_id={self.seller_id}&framework_no=MHB/VAL/2026&contract_value=5000000000".encode()
        handler = MockHandler(body=body, headers={"content-length": str(len(body))})
        contracts.handle_contract_create_post(handler)
        c = self.conn.execute("SELECT * FROM contracts WHERE framework_no='MHB/VAL/2026'").fetchone()
        self.assertIsNotNone(c)
        self.assertEqual(c["contract_value"], 5000000000.0)

        # Create annexes for this contract and verify sum default calculation
        body_annex1 = f"contract_id={c['id']}&annex_name=AnnexA&value=1200000000".encode()
        handler1 = MockHandler(body=body_annex1, headers={"content-length": str(len(body_annex1))})
        contracts.handle_annex_create_post(handler1)

        body_annex2 = f"contract_id={c['id']}&annex_name=AnnexB&value=800000000".encode()
        handler2 = MockHandler(body=body_annex2, headers={"content-length": str(len(body_annex2))})
        contracts.handle_annex_create_post(handler2)

        # Get list view html and check default fallback/total
        html = contracts.page_contracts_list("", "active", return_to="/")
        self.assertIn("5,000,000,000", html) # Since contract_value is set, it shows contract_value

        # Create another contract without contract_value (defaults to annexes sum)
        body2 = f"buyer_vendor_id={self.buyer_id}&seller_vendor_id={self.seller_id}&framework_no=MHB/VAL_DEF/2026".encode()
        handler_c2 = MockHandler(body=body2, headers={"content-length": str(len(body2))})
        contracts.handle_contract_create_post(handler_c2)
        c2 = self.conn.execute("SELECT * FROM contracts WHERE framework_no='MHB/VAL_DEF/2026'").fetchone()

        # Add annexes
        body_annex3 = f"contract_id={c2['id']}&annex_name=AnnexC&value=1500000000".encode()
        handler3 = MockHandler(body=body_annex3, headers={"content-length": str(len(body_annex3))})
        contracts.handle_annex_create_post(handler3)

        # Verify page list displays sum
        html2 = contracts.page_contracts_list("", "active", return_to="/")
        self.assertIn("1,500,000,000", html2)
        self.assertIn("sum of annexes", html2)

    def test_carried_over_leave_hint_in_assign_staff_form(self):
        cur = self.conn.cursor()
        cur.execute("INSERT INTO contract_annexes (contract_id, annex_name, start_date, end_date) VALUES (?, 'Phụ lục Cũ', '2026-01-01', '2026-06-30')", (self.contract_id,))
        a1_id = cur.lastrowid
        cur.execute("INSERT INTO contract_annexes (contract_id, annex_name, start_date, end_date) VALUES (?, 'Phụ lục Mới', '2026-07-01', '2026-12-31')", (self.contract_id,))
        a2_id = cur.lastrowid

        cur.execute("INSERT INTO contract_staff_links (staff_id, contract_id, annex_id, joining_date, tentative_leaving_date, paid_leave_total_hours) VALUES (?, ?, ?, '2026-01-01', '2026-06-30', 16.0)", (self.staff_id, self.contract_id, a1_id))
        self.conn.commit()

        html = contracts.page_contract_assign_staff(self.contract_id, annex_id=a2_id)
        self.assertIn("Carried Over (h)", html)
        self.assertIn("Paid Leave (h)", html)
        self.assertIn(f'"{self.staff_id}":', html)
        self.assertIn('"hours": 16.0', html)
        self.assertIn("setCarriedOver", html)


# ==================== 4. Test Staff / Shifts ====================
class TestStaff(BaseTestCase):
    def test_check_no_overlap(self):
        cur = self.conn.cursor()
        # 1. Same staff overlap test
        ok, msg = staff.check_no_overlap(cur, None, self.staff_id, "2025-07-01", "2025-08-01")
        self.assertFalse(ok)
        self.assertIn("already allocated", msg)

        # 2. Distinct staff_id, no overlap issues
        ok_diff, msg_diff = staff.check_no_overlap(cur, None, 9999, "2025-07-01", "2025-08-01")
        self.assertTrue(ok_diff)

    def test_page_staff_shifts(self):
        html = staff.page_staff_shifts()
        self.assertIn("Nguyễn Văn An", html)
        self.assertIn("8:00 - 17:00", html)

    def test_page_staff_list_locked_payroll(self):
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO monthly_attendance_summary (staff_id, month, standard_days, actual_days, paid_leave_days, ot_converted_hours, daily_rate, total_amount, locked)
            VALUES (?, '2026-05', 21.0, 9.0, 0.0, 7.83, 2857142.85, 28510715.0, 1)
        """, (self.staff_id,))
        self.conn.commit()

        html = staff.page_staff_list("", "", "", "", "all", return_to="/staff")
        self.assertIn("Locked Payroll", html)
        self.assertIn("28,510,715.00", html)

    def test_handle_staff_create_post(self):
        body = f"full_name_vi=Lê+Hoàng+Long&vendor_id={self.seller_id}&contract_id={self.contract_id}&joining_date=2026-01-01&ot=1&work_shift=8%3A30+-+17%3A30".encode()
        handler = MockHandler(body=body, headers={"content-length": str(len(body))})
        staff.handle_staff_create_post(handler)
        
        self.assertEqual(handler.response_status, 302)
        inserted = self.conn.execute("SELECT * FROM contract_staff WHERE full_name_vi='Lê Hoàng Long'").fetchone()
        self.assertIsNotNone(inserted)
        self.assertEqual(inserted["work_shift"], "8:30 - 17:30")
        self.assertEqual(inserted["joining_date"], "2026-01-01")

    def test_page_staff_form_with_none_values(self):
        cur = self.conn.cursor()
        # Insert a contract with None values
        cur.execute("""
            INSERT INTO contracts (buyer_vendor_id, seller_vendor_id, framework_no, framework_name, start_date, is_active)
            VALUES (?, ?, NULL, NULL, '2026-01-01', 1)
        """, (self.buyer_id, self.seller_id))
        c_none_id = cur.lastrowid

        # Insert an annex with None values
        cur.execute("""
            INSERT INTO contract_annexes (contract_id, annex_name, value, is_active)
            VALUES (?, NULL, 100000000.0, 1)
        """, (c_none_id,))
        a_none_id = cur.lastrowid

        # Insert link for the staff
        cur.execute("""
            INSERT INTO contract_staff_links (staff_id, contract_id, annex_id, monthly_rate, manday_rate, joining_date, tentative_leaving_date, created_at, updated_at)
            VALUES (?, ?, ?, 50000000.0, 2500000.0, '2026-01-01', '2026-12-31', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """, (self.staff_id, c_none_id, a_none_id))
        self.conn.commit()

        # Load staff row
        staff_row = self.conn.execute("SELECT * FROM contract_staff WHERE id=?", (self.staff_id,)).fetchone()
        
        # Render staff form in edit mode
        html = staff.page_staff_form("edit", staff_row, None, return_to="/staff")
        
        # Verify render completes successfully and contains expected elements
        self.assertIn("Contract & Annex Allocations History", html)

    def test_page_staff_form_payroll(self):
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO projects (short_name, full_name, is_active)
            VALUES ('TEST-STAFF-PROJ', 'Test Staff Project', 1)
        """)
        p_id = cur.lastrowid

        cur.execute("""
            INSERT INTO project_staff_assignments (project_id, staff_id, month)
            VALUES (?, ?, '2026-05')
        """, (p_id, self.staff_id))

        cur.execute("""
            INSERT INTO monthly_attendance_summary (staff_id, month, standard_days, actual_days, paid_leave_days, ot_converted_hours, daily_rate, total_amount, locked)
            VALUES (?, '2026-05', 21.0, 9.0, 0.0, 7.83, 2857142.85, 28510715.0, 1)
        """, (self.staff_id,))
        self.conn.commit()

        staff_row = self.conn.execute("SELECT * FROM contract_staff WHERE id=?", (self.staff_id,)).fetchone()
        html = staff.page_staff_form("edit", staff_row, None, return_to="/staff")

        self.assertIn("Payroll Report by Project", html)
        self.assertIn("TEST-STAFF-PROJ", html)
        self.assertIn("28,510,715", html)

    def test_handle_staff_update_post(self):
        # Insert a link first that does not overlap with the mock data (which is 2025-06-01 to 2026-05-31)
        self.conn.execute("""
            INSERT INTO contract_staff_links (staff_id, contract_id, annex_id, monthly_rate, manday_rate, joining_date, tentative_leaving_date, created_at, updated_at)
            VALUES (?, ?, NULL, 50000000.0, NULL, '2026-06-01', '2026-12-31', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """, (self.staff_id, self.contract_id))
        self.conn.commit()

        body = f"id={self.staff_id}&full_name_vi=Nguyễn+Văn+An+Update&vendor_id={self.seller_id}&joining_date=2026-07-01&tentative_leaving_date=2026-11-30&paid_leave_total_hours=12&paid_leave_used_hours=2&ot=1&work_shift=8%3A30+-+17%3A30".encode()
        handler = MockHandler(body=body, headers={"content-length": str(len(body))})
        staff.handle_staff_update_post(handler)

        self.assertEqual(handler.response_status, 302)
        
        # Verify staff info updated (joining_date and tentative_leaving_date are saved directly to contract_staff)
        inserted = self.conn.execute("SELECT * FROM contract_staff WHERE id=?", (self.staff_id,)).fetchone()
        self.assertEqual(inserted["full_name_vi"], "Nguyễn Văn An Update")
        self.assertEqual(inserted["joining_date"], "2026-07-01")
        self.assertEqual(inserted["tentative_leaving_date"], "2026-11-30")

    def test_staff_leave_calculation_and_carry_over(self):
        import urllib.parse
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO contract_staff (vendor_id, full_name_vi, position, status, paid_leave_total_hours, paid_leave_used_hours)
            VALUES (?, 'Phạm Văn Leave', 'Developer', 'active', 16.0, 0.0)
        """, (self.seller_id,))
        s_id = cur.lastrowid

        cur.execute("""
            INSERT INTO contract_annexes (contract_id, annex_name, start_date, end_date, is_active)
            VALUES (?, 'Phụ lục 1', '2026-01-01', '2026-06-30', 1)
        """, (self.contract_id,))
        a1_id = cur.lastrowid

        cur.execute("""
            INSERT INTO contract_annexes (contract_id, annex_name, start_date, end_date, is_active)
            VALUES (?, 'Phụ lục 2', '2026-07-01', '2026-12-31', 1)
        """, (self.contract_id,))
        a2_id = cur.lastrowid

        cur.execute("""
            INSERT INTO contract_staff_links (staff_id, contract_id, annex_id, monthly_rate, joining_date, tentative_leaving_date, paid_leave_total_hours, carried_over_leave_hours)
            VALUES (?, ?, ?, 50000000, '2026-01-01', '2026-06-30', 16.0, 0.0)
        """, (s_id, self.contract_id, a1_id))

        cur.execute("""
            INSERT INTO monthly_attendance_summary (staff_id, month, standard_days, actual_days, paid_leave_days, ot_converted_hours, daily_rate, total_amount, locked)
            VALUES (?, '2026-03', 22, 21, 1.0, 0, 2272727, 50000000, 1)
        """, (s_id,))
        self.conn.commit()

        unused_h, prev_link = common.get_staff_previous_unused_leave(self.conn, s_id, joining_date="2026-07-01")
        self.assertEqual(unused_h, 8.0)
        self.assertEqual(prev_link["annex_name"], "Phụ lục 1")

        post_data = urllib.parse.urlencode([
            ("contract_id", str(self.contract_id)),
            ("annex_id", str(a2_id)),
            ("link_id", ""),
            ("staff_id", str(s_id)),
            ("joining_date", "2026-07-01"),
            ("tentative_leaving_date", "2026-12-31"),
            ("monthly_rate", "55000000"),
            ("manday_rate", ""),
            ("paid_leave_total_hours", "16.0"),
            ("carried_over_leave_hours", "8.0")
        ]).encode("utf-8")
        handler = StubHandler("/contract/assign-staff/save", "POST", body=post_data, headers={"Content-Length": str(len(post_data)), "Content-Type": "application/x-www-form-urlencoded"})
        contracts.handle_contract_assign_staff_save_post(handler)

        status_aug = common.get_staff_leave_status(self.conn, s_id, as_of_month="2026-08")
        self.assertEqual(status_aug["active_budget_hours"], 24.0)
        self.assertEqual(status_aug["active_used_hours"], 0.0)
        self.assertEqual(status_aug["active_remaining_hours"], 24.0)
        self.assertEqual(status_aug["contract_total_hours"], 32.0)

        post_att = urllib.parse.urlencode([
            ("month", "2026-08"),
            ("staff_ids", str(s_id)),
            (f"pl_{s_id}_2026-08", "3.5"),
            (f"std_{s_id}_2026-08", "22"),
            (f"act_{s_id}_2026-08", "18.5"),
            (f"ot_{s_id}_2026-08", "0"),
            (f"rate_{s_id}_2026-08", "2500000"),
            (f"tot_{s_id}_2026-08", "55000000")
        ]).encode("utf-8")
        handler_att = StubHandler("/attendance/monthly/save", "POST", body=post_att, headers={"Content-Length": str(len(post_att)), "Content-Type": "application/x-www-form-urlencoded"})
        attendance.handle_attendance_monthly_save_post(handler_att)
        self.assertIn("exceeds remaining balance", handler_att.wfile.getvalue().decode("utf-8", errors="ignore"))

        post_att_ok = urllib.parse.urlencode([
            ("month", "2026-08"),
            ("staff_ids", str(s_id)),
            (f"pl_{s_id}_2026-08", "2.5"),
            (f"std_{s_id}_2026-08", "22"),
            (f"act_{s_id}_2026-08", "19.5"),
            (f"ot_{s_id}_2026-08", "0"),
            (f"rate_{s_id}_2026-08", "2500000"),
            (f"tot_{s_id}_2026-08", "55000000")
        ]).encode("utf-8")
        handler_att_ok = StubHandler("/attendance/monthly/save", "POST", body=post_att_ok, headers={"Content-Length": str(len(post_att_ok)), "Content-Type": "application/x-www-form-urlencoded"})
        attendance.handle_attendance_monthly_save_post(handler_att_ok)
        self.assertEqual(handler_att_ok.response_status, 302)

        html_list = staff.page_staff_list("Phạm Văn Leave", "", "", "", "all", return_to="/staff")
        self.assertIn("Phạm Văn Leave", html_list)
        self.assertIn("rem", html_list)

        staff_row = self.conn.execute("SELECT * FROM contract_staff WHERE id = ?", (s_id,)).fetchone()
        html_form = staff.page_staff_form("edit", staff_row)
        self.assertIn("Remaining usable", html_form)
        self.assertIn("Active available", html_form)

    def test_future_annex_leave_cannot_be_used_in_current_month(self):
        import urllib.parse
        cur = self.conn.cursor()
        
        # 1. Create a staff member
        cur.execute("""
            INSERT INTO contract_staff (vendor_id, full_name_vi, position, status, paid_leave_total_hours, paid_leave_used_hours)
            VALUES (?, 'Lê Tương Lai', 'Developer', 'active', 16.0, 16.0)
        """, (self.seller_id,))
        s_id = cur.lastrowid

        # 2. Annex 1: Current period (2026-06-01 to 2026-11-30) with 2 days (16 hours) leave, fully used
        cur.execute("""
            INSERT INTO contract_annexes (contract_id, annex_name, start_date, end_date, is_active)
            VALUES (?, 'Phụ lục Hiện Tại', '2026-06-01', '2026-11-30', 1)
        """, (self.contract_id,))
        a1_id = cur.lastrowid

        cur.execute("""
            INSERT INTO contract_staff_links (staff_id, contract_id, annex_id, monthly_rate, joining_date, tentative_leaving_date, paid_leave_total_hours, carried_over_leave_hours)
            VALUES (?, ?, ?, 50000000, '2026-06-01', '2026-11-30', 16.0, 0.0)
        """, (s_id, self.contract_id, a1_id))

        # Record 2 days (16 hours) used in month 2026-07
        cur.execute("""
            INSERT INTO monthly_attendance_summary (staff_id, month, standard_days, actual_days, paid_leave_days, ot_converted_hours, daily_rate, total_amount, locked)
            VALUES (?, '2026-07', 22, 20, 2.0, 0, 2272727, 50000000, 1)
        """, (s_id,))

        # 3. Annex 2: Future period starting 2026-12-01 with 5 days (40 hours) leave
        cur.execute("""
            INSERT INTO contract_annexes (contract_id, annex_name, start_date, end_date, is_active)
            VALUES (?, 'Phụ lục Tương Lai', '2026-12-01', '2027-05-31', 1)
        """, (self.contract_id,))
        a2_id = cur.lastrowid

        cur.execute("""
            INSERT INTO contract_staff_links (staff_id, contract_id, annex_id, monthly_rate, joining_date, tentative_leaving_date, paid_leave_total_hours, carried_over_leave_hours)
            VALUES (?, ?, ?, 55000000, '2026-12-01', '2027-05-31', 40.0, 0.0)
        """, (s_id, self.contract_id, a2_id))
        self.conn.commit()

        # 4. Check leave status in current month 2026-11:
        # Active budget must ONLY be Annex 1's budget (16h), and remaining must be 0h (0 days)
        st_nov = common.get_staff_leave_status(self.conn, s_id, as_of_month="2026-11")
        self.assertEqual(st_nov["active_budget_hours"], 16.0)
        self.assertEqual(st_nov["active_used_hours"], 16.0)
        self.assertEqual(st_nov["active_remaining_hours"], 0.0)
        # Total contract leave across all signed annexes includes future annex (16 + 40 = 56h)
        self.assertEqual(st_nov["contract_total_hours"], 56.0)

        # 5. Attempting to use even 1 day (8 hours) in 2026-11 must be blocked
        post_att = urllib.parse.urlencode([
            ("month", "2026-11"),
            ("staff_ids", str(s_id)),
            (f"pl_{s_id}_2026-11", "1.0"),
            (f"std_{s_id}_2026-11", "22"),
            (f"act_{s_id}_2026-11", "21.0"),
            (f"ot_{s_id}_2026-11", "0"),
            (f"rate_{s_id}_2026-11", "2272727"),
            (f"tot_{s_id}_2026-11", "50000000")
        ]).encode("utf-8")
        handler_nov = StubHandler("/attendance/monthly/save", "POST", body=post_att, headers={"Content-Length": str(len(post_att)), "Content-Type": "application/x-www-form-urlencoded"})
        attendance.handle_attendance_monthly_save_post(handler_nov)
        self.assertIn("exceeds remaining balance", handler_nov.wfile.getvalue().decode("utf-8", errors="ignore"))

        # 6. Check leave status in future month 2026-12 (when Annex 2 becomes active):
        # Active budget must now be Annex 2's budget (40h = 5 days)
        st_dec = common.get_staff_leave_status(self.conn, s_id, as_of_month="2026-12")
        self.assertEqual(st_dec["active_budget_hours"], 40.0)
        self.assertEqual(st_dec["active_used_hours"], 0.0)
        self.assertEqual(st_dec["active_remaining_hours"], 40.0)

        # 7. Taking 3.0 days (24 hours) in 2026-12 succeeds
        cur.execute("""
            INSERT INTO monthly_attendance_summary (staff_id, month, standard_days, actual_days, paid_leave_days, ot_converted_hours, daily_rate, total_amount, locked)
            VALUES (?, '2026-12', 22, 22, 0.0, 0, 2500000, 55000000, 0)
        """, (s_id,))
        self.conn.commit()

        post_dec = urllib.parse.urlencode([
            ("month", "2026-12"),
            ("staff_ids", str(s_id)),
            (f"pl_{s_id}_2026-12", "3.0"),
            (f"std_{s_id}_2026-12", "22"),
            (f"act_{s_id}_2026-12", "19.0"),
            (f"ot_{s_id}_2026-12", "0"),
            (f"rate_{s_id}_2026-12", "2500000"),
            (f"tot_{s_id}_2026-12", "55000000")
        ]).encode("utf-8")
        handler_dec = StubHandler("/attendance/monthly/save", "POST", body=post_dec, headers={"Content-Length": str(len(post_dec)), "Content-Type": "application/x-www-form-urlencoded"})
        attendance.handle_attendance_monthly_save_post(handler_dec)
        self.assertEqual(handler_dec.response_status, 302)

        # After saving, remaining in Annex 2 is 40 - 24 = 16h (2 days)
        st_dec_after = common.get_staff_leave_status(self.conn, s_id, as_of_month="2026-12")
        self.assertEqual(st_dec_after["active_used_hours"], 24.0)
        self.assertEqual(st_dec_after["active_remaining_hours"], 16.0)

    def test_get_staff_previous_unused_leave_multiple_prior_annexes(self):
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO contract_staff (vendor_id, full_name_vi, position, status, paid_leave_total_hours, paid_leave_used_hours)
            VALUES (?, 'Trần Lịch Sử', 'Tester', 'active', 32.0, 0.0)
        """, (self.seller_id,))
        s_id = cur.lastrowid

        # Annex 1: 2025-01-01 to 2025-06-30 with 16h leave, 0 used -> 16h unused
        cur.execute("INSERT INTO contract_annexes (contract_id, annex_name, start_date, end_date) VALUES (?, 'PL 2025-H1', '2025-01-01', '2025-06-30')", (self.contract_id,))
        a1_id = cur.lastrowid
        cur.execute("INSERT INTO contract_staff_links (staff_id, contract_id, annex_id, joining_date, tentative_leaving_date, paid_leave_total_hours) VALUES (?, ?, ?, '2025-01-01', '2025-06-30', 16.0)", (s_id, self.contract_id, a1_id))

        # Annex 2: 2025-07-01 to 2025-12-31 with 16h leave + 8h carried -> 24h budget. Used 12h in month 2025-09 -> 12h unused
        cur.execute("INSERT INTO contract_annexes (contract_id, annex_name, start_date, end_date) VALUES (?, 'PL 2025-H2', '2025-07-01', '2025-12-31')", (self.contract_id,))
        a2_id = cur.lastrowid
        cur.execute("INSERT INTO contract_staff_links (staff_id, contract_id, annex_id, joining_date, tentative_leaving_date, paid_leave_total_hours, carried_over_leave_hours) VALUES (?, ?, ?, '2025-07-01', '2025-12-31', 16.0, 8.0)", (s_id, self.contract_id, a2_id))
        cur.execute("INSERT INTO monthly_attendance_summary (staff_id, month, standard_days, actual_days, paid_leave_days, daily_rate, total_amount, locked) VALUES (?, '2025-09', 22, 20.5, 1.5, 2000000, 44000000, 1)", (s_id,))
        self.conn.commit()

        # When creating Annex 3 starting 2026-01-01, get_staff_previous_unused_leave must find Annex 2 (the immediately preceding one)
        unused_h, prev_link = common.get_staff_previous_unused_leave(self.conn, s_id, joining_date="2026-01-01")
        self.assertEqual(prev_link["annex_name"], "PL 2025-H2")
        self.assertEqual(unused_h, 12.0)

    def test_inactive_staff_leave_status_handling(self):
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO contract_staff (vendor_id, full_name_vi, position, status, paid_leave_total_hours, paid_leave_used_hours)
            VALUES (?, 'Nguyễn Đã Nghỉ', 'BA', 'inactive', 24.0, 16.0)
        """, (self.seller_id,))
        s_id = cur.lastrowid
        self.conn.commit()

        st = common.get_staff_leave_status(self.conn, s_id)
        self.assertEqual(st["contract_total_hours"], 24.0)
        self.assertEqual(st["active_remaining_hours"], 8.0)


# ==================== 5. Test Invoices ====================
class TestInvoices(BaseTestCase):
    def test_normalization(self):
        self.assertEqual(invoices.norm_text("  Nguyễn   Văn   An  "), "nguyễn văn an")
        self.assertEqual(invoices.norm_tax(" 0102-135 934 "), "0102-135934")

    def test_match_party(self):
        vendor_set = {("fpt software", "0102135934", "duy tân")}
        
        # Perfect match
        self.assertTrue(invoices.match_party("FPT Software", "0102135934", "Duy Tân", vendor_set)[0])
        # Mismatch
        self.assertFalse(invoices.match_party("FPT Software", "000000", "Duy Tân", vendor_set)[0])

    def test_parse_xml_bytes(self):
        xml_data = """<?xml version="1.0" encoding="UTF-8"?>
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
                <DChi>Hà Nội</DChi>
              </NBan>
              <NMua>
                <Ten>NGÂN HÀNG MIZUHO</Ten>
                <MST>0100234567</MST>
                <DChi>Hà Nội</DChi>
              </NMua>
              <TToan>
                <TgTCThue>1000</TgTCThue>
                <TgTThue>100</TgTThue>
                <TgTTTBSo>1100</TgTTTBSo>
              </TToan>
            </NDHDon>
          </DLHDon>
        </HDon>
        """.encode("utf-8")
        
        invoice, tax_lines = invoices.parse_xml_bytes(xml_data, "test.xml")
        self.assertEqual(invoice["khhdon"], "1C26TUU")
        self.assertEqual(invoice["shdon"], "0001234")
        self.assertEqual(invoice["seller_mst"], "0102135934")

    def test_handle_new_invoice_post_paste_method(self):
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
        <HDon>
          <DLHDon>
            <TTChung>
              <KHHDon>1C26TUU</KHHDon>
              <SHDon>0009999</SHDon>
              <NLap>2026-05-31</NLap>
              <DVTTe>VND</DVTTe>
            </TTChung>
            <NDHDon>
              <NBan><Ten>FPT</Ten><MST>0102135934</MST></NBan>
              <NMua><Ten>MIZUHO</Ten><MST>0100234567</MST></NMua>
              <TToan><TgTTTBSo>100</TgTTTBSo></TToan>
            </NDHDon>
          </DLHDon>
        </HDon>
        """
        # Simulate multipart form payload manually
        boundary = "----WebKitFormBoundary123456"
        body = f"""--{boundary}
Content-Disposition: form-data; name="import_type"

paste
--{boundary}
Content-Disposition: form-data; name="xml_content"

{xml_content}
--{boundary}--""".replace("\n", "\r\n").encode("utf-8")

        handler = MockHandler(
            body=body,
            headers={
                "content-type": f"multipart/form-data; boundary={boundary}",
                "content-length": str(len(body))
            }
        )
        
        invoices.handle_new_invoice_post(handler)
        
        # Verify db insert (reopen connection to clear cached SQLite transactions)
        self.conn.close()
        self.conn = common.db_connect()
        inserted = self.conn.execute("SELECT * FROM invoices WHERE shdon='0009999'").fetchone()
        self.assertIsNotNone(inserted)

    def test_invoice_payroll_reconciliation(self):
        # Extend leaving date so Nguyễn Văn An is active in June 2026
        cur = self.conn.cursor()
        cur.execute("UPDATE contract_staff_links SET tentative_leaving_date = '2026-06-30' WHERE staff_id = ?", (self.staff_id,))
        # 1. Setup mock monthly attendance summary for self.staff_id (Nguyễn Văn An, contract id=self.contract_id)
        # Nguyễn Văn An belongs to contract self.contract_id (framework_no = 'MHB/FPT/2025/001')
        cur.execute("""
            INSERT INTO monthly_attendance_summary (staff_id, month, standard_days, actual_days, paid_leave_days, ot_converted_hours, daily_rate, total_amount, locked)
            VALUES (?, '2026-06', 20.0, 20.0, 0.0, 0.0, 2500000.0, 50000000.0, 0)
        """, (self.staff_id,))
        self.conn.commit()

        # Test 1: Unlocked payroll exists (status should be 'no_payroll' with all_sum = 50000000.0)
        status, locked_sum, all_sum, msg = invoices.check_invoice_payroll_reconciliation(
            self.conn, "MHB/FPT/2025/001", 2026, 6, 50000000.0
        )
        self.assertEqual(status, 'no_payroll')
        self.assertEqual(locked_sum, 0.0)
        self.assertEqual(all_sum, 50000000.0)
        self.assertIn("Found unlocked payroll sum", msg)

        # Test 2: Lock the payroll
        cur.execute("""
            UPDATE monthly_attendance_summary 
            SET locked = 1 
            WHERE staff_id = ? AND month = '2026-06'
        """, (self.staff_id,))
        self.conn.commit()

        # Check reconciliation matching
        status, locked_sum, all_sum, msg = invoices.check_invoice_payroll_reconciliation(
            self.conn, "MHB/FPT/2025/001", 2026, 6, 50000000.0
        )
        self.assertEqual(status, 'ok')
        self.assertEqual(locked_sum, 50000000.0)
        self.assertIn("matches invoice amount exactly", msg)

        # Test 3: Mismatch amount
        status, locked_sum, all_sum, msg = invoices.check_invoice_payroll_reconciliation(
            self.conn, "MHB/FPT/2025/001", 2026, 6, 45000000.0
        )
        self.assertEqual(status, 'mismatch')
        self.assertEqual(locked_sum, 50000000.0)
        self.assertIn("does not match invoice amount", msg)

        # Test 4: Invalid contract_no
        status, locked_sum, all_sum, msg = invoices.check_invoice_payroll_reconciliation(
            self.conn, "INVALID-CONTRACT-NO", 2026, 6, 50000000.0
        )
        self.assertEqual(status, 'no_contract')
        self.assertEqual(locked_sum, 0.0)
        self.assertIn("No matching contract or annex found", msg)

    def test_mgs_details_and_button(self):
        # 1. Thêm mock invoice vào DB
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO invoices (
                service_year, service_month, service_day, contract_no,
                khhdon, shdon, nlap, dvtte,
                seller_name, seller_mst, seller_address,
                buyer_name, buyer_mst, buyer_address,
                tg_tttbso
            ) VALUES (2026, 6, 30, 'MHB/FPT/2025/001', '1C26TUU', '0001234', '2026-06-30', 'VND',
                      'CÔNG TY TNHH PHẦN MỀM FPT', '0102135934', 'Duy Tân',
                      'NGÂN HÀNG MIZUHO', '0100234567', '16 Phan Chu Trinh', 50000000.0)
        """)
        invoice_id = cur.lastrowid
        
        # Thêm Reference
        cur.execute("""
            INSERT INTO contract_references (contract_id, annex_id, month, reference_number)
            VALUES (?, ?, '2026-06', 'REF-MGS-123')
        """, (self.contract_id, self.annex_id))
        self.conn.commit()
        
        # 2. Lấy invoice ra
        inv = self.conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
        ref, tax, comp, amt, curr, num, sname, mmyyyy = invoices.get_mgs_details(self.conn, inv)
        
        self.assertEqual(ref, "REF-MGS-123")
        self.assertEqual(tax, "0102135934") 
        self.assertEqual(comp, "CÔNG TY TNHH PHẦN MỀM FPT")
        self.assertEqual(curr, "VND")
        self.assertEqual(num, "0001234")

        # Test get_mgs_data_dict contract format: "framework_no-annex_name"
        mgs_data = invoices.get_mgs_data_dict(self.conn, inv)
        self.assertEqual(mgs_data["contract_no"], "MHB/FPT/2025/001-Phụ lục 1")
        
        # 3. Test HTML page list contains To MGS button
        html_list = invoices.page_invoices_list({}, return_to="/")
        self.assertIn("To MGS", html_list)
        
        # 4. Test HTML page detail contains To MGS button
        html_detail = invoices.page_invoice_detail(invoice_id)
        self.assertIn("To MGS", html_detail)

    def test_force_match(self):
        cur = self.conn.cursor()
        cur.execute("UPDATE contract_staff_links SET tentative_leaving_date = '2026-06-30' WHERE staff_id = 1")
        cur.execute("""
            INSERT INTO invoices (
                service_year, service_month, service_day, contract_no,
                khhdon, shdon, nlap, dvtte,
                seller_name, seller_mst, seller_address,
                buyer_name, buyer_mst, buyer_address,
                tg_tttbso
            ) VALUES (2026, 6, 30, 'MHB/FPT/2025/001', '1C26TUU', '0005555', '2026-06-30', 'VND',
                      'CÔNG TY TNHH PHẦN MỀM FPT', '0102135934', 'Duy Tân',
                      'NGÂN HÀNG MIZUHO', '0100234567', '16 Phan Chu Trinh', 50000000.0)
        """)
        invoice_id = cur.lastrowid
        self.conn.commit()

        # By default it is mismatch/no_payroll
        html_list = invoices.page_invoices_list({}, return_to="/")
        self.assertIn("No payroll", html_list)

        # Force Match via POST handler
        body = f"id={invoice_id}&value=1&return_to=/".encode()
        handler = MockHandler(body=body, headers={"content-length": str(len(body))})
        invoices.handle_force_match_post(handler)

        self.assertEqual(handler.response_status, 302)

        # Refresh connection
        self.conn.close()
        self.conn = common.db_connect()

        # Check in DB
        row = self.conn.execute("SELECT force_match FROM invoices WHERE id=?", (invoice_id,)).fetchone()
        self.assertEqual(row["force_match"], 1)

        # Verify page list displays "✓ Force Matched"
        html_list_after = invoices.page_invoices_list({}, return_to="/")
        self.assertIn("✓ Force Matched", html_list_after)


# ==================== 6. Test Time Attendance ====================
class TestAttendance(BaseTestCase):
    def test_parse_attendance_csv(self):
        csv_data = """Name,Timestamp
        Nguyễn Văn An,2026-06-01 07:55:00
        Nguyễn Văn An,2026-06-01 17:35:00
        """.encode("utf-8")
        
        records = attendance.parse_attendance_csv(csv_data)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0][0], "Nguyễn Văn An")
        self.assertEqual(records[0][1], "2026-06-01 07:55:00")

    def test_parse_attendance_csv_new_format(self):
        csv_data = """Date,Door,Device ID,Device,User Group,User,Event
2026-05-29 17:36:26,,538218377,MO 6FL MAIN DOOR - OUT,OSMale,378(Can Duy Hung),1:N authentication succeeded (Face)
2026-05-29 16:34:47,,538218382,MO 6FL MAIN DOOR IN 1,OSMale,378(Can Duy Hung),1:N authentication succeeded (Face)
""".encode("utf-8")
        records = attendance.parse_attendance_csv(csv_data)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0][0], "Can Duy Hung")
        self.assertEqual(records[0][1], "2026-05-29 17:36:26")

    def test_remove_accents(self):
        self.assertEqual(attendance.remove_accents("Nguyễn Văn An"), "nguyen van an")
        self.assertEqual(attendance.remove_accents("Lê Hoàng Long"), "le hoang long")

    def test_parse_dt(self):
        dt = attendance.parse_dt("01/06/2026 08:30:00")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 6)
        self.assertEqual(dt.day, 1)

    def test_page_attendance_totals(self):
        # 1. Thêm dữ liệu chấm công cho Nguyễn Văn An (ID: 1)
        cur = self.conn.cursor()
        # Extend leaving date so he is active in June 2026
        cur.execute("UPDATE contract_staff_links SET tentative_leaving_date = '2026-06-30' WHERE staff_id = 1")
        cur.execute("""
            INSERT INTO attendance (staff_id, date, work_hours, ot_hours)
            VALUES (1, '2026-06-01', 8.0, 2.0)
        """)
        self.conn.commit()
        
        # 2. Render trang daily attendance tháng 6/2026
        html = attendance.page_attendance({"month": "2026-06"})
        
        # Kiểm tra tiêu đề cột xuất hiện
        self.assertIn("Total Days", html)
        self.assertIn("Total OT", html)
        
        # Kiểm tra tổng số ngày công (8.0 giờ = 1.0 ngày? Hoặc tính theo work_hours. w, ot ở đây là work_hours/ot_hours)
        # Trong page_attendance, ta hiển thị total_work và total_ot dạng .1f trực tiếp (tổng số giờ làm việc thực tế và tổng giờ OT)
        # Vì ta đã chèn work_hours = 8.0 và ot_hours = 2.0, tổng sẽ hiển thị là 8.0 và 2.0.
        self.assertIn("8.0", html)
        self.assertIn("2.0", html)

    def test_monthly_auto_sync_from_daily_logs(self):
        # 1. Tạo summary cũ với actual_days = 2.5
        cur = self.conn.cursor()
        cur.execute("UPDATE contract_staff_links SET tentative_leaving_date = '2026-06-30' WHERE staff_id = ?", (self.staff_id,))
        self.conn.commit()
        cur.execute("""
            INSERT INTO monthly_attendance_summary (
                staff_id, month, standard_days, actual_days, paid_leave_days,
                ot_converted_hours, daily_rate, total_amount, locked
            ) VALUES (?, '2026-06', 22.0, 2.5, 0.0, 2.1, 1600000.0, 4420000.0, 0)
        """, (self.staff_id,))
        
        # 2. Chèn daily logs mới: làm việc 2 ngày (mỗi ngày 8h -> tổng 16.0h), OT 4.0h
        cur.execute("""
            INSERT INTO attendance (staff_id, date, work_hours, ot_hours)
            VALUES (?, '2026-06-01', 8.0, 2.0)
        """, (self.staff_id,))
        cur.execute("""
            INSERT INTO attendance (staff_id, date, work_hours, ot_hours)
            VALUES (?, '2026-06-02', 8.0, 2.0)
        """, (self.staff_id,))
        
        # 3. Lock daily attendance
        cur.execute("""
            INSERT INTO attendance_locks (staff_id, month, locked)
            VALUES (?, '2026-06', 1)
        """, (self.staff_id,))
        self.conn.commit()

        # 4. Trigger page_monthly_attendance
        attendance.page_monthly_attendance({"month": "2026-06"})

        # 5. Kiểm định DB được cập nhật
        summary = self.conn.execute("SELECT * FROM monthly_attendance_summary WHERE staff_id=? AND month='2026-06'", (self.staff_id,)).fetchone()
        self.assertIsNotNone(summary)
        # 16.0h / 8.0 = 2.0 days
        self.assertEqual(summary["actual_days"], 2.0)
        # 4.0h * 1.5 = 6.0 OT converted hours
        self.assertEqual(summary["ot_converted_hours"], 6.0)

    def test_attendance_calculations_and_save(self):
        # Simulate manual spreadsheet save
        body = b"month=2026-06&w_1_2026-06-01=8.0&ot_1_2026-06-01=1.5"
        handler = MockHandler(body=body, headers={"content-length": str(len(body))})
        attendance.handle_attendance_save_post(handler)
        
        # Verify db save
        saved = self.conn.execute("SELECT work_hours, ot_hours FROM attendance WHERE staff_id=1 AND date='2026-06-01'").fetchone()
        self.assertIsNotNone(saved)
        self.assertEqual(saved["work_hours"], 8.0)
        self.assertEqual(saved["ot_hours"], 1.5)

    def test_attendance_lock_unlock(self):
        # 1. Test locking
        handler_lock = MockHandler(path=f"/attendance/lock?staff_id={self.staff_id}&month=2026-06")
        attendance.handle_attendance_lock_get(handler_lock)
        self.assertEqual(handler_lock.response_status, 302)

        # Verify DB lock status
        locked = self.conn.execute("SELECT locked FROM attendance_locks WHERE staff_id=? AND month=?", (self.staff_id, "2026-06")).fetchone()
        self.assertIsNotNone(locked)
        self.assertEqual(locked["locked"], 1)

        # 2. Test that manual save ignores updates for locked staff
        body = b"month=2026-06&w_1_2026-06-01=5.0&ot_1_2026-06-01=2.0"
        handler_save = MockHandler(body=body, headers={"content-length": str(len(body))})
        attendance.handle_attendance_save_post(handler_save)

        # The work_hours / ot_hours should NOT be updated to 5.0 / 2.0 (it should be 8.0 / 1.5 from previous setup or empty)
        # Let's verify it did NOT change (in this clean DB setup, it remains empty or unchanged)
        saved = self.conn.execute("SELECT work_hours, ot_hours FROM attendance WHERE staff_id=1 AND date='2026-06-01'").fetchone()
        # Since it was never inserted, it should still be None or 0.0, definitely not 5.0
        if saved:
            self.assertNotEqual(saved["work_hours"], 5.0)

        # 3. Test unlocking
        handler_unlock = MockHandler(path=f"/attendance/unlock?staff_id={self.staff_id}&month=2026-06")
        attendance.handle_attendance_unlock_get(handler_unlock)
        self.assertEqual(handler_unlock.response_status, 302)

        # Verify DB lock status is updated
        unlocked = self.conn.execute("SELECT locked FROM attendance_locks WHERE staff_id=? AND month=?", (self.staff_id, "2026-06")).fetchone()
        self.assertEqual(unlocked["locked"], 0)

    def test_monthly_attendance_calculations_and_save(self):
        cur = self.conn.cursor()
        cur.execute("UPDATE contract_staff_links SET tentative_leaving_date = '2026-06-30' WHERE staff_id = ?", (self.staff_id,))
        self.conn.commit()
        # 1. Lock attendance first so they appear in monthly summary
        handler_lock = MockHandler(path=f"/attendance/lock?staff_id={self.staff_id}&month=2026-06")
        attendance.handle_attendance_lock_get(handler_lock)

        # 2. Render monthly attendance summary
        html = attendance.page_monthly_attendance({"month": "2026-06"})
        self.assertIn("Nguyễn Văn An", html)
        self.assertIn("Monthly Payroll", html)

        # 3. Save monthly summary updates
        body = f"month=2026-06&std_{self.staff_id}=20.0&pl_{self.staff_id}=1.0&ot_{self.staff_id}=10.0".encode()
        handler_save = MockHandler(body=body, headers={"content-length": str(len(body))})
        attendance.handle_attendance_monthly_save_post(handler_save)
        self.assertEqual(handler_save.response_status, 302)

        # Re-connect to database to verify saved monthly summary
        self.conn.close()
        self.conn = common.db_connect()
        summary = self.conn.execute("SELECT * FROM monthly_attendance_summary WHERE staff_id=? AND month=?", (self.staff_id, "2026-06")).fetchone()
        self.assertIsNotNone(summary)
        self.assertEqual(summary["standard_days"], 20.0)
        self.assertEqual(summary["paid_leave_days"], 1.0)
        self.assertEqual(summary["ot_converted_hours"], 10.0)

        # 4. Test validation error (leave days exceeded remaining annual leave)
        # Note: self.staff_id Nguyễn Văn An has paid_leave_total_hours=12.0 and used=4.0 -> remaining=8.0 hours = 1.0 day
        # Saving paid_leave_days = 2.0 (16.0 hours) should trigger validation error
        body_err = f"month=2026-06&std_{self.staff_id}=20.0&pl_{self.staff_id}=2.0&ot_{self.staff_id}=10.0".encode()
        handler_err = MockHandler(body=body_err, headers={"content-length": str(len(body_err))})
        attendance.handle_attendance_monthly_save_post(handler_err)
        # It should return error page (200 status with error HTML output, not redirect 302!)
        self.assertEqual(handler_err.response_status, 200)
        self.assertIn("exceeds remaining balance", handler_err.get_output_text())

        # 5. Test locking monthly summary
        handler_m_lock = MockHandler(path=f"/attendance/monthly/lock?staff_id={self.staff_id}&month=2026-06")
        attendance.handle_attendance_monthly_lock_get(handler_m_lock)
        self.assertEqual(handler_m_lock.response_status, 302)

        # Verify locked in DB
        self.conn.close()
        self.conn = common.db_connect()
        summary_locked = self.conn.execute("SELECT locked FROM monthly_attendance_summary WHERE staff_id=? AND month=?", (self.staff_id, "2026-06")).fetchone()
        self.assertEqual(summary_locked["locked"], 1)

        # 6. Test that updates are ignored for locked monthly summary
        body_ignored = f"month=2026-06&std_{self.staff_id}=15.0&pl_{self.staff_id}=0.0&ot_{self.staff_id}=0.0".encode()
        handler_ignored = MockHandler(body=body_ignored, headers={"content-length": str(len(body_ignored))})
        attendance.handle_attendance_monthly_save_post(handler_ignored)
        self.assertEqual(handler_ignored.response_status, 302)

        # Standard days should still be 20.0, NOT 15.0!
        self.conn.close()
        self.conn = common.db_connect()
        summary_check = self.conn.execute("SELECT standard_days FROM monthly_attendance_summary WHERE staff_id=? AND month=?", (self.staff_id, "2026-06")).fetchone()
        self.assertEqual(summary_check["standard_days"], 20.0)

        # 7. Test unlocking monthly summary
        handler_m_unlock = MockHandler(path=f"/attendance/monthly/unlock?staff_id={self.staff_id}&month=2026-06")
        attendance.handle_attendance_monthly_unlock_get(handler_m_unlock)
        self.assertEqual(handler_m_unlock.response_status, 302)

        # Verify unlocked in DB
        self.conn.close()
        self.conn = common.db_connect()
        summary_unlocked = self.conn.execute("SELECT locked FROM monthly_attendance_summary WHERE staff_id=? AND month=?", (self.staff_id, "2026-06")).fetchone()
        self.assertEqual(summary_unlocked["locked"], 0)

        # 8. Test lock monthly payroll when daily attendance is NOT locked
        # Let's unlock daily attendance first
        handler_daily_unlock = MockHandler(path=f"/attendance/unlock?staff_id={self.staff_id}&month=2026-06")
        attendance.handle_attendance_unlock_get(handler_daily_unlock)
        self.assertEqual(handler_daily_unlock.response_status, 302)

        # Now try to lock monthly payroll (should fail and render error)
        handler_m_lock_fail = MockHandler(path=f"/attendance/monthly/lock?staff_id={self.staff_id}&month=2026-06")
        attendance.handle_attendance_monthly_lock_get(handler_m_lock_fail)
        self.assertEqual(handler_m_lock_fail.response_status, 200) # Renders error HTML page
        self.assertIn("Cannot lock monthly payroll because daily attendance is not locked", handler_m_lock_fail.get_output_text())

        # 9. Test unlock daily attendance when monthly payroll is locked
        # Lock daily attendance first
        handler_daily_lock = MockHandler(path=f"/attendance/lock?staff_id={self.staff_id}&month=2026-06")
        attendance.handle_attendance_lock_get(handler_daily_lock)
        # Lock monthly payroll
        handler_m_lock_ok = MockHandler(path=f"/attendance/monthly/lock?staff_id={self.staff_id}&month=2026-06")
        attendance.handle_attendance_monthly_lock_get(handler_m_lock_ok)
        self.assertEqual(handler_m_lock_ok.response_status, 302) # Successfully redirects

        # Now try to unlock daily attendance (should fail)
        handler_daily_unlock_fail = MockHandler(path=f"/attendance/unlock?staff_id={self.staff_id}&month=2026-06")
        attendance.handle_attendance_unlock_get(handler_daily_unlock_fail)
        self.assertEqual(handler_daily_unlock_fail.response_status, 200) # Renders error HTML page
        self.assertIn("Cannot unlock daily attendance because monthly payroll is locked", handler_daily_unlock_fail.get_output_text())

    def test_monthly_payroll_converted_ot_two_decimals(self):
        cur = self.conn.cursor()
        cur.execute("UPDATE contract_staff_links SET tentative_leaving_date = '2026-06-30' WHERE staff_id = ?", (self.staff_id,))
        self.conn.commit()

        # 1. Lock daily attendance so staff appears in monthly summary
        handler_lock = MockHandler(path=f"/attendance/lock?staff_id={self.staff_id}&month=2026-06")
        attendance.handle_attendance_lock_get(handler_lock)

        # 2. Render monthly payroll and verify step="0.01" is used on ot input
        html = attendance.page_monthly_attendance({"month": "2026-06"})
        self.assertIn('step="0.01"', html)
        self.assertIn(f'name="ot_{self.staff_id}_2026-06"', html)

        # 3. Save calculations with 2 decimal places (10.15)
        body = f"month=2026-06&std_{self.staff_id}=20.0&pl_{self.staff_id}=1.0&ot_{self.staff_id}=10.15".encode()
        handler_save = MockHandler(body=body, headers={"content-length": str(len(body))})
        attendance.handle_attendance_monthly_save_post(handler_save)
        self.assertEqual(handler_save.response_status, 302)

        # 4. Check DB value
        self.conn.close()
        self.conn = common.db_connect()
        summary = self.conn.execute("SELECT * FROM monthly_attendance_summary WHERE staff_id=? AND month=?", (self.staff_id, "2026-06")).fetchone()
        self.assertIsNotNone(summary)
        self.assertEqual(summary["ot_converted_hours"], 10.15)

        # 5. Render page again and verify 10.15 is preserved and displayed
        html_after = attendance.page_monthly_attendance({"month": "2026-06"})
        self.assertIn('value="10.15"', html_after)

    def test_handle_attendance_import_post_success(self):
        # Save original function
        orig = attendance.parse_multipart_attendance
        # Mock it to return our test file upload data
        attendance.parse_multipart_attendance = lambda h: {
            "month": ["2026-06"],
            "vendor_id": [str(self.seller_id)],
            "contract_id": [str(self.contract_id)],
            "q": [""],
            f"file_{self.staff_id}": [{"filename": "att.csv", "content": b"Name,Timestamp\nNguyen Van An,2026-06-01 07:55:00\nNguyen Van An,2026-06-01 17:35:00\n"}]
        }
        try:
            handler = MockHandler()
            attendance.handle_attendance_import_post(handler)
            self.assertEqual(handler.response_status, 200)
            self.assertIn("Successfully imported 1 attendance records", handler.get_output_text())
        finally:
            # Restore original function
            attendance.parse_multipart_attendance = orig


    def test_attendance_clear(self):
        # Insert a daily attendance record first
        conn = attendance.db_connect()
        try:
            conn.execute("""
                INSERT INTO attendance (staff_id, date, work_hours, ot_hours)
                VALUES (?, '2026-06-01', 8.0, 2.0)
                ON CONFLICT(staff_id, date) DO UPDATE SET work_hours=8.0, ot_hours=2.0
            """, (self.staff_id,))
            conn.commit()
            
            # Verify it exists
            r = conn.execute("SELECT 1 FROM attendance WHERE staff_id=? AND date='2026-06-01'", (self.staff_id,)).fetchone()
            self.assertIsNotNone(r)
            
            # Invoke clear GET route
            handler = MockHandler()
            handler.path = f"/attendance/clear?staff_id={self.staff_id}&month=2026-06"
            attendance.handle_attendance_clear_get(handler)
            
            # Verify records are deleted
            r_deleted = conn.execute("SELECT 1 FROM attendance WHERE staff_id=? AND date='2026-06-01'", (self.staff_id,)).fetchone()
            self.assertIsNone(r_deleted)
        finally:
            conn.close()

    def test_attendance_manual_totals(self):
        # Extend leaving date so Nguyễn Văn An is active in June 2026
        conn = attendance.db_connect()
        try:
            conn.execute("UPDATE contract_staff_links SET tentative_leaving_date = '2026-06-30' WHERE staff_id = ?", (self.staff_id,))
            conn.commit()
        finally:
            conn.close()

        # Mock save post with manual totals
        body = f"month=2026-06&total_work_{self.staff_id}=164.0&total_ot_{self.staff_id}=10.0".encode('utf-8')
        handler = MockHandler()
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        
        attendance.handle_attendance_save_post(handler)
        
        # Verify manual work and ot hours are saved in monthly_attendance_summary
        conn = attendance.db_connect()
        try:
            row = conn.execute("""
                SELECT manual_work_hours, manual_ot_hours, total_amount, actual_days, ot_converted_hours FROM monthly_attendance_summary
                WHERE staff_id=? AND month='2026-06'
            """, (self.staff_id,)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["manual_work_hours"], 164.0)
            self.assertEqual(row["manual_ot_hours"], 10.0)
            self.assertEqual(row["actual_days"], 164.0 / 8.0)
            self.assertEqual(row["ot_converted_hours"], 15.0)

            # 1. Lock daily attendance so it appears in monthly page
            cur = conn.cursor()
            cur.execute("INSERT OR REPLACE INTO attendance_locks (staff_id, month, locked) VALUES (?, '2026-06', 1)", (self.staff_id,))
            conn.commit()

            # 2. Verify display in monthly page
            html = attendance.page_monthly_attendance({"month": "2026-06"})
            self.assertIn("Work: 164.00h", html)
            self.assertIn("OT: 10.00h", html)

            # 3. Verify CSV Export contains overridden values and modified headers
            class StubHandler:
                def __init__(self, path, method="GET"):
                    self.path = path
                    self.method = method
                    self.response_headers = {}
                    self.response_status = 200
                    self.wfile = io.BytesIO()
                def send_response(self, status):
                    self.response_status = status
                def send_header(self, name, value):
                    self.response_headers[name.lower()] = value
                def end_headers(self):
                    pass

            csv_handler = StubHandler("/attendance/monthly/export?month=2026-06", "GET")
            attendance.handle_attendance_monthly_export_get(csv_handler)
            csv_text = csv_handler.wfile.getvalue().decode("utf-8")
            self.assertIn("Work Hours,OT Hours", csv_text)
            self.assertIn("164.00,10.00", csv_text)
        finally:
            conn.close()

    def test_leave_fractional_days_and_decimal_precision(self):
        import urllib.parse
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO contract_staff (vendor_id, full_name_vi, position, status, paid_leave_total_hours, paid_leave_used_hours)
            VALUES (?, 'Hoàng Phân Số', 'Developer', 'active', 24.0, 0.0)
        """, (self.seller_id,))
        s_id = cur.lastrowid

        cur.execute("INSERT INTO contract_annexes (contract_id, annex_name, start_date, end_date) VALUES (?, 'PL 2026-Test', '2026-01-01', '2026-12-31')", (self.contract_id,))
        a_id = cur.lastrowid
        cur.execute("INSERT INTO contract_staff_links (staff_id, contract_id, annex_id, joining_date, tentative_leaving_date, paid_leave_total_hours) VALUES (?, ?, ?, '2026-01-01', '2026-12-31', 24.0)", (s_id, self.contract_id, a_id))
        cur.execute("""
            INSERT INTO monthly_attendance_summary (staff_id, month, standard_days, actual_days, paid_leave_days, ot_converted_hours, daily_rate, total_amount, locked)
            VALUES (?, '2026-04', 22, 22, 0.0, 0, 2000000, 44000000, 0)
        """, (s_id,))
        self.conn.commit()

        post_data = urllib.parse.urlencode([
            ("month", "2026-04"),
            ("staff_ids", str(s_id)),
            (f"pl_{s_id}_2026-04", "1.5"),
            (f"std_{s_id}_2026-04", "22"),
            (f"act_{s_id}_2026-04", "20.5"),
            (f"ot_{s_id}_2026-04", "0"),
            (f"rate_{s_id}_2026-04", "2000000"),
            (f"tot_{s_id}_2026-04", "44000000")
        ]).encode("utf-8")
        h = StubHandler("/attendance/monthly/save", "POST", body=post_data, headers={"Content-Length": str(len(post_data)), "Content-Type": "application/x-www-form-urlencoded"})
        attendance.handle_attendance_monthly_save_post(h)
        self.assertEqual(h.response_status, 302)

        row = self.conn.execute("SELECT paid_leave_days FROM monthly_attendance_summary WHERE staff_id = ? AND month = '2026-04'", (s_id,)).fetchone()
        self.assertEqual(row["paid_leave_days"], 1.5)

        st = common.get_staff_leave_status(self.conn, s_id, as_of_month="2026-04")
        self.assertEqual(st["active_used_hours"], 12.0)
        self.assertEqual(st["active_remaining_hours"], 12.0)


# ==================== 7. Test Web Routes routing ====================
class TestServerRoutes(BaseTestCase):
    def test_do_GET_routes(self):
        routes = [
            ("/", "Invoices List"),
            ("/dashboard", "Dashboard"),
            ("/vendors", "Vendor Management"),
            ("/contracts", "Contract Management"),
            ("/staff", "Contract Staff (HR)"),
            ("/staff/shifts", "Staff Work Shifts Settings"),
            ("/attendance", "Time Attendance"),
            ("/attendance/cashout", "Fiscal Year Cash-out Overview"),
            ("/invoice/new", "Import New Invoice"),
            ("/vendor/new", "Add Vendor"),
            (f"/vendor/edit?id={self.seller_id}", "Edit Vendor"),
            (f"/contract/edit?id={self.contract_id}", "Edit Contract"),
            (f"/annex/new?contract_id={self.contract_id}", "Add Annex"),
            (f"/annex/edit?id={self.annex_id}", "Edit Annex #"),
            ("/staff/new", "Add Staff"),
            (f"/staff/edit?id={self.staff_id}", "Edit Staff"),
        ]
        for path, expected_text in routes:
            handler = StubHandler(path, "GET")
            handler.do_GET()
            output = handler.get_output_text()
            self.assertIn(expected_text, output, f"Route {path} failed to return {expected_text}")

    def test_do_POST_routes(self):
        # Test a simple route dispatching for POST
        body = b"id=1"
        handler = StubHandler("/delete-invoice", "POST", headers={"content-length": str(len(body))}, body=body)
        
        # Delete invoice with ID=1 should redirect to /
        handler.do_POST()
        self.assertEqual(handler.response_status, 302)


# ==================== 8. Test New Improvements ====================
class TestNewImprovements(BaseTestCase):
    def test_attendance_save_cell_ajax_success(self):
        # 1. Update work hours using the save-cell endpoint
        body = b'{"staff_id": 1, "date": "2026-06-01", "type": "w", "value": 8.0}'
        handler = StubHandler("/attendance/save-cell", "POST", headers={"content-length": str(len(body)), "content-type": "application/json"}, body=body)
        handler.do_POST()
        
        # Verify JSON response
        output = handler.get_output_text()
        self.assertIn('"status": "ok"', output)
        
        # Verify SQLite DB
        saved = self.conn.execute("SELECT work_hours FROM attendance WHERE staff_id=1 AND date='2026-06-01'").fetchone()
        self.assertIsNotNone(saved)
        self.assertEqual(saved["work_hours"], 8.0)

    def test_attendance_save_cell_ajax_locked_error(self):
        # Lock attendance first
        cur = self.conn.cursor()
        cur.execute("INSERT INTO attendance_locks (staff_id, month, locked) VALUES (1, '2026-06', 1)")
        self.conn.commit()
        
        # Try to update
        body = b'{"staff_id": 1, "date": "2026-06-01", "type": "w", "value": 8.0}'
        handler = StubHandler("/attendance/save-cell", "POST", headers={"content-length": str(len(body)), "content-type": "application/json"}, body=body)
        handler.do_POST()
        
        # Should return 403 or error JSON
        output = handler.get_output_text()
        self.assertIn('"status": "error"', output)
        self.assertIn("locked", output)

    def test_monthly_payroll_export_csv(self):
        # 1. Setup daily attendance lock so staff appears in monthly summary
        cur = self.conn.cursor()
        cur.execute("UPDATE contract_staff_links SET tentative_leaving_date = '2026-06-30' WHERE staff_id = 1")
        cur.execute("INSERT INTO attendance_locks (staff_id, month, locked) VALUES (1, '2026-06', 1)")
        # Insert a mock summary row
        cur.execute("""
            INSERT INTO monthly_attendance_summary (staff_id, month, standard_days, actual_days, paid_leave_days, ot_converted_hours, daily_rate, total_amount, locked)
            VALUES (1, '2026-06', 20.0, 18.0, 1.0, 3.0, 2000000.0, 38750000.0, 1)
        """)
        self.conn.commit()
        
        # Request CSV Export
        handler = StubHandler("/attendance/monthly/export?month=2026-06", "GET")
        handler.do_GET()
        
        # Verify Response headers
        self.assertEqual(handler.response_headers.get("content-type"), "text/csv; charset=utf-8")
        self.assertIn("attachment", handler.response_headers.get("content-disposition"))
        
        # Verify CSV Content contains BOM and data
        csv_data = handler.wfile.getvalue()
        self.assertTrue(csv_data.startswith(b'\xef\xbb\xbf'))
        
        text = csv_data.decode("utf-8")
        self.assertIn("Staff ID,Full Name,Vendor,Contract No", text)
        self.assertIn("Nguyễn Văn An", text)


# ==================== 9. Test References ====================
class TestReferences(BaseTestCase):
    def test_get_months_between(self):
        # Test valid range
        months = contracts.get_months_between("2025-06-01", "2025-08-31")
        self.assertEqual(months, ["2025-06", "2025-07", "2025-08"])
        
        # Test empty or invalid range
        self.assertEqual(contracts.get_months_between(None, "2025-08-31"), [])
        self.assertEqual(contracts.get_months_between("2025-06-01", "invalid"), [])

    def test_page_contract_references(self):
        # Create a reference first
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO contract_references (contract_id, annex_id, month, reference_number)
            VALUES (?, ?, '2025-06', 'REF-001')
        """, (self.contract_id, self.annex_id))
        self.conn.commit()
        
        html = contracts.page_contract_references()
        self.assertIn("REF-001", html)
        self.assertIn("Framework Contract", html)

    def test_page_contract_references_filters(self):
        # Create a reference first
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO contract_references (contract_id, annex_id, month, reference_number)
            VALUES (?, ?, '2025-06', 'REF-FILTERED-001')
        """, (self.contract_id, self.annex_id))
        self.conn.commit()

        # Test filtering by matching vendor/company
        html = contracts.page_contract_references(vendor_id=str(self.seller_id))
        self.assertIn("REF-FILTERED-001", html)

        # Test filtering by matching contract
        html_c = contracts.page_contract_references(contract_id=str(self.contract_id))
        self.assertIn("REF-FILTERED-001", html_c)

        # Test filtering by matching annex
        html_a = contracts.page_contract_references(annex_id=str(self.annex_id))
        self.assertIn("REF-FILTERED-001", html_a)

        # Test filtering by matching month
        html_m = contracts.page_contract_references(month="2025-06")
        self.assertIn("REF-FILTERED-001", html_m)

        # Test filtering by non-matching month (out of range)
        html_none = contracts.page_contract_references(month="2025-08")
        self.assertNotIn("REF-FILTERED-001", html_none)

        # Test filtering by sent_mgs = "no" (should contain this month since no invoice is sent)
        html_unsent = contracts.page_contract_references(sent_mgs="no")
        self.assertIn("REF-FILTERED-001", html_unsent)

        # Test filtering by sent_mgs = "yes" (should be empty since no invoice has been sent yet)
        html_sent = contracts.page_contract_references(sent_mgs="yes")
        self.assertNotIn("REF-FILTERED-001", html_sent)

    def test_handle_save_reference_ajax_success(self):
        import json
        body = json.dumps({
            "contract_id": self.contract_id,
            "annex_id": 0,
            "month": "2025-07",
            "value": "REF-002"
        }).encode("utf-8")
        
        handler = StubHandler("/contracts/save-reference", "POST", headers={"content-length": str(len(body)), "content-type": "application/json"}, body=body)
        handler.do_POST()
        
        # Verify JSON response
        output = handler.get_output_text()
        self.assertIn('"status": "ok"', output)
        
        # Verify DB
        conn2 = common.db_connect()
        ref = conn2.execute("SELECT reference_number FROM contract_references WHERE contract_id=? AND annex_id=? AND month=?", (self.contract_id, 0, "2025-07")).fetchone()
        conn2.close()
        self.assertIsNotNone(ref)
        self.assertEqual(ref["reference_number"], "REF-002")

    def test_handle_toggle_mgs_sent_ajax_success(self):
        import json
        # Insert a mock invoice
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO invoices (
                service_year, service_month, service_day, contract_no,
                khhdon, shdon, nlap, dvtte,
                seller_name, seller_mst, seller_address,
                buyer_name, buyer_mst, buyer_address,
                tg_tttbso
            ) VALUES (2026, 6, 30, 'MHB/FPT/2025/001', '1C26TUU', '0001234', '2026-06-30', 'VND',
                      'CÔNG TY TNHH PHẦN MỀM FPT', '0102135934', 'Duy Tân',
                      'NGÂN HÀNG MIZUHO', '0100234567', '16 Phan Chu Trinh', 50000000.0)
        """)
        invoice_id = cur.lastrowid
        self.conn.commit()

        body = json.dumps({
            "id": invoice_id,
            "sent": 1
        }).encode("utf-8")
        
        handler = StubHandler("/api/invoice/toggle-mgs-sent", "POST", headers={"content-length": str(len(body)), "content-type": "application/json"}, body=body)
        handler.do_POST()
        
        output = handler.get_output_text()
        self.assertIn('"status": "ok"', output)
        
        # Verify DB
        conn2 = common.db_connect()
        inv = conn2.execute("SELECT sent_to_mgs FROM invoices WHERE id=?", (invoice_id,)).fetchone()
        conn2.close()
        self.assertIsNotNone(inv)
        self.assertEqual(inv["sent_to_mgs"], 1)


# ==================== 10. Test Dashboard ====================
class TestDashboard(BaseTestCase):
    def test_page_dashboard_rendering(self):
        # Insert some test data to cover all parts of dashboard calculations
        cur = self.conn.cursor()
        # Active framework contract expiring in 15 days
        import datetime
        future_date = (datetime.date.today() + datetime.timedelta(days=15)).strftime("%Y-%m-%d")
        cur.execute("""
            INSERT INTO contracts (buyer_vendor_id, seller_vendor_id, framework_no, framework_name, start_date, end_date, is_active)
            VALUES (?, ?, 'MHB/EXPIRING/2026', 'Expiring Framework Contract', '2026-01-01', ?, 1)
        """, (self.buyer_id, self.seller_id, future_date))
        
        # Test invoice with VND
        cur.execute("""
            INSERT INTO invoices (
                service_year, service_month, service_day, contract_no,
                khhdon, shdon, nlap, dvtte,
                seller_name, seller_mst, seller_address,
                buyer_name, buyer_mst, buyer_address,
                tg_tttbso
            ) VALUES (2026, 6, 30, 'MHB/FPT/2025/001', '1C26TUU', '0001235', '2026-06-30', 'VND',
                      'CÔNG TY TNHH PHẦN MỀM FPT', '0102135934', 'Duy Tân',
                      'NGÂN HÀNG MIZUHO', '0100234567', '16 Phan Chu Trinh', 100000000.0)
        """)
        
        # Test invoice with USD
        cur.execute("""
            INSERT INTO invoices (
                service_year, service_month, service_day, contract_no,
                khhdon, shdon, nlap, dvtte,
                seller_name, seller_mst, seller_address,
                buyer_name, buyer_mst, buyer_address,
                tg_tttbso
            ) VALUES (2026, 6, 30, 'MHB/FPT/2025/001', '1C26TUU', '0001236', '2026-06-30', 'USD',
                      'CÔNG TY TNHH PHẦN MỀM FPT', '0102135934', 'Duy Tân',
                      'NGÂN HÀNG MIZUHO', '0100234567', '16 Phan Chu Trinh', 4500.0)
        """)
        
        self.conn.commit()

        # Run page_dashboard via StubHandler
        handler = StubHandler("/dashboard", "GET")
        handler.do_GET()
        output = handler.get_output_text()
        
        # Assertions
        self.assertIn("Dashboard", output)
        self.assertIn("100,000,000", output) # VND formatted
        self.assertIn("4,500.00 USD", output) # USD formatted
        self.assertIn("Active Staff", output)
        self.assertIn("MHB/EXPIRING/2026", output)

    def test_page_dashboard_filtering_and_payroll_trend(self):
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO projects (short_name, full_name, it_outsourcing_budget, is_active)
            VALUES ('DASH-PROJ', 'Dashboard Filter Project', 500000000.0, 1)
        """)
        p_id = cur.lastrowid
        
        cur.execute("""
            INSERT INTO project_staff_assignments (project_id, staff_id, month)
            VALUES (?, ?, '2026-05')
        """, (p_id, self.staff_id))
        
        cur.execute("""
            INSERT INTO monthly_attendance_summary (staff_id, month, standard_days, actual_days, paid_leave_days, ot_converted_hours, daily_rate, total_amount, locked)
            VALUES (?, '2026-05', 21.0, 9.0, 0.0, 7.83, 2857142.85, 28510715.0, 1)
        """, (self.staff_id,))
        self.conn.commit()
        
        handler = StubHandler("/dashboard", "GET")
        handler.do_GET()
        output = handler.get_output_text()
        self.assertIn("VND Payroll Trend (by Month)", output)
        self.assertIn("28,510,715", output)
        self.assertIn("DASH-PROJ", output)
        
        handler_f = StubHandler(f"/dashboard?project_id={p_id}&start_month=2026-01&end_month=2026-12&vendor_id={self.seller_id}", "GET")
        handler_f.do_GET()
        output_f = handler_f.get_output_text()
        self.assertIn("DASH-PROJ", output_f)


# ==================== 11. Test Annex Filters ====================
class TestAnnexFilters(BaseTestCase):
    def test_annex_filter_handling(self):
        # Extend leaving date so Nguyễn Văn An is active in June 2026 for attendance tests
        cur = self.conn.cursor()
        cur.execute("UPDATE contract_staff_links SET tentative_leaving_date = '2026-06-30' WHERE staff_id = ?", (self.staff_id,))
        self.conn.commit()

        # 1. Test GET /staff with annex_id
        handler = StubHandler(f"/staff?annex_id={self.annex_id}", "GET")
        handler.do_GET()
        output = handler.get_output_text()
        self.assertIn("Contract Staff (HR)", output)
        self.assertIn("Nguyễn Văn An", output)

        # Test GET /staff with non-matching annex_id
        handler = StubHandler("/staff?annex_id=999", "GET")
        handler.do_GET()
        output = handler.get_output_text()
        self.assertNotIn("Nguyễn Văn An", output)

        # 2. Test GET /attendance with annex_id
        handler = StubHandler(f"/attendance?month=2026-06&annex_id={self.annex_id}", "GET")
        handler.do_GET()
        output = handler.get_output_text()
        self.assertIn("Nguyễn Văn An", output)

        # Test GET /attendance with non-matching annex_id
        handler = StubHandler("/attendance?month=2026-06&annex_id=999", "GET")
        handler.do_GET()
        output = handler.get_output_text()
        self.assertNotIn("Nguyễn Văn An", output)

        # 3. Test GET /attendance/monthly with annex_id
        # First lock daily attendance so staff appears in monthly summary
        cur = self.conn.cursor()
        cur.execute("INSERT OR REPLACE INTO attendance_locks (staff_id, month, locked) VALUES (?, '2026-06', 1)", (self.staff_id,))
        self.conn.commit()

        handler = StubHandler(f"/attendance/monthly?month=2026-06&annex_id={self.annex_id}", "GET")
        handler.do_GET()
        output = handler.get_output_text()
        self.assertIn("Nguyễn Văn An", output)

        # Test GET /attendance/monthly with non-matching annex_id
        handler = StubHandler("/attendance/monthly?month=2026-06&annex_id=999", "GET")
        handler.do_GET()
        output = handler.get_output_text()
        self.assertNotIn("Nguyễn Văn An", output)

    def test_monthly_multiselect_filters(self):
        cur = self.conn.cursor()
        cur.execute("INSERT OR REPLACE INTO attendance_locks (staff_id, month, locked) VALUES (?, '2026-05', 1)", (self.staff_id,))
        cur.execute("INSERT OR REPLACE INTO attendance_locks (staff_id, month, locked) VALUES (?, '2026-06', 1)", (self.staff_id,))
        self.conn.commit()

        # Multi-month query
        handler = StubHandler(f"/attendance/monthly?month=2026-05&month=2026-06&vendor_id={self.seller_id}", "GET")
        handler.do_GET()
        output = handler.get_output_text()
        self.assertIn("Nguyễn Văn An", output)
        self.assertIn("ms-month", output)
        self.assertIn("ms-vendor", output)
        self.assertIn("ms-contract", output)
        self.assertIn("ms-annex", output)

    def test_daily_attendance_annex_filter_validity_period(self):
        cur = self.conn.cursor()
        # Create 3 annexes:
        # 1. Expired for 2026-11: 2026-01-01 to 2026-05-31 (Expired Annex)
        cur.execute("""
            INSERT INTO contract_annexes (contract_id, annex_name, start_date, end_date, is_active)
            VALUES (?, 'Annex Expired May', '2026-01-01', '2026-05-31', 1)
        """, (self.contract_id,))
        annex_expired = cur.lastrowid

        # 2. Valid for 2026-11: 2026-06-01 to 2026-11-30 (Active Annex)
        cur.execute("""
            INSERT INTO contract_annexes (contract_id, annex_name, start_date, end_date, is_active)
            VALUES (?, 'Annex Active Nov', '2026-06-01', '2026-11-30', 1)
        """, (self.contract_id,))
        annex_active = cur.lastrowid

        # 3. Future for 2026-11: 2026-12-01 to 2027-05-31 (Future Annex)
        cur.execute("""
            INSERT INTO contract_annexes (contract_id, annex_name, start_date, end_date, is_active)
            VALUES (?, 'Annex Future Dec', '2026-12-01', '2027-05-31', 1)
        """, (self.contract_id,))
        annex_future = cur.lastrowid
        self.conn.commit()

        # Load daily attendance for 2026-11
        handler = StubHandler("/attendance?month=2026-11", "GET")
        handler.do_GET()
        output = handler.get_output_text()

        # Check options inside <select id="annex_id"
        self.assertIn("Annex Active Nov", output)
        self.assertNotIn("Annex Expired May", output)
        self.assertNotIn("Annex Future Dec", output)

        # Load daily attendance for 2026-05
        handler_may = StubHandler("/attendance?month=2026-05", "GET")
        handler_may.do_GET()
        output_may = handler_may.get_output_text()
        self.assertIn("Annex Expired May", output_may)
        self.assertNotIn("Annex Active Nov", output_may)
        self.assertNotIn("Annex Future Dec", output_may)

    def test_monthly_attendance_no_duplicate_when_staff_has_multiple_annexes(self):
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO contract_staff (vendor_id, full_name_vi, position, status, paid_leave_total_hours, paid_leave_used_hours)
            VALUES (?, 'Nguyễn Trùng Lặp', 'Tester', 'active', 56.0, 8.0)
        """, (self.seller_id,))
        s_id = cur.lastrowid

        cur.execute("INSERT INTO contract_annexes (contract_id, annex_name, start_date, end_date) VALUES (?, 'Phụ lục Giai đoạn 1', '2026-05-01', '2026-09-30')", (self.contract_id,))
        a1_id = cur.lastrowid
        cur.execute("INSERT INTO contract_staff_links (staff_id, contract_id, annex_id, joining_date, tentative_leaving_date, paid_leave_total_hours) VALUES (?, ?, ?, '2026-05-01', '2026-09-30', 40.0)", (s_id, self.contract_id, a1_id))

        cur.execute("INSERT INTO contract_annexes (contract_id, annex_name, start_date, end_date) VALUES (?, 'Phụ lục Giai đoạn 2', '2026-10-01', '2026-11-30')", (self.contract_id,))
        a2_id = cur.lastrowid
        cur.execute("INSERT INTO contract_staff_links (staff_id, contract_id, annex_id, joining_date, tentative_leaving_date, paid_leave_total_hours, carried_over_leave_hours) VALUES (?, ?, ?, '2026-10-01', '2026-11-30', 16.0, 32.0)", (s_id, self.contract_id, a2_id))

        cur.execute("INSERT OR REPLACE INTO attendance_locks (staff_id, month, locked) VALUES (?, '2026-07', 1)", (s_id,))
        cur.execute("INSERT OR REPLACE INTO attendance_locks (staff_id, month, locked) VALUES (?, '2026-08', 1)", (s_id,))
        self.conn.commit()

        html = attendance.page_monthly_attendance({"month": ["2026-07", "2026-08"], "q": "Nguyễn Trùng Lặp"})
        row_occurrences = html.count('<div style="font-weight:600;">Nguyễn Trùng Lặp</div>')
        self.assertEqual(row_occurrences, 2, f"Expected 2 table rows but got {row_occurrences} (duplicated rows)")


# ==================== 12. Test Improvements ====================
class TestDashboardAndReferencesImprovements(BaseTestCase):
    def test_dashboard_active_staff_filtering(self):
        from datetime import timedelta, date
        today = date.today()
        past_join = (today - timedelta(days=10)).strftime("%Y-%m-%d")
        future_join = (today + timedelta(days=10)).strftime("%Y-%m-%d")
        past_leave = (today - timedelta(days=5)).strftime("%Y-%m-%d")
        future_leave = (today + timedelta(days=10)).strftime("%Y-%m-%d")

        cur = self.conn.cursor()
        # Clean current staff to have a clean count
        cur.execute("DELETE FROM contract_staff")
        cur.execute("DELETE FROM contract_staff_links")
        
        # 1. Active staff (valid today)
        cur.execute("""
            INSERT INTO contract_staff (full_name_vi, vendor_id, ot, status)
            VALUES ('Staff Active 1', ?, 1, 'active')
        """, (self.seller_id,))
        s1_id = cur.lastrowid
        cur.execute("""
            INSERT INTO contract_staff_links (staff_id, contract_id, joining_date, tentative_leaving_date, created_at, updated_at)
            VALUES (?, ?, ?, ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """, (s1_id, self.contract_id, past_join, future_leave))
        
        # 2. Staff active but joining date in the future
        cur.execute("""
            INSERT INTO contract_staff (full_name_vi, vendor_id, ot, status)
            VALUES ('Staff Future', ?, 1, 'active')
        """, (self.seller_id,))
        s_fut_id = cur.lastrowid
        cur.execute("""
            INSERT INTO contract_staff_links (staff_id, contract_id, joining_date, tentative_leaving_date, created_at, updated_at)
            VALUES (?, ?, ?, ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """, (s_fut_id, self.contract_id, future_join, future_leave))
        
        # 3. Staff active but leaving date in the past
        cur.execute("""
            INSERT INTO contract_staff (full_name_vi, vendor_id, ot, status)
            VALUES ('Staff Past Leaving', ?, 1, 'active')
        """, (self.seller_id,))
        s_past_id = cur.lastrowid
        cur.execute("""
            INSERT INTO contract_staff_links (staff_id, contract_id, joining_date, tentative_leaving_date, created_at, updated_at)
            VALUES (?, ?, ?, ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """, (s_past_id, self.contract_id, past_join, past_leave))
        
        # 4. Duplicate staff name (Staff Active 1) with another contract
        cur.execute("""
            INSERT INTO contracts (buyer_vendor_id, seller_vendor_id, framework_no, framework_name, start_date, end_date, is_active)
            VALUES (?, ?, 'MHB/FPT/2026/002', 'Contract 2', '2026-01-01', '2026-12-31', 1)
        """, (self.buyer_id, self.seller_id))
        c2_id = cur.lastrowid
        cur.execute("""
            INSERT INTO contract_staff_links (staff_id, contract_id, joining_date, tentative_leaving_date, created_at, updated_at)
            VALUES (?, ?, ?, ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """, (s1_id, c2_id, past_join, future_leave))
        
        self.conn.commit()
        
        # Run dashboard via StubHandler
        handler = StubHandler("/dashboard", "GET")
        handler.do_GET()
        output = handler.get_output_text()
        
        # Assertions: Count must be exactly 1 unique active staff
        self.assertIn("1 Active Staff", output)

    def test_reference_numbers_highlight_sent_mgs(self):
        cur = self.conn.cursor()
        # Insert a contract with a known framework_no
        cur.execute("""
            INSERT INTO contracts (buyer_vendor_id, seller_vendor_id, framework_no, framework_name, start_date, end_date, is_active)
            VALUES (?, ?, 'MHB/TEST/REF/001', 'Test Ref Contract', '2026-06-01', '2026-06-30', 1)
        """, (self.buyer_id, self.seller_id))
        c_id = cur.lastrowid
        
        # Insert an invoice for that contract and month (June 2026) that is sent to MGS
        cur.execute("""
            INSERT INTO invoices (
                service_year, service_month, service_day, contract_no,
                shdon, nlap, dvtte, seller_name, seller_mst, buyer_name, buyer_mst,
                tg_tttbso, sent_to_mgs
            ) VALUES (2026, 6, 15, 'MHB/TEST/REF/001', '0000001', '2026-06-15', 'VND',
                      'Seller', '12345678', 'Buyer', '87654321', 1000.0, 1)
        """)
        self.conn.commit()
        
        # View page references
        html = contracts.page_contract_references()
        
        # Verify the month 06/2026 has the "(Sent MGS)" badge and the correct styling
        self.assertIn("(Sent MGS)", html)
        self.assertIn("border: 1px solid #10b981; background: #ecfdf5;", html)

    def test_dashboard_annex_alert(self):
        cur = self.conn.cursor()
        
        # Create an annex expiring in 10 days
        import datetime
        future_date = (datetime.date.today() + datetime.timedelta(days=10)).strftime("%Y-%m-%d")
        
        cur.execute("""
            INSERT INTO contracts (buyer_vendor_id, seller_vendor_id, framework_no, framework_name, start_date, end_date, is_active)
            VALUES (?, ?, 'MHB/TEST/ALERT/001', 'Test Alert Contract', '2026-01-01', '2026-12-31', 1)
        """, (self.buyer_id, self.seller_id))
        c_id = cur.lastrowid
        
        cur.execute("""
            INSERT INTO contract_annexes (contract_id, annex_name, start_date, end_date, is_active)
            VALUES (?, 'Annex Expiring Soon', '2026-01-01', ?, 1)
        """, (c_id, future_date))
        self.conn.commit()
        
        # Run dashboard
        handler = StubHandler("/dashboard", "GET")
        handler.do_GET()
        output = handler.get_output_text()
        
        # Assertions
        self.assertIn("MHB/TEST/ALERT/001 - Annex Expiring Soon", output)
        self.assertIn("Contract/Annex alert", output)


# ==================== Test Projects & Assignments ====================
class TestProjects(BaseTestCase):
    def test_page_projects_list(self):
        # Insert a project
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO projects (short_name, full_name, it_outsourcing_budget, os_start_date, os_end_date, is_active)
            VALUES ('TEST-PROJ', 'Test Project Name', 12345.67, '2026-01-01', '2026-12-31', 1)
        """)
        self.conn.commit()

        html = projects.page_projects_list()
        self.assertIn("TEST-PROJ", html)
        self.assertIn("Test Project Name", html)
        self.assertIn("12,345.67 VND", html)
        self.assertIn("/projects/assign?project_id=", html)

    def test_handle_project_create_post(self):
        body = b"short_name=NEW-PROJ&full_name=New+Project+Full+Name&it_outsourcing_budget=54321.00&os_start_date=2026-01-01&os_end_date=2026-12-31"
        handler = MockHandler(body=body, headers={"content-length": str(len(body))})
        projects.handle_project_create_post(handler)
        self.assertEqual(handler.response_status, 302)

        # Verify db insert
        inserted = self.conn.execute("SELECT * FROM projects WHERE short_name='NEW-PROJ'").fetchone()
        self.assertIsNotNone(inserted)
        self.assertEqual(inserted["full_name"], "New Project Full Name")
        self.assertEqual(inserted["it_outsourcing_budget"], 54321.00)

    def test_handle_project_delete_post(self):
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO projects (short_name, full_name, is_active)
            VALUES ('DEL-PROJ', 'To Be Deleted', 1)
        """)
        self.conn.commit()
        p_id = cur.lastrowid

        body = f"id={p_id}".encode()
        handler = MockHandler(body=body, headers={"content-length": str(len(body))})
        projects.handle_project_delete_post(handler)
        self.assertEqual(handler.response_status, 302)

        # Verify inactive
        p = self.conn.execute("SELECT is_active FROM projects WHERE id=?", (p_id,)).fetchone()
        self.assertEqual(p["is_active"], 0)

    def test_staff_assignments_logic(self):
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO projects (short_name, full_name, is_active)
            VALUES ('ASSIGN-PROJ-1', 'Assign Project One', 1)
        """)
        p1_id = cur.lastrowid
        cur.execute("""
            INSERT INTO projects (short_name, full_name, is_active)
            VALUES ('ASSIGN-PROJ-2', 'Assign Project Two', 1)
        """)
        p2_id = cur.lastrowid
        self.conn.commit()

        # In mock data, staff Nguyễn Văn An (self.staff_id) is active from 2025-06-01 to 2026-05-31.
        # So in 2026-05, he is active.
        month_active = "2026-05"
        month_inactive = "2026-06" # out of range (tentative_leaving_date is 2026-05-31)

        # 1. Verify staff Nguyễn Văn An is available in month_active via AJAX
        handler_ajax = MockHandler(path=f"/api/projects/available-staff?months={month_active}")
        projects.handle_available_staff_ajax(handler_ajax)
        self.assertEqual(handler_ajax.response_status, 200)
        import json
        data = json.loads(handler_ajax.get_output_text())
        self.assertTrue(any(s['full_name_vi'] == "Nguyễn Văn An" for s in data))

        # 2. Assign staff to project 1 in month_active
        body = f"project_id={p1_id}&staff_id={self.staff_id}&months={month_active}".encode()
        handler = MockHandler(body=body, headers={"content-length": str(len(body))})
        projects.handle_project_assign_create_post(handler)
        self.assertEqual(handler.response_status, 302)

        # 3. Verify staff is now assigned and NOT in available list anymore
        html_after = projects.page_projects_assign(selected_month=month_active, selected_project_id=p1_id)
        # Should show in the assigned section
        self.assertIn("Nguyễn Văn An", html_after)
        
        # But should NOT show in the available staff dropdown options via AJAX
        handler_ajax_after = MockHandler(path=f"/api/projects/available-staff?months={month_active}")
        projects.handle_available_staff_ajax(handler_ajax_after)
        data_after = json.loads(handler_ajax_after.get_output_text())
        self.assertFalse(any(s['full_name_vi'] == "Nguyễn Văn An" for s in data_after))

        # 4. Attempt to assign the same staff to project 2 in the same month (should fail due to validation)
        body2 = f"project_id={p2_id}&staff_id={self.staff_id}&months={month_active}".encode()
        handler2 = MockHandler(body=body2, headers={"content-length": str(len(body2))})
        projects.handle_project_assign_create_post(handler2)
        # The logic will return a 400 bad request / display page with error message
        self.assertEqual(handler2.response_status, 400)
        self.assertIn("already assigned", handler2.get_output_text())

        # 5. Attempt to assign staff in month_inactive (should fail since staff is inactive in 2026-06)
        body3 = f"project_id={p1_id}&staff_id={self.staff_id}&months={month_inactive}".encode()
        handler3 = MockHandler(body=body3, headers={"content-length": str(len(body3))})
        projects.handle_project_assign_create_post(handler3)
        self.assertEqual(handler3.response_status, 400)
        self.assertIn("not active", handler3.get_output_text())

        # 6. Unassign staff
        assignment = self.conn.execute("SELECT id FROM project_staff_assignments WHERE staff_id=? AND month=?", (self.staff_id, month_active)).fetchone()
        self.assertIsNotNone(assignment)
        
        body_del = f"id={assignment['id']}&month={month_active}".encode()
        handler_del = MockHandler(body=body_del, headers={"content-length": str(len(body_del))})
        projects.handle_project_assign_delete_post(handler_del)
        self.assertEqual(handler_del.response_status, 302)

        # Verify assignment deleted from DB
        deleted = self.conn.execute("SELECT 1 FROM project_staff_assignments WHERE id=?", (assignment['id'],)).fetchone()
        self.assertIsNone(deleted)

    def test_staff_assignments_multi_month(self):
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO projects (short_name, full_name, is_active)
            VALUES ('ASSIGN-PROJ-3', 'Assign Project Three', 1)
        """)
        p3_id = cur.lastrowid
        self.conn.commit()

        # Nguyễn Văn An is active from 2025-06-01 to 2026-05-31
        # Let's test assigning to 2026-04 and 2026-05
        
        # Verify available in both months via AJAX
        handler_ajax = MockHandler(path="/api/projects/available-staff?months=2026-04,2026-05")
        projects.handle_available_staff_ajax(handler_ajax)
        self.assertEqual(handler_ajax.response_status, 200)
        import json
        data = json.loads(handler_ajax.get_output_text())
        self.assertTrue(any(s['full_name_vi'] == "Nguyễn Văn An" for s in data))
        
        # Perform multi-month assignment
        body = f"project_id={p3_id}&staff_id={self.staff_id}&months=2026-04&months=2026-05".encode()
        handler = MockHandler(body=body, headers={"content-length": str(len(body))})
        projects.handle_project_assign_create_post(handler)
        self.assertEqual(handler.response_status, 302)
        
        # Verify assigned in both months in DB
        rows = self.conn.execute("SELECT month FROM project_staff_assignments WHERE staff_id=? AND project_id=?", (self.staff_id, p3_id)).fetchall()
        assigned_months = [r['month'] for r in rows]
        self.assertIn("2026-04", assigned_months)
        self.assertIn("2026-05", assigned_months)
        self.assertEqual(len(assigned_months), 2)

    def test_page_project_edit_payroll(self):
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO projects (short_name, full_name, is_active)
            VALUES ('PAYROLL-PROJ', 'Payroll Project', 1)
        """)
        p_id = cur.lastrowid
        
        cur.execute("""
            INSERT INTO project_staff_assignments (project_id, staff_id, month)
            VALUES (?, ?, '2026-05')
        """, (p_id, self.staff_id))
        
        cur.execute("""
            INSERT INTO monthly_attendance_summary (staff_id, month, standard_days, actual_days, paid_leave_days, ot_converted_hours, daily_rate, total_amount, locked)
            VALUES (?, '2026-05', 21.0, 9.0, 0.0, 7.83, 2857142.85, 28510715.0, 1)
        """, (self.staff_id,))
        
        self.conn.commit()
        
        html = projects.page_project_edit(p_id)
        self.assertIn("Payroll Report by Contract / Annex", html)
        self.assertIn("28,510,715", html)

    def test_locked_payroll_payment_matrix(self):
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO projects (short_name, full_name, os_start_date, os_end_date, is_active)
            VALUES ('LOCKED-PROJ', 'Locked Payment Matrix Project', '2026-01-01', '2026-12-31', 1)
        """)
        p_id = cur.lastrowid
        
        cur.execute("""
            INSERT INTO project_staff_assignments (project_id, staff_id, month)
            VALUES (?, ?, '2026-05')
        """, (p_id, self.staff_id))
        
        cur.execute("""
            INSERT INTO monthly_attendance_summary (staff_id, month, standard_days, actual_days, paid_leave_days, ot_converted_hours, daily_rate, total_amount, locked)
            VALUES (?, '2026-05', 21.0, 21.0, 0.0, 0.0, 1845238.10, 38750000.0, 1)
        """, (self.staff_id,))
        
        self.conn.commit()
        
        html = projects.page_projects_assign(selected_project_id=p_id)
        self.assertIn("Locked Monthly Payroll & Payment Matrix (VND)", html)
        self.assertIn("38,750,000.00", html)

    def test_projects_assign_export_csv(self):
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO projects (short_name, full_name, os_start_date, os_end_date, is_active)
            VALUES ('EXPORT-PROJ', 'Export Project Test', '2026-01-01', '2026-12-31', 1)
        """)
        p_id = cur.lastrowid

        cur.execute("""
            INSERT INTO project_staff_assignments (project_id, staff_id, month)
            VALUES (?, ?, '2026-05')
        """, (p_id, self.staff_id))

        cur.execute("""
            INSERT INTO monthly_attendance_summary (staff_id, month, standard_days, actual_days, paid_leave_days, ot_converted_hours, daily_rate, total_amount, locked)
            VALUES (?, '2026-05', 21.0, 21.0, 0.0, 0.0, 1845238.10, 38750000.0, 1)
        """, (self.staff_id,))

        self.conn.commit()

        handler = StubHandler(f"/projects/assign/export?project_id={p_id}", "GET")
        projects.handle_projects_assign_export_csv(handler)

        self.assertEqual(handler.response_headers.get("content-type"), "text/csv; charset=utf-8")
        csv_bytes = handler.wfile.getvalue()
        self.assertTrue(csv_bytes.startswith(b'\xef\xbb\xbf'))
        csv_text = csv_bytes.decode("utf-8")
        self.assertIn("EXPORT-PROJ", csv_text)
        self.assertIn("Nguyễn Văn An", csv_text)
        self.assertIn("38,750,000.00", csv_text)

    def test_inactive_staff_in_projects_and_attendance(self):
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO projects (short_name, full_name, os_start_date, os_end_date, is_active)
            VALUES ('INACTIVE-PROJ', 'Inactive Staff Project', '2026-01-01', '2026-12-31', 1)
        """)
        p_id = cur.lastrowid

        # Assign staff Nguyễn Văn An to project
        cur.execute("""
            INSERT INTO project_staff_assignments (project_id, staff_id, month)
            VALUES (?, ?, '2026-05')
        """, (p_id, self.staff_id))

        cur.execute("""
            INSERT INTO monthly_attendance_summary (staff_id, month, standard_days, actual_days, paid_leave_days, ot_converted_hours, daily_rate, total_amount, locked)
            VALUES (?, '2026-05', 21.0, 21.0, 0.0, 0.0, 1000000.0, 21000000.0, 1)
        """, (self.staff_id,))

        cur.execute("""
            INSERT INTO attendance_locks (staff_id, month, locked)
            VALUES (?, '2026-05', 1)
        """, (self.staff_id,))

        # Set staff to status = 'inactive'
        cur.execute("UPDATE contract_staff SET status = 'inactive' WHERE id = ?", (self.staff_id,))
        self.conn.commit()

        # 1. Check project assign page displays inactive staff member & their assignment
        html_assign = projects.page_projects_assign(selected_month='2026-05', selected_project_id=p_id)
        self.assertIn("Nguyễn Văn An", html_assign)
        self.assertIn("Inactive", html_assign)

        # 2. Check project detail CSV export includes inactive staff & their locked payment
        handler_csv = StubHandler(f"/projects/assign/export?project_id={p_id}", "GET")
        projects.handle_projects_assign_export_csv(handler_csv)
        csv_text = handler_csv.wfile.getvalue().decode("utf-8")
        self.assertIn("Nguyễn Văn An (Inactive)", csv_text)
        self.assertIn("21,000,000.00", csv_text)

        # 3. Check attendance page displays inactive staff member for that month
        html_att = attendance.page_attendance({"month": "2026-05"})
        self.assertIn("Nguyễn Văn An", html_att)
        self.assertIn("Inactive", html_att)

        # 4. Check locked payroll matrix includes inactive staff member
        html_matrix = attendance.page_monthly_attendance({"month": "2026-05"})
        self.assertIn("Nguyễn Văn An", html_matrix)

    def test_contract_assign_staff_with_leave_and_rates(self):
        import contracts
        import urllib.parse
        cur = self.conn.cursor()
        
        # Check initial paid leave total
        staff = cur.execute("SELECT paid_leave_total_hours FROM contract_staff WHERE id = ?", (self.staff_id,)).fetchone()
        init_leave = staff["paid_leave_total_hours"] or 0.0

        existing_link = cur.execute("SELECT id FROM contract_staff_links WHERE staff_id = ? AND annex_id = ?", (self.staff_id, self.annex_id)).fetchone()
        link_id_val = str(existing_link["id"]) if existing_link else ""

        # Simulate POST request to assign staff to contract annex with rate and paid leave hours
        post_data = urllib.parse.urlencode([
            ("contract_id", str(self.contract_id)),
            ("annex_id", str(self.annex_id)),
            ("link_id", link_id_val),
            ("staff_id", str(self.staff_id)),
            ("joining_date", "2026-06-01"),
            ("tentative_leaving_date", "2026-12-31"),
            ("monthly_rate", "55000000"),
            ("manday_rate", ""),
            ("paid_leave_total_hours", "16.0")
        ]).encode("utf-8")

        handler = StubHandler(
            "/contract/assign-staff/save",
            "POST",
            headers={"Content-Type": "application/x-www-form-urlencoded", "Content-Length": str(len(post_data))},
            body=post_data
        )
        contracts.handle_contract_assign_staff_save_post(handler)

        self.assertEqual(handler.response_status, 302)

        # Verify staff link saved rate, dates, and paid leave hours
        link = cur.execute("SELECT * FROM contract_staff_links WHERE staff_id = ? AND annex_id = ?", (self.staff_id, self.annex_id)).fetchone()
        self.assertIsNotNone(link)
        self.assertEqual(link["monthly_rate"], 55000000.0)
        self.assertEqual(link["joining_date"], "2026-06-01")
        self.assertEqual(link["paid_leave_total_hours"], 16.0)

        # Verify staff paid leave total was updated with total hours across links
        updated_staff = cur.execute("SELECT paid_leave_total_hours FROM contract_staff WHERE id = ?", (self.staff_id,)).fetchone()
        self.assertEqual(updated_staff["paid_leave_total_hours"], 16.0)

    def test_multi_row_contract_staff_allocation(self):
        import contracts
        import urllib.parse
        cur = self.conn.cursor()

        # Create a second staff member for testing bulk allocation
        cur.execute("""
            INSERT INTO contract_staff (vendor_id, full_name_vi, position, status)
            VALUES (1, 'Trần Thị Bình', 'Tester', 'active')
        """)
        s2_id = cur.lastrowid
        self.conn.commit()

        # Simulate bulk multi-row POST (allocating 2 staff members at once)
        post_data = urllib.parse.urlencode([
            ("contract_id", str(self.contract_id)),
            ("annex_id", str(self.annex_id)),
            ("link_id", ""),
            ("staff_id", str(self.staff_id)),
            ("joining_date", "2026-07-01"),
            ("tentative_leaving_date", "2026-12-31"),
            ("monthly_rate", "40000000"),
            ("manday_rate", "2000000"),
            ("paid_leave_total_hours", "12.0"),
            # Row 2 (Second staff member)
            ("link_id", ""),
            ("staff_id", str(s2_id)),
            ("joining_date", "2026-07-01"),
            ("tentative_leaving_date", "2026-12-31"),
            ("monthly_rate", "45000000"),
            ("manday_rate", "2200000"),
            ("paid_leave_total_hours", "16.0")
        ]).encode("utf-8")

        handler = StubHandler(
            "/contract/assign-staff/save",
            "POST",
            body=post_data,
            headers={"Content-Length": str(len(post_data)), "Content-Type": "application/x-www-form-urlencoded"}
        )
        contracts.handle_contract_assign_staff_save_post(handler)

        self.assertEqual(handler.response_status, 302)
        
        # Verify both allocations were inserted into DB
        link1 = cur.execute("SELECT * FROM contract_staff_links WHERE staff_id = ? AND joining_date = '2026-07-01'", (self.staff_id,)).fetchone()
        self.assertIsNotNone(link1)
        self.assertEqual(link1["monthly_rate"], 40000000.0)

        link2 = cur.execute("SELECT * FROM contract_staff_links WHERE staff_id = ? AND joining_date = '2026-07-01'", (s2_id,)).fetchone()
        self.assertIsNotNone(link2)
        self.assertEqual(link2["monthly_rate"], 45000000.0)

    def test_page_attendance_acceptance(self):
        # Render attendance acceptance tab page with string and list inputs
        html = attendance.page_attendance_acceptance({"month": "2026-06"})
        self.assertIn("Attendance Month", html)
        self.assertIn("Framework Contract", html)
        self.assertNotIn("gồm 10% VAT", html)

        # Test list inputs (from HTTP parse_qs)
        html_list = attendance.page_attendance_acceptance({
            "month": ["2026-06"],
            "vendor_id": ["1"],
            "contract_id": ["1"],
            "annex_id": ["1"],
            "q": ["test"]
        })
    def test_attendance_acceptance_both_locks_required(self):
        # Create dedicated annex and staff, test lock requirements.
        cur = self.conn.cursor()
        cur.execute("INSERT INTO contract_annexes (contract_id, annex_name, start_date, end_date, is_active) VALUES (?, 'Annex Lock Test 1', '2026-01-01', '2026-12-31', 1)", (self.contract_id,))
        test_annex_id = cur.lastrowid

        cur.execute("INSERT INTO contract_staff (full_name_vi, vendor_id) VALUES ('Test Staff Both Locks', ?)", (self.seller_id,))
        test_staff_id = cur.lastrowid
        cur.execute("INSERT INTO contract_staff_links (staff_id, contract_id, annex_id, monthly_rate) VALUES (?, ?, ?, 50000000)", (test_staff_id, self.contract_id, test_annex_id))
        cur.execute("INSERT INTO attendance (staff_id, date, work_hours, ot_hours) VALUES (?, '2026-06-01', 8, 0)", (test_staff_id,))
        self.conn.commit()

        # 1. Unlocked daily & monthly -> Annex should NOT appear in acceptance
        html = attendance.page_attendance_acceptance({"month": "2026-06", "annex_id": str(test_annex_id)})
        self.assertNotIn("Test Staff Both Locks", html)

        # 2. Lock daily attendance only -> Annex should still NOT appear
        cur.execute("INSERT INTO attendance_locks (staff_id, month, locked, locked_at) VALUES (?, '2026-06', 1, '2026-06-30 17:30:00')", (test_staff_id,))
        self.conn.commit()
        html = attendance.page_attendance_acceptance({"month": "2026-06", "annex_id": str(test_annex_id)})
        self.assertNotIn("Test Staff Both Locks", html)

        # 3. Lock monthly payroll as well -> Annex SHOULD appear
        cur.execute("""
            INSERT INTO monthly_attendance_summary (staff_id, month, standard_days, actual_days, paid_leave_days, ot_converted_hours, daily_rate, total_amount, locked)
            VALUES (?, '2026-06', 22, 22, 0, 0, 2272727, 50000000, 1)
        """, (test_staff_id,))
        self.conn.commit()
        html = attendance.page_attendance_acceptance({"month": "2026-06", "annex_id": str(test_annex_id)})
        self.assertIn("💰 Cash-out", html)
        self.assertNotIn("CASHED OUT", html)

    def test_attendance_acceptance_all_contract_staff_must_be_locked(self):
        # Test that if an Annex has 2 staff members, Annex only appears when ALL contract staff are locked.
        cur = self.conn.cursor()
        cur.execute("INSERT INTO contract_annexes (contract_id, annex_name, start_date, end_date, is_active) VALUES (?, 'Annex Multi Staff Lock Test', '2026-01-01', '2026-12-31', 1)", (self.contract_id,))
        test_annex_id = cur.lastrowid

        # Staff 1
        cur.execute("INSERT INTO contract_staff (full_name_vi, vendor_id) VALUES ('Staff One Contract', ?)", (self.seller_id,))
        sid1 = cur.lastrowid
        cur.execute("INSERT INTO contract_staff_links (staff_id, contract_id, annex_id, monthly_rate) VALUES (?, ?, ?, 40000000)", (sid1, self.contract_id, test_annex_id))
        cur.execute("INSERT INTO attendance_locks (staff_id, month, locked, locked_at) VALUES (?, '2026-07', 1, '2026-07-31 18:00:00')", (sid1,))
        cur.execute("INSERT INTO monthly_attendance_summary (staff_id, month, standard_days, actual_days, paid_leave_days, ot_converted_hours, daily_rate, total_amount, locked) VALUES (?, '2026-07', 22, 22, 0, 0, 1818181, 40000000, 1)", (sid1,))

        # Staff 2 (linked to same annex, but not locked yet)
        cur.execute("INSERT INTO contract_staff (full_name_vi, vendor_id) VALUES ('Staff Two Contract', ?)", (self.seller_id,))
        sid2 = cur.lastrowid
        cur.execute("INSERT INTO contract_staff_links (staff_id, contract_id, annex_id, monthly_rate) VALUES (?, ?, ?, 60000000)", (sid2, self.contract_id, test_annex_id))
        self.conn.commit()

        # Only Staff 1 is locked, Staff 2 is unlocked -> Annex MUST NOT appear
        html = attendance.page_attendance_acceptance({"month": "2026-07", "annex_id": str(test_annex_id)})
        self.assertNotIn("Staff One Contract", html)

        # Now lock Staff 2 daily & monthly -> Annex SHOULD appear
        cur.execute("INSERT INTO attendance_locks (staff_id, month, locked, locked_at) VALUES (?, '2026-07', 1, '2026-07-31 19:00:00')", (sid2,))
        cur.execute("INSERT INTO monthly_attendance_summary (staff_id, month, standard_days, actual_days, paid_leave_days, ot_converted_hours, daily_rate, total_amount, locked) VALUES (?, '2026-07', 22, 22, 0, 0, 2727272, 60000000, 1)", (sid2,))
        self.conn.commit()

        html2 = attendance.page_attendance_acceptance({"month": "2026-07", "annex_id": str(test_annex_id)})
        self.assertIn("Staff One Contract", html2)
        self.assertIn("Staff Two Contract", html2)

    def test_attendance_pdf_lock_date_leave_and_amount_consistency(self):
        # Verify PDF contains daily attendance lock timestamp, leave hours match monthly payroll, and total amount matches monthly payroll.
        cur = self.conn.cursor()
        cur.execute("INSERT INTO contract_annexes (contract_id, annex_name, start_date, end_date, is_active) VALUES (?, 'Annex Consistency Test', '2026-01-01', '2026-12-31', 1)", (self.contract_id,))
        test_annex_id = cur.lastrowid

        cur.execute("INSERT INTO contract_staff (full_name_vi, vendor_id) VALUES ('Staff Consistency Check', ?)", (self.seller_id,))
        sid = cur.lastrowid
        cur.execute("INSERT INTO contract_staff_links (staff_id, contract_id, annex_id, monthly_rate) VALUES (?, ?, ?, 65000000)", (sid, self.contract_id, test_annex_id))
        cur.execute("INSERT INTO attendance (staff_id, date, work_hours, ot_hours) VALUES (?, '2026-08-01', 8, 0)", (sid,))
        cur.execute("INSERT INTO attendance_locks (staff_id, month, locked, locked_at) VALUES (?, '2026-08', 1, '2026-08-31 16:45:00')", (sid,))
        # Set 2.0 paid leave days (16.0 hours) and total_amount = 65000000 in monthly payroll summary
        cur.execute("""
            INSERT INTO monthly_attendance_summary (staff_id, month, standard_days, actual_days, paid_leave_days, ot_converted_hours, daily_rate, total_amount, locked)
            VALUES (?, '2026-08', 22, 20, 2.0, 0, 2954545, 65000000, 1)
        """, (sid,))
        self.conn.commit()

        # Fetch PDF HTML
        pdf_html = attendance.page_attendance_timesheet_report({"month": "2026-08", "annex_id": str(test_annex_id)})

        # 1. Verify Daily Attendance Lock Date and Vietnamese subtitle are NOT present
        self.assertNotIn("Daily Attendance Lock Date:", pdf_html)
        self.assertNotIn("(BIÊN BẢN NGHIỆM THU DỊCH VỤ)", pdf_html)

        # 2. Verify Annual leave hours in Section 1 match monthly payroll paid_leave_days * 8 = 16h
        self.assertIn("Annual leave: 16h", pdf_html)

        # 3. Verify Total amount matches monthly payroll summary total_amount = 65,000,000
        self.assertIn("65,000,000", pdf_html)

    def test_attendance_acceptance_joining_date_filtering(self):
        # Staff joining in 2026-07 must NOT appear in 2026-06 Acceptance
        cur = self.conn.cursor()
        cur.execute("INSERT INTO contract_annexes (contract_id, annex_name, start_date, end_date, is_active) VALUES (?, 'Annex Joining Date Test', '2026-01-01', '2026-12-31', 1)", (self.contract_id,))
        test_annex_id = cur.lastrowid

        cur.execute("INSERT INTO contract_staff (full_name_vi, vendor_id) VALUES ('Lưu Hoàng Long', ?)", (self.seller_id,))
        sid = cur.lastrowid
        cur.execute("INSERT INTO contract_staff_links (staff_id, contract_id, annex_id, joining_date, monthly_rate) VALUES (?, ?, ?, '2026-07-01', 50000000)", (sid, self.contract_id, test_annex_id))
        self.conn.commit()

        # In June 2026 (before joining date), staff should NOT be included
        html_june = attendance.page_attendance_acceptance({"month": "2026-06", "annex_id": str(test_annex_id)})
        self.assertNotIn("Lưu Hoàng Long", html_june)

        # In July 2026 (starting from joining date), after locking daily & monthly
        cur.execute("INSERT INTO attendance_locks (staff_id, month, locked, locked_at) VALUES (?, '2026-07', 1, '2026-07-31 18:00:00')", (sid,))
        cur.execute("INSERT INTO monthly_attendance_summary (staff_id, month, standard_days, actual_days, paid_leave_days, ot_converted_hours, daily_rate, total_amount, locked) VALUES (?, '2026-07', 22, 22, 0, 0, 2272727, 50000000, 1)", (sid,))
        self.conn.commit()

        html_july = attendance.page_attendance_acceptance({"month": "2026-07", "annex_id": str(test_annex_id)})
        self.assertIn("Lưu Hoàng Long", html_july)

    def test_service_fee_calculation_columns_and_rates(self):
        # Verify Section 3 includes Standard Days, Actual Days, Paid Leave, and Unit Rate (Man-month vs Man-day rate)
        cur = self.conn.cursor()
        cur.execute("INSERT INTO contract_annexes (contract_id, annex_name, start_date, end_date, is_active) VALUES (?, 'Annex Rate Test', '2026-01-01', '2026-12-31', 1)", (self.contract_id,))
        annex_id = cur.lastrowid

        # Staff 1: Monthly rate
        cur.execute("INSERT INTO contract_staff (full_name_vi, vendor_id) VALUES ('Staff Monthly Rate', ?)", (self.seller_id,))
        sid1 = cur.lastrowid
        cur.execute("INSERT INTO contract_staff_links (staff_id, contract_id, annex_id, monthly_rate) VALUES (?, ?, ?, 60000000)", (sid1, self.contract_id, annex_id))

        # Staff 2: Manday rate
        cur.execute("INSERT INTO contract_staff (full_name_vi, vendor_id) VALUES ('Staff Manday Rate', ?)", (self.seller_id,))
        sid2 = cur.lastrowid
        cur.execute("INSERT INTO contract_staff_links (staff_id, contract_id, annex_id, manday_rate) VALUES (?, ?, ?, 3000000)", (sid2, self.contract_id, annex_id))

        # Locks and Monthly Summary
        for sid in [sid1, sid2]:
            cur.execute("INSERT INTO attendance (staff_id, date, work_hours, ot_hours) VALUES (?, '2026-08-01', 8, 0)", (sid,))
            cur.execute("INSERT INTO attendance_locks (staff_id, month, locked, locked_at) VALUES (?, '2026-08', 1, '2026-08-31 17:00:00')", (sid,))

        cur.execute("INSERT INTO monthly_attendance_summary (staff_id, month, standard_days, actual_days, paid_leave_days, ot_converted_hours, daily_rate, total_amount, locked) VALUES (?, '2026-08', 22, 20, 2.0, 0, 2727273, 60000000, 1)", (sid1,))
        cur.execute("INSERT INTO monthly_attendance_summary (staff_id, month, standard_days, actual_days, paid_leave_days, ot_converted_hours, daily_rate, total_amount, locked) VALUES (?, '2026-08', 22, 20, 2.0, 0, 3000000, 66000000, 1)", (sid2,))
        self.conn.commit()

        pdf_html = attendance.page_attendance_timesheet_report({"month": "2026-08", "annex_id": str(annex_id)})

        # Check headers
        self.assertIn("Standard Days", pdf_html)
        self.assertIn("Actual Days", pdf_html)
        self.assertIn("Paid Leave", pdf_html)
        self.assertIn("Unit Rate", pdf_html)

        # Check rates
        self.assertIn("60,000,000", pdf_html)  # Staff 1 Man-month rate
        self.assertIn("3,000,000", pdf_html)   # Staff 2 Man-day rate

    def test_staff_submenu_assign_to_project(self):
        # 1. Verify layout contains Staff sub-menu link for Assign Staff to Project
        html = common.layout("Test Title", "<p>Content</p>")
        self.assertIn("Assign Staff to Project", html)
        self.assertIn("/projects/assign#add-staff-section", html)
        self.assertIn('Timesheet & Payroll (T&M)', html)
        self.assertIn('Payments', html)

        # 2. Verify /projects/assign page contains Add New Staff member to Project form with id="add-staff-section"
        cur = self.conn.cursor()
        cur.execute("INSERT INTO projects (short_name, full_name, os_start_date, os_end_date, is_active) VALUES ('PROJ-SUB', 'Submenu Project', '2026-01-01', '2026-12-31', 1)")
        p_id = cur.lastrowid
        self.conn.commit()

        assign_html = projects.page_projects_assign(selected_project_id=str(p_id))
        self.assertIn('id="add-staff-section"', assign_html)
    def test_attendance_tab_name_and_import_invoice_link(self):
        # 1. Verify tab name changed to "Monthly Payroll" (not "Monthly Payroll & Payment")
        html_daily = attendance.page_attendance({"month": "2026-08"})
        self.assertIn("💵 Monthly Payroll", html_daily)
        self.assertNotIn("💵 Monthly Payroll & Payment", html_daily)

        html_monthly = attendance.page_monthly_attendance({"month": "2026-08"})
        self.assertIn("💵 Monthly Payroll", html_monthly)
        self.assertNotIn("💵 Monthly Payroll & Payment", html_monthly)

        html_acc = attendance.page_attendance_acceptance({"month": "2026-08"})
        self.assertIn("💵 Monthly Payroll", html_acc)
        self.assertNotIn("💵 Monthly Payroll & Payment", html_acc)

        # 2. Setup a locked annex to test "Import hóa đơn" button in Attendance Acceptance
        cur = self.conn.cursor()
        cur.execute("INSERT INTO contract_annexes (contract_id, annex_name, start_date, end_date, is_active) VALUES (?, 'Annex 3', '2026-01-01', '2026-12-31', 1)", (self.contract_id,))
        annex_id = cur.lastrowid

        cur.execute("INSERT INTO contract_staff (full_name_vi, vendor_id) VALUES ('Staff Acceptance Test', ?)", (self.seller_id,))
        sid = cur.lastrowid
        cur.execute("INSERT INTO contract_staff_links (staff_id, contract_id, annex_id, monthly_rate) VALUES (?, ?, ?, 50000000)", (sid, self.contract_id, annex_id))

        cur.execute("INSERT INTO attendance (staff_id, date, work_hours, ot_hours) VALUES (?, '2026-08-01', 8, 0)", (sid,))
        cur.execute("INSERT INTO attendance_locks (staff_id, month, locked, locked_at) VALUES (?, '2026-08', 1, '2026-08-31 17:00:00')", (sid,))
        cur.execute("INSERT INTO monthly_attendance_summary (staff_id, month, standard_days, actual_days, paid_leave_days, ot_converted_hours, daily_rate, total_amount, locked) VALUES (?, '2026-08', 22, 22, 0, 0, 2272727, 50000000, 1)", (sid,))
        self.conn.commit()

        acc_html = attendance.page_attendance_acceptance({"month": "2026-08", "annex_id": str(annex_id)})
        self.assertIn("📥 Import Invoice", acc_html)
        self.assertIn('service_year=2026', acc_html)
        self.assertIn('service_month=08', acc_html)
        self.assertIn('Annex%203', acc_html)

        # 3. Test /invoice/new with query parameters (via StubHandler)
        handler_with_params = StubHandler("/invoice/new?service_year=2026&service_month=08&contract_no=Annex%203&return_month=2026-08&from=acceptance", "GET")
        handler_with_params.do_GET()
        invoice_html = handler_with_params.get_output_text()

        self.assertIn('value="2026"', invoice_html)
        self.assertIn('value="08"', invoice_html)
        self.assertIn('value="Annex 3"', invoice_html)
        self.assertIn('forward to Attendance acceptance', invoice_html)
        self.assertIn('/attendance/acceptance?month=2026-08', invoice_html)

        # 4. Test /invoice/new without parameters (default: origin is Invoices List)
        handler_no_params = StubHandler("/invoice/new", "GET")
        handler_no_params.do_GET()
        invoice_html_default = handler_no_params.get_output_text()
        self.assertIn('Back to Invoices List', invoice_html_default)
        self.assertNotIn('forward to Attendance acceptance', invoice_html_default)

        # 5. Test locking import button when invoice already exists for this annex & month
        seller_tax_id = self.conn.execute("SELECT tax_id FROM vendors WHERE id = ?", (self.seller_id,)).fetchone()["tax_id"]
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO invoices (service_year, service_month, contract_no, seller_mst, shdon, imported_at)
            VALUES (2026, 8, 'Annex 3', ?, 'HD-TEST-001', '2026-08-20')
        """, (seller_tax_id,))
        self.conn.commit()

        acc_html_locked = attendance.page_attendance_acceptance({"month": "2026-08", "annex_id": str(annex_id)})
        self.assertIn("🔒 Invoice Imported", acc_html_locked)
        self.assertIn("disabled", acc_html_locked)
        self.assertIn("View Inv #HD-TEST-001", acc_html_locked)
        self.assertNotIn("/invoice/new?service_year=2026&amp;service_month=08&amp;contract_no=Annex%203", acc_html_locked)

    def test_attendance_acceptance_cashout_popup_and_save(self):
        # 1. Setup a locked annex
        cur = self.conn.cursor()
        cur.execute("INSERT INTO contract_annexes (contract_id, annex_name, start_date, end_date, is_active) VALUES (?, 'Annex Cashout Test', '2026-01-01', '2026-12-31', 1)", (self.contract_id,))
        annex_id = cur.lastrowid

        cur.execute("INSERT INTO contract_staff (full_name_vi, vendor_id) VALUES ('Staff Cashout', ?)", (self.seller_id,))
        sid = cur.lastrowid
        cur.execute("INSERT INTO contract_staff_links (staff_id, contract_id, annex_id, monthly_rate) VALUES (?, ?, ?, 50000000)", (sid, self.contract_id, annex_id))

        cur.execute("INSERT INTO attendance (staff_id, date, work_hours, ot_hours) VALUES (?, '2026-09-01', 8, 0)", (sid,))
        cur.execute("INSERT INTO attendance_locks (staff_id, month, locked, locked_at) VALUES (?, '2026-09', 1, '2026-09-30 17:00:00')", (sid,))
        cur.execute("INSERT INTO monthly_attendance_summary (staff_id, month, standard_days, actual_days, paid_leave_days, ot_converted_hours, daily_rate, total_amount, locked) VALUES (?, '2026-09', 22, 22, 0, 0, 2272727, 50000000, 1)", (sid,))
        self.conn.commit()

        # 2. Before cash-out:
        # - Button "💰 Cash-out" is present
        # - CASHED OUT badge is NOT displayed ("trường hợp chưa cashout thì ko hiển thị gì")
        # - Modal popup HTML is rendered
        html_before = attendance.page_attendance_acceptance({"month": "2026-09", "annex_id": str(annex_id)})
        self.assertIn("💰 Cash-out", html_before)
        self.assertNotIn("CASHED OUT", html_before)
        self.assertIn('id="cashoutModal"', html_before)

        # 3. Save cash-out date via POST handler
        body_set = f"annex_id={annex_id}&month=2026-09&cashout_date=2026-09-25&action=save".encode()
        handler_set = MockHandler(path="/attendance/acceptance/cashout", body=body_set, headers={"content-length": str(len(body_set))})
        attendance.handle_attendance_cashout_post(handler_set)
        self.assertEqual(handler_set.response_status, 302)

        # 4. After cash-out:
        # - Badge "💸 CASHED OUT (2026-09-25)" is displayed
        # - Button changes to "✏️ Edit Cash-out"
        html_after_set = attendance.page_attendance_acceptance({"month": "2026-09", "annex_id": str(annex_id)})
        self.assertIn("CASHED OUT", html_after_set)
        self.assertIn("2026-09-25", html_after_set)
        self.assertIn("✏️ Edit Cash-out", html_after_set)

        # 5. Edit cash-out date to 2026-09-28
        body_edit = f"annex_id={annex_id}&month=2026-09&cashout_date=2026-09-28&action=save".encode()
        handler_edit = MockHandler(path="/attendance/acceptance/cashout", body=body_edit, headers={"content-length": str(len(body_edit))})
        attendance.handle_attendance_cashout_post(handler_edit)
        self.assertEqual(handler_edit.response_status, 302)

        html_after_edit = attendance.page_attendance_acceptance({"month": "2026-09", "annex_id": str(annex_id)})
        self.assertIn("2026-09-28", html_after_edit)
        self.assertNotIn("2026-09-25", html_after_edit)

        # 6. Clear cash-out date
        body_clear = f"annex_id={annex_id}&month=2026-09&action=clear".encode()
        handler_clear = MockHandler(path="/attendance/acceptance/cashout", body=body_clear, headers={"content-length": str(len(body_clear))})
        attendance.handle_attendance_cashout_post(handler_clear)
        self.assertEqual(handler_clear.response_status, 302)

        html_after_clear = attendance.page_attendance_acceptance({"month": "2026-09", "annex_id": str(annex_id)})
        self.assertNotIn("CASHED OUT", html_after_clear)
        self.assertIn("💰 Cash-out", html_after_clear)

    def test_attendance_payout_tab_and_csv_export(self):
        # 1. Verify sub-nav contains Cash-out tab on all attendance views
        daily_html = attendance.page_attendance({"month": "2026-08"})
        self.assertIn("💰 Cash-out", daily_html)
        self.assertIn('/attendance/cashout', daily_html)

        monthly_html = attendance.page_monthly_attendance({"month": "2026-08"})
        self.assertIn("💰 Cash-out", monthly_html)

        acceptance_html = attendance.page_attendance_acceptance({"month": "2026-08"})
        self.assertIn("💰 Cash-out", acceptance_html)

        # 2. Setup test data for FY26:
        # Create a vendor, contract, and annex with cashout in FY26 (2026-04 to 2027-03)
        cur = self.conn.cursor()
        cur.execute("INSERT INTO vendors (company_name, short_name, purchasing, tax_id) VALUES ('Alpha Vendor Solutions', 'Alpha Vendor', 0, '0109999999')")
        v_id = cur.lastrowid
        cur.execute("INSERT INTO contracts (buyer_vendor_id, seller_vendor_id, framework_no) VALUES (?, ?, 'CONT-PAYOUT-01')", (self.buyer_id, v_id))
        c_id = cur.lastrowid
        cur.execute("INSERT INTO contract_annexes (contract_id, annex_name) VALUES (?, 'Annex Payout 1')", (c_id,))
        a_id = cur.lastrowid
        cur.execute("INSERT INTO contract_staff (full_name_vi, vendor_id) VALUES ('Nguyen Payout Staff', ?)", (v_id,))
        s_id = cur.lastrowid
        cur.execute("INSERT INTO contract_staff_links (staff_id, contract_id, annex_id, monthly_rate) VALUES (?, ?, ?, 50000000)", (s_id, c_id, a_id))
        # Add summary record for 2026-05 (Month 5 in Q1 of FY26)
        cur.execute("""
            INSERT INTO monthly_attendance_summary (staff_id, month, standard_days, actual_days, daily_rate, total_amount, locked)
            VALUES (?, '2026-05', 22, 22, 2272727, 50000000, 1)
        """, (s_id,))
        # Set cashout date for 2026-05
        cur.execute("""
            INSERT INTO annex_cashouts (annex_id, month, cashout_date)
            VALUES (?, '2026-05', '2026-06-15')
        """, (a_id,))
        self.conn.commit()

        # 3. View Cash-out tab for FY26
        payout_html = attendance.page_attendance_payout({"fy": "2026"})
        self.assertIn("Timesheet &amp; Payroll - Cash-out FY26", payout_html)
        self.assertIn("Fiscal Year Cash-out Overview - FY26", payout_html)
        self.assertIn("Period: 01/04/2026 &rarr; 31/03/2027", payout_html)

        # Verify quarters and months headers
        self.assertIn("Quarter 1 (Q1)", payout_html)
        self.assertIn("Quarter 2 (Q2)", payout_html)
        self.assertIn("Quarter 3 (Q3)", payout_html)
        self.assertIn("Quarter 4 (Q4)", payout_html)
        self.assertIn("Apr", payout_html)
        self.assertIn("May", payout_html)
        self.assertIn("Jun", payout_html)
        self.assertIn("Jul", payout_html)
        self.assertIn("Aug", payout_html)
        self.assertIn("Sep", payout_html)
        self.assertIn("Oct", payout_html)
        self.assertIn("Nov", payout_html)
        self.assertIn("Dec", payout_html)
        self.assertIn("Jan", payout_html)
        self.assertIn("Feb", payout_html)
        self.assertIn("Mar", payout_html)

        # Verify calendar FY picker UI elements
        self.assertIn('id="fyPickerBtn"', payout_html)
        self.assertIn('id="fyCalendarPopup"', payout_html)
        self.assertIn('id="fyMonthPicker"', payout_html)
        self.assertIn('pickMonthFY', payout_html)
        self.assertIn('toggleFyCalendar', payout_html)
        self.assertIn('Total FY Payroll', payout_html)
        self.assertIn('Total FY Cash-out', payout_html)

        # Verify dual concepts: Payroll vs Cash-out in table
        self.assertIn("Alpha Vendor", payout_html)
        self.assertIn('title="Alpha Vendor Solutions"', payout_html)
        self.assertIn("Framework / Annex", payout_html)
        self.assertIn('<td colspan="3" style="text-align:right;', payout_html)
        self.assertIn("CONT-PAYOUT-01", payout_html)
        self.assertIn("Annex Payout 1", payout_html)
        self.assertIn("50,000,000", payout_html)
        self.assertIn("2026-06-15", payout_html)
        self.assertIn("Export to CSV", payout_html)

        # Check raw data breakdown from get_payout_data
        data = attendance.get_payout_data(self.conn, 2026, "with_cashout", None, "")
        self.assertEqual(len(data["rows"]), 1)
        r0 = data["rows"][0]
        # In Month 2026-05: Payroll is 50,000,000 (service month), Cash-out is 0.0 (no cashout executed in May)
        self.assertEqual(r0["months"]["2026-05"]["payroll"], 50000000.0)
        self.assertEqual(r0["months"]["2026-05"]["cashout"], 0.0)
        # In Month 2026-06: Cash-out is 50,000,000 (paid on 2026-06-15), Payroll is 0.0
        self.assertEqual(r0["months"]["2026-06"]["cashout"], 50000000.0)
        self.assertEqual(r0["months"]["2026-06"]["cashout_date_str"], "2026-06-15")
        self.assertEqual(r0["months"]["2026-06"]["payroll"], 0.0)
        # Check cashout breakdown details for tooltip
        self.assertIn("cashout_breakdown", r0["months"]["2026-06"])
        bd0 = r0["months"]["2026-06"]["cashout_breakdown"][0]
        self.assertEqual(bd0["service_month"], "2026-05")
        self.assertEqual(bd0["service_month_formatted"], "05/2026")
        self.assertEqual(bd0["cashout_date"], "2026-06-15")
        self.assertEqual(bd0["cashout_date_formatted"], "15/06/2026")
        self.assertEqual(bd0["amount"], 50000000.0)
        self.assertEqual(bd0["basis"], "Timesheet lock")
        self.assertIn("showCoTip", payout_html)
        self.assertIn("data-bd=", payout_html)
        self.assertIn("&quot;service_month_formatted&quot;: &quot;05/2026&quot;", payout_html)
        self.assertIn("Paying for Month:", payout_html)

        # 4. Test blank cashout date logic
        # Annex 2 with payroll locked in 2026-07 but NO cashout date set (blank)
        cur.execute("INSERT INTO contract_annexes (contract_id, annex_name) VALUES (?, 'Annex No Cashout Date')", (c_id,))
        a2_id = cur.lastrowid
        cur.execute("INSERT INTO contract_staff (full_name_vi, vendor_id) VALUES ('Pending Cashout Staff', ?)", (v_id,))
        s2_id = cur.lastrowid
        cur.execute("INSERT INTO contract_staff_links (staff_id, contract_id, annex_id, monthly_rate) VALUES (?, ?, ?, 30000000)", (s2_id, c_id, a2_id))
        cur.execute("""
            INSERT INTO monthly_attendance_summary (staff_id, month, standard_days, actual_days, daily_rate, total_amount, locked)
            VALUES (?, '2026-07', 22, 22, 1363636, 30000000, 1)
        """, (s2_id,))
        self.conn.commit()

        data2 = attendance.get_payout_data(self.conn, 2026, "with_cashout", None, "")
        annex2_row = next(r for r in data2["rows"] if r["annex"]["annex_id"] == a2_id)
        # Month 2026-07: Payroll is 30,000,000; Cash-out is 0.0 because cashout date is blank
        self.assertEqual(annex2_row["months"]["2026-07"]["payroll"], 30000000.0)
        self.assertEqual(annex2_row["months"]["2026-07"]["cashout"], 0.0)
        self.assertFalse(annex2_row["has_cashout"])
        self.assertTrue(annex2_row["has_payroll"])

        # In "cashed_out" only filter, Annex 2 must NOT appear
        data_co_only = attendance.get_payout_data(self.conn, 2026, "cashed_out", None, "")
        self.assertFalse(any(r["annex"]["annex_id"] == a2_id for r in data_co_only["rows"]))

        # 6. Test cashout_only status filter: hides Payroll, shows Cash-out only
        html_co = attendance.page_attendance_payout({"fy": "2026", "status": "cashout_only"})
        self.assertIn("Total FY Cash-out", html_co)
        self.assertNotIn("Total FY Payroll", html_co)
        self.assertIn("Annex Payout 1", html_co)
        self.assertNotIn("Annex No Cashout Date", html_co) # Annex 2 has no cashout

        # Test CSV export with cashout_only
        export_co_handler = MockHandler(path="/attendance/cashout/export?fy=2026&status=cashout_only")
        attendance.handle_attendance_cashout_export_get(export_co_handler)
        csv_co = export_co_handler.wfile.getvalue().decode("utf-8-sig")
        self.assertIn("Q1 - Jun (06/2026) Cash-out", csv_co)
        self.assertNotIn(") Payroll", csv_co)

        # 7. Test payroll_only status filter: hides Cash-out, shows Payroll only
        html_po = attendance.page_attendance_payout({"fy": "2026", "status": "payroll_only"})
        self.assertIn("Total FY Payroll", html_po)
        self.assertNotIn("Total FY Cash-out", html_po)
        self.assertIn("Annex Payout 1", html_po)
        self.assertIn("Annex No Cashout Date", html_po) # Annex 2 has payroll

        # Test CSV export with payroll_only
        export_po_handler = MockHandler(path="/attendance/cashout/export?fy=2026&status=payroll_only")
        attendance.handle_attendance_cashout_export_get(export_po_handler)
        csv_po = export_po_handler.wfile.getvalue().decode("utf-8-sig")
        self.assertIn("Q1 - May (05/2026) Payroll", csv_po)
        self.assertNotIn(") Cash-out", csv_po)

    def test_attendance_payout_annex_effective_dates_isolation(self):
        """Verify that an annex only receives payroll for months within its validity and staff assignment dates."""
        cur = self.conn.cursor()
        cur.execute("INSERT INTO vendors (company_name, purchasing, tax_id) VALUES ('Annex Date Vendor', 0, '0108888888')")
        v_id = cur.lastrowid
        cur.execute("INSERT INTO contracts (buyer_vendor_id, seller_vendor_id, framework_no) VALUES (?, ?, 'CONT-DATE-01')", (self.buyer_id, v_id))
        c_id = cur.lastrowid

        # Annex A: April to September 2026
        cur.execute("""
            INSERT INTO contract_annexes (contract_id, annex_name, start_date, end_date) 
            VALUES (?, 'Annex Early Period', '2026-04-01', '2026-09-30')
        """, (c_id,))
        a1_id = cur.lastrowid

        # Annex B: October to November 2026
        cur.execute("""
            INSERT INTO contract_annexes (contract_id, annex_name, start_date, end_date) 
            VALUES (?, 'Annex Late Period', '2026-10-01', '2026-11-30')
        """, (c_id,))
        a2_id = cur.lastrowid

        cur.execute("INSERT INTO contract_staff (full_name_vi, vendor_id) VALUES ('Reassigned Staff', ?)", (v_id,))
        s_id = cur.lastrowid

        # Staff link 1: assigned to Annex A during April-September
        cur.execute("""
            INSERT INTO contract_staff_links (staff_id, contract_id, annex_id, monthly_rate, joining_date, tentative_leaving_date)
            VALUES (?, ?, ?, 60000000, '2026-04-01', '2026-09-30')
        """, (s_id, c_id, a1_id))

        # Staff link 2: extended/reassigned to Annex B during October-November
        cur.execute("""
            INSERT INTO contract_staff_links (staff_id, contract_id, annex_id, monthly_rate, joining_date, tentative_leaving_date)
            VALUES (?, ?, ?, 70000000, '2026-10-01', '2026-11-30')
        """, (s_id, c_id, a2_id))

        # Attendance record for May 2026 (60M)
        cur.execute("""
            INSERT INTO monthly_attendance_summary (staff_id, month, standard_days, actual_days, daily_rate, total_amount, locked)
            VALUES (?, '2026-05', 22, 22, 2727272, 60000000, 1)
        """, (s_id,))

        # Attendance record for October 2026 (70M)
        cur.execute("""
            INSERT INTO monthly_attendance_summary (staff_id, month, standard_days, actual_days, daily_rate, total_amount, locked)
            VALUES (?, '2026-10', 22, 22, 3181818, 70000000, 1)
        """, (s_id,))
        self.conn.commit()

        data = attendance.get_payout_data(self.conn, 2026, "all_active", None, "CONT-DATE-01")
        annex_map = {r["annex"]["annex_id"]: r for r in data["rows"]}

        self.assertIn(a1_id, annex_map)
        self.assertIn(a2_id, annex_map)

        row_a1 = annex_map[a1_id]
        row_a2 = annex_map[a2_id]

        # Annex A: has 60M in May, but 0 in October (outside its date range)
        self.assertEqual(row_a1["months"]["2026-05"]["payroll"], 60000000.0)
        self.assertEqual(row_a1["months"]["2026-10"]["payroll"], 0.0)

        # Annex B: has 0 in May (starts in October), and 70M in October
        self.assertEqual(row_a2["months"]["2026-05"]["payroll"], 0.0)
        self.assertEqual(row_a2["months"]["2026-10"]["payroll"], 70000000.0)


class TestFixedPriceMilestones(BaseTestCase):
    def test_standalone_fixed_price_contract_and_milestones(self):
        # 1. Create Standalone Fixed Price Contract
        body = (
            f"buyer_vendor_id={self.buyer_id}&seller_vendor_id={self.seller_id}"
            f"&framework_no=FP-2026-001&framework_name=Core+Banking+Module"
            f"&contract_type=STANDALONE&billing_type=FIXED_PRICE"
            f"&contract_value=500000000&start_date=2026-01-01&end_date=2026-12-31"
        ).encode()
        handler = MockHandler(body=body, headers={"content-length": str(len(body))})
        contracts.handle_contract_create_post(handler)
        self.assertEqual(handler.response_status, 302)

        c = self.conn.execute("SELECT * FROM contracts WHERE framework_no='FP-2026-001'").fetchone()
        self.assertIsNotNone(c)
        self.assertEqual(c["contract_type"], "STANDALONE")
        self.assertEqual(c["billing_type"], "FIXED_PRICE")
        self.assertEqual(float(c["contract_value"]), 500000000.0)
        c_id = c["id"]

        # 2. Add Milestones to this contract
        # Milestone 1: Advance payment 20% = 100M
        body_m1 = (
            f"contract_id={c_id}&annex_id=&milestone_name=T%E1%BA%A1m+%E1%BB%A9ng+20%25"
            f"&milestone_type=ADVANCE&percentage=20&amount=100000000"
            f"&planned_date=2026-01-15&status=PENDING"
        ).encode()
        h_m1 = MockHandler(body=body_m1, headers={"content-length": str(len(body_m1))})
        contracts.handle_milestone_create_post(h_m1)
        self.assertEqual(h_m1.response_status, 302)

        # Milestone 2: UAT 50% = 250M
        body_m2 = (
            f"contract_id={c_id}&annex_id=&milestone_name=Nghi%E1%BB%87m+thu+UAT"
            f"&milestone_type=ACCEPTANCE&percentage=50&amount=250000000"
            f"&planned_date=2026-06-30&status=PENDING"
        ).encode()
        h_m2 = MockHandler(body=body_m2, headers={"content-length": str(len(body_m2))})
        contracts.handle_milestone_create_post(h_m2)

        # Milestone 3: Golive 30% = 150M
        body_m3 = (
            f"contract_id={c_id}&annex_id=&milestone_name=B%C3%A0n+giao+to%C3%A0n+di%E1%BB%87n"
            f"&milestone_type=DELIVERY&percentage=30&amount=150000000"
            f"&planned_date=2026-11-30&status=PENDING"
        ).encode()
        h_m3 = MockHandler(body=body_m3, headers={"content-length": str(len(body_m3))})
        contracts.handle_milestone_create_post(h_m3)

        ms = common.get_milestones_for_contract(self.conn, c_id, annex_id=None)
        self.assertEqual(len(ms), 3)
        self.assertEqual(sum(float(m["amount"]) for m in ms), 500000000.0)

        m1_id = ms[0]["id"]

        # 3. Update Milestone 1
        body_update = (
            f"id={m1_id}&milestone_name=T%E1%BA%A1m+%E1%BB%A9ng+%C4%91%E1%BB%A3t+1"
            f"&milestone_type=ADVANCE&percentage=20&amount=100000000"
            f"&planned_date=2026-01-15&actual_date=2026-01-16&status=ACCEPTED"
            f"&acceptance_doc_no=BBNT-ADV-01&cashout_date=&note=Ghi+chu"
        ).encode()
        h_up = MockHandler(body=body_update, headers={"content-length": str(len(body_update))})
        contracts.handle_milestone_update_post(h_up)
        self.assertEqual(h_up.response_status, 302)

        m1_updated = self.conn.execute("SELECT * FROM contract_milestones WHERE id=?", (m1_id,)).fetchone()
        self.assertEqual(m1_updated["acceptance_doc_no"], "BBNT-ADV-01")
        self.assertEqual(m1_updated["status"], "ACCEPTED")

        # 4. Cashout Milestone 1
        body_co = f"id={m1_id}&cashout_date=2026-01-20".encode()
        h_co = MockHandler(body=body_co, headers={"content-length": str(len(body_co))})
        contracts.handle_milestone_cashout_post(h_co)
        self.assertEqual(h_co.response_status, 302)

        m1_paid = self.conn.execute("SELECT * FROM contract_milestones WHERE id=?", (m1_id,)).fetchone()
        self.assertEqual(m1_paid["cashout_date"], "2026-01-20")
        self.assertEqual(m1_paid["status"], "PAID")

        # 5. Test Invoice Reconciliation for Fixed Price Contract
        # Matching amount 100M
        st, l_sum, a_sum, msg = invoices.check_invoice_payroll_reconciliation(
            self.conn, "FP-2026-001", None, None, 100000000.0
        )
        self.assertEqual(st, "ok")
        self.assertIn("Matched Fixed Price Milestone", msg)

        # Mismatch amount (e.g. 80M)
        st_mis, l_sum, a_sum, msg_mis = invoices.check_invoice_payroll_reconciliation(
            self.conn, "FP-2026-001", None, None, 80000000.0
        )
        self.assertEqual(st_mis, "mismatch")

        # 6. Test UI rendering
        html_contract = contracts.page_contract_form("edit", c, [])
        self.assertIn("Payment Milestones & Schedule", html_contract)
        self.assertIn("Tạm ứng đợt 1", html_contract)
        self.assertIn("Nghiệm thu UAT", html_contract)

        html_list = contracts.page_contracts_list(q="FP-2026-001", status="active", return_to="/contracts")
        self.assertIn("Standalone", html_list)
        self.assertIn("Fixed Price", html_list)
        self.assertIn("3 milestone(s)", html_list)

        # 7. Delete Milestone 3
        m3_id = ms[2]["id"]
        body_del = f"id={m3_id}".encode()
        h_del = MockHandler(body=body_del, headers={"content-length": str(len(body_del))})
        contracts.handle_milestone_delete_post(h_del)
        self.assertEqual(h_del.response_status, 302)

        remaining_ms = common.get_milestones_for_contract(self.conn, c_id, annex_id=None)
        self.assertEqual(len(remaining_ms), 2)

    def test_framework_contract_with_fixed_price_annex(self):
        # 1. Create Framework Contract
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO contracts (
              buyer_vendor_id, seller_vendor_id, framework_no, framework_name,
              contract_type, billing_type, is_active, created_at, updated_at
            ) VALUES (?, ?, 'MSA-FIXED-01', 'Framework for Solutions', 'FRAMEWORK', 'TM', 1, datetime('now'), datetime('now'))
        """, (self.buyer_id, self.seller_id))
        c_id = cur.lastrowid
        self.conn.commit()

        # 2. Create Fixed Price Annex under this contract
        body_a = (
            f"contract_id={c_id}&annex_name=ANNEX-FP-PHASE1&billing_type=FIXED_PRICE"
            f"&value=300000000&start_date=2026-03-01&end_date=2026-08-31"
        ).encode()
        h_a = MockHandler(body=body_a, headers={"content-length": str(len(body_a))})
        contracts.handle_annex_create_post(h_a)
        self.assertEqual(h_a.response_status, 302)

        annex = self.conn.execute("SELECT * FROM contract_annexes WHERE annex_name='ANNEX-FP-PHASE1'").fetchone()
        self.assertIsNotNone(annex)
        self.assertEqual(annex["billing_type"], "FIXED_PRICE")
        a_id = annex["id"]

        # 3. Add Milestone to this Annex
        body_m = (
            f"contract_id={c_id}&annex_id={a_id}&milestone_name=Giai+%C4%91o%E1%BA%A1n+1"
            f"&milestone_type=DELIVERY&percentage=100&amount=300000000"
            f"&planned_date=2026-08-15&status=PENDING"
        ).encode()
        h_m = MockHandler(body=body_m, headers={"content-length": str(len(body_m))})
        contracts.handle_milestone_create_post(h_m)
        self.assertEqual(h_m.response_status, 302)

        ms = common.get_milestones_for_contract(self.conn, c_id, annex_id=a_id)
        self.assertEqual(len(ms), 1)
        self.assertEqual(ms[0]["annex_id"], a_id)
        self.assertEqual(float(ms[0]["amount"]), 300000000.0)

        # 4. Verify Invoice reconciliation on Annex level
        st, l_sum, a_sum, msg = invoices.check_invoice_payroll_reconciliation(
            self.conn, "ANNEX-FP-PHASE1", None, None, 300000000.0
        )
        self.assertEqual(st, "ok")
        self.assertIn("Giai đoạn 1", msg)

        # 5. Verify Annex Edit page renders milestones card
        html_annex = contracts.page_annex_form("edit", annex, c_id)
        self.assertIn("Payment Milestones & Schedule", html_annex)
        self.assertIn("Giai đoạn 1", html_annex)


class TestRecurringAndPaymentsDashboards(BaseTestCase):
    def test_recurring_contract_and_invoice_reconciliation(self):
        import payments

        # 1. Create a Recurring contract (e.g. Internet Leased Line 15M/month)
        body = (
            f"buyer_vendor_id={self.buyer_id}&seller_vendor_id={self.seller_id}"
            f"&framework_no=INTERNET-VNPT-2026&framework_name=Internet+Leased+Line+100Mbps"
            f"&contract_type=STANDALONE&billing_type=RECURRING"
            f"&recurring_fee=15000000&recurring_period=MONTHLY"
            f"&start_date=2026-01-01&end_date=2026-12-31"
        ).encode()
        h = MockHandler(body=body, headers={"content-length": str(len(body))})
        contracts.handle_contract_create_post(h)
        self.assertEqual(h.response_status, 302)

        c = self.conn.execute("SELECT * FROM contracts WHERE framework_no='INTERNET-VNPT-2026'").fetchone()
        self.assertIsNotNone(c)
        self.assertEqual(c["billing_type"], "RECURRING")
        self.assertEqual(float(c["recurring_fee"]), 15000000.0)
        self.assertEqual(c["recurring_period"], "MONTHLY")

        # 2. Test invoice reconciliation
        # Match 15,000,000 VND
        st, l_sum, a_sum, msg = invoices.check_invoice_payroll_reconciliation(
            self.conn, "INTERNET-VNPT-2026", 2026, 11, 15000000.0
        )
        self.assertEqual(st, "ok")
        self.assertIn("Matched Recurring Fee", msg)
        self.assertEqual(l_sum, 15000000.0)

        # Mismatch 18,000,000 VND
        st_mis, l_sum, a_sum, msg_mis = invoices.check_invoice_payroll_reconciliation(
            self.conn, "INTERNET-VNPT-2026", 2026, 11, 18000000.0
        )
        self.assertEqual(st_mis, "mismatch")
        self.assertIn("does not match expected recurring fee", msg_mis)

        # 3. Test Recurring dashboard view
        html_rec = payments.page_payments_recurring(month="2026-11")
        self.assertIn("INTERNET-VNPT-2026", html_rec)
        self.assertIn("FPT SOFTWARE", html_rec)
        self.assertIn("15,000,000 VND", html_rec)
        self.assertIn("Commitment for 2026-11", html_rec)
        self.assertIn("📥 Import Invoice", html_rec)
        self.assertIn("billing_type=RECURRING", html_rec)

        # Test Vendor filter on Recurring dashboard
        html_by_vendor = payments.page_payments_recurring(month="2026-11", vendor_id=str(self.seller_id))
        self.assertIn("INTERNET-VNPT-2026", html_by_vendor)
        html_other_vendor = payments.page_payments_recurring(month="2026-11", vendor_id="99999")
        self.assertNotIn("INTERNET-VNPT-2026", html_other_vendor)

        # Test Fee Reconciliation badge
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO invoices (
                shdon, tg_tttbso, nlap, seller_mst, seller_name, contract_no, service_year, service_month, created_at, updated_at
            ) VALUES ('INV-REC-01', 15000000.0, '2026-11-05', '0101234567', 'FPT SOFTWARE', 'INTERNET-VNPT-2026', 2026, 11, datetime('now'), datetime('now'))
        """)
        rec_inv_id = cur.lastrowid
        self.conn.commit()

        html_rec_matched = payments.page_payments_recurring(month="2026-11")
        self.assertIn("✓ Matched Fee", html_rec_matched)

        # Update invoice amount to 16,500,000 VND (mismatch +1,500,000)
        cur.execute("UPDATE invoices SET tg_tttbso = 16500000.0 WHERE id = ?", (rec_inv_id,))
        self.conn.commit()
        html_rec_mismatch = payments.page_payments_recurring(month="2026-11")
        self.assertIn("⚠️ Mismatch: +1,500,000 VND", html_rec_mismatch)

        # 4. Test Recurring cashout handler (Pay)
        body_cashout = (
            f"contract_id={c['id']}&service_month=2026-11&amount=15000000"
            f"&cashout_date=2026-11-20&action=pay"
        ).encode()
        h_co = MockHandler(body=body_cashout, headers={"content-length": str(len(body_cashout))})
        payments.handle_recurring_cashout_post(h_co)
        self.assertEqual(h_co.response_status, 302)

        payout = self.conn.execute("SELECT * FROM recurring_payouts WHERE contract_id=? AND service_month='2026-11'", (c["id"],)).fetchone()
        self.assertIsNotNone(payout)
        self.assertEqual(payout["status"], "PAID")
        self.assertEqual(payout["cashout_date"], "2026-11-20")

        # 5. Test Recurring cashout handler (Cancel)
        body_cancel = (
            f"contract_id={c['id']}&service_month=2026-11&action=cancel"
        ).encode()
        h_cancel = MockHandler(body=body_cancel, headers={"content-length": str(len(body_cancel))})
        payments.handle_recurring_cashout_post(h_cancel)
        self.assertEqual(h_cancel.response_status, 302)

        payout_cancelled = self.conn.execute("SELECT * FROM recurring_payouts WHERE contract_id=? AND service_month='2026-11'", (c["id"],)).fetchone()
        self.assertIsNone(payout_cancelled)

        # 6. Test Expiration / Validity filtering for recurring payments
        # Contract ends on 2026-12-31. In month 2027-01, it must NOT appear.
        html_2027_01 = payments.page_payments_recurring(month="2027-01")
        self.assertNotIn("INTERNET-VNPT-2026", html_2027_01)

        # Attempting to cashout for month 2027-01 must be rejected with 400
        body_invalid_month = (
            f"contract_id={c['id']}&service_month=2027-01&amount=15000000"
            f"&cashout_date=2027-01-10&action=pay"
        ).encode()
        h_inv = MockHandler(body=body_invalid_month, headers={"content-length": str(len(body_invalid_month))})
        payments.handle_recurring_cashout_post(h_inv)
        self.assertEqual(h_inv.response_status, 400)
        self.assertIn("Contract expired on", h_inv.get_output_text())

    def test_fixed_price_dashboard_view(self):
        import payments

        # 1. Create a contract and milestone
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO contracts (
              buyer_vendor_id, seller_vendor_id, framework_no, framework_name,
              contract_type, billing_type, contract_value, is_active, created_at, updated_at
            ) VALUES (?, ?, 'FP-DASH-01', 'Core System Revamp', 'STANDALONE', 'FIXED_PRICE', 500000000, 1, datetime('now'), datetime('now'))
        """, (self.buyer_id, self.seller_id))
        c_id = cur.lastrowid

        cur.execute("""
            INSERT INTO contract_milestones (
              contract_id, milestone_name, milestone_type, percentage, amount, planned_date, status, created_at, updated_at
            ) VALUES (?, 'Phase 1 Delivery', 'DELIVERY', 40.0, 200000000, '2026-06-30', 'PENDING', datetime('now'), datetime('now'))
        """, (c_id,))
        self.conn.commit()

        # 2. View Fixed Price dashboard
        html_fp = payments.page_payments_fixed_price()
        self.assertIn("FP-DASH-01", html_fp)
        self.assertIn("Phase 1 Delivery", html_fp)
        self.assertIn("200,000,000", html_fp)
        self.assertIn("Delivery", html_fp)
        self.assertIn("Total Milestones Committed", html_fp)

        # Overdue check: Planned date 2026-06-30 is in the past, status is PENDING -> must show Overdue
        self.assertIn("Overdue", html_fp)
        html_overdue = payments.page_payments_fixed_price(status="OVERDUE")
        self.assertIn("Phase 1 Delivery", html_overdue)

        # 3. Test Invoice Reconciliation on Fixed Price
        # Create an invoice linked to this milestone with matching amount (200,000,000 VND)
        cur.execute("""
            INSERT INTO invoices (
                shdon, tg_tttbso, nlap, seller_mst, seller_name, contract_no, milestone_id, created_at, updated_at
            ) VALUES ('INV-MATCH-01', 200000000.0, '2026-07-01', '0101234567', 'FPT SOFTWARE', 'FP-DASH-01', 1, datetime('now'), datetime('now'))
        """)
        inv_id = cur.lastrowid
        cur.execute("UPDATE contract_milestones SET invoice_id = ?, status = 'INVOICED' WHERE id = 1", (inv_id,))
        self.conn.commit()

        html_matched = payments.page_payments_fixed_price()
        self.assertIn("✓ Matched", html_matched)
        self.assertIn("INV-MATCH-01", html_matched)

        # Update invoice amount to mismatch (220,000,000 VND -> mismatch +20,000,000)
        cur.execute("UPDATE invoices SET tg_tttbso = 220000000.0 WHERE id = ?", (inv_id,))
        self.conn.commit()

        html_mismatch = payments.page_payments_fixed_price()
        self.assertIn("⚠️ Mismatch: +20,000,000 VND", html_mismatch)

    def test_payments_server_routes(self):
        # Test GET /payments (Dashboard route displaying T&M Cash-out)
        stub_pay = StubHandler("/payments", method="GET")
        stub_pay.do_GET()
        out_pay = stub_pay.get_output_text()
        self.assertIn("Fiscal Year Cash-out Overview", out_pay)
        self.assertIn("📊 Dashboard", out_pay)
        self.assertIn("/payments/fixed-price", out_pay)
        self.assertIn("/payments/recurring", out_pay)

        # Test GET /payments/fixed-price via server Handler
        stub_fp = StubHandler("/payments/fixed-price", method="GET")
        stub_fp.do_GET()
        out_fp = stub_fp.get_output_text()
        self.assertIn("Fixed Price Payments", out_fp)
        self.assertIn("Milestones Committed", out_fp)
        self.assertIn("📊 Dashboard", out_fp)

        # Test GET /payments/recurring via server Handler
        stub_rec = StubHandler("/payments/recurring", method="GET")
        stub_rec.do_GET()
        out_rec = stub_rec.get_output_text()
        self.assertIn("Recurring Services", out_rec)
        self.assertIn("Commitment for", out_rec)
        self.assertIn("📊 Dashboard", out_rec)

    def test_payments_dashboard_three_tabs_and_cashout_matrix(self):
        import attendance

        cur = self.conn.cursor()

        # 1. Setup a Fixed Price contract with milestones
        cur.execute("""
            INSERT INTO contracts (
              buyer_vendor_id, seller_vendor_id, framework_no, framework_name,
              contract_type, billing_type, contract_value, is_active, created_at, updated_at
            ) VALUES (?, ?, 'FP-MATRIX-01', 'Core Banking Upgrade', 'STANDALONE', 'FIXED_PRICE', 300000000, 1, datetime('now'), datetime('now'))
        """, (self.buyer_id, self.seller_id))
        fp_c_id = cur.lastrowid

        # Milestone 1: planned 2026-06-15, cashed out 2026-06-25 (Q1 Jun)
        cur.execute("""
            INSERT INTO contract_milestones (
              contract_id, milestone_name, milestone_type, percentage, amount, planned_date, cashout_date, status, created_at, updated_at
            ) VALUES (?, 'Milestone 1 Advance', 'ADVANCE', 30.0, 90000000, '2026-06-15', '2026-06-25', 'PAID', datetime('now'), datetime('now'))
        """, (fp_c_id,))

        # Milestone 2: planned 2026-11-20, no cashout yet (Q3 Nov)
        cur.execute("""
            INSERT INTO contract_milestones (
              contract_id, milestone_name, milestone_type, percentage, amount, planned_date, cashout_date, status, created_at, updated_at
            ) VALUES (?, 'Milestone 2 Delivery', 'DELIVERY', 70.0, 210000000, '2026-11-20', '', 'PENDING', datetime('now'), datetime('now'))
        """, (fp_c_id,))

        # 2. Setup a Recurring contract with payout
        cur.execute("""
            INSERT INTO contracts (
              buyer_vendor_id, seller_vendor_id, framework_no, framework_name,
              contract_type, billing_type, recurring_fee, recurring_period, start_date, end_date, is_active, created_at, updated_at
            ) VALUES (?, ?, 'REC-MATRIX-01', 'Cloud Leased Line', 'STANDALONE', 'RECURRING', 15000000, 'MONTHLY', '2026-04-01', '2027-03-31', 1, datetime('now'), datetime('now'))
        """, (self.buyer_id, self.seller_id))
        rec_c_id = cur.lastrowid

        # Payout for 2026-05, cashed out 2026-06-05
        cur.execute("""
            INSERT INTO recurring_payouts (
              contract_id, service_month, amount, status, cashout_date, created_at, updated_at
            ) VALUES (?, '2026-05', 15000000, 'PAID', '2026-06-05', datetime('now'), datetime('now'))
        """, (rec_c_id,))
        self.conn.commit()

        # 3. Test Dashboard Tab 1: Time & Material (T&M) default
        stub_tm = StubHandler("/payments?type=tm&fy=2026", method="GET")
        stub_tm.do_GET()
        html_tm = stub_tm.get_output_text()
        self.assertIn("Time & Material (T&M)", html_tm)
        self.assertIn("Fixed Price (Milestones)", html_tm)
        self.assertIn("Recurring Services (Internet / SaaS)", html_tm)
        self.assertIn("Framework / Annex", html_tm)
        self.assertIn("Total FY Payroll", html_tm)
        self.assertIn("Total FY Cash-out", html_tm)
        self.assertIn("/attendance", html_tm)

        # 4. Test Dashboard Tab 2: Fixed Price (Milestones)
        stub_fp = StubHandler("/payments?type=fixed_price&fy=2026", method="GET")
        stub_fp.do_GET()
        html_fp = stub_fp.get_output_text()
        self.assertIn("Fiscal Year Cash-out Overview - FY26 (Fixed Price)", html_fp)
        self.assertIn("Contract / Project", html_fp)
        self.assertIn("Total FY Planned", html_fp)
        self.assertIn("Total FY Cash-out", html_fp)
        self.assertIn("FP-MATRIX-01", html_fp)
        self.assertIn("Core Banking Upgrade", html_fp)
        self.assertIn("90,000,000", html_fp) # Milestone 1 planned & cashout in Jun
        self.assertIn("210,000,000", html_fp) # Milestone 2 planned in Nov
        self.assertIn("/payments/fixed-price", html_fp)

        # Tooltip breakdown check for Fixed Price
        self.assertIn("showCoTip", html_fp)
        self.assertIn("Milestone: Milestone 1 Advance", html_fp)

        # 5. Test Dashboard Tab 3: Recurring Services
        stub_rec = StubHandler("/payments?type=recurring&fy=2026", method="GET")
        stub_rec.do_GET()
        html_rec = stub_rec.get_output_text()
        self.assertIn("Fiscal Year Cash-out Overview - FY26 (Recurring Services)", html_rec)
        self.assertIn("Contract / Service", html_rec)
        self.assertIn("Total FY Fee", html_rec)
        self.assertIn("Total FY Cash-out", html_rec)
        self.assertIn("REC-MATRIX-01", html_rec)
        self.assertIn("Cloud Leased Line", html_rec)
        self.assertIn("15,000,000", html_rec)
        self.assertIn("/payments/recurring", html_rec)

        # 6. Test CSV Exports for Fixed Price & Recurring
        h_fp_exp = StubHandler("/payments/export?type=fixed_price&fy=2026", method="GET")
        h_fp_exp.do_GET()
        csv_fp = h_fp_exp.get_output_text()
        self.assertIn("Fixed Price Milestones", csv_fp)
        self.assertIn("Planned", csv_fp)
        self.assertIn("Cash-out", csv_fp)
        self.assertIn("FP-MATRIX-01", csv_fp)

        h_rec_exp = StubHandler("/payments/export?type=recurring&fy=2026", method="GET")
        h_rec_exp.do_GET()
        csv_rec = h_rec_exp.get_output_text()
        self.assertIn("Recurring Services", csv_rec)
        self.assertIn("Monthly Fee", csv_rec)
        self.assertIn("Cash-out", csv_rec)
        self.assertIn("REC-MATRIX-01", csv_rec)


class TestMultiModelInvoiceImport(BaseTestCase):
    def test_page_new_invoice_renders_three_tabs_and_preselected_model(self):
        # 1. Default load (origin is Invoices List)
        stub_def = StubHandler("/invoice/new", method="GET")
        stub_def.do_GET()
        html_def = stub_def.get_output_text()
        self.assertIn("Time & Material (T&M)", html_def)
        self.assertIn("Fixed Price (Milestones)", html_def)
        self.assertIn("Recurring Services (Internet / SaaS)", html_def)
        self.assertIn('Back to Invoices List', html_def)
        self.assertNotIn('forward to Attendance acceptance', html_def)

        # 2. Pre-selected Fixed Price model (origin is Fixed Price payments)
        stub_fp = StubHandler("/invoice/new?billing_type=FIXED_PRICE&contract_no=MHB/FSOFT/FP-2026-001", method="GET")
        stub_fp.do_GET()
        html_fp = stub_fp.get_output_text()
        self.assertIn('value="FIXED_PRICE"', html_fp)
        self.assertIn('id="tab_fp"', html_fp)
        self.assertIn('Back to Invoices List', html_fp)
        self.assertIn('forward to Fixed Price Payments', html_fp)
        self.assertNotIn('forward to Attendance acceptance', html_fp)

    def test_import_invoice_for_fixed_price_milestone(self):
        # 1. Setup Fixed Price contract with Milestone
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO contracts (
              buyer_vendor_id, seller_vendor_id, framework_no, framework_name,
              contract_type, billing_type, contract_value, is_active, created_at, updated_at
            ) VALUES (?, ?, 'FP-INV-001', 'Fixed Price Project', 'STANDALONE', 'FIXED_PRICE', 100000000, 1, datetime('now'), datetime('now'))
        """, (self.buyer_id, self.seller_id))
        c_id = cur.lastrowid

        cur.execute("""
            INSERT INTO contract_milestones (
              contract_id, milestone_name, milestone_type, percentage, amount, planned_date, status, created_at, updated_at
            ) VALUES (?, 'Milestone 1 Advance 50M', 'ADVANCE', 50.0, 50000000, '2026-05-15', 'PENDING', datetime('now'), datetime('now'))
        """, (c_id,))
        m_id = cur.lastrowid
        self.conn.commit()

        # Verify payments fixed-price dashboard renders Import Invoice button for this milestone
        html_fp_dash = payments.page_payments_fixed_price()
        self.assertIn("📥 Import Invoice", html_fp_dash)
        self.assertIn(f"milestone_id={m_id}", html_fp_dash)
        self.assertIn("contract_no=FP-INV-001", html_fp_dash)

        # Verify page_new_invoice pre-populates target milestone details
        stub_new = StubHandler(f"/invoice/new?billing_type=FIXED_PRICE&contract_no=FP-INV-001&milestone_id={m_id}", method="GET")
        stub_new.do_GET()
        html_new_inv = stub_new.get_output_text()
        self.assertIn("Target Payment Milestone", html_new_inv)
        self.assertIn("Milestone 1 Advance 50M", html_new_inv)
        self.assertIn("50,000,000 VND", html_new_inv)

        # 2. Post XML invoice targeting this milestone
        xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
        <HDon>
          <DLHDon>
            <TTChung>
              <KHHDon>1C26TUU</KHHDon>
              <SHDon>0088881</SHDon>
              <NLap>2026-05-20</NLap>
              <DVTTe>VND</DVTTe>
            </TTChung>
            <NDHDon>
              <NBan><Ten>FPT</Ten><MST>0102135934</MST></NBan>
              <NMua><Ten>MIZUHO</Ten><MST>0100234567</MST></NMua>
              <TToan><TgTTTBSo>50000000</TgTTTBSo></TToan>
            </NDHDon>
          </DLHDon>
        </HDon>
        """
        boundary = "----WebKitFormBoundaryFPTest123"
        body = f"""--{boundary}
Content-Disposition: form-data; name="import_type"

paste
--{boundary}
Content-Disposition: form-data; name="billing_type"

FIXED_PRICE
--{boundary}
Content-Disposition: form-data; name="contract_no_fp"

FP-INV-001
--{boundary}
Content-Disposition: form-data; name="milestone_id"

{m_id}
--{boundary}
Content-Disposition: form-data; name="xml_content"

{xml_content}
--{boundary}--""".replace("\n", "\r\n").encode("utf-8")

        handler = MockHandler(
            body=body,
            headers={
                "content-type": f"multipart/form-data; boundary={boundary}",
                "content-length": str(len(body))
            }
        )
        invoices.handle_new_invoice_post(handler)

        # Refresh connection
        self.conn.close()
        self.conn = common.db_connect()

        # 3. Verify invoice saved with milestone_id
        inv = self.conn.execute("SELECT * FROM invoices WHERE shdon='0088881'").fetchone()
        self.assertIsNotNone(inv)
        self.assertEqual(inv["contract_no"], "FP-INV-001")
        self.assertEqual(inv["milestone_id"], m_id)

        # 4. Verify milestone status updated to INVOICED and invoice_id linked
        m = self.conn.execute("SELECT * FROM contract_milestones WHERE id=?", (m_id,)).fetchone()
        self.assertEqual(m["status"], "INVOICED")
        self.assertEqual(m["invoice_id"], inv["id"])

        # 5. Verify payments fixed-price dashboard now shows the invoice and re-import option
        html_fp_after = payments.page_payments_fixed_price()
        self.assertIn("0088881", html_fp_after)
        self.assertIn("↺ Re-import", html_fp_after)

    def test_import_invoice_for_recurring_service(self):
        # 1. Setup Recurring Service Contract (e.g. 15,000,000 VND / month)
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO contracts (
              buyer_vendor_id, seller_vendor_id, framework_no, framework_name,
              contract_type, billing_type, recurring_fee, recurring_period, is_active, created_at, updated_at
            ) VALUES (?, ?, 'REC-INV-001', 'Dedicated Leased Line', 'STANDALONE', 'RECURRING', 15000000, 'MONTHLY', 1, datetime('now'), datetime('now'))
        """, (self.buyer_id, self.seller_id))
        c_id = cur.lastrowid
        self.conn.commit()

        # 2. Post XML invoice targeting recurring billing month 2026-11
        xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
        <HDon>
          <DLHDon>
            <TTChung>
              <KHHDon>1C26TUU</KHHDon>
              <SHDon>0088882</SHDon>
              <NLap>2026-11-25</NLap>
              <DVTTe>VND</DVTTe>
            </TTChung>
            <NDHDon>
              <NBan><Ten>VNPT</Ten><MST>0102135934</MST></NBan>
              <NMua><Ten>MIZUHO</Ten><MST>0100234567</MST></NMua>
              <TToan><TgTTTBSo>15000000</TgTTTBSo></TToan>
            </NDHDon>
          </DLHDon>
        </HDon>
        """
        boundary = "----WebKitFormBoundaryRecTest123"
        body = f"""--{boundary}
Content-Disposition: form-data; name="import_type"

paste
--{boundary}
Content-Disposition: form-data; name="billing_type"

RECURRING
--{boundary}
Content-Disposition: form-data; name="contract_no_rec"

REC-INV-001
--{boundary}
Content-Disposition: form-data; name="recurring_month"

2026-11
--{boundary}
Content-Disposition: form-data; name="xml_content"

{xml_content}
--{boundary}--""".replace("\n", "\r\n").encode("utf-8")

        handler = MockHandler(
            body=body,
            headers={
                "content-type": f"multipart/form-data; boundary={boundary}",
                "content-length": str(len(body))
            }
        )
        invoices.handle_new_invoice_post(handler)

        # Refresh connection
        self.conn.close()
        self.conn = common.db_connect()

        # 3. Verify invoice saved with service_year=2026 and service_month=11
        inv = self.conn.execute("SELECT * FROM invoices WHERE shdon='0088882'").fetchone()
        self.assertIsNotNone(inv)
        self.assertEqual(inv["contract_no"], "REC-INV-001")
        self.assertEqual(inv["service_year"], 2026)
        self.assertEqual(inv["service_month"], 11)

        # 4. Verify reconciliation check
        st, l_sum, a_sum, msg = invoices.check_invoice_payroll_reconciliation(
            self.conn, "REC-INV-001", 2026, 11, 15000000.0
        )
        self.assertEqual(st, "ok")
        self.assertIn("Matched Recurring Fee", msg)

    def test_logo_and_favicon_static_routes_and_layout(self):
        # 1. Test layout contains logo image and browser favicon link
        html = common.layout("Test Title", "<div>Content</div>")
        self.assertIn('<link rel="icon" type="image/png" href="/logo.png">', html)
        self.assertIn('<img src="/logo.png"', html)
        self.assertIn('height:64px', html)
        self.assertIn('alt="Mizuho Logo"', html)
        self.assertIn('Mizuho IT Outsourcing Vendor Hub</h1>', html)

        # 2. Test GET /logo.png via server StubHandler
        stub_logo = StubHandler("/logo.png", method="GET")
        stub_logo.do_GET()
        self.assertEqual(stub_logo.response_status, 200)
        self.assertIn("image/png", stub_logo.response_headers.get("content-type", ""))
        self.assertGreater(len(stub_logo.wfile.getvalue()), 1000)

        # 3. Test GET /favicon.ico via server StubHandler
        stub_fav = StubHandler("/favicon.ico", method="GET")
        stub_fav.do_GET()
        self.assertEqual(stub_fav.response_status, 200)
        self.assertIn("image/png", stub_fav.response_headers.get("content-type", ""))
        self.assertGreater(len(stub_fav.wfile.getvalue()), 1000)

    def test_offline_static_assets_and_no_external_cdns(self):
        # 1. Verify layout has no external links to fonts or cdns
        html = common.layout("Test", "<div>Body</div>")
        self.assertNotIn("fonts.googleapis.com", html)
        self.assertNotIn("fonts.gstatic.com", html)
        self.assertNotIn("cdnjs.cloudflare.com", html)
        self.assertNotIn("cdn.jsdelivr.net", html)
        self.assertIn('/static/js/jspdf.umd.min.js', html)

        # 2. Verify dashboard page has no external cdn links
        stub_dash = StubHandler("/dashboard", method="GET")
        stub_dash.do_GET()
        dash_html = stub_dash.get_output_text()
        self.assertNotIn("cdn.jsdelivr.net", dash_html)
        self.assertNotIn("cdnjs.cloudflare.com", dash_html)
        self.assertIn('/static/js/chart.umd.min.js', dash_html)

        # 3. Test static route serving chart.umd.min.js
        stub_chart = StubHandler("/static/js/chart.umd.min.js", method="GET")
        stub_chart.do_GET()
        self.assertEqual(stub_chart.response_status, 200)
        self.assertIn("application/javascript", stub_chart.response_headers.get("content-type", ""))
        self.assertGreater(len(stub_chart.wfile.getvalue()), 50000)

        # 4. Test static route serving jspdf.umd.min.js
        stub_jspdf = StubHandler("/static/js/jspdf.umd.min.js", method="GET")
        stub_jspdf.do_GET()
        self.assertEqual(stub_jspdf.response_status, 200)
        self.assertIn("application/javascript", stub_jspdf.response_headers.get("content-type", ""))
        self.assertGreater(len(stub_jspdf.wfile.getvalue()), 50000)

        # 5. Test HEAD request on static file
        stub_head = StubHandler("/static/js/chart.umd.min.js", method="HEAD")
        stub_head.do_HEAD()
        self.assertEqual(stub_head.response_status, 200)
        self.assertIn("application/javascript", stub_head.response_headers.get("content-type", ""))
        self.assertEqual(len(stub_head.wfile.getvalue()), 0)  # HEAD must not write body

        # 6. Test directory traversal protection
        stub_traversal = StubHandler("/static/../server.py", method="GET")
        stub_traversal.do_GET()
        self.assertIn(stub_traversal.response_status, (403, 404))

        # 7. Test non-existent static file
        stub_404 = StubHandler("/static/js/not_exist.js", method="GET")
        stub_404.do_GET()
        self.assertEqual(stub_404.response_status, 404)

    def test_config_ini_loading(self):
        import tempfile
        import shutil

        # Test default load from existing config.ini
        host, port, db_path = common.load_config()
        self.assertIn(host, ("127.0.0.1", "localhost", "0.0.0.0"))
        self.assertIsInstance(port, int)
        self.assertTrue(db_path.endswith(".sqlite3"))

        # Test loading custom config.ini via temporary file
        temp_dir = tempfile.mkdtemp()
        try:
            custom_ini = Path(temp_dir) / "config.ini"
            custom_ini.write_text(
                "[server]\nhost = 0.0.0.0\nport = 9999\n\n[database]\npath = custom.sqlite3\n",
                encoding="utf-8"
            )
            old_config_file = common.CONFIG_FILE
            old_env_port = os.environ.get("PORT")
            old_env_host = os.environ.get("HOST")
            old_env_db = os.environ.get("DB_PATH")
            try:
                # Clear env overrides temporarily
                os.environ.pop("PORT", None)
                os.environ.pop("HOST", None)
                os.environ.pop("DB_PATH", None)
                common.CONFIG_FILE = custom_ini

                c_host, c_port, c_db = common.load_config()
                self.assertEqual(c_host, "0.0.0.0")
                self.assertEqual(c_port, 9999)
                self.assertTrue(c_db.endswith("custom.sqlite3"))

                # Test environment variable overrides config.ini
                os.environ["PORT"] = "7777"
                _, env_port, _ = common.load_config()
                self.assertEqual(env_port, 7777)
            finally:
                common.CONFIG_FILE = old_config_file
                if old_env_port is not None:
                    os.environ["PORT"] = old_env_port
                else:
                    os.environ.pop("PORT", None)
                if old_env_host is not None:
                    os.environ["HOST"] = old_env_host
                else:
                    os.environ.pop("HOST", None)
                if old_env_db is not None:
                    os.environ["DB_PATH"] = old_env_db
                else:
                    os.environ.pop("DB_PATH", None)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestContractRenewal(BaseTestCase):
    def test_calculate_suggested_renewal_end_date(self):
        # 1-year duration
        sug1 = contracts.calculate_suggested_renewal_end_date("2025-01-01", "2025-12-31")
        self.assertEqual(sug1, "2026-12-31")

        # 6-month duration (~181 days)
        sug2 = contracts.calculate_suggested_renewal_end_date("2026-01-01", "2026-06-30")
        self.assertEqual(sug2, "2026-12-31")

        # Explicit period months
        sug3 = contracts.calculate_suggested_renewal_end_date("2026-01-01", "2026-03-31", period_months=3)
        self.assertEqual(sug3, "2026-06-30")

        # None or invalid input
        self.assertEqual(contracts.calculate_suggested_renewal_end_date(None, None), "")
        self.assertEqual(contracts.calculate_suggested_renewal_end_date("2025-01-01", ""), "")

    def test_get_contract_renewal_status(self):
        from datetime import date
        today = date(2026, 6, 1)

        # Active recurring contract (> 60 days left) - STANDALONE
        r_active = {"end_date": "2026-12-31", "contract_type": "STANDALONE", "billing_type": "RECURRING", "renewal_type": "MANUAL", "renewal_notice_days": 60}
        st_active = contracts.get_contract_renewal_status(r_active, today_date=today)
        self.assertEqual(st_active["status"], "ACTIVE")
        self.assertGreater(st_active["days_left"], 60)

        # Renewal Due recurring contract (<= 60 days left, MANUAL) - STANDALONE
        r_due = {"end_date": "2026-07-15", "contract_type": "STANDALONE", "billing_type": "RECURRING", "renewal_type": "MANUAL", "renewal_notice_days": 60}
        st_due = contracts.get_contract_renewal_status(r_due, today_date=today)
        self.assertEqual(st_due["status"], "RENEWAL_DUE")
        self.assertEqual(st_due["days_left"], 44)
        self.assertIn("Renewal Due", st_due["badge"])

        # FRAMEWORK recurring contract: NEVER enters RENEWAL_DUE because renewal is N/A for FRAMEWORK
        # 1. 44 days left (> 30 days notice for general contracts) -> ACTIVE, not RENEWAL_DUE
        r_fw = {"end_date": "2026-07-15", "contract_type": "FRAMEWORK", "billing_type": "RECURRING", "renewal_type": "MANUAL", "renewal_notice_days": 60}
        st_fw = contracts.get_contract_renewal_status(r_fw, today_date=today)
        self.assertEqual(st_fw["status"], "ACTIVE")
        self.assertNotEqual(st_fw["status"], "RENEWAL_DUE")

        # 2. 19 days left (<= 30 days notice) -> EXPIRING_SOON, not RENEWAL_DUE
        r_fw_soon = {"end_date": "2026-06-20", "contract_type": "FRAMEWORK", "billing_type": "RECURRING", "renewal_type": "MANUAL", "renewal_notice_days": 60}
        st_fw_soon = contracts.get_contract_renewal_status(r_fw_soon, today_date=today)
        self.assertEqual(st_fw_soon["status"], "EXPIRING_SOON")
        self.assertNotEqual(st_fw_soon["status"], "RENEWAL_DUE")
        self.assertIn("Ending soon", st_fw_soon["badge"])

        # Non-recurring contract (TM / Fixed Price): NEVER enters RENEWAL_DUE even if expiring soon
        r_tm = {"end_date": "2026-06-20", "contract_type": "STANDALONE", "billing_type": "TM", "renewal_type": "MANUAL", "renewal_notice_days": 60}
        st_tm = contracts.get_contract_renewal_status(r_tm, today_date=today)
        self.assertEqual(st_tm["status"], "EXPIRING_SOON")
        self.assertNotEqual(st_tm["status"], "RENEWAL_DUE")
        self.assertIn("Ending soon", st_tm["badge"])

        # Expired contract (< 0 days)
        r_exp = {"end_date": "2026-05-15", "contract_type": "STANDALONE", "billing_type": "RECURRING", "renewal_type": "MANUAL", "renewal_notice_days": 60}
        st_exp = contracts.get_contract_renewal_status(r_exp, today_date=today)
        self.assertEqual(st_exp["status"], "EXPIRED")
        self.assertEqual(st_exp["days_left"], -17)

        # No expiry contract
        r_no_exp = {"end_date": None, "contract_type": "STANDALONE", "billing_type": "RECURRING", "renewal_type": "MANUAL"}
        st_no_exp = contracts.get_contract_renewal_status(r_no_exp, today_date=today)
        self.assertEqual(st_no_exp["status"], "NO_EXPIRY")

    def test_contract_creation_defaults_and_custom_renewal(self):
        # 1. Create STANDALONE RECURRING contract with defaults -> defaults renewal_type to MANUAL and notice_days to 60
        body_rec_default = (
            f"contract_type=STANDALONE&buyer_vendor_id={self.buyer_id}&seller_vendor_id={self.seller_id}&"
            f"framework_no=MHB/DEF/01&framework_name=Default+Renewal&billing_type=RECURRING&start_date=2026-01-01&end_date=2026-12-31"
        ).encode()
        h_def = MockHandler(body=body_rec_default, headers={"content-length": str(len(body_rec_default))})
        contracts.handle_contract_create_post(h_def)
        self.assertEqual(h_def.response_status, 302)

        c_def = self.conn.execute("SELECT * FROM contracts WHERE framework_no='MHB/DEF/01'").fetchone()
        self.assertIsNotNone(c_def)
        self.assertEqual(c_def["contract_type"], "STANDALONE")
        self.assertEqual(c_def["renewal_type"], "MANUAL")
        self.assertEqual(c_def["renewal_notice_days"], 60)

        # 2. Create STANDALONE RECURRING contract with custom renewal policy
        body_custom = (
            f"contract_type=STANDALONE&buyer_vendor_id={self.buyer_id}&seller_vendor_id={self.seller_id}&"
            f"framework_no=MHB/AUTO/02&framework_name=Auto+Renewal&billing_type=RECURRING&start_date=2026-01-01&end_date=2026-12-31&"
            f"renewal_type=AUTO&renewal_notice_days=45&renewal_period_months=12&renewal_note=Automatic+annual+extension"
        ).encode()
        h_custom = MockHandler(body=body_custom, headers={"content-length": str(len(body_custom))})
        contracts.handle_contract_create_post(h_custom)
        self.assertEqual(h_custom.response_status, 302)

        c_custom = self.conn.execute("SELECT * FROM contracts WHERE framework_no='MHB/AUTO/02'").fetchone()
        self.assertIsNotNone(c_custom)
        self.assertEqual(c_custom["renewal_type"], "AUTO")
        self.assertEqual(c_custom["renewal_notice_days"], 45)
        self.assertEqual(c_custom["renewal_period_months"], 12)
        self.assertEqual(c_custom["renewal_note"], "Automatic annual extension")

        # 3. Create FRAMEWORK contract with RECURRING -> renewal_type is forced to NONE by matrix rule
        body_fw = (
            f"contract_type=FRAMEWORK&buyer_vendor_id={self.buyer_id}&seller_vendor_id={self.seller_id}&"
            f"framework_no=MHB/FW/03&framework_name=Framework+Contract&billing_type=RECURRING&renewal_type=AUTO"
        ).encode()
        h_fw = MockHandler(body=body_fw, headers={"content-length": str(len(body_fw))})
        contracts.handle_contract_create_post(h_fw)
        self.assertEqual(h_fw.response_status, 302)

        c_fw = self.conn.execute("SELECT * FROM contracts WHERE framework_no='MHB/FW/03'").fetchone()
        self.assertEqual(c_fw["renewal_type"], "NONE")

        # 4. Create STANDALONE non-recurring (TM) contract -> renewal_type is forced to NONE
        body_tm = (
            f"contract_type=STANDALONE&buyer_vendor_id={self.buyer_id}&seller_vendor_id={self.seller_id}&"
            f"framework_no=MHB/TM/03&framework_name=TM+Contract&billing_type=TM&renewal_type=AUTO"
        ).encode()
        h_tm = MockHandler(body=body_tm, headers={"content-length": str(len(body_tm))})
        contracts.handle_contract_create_post(h_tm)
        self.assertEqual(h_tm.response_status, 302)

        c_tm = self.conn.execute("SELECT * FROM contracts WHERE framework_no='MHB/TM/03'").fetchone()
        self.assertEqual(c_tm["renewal_type"], "NONE")

    def test_contract_update_renewal_policy(self):
        # Create a dedicated STANDALONE RECURRING contract
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO contracts (framework_no, framework_name, buyer_vendor_id, seller_vendor_id, contract_type, billing_type, start_date, end_date, renewal_type, renewal_notice_days, is_active, created_at, updated_at)
            VALUES ('MHB/SA/REC01', 'Standalone Rec', ?, ?, 'STANDALONE', 'RECURRING', '2025-01-01', '2026-12-31', 'MANUAL', 60, 1, '2025-01-01T00:00:00', '2025-01-01T00:00:00')
        """, (self.buyer_id, self.seller_id))
        standalone_id = cur.lastrowid
        self.conn.commit()

        body_update = (
            f"id={standalone_id}&contract_type=STANDALONE&buyer_vendor_id={self.buyer_id}&seller_vendor_id={self.seller_id}&"
            f"framework_no=MHB/SA/REC01&framework_name=Updated+Policy&billing_type=RECURRING&start_date=2025-01-01&end_date=2026-12-31&"
            f"renewal_type=AUTO&renewal_notice_days=90&renewal_period_months=6&renewal_note=Updated+terms"
        ).encode()
        h_up = MockHandler(body=body_update, headers={"content-length": str(len(body_update))})
        contracts.handle_contract_update_post(h_up)
        self.assertEqual(h_up.response_status, 302)

        c = self.conn.execute("SELECT * FROM contracts WHERE id=?", (standalone_id,)).fetchone()
        self.assertEqual(c["billing_type"], "RECURRING")
        self.assertEqual(c["renewal_type"], "AUTO")
        self.assertEqual(c["renewal_notice_days"], 90)
        self.assertEqual(c["renewal_period_months"], 6)
        self.assertEqual(c["renewal_note"], "Updated terms")

    def test_handle_contract_renew_post(self):
        # Create a dedicated STANDALONE RECURRING contract
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO contracts (framework_no, framework_name, buyer_vendor_id, seller_vendor_id, contract_type, billing_type, start_date, end_date, renewal_type, renewal_notice_days, is_active, created_at, updated_at)
            VALUES ('MHB/RENEW/01', 'Renewable Contract', ?, ?, 'STANDALONE', 'RECURRING', '2025-01-01', '2026-12-31', 'MANUAL', 60, 1, '2025-01-01T00:00:00', '2025-01-01T00:00:00')
        """, (self.buyer_id, self.seller_id))
        renew_cid = cur.lastrowid
        self.conn.commit()

        # Initial end_date is 2026-12-31
        body_renew = (
            f"id={renew_cid}&new_end_date=2027-12-31&renewal_note=Extension+Annex+02&return_to=/contracts"
        ).encode()
        h_renew = MockHandler(body=body_renew, headers={"content-length": str(len(body_renew))})
        contracts.handle_contract_renew_post(h_renew)
        self.assertEqual(h_renew.response_status, 302)

        c = self.conn.execute("SELECT * FROM contracts WHERE id=?", (renew_cid,)).fetchone()
        self.assertEqual(c["end_date"], "2027-12-31")
        self.assertIsNotNone(c["last_renewed_at"])
        self.assertIn("Extension Annex 02", c["renewal_note"])
        self.assertIn("Renewed to 2027-12-31", c["renewal_note"])

        # Check audit log
        audit = self.conn.execute("SELECT * FROM audit_logs WHERE record_id=? AND action='RENEW_CONTRACT'", (renew_cid,)).fetchone()
        self.assertIsNotNone(audit)
        self.assertIn("Renewed contract", audit["description"])

    def test_handle_contract_renew_validation(self):
        # Create a STANDALONE TM contract
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO contracts (framework_no, framework_name, buyer_vendor_id, seller_vendor_id, contract_type, billing_type, start_date, end_date, renewal_type, renewal_notice_days, is_active, created_at, updated_at)
            VALUES ('MHB/VAL/01', 'Validation Contract', ?, ?, 'STANDALONE', 'TM', '2025-01-01', '2026-12-31', 'NONE', 0, 1, '2025-01-01T00:00:00', '2025-01-01T00:00:00')
        """, (self.buyer_id, self.seller_id))
        val_cid = cur.lastrowid
        self.conn.commit()

        # 1. Reject renewal if contract is not RECURRING (e.g. TM)
        body_tm = f"id={val_cid}&new_end_date=2027-12-31".encode()
        h_tm = MockHandler(body=body_tm, headers={"content-length": str(len(body_tm))})
        contracts.handle_contract_renew_post(h_tm)
        self.assertEqual(h_tm.response_status, 400)
        self.assertIn("Contract renewal is only allowed for Standalone contracts with RECURRING billing type", h_tm.get_output_text())

        # 2. Reject renewal if contract is FRAMEWORK
        body_fw = f"id={self.contract_id}&new_end_date=2027-12-31".encode()
        h_fw = MockHandler(body=body_fw, headers={"content-length": str(len(body_fw))})
        contracts.handle_contract_renew_post(h_fw)
        self.assertEqual(h_fw.response_status, 400)
        self.assertIn("Contract renewal is only allowed for Standalone contracts with RECURRING billing type", h_fw.get_output_text())

        # Set val_cid to RECURRING for remaining validation tests
        self.conn.execute("UPDATE contracts SET billing_type='RECURRING' WHERE id=?", (val_cid,))
        self.conn.commit()

        # Missing new_end_date
        body_bad = f"id={val_cid}&new_end_date=&renewal_note=Test".encode()
        h_bad = MockHandler(body=body_bad, headers={"content-length": str(len(body_bad))})
        contracts.handle_contract_renew_post(h_bad)
        self.assertEqual(h_bad.response_status, 400)

        # Invalid ID
        body_invalid_id = b"id=abc&new_end_date=2027-12-31"
        h_inv = MockHandler(body=body_invalid_id, headers={"content-length": str(len(body_invalid_id))})
        contracts.handle_contract_renew_post(h_inv)
        self.assertEqual(h_inv.response_status, 400)

        # Non-existent ID
        body_not_found = b"id=999999&new_end_date=2027-12-31"
        h_nf = MockHandler(body=body_not_found, headers={"content-length": str(len(body_not_found))})
        contracts.handle_contract_renew_post(h_nf)
        self.assertEqual(h_nf.response_status, 404)

    def test_contract_list_and_renewal_ui(self):
        from datetime import date, timedelta
        soon = (date.today() + timedelta(days=10)).isoformat()

        # Insert a STANDALONE RECURRING contract expiring soon
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO contracts (framework_no, framework_name, buyer_vendor_id, seller_vendor_id, contract_type, billing_type, start_date, end_date, renewal_type, renewal_notice_days, is_active, created_at, updated_at)
            VALUES ('MHB/UI/01', 'UI Contract', ?, ?, 'STANDALONE', 'RECURRING', '2025-01-01', ?, 'MANUAL', 60, 1, '2025-01-01T00:00:00', '2025-01-01T00:00:00')
        """, (self.buyer_id, self.seller_id, soon))
        ui_cid = cur.lastrowid
        self.conn.commit()

        # 1. When contract is STANDALONE RECURRING and expires soon: shows Renewal Due and Renew button
        html_list = contracts.page_contracts_list(return_to="/contracts")
        self.assertIn("Manual-Renew", html_list)
        self.assertIn("Renewal Due", html_list)
        self.assertIn(f"openRenewalModal('{ui_cid}'", html_list)

        # View contract edit form for STANDALONE RECURRING contract
        c_row = self.conn.execute("SELECT * FROM contracts WHERE id=?", (ui_cid,)).fetchone()
        html_edit = contracts.page_contract_form("edit", c_row, [])
        self.assertIn("Contract Renewal & Validity", html_edit)
        self.assertIn("Recurring Renewal Policy", html_edit)
        self.assertIn("Standalone / Direct Contract", html_edit)

        # 2. When contract is STANDALONE TM (non-recurring): does NOT show Renewal Policy badge or Renew button
        self.conn.execute("UPDATE contracts SET billing_type='TM', end_date=?, renewal_type='NONE' WHERE id=?", (soon, ui_cid))
        self.conn.commit()

        html_list_tm = contracts.page_contracts_list(return_to="/contracts")
        self.assertNotIn(f"openRenewalModal('{ui_cid}'", html_list_tm)

        # Set back to RECURRING with MANUAL policy for server route test
        self.conn.execute("UPDATE contracts SET billing_type='RECURRING', renewal_type='MANUAL' WHERE id=?", (ui_cid,))
        self.conn.commit()

        # Check server route GET /contracts with renewal filter
        stub = StubHandler("/contracts?renewal_type=MANUAL&renewal_due=1", method="GET")
        stub.do_GET()
        self.assertEqual(stub.response_status, 200)
        self.assertIn("MHB/UI/01", stub.get_output_text())

        # Check server route POST /contract/renew
        body_post = f"id={ui_cid}&new_end_date=2028-06-30&renewal_note=Via+Server+Route".encode()
        stub_post = StubHandler("/contract/renew", method="POST", headers={"content-length": str(len(body_post))}, body=body_post)
        stub_post.do_POST()
        self.assertEqual(stub_post.response_status, 302)

        c_updated = self.conn.execute("SELECT end_date FROM contracts WHERE id=?", (ui_cid,)).fetchone()
        self.assertEqual(c_updated["end_date"], "2028-06-30")

    def test_matrix_contract_structure_rules(self):
        # Test 1: Transition from FRAMEWORK to STANDALONE blocked when active annexes exist
        body_invalid_transition = (
            f"id={self.contract_id}&contract_type=STANDALONE&buyer_vendor_id={self.buyer_id}&seller_vendor_id={self.seller_id}&"
            f"framework_no=MHB/FPT/2025/001&framework_name=Master+Agreement&billing_type=FIXED_PRICE"
        ).encode()
        h_fail = MockHandler(body=body_invalid_transition, headers={"content-length": str(len(body_invalid_transition))})
        contracts.handle_contract_update_post(h_fail)
        self.assertEqual(h_fail.response_status, 400)
        self.assertIn("Cannot change contract structure to Standalone", h_fail.get_output_text())

        # Test 2: Adding Annex to STANDALONE contract is rejected
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO contracts (framework_no, framework_name, buyer_vendor_id, seller_vendor_id, contract_type, billing_type, start_date, end_date, renewal_type, renewal_notice_days, is_active, created_at, updated_at)
            VALUES ('MHB/SA/TEST01', 'Standalone Matrix Test', ?, ?, 'STANDALONE', 'FIXED_PRICE', '2025-01-01', '2025-12-31', 'NONE', 0, 1, '2025-01-01T00:00:00', '2025-01-01T00:00:00')
        """, (self.buyer_id, self.seller_id))
        standalone_id = cur.lastrowid
        self.conn.commit()

        body_annex = (
            f"contract_id={standalone_id}&annex_no=ANX/INVALID/01&annex_name=Invalid+Annex&"
            f"billing_type=FIXED_PRICE&start_date=2025-01-01&end_date=2025-06-30&value_ceiling=50000"
        ).encode()
        h_annex = MockHandler(body=body_annex, headers={"content-length": str(len(body_annex))})
        contracts.handle_annex_create_post(h_annex)
        self.assertEqual(h_annex.response_status, 400)
        self.assertIn("Cannot add annex to a Standalone contract", h_annex.get_output_text())

        # Test 3: GET /annex/new for STANDALONE contract is rejected by server route
        stub_new = StubHandler(f"/annex/new?contract_id={standalone_id}", method="GET")
        stub_new.do_GET()
        self.assertEqual(stub_new.response_status, 400)
        self.assertIn("Cannot add annex to a Standalone contract", stub_new.get_output_text())

        # Test 4: Transition from STANDALONE to FRAMEWORK blocked when direct milestones exist
        cur.execute("""
            INSERT INTO contract_milestones (contract_id, annex_id, milestone_name, milestone_type, percentage, amount, planned_date, status, created_at, updated_at)
            VALUES (?, NULL, 'Milestone 1', 'ADVANCE', 50.0, 50000000, '2025-06-30', 'PENDING', '2025-01-01', '2025-01-01')
        """, (standalone_id,))
        self.conn.commit()

        body_sa_to_fw = (
            f"id={standalone_id}&contract_type=FRAMEWORK&buyer_vendor_id={self.buyer_id}&seller_vendor_id={self.seller_id}&"
            f"framework_no=MHB/SA/TEST01&framework_name=Converted+Framework&billing_type=FIXED_PRICE"
        ).encode()
        h_ms_fail = MockHandler(body=body_sa_to_fw, headers={"content-length": str(len(body_sa_to_fw))})
        contracts.handle_contract_update_post(h_ms_fail)
        self.assertEqual(h_ms_fail.response_status, 400)
        self.assertIn("Cannot change contract structure to Framework because it already has 1 direct milestone", h_ms_fail.get_output_text())

        # When milestone is removed, transition to FRAMEWORK is permitted
        cur.execute("DELETE FROM contract_milestones WHERE contract_id=?", (standalone_id,))
        self.conn.commit()

        h_ms_ok = MockHandler(body=body_sa_to_fw, headers={"content-length": str(len(body_sa_to_fw))})
        contracts.handle_contract_update_post(h_ms_ok)
        self.assertEqual(h_ms_ok.response_status, 302)
        c_fw_check = self.conn.execute("SELECT contract_type FROM contracts WHERE id=?", (standalone_id,)).fetchone()
        self.assertEqual(c_fw_check["contract_type"], "FRAMEWORK")

    def test_contract_summary_crud_and_search(self):
        from urllib.parse import quote_plus

        # 1. Create contract with contract_summary
        summary_text = "Annual cleaning service for 4th floor Hanoi office. Mon-Fri schedule."
        body_create = (
            f"contract_type=STANDALONE&buyer_vendor_id={self.buyer_id}&seller_vendor_id={self.seller_id}&"
            f"framework_no=MHB/GA/CLEAN-01&framework_name=Office+Cleaning&billing_type=RECURRING&"
            f"contract_summary={quote_plus(summary_text)}&start_date=2026-01-01&end_date=2026-12-31"
        ).encode()
        h_create = MockHandler(body=body_create, headers={"content-length": str(len(body_create))})
        contracts.handle_contract_create_post(h_create)
        self.assertEqual(h_create.response_status, 302)

        c = self.conn.execute("SELECT * FROM contracts WHERE framework_no='MHB/GA/CLEAN-01'").fetchone()
        self.assertIsNotNone(c)
        self.assertEqual(c["contract_summary"], summary_text)

        # 2. Update contract_summary
        updated_summary = "Updated cleaning service: 4th floor and 5th floor meeting rooms."
        body_update = (
            f"id={c['id']}&contract_type=STANDALONE&buyer_vendor_id={self.buyer_id}&seller_vendor_id={self.seller_id}&"
            f"framework_no=MHB/GA/CLEAN-01&framework_name=Office+Cleaning+Extended&billing_type=RECURRING&"
            f"contract_summary={quote_plus(updated_summary)}&start_date=2026-01-01&end_date=2026-12-31"
        ).encode()
        h_update = MockHandler(body=body_update, headers={"content-length": str(len(body_update))})
        contracts.handle_contract_update_post(h_update)
        self.assertEqual(h_update.response_status, 302)

        c_updated = self.conn.execute("SELECT * FROM contracts WHERE id=?", (c["id"],)).fetchone()
        self.assertEqual(c_updated["contract_summary"], updated_summary)

        # 3. Form rendering includes contract_summary in textarea
        form_html = contracts.page_contract_form("edit", c_updated, [])
        self.assertIn("Contract Summary / Scope Notes", form_html)
        self.assertIn(updated_summary, form_html)

        # 4. Contracts list includes contract_summary preview
        list_html = contracts.page_contracts_list(return_to="/contracts")
        self.assertIn(updated_summary, list_html)

        # 5. Search query matching words in contract_summary
        search_html = contracts.page_contracts_list(q="meeting rooms", return_to="/contracts")
        self.assertIn("MHB/GA/CLEAN-01", search_html)

    def test_recurring_service_month_expiration_validation(self):
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO contracts (
                framework_no, framework_name, buyer_vendor_id, seller_vendor_id,
                contract_type, billing_type, start_date, end_date, recurring_fee, recurring_period,
                renewal_type, renewal_notice_days, is_active, created_at, updated_at
            )
            VALUES ('MHB/NET/2026', 'Internet Service 2026', ?, ?, 'STANDALONE', 'RECURRING', '2026-01-01', '2026-12-31', 15000000, 'MONTHLY', 'MANUAL', 60, 1, '2026-01-01', '2026-01-01')
        """, (self.buyer_id, self.seller_id))
        rec_cid = cur.lastrowid
        self.conn.commit()

        # 1. Direct validation helper check:
        # Valid month: 2026-12 (within validity)
        ok_valid, msg_valid = invoices.validate_recurring_service_month(self.conn, 'MHB/NET/2026', 2026, 12)
        self.assertTrue(ok_valid)
        self.assertIsNone(msg_valid)

        # Invalid month: 2027-01 (month after expiration) -> Rejected!
        ok_exp, msg_exp = invoices.validate_recurring_service_month(self.conn, 'MHB/NET/2026', 2027, 1)
        self.assertFalse(ok_exp)
        self.assertIn("Invalid Billing Month: Service Month 2027-01 does not exist within the contract validity period", msg_exp)
        self.assertIn("Please renew the contract first", msg_exp)

        # Invalid month: 2025-12 (month prior to start date) -> Rejected!
        ok_pre, msg_pre = invoices.validate_recurring_service_month(self.conn, 'MHB/NET/2026', 2025, 12)
        self.assertFalse(ok_pre)
        self.assertIn("prior to contract start date", msg_pre)

        # 2. Form POST validation: handle_new_invoice_post rejecting month after expiration
        boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
        body_parts = [
            f"--{boundary}",
            'Content-Disposition: form-data; name="billing_type"',
            '',
            'RECURRING',
            f"--{boundary}",
            'Content-Disposition: form-data; name="contract_no_rec"',
            '',
            'MHB/NET/2026',
            f"--{boundary}",
            'Content-Disposition: form-data; name="recurring_month"',
            '',
            '2027-01',
            f"--{boundary}",
            'Content-Disposition: form-data; name="import_type"',
            '',
            'paste',
            f"--{boundary}",
            'Content-Disposition: form-data; name="xml_content"',
            '',
            '<invoice>test</invoice>',
            f"--{boundary}--",
            ''
        ]
        body_bytes = "\r\n".join(body_parts).encode("utf-8")
        headers = {
            "content-type": f"multipart/form-data; boundary={boundary}",
            "content-length": str(len(body_bytes))
        }
        h_inv = MockHandler(body=body_bytes, headers=headers)
        invoices.handle_new_invoice_post(h_inv)
        self.assertIn("Invalid Billing Month: Service Month 2027-01 does not exist within the contract validity period", h_inv.get_output_text())

        # 3. After renewing contract to 2027-12-31, 2027-01 is now valid
        self.conn.execute("UPDATE contracts SET end_date='2027-12-31' WHERE id=?", (rec_cid,))
        self.conn.commit()

        ok_renewed, msg_renewed = invoices.validate_recurring_service_month(self.conn, 'MHB/NET/2026', 2027, 1)
        self.assertTrue(ok_renewed)
        self.assertIsNone(msg_renewed)


if __name__ == "__main__":
    unittest.main()

