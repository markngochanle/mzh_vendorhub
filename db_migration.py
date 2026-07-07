# db_migration.py
import os
import sqlite3
import logging

# Cấu hình logging để dễ theo dõi quá trình chạy
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("MigrationTool")

def check_and_migrate_db(db_path: str, table_schemas: dict):
    """
    Hàm kiểm tra database và thực hiện migration cho các bảng.
    
    Parameters:
    - db_path: Đường dẫn đến file SQLite database.
    - table_schemas: Dictionary chứa cấu trúc đích của các bảng cần quản lý.
      Ví dụ:
      {
          "users": {
              "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
              "name": "TEXT NOT NULL",
              "email": "TEXT UNIQUE",
              "age": "INTEGER"
          }
      }
    """
    # 1. Kiểm tra database tồn tại chưa
    db_exists = os.path.exists(db_path)
    if not db_exists:
        logger.info(f"Database tại '{db_path}' chưa tồn tại. Sẽ tiến hành tạo mới.")
    else:
        logger.info(f"Database tại '{db_path}' đã tồn tại. Tiến hành kiểm tra cấu trúc.")

    # sqlite3.connect sẽ tự động tạo file database mới nếu chưa có
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    try:
        # Tạm thời tắt foreign key constraints trong quá trình migration để tránh lỗi ràng buộc khi đổi tên bảng
        conn.execute("PRAGMA foreign_keys = OFF;")
        
        for table_name, target_columns in table_schemas.items():
            migrate_table(conn, table_name, target_columns)
            
        logger.info("Hoàn thành quá trình migration thành công!")
    except Exception as e:
        logger.error(f"Đã xảy ra lỗi trong quá trình migration: {e}")
        conn.rollback()
        raise e
    finally:
        # Bật lại foreign key constraints sau khi xong
        try:
            conn.execute("PRAGMA foreign_keys = ON;")
        except:
            pass
        conn.close()

def migrate_table(conn: sqlite3.Connection, table_name: str, target_columns: dict):
    """
    Đảm bảo bảng tồn tại và có cấu trúc chính xác như target_columns.
    Thêm cột thiếu và xóa cột thừa.
    """
    cur = conn.cursor()
    
    # 2. Kiểm tra bảng đã tồn tại chưa
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?;", (table_name,))
    table_exists = cur.fetchone() is not None
    
    if not table_exists:
        # Nếu chưa tồn tại, tạo mới bảng hoàn toàn
        logger.info(f"Bảng '{table_name}' chưa tồn tại. Đang tạo mới...")
        col_definitions = [f"{col_name} {col_def}" for col_name, col_def in target_columns.items()]
        create_sql = f"CREATE TABLE {table_name} (\n    " + ",\n    ".join(col_definitions) + "\n);"
        cur.execute(create_sql)
        conn.commit()
        logger.info(f"Đã tạo bảng '{table_name}' thành công.")
        return

    # 3. Nếu bảng đã tồn tại, kiểm tra và so sánh cột
    cur.execute(f"PRAGMA table_info({table_name});")
    current_columns_info = cur.fetchall()
    current_column_names = [row["name"] for row in current_columns_info]
    
    target_column_names = list(target_columns.keys())
    
    # Tìm cột thiếu và cột thừa
    missing_columns = [col for col in target_column_names if col not in current_column_names]
    extra_columns = [col for col in current_column_names if col not in target_column_names]
    
    if not missing_columns and not extra_columns:
        logger.info(f"Bảng '{table_name}' đã chuẩn cấu trúc. Không cần thay đổi.")
        return
        
    logger.info(f"Bảng '{table_name}' phát hiện thay đổi cấu trúc:")
    if missing_columns:
        logger.info(f"  - Thiếu cột: {missing_columns}")
    if extra_columns:
        logger.info(f"  - Thừa cột: {extra_columns}")

    # Trường hợp 1: Chỉ có cột thiếu (Không có cột thừa)
    # Ta có thể dùng `ALTER TABLE ADD COLUMN` trực tiếp cho nhanh và an toàn
    if missing_columns and not extra_columns:
        logger.info(f"Đang thêm các cột thiếu vào bảng '{table_name}'...")
        for col in missing_columns:
            col_def = target_columns[col]
            alter_sql = f"ALTER TABLE {table_name} ADD COLUMN {col} {col_def};"
            cur.execute(alter_sql)
        conn.commit()
        logger.info(f"Đã thêm các cột {missing_columns} vào bảng '{table_name}'.")
        return

    # Trường hợp 2: Có cột thừa cần xóa (hoặc vừa thiếu vừa thừa)
    # SQLite phiên bản cũ (trước 3.35.0) không hỗ trợ DROP COLUMN.
    # Để an toàn nhất trên mọi phiên bản SQLite, ta sử dụng phương pháp "Table Reconstruction":
    # 1. Đổi tên bảng cũ thành bảng tạm (_old)
    # 2. Tạo bảng mới với cấu trúc chuẩn
    # 3. Copy dữ liệu từ các cột chung của bảng cũ sang bảng mới
    # 4. Xóa bảng tạm
    logger.info(f"Bảng '{table_name}' có cột thừa cần xóa. Bắt đầu tái cấu trúc bảng (Table Reconstruction)...")
    
    try:
        # Bắt đầu transaction phụ
        cur.execute("SAVEPOINT migration_savepoint;")
        
        # 1. Đổi tên bảng cũ thành temp_old
        temp_old_name = f"{table_name}_old_temp"
        cur.execute(f"ALTER TABLE {table_name} RENAME TO {temp_old_name};")
        
        # 2. Tạo bảng mới với cấu trúc đích mong muốn
        col_definitions = [f"{col_name} {col_def}" for col_name, col_def in target_columns.items()]
        create_sql = f"CREATE TABLE {table_name} (\n    " + ",\n    ".join(col_definitions) + "\n);"
        cur.execute(create_sql)
        
        # 3. Copy dữ liệu từ cột chung (cột có ở cả bảng cũ và bảng đích)
        common_columns = [col for col in target_column_names if col in current_column_names]
        common_cols_str = ", ".join(common_columns)
        
        insert_sql = f"INSERT INTO {table_name} ({common_cols_str}) SELECT {common_cols_str} FROM {temp_old_name};"
        cur.execute(insert_sql)
        
        # 4. Xóa bảng tạm cũ
        cur.execute(f"DROP TABLE {temp_old_name};")
        
        # Giải phóng Savepoint
        cur.execute("RELEASE migration_savepoint;")
        conn.commit()
        logger.info(f"Tái cấu trúc bảng '{table_name}' hoàn tất. Đã thêm cột thiếu và xóa cột thừa.")
        
    except Exception as e:
        cur.execute("ROLLBACK TO migration_savepoint;")
        logger.error(f"Lỗi khi tái cấu trúc bảng '{table_name}': {e}")
        raise e

# =====================================================================
# Ví dụ chạy thử nghiệm (Demo)
# =====================================================================
if __name__ == "__main__":
    # Đường dẫn file DB chạy thử
    DEMO_DB = "demo_migration.db"
    
    # Xóa file db cũ nếu có để chạy lại từ đầu cho trực quan
    if os.path.exists(DEMO_DB):
        os.remove(DEMO_DB)
        
    # Bước 1: Định nghĩa cấu trúc ban đầu (bảng users có id, name, age, address)
    schema_v1 = {
        "users": {
            "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
            "name": "TEXT NOT NULL",
            "age": "INTEGER",
            "address": "TEXT"
        }
    }
    
    print("\n--- BƯỚC 1: KHỞI TẠO DATABASE VÀ BẢNG LẦN ĐẦU (SCHEMA V1) ---")
    check_and_migrate_db(DEMO_DB, schema_v1)
    
    # Insert dữ liệu mẫu vào
    conn = sqlite3.connect(DEMO_DB)
    conn.row_factory = sqlite3.Row
    conn.execute("INSERT INTO users (name, age, address) VALUES ('Nguyen Van A', 25, 'Ha Noi');")
    conn.execute("INSERT INTO users (name, age, address) VALUES ('Tran Thi B', 30, 'TP HCM');")
    conn.commit()
    
    print("\nDữ liệu hiện tại trong DB:")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users;")
    for row in cursor.fetchall():
        print(dict(row))
    conn.close()

    # Bước 2: Thay đổi schema (V2)
    # - Thêm cột: `email` (TEXT)
    # - Xóa cột thừa: `address`
    schema_v2 = {
        "users": {
            "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
            "name": "TEXT NOT NULL",
            "age": "INTEGER",
            "email": "TEXT" # Cột mới thêm
            # Cột 'address' đã bị loại bỏ ở đây
        }
    }
    
    print("\n--- BƯỚC 2: MIGRATION SANG SCHEMA V2 (THÊM CỘT 'email', XÓA CỘT 'address') ---")
    check_and_migrate_db(DEMO_DB, schema_v2)
    
    # Kiểm tra lại dữ liệu và cấu trúc sau khi migrate
    conn = sqlite3.connect(DEMO_DB)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("\nCấu trúc bảng users hiện tại:")
    cursor.execute("PRAGMA table_info(users);")
    for col in cursor.fetchall():
        print(f"Cột: {col['name']} | Kiểu: {col['type']}")
        
    print("\nDữ liệu bảng users hiện tại (dữ liệu cũ vẫn được giữ nguyên ở các cột chung):")
    cursor.execute("SELECT * FROM users;")
    for row in cursor.fetchall():
        print(dict(row))
    conn.close()
    
    # Dọn dẹp file thử nghiệm
    if os.path.exists(DEMO_DB):
        os.remove(DEMO_DB)
