# server.py
# Run:
#   python server.py
#
# Open:
#   http://127.0.0.1:8000/           (Invoices)
#   http://127.0.0.1:8000/vendors    (Vendors)
#   http://127.0.0.1:8000/contracts  (Contracts)
#   http://127.0.0.1:8000/staff      (Contract Staff / HR)

import os
import sqlite3
import logging
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from html import escape

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(str(Path(__file__).resolve().with_name("app.log")), encoding="utf-8")
    ]
)
logger = logging.getLogger("server")


from common import (
    init_db, layout, send_html, HOST, PORT, DB_PATH, db_connect
)

from invoices import (
    page_invoices_list,
    page_invoice_detail,
    page_edit_invoice,
    page_raw_xml,
    handle_edit_invoice_post,
    handle_delete_invoice_post,
    page_new_invoice,
    handle_new_invoice_post,
    handle_toggle_mgs_sent_ajax,
    handle_force_match_post,
)

from dashboard import page_dashboard
from audit import page_audit_logs

from vendors import (
    page_vendors_list,
    page_vendor_form,
    handle_vendor_create_post,
    handle_vendor_update_post,
    handle_vendor_deactivate_post,
    handle_vendor_restore_post,
)

from contracts import (
    page_contracts_list,
    page_contract_form,
    page_annex_form,
    handle_contract_create_post,
    handle_contract_update_post,
    handle_contract_delete_post,
    handle_contract_restore_post,
    handle_annex_create_post,
    handle_annex_update_post,
    handle_annex_delete_post,
    handle_annex_restore_post,
    page_contract_references,
    handle_save_reference_ajax,
    handle_toggle_reference_lock_ajax,
)

from staff import (
    page_staff_list,
    page_staff_form,
    handle_staff_create_post,
    handle_staff_update_post,
    page_staff_shifts,
)
from attendance import (
    page_attendance,
    handle_attendance_import_post,
    handle_attendance_save_post,
    handle_attendance_lock_get,
    handle_attendance_unlock_get,
    handle_attendance_clear_get,
    page_monthly_attendance,
    handle_attendance_monthly_save_post,
    handle_attendance_monthly_lock_get,
    handle_attendance_monthly_unlock_get,
    handle_attendance_save_cell_post,
    handle_attendance_monthly_export_get,
)
from projects import (
    page_projects_list,
    handle_project_create_post,
    handle_project_delete_post,
    page_projects_assign,
    handle_project_assign_create_post,
    handle_project_assign_delete_post,
    handle_available_staff_ajax,
    handle_project_toggle_assignment_ajax,
)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        logger.info("%s - - [%s] %s" % (self.address_string(), self.log_date_time_string(), format % args))

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        try:
            # ---------------- Invoices ----------------
            if path == "/dashboard":
                page_dashboard(self)
                return

            if path == "/audit-logs":
                page_audit_logs(self)
                return

            if path == "/":
                filters = {
                    "year": qs["year"][0] if "year" in qs else None,
                    "month": qs["month"][0] if "month" in qs else None,
                    "day": qs["day"][0] if "day" in qs else None,
                    "q": qs["q"][0] if "q" in qs else None,
                }
                send_html(self, page_invoices_list(filters, return_to=self.path))
                return

            if path == "/invoice":
                invoice_id_raw = qs.get("id", [""])[0]
                if not invoice_id_raw.isdigit():
                    send_html(self, layout("Lỗi", "<div class='card danger'>Thiếu hoặc sai invoice id</div>"), status=400)
                    return
                send_html(self, page_invoice_detail(int(invoice_id_raw)))
                return

            if path == "/edit-invoice":
                invoice_id_raw = qs.get("id", [""])[0]
                if not invoice_id_raw.isdigit():
                    send_html(self, layout("Lỗi", "<div class='card danger'>Thiếu hoặc sai invoice id</div>"), status=400)
                    return
                send_html(self, page_edit_invoice(int(invoice_id_raw)))
                return

            if path == "/raw":
                invoice_id_raw = qs.get("id", [""])[0]
                if not invoice_id_raw.isdigit():
                    send_html(self, layout("Lỗi", "<div class='card danger'>Thiếu hoặc sai invoice id</div>"), status=400)
                    return
                send_html(self, page_raw_xml(int(invoice_id_raw)))
                return

            if path == "/invoice/new":
                send_html(self, page_new_invoice())
                return

            # ---------------- Vendors ----------------
            if path == "/vendors":
                q = qs.get("q", [""])[0]
                status = qs.get("status", ["active"])[0]
                send_html(self, page_vendors_list(q=q, status=status, return_to=self.path))
                return

            if path == "/vendor/new":
                send_html(self, page_vendor_form("new", None))
                return

            if path == "/vendor/edit":
                vendor_id_raw = qs.get("id", [""])[0]
                if not vendor_id_raw.isdigit():
                    send_html(self, layout("Lỗi", "<div class='card danger'>Thiếu hoặc sai vendor id</div>"), status=400)
                    return
                vendor_id = int(vendor_id_raw)

                conn = db_connect()
                try:
                    vendor = conn.execute("SELECT * FROM vendors WHERE id=?", (vendor_id,)).fetchone()
                finally:
                    conn.close()

                if not vendor:
                    send_html(
                        self,
                        layout("Không tìm thấy", f"<div class='card'>Không tìm thấy vendor id={vendor_id}. <a href='/vendors'>Quay lại</a></div>"),
                        status=404,
                    )
                    return

                send_html(self, page_vendor_form("edit", vendor))
                return

            if path == "/contracts":
                q = qs.get("q", [""])[0]
                status = qs.get("status", ["active"])[0]
                send_html(self, page_contracts_list(q=q, status=status, return_to=self.path))
                return

            if path == "/contracts/references":
                send_html(self, page_contract_references())
                return

            if path == "/contract/new":
                send_html(self, page_contract_form("new", None, [], None))
                return

            if path == "/contract/edit":
                cid = qs.get("id", [""])[0]
                if not cid.isdigit():
                    send_html(self, layout("Lỗi", "<div class='card danger'>Thiếu hoặc sai contract id</div>"), status=400)
                    return

                conn = db_connect()
                try:
                    c = conn.execute("SELECT * FROM contracts WHERE id=?", (int(cid),)).fetchone()
                    annexes = conn.execute(
                        "SELECT * FROM contract_annexes WHERE contract_id=? ORDER BY is_active DESC, id DESC",
                        (int(cid),),
                    ).fetchall()
                finally:
                    conn.close()

                if not c:
                    send_html(
                        self,
                        layout("Không tìm thấy", f"<div class='card'>Không tìm thấy contract id={cid}. <a href='/contracts'>Quay lại</a></div>"),
                        status=404,
                    )
                    return

                send_html(self, page_contract_form("edit", c, annexes, None))
                return

            if path == "/annex/new":
                cid = qs.get("contract_id", [""])[0]
                if not cid.isdigit():
                    send_html(self, layout("Lỗi", "<div class='card danger'>Thiếu hoặc sai contract_id</div>"), status=400)
                    return
                send_html(self, page_annex_form("new", None, int(cid), None))
                return

            if path == "/annex/edit":
                aid = qs.get("id", [""])[0]
                if not aid.isdigit():
                    send_html(self, layout("Lỗi", "<div class='card danger'>Thiếu hoặc sai annex id</div>"), status=400)
                    return

                conn = db_connect()
                try:
                    a = conn.execute("SELECT * FROM contract_annexes WHERE id=?", (int(aid),)).fetchone()
                finally:
                    conn.close()

                if not a:
                    send_html(
                        self,
                        layout("Không tìm thấy", f"<div class='card'>Không tìm thấy annex id={aid}. <a href='/contracts'>Quay lại</a></div>"),
                        status=404,
                    )
                    return

                send_html(self, page_annex_form("edit", a, int(a["contract_id"]), None))
                return

            # ---------------- Staff / HR ----------------
            if path == "/staff":
                q = qs.get("q", [""])[0]
                vendor_id = qs.get("vendor_id", [""])[0]
                contract_id = qs.get("contract_id", [""])[0]
                annex_id = qs.get("annex_id", [""])[0]
                status = qs.get("status", ["active"])[0]
                send_html(self, page_staff_list(q=q, vendor_id=vendor_id, contract_id=contract_id, annex_id=annex_id, status=status, return_to=self.path))
                return

            if path == "/staff/shifts":
                send_html(self, page_staff_shifts())
                return

            if path == "/attendance":
                filters = {
                    "month": qs.get("month", [""])[0],
                    "vendor_id": qs.get("vendor_id", [""])[0],
                    "contract_id": qs.get("contract_id", [""])[0],
                    "annex_id": qs.get("annex_id", [""])[0],
                    "q": qs.get("q", [""])[0],
                }
                send_html(self, page_attendance(filters))
                return



            if path == "/attendance/lock":
                handle_attendance_lock_get(self)
                return

            if path == "/attendance/unlock":
                handle_attendance_unlock_get(self)
                return

            if path == "/attendance/clear":
                handle_attendance_clear_get(self)
                return

            if path == "/attendance/monthly":
                filters = {
                    "month": qs.get("month", [""])[0],
                    "vendor_id": qs.get("vendor_id", [""])[0],
                    "contract_id": qs.get("contract_id", [""])[0],
                    "annex_id": qs.get("annex_id", [""])[0],
                    "q": qs.get("q", [""])[0],
                }
                send_html(self, page_monthly_attendance(filters))
                return

            if path == "/attendance/monthly/lock":
                handle_attendance_monthly_lock_get(self)
                return

            if path == "/attendance/monthly/unlock":
                handle_attendance_monthly_unlock_get(self)
                return

            if path == "/attendance/monthly/export":
                handle_attendance_monthly_export_get(self)
                return

            # ---------------- Projects ----------------
            if path == "/projects":
                err = qs.get("error", [None])[0]
                succ = qs.get("success", [None])[0]
                send_html(self, page_projects_list(error_msg=err, success_msg=succ))
                return

            if path == "/projects/assign":
                m = qs.get("month", [None])[0]
                pid = qs.get("project_id", [None])[0]
                vid = qs.get("vendor_id", [None])[0]
                err = qs.get("error", [None])[0]
                succ = qs.get("success", [None])[0]
                send_html(self, page_projects_assign(selected_month=m, selected_project_id=pid, selected_vendor_id=vid, error_msg=err, success_msg=succ))
                return

            if path == "/api/projects/available-staff":
                handle_available_staff_ajax(self)
                return

            if path == "/staff/new":
                return_to = qs.get("return_to", ["/staff"])[0]
                send_html(self, page_staff_form("new", None, None, return_to=return_to))
                return

            if path == "/staff/edit":
                sid = qs.get("id", [""])[0]
                if not sid.isdigit():
                    send_html(self, layout("Lỗi", "<div class='card danger'>Thiếu hoặc sai staff id</div>"), status=400)
                    return

                conn = db_connect()
                try:
                    staff_row = conn.execute("SELECT * FROM contract_staff WHERE id=?", (int(sid),)).fetchone()
                finally:
                    conn.close()

                if not staff_row:
                    send_html(
                        self,
                        layout("Không tìm thấy", f"<div class='card'>Không tìm thấy staff id={sid}. <a href='/staff'>Quay lại</a></div>"),
                        status=404,
                    )
                    return

                return_to = qs.get("return_to", ["/staff"])[0]
                send_html(self, page_staff_form("edit", staff_row, None, return_to=return_to))
                return



            # ---------------- 404 ----------------
            send_html(
                self,
                layout("404", f"<div class='card'>Không có đường dẫn: <code>{escape(path)}</code>. <a href='/'>Trang chủ</a></div>"),
                status=404,
            )

        except sqlite3.OperationalError as e:
            send_html(
                self,
                layout("Lỗi SQLite", f"<div class='card danger'><b>Lỗi SQLite:</b> <code>{escape(str(e))}</code></div>"),
                status=500,
            )

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            # ---------------- Invoices ----------------
            if path == "/edit-invoice":
                handle_edit_invoice_post(self)
                return

            if path == "/delete-invoice":
                handle_delete_invoice_post(self)
                return

            if path == "/invoice/create":
                handle_new_invoice_post(self)
                return

            if path == "/api/invoice/toggle-mgs-sent":
                handle_toggle_mgs_sent_ajax(self)
                return

            if path == "/invoice/force-match":
                handle_force_match_post(self)
                return

            # ---------------- Vendors ----------------
            if path == "/vendor/create":
                handle_vendor_create_post(self)
                return

            if path == "/vendor/update":
                handle_vendor_update_post(self)
                return

            if path == "/vendor/deactivate":
                handle_vendor_deactivate_post(self)
                return

            if path == "/vendor/restore":
                handle_vendor_restore_post(self)
                return

            # ---------------- Contracts ----------------
            if path == "/contract/create":
                handle_contract_create_post(self)
                return

            if path == "/contract/update":
                handle_contract_update_post(self)
                return

            if path == "/contract/delete":
                handle_contract_delete_post(self)
                return

            if path == "/contract/restore":
                handle_contract_restore_post(self)
                return

            if path == "/contracts/save-reference":
                handle_save_reference_ajax(self)
                return

            if path == "/api/contracts/toggle-reference-lock":
                handle_toggle_reference_lock_ajax(self)
                return

            # ---------------- Annexes ----------------
            if path == "/annex/create":
                handle_annex_create_post(self)
                return

            if path == "/annex/update":
                handle_annex_update_post(self)
                return

            if path == "/annex/delete":
                handle_annex_delete_post(self)
                return

            if path == "/annex/restore":
                handle_annex_restore_post(self)
                return

            # ---------------- Projects ----------------
            if path == "/project/create":
                handle_project_create_post(self)
                return

            if path == "/project/delete":
                handle_project_delete_post(self)
                return

            if path == "/project/assign/create":
                handle_project_assign_create_post(self)
                return

            if path == "/project/assign/delete":
                handle_project_assign_delete_post(self)
                return

            if path == "/api/projects/toggle-assignment":
                handle_project_toggle_assignment_ajax(self)
                return

            # ---------------- Staff / HR ----------------
            if path == "/staff/create":
                handle_staff_create_post(self)
                return

            if path == "/staff/update":
                handle_staff_update_post(self)
                return

            if path == "/attendance/import":
                handle_attendance_import_post(self)
                return



            if path == "/attendance/save":
                handle_attendance_save_post(self)
                return

            if path == "/attendance/monthly/save":
                handle_attendance_monthly_save_post(self)
                return

            if path == "/attendance/save-cell":
                handle_attendance_save_cell_post(self)
                return

            send_html(
                self,
                layout("404", f"<div class='card'>Không hỗ trợ POST: <code>{escape(path)}</code></div>"),
                status=404,
            )

        except sqlite3.OperationalError as e:
            send_html(
                self,
                layout("Lỗi SQLite", f"<div class='card danger'><b>Lỗi SQLite:</b> <code>{escape(str(e))}</code></div>"),
                status=500,
            )


def main():
    # Create/migrate DB tables (vendors + contracts + annexes + staff)
    init_db()

    logger.info(f"DB absolute path: {DB_PATH}")
    logger.info(f"Open:      http://{HOST}:{PORT}/")
    logger.info(f"Vendors:   http://{HOST}:{PORT}/vendors")
    logger.info(f"Contracts: http://{HOST}:{PORT}/contracts")
    logger.info(f"Staff:     http://{HOST}:{PORT}/staff")

    httpd = HTTPServer((HOST, PORT), Handler)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
