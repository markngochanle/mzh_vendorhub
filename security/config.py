"""
Security Audit Configuration & Policy Rules.
Defines OWASP Top 10 categories, severity levels, scoring thresholds, and 100% endpoint inventory.
"""

from pathlib import Path
from typing import Dict, Any, List

BASE_DIR = Path(__file__).resolve().parent.parent
REPORTS_DIR = BASE_DIR / "security_reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE_PATH = REPORTS_DIR / "security_progress.log"

# Mức độ nghiêm trọng của lỗ hổng (Severity Levels)
SEVERITY_CRITICAL = "NGHIÊM TRỌNG"
SEVERITY_HIGH = "CAO"
SEVERITY_MEDIUM = "TRUNG BÌNH"
SEVERITY_LOW = "THẤP"
SEVERITY_INFO = "THÔNG TIN"

SEVERITY_COLORS = {
    SEVERITY_CRITICAL: {"bg": "#fee2e2", "color": "#991b1b", "badge": "#dc2626"},
    SEVERITY_HIGH: {"bg": "#ffedd5", "color": "#9a3412", "badge": "#ea580c"},
    SEVERITY_MEDIUM: {"bg": "#fef9c3", "color": "#854d0e", "badge": "#ca8a04"},
    SEVERITY_LOW: {"bg": "#dbeafe", "color": "#1e40af", "badge": "#2563eb"},
    SEVERITY_INFO: {"bg": "#f1f5f9", "color": "#475569", "badge": "#64748b"},
}

# Điểm số trừ theo từng cấp độ vi phạm
SEVERITY_DEDUCTIONS = {
    SEVERITY_CRITICAL: 25.0,
    SEVERITY_HIGH: 10.0,
    SEVERITY_MEDIUM: 3.0,
    SEVERITY_LOW: 1.0,
    SEVERITY_INFO: 0.0,
}

# Tiêu chuẩn Cổng An Ninh Thực Tế (Security Gatekeeper - NIST SP 800-115 & OWASP ASVS v4.0)
# Nếu hệ thống tồn tại lỗ hổng cốt lõi, điểm số tối đa bị khóa trần (Cap) không thể vượt qua ngưỡng rủi ro
GATEKEEPER_THRESHOLDS = {
    "CRITICAL_CAP": 40.0,  # Còn lỗi Nghiêm Trọng (ví dụ: Không có Xác thực): Điểm tối đa 40.0 (Hạng F)
    "HIGH_CAP": 65.0,      # Còn lỗi Cao (ví dụ: Thiếu RBAC, Thiếu CSRF Token): Điểm tối đa 65.0 (Hạng C)
    "MEDIUM_CAP": 82.0,    # Còn lỗi Trung bình (ví dụ: Thiếu Session Hygiene, Rate Limit): Điểm tối đa 82.0 (Hạng B)
}

# Thang điểm đánh giá xếp hạng an ninh
SECURITY_GRADES = [
    (95.0, "A+ (Xuất sắc - Bảo mật tối ưu)"),
    (85.0, "A (Rất tốt - An toàn cao)"),
    (75.0, "B (Tốt - Đạt tiêu chuẩn)"),
    (60.0, "C (Trung bình - Cần cải thiện)"),
    (0.0, "F (Kém - Nguy cơ rủi ro cao)"),
]

# 10 Hạng mục tiêu chuẩn an ninh ứng dụng web (OWASP Top 10:2021 & OWASP ASVS 4.0)
OWASP_CATEGORIES = {
    "A01": {
        "id": "A01:2021",
        "name": "Kiểm Soát Truy Cập & Phân Quyền (Access Control & RBAC)",
        "description": "Yêu cầu cổng xác thực người dùng, ma trận phân quyền (RBAC), tối thiểu đặc quyền và chống IDOR.",
    },
    "A02": {
        "id": "A02:2021",
        "name": "Mã Hóa & An Toàn Kênh Truyền (Cryptographic Failures)",
        "description": "Bảo vệ thông tin cá nhân/tài chính, mã hóa kênh truyền (HTTPS/HSTS) và ngăn lộ bí mật/mật khẩu trong code.",
    },
    "A03": {
        "id": "A03:2021",
        "name": "Chống Chèn Mã Độc (Injection - SQLi/XSS)",
        "description": "Ngăn chặn các cuộc tấn công SQL Injection và ép kiểu tham số an toàn trong truy vấn CSDL.",
    },
    "A04": {
        "id": "A04:2021",
        "name": "Thiết Kế An Toàn & Chống Lạm Dụng (Insecure Design & Rate Limiting)",
        "description": "Kiểm soát tính toàn vẹn nghiệp vụ, cơ chế giới hạn tần suất yêu cầu (Rate Limiting) và xử lý ngoại lệ.",
    },
    "A05": {
        "id": "A05:2021",
        "name": "Cấu Hình Bảo Mật & HTTP Headers (Security Misconfiguration)",
        "description": "Kiểm tra cấu hình máy chủ, các tiêu đề bảo vệ trình duyệt (X-Frame, X-Content-Type, CSP, Referrer).",
    },
    "A06": {
        "id": "A06:2021",
        "name": "Thành Phần Phần Mềm & Thư Viện (Vulnerable Components)",
        "description": "Kiểm tra phiên bản thư viện nội bộ (Chart.js), tài nguyên tĩnh và phụ thuộc không an toàn.",
    },
    "A07": {
        "id": "A07:2021",
        "name": "Xác Thực & Quản Lý Phiên (Identification & Authentication)",
        "description": "Kiểm tra cơ chế đăng nhập, quản lý phiên làm việc, cookie bảo mật (HttpOnly, SameSite) và hết hạn phiên.",
    },
    "A08": {
        "id": "A08:2021",
        "name": "Toàn Vẹn Dữ Liệu & Mã Nguồn (Software & Data Integrity)",
        "description": "Ngăn ngừa giải tuần tự hóa độc hại (deserialization), chèn mã động (eval/exec).",
    },
    "A09": {
        "id": "A09:2021",
        "name": "Ghi Nhật Ký Kiểm Toán & Giám Sát (Security Logging & Monitoring)",
        "description": "Đảm bảo mọi thao tác thêm/sửa/xóa/khóa dữ liệu đều được lưu vết đầy đủ trong Audit Logs.",
    },
    "A10": {
        "id": "A10:2021",
        "name": "Giả Mạo Yêu Cầu & Duyệt Tệp (SSRF, CSRF & Path Traversal)",
        "description": "Bảo vệ chống tấn công CSRF trên các form POST và ngăn chặn Path Traversal khi tải tệp.",
    },
}

# Danh mục đầy đủ 100% 40 Endpoints và URL chức năng của hệ thống Mizuho VMS
ALL_SECURITY_ENDPOINTS: List[Dict[str, Any]] = [
    # 1. Executive Dashboard & Audit
    {"path": "/dashboard", "category": "Dashboard", "name": "Executive Dashboard", "params": {}},
    {"path": "/dashboard?fy=2026", "category": "Dashboard", "name": "Dashboard Năm Tài Chính 2026", "params": {"fy": "2026"}},
    {"path": "/dashboard?fy=2025", "category": "Dashboard", "name": "Dashboard Năm Tài Chính 2025", "params": {"fy": "2025"}},
    {"path": "/audit-logs", "category": "Audit", "name": "Nhật Ký Kiểm Toán Hệ Thống", "params": {}},

    # 2. Hóa đơn & Đối soát (Invoices)
    {"path": "/", "category": "Invoices", "name": "Danh Sách Hóa Đơn", "params": {}},
    {"path": "/?month=2026-06", "category": "Invoices", "name": "Lọc Hóa Đơn Theo Tháng", "params": {"month": "2026-06"}},
    {"path": "/invoice?id=1", "category": "Invoices", "name": "Chi Tiết Hóa Đơn", "params": {"id": "1"}},
    {"path": "/invoice/new", "category": "Invoices", "name": "Form Tạo Mới Hóa Đơn", "params": {}},
    {"path": "/edit-invoice?id=1", "category": "Invoices", "name": "Form Chỉnh Sửa Hóa Đơn", "params": {"id": "1"}},
    {"path": "/raw?id=1", "category": "Invoices", "name": "Dữ Liệu Thô Hóa Đơn", "params": {"id": "1"}},

    # 3. Nhà cung cấp (Vendors)
    {"path": "/vendors", "category": "Vendors", "name": "Danh Sách Nhà Cung Cấp", "params": {}},
    {"path": "/vendor/new", "category": "Vendors", "name": "Form Tạo Mới Nhà Cung Cấp", "params": {}},
    {"path": "/vendor/edit?id=1", "category": "Vendors", "name": "Form Sửa Nhà Cung Cấp", "params": {"id": "1"}},

    # 4. Hợp đồng & Phụ lục (Contracts & Annexes)
    {"path": "/contracts", "category": "Contracts", "name": "Danh Sách Hợp Đồng", "params": {}},
    {"path": "/contracts?status=active", "category": "Contracts", "name": "Lọc Hợp Đồng Hiệu Lực", "params": {"status": "active"}},
    {"path": "/contracts/references", "category": "Contracts", "name": "Bảng Tham Chiếu Chi Phí", "params": {}},
    {"path": "/contract/new", "category": "Contracts", "name": "Form Tạo Mới Hợp Đồng", "params": {}},
    {"path": "/contract/edit?id=1", "category": "Contracts", "name": "Form Sửa Hợp Đồng", "params": {"id": "1"}},
    {"path": "/contract/assign-staff?contract_id=1", "category": "Contracts", "name": "Gán Nhân Sự Vào Hợp Đồng", "params": {"contract_id": "1"}},
    {"path": "/contract/edit-staff-link?id=1", "category": "Contracts", "name": "Sửa Phân Bổ Nhân Sự", "params": {"id": "1"}},
    {"path": "/annex/new?contract_id=1", "category": "Contracts", "name": "Form Tạo Mới Phụ Lục", "params": {"contract_id": "1"}},
    {"path": "/annex/edit?id=1", "category": "Contracts", "name": "Form Sửa Phụ Lục", "params": {"id": "1"}},

    # 5. Nhân sự & Ca làm việc (Staff & Shifts)
    {"path": "/staff", "category": "Staff", "name": "Danh Sách Nhân Sự & Phép", "params": {}},
    {"path": "/staff/new", "category": "Staff", "name": "Form Thêm Mới Nhân Sự", "params": {}},
    {"path": "/staff/edit?id=1", "category": "Staff", "name": "Form Sửa Nhân Sự", "params": {"id": "1"}},
    {"path": "/staff/shifts", "category": "Staff", "name": "Cấu Hình Ca Làm Việc & Phụ Cấp", "params": {}},

    # 6. Chấm công, Timesheet & Nghiệm thu
    {"path": "/attendance", "category": "Attendance", "name": "Ma Trận Chấm Công Hàng Ngày", "params": {}},
    {"path": "/attendance/monthly", "category": "Attendance", "name": "Bảng Tổng Hợp Công Tháng", "params": {}},
    {"path": "/attendance/timesheet", "category": "Attendance", "name": "Xem Bảng Timesheet", "params": {}},
    {"path": "/attendance/acceptance", "category": "Attendance", "name": "Nghiệm Thu Dịch Vụ Vendor", "params": {}},
    {"path": "/attendance/punctuality", "category": "Attendance", "name": "Báo Cáo Chuyên Cần & Đi Muộn", "params": {}},

    # 7. Quản lý Thanh toán (Payments)
    {"path": "/payments", "category": "Payments", "name": "Tổng Quan Thanh Toán", "params": {}},
    {"path": "/payments/dashboard", "category": "Payments", "name": "Dashboard Thanh Toán", "params": {}},
    {"path": "/payments/fixed-price", "category": "Payments", "name": "Thanh Toán Hợp Đồng Trọn Gói", "params": {}},
    {"path": "/payments/recurring", "category": "Payments", "name": "Thanh Toán Định Kỳ Hàng Tháng", "params": {}},
    {"path": "/attendance/payout", "category": "Payments", "name": "Chi Trả Thu Nhập Chấm Công", "params": {}},

    # 8. Quản lý Dự án (Projects)
    {"path": "/projects", "category": "Projects", "name": "Danh Mục Dự Án", "params": {}},
    {"path": "/projects/assign", "category": "Projects", "name": "Ma Trận Phân Bổ Dự Án", "params": {}},
    {"path": "/project/edit?id=1", "category": "Projects", "name": "Form Sửa Dự Án", "params": {"id": "1"}},
    {"path": "/api/projects/available-staff?month=2026-06", "category": "Projects", "name": "API Nhân Sự Khả Dụng", "params": {"month": "2026-06"}},

    # 9. Tài nguyên tĩnh & Báo cáo
    {"path": "/performance/report", "category": "Reports", "name": "Trình Xem Báo Cáo Hiệu Năng", "params": {"name": "perf_progress.log"}},
    {"path": "/static/js/chart.umd.min.js", "category": "Static", "name": "Thư Viện Đồ Thị Chart.js", "params": {}},
]

# Các cấu hình quét bảo mật
SECURITY_PROFILES = {
    "standard": {
        "name": "Quét Tiêu Chuẩn Toàn Diện (Standard - 100% Coverage)",
        "description": "Quét phân tích tĩnh toàn bộ mã nguồn + kiểm tra động 100% tất cả 40 endpoints đối chiếu 10 chuẩn OWASP.",
        "include_static": True,
        "include_dynamic": True,
        "include_db": True,
        "fuzz_iterations": 3,
    },
    "quick": {
        "name": "Quét Nhanh Trọng Yếu (Quick Scan)",
        "description": "Quét phân tích tĩnh mã nguồn và kiểm tra 12 endpoint cốt lõi để phát hiện sớm các lỗ hổng nghiêm trọng.",
        "include_static": True,
        "include_dynamic": True,
        "include_db": False,
        "fuzz_iterations": 1,
    },
    "deep": {
        "name": "Quét Chuyên Sâu Tối Đa (Deep Security Audit)",
        "description": "Quét mở rộng toàn diện kết hợp kiểm tra tính toàn vẹn CSDL, đối soát log kiểm toán và thử nghiệm biên cao cấp.",
        "include_static": True,
        "include_dynamic": True,
        "include_db": True,
        "fuzz_iterations": 5,
    },
}
