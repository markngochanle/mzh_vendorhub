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
    "SEC-11-AUTH-GATEWAY": {
        "name": "Cổng Xác Thực & Kiểm Soát Truy Cập Điểm Cuối (Authentication Gateway & Endpoint Protection)",
        "category": "A01",
        "description": "Theo chuẩn OWASP A01:2021 & ASVS V1.4, V2.1: Mọi endpoint nhạy cảm (quản lý hợp đồng, hóa đơn, thanh toán, nhân sự) bắt buộc phải được bảo vệ bởi cổng xác thực (Authentication). Việc hệ thống mở tự do cho mọi truy cập không xác thực là rủi ro nghiêm trọng nhất.",
        "default_severity": SEVERITY_CRITICAL,
    },
    "SEC-12-RBAC-CONTROL": {
        "name": "Phân Quyền Theo Vai Trò & Tối Thiểu Đặc Quyền (Role-Based Access Control - RBAC)",
        "category": "A01",
        "description": "Theo chuẩn OWASP A01:2021 & ASVS V4.1: Hệ thống phải thực thi phân tách nhiệm vụ (Segregation of Duties) giữa các vai trò (Admin, Project Manager, Accountant, Staff, Viewer). Không cho phép mọi người dùng ẩn danh đều có toàn quyền thực hiện các thao tác phá hủy (xóa/hủy/khóa).",
        "default_severity": SEVERITY_HIGH,
    },
    "SEC-13-CSRF-TOKEN": {
        "name": "Bảo Vệ Biểu Mẫu Thay Đổi Dữ Liệu Chống Tấn Công CSRF (Anti-CSRF Token Defense)",
        "category": "A10",
        "description": "Theo chuẩn OWASP A01:2021, A10:2021 & ASVS V4.2: Các biểu mẫu POST làm thay đổi trạng thái bản ghi bắt buộc phải kèm Anti-CSRF Token hoặc kiểm tra SameSite Cookie + Origin Header để ngăn ngừa tấn công giả mạo yêu cầu từ trang ngoài.",
        "default_severity": SEVERITY_HIGH,
    },
    "SEC-14-SESSION-HYGIENE": {
        "name": "Quản Lý Phiên Làm Việc & Thuộc Tính Cookie (Session & Cookie Hygiene)",
        "category": "A07",
        "description": "Theo chuẩn OWASP A07:2021 & ASVS V3.1 - V3.4: Kiểm tra cơ chế quản lý phiên làm việc tập trung, cờ bảo mật cookie (HttpOnly, SameSite=Lax/Strict, Secure) và chính sách hết hạn phiên làm việc (Session Inactivity Timeout).",
        "default_severity": SEVERITY_MEDIUM,
    },
    "SEC-15-RATE-LIMITING": {
        "name": "Giới Hạn Tần Suất Yêu Cầu & Chống Lạm Dụng (Rate Limiting & Abuse Prevention)",
        "category": "A04",
        "description": "Theo chuẩn OWASP A04:2021 & ASVS V1.11: Kiểm tra cơ chế giới hạn tần suất yêu cầu (Rate Limiting) trên các endpoint nhạy cảm (tải file XML, tra cứu báo cáo tài chính nặng) để ngăn ngừa tấn công từ chối dịch vụ hoặc cào dữ liệu hàng loạt.",
        "default_severity": SEVERITY_MEDIUM,
    },
    "SEC-16-TRANSPORT-SECURITY": {
        "name": "An Toàn Kênh Truyền Thông Tin Nhạy Cảm (Transport Layer Security - TLS & HSTS)",
        "category": "A02",
        "description": "Theo chuẩn OWASP A02:2021 & ASVS V9.1, V9.2: Dữ liệu tài chính, lương nhân sự và thuế phải được truyền tải trên giao thức bảo mật HTTPS/TLS kèm theo tiêu đề Strict-Transport-Security (HSTS).",
        "default_severity": SEVERITY_MEDIUM,
    },
}
