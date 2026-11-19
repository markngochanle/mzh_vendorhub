"""
Security Audit Rules & Policy Definitions.
Defines 10 core security check modules aligned with OWASP Top 10:2021.
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any, List

from security.config import (
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    SEVERITY_LOW,
    SEVERITY_INFO,
)


@dataclass
class Finding:
    rule_id: str
    title: str
    category_id: str
    severity: str
    component: str
    description: str
    evidence: str
    remediation: str


# Định nghĩa 10 quy tắc kiểm định an ninh tiêu chuẩn
RULES_METADATA = {
    "SEC-01-SQLI": {
        "name": "Kiểm Tra Chống Chèn Mã SQL (SQL Injection Prevention)",
        "category": "A03",
        "description": "Quét tĩnh mã nguồn và kiểm tra động 100% endpoints để đảm bảo mọi câu lệnh truy vấn SQLite đều sử dụng tham số hóa (parameterized query ?), không ghép chuỗi f-string hoặc %.",
        "default_severity": SEVERITY_CRITICAL,
    },
    "SEC-02-XSS": {
        "name": "Kiểm Tra Ngăn Chặn XSS (Cross-Site Scripting Sanitization)",
        "category": "A03",
        "description": "Kiểm tra cơ chế mã hóa HTML entities (escape) đối với mọi tham số đầu vào được hiển thị lại trên giao diện web để ngăn chặn thực thi JavaScript độc hại.",
        "default_severity": SEVERITY_HIGH,
    },
    "SEC-03-TRAVERSAL": {
        "name": "Kiểm Tra Ngăn Chặn Duyệt Thư Mục (Path Traversal & File Access)",
        "category": "A10",
        "description": "Kiểm tra các đường dẫn tải tệp báo cáo hoặc file tĩnh để ngăn chặn tấn công đọc tệp tùy ý ngoài thư mục cho phép thông qua ký tự '..' hoặc ký tự phân cách đường dẫn.",
        "default_severity": SEVERITY_CRITICAL,
    },
    "SEC-04-HEADERS": {
        "name": "Kiểm Định Header Bảo Mật HTTP (Security Headers Compliance)",
        "category": "A05",
        "description": "Đo lường sự hiện diện của các tiêu đề bảo mật chuẩn phòng ngự: X-Content-Type-Options: nosniff, X-Frame-Options: SAMEORIGIN/DENY, Content-Security-Policy và Referrer-Policy.",
        "default_severity": SEVERITY_MEDIUM,
    },
    "SEC-05-METHOD-CSRF": {
        "name": "Kiểm Soát Phương Thức HTTP & Ràng Buộc Thao Tác (Method Safety & CSRF)",
        "category": "A01",
        "description": "Đảm bảo các thao tác làm thay đổi dữ liệu hoặc xóa bản ghi (hóa đơn, nhà cung cấp, hợp đồng) bắt buộc phải dùng phương thức POST, từ chối kích hoạt qua phương thức GET.",
        "default_severity": SEVERITY_HIGH,
    },
    "SEC-06-TRACEBACK": {
        "name": "Ngăn Ngừa Rò Rỉ Dấu Vết Hệ Thống (Information Disclosure & Traceback)",
        "category": "A04",
        "description": "Kiểm tra phản hồi khi gửi tham số sai kiểu hoặc bất thường để bảo đảm máy chủ không để lộ stack trace Python, đường dẫn mã nguồn nội bộ hoặc cấu trúc CSDL.",
        "default_severity": SEVERITY_MEDIUM,
    },
    "SEC-07-SECRETS": {
        "name": "Kiểm Tra Mật Khẩu & Bí Mật Cứng (Hardcoded Secrets & Credentials)",
        "category": "A02",
        "description": "Quét toàn bộ mã nguồn để phát hiện API key, Private Key, token xác thực hoặc mật khẩu quản trị bị lưu cố định trong code.",
        "default_severity": SEVERITY_CRITICAL,
    },
    "SEC-08-AUDIT-LOG": {
        "name": "Kiểm Định Ghi Nhật Ký Kiểm Toán Nghiệp Vụ (Audit Logging Compliance)",
        "category": "A09",
        "description": "Kiểm tra xem các hành động tạo mới, cập nhật, xóa, phục hồi và khóa dữ liệu có được ghi lại vào bảng audit_logs với đầy đủ thông tin thời gian và đối tượng hay không.",
        "default_severity": SEVERITY_MEDIUM,
    },
    "SEC-09-SQLITE-CONFIG": {
        "name": "Kiểm Tra Cấu Hình An Toàn CSDL SQLite (Database Security Pragma)",
        "category": "A05",
        "description": "Kiểm tra các cấu hình bảo vệ cơ sở dữ liệu như ràng buộc khóa ngoại (foreign_keys), chế độ schema an toàn, quyền đọc ghi tệp cơ sở dữ liệu trên đĩa.",
        "default_severity": SEVERITY_LOW,
    },
    "SEC-10-IDOR-BOUNDARY": {
        "name": "Xử Lý Giá Trị Biên & An Toàn Tham Chiếu Đối Tượng (IDOR & Boundary Safety)",
        "category": "A01",
        "description": "Kiểm tra phản ứng của hệ thống khi truy cập các ID không tồn tại, ID âm hoặc giá trị biên cực đại để đảm bảo trả về mã trạng thái hợp lý (400/404) thay vì lỗi máy chủ 500.",
        "default_severity": SEVERITY_LOW,
    },
}
