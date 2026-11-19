"""
Configuration and SLA thresholds for Performance Testing Suite.
"""

import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
PERF_DIR = BASE_DIR / "performance"
REPORTS_DIR = BASE_DIR / "performance_reports"
PERF_DB_PATH = PERF_DIR / "perf_db.sqlite3"
MAIN_DB_PATH = BASE_DIR / "db.sqlite3"

REPORTS_DIR.mkdir(parents=True, exist_ok=True)
PERF_DIR.mkdir(parents=True, exist_ok=True)

# Target Server
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8800
TARGET_BASE_URL = os.environ.get("PERF_TARGET_URL", f"http://{DEFAULT_HOST}:{DEFAULT_PORT}")

# SLA Thresholds (Service Level Agreements - World-Class Standards)
SLA_THRESHOLDS = {
    "p50_latency_ms": 60.0,       # 50th percentile (median) must be <= 60ms
    "p95_latency_ms": 250.0,      # 95th percentile must be <= 250ms
    "p99_latency_ms": 600.0,      # 99th percentile must be <= 600ms
    "p99_9_latency_ms": 1200.0,   # 99.9th percentile (Three Nines tail) <= 1200ms
    "max_error_rate_pct": 0.5,    # Error rate must be <= 0.5%
    "min_rps": 35.0,              # Minimum throughput
    "apdex_target_ms": 100.0,     # Apdex T (Satisfied threshold)
    "apdex_tolerating_ms": 400.0, # Apdex 4T (Tolerating threshold)
    "min_apdex_score": 0.90,      # Minimum Apdex score (0.90+ is Good / Excellent)
    "max_memory_drift_mb_min": 0.5, # Maximum allowable memory growth rate (MB/min)
    "max_lock_contention_pct": 0.1, # Maximum SQLite write lock contention rate
}

# Concurrency & Workload Profiles (Including Multi-Stage Ramping & Saturation Scanning)
PROFILES = {
    "smoke": {
        "concurrency": 2,
        "duration_sec": 5,
        "description": "Kiểm thử nhanh tình trạng hệ thống với 2 người dùng đồng thời"
    },
    "standard": {
        "concurrency": 10,
        "duration_sec": 15,
        "description": "Kiểm thử tải tiêu chuẩn mô phỏng 10 người dùng hoạt động đồng thời"
    },
    "stages": {
        "concurrency": 15,
        "duration_sec": 18,
        "stages": [
            {"target_concurrency": 5, "duration_sec": 3, "name": "Ramp-up Khởi động"},
            {"target_concurrency": 15, "duration_sec": 12, "name": "Steady Tải Ổn định"},
            {"target_concurrency": 2, "duration_sec": 3, "name": "Ramp-down Thu hồi"},
        ],
        "description": "Kiểm thử đa giai đoạn (k6 Stages): Khởi động -> Tải ổn định -> Thu hồi giải phóng tài nguyên"
    },
    "heavy": {
        "concurrency": 25,
        "duration_sec": 20,
        "description": "Kiểm thử tải cao mô phỏng 25 người dùng hoạt động đồng thời"
    },
    "stress": {
        "concurrency": 50,
        "duration_sec": 15,
        "description": "Kiểm thử quá tải cực hạn với 50 người dùng để tìm điểm nghẽn chịu tải"
    },
    "spike": {
        "concurrency": 75,
        "duration_sec": 10,
        "description": "Kiểm thử đột biến lưu lượng bất ngờ với 75 người dùng đồng thời"
    },
    "soak": {
        "concurrency": 8,
        "duration_sec": 45,
        "description": "Kiểm thử độ bền bỉ dài hạn để theo dõi rò rỉ bộ nhớ và độ ổn định"
    },
    "saturation_knee": {
        "concurrency": 100,
        "duration_sec": 30,
        "steps": [5, 15, 30, 50, 75, 100],
        "step_duration_sec": 5,
        "description": "Quét trần năng lực chịu tải (Knee-of-the-Curve): Tự động tìm điểm bão hòa tối đa của máy chủ"
    }
}
