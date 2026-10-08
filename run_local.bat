@echo off
title Fintrust EWS - Browser Launcher

echo =======================================================================
echo * HE THONG CANH BAO SOM EWS FINTRUST - KHOI DONG TRICH XUAT BCTC *
echo =======================================================================
echo.

rem 1. Kiem tra su hien huu cua Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Khong tim thay Python tren may tinh cua ban!
    echo.
    echo Vui long thuc hien 1 trong 2 cach sau de cai dat Python:
    echo - Cach 1 [Khuyen nghi]: Mo ung dung "Microsoft Store" tren Windows,
    echo   tim kiem tu khoa "Python 3.10" hoac "Python 3.11" va nhan "Get" hoac "Install".
    echo - Cach 2: Tai bo cai dat .exe tu trang chu: https://www.python.org/downloads/
    echo   [Luu y: Nho tich chon o "Add Python to PATH" khi cai dat].
    echo.
    pause
    exit /b
)

rem 2. Khoi tao moi truong ao Python [venv]
if not exist "venv" (
    echo [*] Dang khoi tao moi truong ao Python [venv] cho lan dau chay...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo [ERROR] Khong the khoi tao moi truong ao venv!
        pause
        exit /b
    )
)

rem 3. Kich hoat moi truong ao va cai dat thu vien
echo [*] Dang kich hoat moi truong ao venv...
call venv\Scripts\activate

if not exist "venv\.installed" (
    echo [*] Dang kiem tra va cai dat cac thu vien phu thuoc lan dau...
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [ERROR] Cai dat thu vien that bai! Vui long kiem tra lai ket noi mang.
        pause
        exit /b
    )
    type nul > "venv\.installed"
    echo [OK] Da chuan bi xong thu vien.
) else (
    echo [OK] Moi truong thu vien da san sang (khoi dong tuc thi).
)
echo.

rem 4. Khoi chay Streamlit Server
echo [*] Dang khoi chay Fintrust EWS tren trinh duyet web...
echo [TIP] De tat phan mem, ban chi can dong cua so cmd nay lai.
echo.
streamlit run fintrust_app.py

pause
