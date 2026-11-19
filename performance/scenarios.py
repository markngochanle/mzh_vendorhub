"""
Performance Scenarios and Workload Generators.
Simulates realistic enterprise workloads across Mizuho Vendor Management System.
"""

import random
from typing import Dict, Any, List, Callable


# Endpoint Pools for Scenario Workloads

READ_HEAVY_ENDPOINTS = [
    {"path": "/", "weight": 20, "method": "GET"},
    {"path": "/dashboard", "weight": 25, "method": "GET"},
    {"path": "/dashboard?fy=2026", "weight": 15, "method": "GET"},
    {"path": "/contracts", "weight": 20, "method": "GET"},
    {"path": "/contracts?status=active", "weight": 10, "method": "GET"},
    {"path": "/contracts/references", "weight": 10, "method": "GET"},
    {"path": "/staff", "weight": 15, "method": "GET"},
    {"path": "/vendors", "weight": 10, "method": "GET"},
    {"path": "/payments/fixed-price", "weight": 10, "method": "GET"},
    {"path": "/payments/recurring", "weight": 10, "method": "GET"},
    {"path": "/attendance/punctuality", "weight": 10, "method": "GET"},
    {"path": "/attendance/acceptance", "weight": 10, "method": "GET"},
    {"path": "/projects", "weight": 10, "method": "GET"},
    {"path": "/static/js/chart.umd.min.js", "weight": 10, "method": "GET"},
    {"path": "/logo.png", "weight": 5, "method": "GET"},
]

HEAVY_REPORTS_ENDPOINTS = [
    {"path": "/dashboard", "weight": 30, "method": "GET"},
    {"path": "/dashboard?fy=2025", "weight": 20, "method": "GET"},
    {"path": "/dashboard?fy=2026", "weight": 25, "method": "GET"},
    {"path": "/contracts", "weight": 25, "method": "GET"},
    {"path": "/attendance/punctuality", "weight": 20, "method": "GET"},
    {"path": "/attendance/payout", "weight": 15, "method": "GET"},
    {"path": "/payments/fixed-price", "weight": 20, "method": "GET"},
    {"path": "/payments/recurring", "weight": 15, "method": "GET"},
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
