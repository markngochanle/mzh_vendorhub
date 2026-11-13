@echo off
chcp 65001 >nul
title Packaging Mizuho Vendor Management App to Windows EXE

echo =========================================================
echo   DONG GOI UNG DUNG MIZUHO VENDOR MANAGEMENT (WINDOWS EXE)
echo =========================================================
echo.

REM Chuyen den thu muc chua file bat
cd /d "%~dp0"

REM 1. Kiem tra Python
echo [1/5] Kiem tra moi truong Python...
where python >nul 2>&1
if %errorlevel% equ 0 (
    set "PY_CMD=python"
) else (
    where py >nul 2>&1
    if %errorlevel% equ 0 (
        set "PY_CMD=py -3"
    ) else (
        echo [ERROR] Khong tim thay Python! Vui long cai dat Python 3 va tick chon "Add Python to PATH".
        echo Link tai: https://www.python.org/downloads/
        goto :failed
    )
)
echo      Da tim thay: %PY_CMD%

REM 2. Kiem tra va cai dat PyInstaller
echo.
echo [2/5] Kiem tra PyInstaller...
%PY_CMD% -c "import PyInstaller" >nul 2>&1
if %errorlevel% neq 0 (
    if exist "offline_packages" (
        echo      Phat hien thu muc offline_packages! Dang cai dat che do OFFLINE...
        %PY_CMD% -m pip install --no-index --find-links=offline_packages pyinstaller
    ) else (
        echo      Dang cai dat PyInstaller qua pip (can ket noi Internet)...
        %PY_CMD% -m pip install pyinstaller
    )
    if %errorlevel% neq 0 (
        echo [ERROR] Cai dat PyInstaller that bai!
        echo [*] Neu may cua ban KHONG CO INTERNET:
        echo     Vui long xem chi tiet tai file HUONG_DAN_DONG_GOI.md de tai thu muc offline_packages.
        goto :failed
    )
) else (
    echo      PyInstaller da san sang.
)

REM 3. Kiem tra icon logo.ico
echo.
echo [3/5] Kiem tra icon dai dien (logo.ico)...
if not exist "logo.ico" (
    if exist "logo.png" (
        echo      Dang chuyen doi logo.png thanh logo.ico...
        %PY_CMD% -c "from PIL import Image; img=Image.open('logo.png'); img.save('logo.ico', format='ICO', sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])" 2>nul
    )
)

set "ICON_PARAM="
if exist "logo.ico" (
    set "ICON_PARAM=--icon=logo.ico"
    echo      Su dung icon: logo.ico
) else (
    echo      [CANH BAO] Khong tim thay logo.ico, tiep tuc dong goi khong icon.
)

REM 4. Thuc hien dong goi voi PyInstaller
echo.
echo [4/5] Dang dong goi ma nguon thanh file EXE duy nhat...
%PY_CMD% -m PyInstaller ^
    --noconfirm ^
    --onefile ^
    --clean ^
    --name="MizuhoVendorHub" ^
    %ICON_PARAM% ^
    --add-data "static;static" ^
    --add-data "logo.png;." ^
    server.py

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Qua trinh dong goi EXE gap loi!
    goto :failed
)

REM 5. Sao chep database va config vao thu muc dist
echo.
echo [5/5] Hoan thien thu muc dist...
if not exist "dist" mkdir "dist"

if exist "db.sqlite3" (
    copy /Y "db.sqlite3" "dist\db.sqlite3" >nul
    echo      Da copy db.sqlite3 vao dist\
) else if exist "database.sqlite3" (
    copy /Y "database.sqlite3" "dist\db.sqlite3" >nul
    echo      Da copy database.sqlite3 thanh dist\db.sqlite3
)

if exist "config.ini" (
    copy /Y "config.ini" "dist\config.ini" >nul
    echo      Da copy config.ini vao dist\
)

REM Don dep file tam build va spec
if exist "build" rmdir /s /q "build"
if exist "MizuhoVendorHub.spec" del /f /q "MizuhoVendorHub.spec"

echo.
echo =========================================================
echo   HOAN THANH XUAT SAC! CAC FILE TRONG THU MUC dist:
echo =========================================================
echo   1. dist\MizuhoVendorHub.exe  (Ung dung chay web server co icon logo)
echo   2. dist\db.sqlite3           (Co so du lieu SQLite dung doc lap)
echo   3. dist\config.ini           (File cau hinh port, host, db_path)
echo =========================================================
echo.
echo Chi can copy toan bo thu muc "dist" sang may bat ky de chay truc tiep!
pause
exit /b 0

:failed
echo.
echo =========================================================
echo   DONG GOI THAT BAI! Vui long kiem tra cac thong bao loi o tren.
echo =========================================================
pause
exit /b 1
