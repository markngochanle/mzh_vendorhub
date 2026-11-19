"""
Automated CI/CD Unit Test Suite for Mizuho VMS Security & Compliance Audit Engine.
Run via: python3 -m unittest test_security.py
"""

import ast
import json
import unittest
from pathlib import Path

from security.config import (
    SECURITY_GRADES,
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    SEVERITY_LOW,
    ALL_SECURITY_ENDPOINTS,
    REPORTS_DIR,
)
from security.rules import Finding, RULES_METADATA
from security.scanner_engine import SecurityScannerEngine, ScanResult
from security.reporter import SecurityReporter
from performance.benchmark_engine import DirectHandler


class TestSecurityScoringAndGrades(unittest.TestCase):
    def test_grade_thresholds(self):
        def get_grade(score):
            for t, g in SECURITY_GRADES:
                if score >= t:
                    return g
            return "F (Kém - Nguy cơ rủi ro cao)"

        self.assertIn("A+", get_grade(98.0))
        self.assertIn("A ", get_grade(88.0))
        self.assertIn("B ", get_grade(78.0))
        self.assertIn("C ", get_grade(65.0))
        self.assertIn("F ", get_grade(45.0))

    def test_rules_metadata_integrity(self):
        self.assertEqual(len(RULES_METADATA), 10)
        for r_id, meta in RULES_METADATA.items():
            self.assertIn("name", meta)
            self.assertIn("category", meta)
            self.assertIn("default_severity", meta)
            self.assertTrue(meta["category"].startswith("A"))


class TestStaticSecurityAudit(unittest.TestCase):
    def test_ast_sqli_detection(self):
        engine = SecurityScannerEngine()

        safe_code = "conn.execute('SELECT * FROM vendors WHERE id = ?', (vendor_id,))"
        tree_safe = ast.parse(safe_code)
        engine._audit_ast_sql("test_safe.py", tree_safe, safe_code)
        self.assertEqual(len(engine.findings), 0)

        unsafe_code = 'conn.execute(f"SELECT * FROM vendors WHERE name = {user_input}")'
        tree_unsafe = ast.parse(unsafe_code)
        engine._audit_ast_sql("test_unsafe.py", tree_unsafe, unsafe_code)
        self.assertEqual(len(engine.findings), 1)
        self.assertEqual(engine.findings[0].rule_id, "SEC-01-SQLI")

    def test_secret_detection(self):
        engine = SecurityScannerEngine()

        clean_code = "app_name = 'Mizuho VMS'\nport = 8800"
        engine._audit_hardcoded_secrets("clean.py", clean_code)
        self.assertEqual(len(engine.findings), 0)

        secret_code = "api_key = 'abcdef1234567890abcdef1234567890'"
        engine._audit_hardcoded_secrets("secret.py", secret_code)
        self.assertEqual(len(engine.findings), 1)
        self.assertEqual(engine.findings[0].rule_id, "SEC-07-SECRETS")


class TestDynamicSecurityProbes(unittest.TestCase):
    def test_endpoint_inventory_coverage(self):
        self.assertGreaterEqual(len(ALL_SECURITY_ENDPOINTS), 40)
        paths = [ep["path"] for ep in ALL_SECURITY_ENDPOINTS]
        self.assertIn("/", paths)
        self.assertIn("/dashboard", paths)
        self.assertIn("/contracts", paths)
        self.assertIn("/attendance", paths)
        self.assertIn("/payments", paths)
        self.assertIn("/projects", paths)
        self.assertIn("/audit-logs", paths)

    def test_path_traversal_blocking(self):
        h = DirectHandler("/performance/report?name=../../db.sqlite3")
        h.do_GET()
        self.assertIn(h.response_status, (400, 403, 404))
        self.assertNotIn(b"SQLite format 3", h.wfile.getvalue())

    def test_direct_handler_security_headers_inspection(self):
        h = DirectHandler("/")
        h.do_GET()
        self.assertEqual(h.response_status, 200)
        self.assertIn("content-type", h.response_headers)


class TestSecurityReporter(unittest.TestCase):
    def test_report_generation(self):
        sample_result = ScanResult(
            timestamp="2026-11-20 00:00:00",
            duration_sec=1.5,
            profile_name="standard",
            total_endpoints_scanned=40,
            total_files_analyzed=15,
            total_checks_run=100,
            total_checks_passed=95,
            total_checks_failed=5,
            security_score=85.0,
            security_grade="A (Rất tốt - An toàn cao)",
            findings=[
                Finding(
                    rule_id="SEC-04-HEADERS",
                    title="Thiếu Header Bảo Mật",
                    category_id="A05",
                    severity=SEVERITY_MEDIUM,
                    component="/",
                    description="Thiếu X-Frame-Options",
                    evidence="Headers",
                    remediation="Thêm header an toàn"
                )
            ],
            findings_by_severity={SEVERITY_MEDIUM: 1},
            owasp_compliance={"A05": {"id": "A05:2021", "name": "Cấu hình", "score": 90.0, "status": "PASS"}},
            endpoint_matrix=[{"path": "/", "name": "Trang chủ", "category": "Invoices", "status": "PASS", "headers_passed": False, "sqli_passed": True, "xss_passed": True, "traceback_passed": True, "idor_passed": True}],
            database_audit={"foreign_keys_enabled": True, "integrity_check_passed": True}
        )

        reporter = SecurityReporter(sample_result)
        json_path = reporter.export_json("test_sec_report.json")
        html_path = reporter.export_html("test_sec_report.html")

        self.assertTrue(json_path.exists())
        self.assertTrue(html_path.exists())

        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("Báo Cáo Kiểm Định An Ninh", content)
            self.assertIn("OWASP Top 10", content)
            self.assertIn("chart.umd.min.js", content)

        if json_path.exists():
            json_path.unlink()
        if html_path.exists():
            html_path.unlink()


if __name__ == "__main__":
    unittest.main()
