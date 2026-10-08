#!/bin/bash

# Thiet lap tieu de console
echo -e "\033]0;Fintrust EWS - Browser Launcher\007"

echo "======================================================================="
echo "* HE THONG CANH BAO SOM EWS FINTRUST - KHOI DONG TRICH XUAT BCTC *"
echo "======================================================================="
echo ""

# 1. Kiem tra su hien huu cua Python 3
python3 --version >/dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "[ERROR] Khong tim thay Python 3 tren may Mac cua ban!"
    echo "Vui long tai va cai dat Python 3 tu trang chu: https://www.python.org/downloads/"
    echo ""
    read -p "Nhan [Enter] de thoat..."
    exit 1
fi

# 2. Khoi tao moi truong ao Python (venv)
if [ ! -d "venv" ]; then
    echo "[*] Dang khoi tao moi truong ao Python (venv) cho lan dau chay..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "[ERROR] Khong the khoi tao moi truong ao venv!"
        read -p "Nhan [Enter] de thoat..."
        exit 1
    fi
fi

# 3. Kich hoat moi truong ao va cai dat thu vien
echo "[*] Dang kich hoat moi truong ao venv..."
source venv/bin/activate

if [ ! -f "venv/.installed" ]; then
    echo "[*] Dang kiem tra va cai dat cac thu vien phu thuoc lan dau..."
    python3 -m pip install --upgrade pip
    pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "[ERROR] Cai dat thu vien that bai! Vui long kiem tra ket noi mang."
        read -p "Nhan [Enter] de thoat..."
        exit 1
    fi
    touch venv/.installed
    echo "[OK] Da chuan bi xong thu vien."
else
    echo "[OK] Moi truong thu vien da san sang (khoi dong tuc thi)."
fi
echo ""

# 4. Khoi chay Streamlit Server
echo "[*] Dang khoi chay Fintrust EWS tren trinh duyet web..."
echo "[TIP] De dung phan mem, ban co the nhan Ctrl + C tai day hoac dong cua so nay lai."
echo ""
streamlit run fintrust_app.py
