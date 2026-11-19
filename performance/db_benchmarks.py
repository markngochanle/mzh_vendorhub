"""
Database Query Benchmarking and Query Plan Analysis for SQLite.
Measures execution times, percentile latencies, and analyzes EXPLAIN QUERY PLAN.
"""

import sqlite3
import time
import math
from typing import Dict, Any, List, Optional
from pathlib import Path

from performance.benchmark_engine import calculate_percentile
from performance.config import MAIN_DB_PATH


BENCHMARK_QUERIES = [
    {
        "id": "Q1_ACTIVE_CONTRACTS",
        "name": "Active Contracts with Buyer & Seller Vendors",
        "sql": """
            SELECT c.*, b.company_name AS buyer_name, s.company_name AS seller_name
            FROM contracts c
            LEFT JOIN vendors b ON c.buyer_vendor_id = b.id
            LEFT JOIN vendors s ON c.seller_vendor_id = s.id
            WHERE c.deleted_at IS NULL AND c.is_active = 1
            ORDER BY c.id DESC
        """,
        "params": ()
    },
    {
        "id": "Q2_ANNEXES_WITH_CONTRACT",
        "name": "Contract Annexes by Contract ID",
        "sql": """
            SELECT a.*, c.framework_no, c.framework_name
            FROM contract_annexes a
            JOIN contracts c ON a.contract_id = c.id
            WHERE a.deleted_at IS NULL AND a.is_active = 1
            ORDER BY a.contract_id, a.id
        """,
        "params": ()
    },
    {
        "id": "Q3_STAFF_ALLOCATIONS",
        "name": "Staff Allocations across Contracts & Annexes",
        "sql": """
            SELECT l.id AS link_id, l.staff_id, l.contract_id, l.annex_id,
                   l.monthly_rate, l.manday_rate, l.joining_date, l.tentative_leaving_date,
                   l.paid_leave_total_hours, l.carried_over_leave_hours,
                   s.full_name_vi, s.position
            FROM contract_staff_links l
            JOIN contract_staff s ON s.id = l.staff_id
            ORDER BY s.full_name_vi ASC
        """,
        "params": ()
    },
    {
        "id": "Q4_MONTHLY_ATTENDANCE_SUMMARY",
        "name": "Monthly Attendance Summary & Paid Leave",
        "sql": """
            SELECT staff_id, month, paid_leave_days, standard_days, actual_days, total_amount
            FROM monthly_attendance_summary
            ORDER BY month DESC, staff_id ASC
        """,
        "params": ()
    },
    {
        "id": "Q5_DASHBOARD_INVOICE_AGG",
        "name": "Dashboard Invoice Aggregation by Vendor & Month",
        "sql": """
            SELECT seller_name, service_year, service_month,
                   COUNT(*) AS invoice_count,
                   SUM(tg_tttbso) AS total_spent
            FROM invoices
            GROUP BY seller_name, service_year, service_month
        """,
        "params": ()
    },
    {
        "id": "Q6_ATTENDANCE_DAILY_RECORDS",
        "name": "Daily Attendance Records for Work Hours & OT",
        "sql": """
            SELECT staff_id, date, work_hours, ot_hours
            FROM attendance
            WHERE date >= '2026-01-01'
            ORDER BY date DESC
            LIMIT 500
        """,
        "params": ()
    },
    {
        "id": "Q7_MILESTONES_CASHOUT",
        "name": "Milestone Payments with Cash-Out Status",
        "sql": """
            SELECT m.*, c.framework_no, c.framework_name,
                   v.company_name AS vendor_name
            FROM contract_milestones m
            JOIN contracts c ON m.contract_id = c.id
            LEFT JOIN vendors v ON c.seller_vendor_id = v.id
            ORDER BY m.planned_date ASC
        """,
        "params": ()
    },
    {
        "id": "Q8_AUDIT_LOGS_RECENT",
        "name": "Audit Logs Recency Scan with Limit",
        "sql": """
            SELECT id, action, table_name, record_id, description, created_at
            FROM audit_logs
            ORDER BY id DESC
            LIMIT 100
        """,
        "params": ()
    }
]


class DatabaseBenchmark:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = str(db_path or MAIN_DB_PATH)

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def explain_query_plan(self, conn: sqlite3.Connection, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        cursor = conn.cursor()
        try:
            explain_sql = f"EXPLAIN QUERY PLAN {sql.strip()}"
            cursor.execute(explain_sql, params)
            rows = cursor.fetchall()
            plan = []
            for r in rows:
                detail = r["detail"] if "detail" in r.keys() else str(r[3])
                plan.append({
                    "id": r[0],
                    "parent": r[1],
                    "detail": detail,
                    "is_full_scan": "SCAN TABLE" in detail and "USING INDEX" not in detail
                })
            return plan
        except Exception as e:
            return [{"detail": f"Explain failed: {str(e)}", "is_full_scan": False}]

    def benchmark_query(self, query_def: Dict[str, Any], iterations: int = 50, warmup: int = 5) -> Dict[str, Any]:
        conn = self._get_connection()
        try:
            sql = query_def["sql"]
            params = query_def.get("params", ())

            # 1. Explain Query Plan
            plan = self.explain_query_plan(conn, sql, params)
            has_full_table_scan = any(p.get("is_full_scan", False) for p in plan)

            # 2. Warm-up
            cursor = conn.cursor()
            for _ in range(warmup):
                cursor.execute(sql, params)
                cursor.fetchall()

            # 3. Benchmark runs
            timings_ms: List[float] = []
            row_count = 0
            for _ in range(iterations):
                t0 = time.perf_counter_ns()
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                t1 = time.perf_counter_ns()
                timings_ms.append((t1 - t0) / 1_000_000.0)
                row_count = len(rows)

            timings_ms.sort()
            min_ms = timings_ms[0]
            max_ms = timings_ms[-1]
            mean_ms = sum(timings_ms) / len(timings_ms)
            median_ms = calculate_percentile(timings_ms, 50.0)
            p95_ms = calculate_percentile(timings_ms, 95.0)
            p99_ms = calculate_percentile(timings_ms, 99.0)

            # Performance evaluation
            if p95_ms < 5.0:
                health = "EXCELLENT"
            elif p95_ms < 20.0:
                health = "GOOD"
            elif p95_ms < 50.0:
                health = "ACCEPTABLE"
            else:
                health = "SLOW"

            return {
                "id": query_def["id"],
                "name": query_def["name"],
                "sql": sql.strip(),
                "iterations": iterations,
                "rows_returned": row_count,
                "min_ms": round(min_ms, 3),
                "mean_ms": round(mean_ms, 3),
                "median_ms": round(median_ms, 3),
                "p95_ms": round(p95_ms, 3),
                "p99_ms": round(p99_ms, 3),
                "max_ms": round(max_ms, 3),
                "has_full_table_scan": has_full_table_scan,
                "health": health,
                "plan": plan
            }
        except Exception as e:
            return {
                "id": query_def["id"],
                "name": query_def["name"],
                "sql": query_def["sql"].strip(),
                "error": str(e),
                "health": "ERROR",
                "min_ms": 0, "mean_ms": 0, "median_ms": 0, "p95_ms": 0, "p99_ms": 0, "max_ms": 0,
                "has_full_table_scan": False,
                "plan": []
            }
        finally:
            conn.close()

    def run_all(self, iterations: int = 50) -> Dict[str, Any]:
        results = []
        for q in BENCHMARK_QUERIES:
            res = self.benchmark_query(q, iterations=iterations)
            results.append(res)

        valid_runs = [r for r in results if "error" not in r]
        avg_p95 = sum(r["p95_ms"] for r in valid_runs) / len(valid_runs) if valid_runs else 0.0
        full_scans = sum(1 for r in valid_runs if r.get("has_full_table_scan"))

        return {
            "db_path": self.db_path,
            "total_queries_tested": len(results),
            "average_p95_ms": round(avg_p95, 3),
            "full_table_scans_detected": full_scans,
            "queries": results
        }
