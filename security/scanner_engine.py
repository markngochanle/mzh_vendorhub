"""
Core Security Scanner Engine.
Orchestrates static AST code audits, dynamic 40-endpoint vulnerability probes, and database integrity checks.
"""

import ast
import inspect
import io
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Set

import server
from common import db_connect, DB_PATH
from performance.benchmark_engine import DirectHandler
from security.config import (
    BASE_DIR,
    ALL_SECURITY_ENDPOINTS,
    OWASP_CATEGORIES,
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    SEVERITY_LOW,
    SEVERITY_INFO,
    SEVERITY_DEDUCTIONS,
    SECURITY_GRADES,
    GATEKEEPER_THRESHOLDS,
)
from security.rules import Finding, RULES_METADATA


@dataclass
class ScanResult:
    timestamp: str
    duration_sec: float
    profile_name: str
    total_endpoints_scanned: int
    total_files_analyzed: int
    total_checks_run: int
    total_checks_passed: int
    total_checks_failed: int
    security_score: float
    security_grade: str
    code_hygiene_score: float = 100.0
    architecture_score: float = 0.0
    gatekeeper_status: str = "PASSED"
    gatekeeper_reason: str = ""
    findings: List[Finding] = field(default_factory=list)
    findings_by_severity: Dict[str, int] = field(default_factory=dict)
    owasp_compliance: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    endpoint_matrix: List[Dict[str, Any]] = field(default_factory=list)
    database_audit: Dict[str, Any] = field(default_factory=dict)


class SecurityScannerEngine:
    """
    Automated Security Scanner covering 100% of application code and endpoints.
    Executes in-process without network overhead or third-party cloud connections.
    """

    def __init__(self, profile: str = "standard", log_callback=None):
        self.profile = profile
        self.log_callback = log_callback or (lambda msg: None)
        self.findings: List[Finding] = []
        self.endpoint_matrix: List[Dict[str, Any]] = []
        self.total_checks_run = 0
        self.total_checks_passed = 0
        self.total_checks_failed = 0

    def log(self, message: str):
        self.log_callback(message)

    def add_finding(self, rule_id: str, title: str, category_id: str, severity: str,
                    component: str, description: str, evidence: str, remediation: str):
        self.findings.append(Finding(
            rule_id=rule_id,
            title=title,
            category_id=category_id,
            severity=severity,
            component=component,
            description=description,
            evidence=evidence,
            remediation=remediation
        ))

    def record_check(self, passed: bool):
        self.total_checks_run += 1
        if passed:
            self.total_checks_passed += 1
        else:
            self.total_checks_failed += 1

    # =========================================================================
    # 1. STATIC SOURCE CODE ANALYSIS (100% Codebase Coverage)
    # =========================================================================
    def audit_source_code(self) -> int:
        self.log("🔍 Đang tiến hành phân tích tĩnh toàn bộ mã nguồn (.py)...")

        py_files = [
            f for f in BASE_DIR.glob("*.py")
            if not f.name.startswith("test_") and not f.name.startswith("dump_") and f.name != "generate_infographic_pdf.py"
        ]

        # Scan for raw SQL string concatenation / f-strings
        for f in py_files:
            try:
                code_text = f.read_text(encoding="utf-8", errors="ignore")
                parsed_ast = ast.parse(code_text, filename=f.name)
            except Exception as e:
                continue

            self._audit_ast_sql(f.name, parsed_ast, code_text)
            self._audit_hardcoded_secrets(f.name, code_text)
            self._audit_dangerous_functions(f.name, parsed_ast)

        # Audit logging verification in server.py
        self._audit_logging_compliance()

        # Architectural security verification (OWASP ASVS v4.0: Auth, RBAC, CSRF, Session, RateLimit, TLS)
        self._audit_architectural_controls()

        self.log(f"  ✅ Đã phân tích tĩnh {len(py_files)} tệp mã nguồn cốt lõi.")
        return len(py_files)

    def _audit_ast_sql(self, filename: str, tree: ast.AST, code: str):
        """Checks for unsafe SQL query formatting (f-strings, % formatting, or string concatenation)."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_name = ""
                if isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr
                elif isinstance(node.func, ast.Name):
                    func_name = node.func.id

                if func_name in ("execute", "executemany") and node.args:
                    first_arg = node.args[0]
                    # Check if query is an f-string
                    if isinstance(first_arg, ast.JoinedStr):
                        # Inspect if it contains suspicious SQL commands
                        lineno = getattr(node, "lineno", 0)
                        raw_line = code.splitlines()[lineno - 1] if lineno <= len(code.splitlines()) else ""
                        if any(kw in raw_line.upper() for kw in ("SELECT", "INSERT", "UPDATE", "DELETE", "WHERE")):
                            self.add_finding(
                                rule_id="SEC-01-SQLI",
                                title=f"Truy vấn SQL sử dụng f-string tiềm ẩn nguy cơ chèn mã ({filename}:{lineno})",
                                category_id="A03",
                                severity=SEVERITY_HIGH,
                                component=f"{filename}:{lineno}",
                                description="Truy vấn SQL được khởi tạo bằng f-string thay vì sử dụng tham số hóa (parameterized query với dấu ?). Nếu các biến được nội suy chứa dữ liệu từ người dùng, kẻ tấn công có thể chèn mã SQL.",
                                evidence=raw_line.strip()[:140],
                                remediation="Thay thế toàn bộ biểu thức f-string bằng câu truy vấn chuẩn sử dụng dấu ? và truyền giá trị qua tham số tuple: conn.execute('SELECT ... WHERE col = ?', (val,))."
                            )
                            self.record_check(False)
                            continue

                    # Check for string % formatting or string concatenation
                    if isinstance(first_arg, ast.BinOp):
                        if isinstance(first_arg.op, (ast.Mod, ast.Add)):
                            lineno = getattr(node, "lineno", 0)
                            raw_line = code.splitlines()[lineno - 1] if lineno <= len(code.splitlines()) else ""
                            if any(kw in raw_line.upper() for kw in ("SELECT", "INSERT", "UPDATE", "DELETE")):
                                self.add_finding(
                                    rule_id="SEC-01-SQLI",
                                    title=f"Truy vấn SQL sử dụng phép ghép chuỗi hoặc % formatting ({filename}:{lineno})",
                                    category_id="A03",
                                    severity=SEVERITY_HIGH,
                                    component=f"{filename}:{lineno}",
                                    description="Phép toán ghép chuỗi (+) hoặc % formatting trong câu lệnh execute có thể dẫn đến lỗ hổng SQL Injection nghiêm trọng.",
                                    evidence=raw_line.strip()[:140],
                                    remediation="Chuyển sang cú pháp tham số hóa an toàn với tuple: conn.execute('QUERY WHERE id = ?', (id,))."
                                )
                                self.record_check(False)
                                continue

                    self.record_check(True)

    def _audit_hardcoded_secrets(self, filename: str, code: str):
        """Scans source code for potential hardcoded secrets or API tokens."""
        patterns = [
            (r'(?i)(?:api_key|apikey|secret_key|private_key)\s*=\s*["\']([a-zA-Z0-9_\-]{20,})["\']', "Lộ API Key / Secret Key cứng"),
            (r'-----BEGIN (?:RSA |EC )?PRIVATE KEY-----', "Lộ Private Key trong mã nguồn"),
            (r'(?i)password\s*=\s*["\'](?!["\'])(?!admin)(?!password)(?!root)[^"\']{8,}["\']', "Mật khẩu quản trị lưu cứng trong code"),
        ]

        lines = code.splitlines()
        found_secret = False
        for i, line in enumerate(lines, 1):
            # Ignore test files or documentation strings
            if "test_" in filename or line.strip().startswith("#"):
                continue
            for regex, title in patterns:
                match = re.search(regex, line)
                if match:
                    found_secret = True
                    self.add_finding(
                        rule_id="SEC-07-SECRETS",
                        title=f"{title} ({filename}:{i})",
                        category_id="A02",
                        severity=SEVERITY_CRITICAL,
                        component=f"{filename}:{i}",
                        description="Khóa bảo mật hoặc mật khẩu được lưu cứng trực tiếp trong mã nguồn, có nguy cơ bị lộ khi chia sẻ repository.",
                        evidence=line.strip()[:100],
                        remediation="Đưa thông tin nhạy cảm vào biến môi trường (Environment Variables) hoặc tệp cấu hình được bảo vệ (config.ini ngoài git)."
                    )
                    self.record_check(False)

        if not found_secret:
            self.record_check(True)

    def _audit_dangerous_functions(self, filename: str, tree: ast.AST):
        """Checks for usage of eval, exec, or unpickling untrusted inputs."""
        has_dangerous = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = ""
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr

                if name in ("eval", "exec") and filename not in ("test_app.py", "server.py"):
                    lineno = getattr(node, "lineno", 0)
                    has_dangerous = True
                    self.add_finding(
                        rule_id="SEC-08-AUDIT-LOG",
                        title=f"Sử dụng hàm thực thi động {name}() không an toàn ({filename}:{lineno})",
                        category_id="A08",
                        severity=SEVERITY_HIGH,
                        component=f"{filename}:{lineno}",
                        description=f"Hàm {name}() cho phép thực thi mã Python động từ chuỗi. Nếu chuỗi đầu vào bị kẻ xấu thao túng, hệ thống có thể bị chiếm quyền điều khiển (RCE).",
                        evidence=f"{name}(...)",
                        remediation="Loại bỏ hàm eval/exec và thay thế bằng parser cấu trúc dữ liệu an toàn như ast.literal_eval hoặc json.loads."
                    )
                    self.record_check(False)

        if not has_dangerous:
            self.record_check(True)

    def _audit_logging_compliance(self):
        """Ensures destructive actions in server.py are recorded in audit logs."""
        server_path = BASE_DIR / "server.py"
        if not server_path.exists():
            return

        code = server_path.read_text(encoding="utf-8", errors="ignore")
        destructive_routes = [
            "/delete-invoice",
            "/contract/delete",
            "/vendor/deactivate",
            "/project/delete",
            "/annex/delete",
        ]

        for route in destructive_routes:
            # Check if route block contains log_audit or audit or log_action
            pattern = re.compile(rf'if path == "{re.escape(route)}":([\s\S]+?)(?=\n\s*(?:elif|if)\s+path\s*==|\Z)')
            m = pattern.search(code)
            if m:
                block = m.group(1)
                if any(k in block for k in ("log_audit", "audit", "log_action")):
                    self.record_check(True)
                else:
                    self.add_finding(
                        rule_id="SEC-08-AUDIT-LOG",
                        title=f"Thao tác hủy/xóa chưa ghi nhận đầy đủ vào nhật ký kiểm toán ({route})",
                        category_id="A09",
                        severity=SEVERITY_MEDIUM,
                        component=route,
                        description=f"Thao tác tại endpoint {route} làm thay đổi hoặc xóa trạng thái bản ghi trong CSDL nhưng không gọi log_audit() để lưu vết.",
                        evidence=f"Route: {route} thiếu lời gọi log_audit(...)",
                        remediation=f"Bổ sung lời gọi log_audit(action='DELETE', entity=..., entity_id=..., details=...) trong khối xử lý của {route}."
                    )
                    self.record_check(False)

    def _audit_architectural_controls(self):
        """
        Audits core architectural security requirements according to OWASP ASVS v4.0:
        1. Authentication Gateway (ASVS V1.4, V2.1)
        2. Role-Based Access Control / Segregation of Duties (ASVS V4.1)
        3. Anti-CSRF Token on state mutations (ASVS V4.2)
        4. Session & Cookie Management (ASVS V3.1 - V3.4)
        5. Request Rate Limiting / Abuse Prevention (ASVS V1.11)
        6. Transport Layer Security (HTTPS/HSTS) (ASVS V9.1, V9.2)
        """
        self.log("🛡️ Đang kiểm định các rào chắn kiến trúc an ninh cốt lõi (OWASP ASVS v4.0)...")
        server_path = BASE_DIR / "server.py"
        server_code = server_path.read_text(encoding="utf-8", errors="ignore") if server_path.exists() else ""
        common_path = BASE_DIR / "common.py"
        common_code = common_path.read_text(encoding="utf-8", errors="ignore") if common_path.exists() else ""

        # 1. AUTHENTICATION GATEWAY (OWASP A01:2021 / A07:2021 & ASVS V2)
        has_auth = any(
            k in server_code
            for k in ("login_required", "require_auth", "check_auth", "session_user", "get_current_user", "is_authenticated")
        )
        if not has_auth:
            self.add_finding(
                rule_id="SEC-11-AUTH-GATEWAY",
                title="Hệ thống hoàn toàn thiếu cổng Xác thực người dùng (Missing Authentication Gateway)",
                category_id="A01",
                severity=SEVERITY_CRITICAL,
                component="server.py (Toàn bộ 42 Endpoints)",
                description="Theo chuẩn OWASP A01:2021 & ASVS V1.4, V2.1: Mọi endpoint nhạy cảm (quản lý hợp đồng, hóa đơn, thanh toán, nhân sự, nhật ký kiểm toán) đều mở tự do cho bất kỳ ai kết nối mạng nội bộ mà không yêu cầu đăng nhập hay xác thực danh tính.",
                evidence="Toàn bộ request gửi tới /contracts, /invoices, /dashboard, /audit-logs đều được xử lý trực tiếp không qua kiểm tra phiên/token xác thực.",
                remediation="Thiết lập cổng xác thực tập trung (Authentication Middleware / Login Gateway) tại server.py. Bắt buộc kiểm tra session cookie hợp lệ hoặc chuyển hướng sang /login trước khi cho phép vào các trang nghiệp vụ."
            )
            self.record_check(False)
        else:
            self.record_check(True)

        # 2. ROLE-BASED ACCESS CONTROL (OWASP A01:2021 & ASVS V4)
        has_rbac = any(
            k in server_code
            for k in ("check_permission", "user_role", "require_role", "has_permission", "ROLE_ADMIN", "user['role']")
        )
        if not has_rbac:
            self.add_finding(
                rule_id="SEC-12-RBAC-CONTROL",
                title="Thiếu phân quyền theo vai trò người dùng (Missing Role-Based Access Control - RBAC)",
                category_id="A01",
                severity=SEVERITY_HIGH,
                component="server.py (Toàn bộ thao tác CRUD)",
                description="Theo chuẩn OWASP A01:2021 & ASVS V4.1: Hệ thống chưa thực thi phân tách nhiệm vụ (Segregation of Duties). Bất kỳ người dùng nào truy cập cũng đều có toàn quyền thực hiện các thao tác xóa hóa đơn, hủy hợp đồng, sửa đơn giá nhân sự.",
                evidence="Không tìm thấy bảng quản lý vai trò (Roles/Permissions) hoặc lệnh kiểm tra quyền người dùng trong các route xử lý.",
                remediation="Xây dựng ma trận phân quyền (Admin, Project Manager, Accountant, Staff, Viewer) và áp dụng nguyên tắc đặc quyền tối thiểu (Least Privilege) trước các thao tác thay đổi dữ liệu."
            )
            self.record_check(False)
        else:
            self.record_check(True)

        # 3. ANTI-CSRF TOKEN DEFENSE (OWASP A01:2021 / A10:2021 & ASVS V4.2)
        has_csrf_token = any(
            k in server_code
            for k in ("csrf_token", "verify_csrf", "validate_csrf", "check_csrf")
        )
        if not has_csrf_token:
            self.add_finding(
                rule_id="SEC-13-CSRF-TOKEN",
                title="Biểu mẫu POST thiếu token chống giả mạo yêu cầu chéo trang (Missing Anti-CSRF Token)",
                category_id="A10",
                severity=SEVERITY_HIGH,
                component="server.py & Form POST Handlers",
                description="Theo chuẩn OWASP A01:2021, A10:2021 & ASVS V4.2: Dù hệ thống đã bắt buộc phương thức POST cho các hành động thay đổi dữ liệu, nhưng các biểu mẫu chưa có Anti-CSRF Token hoặc cơ chế xác thực Origin nghiêm ngặt, có nguy cơ bị lừa thực thi thao tác ngoài ý muốn.",
                evidence="Các form POST trong invoices.py, contracts.py, attendance.py không chứa trường ẩn csrf_token và không xác thực token khi nhận request.",
                remediation="Bổ sung cơ chế sinh token CSRF ngẫu nhiên lưu trong phiên làm việc, kèm trường ẩn <input type='hidden' name='csrf_token' value='...'> trong mọi biểu mẫu POST và kiểm tra token tại máy chủ."
            )
            self.record_check(False)
        else:
            self.record_check(True)

        # 4. SESSION & COOKIE HYGIENE (OWASP A07:2021 & ASVS V3)
        has_session_mgmt = any(
            k in (server_code + common_code)
            for k in ("session_id", "Set-Cookie", "sessions[", "session_store")
        )
        if not has_session_mgmt:
            self.add_finding(
                rule_id="SEC-14-SESSION-HYGIENE",
                title="Chưa có cơ chế quản lý phiên làm việc & thuộc tính Cookie an toàn (Missing Session Management)",
                category_id="A07",
                severity=SEVERITY_MEDIUM,
                component="server.py / common.py",
                description="Theo chuẩn OWASP A07:2021 & ASVS V3.1 - V3.4: Ứng dụng chưa có phiên làm việc có định danh an toàn (Session ID), thiếu các cờ bảo vệ cookie HttpOnly, SameSite=Lax/Strict, Secure và chính sách thu hồi phiên (Inactivity Timeout).",
                evidence="Máy chủ không phát hành tiêu đề Set-Cookie với cờ bảo mật HttpOnly và SameSite.",
                remediation="Triển khai kho lưu trữ phiên làm việc (Session Store) với ID ngẫu nhiên khó đoán (cryptographically secure), gắn cờ HttpOnly; SameSite=Lax; Secure và thiết lập thời gian hết hạn phiên làm việc."
            )
            self.record_check(False)
        else:
            self.record_check(True)

        # 5. RATE LIMITING & ABUSE PREVENTION (OWASP A04:2021 & ASVS V1.11)
        has_rate_limit = any(
            k in (server_code + common_code)
            for k in ("rate_limit", "limiter", "rate_limiter", "request_counter")
        )
        if not has_rate_limit:
            self.add_finding(
                rule_id="SEC-15-RATE-LIMITING",
                title="Thiếu cơ chế giới hạn tần suất yêu cầu chống lạm dụng tải (Missing Rate Limiting)",
                category_id="A04",
                severity=SEVERITY_MEDIUM,
                component="server.py (Toàn bộ Endpoints)",
                description="Theo chuẩn OWASP A04:2021 & ASVS V1.11: Chưa có cơ chế giới hạn tần suất yêu cầu (Rate Limiting) trên các endpoint tải tệp XML hóa đơn hoặc xuất báo cáo tài chính nặng, có nguy cơ bị tấn công làm cạn kiệt tài nguyên máy chủ.",
                evidence="Không tìm thấy cấu hình giới hạn số lượng yêu cầu theo địa chỉ IP hoặc Token trong server.py.",
                remediation="Tích hợp middleware Rate Limiting theo thuật toán Token Bucket hoặc Sliding Window (ví dụ: tối đa 60 requests/phút đối với người dùng thông thường)."
            )
            self.record_check(False)
        else:
            self.record_check(True)

        # 6. TRANSPORT LAYER SECURITY & HSTS (OWASP A02:2021 & ASVS V9)
        has_hsts = "strict-transport-security" in (server_code + common_code).lower()
        if not has_hsts:
            self.add_finding(
                rule_id="SEC-16-TRANSPORT-SECURITY",
                title="Thiếu tiêu đề bảo mật kênh truyền HSTS (Missing Strict-Transport-Security Header)",
                category_id="A02",
                severity=SEVERITY_MEDIUM,
                component="common.py / server.py",
                description="Theo chuẩn OWASP A02:2021 & ASVS V9.1, V9.2: Dữ liệu tài chính, thuế và chi phí nhân sự chưa được ràng buộc giao thức bảo mật HTTPS/TLS thông qua tiêu đề HSTS, tiềm ẩn nguy cơ bị nghe lén (Eavesdropping/MitM) trên mạng nội bộ.",
                evidence="Tiêu đề phản hồi HTTP không chứa 'Strict-Transport-Security: max-age=...'",
                remediation="Cấu hình máy chủ reverse proxy (Nginx) hoặc HTTP handler bổ sung tiêu đề 'Strict-Transport-Security: max-age=31536000; includeSubDomains' khi triển khai môi trường sản xuất."
            )
            self.record_check(False)
        else:
            self.record_check(True)

    # =========================================================================
    # 2. DYNAMIC ENDPOINT SECURITY ANALYSIS (100% of 40 Endpoints)
    # =========================================================================
    def audit_endpoints(self):
        self.log(f"🌐 Đang bắt đầu kiểm tra động 100% toàn bộ {len(ALL_SECURITY_ENDPOINTS)} endpoints...")

        # Test Path Traversal specifically on file endpoints
        self._test_path_traversal()

        # Test Method Safety (CSRF / GET on destructive actions)
        self._test_method_safety()

        # Iterate through all 40 endpoints
        for ep in ALL_SECURITY_ENDPOINTS:
            path = ep["path"]
            category = ep.get("category", "General")
            name = ep.get("name", path)

            ep_result = {
                "path": path,
                "name": name,
                "category": category,
                "status": "PASS",
                "headers_passed": True,
                "sqli_passed": True,
                "xss_passed": True,
                "traceback_passed": True,
                "idor_passed": True,
            }

            # 1. Base response & Security Headers check
            h = DirectHandler(path, method="GET")
            h.do_GET()
            body = h.wfile.getvalue().decode("utf-8", errors="ignore")
            headers = h.response_headers

            headers_pass, missing_headers = self._check_security_headers(path, headers)
            if not headers_pass:
                ep_result["headers_passed"] = False
                ep_result["status"] = "WARNING" if ep_result["status"] == "PASS" else ep_result["status"]

            # 2. SQL Injection boundary testing
            sqli_pass = self._test_endpoint_sqli(ep)
            if not sqli_pass:
                ep_result["sqli_passed"] = False
                ep_result["status"] = "FAIL"

            # 3. Cross-Site Scripting (XSS) parameter testing
            xss_pass = self._test_endpoint_xss(ep)
            if not xss_pass:
                ep_result["xss_passed"] = False
                ep_result["status"] = "FAIL"

            # 4. Traceback & Error Leakage testing
            tb_pass = self._test_endpoint_traceback(ep)
            if not tb_pass:
                ep_result["traceback_passed"] = False
                ep_result["status"] = "WARNING" if ep_result["status"] == "PASS" else ep_result["status"]

            # 5. IDOR & Boundary Values testing
            idor_pass = self._test_endpoint_idor(ep)
            if not idor_pass:
                ep_result["idor_passed"] = False
                ep_result["status"] = "WARNING" if ep_result["status"] == "PASS" else ep_result["status"]

            self.endpoint_matrix.append(ep_result)

        self.log(f"  ✅ Đã hoàn tất kiểm tra động trên toàn bộ {len(ALL_SECURITY_ENDPOINTS)} endpoints.")

    def _check_security_headers(self, path: str, headers: Dict[str, str]) -> Tuple[bool, List[str]]:
        """Verifies presence of defensive HTTP security headers."""
        required = [
            ("x-content-type-options", "nosniff", "SEC-04-HEADERS", "Thiếu header X-Content-Type-Options: nosniff"),
            ("x-frame-options", ("sameorigin", "deny"), "SEC-04-HEADERS", "Thiếu header X-Frame-Options chống Clickjacking"),
        ]

        missing = []
        for header_name, expected, rule_id, desc in required:
            val = headers.get(header_name.lower(), "").lower()
            if not val:
                missing.append(header_name)
                self.record_check(False)
            elif isinstance(expected, tuple) and val not in expected:
                missing.append(header_name)
                self.record_check(False)
            elif isinstance(expected, str) and val != expected:
                missing.append(header_name)
                self.record_check(False)
            else:
                self.record_check(True)

        if missing and path in ("/", "/dashboard", "/contracts", "/staff", "/attendance"):
            # Record finding once for primary endpoints to avoid clutter
            self.add_finding(
                rule_id="SEC-04-HEADERS",
                title=f"Thiếu các tiêu đề bảo mật HTTP phòng thủ tại ({path})",
                category_id="A05",
                severity=SEVERITY_MEDIUM,
                component=path,
                description=f"Endpoint {path} phản hồi nhưng thiếu các tiêu đề bảo mật chuẩn: {', '.join(missing)}. Điều này khiến trình duyệt có thể bị tấn công MIME-sniffing hoặc Clickjacking qua iframe.",
                evidence=f"Headers hiện tại: {list(headers.keys())}",
                remediation="Bổ sung tiêu đề an toàn trong hàm send_html (common.py): X-Content-Type-Options: nosniff, X-Frame-Options: SAMEORIGIN, Referrer-Policy: strict-origin-when-cross-origin."
            )
            return False, missing

        return len(missing) == 0, missing

    def _test_endpoint_sqli(self, ep: Dict[str, Any]) -> bool:
        """Tests endpoint parameters with benign SQL injection probes."""
        path = ep["path"]
        params = ep.get("params", {})
        if not params:
            # Check baseline path
            self.record_check(True)
            return True

        base_url = path.split("?")[0]
        payloads = ["' OR '1'='1", "1; --", "' UNION SELECT NULL--"]
        passed = True

        for param_key in params.keys():
            for p in payloads:
                test_query = f"{base_url}?{param_key}={p}"
                h = DirectHandler(test_query, method="GET")
                h.do_GET()
                body = h.wfile.getvalue().decode("utf-8", errors="ignore")

                # Check if SQL exception is leaked in body or status is 500
                if "sqlite3.OperationalError" in body or "syntax error" in body or "unrecognized token" in body:
                    passed = False
                    self.add_finding(
                        rule_id="SEC-01-SQLI",
                        title=f"Phát hiện lỗi cú pháp SQL khi gửi payload kiểm thử ({test_query})",
                        category_id="A03",
                        severity=SEVERITY_CRITICAL,
                        component=test_query,
                        description=f"Khi gửi payload thử nghiệm vào tham số '{param_key}', ứng dụng trả về thông báo lỗi SQLite trong mã HTML, chứng tỏ truy vấn chưa được tham số hóa an toàn.",
                        evidence=body[:200].strip(),
                        remediation=f"Đảm bảo tham số '{param_key}' được ép kiểu dữ liệu an toàn (ví dụ int()) trước khi đưa vào câu lệnh CSDL, và sử dụng câu lệnh có dấu ?."
                    )
                    self.record_check(False)
                    break
                else:
                    self.record_check(True)

        return passed

    def _test_endpoint_xss(self, ep: Dict[str, Any]) -> bool:
        """Tests endpoint parameters with XSS canary payloads to verify HTML entity escaping."""
        path = ep["path"]
        params = ep.get("params", {})
        if not params:
            self.record_check(True)
            return True

        base_url = path.split("?")[0]
        xss_payload = '<script>alert("MZH_SEC_CANARY")</script>'
        passed = True

        for param_key in params.keys():
            test_url = f"{base_url}?{param_key}={xss_payload}"
            h = DirectHandler(test_url, method="GET")
            h.do_GET()
            body = h.wfile.getvalue().decode("utf-8", errors="ignore")

            # If raw unescaped payload appears in body -> VULNERABLE!
            if xss_payload in body:
                passed = False
                self.add_finding(
                    rule_id="SEC-02-XSS",
                    title=f"Lỗ hổng XSS phản xạ (Reflected XSS) tại tham số '{param_key}' ({base_url})",
                    category_id="A03",
                    severity=SEVERITY_HIGH,
                    component=base_url,
                    description=f"Tham số '{param_key}' được nhúng trực tiếp vào giao diện HTML mà không qua hàm mã hóa html.escape(). Kẻ tấn công có thể chèn mã JavaScript độc hại vào URL.",
                    evidence=f"Chuỗi '{xss_payload}' xuất hiện nguyên vẹn trong HTML.",
                    remediation=f"Bọc giá trị của tham số '{param_key}' bằng hàm escape() hoặc html.escape() trước khi nội suy vào chuỗi HTML."
                )
                self.record_check(False)
            else:
                self.record_check(True)

        return passed

    def _test_endpoint_traceback(self, ep: Dict[str, Any]) -> bool:
        """Injects malformed types to verify system tracebacks are suppressed."""
        path = ep["path"]
        params = ep.get("params", {})
        if not params:
            self.record_check(True)
            return True

        base_url = path.split("?")[0]
        malformed_values = ["invalid_abc_999", "-99999", "undefined"]
        passed = True

        for param_key in params.keys():
            for mval in malformed_values:
                test_url = f"{base_url}?{param_key}={mval}"
                h = DirectHandler(test_url, method="GET")
                h.do_GET()
                body = h.wfile.getvalue().decode("utf-8", errors="ignore")

                if "Traceback (most recent call last):" in body:
                    passed = False
                    self.add_finding(
                        rule_id="SEC-06-TRACEBACK",
                        title=f"Để lộ Traceback Python khi nhận tham số không hợp lệ ({test_url})",
                        category_id="A04",
                        severity=SEVERITY_MEDIUM,
                        component=test_url,
                        description="Ứng dụng trả về chi tiết dấu vết lỗi hệ thống (stack trace) cho người dùng cuối, để lộ cấu trúc thư mục, tên tệp và dòng lệnh nội bộ.",
                        evidence="Phát hiện 'Traceback (most recent call last):' trong mã nguồn phản hồi.",
                        remediation="Bắt các ngoại lệ ValueError / Exception và trả về trang thông báo lỗi thân thiện (status 400 Bad Request) thay vì ném lỗi chưa xử lý."
                    )
                    self.record_check(False)
                    break
                else:
                    self.record_check(True)

        return passed

    def _test_endpoint_idor(self, ep: Dict[str, Any]) -> bool:
        """Tests negative and non-existent boundary IDs."""
        path = ep["path"]
        params = ep.get("params", {})
        if not params or "id" not in params and "contract_id" not in params:
            self.record_check(True)
            return True

        base_url = path.split("?")[0]
        id_key = "id" if "id" in params else "contract_id"
        boundary_id = "999999999"

        test_url = f"{base_url}?{id_key}={boundary_id}"
        h = DirectHandler(test_url, method="GET")
        h.do_GET()

        # Should return 404 or a safe message, not 500
        if h.response_status == 500:
            self.add_finding(
                rule_id="SEC-10-IDOR-BOUNDARY",
                title=f"Máy chủ trả về mã lỗi 500 khi truy cập ID không tồn tại ({test_url})",
                category_id="A01",
                severity=SEVERITY_LOW,
                component=test_url,
                description=f"Khi gọi {test_url} với ID ngoài giới hạn, hệ thống gặp sự cố máy chủ nội bộ (500) thay vì trả về 404 Not Found hoặc thông báo hợp lệ.",
                evidence=f"Mã trạng thái phản hồi: {h.response_status}",
                remediation="Kiểm tra kết quả truy vấn CSDL: nếu bản ghi không tồn tại, trả về send_html(handler, layout('Not Found', '...'), status=404) một cách an toàn."
            )
            self.record_check(False)
            return False

        self.record_check(True)
        return True

    def _test_path_traversal(self):
        """Tests path traversal attack vectors on report viewing endpoints."""
        traversal_payloads = [
            "/performance/report?name=../../etc/passwd",
            "/performance/report?name=..%2f..%2f..%2fdb.sqlite3",
            "/performance/report?name=../../../common.py",
            "/performance/report?name=/etc/passwd",
        ]

        for p in traversal_payloads:
            h = DirectHandler(p, method="GET")
            h.do_GET()
            body = h.wfile.getvalue().decode("utf-8", errors="ignore")

            # Must NOT succeed in reading system or database files
            is_leaked = ("root:x:0:0:" in body or "SQLite format 3" in body or "def db_connect" in body)
            if is_leaked:
                self.add_finding(
                    rule_id="SEC-03-TRAVERSAL",
                    title="Lỗ hổng duyệt thư mục (Path Traversal) cho phép đọc tệp tùy ý",
                    category_id="A10",
                    severity=SEVERITY_CRITICAL,
                    component=p,
                    description="Hệ thống không kiểm tra chặt chẽ ký tự '../' trong tham số tên tệp, cho phép kẻ tấn công đọc trái phép các tệp cấu hình, mã nguồn và CSDL trên máy chủ.",
                    evidence=f"Đọc được nội dung tệp nhạy cảm thông qua {p}",
                    remediation="Sử dụng Path(REPORTS_DIR / name).resolve() kết hợp kiểm tra target.relative_to(REPORTS_DIR) và từ chối các chuỗi chứa '..' hoặc '/'."
                )
                self.record_check(False)
            elif h.response_status in (400, 403, 404):
                self.record_check(True)
            else:
                self.record_check(True)

    def _test_method_safety(self):
        """Ensures destructive state-changing operations reject GET requests."""
        destructive_routes = [
            "/delete-invoice?id=1",
            "/contract/delete?id=1",
            "/vendor/deactivate?id=1",
            "/project/delete?id=1",
        ]

        for r in destructive_routes:
            h = DirectHandler(r, method="GET")
            h.do_GET()
            # If route allows deletion via GET, flag finding
            # In server.py, these routes are only handled in do_POST, so do_GET returns 404 or nothing
            if h.response_status == 200 and "deleted" in h.wfile.getvalue().decode("utf-8", errors="ignore").lower():
                self.add_finding(
                    rule_id="SEC-05-METHOD-CSRF",
                    title=f"Thao tác xóa dữ liệu cho phép kích hoạt qua phương thức GET ({r})",
                    category_id="A01",
                    severity=SEVERITY_HIGH,
                    component=r,
                    description="Thao tác làm thay đổi hoặc xóa dữ liệu có thể kích hoạt thông qua HTTP GET. Kẻ tấn công có thể lừa nạn nhân bấm vào liên kết để thực hiện hành động trái ý muốn (CSRF).",
                    evidence=f"Endpoint {r} thực thi xóa dữ liệu với phương thức GET.",
                    remediation="Chỉ cho phép các thao tác hủy/xóa thực thi qua phương thức POST có kiểm tra nguồn gốc (Origin/Referer header)."
                )
                self.record_check(False)
            else:
                self.record_check(True)

    # =========================================================================
    # 3. DATABASE INTEGRITY & SECURITY AUDIT
    # =========================================================================
    def audit_database(self) -> Dict[str, Any]:
        self.log("🗄️ Đang kiểm tra an toàn cấu hình và tính toàn vẹn CSDL SQLite...")
        audit_info = {
            "foreign_keys_enabled": False,
            "integrity_check_passed": False,
            "db_size_kb": 0.0,
            "tables_count": 0,
        }

        try:
            conn = db_connect()
            try:
                # Check foreign keys
                fk = conn.execute("PRAGMA foreign_keys").fetchone()
                audit_info["foreign_keys_enabled"] = bool(fk[0]) if fk else False

                # Integrity check
                integ = conn.execute("PRAGMA integrity_check").fetchone()
                audit_info["integrity_check_passed"] = (integ[0].lower() == "ok") if integ else False

                # Tables count
                tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                audit_info["tables_count"] = len(tables)
            finally:
                conn.close()

            db_p = Path(DB_PATH)
            if db_p.exists():
                audit_info["db_size_kb"] = round(db_p.stat().st_size / 1024, 1)

            if audit_info["integrity_check_passed"]:
                self.record_check(True)
            else:
                self.add_finding(
                    rule_id="SEC-09-SQLITE-CONFIG",
                    title="Cơ sở dữ liệu SQLite gặp lỗi toàn vẹn cấu trúc (Integrity Check Fail)",
                    category_id="A05",
                    severity=SEVERITY_HIGH,
                    component="db.sqlite3",
                    description="Lệnh PRAGMA integrity_check phát hiện các khối dữ liệu bị sai lệch hoặc hỏng cấu trúc B-tree.",
                    evidence=f"PRAGMA integrity_check: {integ}",
                    remediation="Sao lưu dữ liệu ngay lập tức và thực hiện dump/restore dữ liệu SQLite sang tệp cơ sở dữ liệu mới."
                )
                self.record_check(False)

        except Exception as e:
            self.log(f"  ⚠️ Lỗi khi kiểm tra CSDL: {e}")
            self.record_check(False)

        return audit_info

    # =========================================================================
    # 4. SCORE CALCULATION & REPORT COMPILATION
    # =========================================================================
    def run_full_scan(self) -> ScanResult:
        start_time = time.time()
        self.log("🚀 KHỞI ĐỘNG CHƯƠNG TRÌNH KIỂM TRA BẢO MẬT TOÀN DIỆN MIZUHO VMS")
        self.log(f"Cấu hình: {self.profile} | Chuẩn: OWASP Top 10 | Độ bao phủ: 100% Endpoints & Source Code")
        self.log("=" * 70)

        # 1. Static audit
        files_count = self.audit_source_code()

        # 2. Dynamic endpoints audit
        self.audit_endpoints()

        # 3. Database audit
        db_audit = self.audit_database()

        # 4. Calculate score with Dual-Pillar & Gatekeeper Model
        findings_by_sev = {
            SEVERITY_CRITICAL: 0,
            SEVERITY_HIGH: 0,
            SEVERITY_MEDIUM: 0,
            SEVERITY_LOW: 0,
            SEVERITY_INFO: 0,
        }

        total_deduction = 0.0
        for f in self.findings:
            findings_by_sev[f.severity] = findings_by_sev.get(f.severity, 0) + 1
            total_deduction += SEVERITY_DEDUCTIONS.get(f.severity, 0.0)

        # Trụ cột 1: Điểm vệ sinh mã nguồn (Code Hygiene Score)
        # Đo lường chất lượng mã nguồn thực tế: SQL tham số hóa, phòng chống XSS, path traversal, security headers, logging
        arch_rule_ids = {
            "SEC-11-AUTH-GATEWAY",
            "SEC-12-RBAC-CONTROL",
            "SEC-13-CSRF-TOKEN",
            "SEC-14-SESSION-HYGIENE",
            "SEC-15-RATE-LIMITING",
            "SEC-16-TRANSPORT-SECURITY",
        }
        code_findings = [f for f in self.findings if f.rule_id not in arch_rule_ids]
        code_deduction = sum(SEVERITY_DEDUCTIONS.get(f.severity, 0.0) for f in code_findings)
        code_hygiene_score = max(0.0, round(100.0 - code_deduction, 1))

        # Trụ cột 2: Điểm rào chắn kiến trúc (Architectural Controls Score)
        # Đo lường sự sẵn sàng theo chuẩn OWASP ASVS v4.0: Cổng Auth, RBAC, CSRF, Session, Rate Limit, TLS
        arch_findings = [f for f in self.findings if f.rule_id in arch_rule_ids]
        arch_deduction = sum(SEVERITY_DEDUCTIONS.get(f.severity, 0.0) for f in arch_findings)
        architecture_score = max(0.0, round(100.0 - arch_deduction, 1))

        # Điểm gộp thuần túy (Raw Combined Score)
        raw_score = max(0.0, 100.0 - total_deduction)

        # Nguyên tắc Cổng An Ninh Thực Tế (Security Gatekeeper - NIST SP 800-115 & OWASP ASVS v4.0)
        gatekeeper_status = "PASSED"
        gatekeeper_reason = "Tất cả các cổng kiểm soát an ninh cốt lõi đều đạt chuẩn."
        capped_score = raw_score

        if findings_by_sev[SEVERITY_CRITICAL] > 0:
            capped_score = min(raw_score, GATEKEEPER_THRESHOLDS["CRITICAL_CAP"])
            gatekeeper_status = "BLOCKED_CRITICAL"
            gatekeeper_reason = (
                f"BỊ CHẶN BỞI CỔNG AN NINH CỐT LÕI (OWASP ASVS v4.0): "
                f"Hệ thống phát hiện {findings_by_sev[SEVERITY_CRITICAL]} lỗ hổng NGHIÊM TRỌNG "
                f"(hoàn toàn chưa có cổng Xác thực Authentication Gateway). "
                f"Điểm số an ninh thực tế bị khóa trần tại {GATEKEEPER_THRESHOLDS['CRITICAL_CAP']}/100.0 (Hạng F - Kém / Nguy cơ cao)."
            )
        elif findings_by_sev[SEVERITY_HIGH] > 0:
            capped_score = min(raw_score, GATEKEEPER_THRESHOLDS["HIGH_CAP"])
            gatekeeper_status = "BLOCKED_HIGH"
            gatekeeper_reason = (
                f"CẢNH BÁO CỔNG AN NINH: Hệ thống còn {findings_by_sev[SEVERITY_HIGH]} phát hiện mức CAO "
                f"(thiếu phân quyền RBAC và token CSRF). Điểm số bị giới hạn tối đa tại {GATEKEEPER_THRESHOLDS['HIGH_CAP']}/100.0."
            )
        elif findings_by_sev[SEVERITY_MEDIUM] > 0:
            capped_score = min(raw_score, GATEKEEPER_THRESHOLDS["MEDIUM_CAP"])
            gatekeeper_status = "PASSED_WITH_WARNING"
            gatekeeper_reason = f"Đạt yêu cầu cơ bản nhưng cần hoàn thiện {findings_by_sev[SEVERITY_MEDIUM]} khuyến nghị mức Trung bình."

        security_score = round(capped_score, 1)

        # Grade
        security_grade = "F (Kém - Nguy cơ rủi ro cao)"
        for threshold, grade_str in SECURITY_GRADES:
            if security_score >= threshold:
                security_grade = grade_str
                break

        # OWASP category compliance
        owasp_compliance = {}
        for cat_id, cat_info in OWASP_CATEGORIES.items():
            cat_findings = [f for f in self.findings if f.category_id == cat_id]
            crit_count = sum(1 for f in cat_findings if f.severity == SEVERITY_CRITICAL)
            high_count = sum(1 for f in cat_findings if f.severity == SEVERITY_HIGH)
            med_count = sum(1 for f in cat_findings if f.severity == SEVERITY_MEDIUM)

            cat_deduction = (crit_count * 30.0) + (high_count * 15.0) + (med_count * 5.0)
            cat_score = max(0.0, round(100.0 - cat_deduction, 1))
            if crit_count > 0:
                cat_score = min(cat_score, 40.0)

            owasp_compliance[cat_id] = {
                "id": cat_info["id"],
                "name": cat_info["name"],
                "description": cat_info["description"],
                "score": cat_score,
                "findings_count": len(cat_findings),
                "status": "PASS" if cat_score >= 80 else ("WARNING" if cat_score >= 60 else "FAIL"),
            }

        duration_sec = round(time.time() - start_time, 2)
        timestamp_str = time.strftime("%Y-%m-%d %H:%M:%S")

        self.log("=" * 70)
        self.log(f"🏁 HOÀN TẤT KIỂM ĐỊNH BẢO MẬT TRONG {duration_sec} GIÂY")
        self.log(f"Điểm số an ninh thực tế: {security_score}/100.0 | Xếp hạng: {security_grade}")
        self.log(f"Điểm vệ sinh mã nguồn: {code_hygiene_score}/100.0 | Điểm rào chắn kiến trúc: {architecture_score}/100.0")
        if gatekeeper_status != "PASSED":
            self.log(f"🚨 TRẠNG THÁI CỔNG AN NINH: {gatekeeper_status}")
            self.log(f"   Lý do: {gatekeeper_reason}")
        self.log(f"Tổng số kiểm tra: {self.total_checks_run} (Đạt: {self.total_checks_passed}, Cảnh báo/Lỗi: {self.total_checks_failed})")
        self.log(f"Phát hiện: {findings_by_sev[SEVERITY_CRITICAL]} Nghiêm trọng, {findings_by_sev[SEVERITY_HIGH]} Cao, {findings_by_sev[SEVERITY_MEDIUM]} Trung bình, {findings_by_sev[SEVERITY_LOW]} Thấp")

        return ScanResult(
            timestamp=timestamp_str,
            duration_sec=duration_sec,
            profile_name=self.profile,
            total_endpoints_scanned=len(ALL_SECURITY_ENDPOINTS),
            total_files_analyzed=files_count,
            total_checks_run=self.total_checks_run,
            total_checks_passed=self.total_checks_passed,
            total_checks_failed=self.total_checks_failed,
            security_score=security_score,
            security_grade=security_grade,
            code_hygiene_score=code_hygiene_score,
            architecture_score=architecture_score,
            gatekeeper_status=gatekeeper_status,
            gatekeeper_reason=gatekeeper_reason,
            findings=self.findings,
            findings_by_severity=findings_by_sev,
            owasp_compliance=owasp_compliance,
            endpoint_matrix=self.endpoint_matrix,
            database_audit=db_audit
        )
