@echo off
chcp 65001 > nul
setlocal

echo ========================================================
echo   BUILD VENDOR MANAGEMENT STANDALONE EXE CHO WINDOWS
echo ========================================================
echo.

:: 1. Kiem tra Python
python --version >nul 2>nul
if %errorlevel% neq 0 (
    echo [LOI] Khong tim thay Python! Vui long cai dat Python 3.9+ tren Windows
    echo       va nho tich chon "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

:: 2. Kiem tra / cai dat PyInstaller
echo [1/4] Kiem tra va cai dat PyInstaller...
python -m pip install --upgrade pip
python -m pip install pyinstaller

:: 3. Tien hanh dong goi
echo [2/4] Dang dong goi bang PyInstaller (Onefile)...
python -m PyInstaller --clean vendor_management.spec

if %errorlevel% neq 0 (
    echo [LOI] Qua trinh dong goi bi loi!
    pause
    exit /b 1
)

:: 4. Gom cac file thanh phan vao thu muc build
echo [3/4] Chuan bi thu muc phan phoi (build)...
if not exist "build" mkdir build

copy /Y "dist\vendor_management.exe" "build\"
copy /Y "config.ini" "build\"

if exist "db.sqlite3" (
    copy /Y "db.sqlite3" "build\"
) else (
    echo [INFO] db.sqlite3 chua co san, se duoc tao tu dong khi chay lan dau.
)

echo.
echo ========================================================
echo [4/4] DONG GOI HOAN TAT THANH CONG!
echo ========================================================
echo Cac file thanh phan duoc tao trong thu muc "build\":
echo   1. vendor_management.exe   (File chuong trinh chay)
echo   2. config.ini              (File cau hinh, chua duong dan db)
echo   3. db.sqlite3              (File co so du lieu)
echo.
echo Ban co the copy ca thu muc "build" sang may tinh khac de su dung.
echo ========================================================
pause
