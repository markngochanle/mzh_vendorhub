"""
Performance Scenarios and Workload Generators.
Simulates realistic enterprise workloads across Mizuho Vendor Management System.
"""

import itertools
import random
from typing import Dict, Any, List, Callable


# Endpoint Pools for Scenario Workloads

# Full 100% Coverage of All Application Pages and Functional Sub-views
FULL_COVERAGE_ENDPOINTS = [
    # 1. Dashboard & Financial Summaries
    {"path": "/dashboard", "weight": 5, "method": "GET", "category": "Dashboard"},
    {"path": "/dashboard?fy=2026", "weight": 4, "method": "GET", "category": "Dashboard"},
    {"path": "/dashboard?fy=2025", "weight": 3, "method": "GET", "category": "Dashboard"},
    {"path": "/audit-logs", "weight": 3, "method": "GET", "category": "Audit"},

    # 2. Invoices & Reconciliation
    {"path": "/", "weight": 6, "method": "GET", "category": "Invoices"},
    {"path": "/?month=2026-06", "weight": 4, "method": "GET", "category": "Invoices"},
    {"path": "/invoice?id=1", "weight": 3, "method": "GET", "category": "Invoices"},
    {"path": "/invoice/new", "weight": 2, "method": "GET", "category": "Invoices"},
    {"path": "/edit-invoice?id=1", "weight": 2, "method": "GET", "category": "Invoices"},
    {"path": "/raw?id=1", "weight": 2, "method": "GET", "category": "Invoices"},

    # 3. Vendors Management
    {"path": "/vendors", "weight": 4, "method": "GET", "category": "Vendors"},
    {"path": "/vendor/new", "weight": 2, "method": "GET", "category": "Vendors"},
    {"path": "/vendor/edit?id=1", "weight": 2, "method": "GET", "category": "Vendors"},

    # 4. Contracts & Annexes
    {"path": "/contracts", "weight": 5, "method": "GET", "category": "Contracts"},
    {"path": "/contracts?status=active", "weight": 4, "method": "GET", "category": "Contracts"},
    {"path": "/contracts/references", "weight": 4, "method": "GET", "category": "Contracts"},
    {"path": "/contract/new", "weight": 2, "method": "GET", "category": "Contracts"},
    {"path": "/contract/edit?id=1", "weight": 2, "method": "GET", "category": "Contracts"},
    {"path": "/contract/assign-staff?contract_id=1", "weight": 3, "method": "GET", "category": "Contracts"},
    {"path": "/contract/edit-staff-link?id=1", "weight": 2, "method": "GET", "category": "Contracts"},
    {"path": "/annex/new?contract_id=1", "weight": 2, "method": "GET", "category": "Contracts"},
    {"path": "/annex/edit?id=1", "weight": 2, "method": "GET", "category": "Contracts"},

    # 5. Staff & Shifts Management
    {"path": "/staff", "weight": 5, "method": "GET", "category": "Staff"},
    {"path": "/staff/new", "weight": 2, "method": "GET", "category": "Staff"},
    {"path": "/staff/edit?id=1", "weight": 2, "method": "GET", "category": "Staff"},
    {"path": "/staff/shifts", "weight": 3, "method": "GET", "category": "Staff"},

    # 6. Attendance, Timesheet & Acceptance
    {"path": "/attendance", "weight": 5, "method": "GET", "category": "Attendance"},
    {"path": "/attendance/monthly", "weight": 4, "method": "GET", "category": "Attendance"},
    {"path": "/attendance/timesheet", "weight": 3, "method": "GET", "category": "Attendance"},
    {"path": "/attendance/acceptance", "weight": 4, "method": "GET", "category": "Attendance"},
    {"path": "/attendance/punctuality", "weight": 4, "method": "GET", "category": "Attendance"},

    # 7. Payments Management
    {"path": "/payments", "weight": 3, "method": "GET", "category": "Payments"},
    {"path": "/payments/dashboard", "weight": 3, "method": "GET", "category": "Payments"},
    {"path": "/payments/fixed-price", "weight": 4, "method": "GET", "category": "Payments"},
    {"path": "/payments/recurring", "weight": 4, "method": "GET", "category": "Payments"},
    {"path": "/attendance/payout", "weight": 3, "method": "GET", "category": "Payments"},

    # 8. Projects Management & Allocation
    {"path": "/projects", "weight": 4, "method": "GET", "category": "Projects"},
    {"path": "/projects/assign", "weight": 4, "method": "GET", "category": "Projects"},
    {"path": "/project/edit?id=1", "weight": 2, "method": "GET", "category": "Projects"},
    {"path": "/api/projects/available-staff?month=2026-06", "weight": 2, "method": "GET", "category": "Projects"},

    # 9. Static Assets & Resources
    {"path": "/static/js/chart.umd.min.js", "weight": 2, "method": "GET", "category": "Static"},
    {"path": "/logo.png", "weight": 2, "method": "GET", "category": "Static"},
]

READ_HEAVY_ENDPOINTS = [
    {"path": "/", "weight": 18, "method": "GET"},
    {"path": "/dashboard", "weight": 20, "method": "GET"},
    {"path": "/dashboard?fy=2026", "weight": 12, "method": "GET"},
    {"path": "/contracts", "weight": 16, "method": "GET"},
    {"path": "/contracts?status=active", "weight": 10, "method": "GET"},
    {"path": "/contracts/references", "weight": 10, "method": "GET"},
    {"path": "/staff", "weight": 14, "method": "GET"},
    {"path": "/vendors", "weight": 10, "method": "GET"},
    {"path": "/payments/fixed-price", "weight": 10, "method": "GET"},
    {"path": "/payments/recurring", "weight": 10, "method": "GET"},
    {"path": "/attendance", "weight": 12, "method": "GET"},
    {"path": "/attendance/monthly", "weight": 10, "method": "GET"},
    {"path": "/attendance/timesheet", "weight": 8, "method": "GET"},
    {"path": "/attendance/punctuality", "weight": 10, "method": "GET"},
    {"path": "/attendance/acceptance", "weight": 10, "method": "GET"},
    {"path": "/projects", "weight": 10, "method": "GET"},
    {"path": "/projects/assign", "weight": 10, "method": "GET"},
    {"path": "/invoice?id=1", "weight": 8, "method": "GET"},
    {"path": "/audit-logs", "weight": 6, "method": "GET"},
    {"path": "/static/js/chart.umd.min.js", "weight": 8, "method": "GET"},
    {"path": "/logo.png", "weight": 4, "method": "GET"},
]

HEAVY_REPORTS_ENDPOINTS = [
    {"path": "/dashboard", "weight": 25, "method": "GET"},
    {"path": "/dashboard?fy=2025", "weight": 15, "method": "GET"},
    {"path": "/dashboard?fy=2026", "weight": 20, "method": "GET"},
    {"path": "/contracts", "weight": 20, "method": "GET"},
    {"path": "/attendance", "weight": 25, "method": "GET"},
    {"path": "/attendance/monthly", "weight": 20, "method": "GET"},
    {"path": "/attendance/punctuality", "weight": 20, "method": "GET"},
    {"path": "/attendance/acceptance", "weight": 15, "method": "GET"},
    {"path": "/attendance/payout", "weight": 15, "method": "GET"},
    {"path": "/payments/fixed-price", "weight": 15, "method": "GET"},
    {"path": "/payments/recurring", "weight": 15, "method": "GET"},
    {"path": "/projects/assign", "weight": 20, "method": "GET"},
    {"path": "/audit-logs", "weight": 15, "method": "GET"},
]

STRESS_ENDPOINTS = [
    {"path": "/dashboard", "weight": 40, "method": "GET"},
    {"path": "/contracts", "weight": 40, "method": "GET"},
    {"path": "/attendance/punctuality", "weight": 20, "method": "GET"},
]


def _build_weighted_chooser(endpoints: List[Dict[str, Any]]) -> Callable[[], Dict[str, Any]]:
    weighted_items = []
    for item in endpoints:
        weight = item.get("weight", 1)
        weighted_items.extend([item] * weight)

    def chooser() -> Dict[str, Any]:
        chosen = random.choice(weighted_items)
        return {
            "path": chosen["path"],
            "method": chosen.get("method", "GET"),
            "data": chosen.get("data"),
            "headers": chosen.get("headers", {})
        }
    return chooser


def get_full_coverage_generator() -> Callable[[], Dict[str, Any]]:
    """
    Cycles sequentially across all 40 system pages and functional URLs
    to guarantee 100% full application page coverage during benchmark.
    """
    cycle_iter = itertools.cycle(FULL_COVERAGE_ENDPOINTS)

    def chooser() -> Dict[str, Any]:
        chosen = next(cycle_iter)
        return {
            "path": chosen["path"],
            "method": chosen.get("method", "GET"),
            "data": chosen.get("data"),
            "headers": chosen.get("headers", {})
        }
    return chooser


def get_read_heavy_generator() -> Callable[[], Dict[str, Any]]:
    return _build_weighted_chooser(READ_HEAVY_ENDPOINTS)


def get_heavy_reports_generator() -> Callable[[], Dict[str, Any]]:
    return _build_weighted_chooser(HEAVY_REPORTS_ENDPOINTS)


def get_stress_generator() -> Callable[[], Dict[str, Any]]:
    return _build_weighted_chooser(STRESS_ENDPOINTS)


def get_write_mixed_generator() -> Callable[[], Dict[str, Any]]:
    import json
    base_chooser = _build_weighted_chooser(READ_HEAVY_ENDPOINTS)

    def generator() -> Dict[str, Any]:
        # 85% read, 15% write / ajax
        if random.random() < 0.85:
            return base_chooser()

        write_type = random.choice(["ref_lock_toggle", "search_filter"])
        if write_type == "ref_lock_toggle":
            return {
                "path": "/api/contracts/toggle-reference-lock",
                "method": "POST",
                "data": json.dumps({
                    "contract_id": 1,
                    "annex_id": 1,
                    "month": "2026-06",
                    "locked": 0
                }),
                "headers": {"Content-Type": "application/json"}
            }
        else:
            fy = random.choice([2024, 2025, 2026, 2027])
            return {
                "path": f"/dashboard?fy={fy}",
                "method": "GET"
            }
    return generator


SCENARIO_REGISTRY = {
    "full_coverage": {
        "name": "Kịch bản Quét Toàn Diện Mọi Trang (100% Page Coverage)",
        "description": "Kiểm thử đầy đủ 40 trang & URL chức năng trên toàn hệ thống (Hóa đơn, Hợp đồng, Phụ lục, Vendor, Nhân sự, Chấm công, Thanh toán, Dự án, Audit Log, Form chỉnh sửa).",
        "generator_factory": get_full_coverage_generator,
        "default_profile": "standard",
    },
    "read_heavy": {
        "name": "Kịch bản Tải Đọc Thực Tế (Read-Heavy)",
        "description": "Mô phỏng người dùng duyệt xem danh sách hóa đơn, hợp đồng, phụ lục, nhân sự và dashboard.",
        "generator_factory": get_read_heavy_generator,
        "default_profile": "standard",
    },
    "heavy_reports": {
        "name": "Kịch bản Báo Cáo & Tổng Hợp Nặng (Heavy Reports)",
        "description": "Mô phỏng các truy vấn tổng hợp phức tạp (ma trận dòng tiền cash-out, tính ngày phép, chuyên cần).",
        "generator_factory": get_heavy_reports_generator,
        "default_profile": "standard",
    },
    "write_mixed": {
        "name": "Kịch bản Tải Kết Hợp Đọc / Ghi (Mixed Load)",
        "description": "Mô phỏng tác vụ thực tế với 85% xem dữ liệu và 15% thao tác cập nhật trạng thái/AJAX.",
        "generator_factory": get_write_mixed_generator,
        "default_profile": "standard",
    },
    "stress_burst": {
        "name": "Kịch bản Quá Tải Cực Hạn (Stress Saturation)",
        "description": "Gửi lưu lượng đồng thời tối đa vào các trang nặng nhất để đo ngưỡng chịu tải giới hạn.",
        "generator_factory": get_stress_generator,
        "default_profile": "stress",
    },
    "soak_endurance": {
        "name": "Kịch bản Kiểm Thử Bền Bỉ (Soak Endurance)",
        "description": "Duy trì tải liên tục trong thời gian dài để kiểm tra rò rỉ bộ nhớ và độ ổn định kết nối.",
        "generator_factory": get_read_heavy_generator,
        "default_profile": "soak",
    },
}
