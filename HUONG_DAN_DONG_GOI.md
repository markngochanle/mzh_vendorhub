# HƯỚNG DẪN ĐÓNG GÓI ỨNG DỤNG (ONLINE & OFFLINE)
**Mizuho IT Outsourcing Vendor Hub**

Tài liệu này hướng dẫn cách đóng gói toàn bộ hệ thống thành file thực thi độc lập **`.exe`** chạy trên hệ điều hành Windows, bao gồm cả trường hợp máy chủ hoặc máy phát triển **hoàn toàn không có kết nối mạng Internet** (mạng nội bộ ngân hàng / Air-gapped network).

---

## 1. Cấu trúc kết quả sau khi đóng gói

Sau khi hoàn tất đóng gói, một thư mục tên là **`dist`** sẽ được tạo ra với đúng **3 thành phần độc lập**:

```text
vendor_management/
└── dist/
    ├── MizuhoVendorHub.exe   # File chạy ứng dụng duy nhất (đã tích hợp icon logo và tài nguyên)
    ├── db.sqlite3            # Cơ sở dữ liệu SQLite hoạt động thực tế
    └── config.ini            # File cấu hình (Host, Port, đường dẫn DB có thể chỉnh sửa tự do)
```

> [!NOTE]
> * **Không cần cài đặt Python trên máy người dùng cuối:** Khi bàn giao, bạn chỉ cần copy nguyên thư mục `dist` sang bất kỳ máy tính Windows nào là có thể double-click chạy ngay.
> * **Tự do tùy biến:** File `config.ini` và `db.sqlite3` nằm ngay bên ngoài, cho phép quản trị viên đổi cổng chạy (mặc định 8800) hoặc sao lưu cơ sở dữ liệu mà không cần phải build lại code.

---

## 2. Trường hợp 1: Đóng gói trên máy CÓ kết nối Internet

Nếu máy tính Windows hiện tại có kết nối mạng Internet:

1. Đảm bảo máy đã cài đặt **Python 3** (khuyên dùng Python 3.10 - 3.12) và đã tích chọn tùy chọn **"Add Python to PATH"** khi cài.
2. Mở thư mục dự án và **Double-click vào file `package.bat`** (hoặc mở CMD và gõ `package.bat`).
3. Script sẽ tự động:
   * Kiểm tra và tải `PyInstaller` qua `pip` nếu máy chưa có.
   * Gắn icon đại diện `logo.ico` vào file `.exe`.
   * Đóng gói mã nguồn thành `dist\MizuhoVendorHub.exe`.
   * Tự động copy `db.sqlite3` và `config.ini` vào thư mục `dist`.
   * Dọn dẹp các thư mục tạm `build\` và file `.spec`.

---

## 3. Trường hợp 2: Đóng gói trong môi trường KHÔNG CÓ INTERNET (Offline / Air-Gapped)

Trong môi trường doanh nghiệp bảo mật nghiêm ngặt (như ngân hàng), máy tính thường bị chặn hoàn toàn truy cập ra ngoài Internet. Dưới đây là 2 phương án xử lý:

### Phương án A (Khuyên dùng - Nhanh & Đơn giản nhất)
> **Đóng gói trước trên máy có Internet rồi copy thư mục `dist` sang máy nội bộ.**

1. Trên máy có Internet (hoặc máy cá nhân): Chạy `package.bat` theo mục 2 để tạo thư mục `dist`.
2. Copy toàn bộ thư mục `dist` (gồm 3 file: `MizuhoVendorHub.exe`, `db.sqlite3`, `config.ini`) qua USB hoặc kênh truyền file nội bộ sang máy đích.
3. Trên máy đích: **Không cần cài Python**, chỉ cần double-click `MizuhoVendorHub.exe` là chạy ngay.

---

### Phương án B: Đóng gói TRỰC TIẾP trên máy nội bộ không có Internet

Nếu bắt buộc phải build mã nguồn trực tiếp trên máy nội bộ:

#### Bước 1: Chuẩn bị gói cài đặt Offline (Thực hiện trên máy có Internet)
Mở Command Prompt (CMD) trên máy tính có mạng và tải sẵn các thư viện cần thiết vào một thư mục tên là `offline_packages`:

```cmd
mkdir offline_packages
pip download pyinstaller pillow -d ./offline_packages
```
*(Lệnh trên sẽ tải tất cả các file bánh xe `.whl` của PyInstaller và các gói phụ thuộc tương thích với Python của bạn vào thư mục `offline_packages`)*.

#### Bước 2: Chuyển thư mục `offline_packages` sang máy Offline
Copy thư mục `offline_packages` này và đặt nó nằm **ngay cạnh file `package.bat`** trong thư mục dự án trên máy offline:

```text
vendor_management/
├── offline_packages/         <-- Thư mục chứa các file .whl vừa copy sang
│   ├── pyinstaller-x.x.x-py3-none-any.whl
│   └── ...
├── package.bat
├── server.py
├── config.ini
├── db.sqlite3
└── logo.ico
```

#### Bước 3: Chạy đóng gói tự động
Double-click vào **`package.bat`**.

Script đã được cấu hình thông minh:
* Khi phát hiện máy không có Internet nhưng có thư mục `offline_packages`, nó sẽ tự động chạy lệnh:
  ```cmd
  python -m pip install --no-index --find-links=offline_packages pyinstaller
  ```
* Sau khi PyInstaller được cài đặt hoàn toàn offline, script sẽ tiếp tục đóng gói ứng dụng ra thư mục `dist` như bình thường.

---

## 4. Hướng dẫn sử dụng & Tùy chỉnh sau khi đóng gói

### Khởi chạy ứng dụng
* Vào thư mục `dist`, double-click vào **`MizuhoVendorHub.exe`**.
* Màn hình cửa sổ đen (Console) sẽ hiện lên thông báo:
  ```text
  2026-11-13 12:00:00 - INFO - DB absolute path: C:\...\dist\db.sqlite3
  2026-11-13 12:00:00 - INFO - Open: http://127.0.0.1:8800/
  ```
* Mở trình duyệt web bất kỳ (Chrome, Edge, Firefox) và truy cập vào địa chỉ:
  👉 **`http://127.0.0.1:8800/`**

### Thay đổi cấu hình (Cổng chạy / Host)
Mở file **`dist\config.ini`** bằng Notepad:
```ini
[server]
host = 127.0.0.1
port = 8800       # Đổi cổng chạy tại đây nếu cổng 8800 bị trùng

[database]
path = db.sqlite3 # Có thể trỏ sang file DB khác hoặc đường dẫn tuyệt đối
```
Lưu file và khởi động lại `MizuhoVendorHub.exe` để nhận cấu hình mới.

### Sao lưu dữ liệu (Backup)
* Để backup dữ liệu: Chỉ cần copy file **`dist\db.sqlite3`** cất vào nơi an toàn.
* Để phục hồi: Đè file backup vào lại thư mục `dist\db.sqlite3`.

---

## 5. Xử lý sự cố thường gặp (Troubleshooting)

| Sự cố | Nguyên nhân | Cách khắc phục |
| :--- | :--- | :--- |
| `Khong tim thay Python!` | Máy chưa cài Python hoặc chưa tích chọn `Add Python to PATH` | Cài đặt Python và tích chọn ô `Add Python to PATH` ở màn hình cài đặt đầu tiên. |
| Antivirus cảnh báo file `.exe` | Windows Defender hoặc Antivirus chặn file exe tự build (False Positive) | Chọn `More info` -> `Run anyway` hoặc thêm thư mục `dist` vào danh sách ngoại lệ (Exclusion). |
| `Address already in use` | Cổng 8800 đang có phần mềm khác chiếm dụng | Mở `dist\config.ini`, sửa `port = 8850` (hoặc cổng khác còn trống) rồi khởi động lại. |
| Bị mất dữ liệu khi tắt ứng dụng? | Trỏ nhầm database trong thư mục tạm | Bản build mới nhất đã được cấu hình cố định trỏ về `dist\db.sqlite3`, dữ liệu luôn được ghi vĩnh viễn trên ổ cứng. |
