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
        "name": "Read-Heavy Workload",
        "description": "Simulates normal browsing activity across invoices, contracts, staff, and dashboards.",
        "generator_factory": get_read_heavy_generator,
        "default_profile": "standard",
    },
    "heavy_reports": {
        "name": "Heavy Analytics & Reports",
        "description": "Simulates high-demand aggregation queries (annual dashboard cashout, leave calculations, punctuality).",
        "generator_factory": get_heavy_reports_generator,
        "default_profile": "standard",
    },
    "write_mixed": {
        "name": "Mixed Read/Write Load",
        "description": "Simulates realistic operational traffic with 85% reads and 15% state updates/AJAX.",
        "generator_factory": get_write_mixed_generator,
        "default_profile": "standard",
    },
    "stress_burst": {
        "name": "Stress Saturation Burst",
        "description": "Drives maximum concurrent traffic into database-intensive endpoints to test concurrency limits.",
        "generator_factory": get_stress_generator,
        "default_profile": "stress",
    },
    "soak_endurance": {
        "name": "Soak & Endurance Test",
        "description": "Longer-duration continuous load to monitor memory leaks, connection starvation, and latency degradation.",
        "generator_factory": get_read_heavy_generator,
        "default_profile": "soak",
    },
}
