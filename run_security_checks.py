#!/usr/bin/env python3
"""
CLI Runner for Mizuho VMS Automated Security Audit Suite.
Usage:
    python3 run_security_checks.py [--profile standard|deep|quick] [--no-html]
"""

import argparse
import sys
import time

from security.config import SECURITY_PROFILES, LOG_FILE_PATH, REPORTS_DIR
from security.scanner_engine import SecurityScannerEngine
from security.reporter import SecurityReporter


def main():
    parser = argparse.ArgumentParser(description="Mizuho VMS Security & Compliance Audit Suite")
    parser.add_argument("--profile", choices=list(SECURITY_PROFILES.keys()), default="standard",
                        help="Security scan profile (standard, deep, quick)")
    parser.add_argument("--no-html", action="store_true", help="Skip HTML report generation")
    args = parser.parse_args()

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    def log_handler(msg: str):
        print(msg)
        with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
            f.write(msg + "\n")

    # Clear previous log file
    with open(LOG_FILE_PATH, "w", encoding="utf-8") as f:
        f.write(f"=== BẮT ĐẦU PHIÊN KIỂM ĐỊNH BẢO MẬT: {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n\n")

    scanner = SecurityScannerEngine(profile=args.profile, log_callback=log_handler)
    result = scanner.run_full_scan()

    reporter = SecurityReporter(result)
    json_path = reporter.export_json()
    log_handler(f"\n💾 Đã lưu dữ liệu JSON kiểm định: {json_path}")

    if not args.no_html:
        html_path = reporter.export_html()
        log_handler(f"📊 Đã tạo báo cáo trực quan HTML: {html_path}")

    log_handler("\n✨ Hoàn tất toàn bộ chương trình kiểm tra an ninh.")


if __name__ == "__main__":
    main()
