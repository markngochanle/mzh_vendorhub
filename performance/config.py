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

# SLA Thresholds (Service Level Agreements)
SLA_THRESHOLDS = {
    "p50_latency_ms": 60.0,       # 50th percentile (median) must be <= 60ms
    "p95_latency_ms": 250.0,      # 95th percentile must be <= 250ms
    "p99_latency_ms": 600.0,      # 99th percentile must be <= 600ms
    "max_error_rate_pct": 0.5,    # Error rate must be <= 0.5%
    "min_rps": 35.0,              # Minimum throughput
    "apdex_target_ms": 100.0,     # Apdex T (Satisfied threshold)
    "apdex_tolerating_ms": 400.0, # Apdex 4T (Tolerating threshold)
    "min_apdex_score": 0.90,      # Minimum Apdex score (0.90+ is Good / Excellent)
}

# Concurrency & Workload Profiles
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
    }
}
