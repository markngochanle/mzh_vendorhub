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
TEST_DB_PATH = str(Path(__file__).resolve().with_name("test_db.sqlite3"))
common.DB_PATH = TEST_DB_PATH

# Import modules to test
import vendors
import contracts
import staff
import invoices
import attendance
import server


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
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except OSError:
                pass

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
                full_name_vi, vendor_id, project_name, position, contract_id, annex_id,
                joining_date, tentative_leaving_date, monthly_rate, manday_rate,
                paid_leave_total_hours, paid_leave_used_hours, ot, status, work_shift
            ) VALUES (?, ?, 'Core Banking', 'Developer', ?, ?, '2025-06-01', '2026-05-31', 45000000.0, 2000000.0, 12.0, 4.0, 1, NULL, '8:00 - 17:00')
        """, ('Nguyễn Văn An', self.seller_id, self.contract_id, self.annex_id))
        self.staff_id = cur.lastrowid

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


# ==================== 4. Test Staff / Shifts ====================
class TestStaff(BaseTestCase):
    def test_check_no_overlap(self):
        # 1. Same project overlap test
        ok, msg = staff.check_no_overlap(self.conn, None, self.seller_id, "Nguyễn Văn An", "2025-07-01", "2025-08-01")
        self.assertFalse(ok)
        self.assertIn("Overlap with", msg)

        # 2. Distinct name, no overlap issues
        ok_diff, msg_diff = staff.check_no_overlap(self.conn, None, self.seller_id, "Trần Thị Bình", "2025-07-01", "2025-08-01")
        self.assertTrue(ok_diff)

    def test_page_staff_shifts(self):
        html = staff.page_staff_shifts()
        self.assertIn("Nguyễn Văn An", html)
        self.assertIn("8:00 - 17:00", html)

    def test_handle_staff_create_post(self):
        body = f"full_name_vi=Lê+Hoàng+Long&vendor_id={self.seller_id}&contract_id={self.contract_id}&joining_date=2026-01-01&ot=1&work_shift=8%3A30+-+17%3A30".encode()
        handler = MockHandler(body=body, headers={"content-length": str(len(body))})
        staff.handle_staff_create_post(handler)
        
        self.assertEqual(handler.response_status, 302)
        inserted = self.conn.execute("SELECT * FROM contract_staff WHERE full_name_vi='Lê Hoàng Long'").fetchone()
        self.assertIsNotNone(inserted)
        self.assertEqual(inserted["work_shift"], "8:30 - 17:30")


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
        # 1. Setup mock monthly attendance summary for self.staff_id (Nguyễn Văn An, contract id=self.contract_id)
        # Nguyễn Văn An belongs to contract self.contract_id (framework_no = 'MHB/FPT/2025/001')
        cur = self.conn.cursor()
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
        
        # 3. Test HTML page list contains To MGS button
        html_list = invoices.page_invoices_list({}, return_to="/")
        self.assertIn("To MGS", html_list)
        
        # 4. Test HTML page detail contains To MGS button
        html_detail = invoices.page_invoice_detail(invoice_id)
        self.assertIn("To MGS", html_detail)

    def test_force_match(self):
        cur = self.conn.cursor()
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
        # 1. Lock attendance first so they appear in monthly summary
        handler_lock = MockHandler(path=f"/attendance/lock?staff_id={self.staff_id}&month=2026-06")
        attendance.handle_attendance_lock_get(handler_lock)

        # 2. Render monthly attendance summary
        html = attendance.page_monthly_attendance({"month": "2026-06"})
        self.assertIn("Nguyễn Văn An", html)
        self.assertIn("Monthly Payroll & Payment", html)

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

    def test_attendance_import_bulk(self):
        orig = attendance.parse_multipart_attendance
        attendance.parse_multipart_attendance = lambda h: {
            "month": ["2026-06"],
            "files": [{"filename": "face_log.csv", "content": b"""Date,Door,Device ID,Device,User Group,User,Event
2026-06-01 17:36:26,,538218377,MAIN DOOR,OSMale,378(Nguyen Van An),Face Succeed
2026-06-01 08:26:00,,538218382,MAIN DOOR,OSMale,378(Nguyen Van An),Face Succeed
2026-06-02 17:30:00,,538218377,MAIN DOOR,OSMale,111(Nonexistent User),Face Succeed
"""}]
        }
        try:
            # 1. Test GET page
            handler_get = MockHandler()
            html_get = attendance.page_attendance_import_bulk(handler_get)
            self.assertIn("Import dữ liệu chấm công từ Thư mục", html_get)

            # 2. Test POST upload
            handler_post = MockHandler()
            attendance.handle_attendance_import_bulk_post(handler_post)
            self.assertEqual(handler_post.response_status, 200)
            output = handler_post.get_output_text()
            self.assertIn("Đã hoàn thành xử lý file nhận diện khuôn mặt hàng loạt", output)
            self.assertIn("Nguyễn Văn An", output)
            self.assertIn("Nonexistent User", output)
        finally:
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
        finally:
            conn.close()


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
            ("/attendance/import-bulk", "Import dữ liệu chấm công từ Thư mục"),
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
        self.assertIn("Hợp đồng khung", html)

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


if __name__ == "__main__":
    unittest.main()
