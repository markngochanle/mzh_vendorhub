# Playwright UAT Automation Tests

Thư mục này chứa toàn bộ chương trình kiểm thử tự động (Automation Test) cho các kịch bản nghiệm thu người dùng (UAT) của ứng dụng **Mizuho IT Outsourcing Vendor Hub**.

## 📑 Danh sách 7 Kịch bản UAT tự động:
1. **UAT 1**: Kiểm tra trang chính (Dashboard) và điều hướng (Navigation) qua các menu.
2. **UAT 2**: Thêm mới một nhân sự (`Nguyen UAT Tester`) thuộc nhà cung cấp FPT Software.
3. **UAT 3**: Tạo mới hợp đồng khung (`MHB/FPT/UAT/001`), tạo phụ lục (`Annex UAT 2026-A`) và phân bổ nhân sự trên vào phụ lục này với rate 55,000,000 VND.
4. **UAT 4**: Phân bổ dự án hàng tháng của nhân sự thông qua giao diện ma trận (Project Matrix).
5. **UAT 6**: Quản lý Reference Numbers (Work Order) hàng tháng của hợp đồng.
6. **UAT 5**: Nhập chấm công công nhật (Daily Attendance) và thực hiện khóa chấm công (Lock Attendance).
7. **UAT 7**: Tải lên hóa đơn XML mẫu (`mock_invoice.xml`) và kiểm tra tự động khớp thông tin hóa đơn với hợp đồng.

---

## 🛠️ Hướng dẫn cài đặt và chạy:

### Bước 1: Cài đặt thư viện Playwright
Chạy lệnh sau để cài đặt gói thư viện Playwright cho Python và tải Chromium browser tự động:
```bash
pip install playwright
playwright install chromium
```

### Bước 2: Chạy bộ kiểm thử UAT tự động
Anh chỉ cần đứng ở thư mục gốc của dự án và chạy kịch bản UAT bằng lệnh:
```bash
python3 playwright/run_tests.py
```

* **Chạy xem trực quan trình duyệt (Headed Mode)**: Nếu muốn xem trình duyệt thực tế tự động mở ra, tự điền form và click chuột trực quan, hãy truyền thêm tham số `--headed`:
  ```bash
  python3 playwright/run_tests.py --headed
  ```

---

## 🛡️ Thiết kế an toàn dữ liệu:
* **Database độc lập**: Bộ kiểm thử tự động UAT sẽ tự khởi động một tệp cơ sở dữ liệu kiểm thử riêng biệt tại [playwright/uat_db.sqlite3](file:///Users/local/04.working/17.mizuho/vendor_management/playwright/uat_db.sqlite3) và chạy trên cổng độc lập `8899`.
* **Không ảnh hưởng dữ liệu thật**: Vì vậy, quá trình chạy test UAT tự động **hoàn toàn không ảnh hưởng hay làm thay đổi dữ liệu** trong tệp cơ sở dữ liệu phát triển/sản xuất chính (`db.sqlite3`) của anh.

---

## 📸 Ảnh chụp màn hình kết quả (Screenshots):
Khi chạy xong, toàn bộ ảnh chụp màn hình ghi nhận từng bước chạy UAT thành công sẽ được lưu trữ tự động tại thư mục [playwright/screenshots/](file:///Users/local/04.working/17.mizuho/vendor_management/playwright/screenshots/).
* `uat1_dashboard.png` - Trang chủ Dashboard.
* `uat2_staff_list_success.png` - Tạo thành công nhân sự.
* `uat3_4_allocation_success.png` - Gán nhân sự vào phụ lục hợp đồng.
* `uat4_project_matrix_assigned.png` - Gán dự án Matrix.
* `uat5_attendance_locked.png` - Trạng thái khóa chấm công.
* `uat6_reference_numbers.png` - Lưu Reference Numbers.
* `uat7_invoice_upload_match_success.png` - Upload hóa đơn XML & Tự động Match.
