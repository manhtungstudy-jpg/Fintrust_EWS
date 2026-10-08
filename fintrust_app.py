import streamlit as st
import pandas as pd
import numpy as np
import io
import re
import pdfplumber
import os
import json
import math
import sqlite3
import datetime
import sys

# -------------------------------------------------------------------------
# CƠ SỞ DỮ LIỆU SQLITE VÀ HÀM TIÊU CHUẨN HÓA DỮ LIỆU (BƯỚC 1)
# -------------------------------------------------------------------------
# Lấy thư mục chạy thực tế từ biến môi trường (được truyền từ desktop_wrapper.py) để lưu database cố định
BASE_DIR = os.environ.get("FINTRUST_EXE_DIR", os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "fintrust_ews.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            ticker TEXT PRIMARY KEY,
            company_name TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS financial_data (
            ticker TEXT,
            year INTEGER,
            variable TEXT,
            value REAL,
            PRIMARY KEY (ticker, year, variable),
            FOREIGN KEY (ticker) REFERENCES companies(ticker)
        )
    """)
    conn.commit()
    conn.close()

def save_to_db(ticker, company_name, financial_data):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO companies (ticker, company_name) VALUES (?, ?)", (ticker, company_name))
    for year, data in financial_data.items():
        for var, val in data.items():
            if var.startswith("_"):
                continue
            val_to_save = float(val) if (val is not None and not pd.isna(val)) else None
            cursor.execute("""
                INSERT OR REPLACE INTO financial_data (ticker, year, variable, value) 
                VALUES (?, ?, ?, ?)
            """, (ticker, int(year), var, val_to_save))
    conn.commit()
    conn.close()

def reconcile_financial_data(financial_data):
    """Tự động chuẩn hóa và cân đối các chỉ tiêu kế toán cơ bản theo Thông tư 200."""
    if not financial_data:
        return financial_data
    for y, y_data in financial_data.items():
        sales = y_data.get("Net_Sales")
        cogs = y_data.get("COGS")
        gp = y_data.get("Gross_Profit")
        
        # 1. Chuẩn hóa các chỉ tiêu tài sản và chi phí luôn dương
        for pos_var in ["COGS", "Selling_Expense", "GA_Expense", "Interest_Expense", "Tangible_PPE_Cost", "Total_Assets", "Total_Liabilities", "Current_Liabilities", "Current_Assets", "Fixed_Assets", "Cash_Equivalents", "Inventories", "Current_Receivables", "Accounts_Receivable"]:
            if pos_var in y_data and y_data[pos_var] is not None and not pd.isna(y_data[pos_var]):
                y_data[pos_var] = abs(y_data[pos_var])
            
        # 2. Cân đối KQKD: Lợi nhuận gộp (20) = Doanh thu thuần (10) - Giá vốn (11)
        if sales is not None and not pd.isna(sales) and sales > 0:
            if (gp is None or pd.isna(gp) or gp == 0) and (cogs is not None and not pd.isna(cogs) and cogs > 0):
                y_data["Gross_Profit"] = sales - cogs
            elif (cogs is None or pd.isna(cogs) or cogs == 0) and (gp is not None and not pd.isna(gp)):
                y_data["COGS"] = sales - gp
            
        # 3. Cân đối CĐKT: Tổng tài sản (270) = Nợ phải trả (300) + Vốn CSH (400)
        ta = y_data.get("Total_Assets")
        liab = y_data.get("Total_Liabilities")
        eq = y_data.get("Equity")
        if ta is not None and not pd.isna(ta) and ta > 0:
            if (liab is None or pd.isna(liab) or liab == 0) and (eq is not None and not pd.isna(eq) and eq > 0):
                y_data["Total_Liabilities"] = ta - eq
            elif (eq is None or pd.isna(eq) or eq == 0) and (liab is not None and not pd.isna(liab) and liab > 0):
                y_data["Equity"] = ta - liab
                
        # 4. Cân đối Tài sản ngắn hạn & Dài hạn
        ca = y_data.get("Current_Assets")
        fa = y_data.get("Fixed_Assets")
        if ta is not None and not pd.isna(ta) and ta > 0:
            if (ca is None or pd.isna(ca) or ca == 0) and fa is not None and not pd.isna(fa) and 0 < fa < ta:
                y_data["Current_Assets"] = ta - fa
            elif (fa is None or pd.isna(fa) or fa == 0) and ca is not None and not pd.isna(ca) and 0 < ca < ta:
                y_data["Fixed_Assets"] = ta - ca
                
        # 5. Default Selling_Expense và Interest_Expense = 0.0 nếu có KQKD nhưng không phát sinh
        if ("Selling_Expense" not in y_data or y_data["Selling_Expense"] is None) and sales is not None and sales > 0:
            y_data["Selling_Expense"] = 0.0
        if ("Interest_Expense" not in y_data or y_data["Interest_Expense"] is None) and sales is not None and sales > 0:
            y_data["Interest_Expense"] = 0.0
            
        # 6. Cân đối EBT từ Net_Income nếu thiếu
        ebt = y_data.get("EBT")
        ni = y_data.get("Net_Income")
        if (ebt is None or pd.isna(ebt) or ebt == 0) and ni is not None and ni != 0:
            y_data["EBT"] = ni
            
    return financial_data

def load_from_db(ticker):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT company_name FROM companies WHERE ticker = ?", (ticker,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None, None
    company_name = row[0]
    
    cursor.execute("SELECT year, variable, value FROM financial_data WHERE ticker = ?", (ticker,))
    rows = cursor.fetchall()
    conn.close()
    
    financial_data = {}
    for year, variable, value in rows:
        y_int = int(year)
        if y_int not in financial_data:
            financial_data[y_int] = {}
        financial_data[y_int][variable] = value
        
    financial_data = reconcile_financial_data(financial_data)
    return company_name, financial_data

@st.cache_data(ttl=60, show_spinner=False)
def get_saved_tickers_from_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT ticker, company_name FROM companies ORDER BY ticker")
    rows = cursor.fetchall()
    conn.close()
    return rows

@st.cache_resource(show_spinner=False)
def ensure_db_initialized(storage_dir):
    init_db()
    if os.path.exists(storage_dir):
        for filename in os.listdir(storage_dir):
            if filename.endswith(".json"):
                ticker = filename[:-5]
                try:
                    with open(os.path.join(storage_dir, filename), "r", encoding="utf-8") as f:
                        data = json.load(f)
                    save_to_db(data["ticker"], data["company_name"], data["financial_data"])
                except Exception:
                    pass
    return True

@st.cache_resource(show_spinner=False)
def load_cached_ml_model(model_file="best_ews_model.joblib"):
    if os.path.exists(model_file):
        try:
            import joblib
            return joblib.load(model_file)
        except Exception:
            return None
    return None

def migrate_json_to_sqlite(storage_dir):
    ensure_db_initialized(storage_dir)

@st.cache_data(show_spinner=False)
def generate_markdown_summary(company_name, ticker, extracted_data, ews_results, firm_age, tobin_q, div_ratio, isg, ab_return, unconditional_prob):
    md = []
    md.append(f"# BÁO CÁO CẢNH BÁO SỚM RỦI RO DOANH NGHIỆP (EWS)")
    md.append(f"**Doanh nghiệp**: {company_name}")
    md.append(f"**Mã chứng khoán**: {ticker}")
    md.append(f"**Ngày lập báo cáo**: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    md.append("")
    md.append("## 1. Tham số đầu vào cấu hình")
    md.append(f"- Tuổi doanh nghiệp: {firm_age} năm")
    md.append(f"- Tỷ số Tobin's Q: {tobin_q}")
    md.append(f"- Tỷ lệ chi trả cổ tức: {div_ratio:.1%}")
    md.append(f"- Tăng trưởng DT ngành (ISG): {isg:.1%}")
    md.append(f"- Tỷ suất sinh lời bất thường: {ab_return:.1%}")
    md.append(f"- Xác suất gian lận gốc: {unconditional_prob:.3%}")
    md.append("")
    
    md.append("## 2. Dữ liệu tài chính trích xuất")
    years = sorted(list(extracted_data.keys()))
    
    header = "| Chỉ tiêu tài chính | " + " | ".join(f"Năm {y}" for y in years) + " |"
    divider = "| :--- | " + " | ".join(":---:" for _ in years) + " |"
    md.append(header)
    md.append(divider)
    
    for var, vname in VAR_NAMES_VN.items():
        row_cells = [vname]
        for y in years:
            val = extracted_data[y].get(var, np.nan)
            if pd.isna(val) or val is None:
                row_cells.append("-")
            else:
                row_cells.append(f"{val:,.0f}" if abs(val) > 1000 else f"{val:.4f}")
        md.append("| " + " | ".join(row_cells) + " |")
        
    md.append("")
    md.append("## 3. Kết quả 10 chỉ số Cảnh báo sớm (EWS)")
    
    ews_names = {
        "Altman_Z_Prime": "Altman Z'-Score",
        "SA_Index": "SA Index",
        "Beneish_M_Score": "Beneish M-Score (1999)",
        "Beneish_M_Score_12": "Beneish M-Score (1997 - Probit)",
        "Dechow_F_Score": "Dechow F-Score",
        "Abnormal_CFO": "Abnormal CFO",
        "Abnormal_PROD": "Abnormal Production",
        "Abnormal_DISEXP": "Abnormal Discretionary Exp",
        "KZ_Index": "KZ Index",
        "WW_Index": "WW Index"
    }
    
    ews_header = "| Chỉ số EWS | " + " | ".join(f"Năm {y}" for y in years) + " |"
    ews_divider = "| :--- | " + " | ".join(":---:" for _ in years) + " |"
    md.append(ews_header)
    md.append(ews_divider)
    
    for var_key, display_name in ews_names.items():
        row_cells = [display_name]
        for y in years:
            res = ews_results[y].get(var_key)
            if res is None:
                row_cells.append("N/A")
            else:
                score = res["score"]
                status = res["status"]
                zone = res["zone"]
                color_emoji = "🟢" if status == "success" else ("🟡" if status == "warning" else "🔴")
                row_cells.append(f"{color_emoji} {score:.4f}")
        md.append("| " + " | ".join(row_cells) + " |")
        
    md.append("")
    md.append("## 4. Kết luận chi tiết và Cảnh báo tổng hợp")
    
    for y in years:
        md.append(f"### Năm {y}:")
        y_alerts = []
        
        cfo_y = ews_results[y].get("Abnormal_CFO")
        prod_y = ews_results[y].get("Abnormal_PROD")
        disexp_y = ews_results[y].get("Abnormal_DISEXP")
        
        if cfo_y and prod_y and disexp_y:
            if cfo_y["score"] < -0.05 and prod_y["score"] > 0.05 and disexp_y["score"] < -0.03:
                y_alerts.append("> ⚠️ **[CẢNH BÁO ĐỎ TỔNG HỢP REM]**: Phát hiện đồng thời hành vi thao túng hoạt động thực tế. Doanh nghiệp nới lỏng tín dụng (Ab_CFO < -0.05), sản xuất quá mức để giảm giá vốn (Ab_PROD > 0.05) và cắt giảm chi phí tùy quyết (Ab_DISEXP < -0.03) để thổi phồng lợi nhuận. Khuyến nghị kiểm tra chuyên sâu!")
                
        m_y = ews_results[y].get("Beneish_M_Score")
        f_y = ews_results[y].get("Dechow_F_Score")
        if m_y and f_y:
            if m_y["score"] > -1.78 and f_y["score"] > 1.85:
                y_alerts.append("> ⚠️ **[CẢNH BÁO BÓP MÉO BCTC]**: Có sự đồng thuận giữa Beneish M-Score và Dechow F-Score. Báo cáo tài chính bị bóp méo nghiêm trọng. Mọi thông tin sinh lời đều không đáng tin cậy.")
                
        for var_key, display_name in ews_names.items():
            res = ews_results[y].get(var_key)
            if res and res["status"] == "error":
                y_alerts.append(f"- **{display_name}**: Cảnh báo rủi ro cao ({res['zone']}). Điểm số: {res['score']:.4f}")
            elif res and res["status"] == "warning":
                y_alerts.append(f"- **{display_name}**: Chú ý rủi ro trung bình ({res['zone']}). Điểm số: {res['score']:.4f}")
                
        if not y_alerts:
            md.append("🟢 Không có cảnh báo đặc biệt nào. Khách hàng nằm trong vùng an toàn lý thuyết.")
        else:
            md.extend(y_alerts)
            
        md.append("")
        
    md.append("## 5. Đánh giá Định tính 5Cs & Hệ sinh thái Chuỗi cung ứng")
    latest_year = max(years)
    latest_data = extracted_data.get(latest_year, {})
    total_5c = latest_data.get("Qual_5C_TotalScore", 75.0)
    md.append(f"- **Điểm Định tính 5Cs Toàn diện**: {total_5c:.1f} / 100 điểm")
    md.append("- **Cơ cấu điểm 5Cs**:")
    md.append("  - C1: Uy tín & Năng lực Lãnh đạo (20%)")
    md.append("  - C2: Năng lực Quản trị & KSoNB (20%)")
    md.append("  - C3: Tính Xác thực BCTC & Đối chiếu Thuế (25%)")
    md.append("  - C4: Môi trường Ngành & Cạnh tranh (15%)")
    md.append("  - C5: Quan hệ Chuỗi Cung ứng & RPT trong Hệ sinh thái (20%)")
    md.append("")
    md.append("## 6. Khuyến nghị Phê duyệt & Kiểm soát Sau giải ngân")
    md.append("1. **Kiểm tra Hóa đơn GTGT & Tờ khai Thuế**: Yêu cầu cung cấp tờ khai thuế GTGT hàng quý và đối chiếu với doanh thu BCTC.")
    md.append("2. **Giám sát Dòng tiền Tài khoản**: Định kỳ rà soát sao kê dòng tiền thực tế về tài khoản để đối trừ công nợ.")
    md.append("3. **Kiểm tra Giao dịch Bên liên quan (RPT)**: Giám sát chặt chẽ các khoản tạm ứng, cho mượn vốn với các công ty thành viên trong tập đoàn.")
    md.append("")
    md.append("---")
    md.append("*Báo cáo được tạo tự động bởi Hệ thống FinTrust EWS.*")
    return "\n".join(md)

# -------------------------------------------------------------------------
# BỘ CÔNG CỤ ĐÁNH GIÁ ĐỊNH TÍNH 5CS & HỆ SINH THÁI (KHỐI 2)
# -------------------------------------------------------------------------

DEFAULT_5C_CONFIG = {
    # C1: Uy tín & Năng lực Lãnh đạo (Character & Management - 20%)
    "c1_mgmt_exp": {
        "group": "C1",
        "label": "Thâm niên Ban điều hành trong ngành",
        "options": {
            "Trên 10 năm (> 10 năm kinh nghiệm chuyên sâu)": 100,
            "Từ 5 đến 10 năm": 80,
            "Từ 3 đến 5 năm": 60,
            "Dưới 3 năm (Ban lãnh đạo mới, ít kinh nghiệm)": 35
        },
        "default": "Từ 5 đến 10 năm"
    },
    "c1_cic_history": {
        "group": "C1",
        "label": "Lịch sử tín dụng CIC (Doanh nghiệp & Chủ DN)",
        "options": {
            "Nhóm 1 chuẩn (Không có chậm trả, trả nợ đúng hạn 100%)": 100,
            "Từng phát sinh Nhóm 2 nhưng đã tất toán > 12 tháng": 75,
            "Từng có nợ xấu Nhóm 3-5 trong 3-5 năm trước (đã xử lý)": 40,
            "Hiện tại đang có nợ cần chú ý (Nhóm 2) hoặc nợ xấu (Nhóm 3-5)": 10
        },
        "default": "Nhóm 1 chuẩn (Không có chậm trả, trả nợ đúng hạn 100%)"
    },
    "c1_owner_commitment": {
        "group": "C1",
        "label": "Mức độ gắn bó & Sở hữu của Cổ đông sáng lập/Chủ DN",
        "options": {
            "Nắm giữ chi phối > 51% và trực tiếp tham gia điều hành": 100,
            "Nắm giữ từ 25% đến 50%, đồng hành lâu năm": 80,
            "Nắm giữ 10% đến 25%": 60,
            "Tỷ lệ sở hữu thấp (< 10%) hoặc liên tục thoái vốn": 30
        },
        "default": "Nắm giữ chi phối > 51% và trực tiếp tham gia điều hành"
    },
    "c1_legal_compliance": {
        "group": "C1",
        "label": "Tính minh bạch pháp lý & Tranh chấp kiện tụng",
        "options": {
            "Không có bất kỳ tranh chấp, khiếu kiện hay xử phạt nào": 100,
            "Có tranh chấp kinh tế dân sự nhỏ (giá trị < 2% Vốn CSH)": 70,
            "Đang bị thanh tra thuế / cơ quan quản lý xử phạt hành chính": 40,
            "Có tranh chấp kiện tụng lớn hoặc bị khởi tố pháp lý": 10
        },
        "default": "Không có bất kỳ tranh chấp, khiếu kiện hay xử phạt nào"
    },

    # C2: Năng lực Quản trị & Vận hành (Capacity & Governance - 20%)
    "c2_board_structure": {
        "group": "C2",
        "label": "Cơ cấu Quản trị (HĐQT & Ban Kiểm soát)",
        "options": {
            "HĐQT có > 1/3 TV độc lập, BKS độc lập hoạt động thực chất": 100,
            "Đầy đủ ban bệ theo luật định nhưng TV độc lập mờ nhạt": 75,
            "Tập trung quyền lực (Chủ tịch kiêm Tổng giám đốc, không TV độc lập)": 50,
            "Quản trị mô hình gia đình, thiếu sự giám sát độc lập": 30
        },
        "default": "Đầy đủ ban bệ theo luật định nhưng TV độc lập mờ nhạt"
    },
    "c2_internal_control": {
        "group": "C2",
        "label": "Hệ thống Kiểm soát Nội bộ (KSoNB) & Quản trị rủi ro",
        "options": {
            "Quy trình chuẩn hóa COSO/ISO, có Kiểm toán Nội bộ độc lập": 100,
            "Có quy trình KSoNB cơ bản và phân quyền phê duyệt rõ ràng": 75,
            "Quy trình còn sơ sài, phê duyệt chủ yếu theo cảm tính lãnh đạo": 45,
            "Không có hệ thống KSoNB, rủi ro gian lận nội bộ cao": 20
        },
        "default": "Có quy trình KSoNB cơ bản và phân quyền phê duyệt rõ ràng"
    },
    "c2_erp_tech": {
        "group": "C2",
        "label": "Mức độ Số hóa & Ứng dụng ERP trong Quản trị Dòng tiền/Kho",
        "options": {
            "Hệ thống ERP đồng bộ (SAP, Oracle...) quản lý thời gian thực": 100,
            "Phần mềm kế toán & quản trị bán hàng đồng bộ (MISA, Fast...)": 80,
            "Sử dụng phần mềm kế toán độc lập, dữ liệu kho/bán hàng rời rạc": 55,
            "Quản lý thủ công bằng Excel và sổ sách giấy": 25
        },
        "default": "Phần mềm kế toán & quản trị bán hàng đồng bộ (MISA, Fast...)"
    },
    "c2_hr_stability": {
        "group": "C2",
        "label": "Tính ổn định Nhân sự cấp cao & Kế toán trưởng",
        "options": {
            "Đội ngũ lãnh đạo và Kế toán trưởng ổn định gắn bó > 3 năm": 100,
            "Thay đổi nhân sự theo quy hoạch kế thừa bình thường": 80,
            "Kế toán trưởng hoặc Giám đốc tài chính (CFO) thay đổi trong năm": 50,
            "Kế toán trưởng / Ban điều hành thay đổi liên tục bất thường": 25
        },
        "default": "Đội ngũ lãnh đạo và Kế toán trưởng ổn định gắn bó > 3 năm"
    },

    # C3: Tính Xác thực & Chất lượng BCTC (BCTC Transparency & Audit Quality - 25%)
    "c3_audit_firm": {
        "group": "C3",
        "label": "Đơn vị Kiểm toán Độc lập",
        "options": {
            "Big 4 (PwC, EY, KPMG, Deloitte) - Độ tin cậy cao nhất": 100,
            "Top 10 Công ty Kiểm toán uy tín tại Việt Nam (BDO, Grant Thornton, A&C, VACO, UHY...)": 85,
            "Công ty kiểm toán vừa và nhỏ địa phương": 55,
            "Báo cáo Tài chính nội bộ / Chưa được kiểm toán độc lập": 20
        },
        "default": "Top 10 Công ty Kiểm toán uy tín tại Việt Nam (BDO, Grant Thornton, A&C, VACO, UHY...)"
    },
    "c3_audit_opinion": {
        "group": "C3",
        "label": "Ý kiến của Kiểm toán viên trên Báo cáo Kiểm toán",
        "options": {
            "Chấp nhận toàn phần (Ý kiến chuẩn mực)": 100,
            "Chấp nhận toàn phần nhưng có Đoạn nhấn mạnh / Vấn đề cần lưu ý": 70,
            "Ý kiến kiểm toán Ngoại trừ (Qualified Opinion)": 30,
            "Từ chối đưa ra ý kiến (Disclaimer) hoặc Ý kiến trái ngược (Adverse)": 0
        },
        "default": "Chấp nhận toàn phần (Ý kiến chuẩn mực)"
    },
    "c3_tax_consistency": {
        "group": "C3",
        "label": "Độ Khớp giữa BCTC và Tờ khai Thuế (Thuế GTGT, Thuế TNDN)",
        "options": {
            "Khớp 100% doanh thu & chi phí hợp lệ giữa BCTC và Tờ khai Thuế": 100,
            "Chênh lệch nhỏ (< 5%) do khác biệt thời điểm ghi nhận theo luật kế toán vs thuế": 85,
            "Chênh lệch từ 5% đến 20% (Có văn bản giải trình hợp lý)": 55,
            "Chênh lệch lớn bất thường (> 20%) không giải trình được nguồn gốc": 15
        },
        "default": "Khớp 100% doanh thu & chi phí hợp lệ giữa BCTC và Tờ khai Thuế"
    },
    "c3_disclosure_quality": {
        "group": "C3",
        "label": "Độ chi tiết & Minh bạch Thuyết minh BCTC",
        "options": {
            "Thuyết minh bóc tách chi tiết từng khoản mục Phải thu, Tồn kho, Nợ vay & TSĐB": 100,
            "Thuyết minh đầy đủ theo mẫu chuẩn Thông tư 200": 80,
            "Thuyết minh sơ sài, gom chung nhiều khoản mục lớn vào 'Khác'": 45,
            "Thiếu thuyết minh các khoản mục trọng yếu và bên liên quan": 20
        },
        "default": "Thuyết minh đầy đủ theo mẫu chuẩn Thông tư 200"
    },

    # C4: Môi trường Ngành & Vị thế Cạnh tranh (Conditions & Market - 15%)
    "c4_market_position": {
        "group": "C4",
        "label": "Vị thế & Thị phần Doanh nghiệp trong Ngành",
        "options": {
            "Top 3 doanh nghiệp đầu ngành, thương hiệu dẫn dắt thị trường": 100,
            "Top 10 thương hiệu có uy tín, thị phần đáng kể": 80,
            "Doanh nghiệp quy mô trung bình, thị phần ổn định": 60,
            "Doanh nghiệp quy mô nhỏ, thị phần phân tán dễ bị cạnh tranh": 35
        },
        "default": "Doanh nghiệp quy mô trung bình, thị phần ổn định"
    },
    "c4_entry_barriers": {
        "group": "C4",
        "label": "Rào cản Gia nhập Ngành (Barriers to Entry)",
        "options": {
            "Rất cao (Đòi hỏi vốn lớn, công nghệ độc quyền hoặc giấy phép cấp phép chặt chẽ)": 100,
            "Trung bình (Cần vốn đầu tư ban đầu đáng kể và mạng lưới phân phối)": 75,
            "Thấp (Ngành nghề kinh doanh tự do, đối thủ mới dễ dàng gia nhập)": 45
        },
        "default": "Trung bình (Cần vốn đầu tư ban đầu đáng kể và mạng lưới phân phối)"
    },
    "c4_cyclical_risk": {
        "group": "C4",
        "label": "Tính Nhạy cảm với Chu kỳ Kinh tế & Chính sách Vĩ mô",
        "options": {
            "Ngành hàng thiết yếu / Kháng chu kỳ (Hàng tiêu dùng thiết yếu, Dược phẩm, Tiện ích)": 95,
            "Ngành có độ nhạy cảm chu kỳ trung bình (Sản xuất công nghiệp, Vận tải)": 75,
            "Ngành có chu kỳ cao / Rất nhạy cảm với Lãi suất & BĐS (Bất động sản, Thép, Xây dựng)": 45
        },
        "default": "Ngành có độ nhạy cảm chu kỳ trung bình (Sản xuất công nghiệp, Vận tải)"
    },

    # C5: Quan hệ Chuỗi Cung ứng & Hệ sinh thái (Ecosystem & Supply Chain - 20%)
    "c5_customer_concentration": {
        "group": "C5",
        "label": "Mức độ Tập trung Khách hàng Đầu ra (Top 3 Khách hàng)",
        "options": {
            "Đa dạng hóa tốt (Top 3 khách hàng chiếm < 25% Tổng doanh thu)": 100,
            "Tập trung vừa phải (Top 3 khách hàng chiếm từ 25% đến 50% Doanh thu)": 75,
            "Phụ thuộc lớn (Top 3 khách hàng chiếm từ 50% đến 75% Doanh thu)": 45,
            "Rủi ro sống còn (1 khách hàng chiếm > 50% hoặc Top 3 chiếm > 75% Doanh thu)": 20
        },
        "default": "Đa dạng hóa tốt (Top 3 khách hàng chiếm < 25% Tổng doanh thu)"
    },
    "c5_supplier_concentration": {
        "group": "C5",
        "label": "Mức độ Tập trung Nhà cung cấp Đầu vào (Top 3 Nhà cung cấp)",
        "options": {
            "Đa dạng hóa nguồn cung (Nhiều nhà cung cấp thay thế, Top 3 < 30% Chi phí mua hàng)": 100,
            "Có 2-3 đối tác chiến lược ổn định (Top 3 chiếm từ 30% đến 60%)": 75,
            "Phụ thuộc vào 1-2 nhà cung cấp độc quyền nguyên vật liệu chính (> 60%)": 40
        },
        "default": "Có 2-3 đối tác chiến lược ổn định (Top 3 chiếm từ 30% đến 60%)"
    },
    "c5_related_party_rpt": {
        "group": "C5",
        "label": "Giao dịch với Bên liên quan (RPT) trong Hệ sinh thái Tập đoàn",
        "options": {
            "Không có hoặc RPT < 5% Tổng tài sản (Minh bạch tuyệt đối)": 100,
            "RPT từ 5% đến 15% Tổng tài sản (Mua bán hàng hóa nội bộ thông thường)": 75,
            "RPT từ 15% đến 30% Tổng tài sản (Có ủy thác vốn, cho mượn vốn, đặt cọc nội bộ)": 45,
            "RPT > 30% Tổng tài sản hoặc dòng tiền lòng vòng nội bộ (Cảnh báo rút ruột/chuyển giá)": 15
        },
        "default": "RPT từ 5% đến 15% Tổng tài sản (Mua bán hàng hóa nội bộ thông thường)"
    },
    "c5_bargaining_power": {
        "group": "C5",
        "label": "Vị thế Đàm phán Thương lượng & Chuỗi Giá trị",
        "options": {
            "Vị thế áp đảo: Bán hàng thu tiền ngay / NCC chấp nhận cho công nợ dài ngày": 100,
            "Vị thế cân bằng: Chu kỳ thu tiền và trả tiền phù hợp thông lệ ngành": 75,
            "Vị thế yếu: Bị khách hàng chiếm dụng vốn kéo dài & Nhà cung cấp ép trả tiền ngay": 35
        },
        "default": "Vị thế cân bằng: Chu kỳ thu tiền và trả tiền phù hợp thông lệ ngành"
    }
}

def calculate_5c_scores(user_answers):
    """
    Tính điểm chi tiết 5 nhóm tiêu chí 5Cs và tổng điểm định tính (Thang điểm 0 - 100).
    """
    c_group_keys = {
        "C1": ["c1_mgmt_exp", "c1_cic_history", "c1_owner_commitment", "c1_legal_compliance"],
        "C2": ["c2_board_structure", "c2_internal_control", "c2_erp_tech", "c2_hr_stability"],
        "C3": ["c3_audit_firm", "c3_audit_opinion", "c3_tax_consistency", "c3_disclosure_quality"],
        "C4": ["c4_market_position", "c4_entry_barriers", "c4_cyclical_risk"],
        "C5": ["c5_customer_concentration", "c5_supplier_concentration", "c5_related_party_rpt", "c5_bargaining_power"]
    }
    
    group_scores = {}
    for group_code, keys in c_group_keys.items():
        scores = []
        for k in keys:
            selected_option = user_answers.get(k, DEFAULT_5C_CONFIG[k]["default"])
            score_val = DEFAULT_5C_CONFIG[k]["options"].get(selected_option, 70)
            scores.append(score_val)
        group_scores[group_code] = sum(scores) / len(scores) if scores else 70.0
        
    # Trọng số chuẩn mực: C1 (20%), C2 (20%), C3 (25%), C4 (15%), C5 (20%)
    total_qual_score = (
        0.20 * group_scores["C1"] +
        0.20 * group_scores["C2"] +
        0.25 * group_scores["C3"] +
        0.15 * group_scores["C4"] +
        0.20 * group_scores["C5"]
    )
    total_qual_score = round(total_qual_score, 2)
    
    radar_data = {
        "C1 - Lãnh đạo": group_scores["C1"],
        "C2 - Quản trị": group_scores["C2"],
        "C3 - BCTC & Thuế": group_scores["C3"],
        "C4 - Ngành & TT": group_scores["C4"],
        "C5 - Hệ sinh thái": group_scores["C5"]
    }
    
    c3_score = group_scores["C3"]
    c5_score = group_scores["C5"]
    
    bctc_trust_level = "🟢 Rất cao (Chuẩn mực)" if c3_score >= 85 else ("🔵 Đạt yêu cầu" if c3_score >= 65 else "🔴 RỦI RO (Cần đối chiếu Thuế)")
    supply_chain_risk = "🟢 An toàn (Đa dạng hóa)" if c5_score >= 80 else ("🟡 Trung bình (Cần theo dõi)" if c5_score >= 60 else "🔴 RỦI RO CAO (Phụ thuộc lớn)")
    
    return {
        "group_scores": group_scores,
        "total_qual_score": total_qual_score,
        "radar_data": radar_data,
        "bctc_trust_level": bctc_trust_level,
        "supply_chain_risk": supply_chain_risk
    }

def calculate_quant_ews_score(ews_year_data):
    """
    Tính điểm định lượng tổng hợp EWS (thang điểm 0 - 100) dựa trên 10 chỉ số tài chính.
    """
    if not ews_year_data:
        return 65.0
    
    sub_scores = []
    
    # 1. Altman Z'-Score (Kiệt quệ tài chính) - Trọng số 25%
    z_prime_data = ews_year_data.get("Altman_Z_Prime")
    if z_prime_data:
        z_val = z_prime_data.get("score", 2.0)
        if z_val >= 2.90:
            z_score = 100.0
        elif z_val >= 1.23:
            z_score = 50.0 + ((z_val - 1.23) / (2.90 - 1.23)) * 45.0
        else:
            z_score = max(10.0, (z_val / 1.23) * 45.0)
        sub_scores.append((z_score, 0.25))
        
    # 2. Dechow F-Score & Beneish M-Score (Thao túng BCTC) - Trọng số 25%
    f_data = ews_year_data.get("Dechow_F_Score")
    m_data = ews_year_data.get("Beneish_M_Score")
    manip_score = 80.0
    if f_data and m_data:
        f_val = f_data.get("score", 1.0)
        m_val = m_data.get("score", -2.5)
        if m_val > -1.78 and f_val > 1.85:
            manip_score = 15.0  # Báo động đỏ bóp méo BCTC
        elif m_val > -1.78 or f_val > 1.85:
            manip_score = 45.0
        elif m_val <= -2.22 and f_val <= 1.0:
            manip_score = 100.0
        else:
            manip_score = 75.0
        sub_scores.append((manip_score, 0.25))
        
    # 3. Thao túng hoạt động thực REM (Abnormal CFO, PROD, DISEXP) - Trọng số 20%
    cfo_data = ews_year_data.get("Abnormal_CFO")
    prod_data = ews_year_data.get("Abnormal_PROD")
    disexp_data = ews_year_data.get("Abnormal_DISEXP")
    if cfo_data and prod_data and disexp_data:
        cfo_v = cfo_data.get("score", 0.0)
        prod_v = prod_data.get("score", 0.0)
        disexp_v = disexp_data.get("score", 0.0)
        if cfo_v < -0.05 and prod_v > 0.05 and disexp_v < -0.03:
            rem_score = 20.0  # Báo động đỏ REM
        elif sum([cfo_v < -0.05, prod_v > 0.05, disexp_v < -0.03]) >= 1:
            rem_score = 60.0
        else:
            rem_score = 95.0
        sub_scores.append((rem_score, 0.20))
        
    # 4. Hạn chế tài chính & Tín dụng (SA, KZ, WW) - Trọng số 15%
    sa_data = ews_year_data.get("SA_Index")
    if sa_data:
        sa_st = sa_data.get("status", "success")
        sa_score = 90.0 if sa_st == "success" else 45.0
        sub_scores.append((sa_score, 0.15))
        
    # 5. Các mô hình kiệt quệ bổ sung (Springate, Zmijewski) - Trọng số 15%
    sp_data = ews_year_data.get("Springate")
    zm_data = ews_year_data.get("Zmijewski")
    extra_scores = []
    if sp_data:
        extra_scores.append(100.0 if sp_data.get("status") == "success" else 40.0)
    if zm_data:
        extra_scores.append(100.0 if zm_data.get("status") == "success" else 35.0)
    if extra_scores:
        sub_scores.append((sum(extra_scores) / len(extra_scores), 0.15))
        
    if not sub_scores:
        return 65.0
        
    total_weight = sum(w for _, w in sub_scores)
    quant_score = sum(s * w for s, w in sub_scores) / total_weight
    return round(float(quant_score), 2)

def calculate_hybrid_rating(quant_score, qual_score, quant_weight=0.60):
    """
    Tính điểm xếp hạng hỗn hợp (Hybrid Rating) kết hợp Định lượng BCTC EWS và Định tính 5Cs.
    """
    qual_weight = round(1.0 - quant_weight, 2)
    hybrid_score = round(quant_score * quant_weight + qual_score * qual_weight, 2)
    
    if hybrid_score >= 88.0:
        grade = "AAA"
        grade_name = "Hạng AAA - Cực kỳ An toàn (Doanh nghiệp Đầu ngành)"
        color = "#22543D"
        bg_color = "#C6F6D5"
        status = "success"
        ltv = "Tối đa 75% - 80% (Cấp hạn mức tín chấp hoặc ưu đãi lãi suất)"
        decision = "PHÊ DUYỆT TÍN DỤNG / CẤP HẠN MỨC CAO NHẤT"
        guidance = "Doanh nghiệp có sức khỏe tài chính xuất sắc, BCTC được kiểm toán uy tín Big 4, hệ sinh thái phân tán lành mạnh. Khuyến nghị duy trì và mở rộng quan hệ tín dụng."
    elif hybrid_score >= 80.0:
        grade = "AA"
        grade_name = "Hạng AA - Rất An toàn (Năng lực Tài chính & Quản trị Cao)"
        color = "#276749"
        bg_color = "#C6F6D5"
        status = "success"
        ltv = "Tối đa 70% - 75% (Tín chấp một phần theo doanh thu)"
        decision = "PHÊ DUYỆT TÍN DỤNG CHUẨN"
        guidance = "Hồ sơ tài chính và quản trị rất tốt. Đảm bảo theo dõi định kỳ BCTC quý và dòng tiền về tài khoản ngân hàng."
    elif hybrid_score >= 70.0:
        grade = "A"
        grade_name = "Hạng A - An toàn Chuẩn mực (Rủi ro Tín dụng Thấp)"
        color = "#2F855A"
        bg_color = "#D4EDDA"
        status = "success"
        ltv = "Tối đa 65% - 70% (Yêu cầu Tài sản Đảm bảo chuẩn)"
        decision = "PHÊ DUYỆT TÍN DỤNG CÓ ĐIỀU KIỆN CHUẨN"
        guidance = "Doanh nghiệp ổn định, đáp ứng đầy đủ tiêu chí thẩm định tín dụng. Yêu cầu tài sản bảo đảm là BĐS hoặc máy móc thiết bị có tính thanh khoản cao."
    elif hybrid_score >= 60.0:
        grade = "BBB"
        grade_name = "Hạng BBB - Trung bình Khá (Chấp nhận được nhưng Cần Kiểm soát)"
        color = "#9C4221"
        bg_color = "#FEEBC8"
        status = "warning"
        ltv = "Tối đa 55% - 60% (Bắt buộc kiểm soát dòng tiền doanh thu)"
        decision = "CHẤP THUẬN TÍN DỤNG CÓ KIỂM SOÁT DÒNG TIỀN CHẶT CHẼ"
        guidance = "Có một số điểm rủi ro nhẹ trong quản trị hoặc dòng tiền. Yêu cầu doanh nghiệp chuyển tối thiểu 70% doanh thu bán hàng về tài khoản tại ngân hàng để khấu trừ nợ."
    elif hybrid_score >= 50.0:
        grade = "BB"
        grade_name = "Hạng BB - Tiềm ẩn Rủi ro (Dưới Chuẩn Đầu tư)"
        color = "#C05621"
        bg_color = "#FEEBC8"
        status = "warning"
        ltv = "Tối đa 40% - 50% (Tài trợ từng món kèm hóa đơn VAT đầu vào)"
        decision = "CÂN NHẮC HẠN CHẾ / GIẢM HẠN MỨC"
        guidance = "Phát hiện dấu hiệu rủi ro về vốn lưu động, phụ thuộc chuỗi cung ứng hoặc BCTC chưa được kiểm toán chặt chẽ. Chỉ giải ngân từng lần khi có hợp đồng đầu ra và hóa đơn GTGT hợp lệ."
    elif hybrid_score >= 40.0:
        grade = "B"
        grade_name = "Hạng B - Rủi ro Cao (Cảnh báo Kiệt quệ / Bóp méo BCTC)"
        color = "#9B2C2C"
        bg_color = "#FED7D7"
        status = "error"
        ltv = "Tối đa 30% (Chỉ nhận Tài sản Đảm bảo là Tiền gửi / BĐS Trung tâm)"
        decision = "HẠN CHẾ TỐI ĐA / TĂNG CƯỜNG THU HỒI NỢ"
        guidance = "Rủi ro tín dụng rất lớn. Không cấp hạn mức mới. Tăng cường kiểm tra thực địa kho hàng và theo dõi sát sao khả năng trả nợ."
    else:
        grade = "CCC / D"
        grade_name = "Hạng CCC / D - Báo động Đỏ (Nguy cơ Vỡ nợ / Gian lận Nghiêm trọng)"
        color = "#742A2A"
        bg_color = "#FEB2B2"
        status = "error"
        ltv = "0% (KHÔNG CẤP TÍN DỤNG)"
        decision = "TỪ CHỐI CẤP TÍN DỤNG / THU HỒI NỢ KHẨN CẤP"
        guidance = "Mô hình EWS cảnh báo kiệt quệ tài chính hoặc thao túng BCTC nghiêm trọng kết hợp với điểm định tính yếu kém. Chuyển hồ sơ sang bộ phận Xử lý nợ đặc biệt."
        
    return {
        "hybrid_score": hybrid_score,
        "grade": grade,
        "grade_name": grade_name,
        "color": color,
        "bg_color": bg_color,
        "status": status,
        "ltv": ltv,
        "decision": decision,
        "guidance": guidance,
        "quant_weight": quant_weight,
        "qual_weight": qual_weight,
        "quant_score": quant_score,
        "qual_score": qual_score
    }

def render_5c_radar_chart(c_scores):
    """
    Vẽ biểu đồ Radar 5 trục thể hiện điểm thành phần 5Cs của Doanh nghiệp.
    """
    import matplotlib.pyplot as plt
    categories = list(c_scores.keys())
    values = [float(v) for v in c_scores.values()]
    
    # Khép kín vòng tròn
    values += values[:1]
    angles = np.linspace(0, 2 * np.pi, len(categories), endpoint=False).tolist()
    angles += angles[:1]
    
    fig, ax = plt.subplots(figsize=(5.5, 5.5), subplot_kw=dict(polar=True))
    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    
    # Vẽ trục và nhãn
    plt.xticks(angles[:-1], categories, color="#2D3748", size=9, weight="bold")
    ax.set_rlabel_position(30)
    plt.yticks([20, 40, 60, 80, 100], ["20", "40", "60", "80", "100"], color="#718096", size=7)
    plt.ylim(0, 100)
    
    # Vẽ đa giác dữ liệu của doanh nghiệp
    ax.plot(angles, values, color="#3182CE", linewidth=2.5, linestyle='solid', label="Điểm Doanh nghiệp")
    ax.fill(angles, values, color="#3182CE", alpha=0.25)
    
    # Vùng an toàn chuẩn mực (Benchmark 70 điểm)
    bench_values = [70] * (len(categories) + 1)
    ax.plot(angles, bench_values, color="#38A169", linewidth=1.5, linestyle='dashed', label="Ngưỡng Chuẩn (70đ)")
    
    ax.legend(loc='lower right', bbox_to_anchor=(1.15, -0.05), fontsize=8)
    plt.tight_layout()
    return fig

# -------------------------------------------------------------------------
# MODULE PHÂN TÍCH SAO KÊ DÒNG TIỀN NGÂN HÀNG (KHỐI 3 - HIGH-FREQUENCY CASHFLOW)
# -------------------------------------------------------------------------

def generate_mock_bank_statement_data(ticker="HSG", company_name="CTCP Tập đoàn Hoa Sen", annual_revenue=30000e9, annual_cogs=25000e9):
    """
    Tạo bộ dữ liệu sao kê ngân hàng mô phỏng 12 tháng sát với thực tế kinh doanh
    phục vụ việc kiểm soát sau giải ngân và phân tích tần suất cao.
    """
    import random
    monthly_rev = annual_revenue / 12.0 if annual_revenue > 0 else 2500e9 / 12.0
    monthly_cogs = annual_cogs / 12.0 if annual_cogs > 0 else 2000e9 / 12.0
    
    # Đối tác mẫu tùy theo doanh nghiệp
    if ticker in ["HSG", "HPG", "NKG", "TLH"]:
        in_partners = [
            ("Chi nhánh Đại lý Tôn Thép Miền Bắc", 0.28, "Thu tiền bán tôn mạ kẽm theo HĐKT-2024/01"),
            ("Công ty CP Xây dựng Coteccons", 0.22, "Thanh toán đợt 3 cung cấp thép công trình"),
            ("Công ty CP Xây dựng Ricons", 0.18, "Thanh toán tiền mua tôn màu nhà xưởng"),
            ("Đại lý Sắt thép Miền Trung Vạn Lợi", 0.15, "Tiền hàng tôn cuộn tháng"),
            ("Khách hàng Xuất khẩu ASEAN (USD quy đổi)", 0.12, "TT tiền hàng xuất khẩu LC-9981"),
            ("Khách hàng vãng lai", 0.05, "Tiền bán hàng lẻ thu trực tiếp")
        ]
        out_partners = [
            ("Công ty TNHH Gang thép Hưng Nghiệp Formosa Hà Tĩnh", 0.45, "Thanh toán tiền mua thép cuộn cán nóng HRC"),
            ("Tập đoàn Công nghiệp Than Khoáng sản", 0.10, "Tiền mua nguyên nhiên liệu sản xuất"),
            ("Tổng Công ty Điện lực Miền Nam (EVN)", 0.06, "Thanh toán tiền điện sản xuất nhà máy"),
            ("Kho bạc Nhà nước tỉnh Bình Dương", 0.08, "Nộp thuế GTGT & Thuế TNDN tạm tính"),
            ("Chi trả lương CBNV qua Vietcombank", 0.09, "Chi lương tháng và bảo hiểm"),
            ("Ngân hàng TMCP Ngoại thương (Vietcombank)", 0.12, "Trả nợ gốc & lãi vay vốn lưu động đến hạn"),
            ("Ngân hàng TMCP Đầu tư & Phát triển (BIDV)", 0.07, "Trả lãi vay hạn mức tín dụng"),
            ("Tạm ứng cá nhân Ban Giám đốc", 0.02, "Tạm ứng công tác và đối ngoại cá nhân"),
            ("Đặt cọc mua đất nền dự án", 0.01, "Đặt cọc mua BĐS ngoài ngành (Cảnh báo)")
        ]
    elif ticker in ["ANV", "VHC", "FMC", "MPC"]:
        in_partners = [
            ("European Seafood Import Corp (Rotterdam)", 0.32, "Thanh toán tiền xuất khẩu cá tra fillet LC-EU204"),
            ("US Seafood Distribution LLC", 0.25, "Thanh toán lô hàng thủy sản đông lạnh"),
            ("Chuỗi Bách Hóa Xanh (MWG)", 0.18, "Thanh toán tiền cá phi lê tiêu thụ nội địa"),
            ("Hệ thống Siêu thị Co.opmart", 0.15, "Tiền hàng thủy sản đóng gói"),
            ("Đại lý Thủy sản Miền Tây", 0.10, "Thanh toán tiền phụ phẩm bột cá")
        ]
        out_partners = [
            ("Hộ nuôi cá tra Vùng nguyên liệu Cù Lao Cỏ", 0.40, "Thanh toán tiền mua cá tra nguyên liệu"),
            ("Công ty CP Thức ăn Thủy sản Việt Hoa", 0.20, "Tiền mua cám thức ăn thủy sản"),
            ("Công ty Bao bì Thủy sản Cần Thơ", 0.08, "Tiền mua bao bì carton và màng co"),
            ("Điện lực An Giang (EVN)", 0.07, "Tiền điện kho lạnh và nhà máy chế biến"),
            ("Kho bạc Nhà nước tỉnh An Giang", 0.06, "Nộp thuế GTGT và thuế TNDN"),
            ("Chi trả lương công nhân nhà máy", 0.09, "Chi lương công nhân chế biến"),
            ("Ngân hàng Agribank Chi nhánh An Giang", 0.08, "Trả gốc và lãi vay hạn mức thu mua nguyên liệu"),
            ("Chuyển tiền đầu tư chứng khoán cá nhân", 0.02, "Ủy thác đầu tư tài chính ngoài ngành (Cảnh báo)")
        ]
    else:
        in_partners = [
            ("Công ty CP Bán lẻ & Phân phối Toàn Cầu", 0.35, "Thanh toán tiền hàng theo HĐKT số 102"),
            ("Công ty TNHH Thương mại Dịch vụ Nam Long", 0.25, "Thanh toán công nợ mua hàng hóa"),
            ("Chuỗi Siêu thị VinMart / WinCommerce", 0.20, "Tiền hàng tiêu dùng tháng"),
            ("Khách hàng đại lý các tỉnh", 0.15, "Tiền mua hàng sỉ chuyển khoản"),
            ("Khách hàng mua lẻ chuyển khoản", 0.05, "Tiền bán lẻ trực tiếp")
        ]
        out_partners = [
            ("Công ty Cung ứng Nguyên vật liệu Quốc tế", 0.42, "Thanh toán tiền hàng nhập khẩu nguyên liệu"),
            ("Công ty CP Vận tải & Logistics Miền Đông", 0.10, "Thanh toán cước vận chuyển giao hàng"),
            ("Chi cục Thuế Quản lý doanh nghiệp", 0.08, "Nộp thuế GTGT và thuế TNDN"),
            ("Chi trả lương nhân viên toàn công ty", 0.12, "Chi trả lương và phụ cấp CBNV"),
            ("Điện lực & Nước sạch", 0.05, "Chi phí vận hành văn phòng và kho bãi"),
            ("Ngân hàng Vietcombank", 0.15, "Thanh toán gốc và lãi vay định kỳ"),
            ("Rút tiền mặt Séc cá nhân", 0.05, "Rút séc tiền mặt chi tiêu không hóa đơn (Cảnh báo)")
        ]

    records = []
    base_balance = monthly_rev * 0.25
    running_balance = base_balance
    
    months = ["2024-01", "2024-02", "2024-03", "2024-04", "2024-05", "2024-06", 
              "2024-07", "2024-08", "2024-09", "2024-10", "2024-11", "2024-12"]
              
    txn_id_counter = 10001
    
    for m_idx, m_str in enumerate(months):
        # Biến thiên dòng tiền từng tháng (+- 10% tạo độ tự nhiên)
        monthly_factor = 1.0 + 0.15 * math.sin(m_idx * 0.6)
        m_inflow = monthly_rev * monthly_factor * 0.90  # 90% doanh thu về tài khoản này
        m_outflow = monthly_cogs * monthly_factor * 0.92
        
        # 1. Giao dịch Thu vào (Inflow)
        for p_name, weight, desc in in_partners:
            amount = m_inflow * weight * random.uniform(0.95, 1.05)
            day = random.randint(5, 26)
            date_str = f"{m_str}-{day:02d}"
            running_balance += amount
            records.append({
                "Ngày GD": date_str,
                "Tháng": m_str,
                "Mã GD": f"TXN-{txn_id_counter}",
                "Đối tác / TK Đối ứng": p_name,
                "Số tiền Ghi Có (Vào)": round(amount, 0),
                "Số tiền Ghi Nợ (Ra)": 0.0,
                "Số dư (VND)": round(running_balance, 0),
                "Nội dung giao dịch": desc,
                "Phân loại": "Thu tiền bán hàng (Đúng ngành nghề)",
                "Cờ rủi ro": "🟢 Chuẩn mực"
            })
            txn_id_counter += 1
            
        # 2. Giao dịch Chi ra (Outflow)
        for p_name, weight, desc in out_partners:
            amount = m_outflow * weight * random.uniform(0.95, 1.05)
            day = random.randint(10, 28)
            date_str = f"{m_str}-{day:02d}"
            running_balance -= amount
            
            # Phân loại cờ rủi ro cho các khoản chi bất thường
            if "Cảnh báo" in desc or "Cá nhân" in desc or "BĐS ngoài ngành" in desc or "Rút séc" in desc:
                flag = "🔴 Cảnh báo sai mục đích"
                cat = "Chi ngoài ngành / Rút vốn cá nhân"
            elif "Trả nợ gốc" in desc or "Trả lãi vay" in desc or "Ngân hàng" in desc:
                flag = "🟢 Trả nợ ngân hàng"
                cat = "Chi nghĩa vụ nợ ngân hàng"
            elif "Lương" in desc or "Thuế" in desc or "Điện lực" in desc:
                flag = "🟢 Chi phí hoạt động"
                cat = "Chi phí vận hành & Thuế"
            else:
                flag = "🟢 Mua hàng đúng ngành"
                cat = "Chi thanh toán NCC (Đúng ngành nghề)"
                
            records.append({
                "Ngày GD": date_str,
                "Tháng": m_str,
                "Mã GD": f"TXN-{txn_id_counter}",
                "Đối tác / TK Đối ứng": p_name,
                "Số tiền Ghi Có (Vào)": 0.0,
                "Số tiền Ghi Nợ (Ra)": round(amount, 0),
                "Số dư (VND)": round(running_balance, 0),
                "Nội dung giao dịch": desc,
                "Phân loại": cat,
                "Cờ rủi ro": flag
            })
            txn_id_counter += 1
            
    df_res = pd.DataFrame(records)
    df_res = df_res.sort_values(by="Ngày GD").reset_index(drop=True)
    return df_res

def parse_and_analyze_bank_statement(df_statement, annual_sales_target=None):
    """
    Phân tích toàn diện dữ liệu sao kê ngân hàng:
    - Tính đều đặn dòng tiền (CV_in)
    - Tỷ lệ đúng ngành nghề & kiểm soát mục đích sử dụng vốn
    - Tỷ lệ doanh thu về tài khoản (% Capture Ratio)
    - Top đối tác dòng tiền & Giao dịch cảnh báo
    """
    if df_statement is None or df_statement.empty:
        return None
        
    df = df_statement.copy()
    
    # Chuẩn hóa tên cột
    in_col = None
    out_col = None
    bal_col = None
    date_col = None
    desc_col = None
    partner_col = None
    
    for col in df.columns:
        col_l = col.lower()
        if "có" in col_l or "inflow" in col_l or "thu" in col_l or "credit" in col_l:
            in_col = col
        elif "nợ" in col_l or "outflow" in col_l or "chi" in col_l or "debit" in col_l:
            out_col = col
        elif "dư" in col_l or "balance" in col_l:
            bal_col = col
        elif "ngày" in col_l or "date" in col_l:
            date_col = col
        elif "nội dung" in col_l or "desc" in col_l or "diễn giải" in col_l:
            desc_col = col
        elif "đối tác" in col_l or "partner" in col_l or "tài khoản" in col_l:
            partner_col = col
            
    in_series = df[in_col].fillna(0).astype(float) if in_col else pd.Series([0]*len(df))
    out_series = df[out_col].fillna(0).astype(float) if out_col else pd.Series([0]*len(df))
    
    total_inflow = in_series.sum()
    total_outflow = out_series.sum()
    net_cashflow = total_inflow - total_outflow
    
    # 1. Phân tích theo tháng
    if date_col:
        df["_Month"] = pd.to_datetime(df[date_col], errors='coerce').dt.strftime('%Y-%m')
        monthly_grp = df.groupby("_Month").agg({
            in_col: "sum" if in_col else "count",
            out_col: "sum" if out_col else "count"
        }).reset_index()
        monthly_inflows = monthly_grp[in_col].values if in_col else np.array([total_inflow/12]*12)
    else:
        monthly_grp = pd.DataFrame()
        monthly_inflows = np.array([total_inflow/12]*12)
        
    # Tính hệ số biến động dòng tiền vào (CV_in = std / mean)
    mean_in = np.mean(monthly_inflows) if len(monthly_inflows) > 0 else 1.0
    std_in = np.std(monthly_inflows) if len(monthly_inflows) > 0 else 0.0
    cv_in = std_in / mean_in if mean_in > 0 else 1.0
    regularity_score = max(10.0, min(100.0, (1.0 - cv_in) * 100.0 + 30.0))
    
    if cv_in < 0.20:
        reg_status = "🟢 Rất đều đặn (Dòng tiền kinh doanh ổn định cao)"
    elif cv_in < 0.40:
        reg_status = "🔵 Đều đặn khá (Biến động theo chu kỳ nhẹ)"
    elif cv_in < 0.70:
        reg_status = "🟡 Biến động vừa phải (Có tháng trồi sụt)"
    else:
        reg_status = "🔴 Thất thường / Gián đoạn (Rủi ro thiếu hụt thanh khoản)"
        
    # 2. Phân loại mục đích giao dịch & Kiểm tra đúng ngành nghề
    flagged_txns = []
    normal_txns = []
    debt_service_outflow = 0.0
    operating_inflow = 0.0
    operating_outflow = 0.0
    
    for idx, row in df.iterrows():
        desc_text = str(row.get(desc_col, "")).lower()
        r_in = float(row.get(in_col, 0))
        r_out = float(row.get(out_col, 0))
        
        # Nhận diện giao dịch cảnh báo sai mục đích
        is_flagged = False
        warning_reason = ""
        
        if any(w in desc_text for w in ["bất động sản", "bđs", "mua đất", "đặt cọc đất", "ngoài ngành"]):
            is_flagged = True
            warning_reason = "⚠️ Chuyển tiền đầu tư BĐS ngoài ngành kinh doanh"
        elif any(w in desc_text for w in ["chứng khoán", "cổ phiếu", "tiền ảo", "crypto", "forex", "ủy thác"]):
            is_flagged = True
            warning_reason = "⚠️ Chuyển tiền đầu tư tài chính rủi ro cao"
        elif any(w in desc_text for w in ["tạm ứng cá nhân", "chuyển tiền giám đốc", "cho mượn cá nhân", "rút séc"]):
            is_flagged = True
            warning_reason = "⚠️ Rút vốn cá nhân / Tạm ứng lãnh đạo không hóa đơn"
            
        if is_flagged:
            flagged_txns.append({
                "Ngày": row.get(date_col, "-"),
                "Đối tác": row.get(partner_col, "-"),
                "Số tiền Chi (VND)": r_out,
                "Nội dung": row.get(desc_col, "-"),
                "Cảnh báo": warning_reason
            })
            
        if any(w in desc_text for w in ["trả nợ gốc", "trả lãi", "ngân hàng", "vay vốn"]):
            debt_service_outflow += r_out
        elif r_out > 0:
            operating_outflow += r_out
            
        if r_in > 0:
            operating_inflow += r_in
            
    flagged_amount = sum(t["Số tiền Chi (VND)"] for t in flagged_txns)
    compliance_ratio = (total_outflow - flagged_amount) / total_outflow if total_outflow > 0 else 1.0
    
    # 3. Tỷ lệ doanh thu về tài khoản (% Capture Ratio)
    capture_ratio = None
    if annual_sales_target and annual_sales_target > 0:
        capture_ratio = total_inflow / annual_sales_target
        
    # 4. Top đối tác dòng tiền
    top_in_partners = []
    top_out_partners = []
    if partner_col:
        grp_in = df[df[in_col] > 0].groupby(partner_col)[in_col].sum().sort_values(ascending=False).head(5)
        for p, amt in grp_in.items():
            top_in_partners.append({"Đối tác nộp tiền": p, "Doanh số vào (VND)": amt, "Tỷ trọng": amt/total_inflow if total_inflow>0 else 0})
            
        grp_out = df[df[out_col] > 0].groupby(partner_col)[out_col].sum().sort_values(ascending=False).head(5)
        for p, amt in grp_out.items():
            top_out_partners.append({"Đối tác nhận tiền": p, "Doanh số chi (VND)": amt, "Tỷ trọng": amt/total_outflow if total_outflow>0 else 0})

    # 5. Hệ số DSCR dòng tiền ngân hàng
    net_operating_cf = operating_inflow - operating_outflow
    dscr_bank = net_operating_cf / debt_service_outflow if debt_service_outflow > 0 else 2.5
    
    return {
        "total_inflow": total_inflow,
        "total_outflow": total_outflow,
        "net_cashflow": net_cashflow,
        "cv_in": cv_in,
        "regularity_score": regularity_score,
        "reg_status": reg_status,
        "compliance_ratio": compliance_ratio,
        "flagged_txns": flagged_txns,
        "flagged_amount": flagged_amount,
        "capture_ratio": capture_ratio,
        "top_in_partners": pd.DataFrame(top_in_partners),
        "top_out_partners": pd.DataFrame(top_out_partners),
        "monthly_grp": monthly_grp,
        "dscr_bank": dscr_bank,
        "debt_service_outflow": debt_service_outflow,
        "raw_df": df
    }



# Thiết lập tiêu đề trang và cấu hình giao diện
st.set_page_config(
    page_title="FinTrust - Đánh giá Rủi ro BCTC (EWS)",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Thêm CSS tùy chỉnh để giao diện đẹp, mang tính thẩm mỹ cao (Sleek Dark UI accents & Glassmorphism)
st.markdown("""
<style>
    .reportview-container {
        background: #f8f9fa;
    }
    .metric-card {
        background-color: white;
        border-radius: 12px;
        padding: 22px;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.05);
        border-top: 4px solid #2d3748;
        margin-bottom: 20px;
        transition: transform 0.2s;
    }
    .metric-card:hover {
        transform: translateY(-2px);
    }
    .metric-red {
        border-top-color: #e53e3e;
        background-color: #fff5f5;
    }
    .metric-yellow {
        border-top-color: #dd6b20;
        background-color: #fffaf0;
    }
    .metric-green {
        border-top-color: #38a169;
        background-color: #f0fff4;
    }
    .badge {
        display: inline-block;
        padding: 4px 8px;
        border-radius: 6px;
        font-weight: bold;
        font-size: 0.85em;
    }
    .badge-red { background-color: #fed7d7; color: #9b2c2c; }
    .badge-yellow { background-color: #feebc8; color: #9c4221; }
    .badge-green { background-color: #c6f6d5; color: #22543d; }
</style>
""", unsafe_allow_html=True)

# -------------------------------------------------------------------------
# BẢN ĐỒ MÃ SỐ CHỈ TIÊU BCTC THEO THÔNG TƯ 200/2014/TT-BTC
# -------------------------------------------------------------------------
CODE_MAP = {
    # Bảng Cân đối Kế toán (CDKT)
    "Current_Assets": "100",        # Tài sản ngắn hạn
    "Cash_Equivalents": "110",      # Tiền và tương đương tiền
    "Current_Receivables": "130",   # Các khoản phải thu ngắn hạn
    "Accounts_Receivable": "131",   # Phải thu ngắn hạn của khách hàng
    "Inventories": "140",          # Hàng tồn kho
    "Fixed_Assets": "220",         # Tài sản cố định (Giá trị ròng)
    "Tangible_PPE_Cost": "222",     # Nguyên giá TSCĐ hữu hình (Mã 222 theo TT 200)
    "Total_Assets": "270",         # Tổng cộng tài sản
    "Total_Liabilities": "300",    # Nợ phải trả
    "Current_Liabilities": "310",   # Nợ ngắn hạn
    "Accounts_Payable": "311",     # Phải trả người bán ngắn hạn
    "Short_Term_Borrowings": "320",# Vay và nợ thuê tài chính ngắn hạn
    "Equity": "400",               # Vốn chủ sở hữu
    "Retained_Earnings": "421",    # Lợi nhuận sau thuế chưa phân phối
    
    # Báo cáo Kết quả Kinh doanh (KQKD)
    "Net_Sales": "10",             # Doanh thu thuần về bán hàng & cung cấp dịch vụ
    "COGS": "11",                  # Giá vốn hàng bán
    "Gross_Profit": "20",          # Lợi nhuận gộp
    "Interest_Expense": "23",      # Chi phí lãi vay
    "Selling_Expense": "25",       # Chi phí bán hàng
    "GA_Expense": "26",            # Chi phí quản lý doanh nghiệp
    "EBT": "50",                   # Tổng lợi nhuận kế toán trước thuế
    "Net_Income": "60",            # Lợi nhuận sau thuế thu nhập doanh nghiệp
    
    # Báo cáo Lưu chuyển Tiền tệ (LCTT)
    "OCF": "20"                    # Lưu chuyển tiền thuần từ hoạt động kinh doanh (Mã 20)
}

# Tên tiếng Việt của các biến số phục vụ hiển thị
VAR_NAMES_VN = {
    "Current_Assets": "Tài sản ngắn hạn (100)",
    "Cash_Equivalents": "Tiền và tương đương tiền (110)",
    "Current_Receivables": "Các khoản phải thu ngắn hạn (130)",
    "Accounts_Receivable": "Phải thu ngắn hạn của KH (131)",
    "Inventories": "Hàng tồn kho (140)",
    "Fixed_Assets": "Tài sản cố định ròng (220)",
    "Tangible_PPE_Cost": "Nguyên giá TSCĐ hữu hình (222)",
    "Total_Assets": "Tổng cộng tài sản (270)",
    "Total_Liabilities": "Nợ phải trả (300)",
    "Current_Liabilities": "Nợ ngắn hạn (310)",
    "Accounts_Payable": "Phải trả người bán ngắn hạn (311)",
    "Short_Term_Borrowings": "Vay & nợ thuê TC ngắn hạn (320)",
    "Equity": "Vốn chủ sở hữu (400)",
    "Retained_Earnings": "LNST chưa phân phối (421)",
    "Net_Sales": "Doanh thu thuần (10)",
    "COGS": "Giá vốn hàng bán (11)",
    "Gross_Profit": "Lợi nhuận gộp (20)",
    "Interest_Expense": "Chi phí lãi vay (23)",
    "Selling_Expense": "Chi phí bán hàng (25)",
    "GA_Expense": "Chi phí QLDN (26)",
    "EBT": "Lợi nhuận trước thuế (50)",
    "Net_Income": "Lợi nhuận sau thuế (60)",
    "OCF": "Dòng tiền từ HĐKD (20 LCTT)"
}

# -------------------------------------------------------------------------
# CẤU HÌNH MÃ CHỨNG KHOÁN VÀ PHỤC HỒI DẤU TIẾNG VIỆT TÊN CÔNG TY
# -------------------------------------------------------------------------
import unicodedata

TICKER_NAME_MAP = {
    "HSG": "Công ty Cổ phần Tập đoàn Hoa Sen",
    "HPG": "Công ty Cổ phần Tập đoàn Hòa Phát",
    "VIX": "Công ty Cổ phần Chứng khoán VIX",
    "VCB": "Ngân hàng TMCP Ngoại thương Việt Nam",
    "TCB": "Ngân hàng TMCP Kỹ thương Việt Nam",
    "MBB": "Ngân hàng TMCP Quân đội",
    "FPT": "Công ty Cổ phần FPT",
    "VIC": "Tập đoàn Vingroup - Công ty CP",
    "VNM": "Công ty Cổ phần Sữa Việt Nam",
    "MSN": "Tập đoàn Masan",
    "ACB": "Ngân hàng TMCP Á Châu",
    "STB": "Ngân hàng TMCP Sài Gòn Thương Tín",
    "VPB": "Ngân hàng TMCP Việt Nam Thịnh Vượng",
    "BID": "Ngân hàng TMCP Đầu tư và Phát triển Việt Nam",
    "CTG": "Ngân hàng TMCP Công thương Việt Nam",
    "MWG": "Công ty Cổ phần Đầu tư Thế giới Di động",
    "GAS": "Tổng Công ty Khí Việt Nam - Công ty Cổ phần",
    "PLX": "Tập đoàn Xăng dầu Việt Nam",
    "POW": "Tổng Công ty Điện lực Dầu khí Việt Nam - Công ty Cổ phần",
    "VRE": "Công ty Cổ phần Vincom Retail",
    "VHM": "Công ty Cổ phần Vinhomes",
    "DGC": "Công ty Cổ phần Tập đoàn Hóa chất Đức Giang",
    "DXG": "Công ty Cổ phần Tập đoàn Đất Xanh",
    "KDH": "Công ty Cổ phần Đầu tư và Kinh doanh Nhà Khang Điền",
    "NLG": "Công ty Cổ phần Đầu tư Nam Long",
    "PDR": "Công ty Cổ phần Phát triển Bất động sản Phát Đạt",
    "DIG": "Tổng Công ty Cổ phần Đầu tư Phát triển Xây dựng",
    "GEX": "Công ty Cổ phần Tập đoàn GELEX",
    "KBC": "Tổng Công ty Phát triển Đô thị Kinh Bắc - Công ty Cổ phần",
    "VCG": "Tổng Công ty Cổ phần Xuất nhập khẩu và Xây dựng Việt Nam",
    "REE": "Công ty Cổ phần Cơ Điện Lạnh",
    "HAG": "Công ty Cổ phần Hoàng Anh Gia Lai",
    "SBT": "Công ty Cổ phần Thành Thành Công - Biên Hòa",
    "DBC": "Công ty Cổ phần Tập đoàn Dabaco Việt Nam",
    "VHC": "Công ty Cổ phần Vĩnh Hoàn",
    "ANV": "Công ty Cổ phần Nam Việt",
    "PVT": "Tổng Công ty Cổ phần Vận tải Dầu khí",
    "PVS": "Tổng Công ty Cổ phần Dịch vụ Kỹ thuật Dầu khí Việt Nam",
    "PVD": "Tổng Công ty Cổ phần Khoan và Dịch vụ Khoan Dầu khí",
    "BSR": "Công ty Cổ phần Lọc hóa dầu Bình Sơn",
    "PC1": "Công ty Cổ phần Tập đoàn PC1",
    "HDG": "Công ty Cổ phần Tập đoàn Hà Đô",
    "BCG": "Công ty Cổ phần Tập đoàn Bamboo Capital",
    "BIO": "Công ty Cổ phần Dược - Trang thiết bị Y tế Bình Định",
    "AGX": "Công ty Cổ phần Thực phẩm Nông sản Xuất khẩu Sài Gòn",
    "BBH": "Công ty Cổ phần Bao bì Hoàng Thạch",
    "BCV": "Công ty Cổ phần Vincom Bình Chánh",
    "ALV": "Công ty Cổ phần Xây dựng ALVICO",
    "ANV": "Công ty Cổ phần Nam Việt",
}

COMPANY_ACCENT_REPLACEMENTS = {
    r'\bCONG\s+TY\b': 'Công ty',
    r'\bCO\s+PHAN\b': 'Cổ phần',
    r'\bTAP\s+DOAN\b': 'Tập đoàn',
    r'\bTNHH\b': 'TNHH',
    r'\bMOT\s+THANH\s+VIEN\b': 'Một thành viên',
    r'\bTHUONG\s+MAI\b': 'Thương mại',
    r'\bDICH\s+VU\b': 'Dịch vụ',
    r'\bSAN\s+XUAT\b': 'Sản xuất',
    r'\bXAY\s+DUNG\b': 'Xây dựng',
    r'\bDAU\s+TU\b': 'Đầu tư',
    r'\bPHAT\s+TRIEN\b': 'Phát triển',
    r'\bVIET\s+NAM\b': 'Việt Nam',
    r'\bQUOC\s+TE\b': 'Quốc tế',
    r'\bXUAT\s+NHAP\s+KHAU\b': 'Xuất Nhập khẩu',
    r'\bCONG\s+NGHIEP\b': 'Công nghiệp',
    r'\bNONG\s+NGHIEP\b': 'Nông nghiệp',
    r'\bGIAO\s+THONG\b': 'Giao thông',
    r'\bVAN\s+TAI\b': 'Vận tải',
    r'\bDU\s+LICH\b': 'Du lịch',
    r'\bDO\s+THI\b': 'Đô thị',
    r'\bMOI\s+TRUONG\b': 'Môi trường',
    r'\bDUOC\s+PHAM\b': 'Dược phẩm',
    r'\bY\s+TE\b': 'Y tế',
    r'\bGIAO\s+DUC\b': 'Giáo dục',
    r'\bTRUYEN\s+THONG\b': 'Truyền thông',
    r'\bQUANG\s+CAO\b': 'Quảng cáo',
    r'\bKHOANG\s+SAN\b': 'Khoáng sản',
    r'\bDAU\s+KHI\b': 'Dầu khí',
    r'\bDIEN\s+LUC\b': 'Điện lực',
    r'\bHOA\s+CHAT\b': 'Hóa chất',
    r'\bDET\s+MAY\b': 'Dệt may',
    r'\bDA\s+GIAY\b': 'Da giày',
    r'\bTHUC\s+PHAM\b': 'Thực phẩm',
    r'\bNUOC\s+SACH\b': 'Nước sạch',
    r'\bHA\s+TANG\b': 'Hạ tầng',
    r'\bTAI\s+CHINH\b': 'Tài chính',
    r'\bBAO\s+HIEM\b': 'Bảo hiểm',
    r'\bCHUNG\s+KHOAN\b': 'Chứng khoán',
    r'\bCONG\s+NGHE\b': 'Công nghệ',
    r'\bVIEN\s+THONG\b': 'Viễn thông',
    
    # Proper Names
    r'\bALVICO\b': 'ALVICO',
    r'\bHOA\s+SEN\b': 'Hoa Sen',
    r'\bHOA\s+PHAT\b': 'Hòa Phát',
    r'\bCHUNG\s+KHOAN\s+VIX\b': 'Chứng khoán VIX',
    r'\bVIX\b': 'VIX',
    r'\bVIET\s+COMBANK\b': 'Vietcombank',
    r'\bNGOAI\s+THUONG\b': 'Ngoại thương',
    r'\bKY\s+THUONG\b': 'Kỹ thương',
    r'\bQUAN\s+DOI\b': 'Quân đội',
    r'\bSUA\b': 'Sữa',
    r'\bBINH\s+MINH\b': 'Bình Minh',
    r'\bTIEN\s+PHONG\b': 'Tiền Phong',
    r'\bSAO\s+MAI\b': 'Sao Mai',
    r'\bDAT\s+XANH\b': 'Đất Xanh',
    r'\bKHANG\s+DIEN\b': 'Khang Điền',
    r'\bNAM\s+LONG\b': 'Nam Long',
    r'\bGIA\s+LAI\b': 'Gia Lai',
    r'\bAN\s+GIANG\b': 'An Giang',
    r'\bDONG\s+NAI\b': 'Đồng Nai',
    r'\bBINH\s+DUONG\b': 'Bình Dương',
    r'\bLONG\s+AN\b': 'Long An',
    r'\bCAN\s+THO\b': 'Cần Thơ',
    r'\bHAI\s+PHONG\b': 'Hải Phòng',
    r'\bQUANG\s+NINH\b': 'Quảng Ninh',
    r'\bBAC\s+NINH\b': 'Bắc Ninh',
    r'\bTHAI\s+NGUYEN\b': 'Thái Nguyên',
    r'\bTHANH\s+HOA\b': 'Thanh Hóa',
    r'\bNGHE\s+AN\b': 'Nghệ An',
    r'\bDA\s+NANG\b': 'Đà Nẵng',
    r'\bKHANH\s+HOA\b': 'Khánh Hòa',
    r'\bLAM\s+DONG\b': 'Lâm Đồng',
    r'\bDONG\s+THAP\b': 'Đồng Tháp',
    r'\bKIEN\s+GIANG\b': 'Kiên Giang',
    r'\bCA\s+MAU\b': 'Cà Mau',
    r'\bBA\s+RIA\b': 'Bà Rịa',
    r'\bVUNG\s+TAU\b': 'Vũng Tàu',
    r'\bHA\s+NOI\b': 'Hà Nội',
    r'\bSAI\s+GON\b': 'Sài Gòn',
    r'\bTP\s+HO\s+CHI\s+MINH\b': 'TP. Hồ Chí Minh',
    r'\bHO\s+CHI\s+MINH\b': 'Hồ Chí Minh',
}

def clean_company_name(name, ticker):
    if ticker in TICKER_NAME_MAP:
        return TICKER_NAME_MAP[ticker]
    if not name or name == "N/A":
        return name
        
    name_clean = name.strip()
    # Loại bỏ ký tự nhiễu OCR ở đầu và cuối (ví dụ = ] | [ ~ ¬ * - _ / \ : ;)
    name_clean = re.sub(r'^[=\]\[|\~¬\*\-_\/\\:;0-9\s]+', '', name_clean).strip()
    name_clean = re.sub(r'[=\]\[|\~¬\*\-_\/\\:;0-9\s]+$', '', name_clean).strip()
    
    # Nếu có tiền tố công ty, lấy từ cụm từ đó
    match_ct = re.search(r'\b(CONG\s+TY|CÔNG\s+TY|TAP\s+DOAN|TẬP\s+ĐOÀN)\b.*', name_clean, re.IGNORECASE)
    if match_ct:
        name_clean = match_ct.group(0).strip()
        
    name_upper = name_clean.upper()
    
    # Apply word-by-word replacements to restore accents
    for pattern, replacement in COMPANY_ACCENT_REPLACEMENTS.items():
        name_upper = re.sub(pattern, replacement, name_upper, flags=re.IGNORECASE)
        
    # Formatting to keep acronyms and fix capitalization
    words = name_upper.split()
    formatted_words = []
    for w in words:
        w_upper = w.upper()
        if w_upper in ["TNHH", "CP", "JSCO", "VIX", "FPT", "HSG", "HPG", "VCB", "TCB", "MBB", "VIC", "VNM", "MSN", "ACB", "STB", "VPB", "BID", "CTG", "ALV", "ALVICO"]:
            formatted_words.append(w_upper)
        elif w_upper.startswith("TP.") or w_upper == "TP":
            formatted_words.append(w)
        else:
            formatted_words.append(w[0].upper() + w[1:] if len(w) > 0 else w)
            
    return " ".join(formatted_words)

def strip_accents(text):
    text = text.lower().replace('đ', 'd')
    return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')

def clean_bctc_line(line):
    """Làm sạch và nối các ký tự số bị phân tách lỗi do font hoặc OCR."""
    if not line:
        return ""
    # 1. Nối dấu ngoặc đơn âm: '( 1 575 428 453 )' -> '(1575428453)'
    line = re.sub(r'\(\s*([0-9\.\,\s]+)\s*\)', lambda m: '(' + re.sub(r'\s+', '', m.group(1)) + ')', line)
    # 2. Nối nhóm 3 chữ số cách nhau bằng space: '52 617 900 827' -> '52617900827'
    line = re.sub(r'\b(\d{1,3}(?:\s+\d{3}){2,})\b', lambda m: re.sub(r'\s+', '', m.group(1)), line)
    # 3. Loại bỏ phương trình kế toán trong ngoặc đơn để tránh nhầm mã số: (270 = 100 + 200) -> ''
    line = re.sub(r'\(\s*\d+\s*[=\+\-\*\/][^\)]*\)', '', line)
    # 4. Chỉ nối nếu là 1 chữ số đứng trước 1 chữ số + dấu chấm nghìn (ví dụ '5 2.617.900...' -> '52.617.900...'):
    line = re.sub(r'\b([1-9])\s+([0-9]\.\d{3}(?:\.\d{3})+)\b', r'\1\2', line)
    return line

def detect_statement_type(text):
    """
    Nhận diện loại BCTC của một trang:
    - CDKT: Bảng Cân đối Kế toán (Mẫu B 01 - DN / B 01a - CTCK)
    - KQKD: Báo cáo Kết quả Hoạt động Kinh doanh (Mẫu B 02 - DN / B 02a - CTCK)
    - LCTT: Báo cáo Lưu chuyển Tiền tệ (Mẫu B 03 - DN / B 03a - CTCK)
    - None: Thuyết minh BCTC (Mẫu B 09 - DN), Báo cáo Kiểm toán độc lập, hoặc trang bìa
    """
    if not text or not text.strip():
        return None
        
    clean_text = strip_accents(text).lower()
    clean_norm = re.sub(r'[^a-z0-9\s]', ' ', clean_text)
    clean_norm = re.sub(r'\s+', ' ', clean_norm)
    top_text = clean_norm[:650]
    
    # 1. Loại bỏ các trang Báo cáo Ban Giám đốc / Báo cáo Kiểm toán độc lập nếu chỉ là báo cáo tường thuật
    if any(k in top_text for k in ["ban tong giam doc", "ban giam doc", "kiem toan doc lap", "y kien cua kiem toan"]):
        if not any(m in top_text for m in ["mau b 01", "mau b 02", "mau b 03", "mau so b 01", "mau so b 02", "mau so b 03", "b 01 dn", "b 02 dn", "b 03 dn", "b01 dn", "b02 dn", "b03 dn"]):
            return None
            
    # 2. Loại bỏ các trang thuyết minh (B09)
    if "b 09" in top_text or "b09" in top_text or "thuyet minh bao cao tai chinh" in top_text or "ban thuyet minh" in top_text:
        return None
        
    # 3. Nhận diện LCTT (B03)
    if any(k in top_text for k in ["b 03", "b03", "luu chuyen tien te", "luu chuyen tien", "luu chuyen tren te", "luu chuyen tu hoat dong"]):
        return "LCTT"
        
    # 4. Nhận diện KQKD (B02)
    if any(k in top_text for k in ["b 02", "b02", "ket qua hoat dong kinh doanh", "ket qua kinh doanh"]):
        return "KQKD"
        
    # 5. Nhận diện CDKT (B01) - Bao gồm cả trang 1 (Tài sản) và trang 2 (Nguồn vốn)
    if any(k in top_text for k in ["b 01", "b01", "can doi ke toan", "bang can doi", "nguon von", "no phai tra va von chu so huu", "tong cong nguon von", "tai san ngan han"]):
        return "CDKT"
    if "tong cong tai san" in clean_norm or "no phai tra" in clean_norm and "von chu so huu" in clean_norm:
        return "CDKT"
        
    return None

# Cấu hình từ khóa không dấu, không khoảng trắng (space-free) để chống lỗi OCR dính chữ / sai dấu
KEYWORDS_CONFIG_SF = {
    "Current_Assets": {
        "pos": [["taisannganhan"], ["tatsannganhan"], ["talsannganhan"], ["tsnganhan"], ["taisanngan"]],
        "neg": ["khac", "duphong", "chiphi", "ngoai"]
    },
    "Cash_Equivalents": {
        "pos": [["tien", "tuongduong"], ["tien", "twongduong"], ["tienvacackhoantuongduongtien"], ["tiencackhoantuongduong"]],
        "neg": ["cuoinam", "daunam"]
    },
    "Current_Receivables": {
        "pos": [["phaithunganhan"], ["phalthunganhan"], ["cackhoanphaithunganhan"], ["phaithungan"]],
        "neg": ["khachhang", "duphong", "khac"]
    },
    "Accounts_Receivable": {
        "pos": [["phaithu", "khachhang"], ["phaithucuakhachhang"], ["phaithucuakhach"]],
        "neg": ["duphong", "khac", "daihan"]
    },
    "Inventories": {
        "pos": [["hangtonkho"], ["hangton"]],
        "neg": ["duphong", "giamgia"]
    },
    "Fixed_Assets": {
        "pos": [["taisancodinh"], ["taisincedinh"], ["taisancedinh"], ["tscodinh"], ["taisancodin"]],
        "neg": ["nguyengia", "haomon", "vohinh", "huuhinh", "thuetaichinh"]
    },
    "Tangible_PPE_Cost": {
        "pos": [["nguyengia"], ["nguyengiatscd"], ["nguyengiatscdhuuhinh"]],
        "neg": ["vohinh", "thuetaichinh"]
    },
    "Total_Assets": {
        "pos": [["tongcongtaisan"], ["tongtaisan"], ["tongts"]],
        "neg": []
    },
    "Total_Liabilities": {
        "pos": [["nophaitra"], ["tongnophaitra"]],
        "neg": ["nganhan", "daihan"]
    },
    "Current_Liabilities": {
        "pos": [["nonganhan"], ["nonhan"]],
        "neg": []
    },
    "Accounts_Payable": {
        "pos": [["phaitra", "nguoiban"], ["phaitranguoiban"], ["phaitrangban"], ["phaitranguoibannganhan"]],
        "neg": ["daihan", "khac", "noibo"]
    },
    "Short_Term_Borrowings": {
        "pos": [["vay", "nganhan"], ["vayvanothuetaichinhnganhan"], ["vayvanotaichinhnganhan"], ["vayvanonganhan"], ["vaynganhan"]],
        "neg": ["daihan"]
    },
    "Equity": {
        "pos": [["vonchusohuu"], ["vonvacacquy"], ["nguonvonchusohuu"]],
        "neg": ["loinhuan"]
    },
    "Retained_Earnings": {
        "pos": [["loinhuansauthuechuaphanphoi"], ["loinhuanchuaphanphoi"], ["lnstchuaphanphoi"], ["lnstcpp"]],
        "neg": []
    },
    "Net_Sales": {
        "pos": [["doanhthuthuan"], ["doanhthuthuanvebanhang"], ["dtt"]],
        "neg": ["giamtru", "chuathuchien"]
    },
    "COGS": {
        "pos": [["giavon"], ["giaven"], ["giavonhangban"]],
        "neg": []
    },
    "Gross_Profit": {
        "pos": [["loinhuangop"], ["lngop"]],
        "neg": []
    },
    "Interest_Expense": {
        "pos": [["laivay"], ["chiphilaivay"], ["trongdo:chiphilaivay"]],
        "neg": []
    },
    "Selling_Expense": {
        "pos": [["chiphibanhang"], ["cpbanhang"]],
        "neg": ["khac", "quanly", "thuyetminh", "taichinh", "thue"]
    },
    "GA_Expense": {
        "pos": [["chiphiquanly"], ["cpquanly"], ["chiphiquanlydoanhnghiep"]],
        "neg": ["khac", "banhang", "taichinh"]
    },
    "EBT": {
        "pos": [["loinhuantruocthue"], ["loinhuanketoantruocthue"], ["lntruocthue"]],
        "neg": []
    },
    "Net_Income": {
        "pos": [["loinhuansauthue"], ["lnst"], ["loinhuansauthuetndn"]],
        "neg": ["chuaphanphoi"]
    },
    "OCF": {
        "pos": [["luuchuyentienthuan"], ["tienthuan", "kinhdoanh"], ["tienthuantrhoatdongkinhdoanh"]],
        "neg": []
    }
}

def match_line_to_var_sf(line_text, code_token, statement):
    var_to_statement = {
        "Current_Assets": "CDKT", "Cash_Equivalents": "CDKT", "Current_Receivables": "CDKT",
        "Accounts_Receivable": "CDKT", "Inventories": "CDKT", "Fixed_Assets": "CDKT",
        "Tangible_PPE_Cost": "CDKT", "Total_Assets": "CDKT", "Total_Liabilities": "CDKT",
        "Current_Liabilities": "CDKT", "Accounts_Payable": "CDKT", "Short_Term_Borrowings": "CDKT",
        "Equity": "CDKT", "Retained_Earnings": "CDKT",
        "Net_Sales": "KQKD", "COGS": "KQKD", "Gross_Profit": "KQKD", "Interest_Expense": "KQKD",
        "Selling_Expense": "KQKD", "GA_Expense": "KQKD", "EBT": "KQKD", "Net_Income": "KQKD",
        "OCF": "LCTT"
    }

    # 1. Ưu tiên tuyệt đối mã 421 cho Retained Earnings trong CDKT
    if code_token:
        clean_code = code_token.strip().replace(".", "").replace(",", "")
        if clean_code.startswith("421") and statement == "CDKT":
            return "Retained_Earnings"
            
    line_s = strip_accents(line_text).lower()
    line_sf = re.sub(r'\s+', '', line_s)
    
    def check_keyword_match_sf(var):
        cfg = KEYWORDS_CONFIG_SF.get(var)
        if not cfg:
            return False
        for neg in cfg["neg"]:
            if neg == "khac":
                # Tránh trùng với "khach"
                if re.search(r'khac(?!h)', line_sf):
                    return False
            else:
                if neg in line_sf:
                    return False
        for pos_set in cfg["pos"]:
            if all(pos_word in line_sf for pos_word in pos_set):
                return True
        return False

    matched_vars = []
    if code_token:
        clean_code = code_token.strip().replace(".", "").replace(",", "")
        for var, code in CODE_MAP.items():
            if code == clean_code:
                # Kiểm tra xem chỉ tiêu có thuộc đúng loại báo cáo hiện tại hay không
                if var_to_statement.get(var) == statement:
                    matched_vars.append(var)

    # Nếu mã khớp và từ khóa khớp -> Đánh giá độ tin cậy cao
    for var in matched_vars:
        if check_keyword_match_sf(var):
            return var
            
    # FALLBACK MÃ SỐ TIN CẬY: Chỉ fallback nếu dòng KHÔNG chứa từ khóa phủ định (negative keywords) của chỉ tiêu đó
    if len(matched_vars) == 1:
        var = matched_vars[0]
        cfg = KEYWORDS_CONFIG_SF.get(var)
        has_neg = False
        if cfg and cfg.get("neg"):
            for neg in cfg["neg"]:
                if neg == "khac":
                    if re.search(r'khac(?!h)', line_sf):
                        has_neg = True
                        break
                else:
                    if neg in line_sf:
                        has_neg = True
                        break
        if not has_neg:
            return var
            
    # Tự động sửa lỗi OCR nhận diện sai mã số chỉ tiêu bằng cách đối chiếu từ khóa
    for var in KEYWORDS_CONFIG_SF.keys():
        if var_to_statement.get(var) != statement:
            continue
        if check_keyword_match_sf(var):
            return var
            
    return None

def extract_numbers_from_tokens(tokens, code_token):
    numeric_vals = []
    for vt in tokens:
        cleaned_vt = vt.strip()
        if not cleaned_vt:
            continue
            
        # Nếu token là gạch ngang biểu diễn giá trị 0
        if cleaned_vt in ["-", "—", "–", "¬"]:
            numeric_vals.append(0.0)
            continue
            
        is_neg = False
        if cleaned_vt.startswith("(") and cleaned_vt.endswith(")"):
            is_neg = True
            cleaned_vt = cleaned_vt[1:-1]
        if cleaned_vt.startswith("-"):
            is_neg = True
            cleaned_vt = cleaned_vt[1:]
        
        # Giữ lại chỉ các chữ số và dấu trừ trong token sau khi đã xử lý âm để loại bỏ dấu phân cách, 
        # ký tự rác hoặc lỗi OCR phân tách ký tự đặc biệt (ví dụ: U+2044 fraction slash '⁄')
        cleaned_vt_num = re.sub(r'[^0-9\-]', '', cleaned_vt)
            
        try:
            val = float(cleaned_vt_num)
            # Không lấy chính mã số chỉ tiêu làm giá trị số tài chính
            if code_token and cleaned_vt_num == code_token:
                continue
            if is_neg:
                val = -val
            numeric_vals.append(val)
        except ValueError:
            continue

    # Lọc bỏ cột Thuyết minh nếu có thừa số ở đầu dòng:
    # Nếu danh sách có nhiều hơn 2 số và số đầu tiên là số nhỏ (< 100 và != 0) 
    # trong khi các số phía sau là số tài chính thực tế (>= 1,000,000 hoặc == 0)
    if len(numeric_vals) > 2:
        if 0 < abs(numeric_vals[0]) < 100 and any(abs(v) >= 1000000 or v == 0 for v in numeric_vals[1:]):
            numeric_vals = numeric_vals[1:]

    return numeric_vals

# -------------------------------------------------------------------------
# HÀM TRÍCH XUẤT DỮ LIỆU TỪ EXCEL BCTC DỰA TRÊN MÃ SỐ CHUẨN
# -------------------------------------------------------------------------
@st.cache_data(show_spinner="Đang phân tích cú pháp BCTC Excel...")
def parse_bctc_excel(file_bytes):
    """
    Đọc tất cả các sheet trong file Excel, nhận diện loại báo cáo theo từng sheet,
    trích xuất chính xác các giá trị số từ mã chỉ tiêu kế toán chuẩn hoặc đối sánh mờ tên nhãn chỉ tiêu.
    """
    xls = pd.ExcelFile(io.BytesIO(file_bytes))
    extracted_data = {}
    
    # Duyệt qua từng sheet trong file
    for sheet_name in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=sheet_name)
        
        # Nhận diện loại báo cáo dựa trên tên sheet
        statement = detect_statement_type(sheet_name)
        
        # 1. Tìm cột chứa mã số chỉ tiêu
        code_col = None
        for col in df.columns:
            col_str = str(col).lower()
            if any(kw in col_str for kw in ["mã số", "mã", "code", "maso"]):
                code_col = col
                break
                
        if code_col is None:
            # Quét các cột để tìm cột chứa nhiều mã số kế toán đặc trưng
            for col in df.columns:
                unique_vals = set(df[col].dropna().astype(str).str.strip().str.split('.').str[0])
                if len(unique_vals.intersection({"100", "270", "400", "10", "60"})) >= 3:
                    code_col = col
                    break
                    
        # Tìm cột chứa nhãn chỉ tiêu (tên chỉ tiêu) làm dự phòng fuzzy matching
        label_col = None
        for col in df.columns:
            col_str = str(col).lower()
            if any(kw in col_str for kw in ["chỉ tiêu", "chitieu", "nội dung", "danh mục", "tên chỉ tiêu", "description", "accounts"]):
                label_col = col
                break
                
        if label_col is None:
            # Quét tìm cột đầu tiên chứa nhiều từ khóa kế toán tiêu chuẩn
            for col in df.columns:
                text_sample = " ".join(df[col].dropna().astype(str).str.lower().tolist()[:15])
                if any(kw in text_sample for kw in ["tài sản", "nợ phải trả", "vốn chủ", "doanh thu", "lợi nhuận"]):
                    label_col = col
                    break
        
        # Nếu không tìm thấy cả cột mã số lẫn cột nhãn, bỏ qua sheet này
        if code_col is None and label_col is None:
            continue  
            
        # Nếu sheet chưa được phân loại, phân loại dựa trên nội dung cột nhãn/chỉ tiêu
        if not statement:
            sample_col = label_col if label_col is not None else code_col
            sheet_text = " ".join(df[sample_col].dropna().astype(str))
            statement = detect_statement_type(sheet_text)
            
        # 2. Tìm các cột chứa năm tài chính
        year_cols = {}
        for col in df.columns:
            col_str = str(col).strip()
            match = re.search(r'\b(20[1-2]\d)\b', col_str)
            if match:
                year = int(match.group(1))
                year_cols[col] = year
                
        if not year_cols:
            continue  
            
        # 3. Trích xuất dữ liệu
        for _, row in df.iterrows():
            target_var = None
            
            # Ưu tiên khớp theo mã số trước nếu có
            if code_col is not None and pd.notna(row[code_col]):
                raw_code = str(row[code_col]).strip().split('.')[0]
                
                # Khớp mã số trong CODE_MAP
                for var, code in CODE_MAP.items():
                    if raw_code == code:
                        if code == "20":
                            if statement == "LCTT" and var == "OCF":
                                target_var = var
                                break
                            elif statement == "KQKD" and var == "Gross_Profit":
                                target_var = var
                                break
                        else:
                            target_var = var
                            break
            
            # Fallback: Nếu không khớp được mã số nhưng có nhãn chỉ tiêu, dùng Fuzzy Label Matching
            if not target_var and label_col is not None and pd.notna(row[label_col]):
                label_text = str(row[label_col])
                # Trích xuất mã số thô nếu dính trong tên nhãn (ví dụ: "Tài sản ngắn hạn (100)")
                found_code = None
                code_matches = re.findall(r'\b(100|270|400|10|60|421|300|310|220|200)\b', label_text)
                if code_matches:
                    found_code = code_matches[0]
                target_var = match_line_to_var_sf(label_text, found_code, statement)
                
            if target_var:
                for col_name, year in year_cols.items():
                    val = row[col_name]
                    if pd.isna(val):
                        continue
                    try:
                        if isinstance(val, str):
                            # Làm sạch chuỗi số liệu để tránh lỗi dính ký tự phân cách rác
                            val_clean = re.sub(r'[^0-9\-.]', '', val)
                            numeric_val = float(val_clean) if val_clean else 0.0
                        else:
                            numeric_val = float(val)
                            
                        if year not in extracted_data:
                            extracted_data[year] = {}
                        # Tránh ghi đè nếu đã có dữ liệu hợp lệ
                        if target_var not in extracted_data[year] or extracted_data[year][target_var] == 0:
                            extracted_data[year][target_var] = numeric_val
                    except ValueError:
                        continue
                        
    return extracted_data

# -------------------------------------------------------------------------
# HÀM TRÍCH XUẤT DỮ LIỆU TỪ PDF BCTC SỬ DỤNG PDFPLUMBER VÀ TOKEN PARSING
# -------------------------------------------------------------------------
@st.cache_data(show_spinner="Đang phân tích cú pháp BCTC PDF...")
def parse_bctc_pdf(file_bytes, filename=""):
    """
    Phân tích file PDF BCTC:
    - Nhận diện các năm có trong báo cáo.
    - Duyệt từng trang, phân loại báo cáo (CDKT, KQKD, LCTT).
    - Quét dòng văn bản, tìm mã chỉ tiêu Thông tư 200 và ánh xạ chính xác cột số vào các năm tương ứng.
    """
    extracted_data = {}
    pdf_file = io.BytesIO(file_bytes)
    
    # 1. Đọc lướt toàn bộ PDF để định vị các năm tài chính xuất hiện
    all_text = ""
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            all_text += page.extract_text() or ""
            
    # Kiểm tra xem PDF có phải là dạng quét ảnh không (không có văn bản)
    if not all_text.strip():
        return parse_bctc_pdf_ocr(file_bytes, filename)
            
    # Xác định năm báo cáo Y từ tên file hoặc nội dung
    Y = None
    fn_years = [int(y) for y in re.findall(r'(20[1-2]\d)', filename)]
    if fn_years:
        Y = max(fn_years)
    if not Y:
        # Tìm ngày kết thúc kỳ kế toán trong văn bản (ví dụ kết thúc ngày 31/12/2024 hoặc 30/09/2024 niên độ HSG)
        m_period = re.search(r'(?:kết\s*thúc\s*ngày|tại\s*ngày|tai\s*ngay|ngay)\s*(?:31[\/\.-]12|30[\/\.-]09|30[\/\.-]06|31[\/\.-]03)[\/\.-](20\d\d)', all_text, re.IGNORECASE)
        if m_period:
            Y = int(m_period.group(1))
    if not Y:
        # Tìm Năm 202x trong tiêu đề cột
        m_nam = [int(y) for y in re.findall(r'Năm\s*(20\d\d)', all_text, re.IGNORECASE)]
        if m_nam:
            Y = max(m_nam)
    if not Y:
        text_years = [int(y) for y in re.findall(r'\b(20[1-2]\d)\b', all_text)]
        if text_years:
            Y = max(text_years)
    if not Y:
        Y = 2024
        
    ordered_years = [Y, Y - 1]
        
    # Khởi tạo khung dữ liệu
    for y in ordered_years:
        extracted_data[y] = {}
        
    # 2. Quét chi tiết từng trang
    pdf_file.seek(0)
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            statement = detect_statement_type(text)
            
            if not statement:
                continue # Bỏ qua trang thuyết minh hoặc phụ lục không chứa báo cáo chính
                
            lines = text.split("\n")
            for line_idx, line in enumerate(lines):
                line = clean_bctc_line(line)
                tokens = line.split()
                if not tokens:
                    continue
                    
                # Nhận diện mã chỉ tiêu: Lấy số hiệu kế toán đầu tiên xuất hiện trên dòng (<= 500)
                code_token = None
                for idx, tok in enumerate(tokens):
                    if idx == 0 and re.match(r'^\d+\.$', tok.strip()):
                        continue
                    tok_clean = tok.strip().replace(".", "").replace(",", "")
                    if re.match(r'^\d+[ab]?$', tok_clean):
                        try:
                            num_val = int(re.sub(r'[ab]', '', tok_clean))
                            if num_val <= 500:
                                code_token = tok_clean
                                break
                        except ValueError:
                            pass
                        
                target_var = match_line_to_var_sf(line, code_token, statement)
                if target_var:
                    numeric_vals = extract_numbers_from_tokens(tokens, code_token)
                    
                    # Xử lý xuống dòng (Split Line): Nếu thiếu số, quét dòng tiếp theo nếu không bắt đầu bằng mã mới
                    if len(numeric_vals) < len(ordered_years) and line_idx + 1 < len(lines):
                        next_line = clean_bctc_line(lines[line_idx + 1])
                        next_tokens = next_line.split()
                        next_code_token = None
                        if next_tokens:
                            for tok in next_tokens[:3]:
                                tok_clean = tok.strip().replace(".", "").replace(",", "")
                                if re.match(r'^\d+[ab]?$', tok_clean):
                                    next_code_token = tok_clean
                                    break
                        if not next_code_token:
                            next_numeric_vals = extract_numbers_from_tokens(next_tokens, None)
                            if len(next_numeric_vals) >= len(ordered_years):
                                numeric_vals = next_numeric_vals
                                
                    # Lọc số thuyết minh: Chỉ giữ lại N số tài chính cuối cùng tương ứng với số năm
                    numeric_vals = numeric_vals[-len(ordered_years):]
                    
                    if len(numeric_vals) == len(ordered_years):
                        for idx, val in enumerate(numeric_vals):
                            target_year = ordered_years[idx]
                            # Đảm bảo các chỉ tiêu chi phí và tài sản luôn mang giá trị dương
                            if target_var in ["COGS", "Selling_Expense", "GA_Expense", "Interest_Expense", "Tangible_PPE_Cost", "Total_Assets", "Total_Liabilities", "Current_Liabilities", "Current_Assets", "Fixed_Assets", "Cash_Equivalents", "Inventories", "Current_Receivables", "Accounts_Receivable"]:
                                val = abs(val)
                            if target_var not in extracted_data[target_year] or extracted_data[target_year][target_var] == 0:
                                extracted_data[target_year][target_var] = val
                                    
    # Tự động suy luận (auto-reconcile) các chỉ tiêu tài chính cơ bản
    extracted_data = reconcile_financial_data(extracted_data)

    # Nếu trích xuất dạng Text bị thiếu nhiều chỉ tiêu (< 16 biến hoặc thiếu Bảng CĐKT/KQKD), tự động chạy OCR bổ sung
    total_extracted_vars = sum(len(d) for d in extracted_data.values()) if extracted_data else 0
    missing_core = any(y not in extracted_data or "Total_Assets" not in extracted_data[y] or "Equity" not in extracted_data[y] or "Net_Sales" not in extracted_data[y] for y in ordered_years)
    if total_extracted_vars < 16 * len(ordered_years) or missing_core:
        try:
            ocr_data = parse_bctc_pdf_ocr(file_bytes, filename)
            if ocr_data:
                for y, y_dict in ocr_data.items():
                    if y not in extracted_data:
                        extracted_data[y] = y_dict
                    else:
                        for k, v in y_dict.items():
                            if k not in extracted_data[y] or extracted_data[y][k] == 0:
                                extracted_data[y][k] = v
                extracted_data = reconcile_financial_data(extracted_data)
        except Exception as e:
            print(f"OCR fallback error: {e}")
        except Exception as e:
            print(f"OCR fallback error: {e}")

    # Loại bỏ các năm không trích xuất được dữ liệu thực tế
    extracted_data = {y: d for y, d in extracted_data.items() if d}
    return extracted_data

# -------------------------------------------------------------------------
# HÀM PHÂN TÍCH VĂN BẢN BÁO CÁO THƯỜNG NIÊN (QUALITATIVE ANALYZER)
# -------------------------------------------------------------------------
@st.cache_data(show_spinner="Đang phân tích Báo cáo thường niên...")
def parse_annual_report_pdf(file_bytes):
    """
    Phân tích văn bản Báo cáo thường niên:
    - Trích xuất toàn bộ văn bản từ PDF.
    - Đếm số từ (ReportLen).
    - Tính tần suất từ khóa rủi ro (RiskWord) và từ tiêu cực (NegTone).
    """
    text = ""
    pdf_file = io.BytesIO(file_bytes)
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""
            
    if not text.strip():
        return None
        
    words = text.split()
    total_words = len(words)
    
    clean_text = strip_accents(text).lower()
    
    # Từ khóa rủi ro tiếng Việt không dấu
    risk_keywords = ["rui ro", "kho khan", "thach thuc", "suy giam", "bat on", "thua lo", "no xau", "thanh khoan", "vo no", "tai co cau"]
    risk_word_count = sum(clean_text.count(kw) for kw in risk_keywords)
    
    # Từ khóa tiêu cực tiếng Việt không dấu
    negative_keywords = ["yeu kem", "that bai", "thiet hai", "suy thoai", "tri tre", "cham tre", "bi phat", "kien tung", "tranh chap", "vuong mac", "ton that", "anh huong xau", "tieu cuc"]
    neg_word_count = sum(clean_text.count(kw) for kw in negative_keywords)
    
    # Tỷ lệ tiêu cực: số từ tiêu cực / tổng số từ
    neg_tone_ratio = (neg_word_count / total_words) if total_words > 0 else 0.0
    
    return {
        "total_words": total_words,
        "risk_word_count": risk_word_count,
        "neg_tone_ratio": neg_tone_ratio,
        "text": text
    }

def calculate_text_similarity(text1, text2):
    """
    Tính độ tương đồng Jaccard giữa hai văn bản dựa trên tập từ vựng không dấu.
    """
    if not text1 or not text2:
        return 0.0
    
    t1_clean = strip_accents(text1).lower()
    t2_clean = strip_accents(text2).lower()
    
    words1 = set(re.findall(r'\b\w+\b', t1_clean))
    words2 = set(re.findall(r'\b\w+\b', t2_clean))
    
    words1 = {w for w in words1 if len(w) > 1}
    words2 = {w for w in words2 if len(w) > 1}
    
    if not words1 or not words2:
        return 0.0
        
    intersection = words1.intersection(words2)
    union = words1.union(words2)
    
    return len(intersection) / len(union)

# -------------------------------------------------------------------------
# BỘ MÁY TÍNH TOÁN CÁC BIẾN KIỂM SOÁT (CONTROLS ENGINE)
# -------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def calculate_controls(data, firm_age=10, is_bds=False, gov_disc_score=0.90, risk_words_ratio=0.0, neg_tone_ratio=0.0, report_len=15000, text_sim=0.65, ceo_age=55, industry="Khác / Mặc định"):
    """
    Tính toán 22 biến kiểm soát định lượng & định tính và phân loại theo 4 mức độ rủi ro:
    Mức 1 (An toàn) -> Mức 4 (Rủi ro cao)
    """
    years = sorted(list(data.keys()))
    control_results = {}
    
    for i, year in enumerate(years):
        y_data = data[year]
        control_results[year] = {}
        
        ta = y_data.get("Total_Assets", np.nan)
        ca = y_data.get("Current_Assets", np.nan)
        cl = y_data.get("Current_Liabilities", np.nan)
        re = y_data.get("Retained_Earnings", np.nan)
        ebt = y_data.get("EBT", np.nan)
        interest = y_data.get("Interest_Expense", 0.0)
        eq = y_data.get("Equity", np.nan)
        liab = y_data.get("Total_Liabilities", np.nan)
        sales = y_data.get("Net_Sales", np.nan)
        ni = y_data.get("Net_Income", np.nan)
        ocf = y_data.get("OCF", np.nan)
        fa = y_data.get("Fixed_Assets", np.nan)
        cash_eq = y_data.get("Cash_Equivalents", 0.0)
        
        # 1. SIZE
        if pd.notna(ta) and ta > 0:
            size_val = np.log(ta)
            if size_val >= 29.24:
                size_lvl, size_desc = 1, "Mức 1: Quy mô rất lớn (Tổng TS >= 5,000 tỷ)"
            elif size_val >= 27.63:
                size_lvl, size_desc = 2, "Mức 2: Quy mô lớn (Tổng TS 1,000 - 5,000 tỷ)"
            elif size_val >= 26.02:
                size_lvl, size_desc = 3, "Mức 3: Quy mô trung bình (Tổng TS 200 - 1,000 tỷ)"
            else:
                size_lvl, size_desc = 4, "Mức 4: Quy mô nhỏ (Tổng TS < 200 tỷ)"
            control_results[year]["SIZE"] = {"value": size_val, "level": size_lvl, "desc": size_desc}
        else:
            control_results[year]["SIZE"] = None

        # 2. LEV
        if pd.notna(ta) and ta > 0 and pd.notna(liab):
            lev_val = liab / ta
            
            # Bản đồ đòn bẩy tối ưu theo ngành niêm yết tại Việt Nam (sheet Chạy chữ U)
            # Tải ngưỡng tối ưu động từ tệp cấu hình JSON, fallback về mặc định
            config_file = os.path.join(BASE_DIR, "industry_opt_lev.json")
            default_opt_lev = {
                "Basic Materials (Nguyên vật liệu)": 0.7450,
                "Consumer Goods (Hàng tiêu dùng)": 0.5201,
                "Industrials (Công nghiệp)": 0.3989,
                "Oil & Gas (Dầu khí)": 1.1176,
                "Technology (Công nghệ)": 0.4441
            }
            if os.path.exists(config_file):
                try:
                    with open(config_file, "r", encoding="utf-8") as f:
                        industry_opt_lev = json.load(f)
                except Exception:
                    industry_opt_lev = default_opt_lev
            else:
                industry_opt_lev = default_opt_lev
            
            opt_lev = industry_opt_lev.get(industry, 0.50)
            if is_bds:
                opt_lev = 0.60
                
            if lev_val <= (opt_lev + 0.05):
                lev_lvl, lev_desc = 1, f"Mức 1: An toàn & Tối ưu (Đòn bẩy {lev_val:.2%} dưới hoặc gần mức tối ưu ngành {opt_lev:.2%})"
            elif lev_val <= (opt_lev + 0.15):
                lev_lvl, lev_desc = 2, f"Mức 2: Bắt đầu vượt ngưỡng tối ưu nhẹ (Đòn bẩy {lev_val:.2%} so với tối ưu {opt_lev:.2%})"
            elif lev_val <= (opt_lev + 0.25):
                lev_lvl, lev_desc = 3, f"Mức 3: Cảnh báo đòn bẩy cao (Đòn bẩy {lev_val:.2%} vượt quá ngưỡng tối ưu ngành {opt_lev:.2%})"
            else:
                lev_lvl, lev_desc = 4, f"Mức 4: Rủi ro kiệt quệ tài chính cực lớn (Đòn bẩy {lev_val:.2%} vượt xa ngưỡng tối ưu ngành {opt_lev:.2%})"
                
            control_results[year]["LEV"] = {"value": lev_val, "level": lev_lvl, "desc": lev_desc}
        else:
            control_results[year]["LEV"] = None

        # 3. ROA
        if pd.notna(ta) and ta > 0 and pd.notna(ni):
            roa_val = ni / ta
            if roa_val >= 0.07:
                roa_lvl, roa_desc = 1, "Mức 1: Sinh lời tốt (>= 7%)"
            elif roa_val >= 0.03:
                roa_lvl, roa_desc = 2, "Mức 2: Sinh lời trung bình (3% - 7%)"
            elif roa_val >= 0.0:
                roa_lvl, roa_desc = 3, "Mức 3: Sinh lời yếu (0% - 3%)"
            else:
                roa_lvl, roa_desc = 4, "Mức 4: Hoạt động thua lỗ (< 0%)"
            control_results[year]["ROA"] = {"value": roa_val, "level": roa_lvl, "desc": roa_desc}
        else:
            control_results[year]["ROA"] = None

        # 4. GROWTH
        growth_val = np.nan
        if i > 0:
            prev_year = years[i-1]
            sales_prev = data[prev_year].get("Net_Sales", np.nan)
            if pd.notna(sales) and pd.notna(sales_prev) and sales_prev > 0:
                growth_val = (sales - sales_prev) / sales_prev
                
        if pd.notna(growth_val):
            if 0.0 <= growth_val <= 0.30:
                g_lvl, g_desc = 1, "Mức 1: Tăng trưởng ổn định (0% - 30%)"
            elif (0.30 < growth_val <= 0.50) or (-0.10 <= growth_val < 0.0):
                g_lvl, g_desc = 2, "Mức 2: Tăng trưởng nóng nhẹ / Suy giảm nhẹ"
            elif (0.50 < growth_val <= 1.0) or (-0.25 <= growth_val < -0.10):
                g_lvl, g_desc = 3, "Mức 3: Tăng trưởng quá nóng / Suy giảm đáng kể"
            else:
                g_lvl, g_desc = 4, "Mức 4: Biến động doanh thu bất thường (>100% hoặc <-25%)"
            control_results[year]["GROWTH"] = {"value": growth_val, "level": g_lvl, "desc": g_desc}
        else:
            control_results[year]["GROWTH"] = None

        # 5. CR
        if pd.notna(ca) and pd.notna(cl) and cl > 0:
            cr_val = ca / cl
            if cr_val >= 1.5:
                cr_lvl, cr_desc = 1, "Mức 1: Thanh khoản rất tốt (>= 1.5)"
            elif cr_val >= 1.2:
                cr_lvl, cr_desc = 2, "Mức 2: Thanh khoản an toàn (1.2 - 1.5)"
            elif cr_val >= 1.0:
                cr_lvl, cr_desc = 3, "Mức 3: Thanh khoản eo hẹp (1.0 - 1.2)"
            else:
                cr_lvl, cr_desc = 4, "Mức 4: Mất cân đối thanh khoản ngắn hạn (< 1.0)"
            control_results[year]["CR"] = {"value": cr_val, "level": cr_lvl, "desc": cr_desc}
        else:
            control_results[year]["CR"] = None

        # 6. WC/TA
        if pd.notna(ta) and ta > 0 and pd.notna(ca) and pd.notna(cl):
            wcta_val = (ca - cl) / ta
            if wcta_val >= 0.20:
                wc_lvl, wc_desc = 1, "Mức 1: Vốn lưu động dồi dào (>= 20% TS)"
            elif wcta_val >= 0.10:
                wc_lvl, wc_desc = 2, "Mức 2: Vốn lưu động an toàn (10% - 20% TS)"
            elif wcta_val >= 0.0:
                wc_lvl, wc_desc = 3, "Mức 3: Vốn lưu động mỏng (0% - 10% TS)"
            else:
                wc_lvl, wc_desc = 4, "Mức 4: Vốn lưu động âm (Rủi ro thanh toán ngắn hạn)"
            control_results[year]["WC_TA"] = {"value": wcta_val, "level": wc_lvl, "desc": wc_desc}
        else:
            control_results[year]["WC_TA"] = None

        # 7. RE/TA
        if pd.notna(ta) and ta > 0 and pd.notna(re):
            reta_val = re / ta
            if reta_val >= 0.25:
                re_lvl, re_desc = 1, "Mức 1: Thặng dư lợi nhuận tích lũy lớn (>= 25% TS)"
            elif reta_val >= 0.10:
                re_lvl, re_desc = 2, "Mức 2: Tích lũy trung bình (10% - 25% TS)"
            elif reta_val >= 0.0:
                re_lvl, re_desc = 3, "Mức 3: Tích lũy thấp (0% - 10% TS)"
            else:
                re_lvl, re_desc = 4, "Mức 4: Lỗ lũy kế âm vốn (< 0% TS)"
            control_results[year]["RE_TA"] = {"value": reta_val, "level": re_lvl, "desc": re_desc}
        else:
            control_results[year]["RE_TA"] = None

        # 8. EBIT/TA
        if pd.notna(ta) and ta > 0 and pd.notna(ebt):
            ebit_val = ebt + interest
            ebitta_val = ebit_val / ta
            if ebitta_val >= 0.10:
                ebit_lvl, ebit_desc = 1, "Mức 1: Tỷ suất EBIT tốt (>= 10%)"
            elif ebitta_val >= 0.05:
                ebit_lvl, ebit_desc = 2, "Mức 2: Tỷ suất EBIT trung bình (5% - 10%)"
            elif ebitta_val >= 0.0:
                ebit_lvl, ebit_desc = 3, "Mức 3: Tỷ suất EBIT yếu (0% - 5%)"
            else:
                ebit_lvl, ebit_desc = 4, "Mức 4: EBIT âm (Lỗ hoạt động kinh doanh)"
            control_results[year]["EBIT_TA"] = {"value": ebitta_val, "level": ebit_lvl, "desc": ebit_desc}
        else:
            control_results[year]["EBIT_TA"] = None

        # 9. ATO
        if pd.notna(ta) and ta > 0 and pd.notna(sales):
            ato_val = sales / ta
            if ato_val >= 1.0:
                ato_lvl, ato_desc = 1, "Mức 1: Vòng quay tài sản nhanh (>= 1.0 lần)"
            elif ato_val >= 0.7:
                ato_lvl, ato_desc = 2, "Mức 2: Vòng quay tài sản trung bình (0.7 - 1.0 lần)"
            elif ato_val >= 0.4:
                ato_lvl, ato_desc = 3, "Mức 3: Vòng quay tài sản chậm (0.4 - 0.7 lần)"
            else:
                ato_lvl, ato_desc = 4, "Mức 4: Hiệu suất sử dụng tài sản rất thấp (< 0.4 lần)"
            control_results[year]["ATO"] = {"value": ato_val, "level": ato_lvl, "desc": ato_desc}
        else:
            control_results[year]["ATO"] = None

        # 10. INVEST
        invest_val = np.nan
        if i > 0:
            prev_year = years[i-1]
            fa_prev = data[prev_year].get("Fixed_Assets", np.nan)
            dep = y_data.get("depreciation", 0.0)
            if dep == 0.0:
                dep = y_data.get("Depreciation", 0.0)
            if pd.notna(fa) and pd.notna(fa_prev) and pd.notna(ta) and ta > 0:
                invest_val = (fa - fa_prev + dep) / ta
        
        if pd.notna(invest_val):
            if invest_val >= 0.08:
                inv_lvl, inv_desc = 1, "Mức 1: Đầu tư phát triển mạnh (>= 8% TS)"
            elif invest_val >= 0.04:
                inv_lvl, inv_desc = 2, "Mức 2: Đầu tư trung bình (4% - 8% TS)"
            elif invest_val >= 0.0:
                inv_lvl, inv_desc = 3, "Mức 3: Đầu tư cầm chừng (0% - 4% TS)"
            else:
                inv_lvl, inv_desc = 4, "Mức 4: Đầu tư ròng âm (Thoái vốn ròng)"
            control_results[year]["INVEST"] = {"value": invest_val, "level": inv_lvl, "desc": inv_desc}
        else:
            control_results[year]["INVEST"] = None

        # 11. CF
        if pd.notna(ta) and ta > 0 and pd.notna(ocf):
            cf_val = ocf / ta
            if cf_val >= 0.10:
                cf_lvl, cf_desc = 1, "Mức 1: Dòng tiền HĐKD mạnh (>= 10% TS)"
            elif cf_val >= 0.05:
                cf_lvl, cf_desc = 2, "Mức 2: Dòng tiền HĐKD khá (5% - 10% TS)"
            elif cf_val >= 0.0:
                cf_lvl, cf_desc = 3, "Mức 3: Dòng tiền HĐKD yếu (0% - 5% TS)"
            else:
                cf_lvl, cf_desc = 4, "Mức 4: Dòng tiền HĐKD âm (Khô hạn thanh khoản)"
            control_results[year]["CF"] = {"value": cf_val, "level": cf_lvl, "desc": cf_desc}
        else:
            control_results[year]["CF"] = None

        # 12. ACCR
        if pd.notna(ta) and ta > 0 and pd.notna(ni) and pd.notna(ocf):
            accr_val = abs(ni - ocf) / ta
            if accr_val < 0.05:
                accr_lvl, accr_desc = 1, "Mức 1: Chất lượng LN cao (Dồn tích thấp < 5% TS)"
            elif accr_val < 0.10:
                accr_lvl, accr_desc = 2, "Mức 2: Chất lượng LN an toàn (5% - 10% TS)"
            elif accr_val < 0.20:
                accr_lvl, accr_desc = 3, "Mức 3: Cảnh báo dồn tích lớn (10% - 20% TS)"
            else:
                accr_lvl, accr_desc = 4, "Mức 4: Nghi ngờ bóp méo kế toán (Dồn tích lớn >= 20% TS)"
            control_results[year]["ACCR"] = {"value": accr_val, "level": accr_lvl, "desc": accr_desc}
        else:
            control_results[year]["ACCR"] = None

        # 13. SOFT
        if pd.notna(ta) and ta > 0:
            fixed_ast = fa if pd.notna(fa) else 0.0
            soft_val = (ta - fixed_ast - cash_eq) / ta
            if soft_val < 0.40:
                soft_lvl, soft_desc = 1, "Mức 1: Cơ cấu TS cứng rắn (Tài sản mềm < 40%)"
            elif soft_val < 0.55:
                soft_lvl, soft_desc = 2, "Mức 2: Cơ cấu TS bình thường (40% - 55%)"
            elif soft_val < 0.70:
                soft_lvl, soft_desc = 3, "Mức 3: Tài sản mềm cao (55% - 70%)"
            else:
                soft_lvl, soft_desc = 4, "Mức 4: Rủi ro tài sản ảo/Dễ bóp méo (Tài sản mềm >= 70%)"
            control_results[year]["SOFT"] = {"value": soft_val, "level": soft_lvl, "desc": soft_desc}
        else:
            control_results[year]["SOFT"] = None

        # --- KHỐI A: CÁC BIẾN ĐỊNH TÍNH ---
        # 14. RiskWord
        rw_ratio = risk_words_ratio
        if rw_ratio < 1.0:
            rw_lvl, rw_desc = 1, "Mức 1: Thấp (Dưới 1.0‰)"
        elif rw_ratio < 2.0:
            rw_lvl, rw_desc = 2, "Mức 2: Vừa phải (1.0‰ - 2.0‰)"
        elif rw_ratio < 4.0:
            rw_lvl, rw_desc = 3, "Mức 3: Đáng lưu ý (2.0‰ - 4.0‰)"
        else:
            rw_lvl, rw_desc = 4, "Mức 4: Rủi ro cao (Từ khóa rủi ro dày đặc >= 4.0‰)"
        control_results[year]["RiskWord"] = {"value": rw_ratio, "level": rw_lvl, "desc": rw_desc}

        # 15. NegTone
        neg_val = neg_tone_ratio
        if neg_val < 0.01:
            neg_lvl, neg_desc = 1, "Mức 1: Tích cực (Từ tiêu cực < 1%)"
        elif neg_val < 0.02:
            neg_lvl, neg_desc = 2, "Mức 2: Trung tính (1% - 2%)"
        elif neg_val < 0.035:
            neg_lvl, neg_desc = 3, "Mức 3: Cảnh giác (2% - 3.5%)"
        else:
            neg_lvl, neg_desc = 4, "Mức 4: Sắc thái tiêu cực cao (> 3.5%)"
        control_results[year]["NegTone"] = {"value": neg_val, "level": neg_lvl, "desc": neg_desc}

        # 16. ReportLen
        med_words = 15000.0
        rep_len = report_len if report_len > 0 else 15000.0
        len_ratio = rep_len / med_words
        if 0.8 <= len_ratio <= 1.2:
            len_lvl, len_desc = 1, "Mức 1: Tiêu chuẩn (80% - 120% trung vị)"
        elif (1.2 < len_ratio <= 1.5) or (0.6 <= len_ratio < 0.8):
            len_lvl, len_desc = 2, "Mức 2: Hơi ngắn / Hơi dài"
        elif (1.5 < len_ratio <= 2.0) or (0.4 <= len_ratio < 0.6):
            len_lvl, len_desc = 3, "Mức 3: Quá ngắn (Thiếu thông tin) / Quá dài (Lan man)"
        else:
            len_lvl, len_desc = 4, "Mức 4: Rất sơ sài (<0.4x) hoặc Cực kỳ phức tạp (>2.0x)"
        control_results[year]["ReportLen"] = {"value": float(rep_len), "level": len_lvl, "desc": len_desc}

        # 17. GovDisc
        gov_val = gov_disc_score
        if gov_val >= 0.90:
            gov_lvl, gov_desc = 1, "Mức 1: Rất minh bạch (Checklist >= 90%)"
        elif gov_val >= 0.70:
            gov_lvl, gov_desc = 2, "Mức 2: Minh bạch khá (70% - 89%)"
        elif gov_val >= 0.50:
            gov_lvl, gov_desc = 3, "Mức 3: Minh bạch trung bình (50% - 69%)"
        else:
            gov_lvl, gov_desc = 4, "Mức 4: Kém minh bạch/Vi phạm QT (< 50%)"
        control_results[year]["GovDisc"] = {"value": gov_val, "level": gov_lvl, "desc": gov_desc}

        # 18. TextSim
        sim_val = text_sim
        if 0.55 <= sim_val <= 0.80:
            sim_lvl, sim_desc = 1, "Mức 1: Cập nhật hợp lý (55% - 80% tương đồng)"
        elif (0.80 < sim_val <= 0.90) or (0.45 <= sim_val < 0.55):
            sim_lvl, sim_desc = 2, "Mức 2: Trùng lặp nhẹ / Thay đổi nhẹ"
        elif (0.90 < sim_val <= 0.95) or (0.30 <= sim_val < 0.45):
            sim_lvl, sim_desc = 3, "Mức 3: Trùng lặp cao (Có thể copy-paste) / Biến động mạnh"
        else:
            sim_lvl, sim_desc = 4, "Mức 4: Copy-paste hoàn toàn (>95%) hoặc Thay đổi bất thường (<30%)"
        control_results[year]["TextSim"] = {"value": sim_val, "level": sim_lvl, "desc": sim_desc}

        # 19. CEOAge
        c_age = float(ceo_age)
        if 50.0 <= c_age <= 70.0:
            ceo_lvl, ceo_desc = 1, f"Mức 1: Thấp (CEO {c_age:.0f} tuổi thuộc nhóm quản trị an toàn, bảo vệ sản nghiệp)"
        elif 40.0 <= c_age < 50.0:
            ceo_lvl, ceo_desc = 2, f"Mức 2: Vừa phải (CEO {c_age:.0f} tuổi ở giai đoạn chín muồi, ít động lực thao túng)"
        elif 30.0 <= c_age < 40.0:
            ceo_lvl, ceo_desc = 3, f"Mức 3: Cao (CEO {c_age:.0f} tuổi chịu áp lực khẳng định bản thân ở doanh nghiệp gia đình)"
        else:
            ceo_lvl, ceo_desc = 4, f"Mức 4: Khẩn cấp (CEO {c_age:.0f} tuổi đối mặt áp lực chuyển giao thế hệ/di sản hoặc quá trẻ)"
        control_results[year]["CEOAge"] = {"value": c_age, "level": ceo_lvl, "desc": ceo_desc}

    return control_results


# -------------------------------------------------------------------------
# HÀM TRÍCH XUẤT DỮ LIỆU TỪ PDF QUÉT BẰNG TESSERACT OCR
# -------------------------------------------------------------------------
@st.cache_data(show_spinner="Đang chạy OCR phân tích PDF quét ảnh...")
def parse_bctc_pdf_ocr(file_bytes, filename):
    """
    Chạy OCR trên tối đa 20 trang đầu của PDF để trích xuất dữ liệu BCTC
    khi không tìm thấy lớp văn bản.
    """
    extracted_data = {}
    
    import fitz
    import pytesseract
    from PIL import Image
    
    # Thiết lập đường dẫn tesseract tự động phát hiện trên Mac hoặc Windows
    if sys.platform == "win32":
        win_tesseract = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        if os.path.exists(win_tesseract):
            pytesseract.pytesseract.tesseract_cmd = win_tesseract
    else:
        mac_tesseract = '/opt/anaconda3/bin/tesseract'
        if os.path.exists(mac_tesseract):
            pytesseract.pytesseract.tesseract_cmd = mac_tesseract
    
    pdf_file = io.BytesIO(file_bytes)
    doc = fitz.open(stream=pdf_file, filetype="pdf")
    total_pages = len(doc)
    
    # Chỉ chạy OCR tối đa 25 trang đầu để tối ưu thời gian và bắt trọn vẹn BCTC hợp nhất
    max_pages = min(25, total_pages)
    
    # Hiển thị thanh tiến trình trong Streamlit
    progress_bar = st.progress(0, text=f"Đang chuẩn bị OCR...")
    
    all_text = ""
    page_texts = {}
    
    for i in range(max_pages):
        progress_bar.progress((i + 1) / max_pages, text=f"Đang chạy OCR cho file **{filename}** (Trang {i+1}/{max_pages})...")
        
        # Chuyển trang PDF thành ảnh
        page = doc[i]
        mat = fitz.Matrix(200 / 72, 200 / 72) # 200 DPI
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        
        # Chạy OCR
        text = pytesseract.image_to_string(img, lang='vie+eng', config='--psm 6 -c preserve_interword_spaces=1')
        page_texts[i] = text
        all_text += text + "\n"
        
    progress_bar.empty()
    
    # Xác định năm báo cáo Y từ tên file hoặc nội dung OCR
    Y = None
    fn_years = [int(y) for y in re.findall(r'(20[1-2]\d)', filename)]
    if fn_years:
        Y = max(fn_years)
    if not Y:
        # Quét các trang CDKT/KQKD để tìm ngày kết thúc kỳ tài chính (31/12 hoặc 30/09)
        for pidx, ptext in page_texts.items():
            m_period = re.search(r'(?:kết\s*thúc\s*ngày|tại\s*ngày|tai\s*ngay|ngay)\s*(?:31[\/\.-]12|30[\/\.-]09|30[\/\.-]06|31[\/\.-]03)[\/\.-](20\d\d)', ptext, re.IGNORECASE)
            if m_period:
                Y = int(m_period.group(1))
                break
    if not Y:
        # Tìm tiêu đề cột Năm 202x
        for pidx, ptext in page_texts.items():
            m_nams = [int(y) for y in re.findall(r'Năm\s*(20\d\d)', ptext, re.IGNORECASE)]
            if m_nams:
                Y = max(m_nams)
                break
    if not Y:
        text_years = [int(y) for y in re.findall(r'\b(20[1-2]\d)\b', all_text)]
        if text_years:
            Y = max(text_years)
    if not Y:
        Y = 2024
        
    ordered_years = [Y, Y - 1]
        
    for y in ordered_years:
        extracted_data[y] = {}
        
    # Phân tích từng trang OCR để trích xuất chỉ tiêu
    for page_idx, text in page_texts.items():
        statement = detect_statement_type(text)
        if not statement:
            continue
            
        lines = text.split("\n")
        for line_idx, line in enumerate(lines):
            line = clean_bctc_line(line)
            tokens = line.split()
            if not tokens:
                continue
                
            # Nhận diện mã chỉ tiêu: Lấy số hiệu kế toán đầu tiên xuất hiện trên dòng (<= 500)
            code_token = None
            for idx, tok in enumerate(tokens):
                if idx == 0 and re.match(r'^\d+\.$', tok.strip()):
                    continue
                tok_clean = tok.strip().replace(".", "").replace(",", "")
                if re.match(r'^\d+[ab]?$', tok_clean):
                    try:
                        num_val = int(re.sub(r'[ab]', '', tok_clean))
                        if num_val <= 500:
                            code_token = tok_clean
                            break
                    except ValueError:
                        pass
                    
            target_var = match_line_to_var_sf(line, code_token, statement)
            if target_var:
                numeric_vals = extract_numbers_from_tokens(tokens, code_token)
                
                # Xử lý xuống dòng (Split Line): Nếu thiếu số, quét dòng tiếp theo nếu không bắt đầu bằng mã mới
                if len(numeric_vals) < len(ordered_years) and line_idx + 1 < len(lines):
                    next_line = clean_bctc_line(lines[line_idx + 1])
                    next_tokens = next_line.split()
                    next_code_token = None
                    if next_tokens:
                        for tok in next_tokens[:3]:
                            tok_clean = tok.strip().replace(".", "").replace(",", "")
                            if re.match(r'^\d+[ab]?$', tok_clean):
                                next_code_token = tok_clean
                                break
                    if not next_code_token:
                        next_numeric_vals = extract_numbers_from_tokens(next_tokens, None)
                        if len(next_numeric_vals) >= len(ordered_years):
                            numeric_vals = next_numeric_vals
                            
                # Lọc số thuyết minh: Chỉ giữ lại N số tài chính cuối cùng tương ứng với số năm
                numeric_vals = numeric_vals[-len(ordered_years):]
                
                if len(numeric_vals) == len(ordered_years):
                    for idx, val in enumerate(numeric_vals):
                        target_year = ordered_years[idx]
                        # Đảm bảo các chỉ tiêu chi phí và tài sản luôn mang giá trị dương
                        if target_var in ["COGS", "Selling_Expense", "GA_Expense", "Interest_Expense", "Tangible_PPE_Cost", "Total_Assets", "Total_Liabilities", "Current_Liabilities", "Current_Assets", "Fixed_Assets", "Cash_Equivalents", "Inventories", "Current_Receivables", "Accounts_Receivable"]:
                            val = abs(val)
                        if target_var not in extracted_data[target_year] or extracted_data[target_year][target_var] == 0:
                            extracted_data[target_year][target_var] = val
                                
    # Tự động suy luận và cân đối toàn diện các báo cáo
    extracted_data = reconcile_financial_data(extracted_data)
    extracted_data = {y: d for y, d in extracted_data.items() if d}
    return extracted_data

# -------------------------------------------------------------------------
# HÀM KIỂM TRA TÍNH TOÀN VẸN VÀ XÁC THỰC DỮ LIỆU (VALIDATION)
# -------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def validate_data(data):
    """
    Kiểm tra tính toàn vẹn của dữ liệu:
    - Có đủ 3 năm liên tiếp hay không.
    - Cân đối kế toán cơ bản (Tổng tài sản = Nợ phải trả + Vốn chủ sở hữu).
    - Các chỉ tiêu bắt buộc bị thiếu.
    Tự động hiệu chỉnh lỗi dính chữ số OCR (ví dụ 410.780... -> 10.780...) để cân đối sổ sách.
    """
    logs = []
    is_valid = True
    
    # 1. Kiểm tra số năm dữ liệu
    years = sorted(list(data.keys()))
    if len(years) < 3:
        logs.append({
            "type": "error",
            "message": f"❌ Không đủ dữ liệu 3 năm. Hệ thống chỉ tìm thấy {len(years)} năm: {', '.join(map(str, years))}. Cần tối thiểu 3 năm để tính các biến động chuỗi thời gian như Beneish M-Score."
        })
        is_valid = False
    else:
        is_consecutive = all(years[i] - years[i-1] == 1 for i in range(1, len(years)))
        if not is_consecutive:
            logs.append({
                "type": "warning",
                "message": f"⚠️ Các năm tài chính được phát hiện không liên tiếp: {', '.join(map(str, years))}. Tính toán động lực tăng trưởng có thể không chính xác."
            })
            is_valid = False
        else:
            logs.append({
                "type": "success",
                "message": f"✅ Kiểm tra số năm: Đủ 3 năm liên tiếp ({years[0]} - {years[-1]})."
            })
    # 2. Bộ giải Cân đối Kế toán (Math Solver & Imputation)
    for year in years:
        y_data = data[year]
        for _ in range(3): # Lặp lại tối đa 3 lần để lan truyền các giá trị nội suy liên tiếp
            # Phương trình 1: Tổng tài sản = Nợ phải trả + Vốn CSH
            ta = y_data.get("Total_Assets", 0)
            liab = y_data.get("Total_Liabilities", 0)
            eq = y_data.get("Equity", 0)
            
            if ta == 0 and liab > 0 and eq > 0:
                y_data["Total_Assets"] = liab + eq
                logs.append({
                    "type": "success",
                    "message": f"ℹ️ Năm {year}: Tự động điền khuyết Tổng tài sản = Nợ ({liab:,.0f} đ) + Vốn CSH ({eq:,.0f} đ) = {liab+eq:,.0f} đ."
                })
            elif ta > 0 and liab == 0 and eq > 0:
                y_data["Total_Liabilities"] = ta - eq
                logs.append({
                    "type": "success",
                    "message": f"ℹ️ Năm {year}: Tự động điền khuyết Nợ phải trả = Tổng tài sản ({ta:,.0f} đ) - Vốn CSH ({eq:,.0f} đ) = {ta-eq:,.0f} đ."
                })
            elif ta > 0 and liab > 0 and eq == 0:
                y_data["Equity"] = ta - liab
                logs.append({
                    "type": "success",
                    "message": f"ℹ️ Năm {year}: Tự động điền khuyết Vốn CSH = Tổng tài sản ({ta:,.0f} đ) - Nợ ({liab:,.0f} đ) = {ta-liab:,.0f} đ."
                })
                
            # Phương trình 2: Lợi nhuận gộp = Doanh thu thuần - Giá vốn bán hàng
            sales = y_data.get("Net_Sales", 0)
            cogs = y_data.get("COGS", 0)
            gp = y_data.get("Gross_Profit", 0)
            
            if gp == 0 and sales > 0 and cogs > 0:
                y_data["Gross_Profit"] = sales - cogs
                logs.append({
                    "type": "success",
                    "message": f"ℹ️ Năm {year}: Tự động điền khuyết Lợi nhuận gộp = Doanh thu ({sales:,.0f} đ) - Giá vốn ({cogs:,.0f} đ) = {sales-cogs:,.0f} đ."
                })
            elif sales == 0 and gp > 0 and cogs > 0:
                y_data["Net_Sales"] = gp + cogs
                logs.append({
                    "type": "success",
                    "message": f"ℹ️ Năm {year}: Tự động điền khuyết Doanh thu thuần = Lợi nhuận gộp ({gp:,.0f} đ) + Giá vốn ({cogs:,.0f} đ) = {gp+cogs:,.0f} đ."
                })
            elif cogs == 0 and sales > 0 and gp > 0:
                y_data["COGS"] = sales - gp
                logs.append({
                    "type": "success",
                    "message": f"ℹ️ Năm {year}: Tự động điền khuyết Giá vốn hàng bán = Doanh thu ({sales:,.0f} đ) - Lợi nhuận gộp ({gp:,.0f} đ) = {sales-gp:,.0f} đ."
                })

            # Phương trình 3: Tổng tài sản = Tài sản ngắn hạn + Tài sản dài hạn (nếu có đủ cột và khớp mã)
            ca = y_data.get("Current_Assets", 0)
            fa = y_data.get("Fixed_Assets", 0) # Fixed_Assets mã 220 hoặc Tài sản dài hạn mã 200
            # Chỉ nội suy tài sản ngắn hạn nếu tổng tài sản và tài sản dài hạn khớp
            if ca == 0 and ta > 0 and fa > 0 and ta > fa:
                y_data["Current_Assets"] = ta - fa

    # 3. Kiểm tra các chỉ tiêu quan trọng bị thiếu (tránh Hallucination)
    for year in years:
        missing_vars = []
        for var in CODE_MAP.keys():
            if var not in data[year]:
                missing_vars.append(VAR_NAMES_VN[var])
                
        if missing_vars:
            logs.append({
                "type": "warning",
                "message": f"⚠️ Năm {year}: Thiếu các chỉ tiêu: {', '.join(missing_vars)}."
            })
            
        # 4. Kiểm tra và cân đối kế toán cơ bản (Tổng tài sản = Nợ phải trả + Vốn CSH)
        ta = data[year].get("Total_Assets", 0)
        liab = data[year].get("Total_Liabilities", 0)
        eq = data[year].get("Equity", 0)
        
        if ta > 0 and (liab > 0 or eq > 0):
            diff = abs(ta - (liab + eq))
            
            # Nếu chênh lệch cực nhỏ (sai lệch làm tròn đơn vị nhỏ hơn 0.1% tổng tài sản)
            if 0 < diff <= (ta * 0.001):
                # Tự động cân đối bằng cách cộng/trừ chênh lệch vào Nợ hoặc Vốn chủ sở hữu
                data[year]["Total_Liabilities"] = ta - eq
                logs.append({
                    "type": "success",
                    "message": f"ℹ️ Năm {year}: Đã tự động xử lý chênh lệch số lẻ làm tròn kế toán ({diff:,.0f} đ) để cân đối bảng cân đối."
                })
            elif diff > 0.0:
                corrected = False
                
                # Thử sửa đổi Equity do lỗi nhận diện OCR dính chữ số ở đầu
                if eq > ta:
                    eq_str = str(int(eq))
                    for skip in range(1, len(eq_str)):
                        try:
                            eq_try = float(eq_str[skip:])
                            if abs(ta - (liab + eq_try)) < (ta * 0.001 + 10000000):
                                data[year]["Equity"] = eq_try
                                logs.append({
                                    "type": "success",
                                    "message": f"ℹ️ Năm {year}: Tự động sửa lỗi dính chữ số OCR cho Vốn chủ sở hữu ({eq:,.0f} đ -> {eq_try:,.0f} đ) để cân đối sổ sách."
                                })
                                corrected = True
                                break
                        except ValueError:
                            continue
                            
                # Thử sửa đổi Total_Liabilities do lỗi nhận diện OCR dính chữ số ở đầu
                elif liab > ta:
                    liab_str = str(int(liab))
                    for skip in range(1, len(liab_str)):
                        try:
                            liab_try = float(liab_str[skip:])
                            if abs(ta - (liab_try + eq)) < (ta * 0.001 + 10000000):
                                data[year]["Total_Liabilities"] = liab_try
                                logs.append({
                                    "type": "success",
                                    "message": f"ℹ️ Năm {year}: Tự động sửa lỗi dính chữ số OCR cho Nợ phải trả ({liab:,.0f} đ -> {liab_try:,.0f} đ) để cân đối sổ sách."
                                })
                                corrected = True
                                break
                        except ValueError:
                            continue
                            
                if not corrected:
                    logs.append({
                        "type": "error",
                        "message": f"❌ Năm {year}: Mất cân đối kế toán! Tổng tài sản ({ta:,.0f} đ) khác so với Nợ phải trả + Vốn CSH ({liab + eq:,.0f} đ). Chênh lệch: {diff:,.0f} đ."
                    })
                    is_valid = False
                else:
                    logs.append({
                        "type": "success",
                        "message": f"✅ Năm {year}: Đã tự động hiệu chỉnh và đảm bảo cân đối kế toán cơ bản (Tổng tài sản = Nợ + VCSH)."
                    })
            else:
                logs.append({
                    "type": "success",
                    "message": f"✅ Năm {year}: Đảm bảo cân đối kế toán cơ bản (Tổng tài sản = Nợ + VCSH)."
                })
        else:
            logs.append({
                "type": "success",
                "message": f"✅ Năm {year}: Đảm bảo cân đối kế toán cơ bản (Tổng tài sản = Nợ + VCSH)."
            })
            
    return is_valid, logs

def fetch_live_market_parameters(ticker, year, total_assets):
    """
    Tải trực tuyến các tham số EWS nâng cao từ API Vnstock cho năm được chọn.
    """
    import vnstock.core.utils.env as env
    env.get_hosting_service = lambda: "Local"
    from vnstock import Company, Quote, Reference, Finance
    import pandas as pd
    
    # Kết quả mặc định
    result = {
        "tobin_q": 1.2,
        "div_ratio": 0.0,
        "isg": 0.08,
        "ab_return": 0.0,
        "issue": False
    }
    
    ticker = str(ticker).strip().upper()
    if not ticker or ticker == "N/A" or len(ticker) < 3:
        return result
        
    try:
        # 1. Lấy số CP lưu hành
        comp = Company(symbol=ticker)
        df_ov = comp.overview()
        outstanding_shares = 0.0
        if not df_ov.empty and "outstanding_shares" in df_ov.columns:
            outstanding_shares = float(df_ov.iloc[0]["outstanding_shares"])
            
        # 2. Lấy giá cuối năm
        q = Quote(symbol=ticker)
        df_price = q.ohlcv(start=f"{year}-12-10", end=f"{year}-12-31")
        last_price = 0.0
        if not df_price.empty:
            last_price = float(df_price.iloc[-1]["close"]) * 1000.0 # Vnstock là nghìn đồng
            
        market_cap = last_price * outstanding_shares
        if market_cap > 0 and total_assets > 0:
            result["tobin_q"] = float(market_cap / total_assets)
            
        # 3. Lấy Abnormal Return
        df_price_full = q.ohlcv(start=f"{year}-01-01", end=f"{year}-12-31")
        stock_return = 0.0
        if not df_price_full.empty and len(df_price_full) > 5:
            first_close = float(df_price_full.iloc[0]["close"])
            last_close = float(df_price_full.iloc[-1]["close"])
            if first_close > 0:
                stock_return = (last_close / first_close) - 1.0
                
        vni_q = Quote(symbol="VNINDEX")
        df_vni = vni_q.ohlcv(start=f"{year}-01-01", end=f"{year}-12-31")
        vni_return = 0.0
        if not df_vni.empty and len(df_vni) > 5:
            first_vni = float(df_vni.iloc[0]["close"])
            last_vni = float(df_vni.iloc[-1]["close"])
            if first_vni > 0:
                vni_return = (last_vni / first_vni) - 1.0
                
        result["ab_return"] = stock_return - vni_return
        
        # 4. Lấy đổi thay số CP lưu hành để check Phát hành thêm
        df_cap = comp.capital_history()
        if not df_cap.empty and "increase_volume" in df_cap.columns:
            if "date" in df_cap.columns:
                df_cap["year"] = pd.to_datetime(df_cap["date"]).dt.year
                df_cap_y = df_cap[df_cap["year"] == int(year)]
                if not df_cap_y.empty:
                    result["issue"] = float(df_cap_y["increase_volume"].sum()) > 0
                    
        # 5. Tăng trưởng DT ngành
        df_sec = Reference().industry().sectors()
        row_sec = df_sec[df_sec["symbol"] == ticker]
        if not row_sec.empty:
            ind_name = row_sec.iloc[0]["industry_name"]
            if "Công nghệ" in ind_name:
                result["isg"] = 0.12
            elif "Dầu khí" in ind_name:
                result["isg"] = 0.10
            elif "Basic Materials" in ind_name or "Nguyên vật liệu" in ind_name:
                result["isg"] = 0.06
            elif "Xây dựng" in ind_name or "Bất động sản" in ind_name:
                result["isg"] = 0.04
            else:
                result["isg"] = 0.08
                
        return result
    except Exception:
        return result

# -------------------------------------------------------------------------
# BỘ MÁY PHÂN TÍCH CÂN ĐỐI VỐN VAY & BÓC TÁCH PHẢI THU / TỒN KHO
# -------------------------------------------------------------------------
def calculate_working_capital_and_debt_analysis(data):
    """
    Phân tích Cân đối Nguồn vốn vay ngắn hạn & Bóc tách chất lượng Phải thu / Tồn kho.
    Hỗ trợ kiểm soát sau giải ngân và phát hiện nguy cơ sử dụng vốn vay sai mục đích.
    """
    years = sorted(list(data.keys()))
    analysis_results = {}
    
    for i, year in enumerate(years):
        y_data = data[year]
        prev_data = data[years[i-1]] if i > 0 else None
        
        # 1. Trích xuất chỉ tiêu
        st_debt = y_data.get("Short_Term_Debt")
        if st_debt is None or pd.isna(st_debt):
            st_debt = y_data.get("Short_Term_Borrowings")
        if st_debt is None or pd.isna(st_debt):
            # Nếu chưa có 320 tách biệt, sử dụng Nợ ngắn hạn (310) làm đại diện trần nợ
            st_debt = y_data.get("Current_Liabilities", 0.0) or 0.0
            st_debt_is_proxy = True
        else:
            st_debt_is_proxy = False
            
        rec = y_data.get("Accounts_Receivable")
        if rec is None or pd.isna(rec) or rec == 0:
            rec = y_data.get("Current_Receivables", 0.0) or 0.0
            
        inv = y_data.get("Inventories", 0.0) or 0.0
        payables = y_data.get("Accounts_Payable", 0.0) or 0.0
        sales = y_data.get("Net_Sales", 0.0) or 0.0
        cogs = y_data.get("COGS", 0.0) or 0.0
        ta = y_data.get("Total_Assets", 0.0) or 1.0
        ca = y_data.get("Current_Assets", 0.0) or 0.0
        
        # 2. Cân đối nguồn vốn vay ngắn hạn
        wc_assets = rec + inv # Tài sản hoạt động = Phải thu + Tồn kho
        owc = wc_assets - payables # Nhu cầu vốn lưu động ròng
        
        debt_to_wc_ratio = (st_debt / wc_assets) if wc_assets > 0 else 0.0
        funding_gap = wc_assets - st_debt # Chênh lệch = (Phải thu + Tồn kho) - Vốn vay
        
        # Trạng thái cân đối
        if wc_assets > 0 and st_debt > wc_assets:
            status = "error"
            zone = "🔴 Mất cân đối vốn (Rủi ro cao)"
            diag = "Vay ngắn hạn vượt quá tổng (Phải thu + Tồn kho). Cảnh báo nguy cơ sử dụng vốn vay ngắn hạn để tài trợ tài sản dài hạn hoặc chuyển hướng dòng tiền sai mục đích."
        elif owc > 0 and st_debt > owc:
            status = "warning"
            zone = "🟡 Vùng cảnh báo (Thừa đòn bẩy)"
            diag = "Vay ngắn hạn vượt quá Nhu cầu Vốn lưu động ròng (OWC). Doanh nghiệp phụ thuộc lớn vào vốn vay ngân hàng thay vì tối ưu công nợ nhà cung cấp."
        else:
            status = "success"
            zone = "🟢 Cân đối an toàn"
            diag = "Nguồn vốn vay ngắn hạn được bảo đảm đầy đủ bởi dòng tài sản lưu động hoạt động (Phải thu + Tồn kho)."
            
        warnings = []
        if wc_assets > 0 and st_debt > wc_assets:
            warnings.append(diag)
            
        # 3. Phân tích bóc tách Phải thu, Tồn kho & Phải trả người bán
        dsri = None
        dso = None
        dsi = None
        dpo = None
        operating_cycle = None
        ccc = None
        inv_vs_cogs_spread = None
        payables_vs_cogs_spread = None
        rec_growth = None
        inv_growth = None
        payables_growth = None
        sales_growth = None
        cogs_growth = None
        
        cl_val = y_data.get("Current_Liabilities", 0.0) or 0.0
        
        if prev_data:
            p_rec = prev_data.get("Accounts_Receivable")
            if p_rec is None or pd.isna(p_rec) or p_rec == 0:
                p_rec = prev_data.get("Current_Receivables", 0.0) or 0.0
            p_inv = prev_data.get("Inventories", 0.0) or 0.0
            p_payables = prev_data.get("Accounts_Payable", 0.0) or 0.0
            p_sales = prev_data.get("Net_Sales", 0.0) or 0.0
            p_cogs = prev_data.get("COGS", 0.0) or 0.0
            
            # Tốc độ tăng trưởng
            if p_sales > 0 and sales > 0:
                sales_growth = (sales - p_sales) / p_sales
            if p_cogs > 0 and cogs > 0:
                cogs_growth = (cogs - p_cogs) / p_cogs
            if p_rec > 0 and rec > 0:
                rec_growth = (rec - p_rec) / p_rec
            if p_inv > 0 and inv > 0:
                inv_growth = (inv - p_inv) / p_inv
            if p_payables > 0 and payables > 0:
                payables_growth = (payables - p_payables) / p_payables
                
            # DSRI
            if p_rec > 0 and p_sales > 0 and sales > 0:
                dsri = (rec / sales) / (p_rec / p_sales)
                if dsri > 1.25:
                    warnings.append(f"⚠️ Bất thường Phải thu (DSRI = {dsri:.2f}): Tốc độ tăng phải thu vượt xa doanh thu. Cần rà soát doanh thu ảo hoặc nguy cơ nợ khó đòi.")
                    
            # Inv vs COGS spread
            if inv_growth is not None and cogs_growth is not None:
                inv_vs_cogs_spread = inv_growth - cogs_growth
                if inv_growth > 0.20 and inv_vs_cogs_spread > 0.15:
                    warnings.append(f"⚠️ Tồn kho tăng bất thường (Chênh lệch +{inv_vs_cogs_spread*100:.1f}%): Tồn kho tăng mạnh hơn giá vốn, cảnh báo ứ đọng hàng hoặc chưa kết chuyển giá vốn.")
                    
            # Payables vs COGS spread
            if payables_growth is not None and cogs_growth is not None:
                payables_vs_cogs_spread = payables_growth - cogs_growth
                if payables_growth > 0.30 and payables_vs_cogs_spread > 0.20:
                    warnings.append(f"⚠️ Nợ người bán tăng đột biến (Chênh lệch +{payables_vs_cogs_spread*100:.1f}%): Doanh nghiệp đang chiếm dụng vốn nhà cung cấp lớn hoặc bị chậm thanh toán.")
                    
            # DSO, DSI, DPO
            avg_rec = (rec + p_rec) / 2.0
            avg_inv = (inv + p_inv) / 2.0
            avg_payables = (payables + p_payables) / 2.0 if (payables > 0 or p_payables > 0) else payables
            
            if sales > 0:
                dso = (avg_rec / sales) * 365.0
            if cogs > 0:
                dsi = (avg_inv / cogs) * 365.0
                if avg_payables > 0:
                    dpo = (avg_payables / cogs) * 365.0
                    
            # Chu kỳ hoạt động & Chu kỳ tiền mặt (CCC)
            if dso is not None and dsi is not None:
                operating_cycle = dso + dsi
                if dpo is not None:
                    ccc = operating_cycle - dpo
                else:
                    ccc = operating_cycle # fallback if no payables
                    
                if ccc > 180:
                    warnings.append(f"🚨 Chu kỳ tiền mặt (CCC = {ccc:.0f} ngày) kéo dài nghiêm trọng: Doanh nghiệp bị đọng vốn dài ngày trong chuỗi cung ứng, áp lực thanh khoản rất cao.")
                elif ccc < 0:
                    warnings.append(f"💡 Chu kỳ tiền mặt âm (CCC = {ccc:.0f} ngày): Doanh nghiệp có vị thế thương lượng mạnh, tận dụng vốn chiếm dụng từ nhà cung cấp để tài trợ kinh doanh.")
                
        analysis_results[year] = {
            "st_debt": st_debt,
            "st_debt_is_proxy": st_debt_is_proxy,
            "rec": rec,
            "inv": inv,
            "payables": payables,
            "wc_assets": wc_assets,
            "owc": owc,
            "debt_to_wc_ratio": debt_to_wc_ratio,
            "funding_gap": funding_gap,
            "status": status,
            "zone": zone,
            "diag": diag,
            "warnings": warnings,
            "rec_to_assets": rec / ta if ta > 0 else 0.0,
            "inv_to_assets": inv / ta if ta > 0 else 0.0,
            "payables_to_assets": payables / ta if ta > 0 else 0.0,
            "rec_to_ca": rec / ca if ca > 0 else 0.0,
            "inv_to_ca": inv / ca if ca > 0 else 0.0,
            "payables_to_cl": payables / cl_val if cl_val > 0 else 0.0,
            "dsri": dsri,
            "dso": dso,
            "dsi": dsi,
            "dpo": dpo,
            "operating_cycle": operating_cycle,
            "ccc": ccc,
            "rec_growth": rec_growth,
            "inv_growth": inv_growth,
            "payables_growth": payables_growth,
            "sales_growth": sales_growth,
            "cogs_growth": cogs_growth,
            "inv_vs_cogs_spread": inv_vs_cogs_spread,
            "payables_vs_cogs_spread": payables_vs_cogs_spread
        }
        
    return analysis_results

# -------------------------------------------------------------------------
# BỘ MÁY TÍNH TOÁN CÁC CHỈ SỐ CẢNH BÁO SỚM (EWS ENGINE)
# -------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def calculate_ews(data, firm_age=10, tobin_q=1.2, div_ratio=0.0, isg=0.08, issue=False, ab_return=0.0, unconditional_prob=0.0037, is_listed=1.0):
    """
    Tính toán 10 bộ chỉ số cảnh báo sớm (EWS) toàn diện:
    1. Altman Z'-Score (Kiệt quệ TC)
    2. SA Index (Hạn chế TC quy mô-tuổi)
    3. Beneish M-Score (1999 - 8 biến)
    4. Beneish M-Score (1997 - 12 biến Probit)
    5. Dechow F-Score (2011)
    6. Abnormal CFO (Ab_CFO)
    7. Abnormal Production (Ab_PROD)
    8. Abnormal Discretionary Expenses (Ab_DISEXP)
    9. KZ Index (Kaplan-Zingales)
    10. WW Index (Whited-Wu)
    """
    years = sorted(list(data.keys()))
    ews_results = {}
    
    for i, year in enumerate(years):
        y_data = data[year]
        ews_results[year] = {}
        
        # ------------------ 1. ALTMAN Z'-SCORE (Cho DN tư nhân) ------------------
        ta = y_data.get("Total_Assets", np.nan)
        ca = y_data.get("Current_Assets", np.nan)
        cl = y_data.get("Current_Liabilities", np.nan)
        re = y_data.get("Retained_Earnings", np.nan)
        ebt = y_data.get("EBT", np.nan)
        interest = y_data.get("Interest_Expense", 0) 
        eq = y_data.get("Equity", np.nan)
        liab = y_data.get("Total_Liabilities", np.nan)
        sales = y_data.get("Net_Sales", np.nan)
        
        if not np.isnan([ta, ca, cl, re, ebt, eq, liab, sales]).any() and ta > 0 and liab > 0:
            x1 = (ca - cl) / ta
            x2 = re / ta
            x3 = (ebt + interest) / ta
            x4 = eq / liab
            x5 = sales / ta
            z_prime = 0.717 * x1 + 0.847 * x2 + 3.107 * x3 + 0.420 * x4 + 0.998 * x5
            
            if z_prime > 2.90:
                zone = "🟢 An toàn (Safe Zone)"
                status = "success"
            elif z_prime > 1.23:
                zone = "🟡 Vùng xám (Grey Zone)"
                status = "warning"
            else:
                zone = "🔴 Nguy hiểm (Distress Zone)"
                status = "error"
                
            ews_results[year]["Altman_Z_Prime"] = {
                "score": z_prime,
                "zone": zone,
                "status": status,
                "details": {"X1": x1, "X2": x2, "X3": x3, "X4": x4, "X5": x5}
            }
        else:
            ews_results[year]["Altman_Z_Prime"] = None
            
        # ------------------ 2. SIZE-AGE (SA) INDEX ------------------
        if not np.isnan(ta) and ta > 0:
            # Tỷ giá: 1 USD = 25,000 VND
            ta_usd_m = (ta / 25000.0) / 1000000.0
            size = np.log(ta_usd_m)
            size = min(size, np.log(4500.0))
            age = min(firm_age, 37.0)
            
            sa_idx = -0.737 * size + 0.043 * (size ** 2) - 0.040 * age
            
            if sa_idx > -2.55:
                sa_status = "error"
                sa_zone = "🔴 Hạn chế tài chính cao (SA > -2.55)"
            elif sa_idx > -3.1:
                sa_status = "warning"
                sa_zone = "🟡 Hạn chế tài chính trung bình"
            else:
                sa_status = "success"
                sa_zone = "🟢 Rủi ro thấp"
                
            ews_results[year]["SA_Index"] = {
                "score": sa_idx,
                "zone": sa_zone,
                "status": sa_status,
                "size_used": size,
                "age_used": age
            }
        else:
            ews_results[year]["SA_Index"] = None

            
        # ------------------ CÁC CHỈ SỐ YÊU CẦU DỮ LIỆU CHUỖI THỜI GIAN (t-1) ------------------
        if i > 0:
            prev_year = years[i-1]
            p_data = data[prev_year]
            
            cogs = y_data.get("COGS", np.nan)
            rec = y_data.get("Accounts_Receivable", np.nan)
            cogs_prev = p_data.get("COGS", np.nan)
            sales_prev = p_data.get("Net_Sales", np.nan)
            rec_prev = p_data.get("Accounts_Receivable", np.nan)
            
            fa = y_data.get("Fixed_Assets", np.nan)
            fa_prev = p_data.get("Fixed_Assets", np.nan)
            prev_ca = p_data.get("Current_Assets", np.nan)
            prev_cl = p_data.get("Current_Liabilities", np.nan)
            prev_ta = p_data.get("Total_Assets", np.nan)
            
            ni = y_data.get("Net_Income", np.nan)
            ocf = y_data.get("OCF", np.nan)
            
            required_m = [sales, sales_prev, rec, rec_prev, cogs, cogs_prev, ca, prev_ca, 
                          fa, fa_prev, ta, prev_ta, cl, prev_cl, ni, ocf]
            
            if not any(np.isnan(val) for val in required_m) and sales_prev > 0 and rec_prev > 0 and sales > 0 and prev_ta > 0 and ta > 0:
                # Tính các biến số cơ bản
                dsri = (rec / sales) / (rec_prev / sales_prev)
                gp_margin = (sales - cogs) / sales
                gp_margin_prev = (sales_prev - cogs_prev) / sales_prev
                gmi = gp_margin_prev / gp_margin if gp_margin != 0 else 1.0
                denom_aqi = 1 - (prev_ca + fa_prev) / prev_ta
                aqi = (1 - (ca + fa) / ta) / denom_aqi if denom_aqi != 0 else 1.0
                sgi = sales / sales_prev
                depi = 1.0 
                sga = y_data.get("Selling_Expense", 0) + y_data.get("GA_Expense", 0)
                sga_prev = p_data.get("Selling_Expense", 0) + p_data.get("GA_Expense", 0)
                sgai = (sga / sales) / (sga_prev / sales_prev) if sga_prev > 0 and sales > 0 else 1.0
                lvg = liab / ta
                lvg_prev = p_data.get("Total_Liabilities", np.nan) / prev_ta
                lvgi = lvg / lvg_prev if lvg_prev > 0 else 1.0
                tata = (ni - ocf) / ta
                
                # 3. BENEISH M-SCORE (1999 - 8 biến)
                m_score = -4.84 + 0.920*dsri + 0.528*gmi + 0.404*aqi + 0.892*sgi + 0.115*depi - 0.172*sgai + 4.679*tata - 0.327*lvgi
                
                if m_score > -1.78:
                    m_zone = "🔴 Nguy cơ thao túng cao (M > -1.78)"
                    m_status = "error"
                elif m_score >= -2.22:
                    m_zone = "🟡 Vùng xám nghi vấn (-2.22 <= M <= -1.78)"
                    m_status = "warning"
                else:
                    m_zone = "🟢 Rủi ro thấp (M < -2.22)"
                    m_status = "success"
                    
                ews_results[year]["Beneish_M_Score"] = {
                    "score": m_score,
                    "zone": m_zone,
                    "status": m_status,
                    "details": {"DSRI": dsri, "GMI": gmi, "AQI": aqi, "SGI": sgi, "TATA": tata, "LVGI": lvgi}
                }
                
                # 4. BENEISH M-SCORE (1997 - 12 biến Probit)
                pos_accruals = 1.0 if tata > 0 else 0.0
                dec_cash = 1.0 if sgi < 1.0 and ocf < ni else 0.0
                issue_sec = 1.0 if issue else 0.0
                
                z_12 = -3.5 + 0.920*dsri + 0.528*gmi + 0.404*aqi + 0.892*sgi + 0.115*depi - 0.172*sgai + 4.679*tata - 0.327*lvgi - 0.320*ab_return + 0.35*pos_accruals + 0.25*dec_cash + 0.40*issue_sec
                p_12 = 0.5 * (1.0 + math.erf(z_12 / math.sqrt(2.0)))
                
                if p_12 > 0.0675:
                    p_12_zone = "🔴 Nguy cơ thao túng rất cao (P > 6.75%)"
                    p_12_status = "error"
                elif p_12 > 0.03:
                    p_12_zone = "🟡 Vùng nghi vấn (3.00% < P <= 6.75%)"
                    p_12_status = "warning"
                else:
                    p_12_zone = "🟢 Rủi ro thấp (P <= 3.00%)"
                    p_12_status = "success"
                    
                ews_results[year]["Beneish_M_Score_12"] = {
                    "score": p_12,
                    "zone": p_12_zone,
                    "status": p_12_status,
                    "details": {"Z": z_12, "Abnormal Return": ab_return, "Pos Accruals": pos_accruals, "Dec Cash Sales": dec_cash, "Issue": issue_sec}
                }
                
                # 5. DECHOW F-SCORE (2011)
                wc_t = (ca - y_data.get("Cash_Equivalents", 0)) - cl
                wc_prev = (prev_ca - p_data.get("Cash_Equivalents", 0)) - prev_cl
                nco_t = (ta - ca - fa) - (liab - cl)
                nco_prev = (prev_ta - prev_ca - fa_prev) - (p_data.get("Total_Liabilities", 0) - prev_cl)
                fin_t = y_data.get("Cash_Equivalents", 0) - (liab - cl)
                fin_prev = p_data.get("Cash_Equivalents", 0) - (p_data.get("Total_Liabilities", 0) - prev_cl)
                
                average_ta = 0.5 * (ta + prev_ta)
                rsst_acc = ((wc_t - wc_prev) + (nco_t - nco_prev) + (fin_t - fin_prev)) / average_ta
                ch_rec = (rec - rec_prev) / average_ta
                ch_inv = (y_data.get("Inventories", 0) - p_data.get("Inventories", 0)) / average_ta
                soft_assets = (ta - fa - y_data.get("Cash_Equivalents", 0)) / ta
                
                cash_sales_t = sales - (rec - rec_prev)
                cash_sales_prev = sales_prev - (rec_prev - p_data.get("Accounts_Receivable", 0))
                ch_cs = (cash_sales_t - cash_sales_prev) / cash_sales_prev if cash_sales_prev > 0 else 0.0
                
                roa_t = ni / ta
                roa_prev = p_data.get("Net_Income", 0) / prev_ta
                ch_roa = roa_t - roa_prev
                
                pred_val = -7.893 + 0.790*rsst_acc + 2.518*ch_rec + 1.191*ch_inv + 1.979*soft_assets + 0.171*ch_cs - 0.932*ch_roa + 1.029*(1.0 if issue else 0.0)
                p_dechow = math.exp(pred_val) / (1.0 + math.exp(pred_val))
                f_score = p_dechow / unconditional_prob if unconditional_prob != 0 else 0.0
                
                if f_score > 1.85:
                    f_zone = "🔴 Rủi ro đáng kể (F-Score > 1.85)"
                    f_status = "error"
                elif f_score > 1.0:
                    f_zone = "🟡 Vùng nghi vấn (1.00 < F-Score <= 1.85)"
                    f_status = "warning"
                else:
                    f_zone = "🟢 Rủi ro thấp (F-Score <= 1.00)"
                    f_status = "success"
                    
                ews_results[year]["Dechow_F_Score"] = {
                    "score": f_score,
                    "zone": f_zone,
                    "status": f_status,
                    "details": {"rsst_acc": rsst_acc, "ch_rec": ch_rec, "ch_inv": ch_inv, "soft_assets": soft_assets, "ch_cs": ch_cs, "ch_roa": ch_roa}
                }
                
                # 6. ABNORMAL CFO (Ab_CFO)
                actual_cfo_ratio = ocf / prev_ta
                normal_cfo_ratio = -0.01 * (1.0 / prev_ta) + 0.09 * (sales / prev_ta) - 0.02 * ((sales - sales_prev) / prev_ta)
                ab_cfo = actual_cfo_ratio - normal_cfo_ratio
                
                if ab_cfo < -0.05:
                    cfo_status = "error"
                    cfo_zone = "🔴 Dòng tiền thấp bất thường (Ab_CFO < -0.05)"
                elif ab_cfo < 0.0:
                    cfo_status = "warning"
                    cfo_zone = "🟡 Dưới mức bình thường nhẹ"
                else:
                    cfo_status = "success"
                    cfo_zone = "🟢 An toàn"
                    
                ews_results[year]["Abnormal_CFO"] = {
                    "score": ab_cfo,
                    "zone": cfo_zone,
                    "status": cfo_status,
                    "details": {"Actual": actual_cfo_ratio, "Normal": normal_cfo_ratio}
                }
                
                # 7. ABNORMAL PRODUCTION (Ab_PROD)
                inv_diff = y_data.get("Inventories", 0) - p_data.get("Inventories", 0)
                prod = cogs + inv_diff
                actual_prod_ratio = prod / prev_ta
                
                lag_delta_sales = 0.0
                if i > 1:
                    prev_year_2 = years[i-2]
                    p_data_2 = data[prev_year_2]
                    sales_prev_2 = p_data_2.get("Net_Sales", 0)
                    lag_delta_sales = sales_prev - sales_prev_2
                else:
                    lag_delta_sales = sales - sales_prev
                    
                normal_prod_ratio = 0.03 * (1.0 / prev_ta) + 0.82 * (sales / prev_ta) + 0.12 * ((sales - sales_prev) / prev_ta) - 0.05 * (lag_delta_sales / prev_ta)
                ab_prod = actual_prod_ratio - normal_prod_ratio
                
                if ab_prod > 0.05:
                    prod_status = "error"
                    prod_zone = "🔴 Chi phí sản xuất cao bất thường (Ab_PROD > 0.05)"
                elif ab_prod > 0.0:
                    prod_status = "warning"
                    prod_zone = "🟡 Vượt mức bình thường nhẹ"
                else:
                    prod_status = "success"
                    prod_zone = "🟢 An toàn"
                    
                ews_results[year]["Abnormal_PROD"] = {
                    "score": ab_prod,
                    "zone": prod_zone,
                    "status": prod_status,
                    "details": {"Actual": actual_prod_ratio, "Normal": normal_prod_ratio}
                }
                
                # 8. ABNORMAL DISEXP (Ab_DISEXP)
                actual_disexp_ratio = sga / prev_ta
                normal_disexp_ratio = 0.01 * (1.0 / prev_ta) + 0.06 * (sales_prev / prev_ta)
                ab_disexp = actual_disexp_ratio - normal_disexp_ratio
                
                if ab_disexp < -0.03:
                    disexp_status = "error"
                    disexp_zone = "🔴 Chi phí hoạt động thấp bất thường (Ab_DISEXP < -0.03)"
                elif ab_disexp < 0.0:
                    disexp_status = "warning"
                    disexp_zone = "🟡 Dưới mức bình thường nhẹ"
                else:
                    disexp_status = "success"
                    disexp_zone = "🟢 An toàn"
                    
                ews_results[year]["Abnormal_DISEXP"] = {
                    "score": ab_disexp,
                    "zone": disexp_zone,
                    "status": disexp_status,
                    "details": {"Actual": actual_disexp_ratio, "Normal": normal_disexp_ratio}
                }
                
                # 9. KZ INDEX (Kaplan-Zingales)
                k_val = fa_prev if fa_prev > 0 else prev_ta
                cf_val = ni + 0.05 * fa if fa > 0 else ni
                debt_val = liab
                div_val = div_ratio * ni if ni > 0 else 0.0
                cash_val = y_data.get("Cash_Equivalents", 0)
                
                kz_score = -1.002 * (cf_val / k_val) + 0.283 * tobin_q + 3.139 * (debt_val / k_val) - 39.368 * (div_val / k_val) - 1.315 * (cash_val / k_val)
                
                if kz_score > 3.0:
                    kz_status = "error"
                    kz_zone = "🔴 Hạn chế tài chính cao (KZ > 3.0)"
                elif kz_score > 1.5:
                    kz_status = "warning"
                    kz_zone = "🟡 Hạn chế tài chính trung bình"
                else:
                    kz_status = "success"
                    kz_zone = "🟢 Rủi ro thấp"
                    
                ews_results[year]["KZ_Index"] = {
                    "score": kz_score,
                    "zone": kz_zone,
                    "status": kz_status,
                    "details": {"CF/K": cf_val/k_val, "Tobin Q": tobin_q, "Debt/K": debt_val/k_val, "Div/K": div_val/k_val, "Cash/K": cash_val/k_val}
                }
                
                # 10. WW INDEX (Whited-Wu)
                cf_ww = cf_val / ta
                divpos_val = 1.0 if div_val > 0 else 0.0
                tltd_val = (liab - cl) / ta
                lnta_val = math.log(max(ta / 25000.0 / 1e6, 1e-3))
                sg_val = (sales / sales_prev) - 1.0
                
                ww_score = -0.091 * cf_ww - 0.062 * divpos_val + 0.021 * tltd_val - 0.044 * lnta_val + 0.102 * isg - 0.035 * sg_val
                
                if ww_score > -0.2:
                    ww_status = "error"
                    ww_zone = "🔴 Hạn chế tài chính cao (WW > -0.2)"
                elif ww_score > -0.4:
                    ww_status = "warning"
                    ww_zone = "🟡 Hạn chế tài chính trung bình"
                else:
                    ww_status = "success"
                    ww_zone = "🟢 Rủi ro thấp"
                    
                ews_results[year]["WW_Index"] = {
                    "score": ww_score,
                    "zone": ww_zone,
                    "status": ww_status,
                    "details": {"CF/TA": cf_ww, "DIVPOS": divpos_val, "TLTD": tltd_val, "LNTA": lnta_val, "ISG": isg, "SG": sg_val}
                }
                
                # 11. CUSTOM MACHINE LEARNING PREDICTION (Vietnam Custom Model)
                try:
                    pkg = load_cached_ml_model("best_ews_model.joblib")
                    if pkg is not None:
                        clf = pkg["model"]
                        scaler = pkg["scaler"]
                        
                        feat_dict = {
                            'z_prime': z_prime,
                            'sa_idx': sa_idx,
                            'm_score': m_score,
                            'p_12': p_12,
                            'f_score': f_score,
                            'ab_cfo': ab_cfo,
                            'ab_prod': ab_prod,
                            'ab_disexp': ab_disexp,
                            'kz_score': kz_score,
                            'ww_score': ww_score,
                            'x1': x1,
                            'x2': x2,
                            'x3': x3,
                            'x4': x4,
                            'x5': x5,
                            'dsri': dsri,
                            'gmi': gmi,
                            'aqi': aqi,
                            'sgi': sgi,
                            'sgai': sgai,
                            'lvgi': lvgi,
                            'tata': tata,
                            'pos_accruals': pos_accruals,
                            'dec_cash': dec_cash,
                            'rsst_acc': rsst_acc,
                            'ch_rec': ch_rec,
                            'ch_inv': ch_inv,
                            'soft_assets': soft_assets,
                            'ch_cs': ch_cs,
                            'ch_roa': ch_roa,
                            'actual_cfo_ratio': actual_cfo_ratio,
                            'actual_prod_ratio': actual_prod_ratio,
                            'actual_disexp_ratio': actual_disexp_ratio,
                            'size': size,
                            'capped_age': age,
                            'is_listed': float(is_listed),
                            'issue': float(issue_sec)
                        }
                        
                        X_pred = np.array([[feat_dict[f] for f in pkg["features"]]])
                        if scaler:
                            X_pred_scaled = scaler.transform(X_pred)
                            prob_fraud = clf.predict_proba(X_pred_scaled)[0, 1]
                        else:
                            prob_fraud = clf.predict_proba(X_pred)[0, 1]
                            
                        if prob_fraud > 0.5:
                            ml_zone = "🔴 Nguy cơ thao túng Rất Cao (ML > 50%)"
                            ml_status = "error"
                        elif prob_fraud > 0.2:
                            ml_zone = "🟡 Nghi vấn cần giám sát (ML 20% - 50%)"
                            ml_status = "warning"
                        else:
                            ml_zone = "🟢 Rủi ro thấp (ML < 20%)"
                            ml_status = "success"
                            
                        ews_results[year]["Custom_ML_Fraud"] = {
                            "score": prob_fraud,
                            "zone": ml_zone,
                            "status": ml_status
                        }
                    else:
                        ews_results[year]["Custom_ML_Fraud"] = None
                except Exception as e:
                    print(f"Error predicting custom ML: {e}")
                    ews_results[year]["Custom_ML_Fraud"] = None
                    
            else:
                ews_results[year]["Beneish_M_Score"] = None
                ews_results[year]["Beneish_M_Score_12"] = None
                ews_results[year]["Dechow_F_Score"] = None
                ews_results[year]["Abnormal_CFO"] = None
                ews_results[year]["Abnormal_PROD"] = None
                ews_results[year]["Abnormal_DISEXP"] = None
                ews_results[year]["KZ_Index"] = None
                ews_results[year]["WW_Index"] = None
                ews_results[year]["Custom_ML_Fraud"] = None
        else:
            ews_results[year]["Beneish_M_Score"] = None
            ews_results[year]["Beneish_M_Score_12"] = None
            ews_results[year]["Dechow_F_Score"] = None
            ews_results[year]["Abnormal_CFO"] = None
            ews_results[year]["Abnormal_PROD"] = None
            ews_results[year]["Abnormal_DISEXP"] = None
            ews_results[year]["KZ_Index"] = None
            ews_results[year]["WW_Index"] = None
            ews_results[year]["Custom_ML_Fraud"] = None
            
    return ews_results

# -------------------------------------------------------------------------
# HÀM TRÍCH XUẤT THÔNG TIN TÓM TẮT (METADATA) TỪ BCTC
# -------------------------------------------------------------------------
def _find_metadata_in_text(text, default_ticker="N/A"):
    company_name = "N/A"
    ticker = default_ticker
    
    # Pattern quoc hieu Viet Nam - thuong bi OCR ghep nham vao cung dong ten cong ty
    _STATE_MOTTO_RE = re.compile(
        r'cong\s*hoa\s*xa\s*hoi|xa\s*hoi\s*chu\s*nghia|doc\s*lap\s*tu\s*do|hanh\s*phuc',
        re.IGNORECASE
    )
    
    if text.strip():
        lines_text = text.split('\n')
        for line in lines_text:
            line_s = strip_accents(line).upper()
            match = re.search(r'\b(CONG\s+TY\s+(?:CO\s+PHAN|TNHH|TRACH\s+NHIEM\s+HUU\s+HAN)|TAP\s+DOAN)\s+([A-Z0-9\s_-]+)', line_s)
            if match:
                raw_name = line[match.start():].strip() if match.start() > 0 else line.strip()
                company_name = re.sub(r'^[=\]\[|\~¬\*\-_\/\\:;0-9\s]+', '', raw_name).strip()
                company_name = re.split(r'(?:Mẫu|Mau|B\s*0)\b', company_name, flags=re.IGNORECASE)[0].strip()
                company_name = company_name.rstrip('- :|/,')
                
                # Fix: Cat bo quoc hieu neu OCR ghep nham vao cung dong ten cong ty
                name_no_accent = strip_accents(company_name).lower()
                m_state = _STATE_MOTTO_RE.search(name_no_accent)
                if m_state:
                    company_name = company_name[:m_state.start()].strip().rstrip('- :|/,')
                
                # Neu sau khi cat, ten con qua ngan (chi "Cong Ty Co Phan" khong ten thuc), bo qua
                remaining = re.sub(
                    r'^(?:cong ty co phan|cong ty tnhh|tap doan|cong ty trach nhiem huu han)\s*',
                    '', strip_accents(company_name).lower()
                ).strip()
                if len(remaining) < 3:
                    company_name = "N/A"
                    continue  # Thu dong tiep theo
                
                company_name = re.sub(r'\s+[^a-zA-Z0-9]$', '', company_name)
                company_name = re.sub(r'\s+[a-zA-Z\u00C0-\u1EF9]$', '', company_name)
                company_name = company_name.strip()
                break
                
        if ticker == "N/A":
            text_s = strip_accents(text)
            match = re.search(r'(ma\s+giao\s+dich\s+co\s+phieu\s+la|ma\s+chung\s+khoan|ma\s+giao\s+dich)\s+["\'\u201c]??([A-Z]{3,4})["\'\u201d]??', text_s, re.IGNORECASE)
            if match:
                ticker = match.group(2).upper()
                
    return company_name, ticker

@st.cache_data(show_spinner="Đang đọc metadata từ PDF...")
def extract_metadata_from_pdf(file_bytes, filename):
    company_name = "N/A"
    ticker = "N/A"
    
    # 1. Trích xuất mã chứng khoán từ tên file (Ví dụ: HSG-BCTC-2024.pdf -> HSG)
    fn_clean = re.sub(r'[^a-zA-Z0-9\s_-]', '', filename)
    fn_tokens = re.split(r'[\s_.-]', fn_clean)
    for tok in fn_tokens:
        if len(tok) in [3, 4] and tok.isupper() and tok.isalpha() and tok not in ["BCTC", "PDF", "XLS", "XLSX"]:
            ticker = tok
            break
            
    # 2. Đọc lướt 3 trang đầu tiên bằng pdfplumber
    first_pages_text = ""
    try:
        pdf_file = io.BytesIO(file_bytes)
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages[:3]:
                first_pages_text += page.extract_text() or ""
    except Exception:
        pass
        
    if first_pages_text.strip():
        company_name, ticker = _find_metadata_in_text(first_pages_text, ticker)
        
    # 3. Nếu là PDF quét hoặc không trích xuất được tên công ty, dùng OCR cho 2 trang đầu để lấy text tìm Metadata
    if company_name == "N/A":
        try:
            import fitz
            import pytesseract
            from PIL import Image
            if sys.platform == "win32":
                win_tesseract = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
                if os.path.exists(win_tesseract):
                    pytesseract.pytesseract.tesseract_cmd = win_tesseract
            else:
                mac_tesseract = '/opt/anaconda3/bin/tesseract'
                if os.path.exists(mac_tesseract):
                    pytesseract.pytesseract.tesseract_cmd = mac_tesseract
            doc = fitz.open(stream=io.BytesIO(file_bytes), filetype="pdf")
            ocr_text = ""
            for i in range(min(2, len(doc))):
                page = doc[i]
                mat = fitz.Matrix(150 / 72, 150 / 72)
                pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                text = pytesseract.image_to_string(img, lang='vie+eng', config='--psm 6')
                ocr_text += text + "\n"
            if ocr_text.strip():
                company_name, ticker = _find_metadata_in_text(ocr_text, ticker)
        except Exception:
            pass
            
    return clean_company_name(company_name, ticker), ticker

@st.cache_data(show_spinner="Đang đọc metadata từ Excel...")
def extract_metadata_from_excel(file_bytes, filename):
    company_name = "N/A"
    ticker = "N/A"
    
    # 1. Trích xuất mã chứng khoán từ tên file
    fn_clean = re.sub(r'[^a-zA-Z0-9\s_-]', '', filename)
    fn_tokens = re.split(r'[\s_.-]', fn_clean)
    for tok in fn_tokens:
        if len(tok) in [3, 4] and tok.isupper() and tok.isalpha() and tok not in ["BCTC", "PDF", "XLS", "XLSX"]:
            ticker = tok
            break
            
    # 2. Tìm tên công ty trong các ô của sheet đầu tiên
    try:
        xls = pd.ExcelFile(io.BytesIO(file_bytes))
        df = pd.read_excel(xls, sheet_name=xls.sheet_names[0])
        for r in range(min(20, len(df))):
            for c in range(min(5, len(df.columns))):
                val = str(df.iloc[r, c]).strip()
                val_s = strip_accents(val).upper()
                if any(p in val_s for p in ["CONG TY CO PHAN", "CONG TY TNHH", "TAP DOAN"]):
                    company_name = val
                    company_name = re.split(r'(?:Mẫu|Mau|B\s*0)\b', company_name, flags=re.IGNORECASE)[0].strip()
                    company_name = company_name.rstrip('- :|/,')
                    break
            if company_name != "N/A":
                break
    except Exception:
        pass
        
    return clean_company_name(company_name, ticker), ticker

# -------------------------------------------------------------------------
# GIAO DIỆN CHÍNH ỨNG DỤNG STREAMLIT
# -------------------------------------------------------------------------
st.title("🛡️ FinTrust - Hệ thống Đánh giá Rủi ro Thông qua Phân tích Tài chính từ BCTC")
st.caption("Financial Statement Risk & Early Warning System (EWS) - Công cụ định lượng hỗ trợ nhận diện sớm rủi ro tài chính, bất thường dòng tiền và dấu hiệu thao túng BCTC")

# Cấu hình thanh bên (Sidebar)
st.sidebar.title("🛡️ FinTrust EWS Engine")
app_mode = st.sidebar.radio("Chức năng hệ thống:", ["🔍 Đánh giá rủi ro tài chính BCTC", "🎛️ Tái ước lượng đòn bẩy (U-Curve)"])
st.sidebar.markdown("---")

from quarterly_leverage_updater import (
    check_and_auto_update_if_due,
    load_scheduler_config,
    save_scheduler_config,
    execute_quarterly_update
)

# Tự động kiểm tra chu kỳ cập nhật quý khi khởi động ứng dụng (chạy 1 lần/phiên)
if "quarterly_auto_checked" not in st.session_state:
    st.session_state["quarterly_auto_checked"] = True
    check_and_auto_update_if_due()

def render_u_curve_workspace():
    st.title("🎛️ Tái ước lượng Ngưỡng Đòn bẩy Tối ưu (U-Curve Regression)")
    st.markdown("""
    Công cụ này cho phép chạy hồi quy Panel OLS bậc hai ($Z' = \\beta_0 + \\beta_1 LEV + \\beta_2 LEV^2$) theo 5 nhóm ngành phi tài chính chuẩn 
    nhằm xác định điểm đòn bẩy tối ưu nơi rủi ro kiệt quệ tài chính là thấp nhất.
    
    Hệ thống hỗ trợ cả chế độ **Tự động Cập nhật Định kỳ (1 Quý / 1 Lần)** và **Ước lượng Thủ công** theo nhu cầu.
    """)
    
    # 1. Quản lý Lập lịch Tự động Cập nhật Định kỳ (1 Quý / 1 Lần)
    st.subheader("⏰ Quản lý Tự động Cập nhật Định kỳ (1 Quý / 1 Lần)")
    sched_cfg = load_scheduler_config()
    
    col_s1, col_s2, col_s3, col_s4 = st.columns(4)
    with col_s1:
        st.metric(
            label="Trạng thái tự động",
            value="🟢 Đang BẬT" if sched_cfg.get("auto_update_enabled", True) else "🔴 Đang TẮT",
            delta="Chu kỳ 90 ngày / 1 Quý"
        )
    with col_s2:
        last_run_display = sched_cfg.get("last_run", "Chưa chạy")
        st.metric(
            label="Lần cập nhật gần nhất",
            value=last_run_display.split()[0] if last_run_display != "Chưa chạy" else "Chưa chạy",
            delta=sched_cfg.get("last_status", "N/A")
        )
    with col_s3:
        next_run_display = sched_cfg.get("next_run", "Chưa đặt lịch")
        st.metric(
            label="Lần cập nhật kế tiếp",
            value=next_run_display.split()[0] if next_run_display != "Chưa đặt lịch" else "Chưa đặt lịch",
            delta="Tự động tái ước lượng"
        )
    with col_s4:
        st.metric(
            label="Tự động áp dụng",
            value="✅ Bật" if sched_cfg.get("auto_apply_thresholds", True) else "⚠️ Thủ công",
            delta="Ghi đè industry_opt_lev.json"
        )
        
    with st.expander("⚙️ Cấu hình & Điều khiển Chu kỳ Cập nhật Quý", expanded=False):
        c_cfg1, c_cfg2 = st.columns(2)
        with c_cfg1:
            enable_auto = st.checkbox(
                "Bật tính năng Tự động Cập nhật Định kỳ (1 Quý / 1 Lần)",
                value=sched_cfg.get("auto_update_enabled", True),
                key="sched_enable_auto"
            )
            auto_apply = st.checkbox(
                "Tự động áp dụng các ngưỡng mới vào hệ thống EWS",
                value=sched_cfg.get("auto_apply_thresholds", True),
                key="sched_auto_apply"
            )
            if st.button("💾 Lưu Cài đặt Lịch trình"):
                sched_cfg["auto_update_enabled"] = enable_auto
                sched_cfg["auto_apply_thresholds"] = auto_apply
                save_scheduler_config(sched_cfg)
                st.success("✅ Đã lưu cấu hình tự động cập nhật quý!")
                st.rerun()
                
        with c_cfg2:
            st.info("💡 Bạn có thể kích hoạt chu kỳ cập nhật quý ngay tức thì mà không cần đợi đến hạn 90 ngày.")
            if st.button("🚀 Kích hoạt Cập nhật Chu kỳ Quý Ngay (Force Run Now)"):
                with st.spinner("Đang thực thi tái ước lượng đòn bẩy tối ưu toàn diện theo dữ liệu Panel..."):
                    success, msg, results = execute_quarterly_update(force=True)
                    if success:
                        st.success(f"🎉 {msg}")
                        st.rerun()
                    else:
                        st.error(f"❌ Cập nhật thất bại: {msg}")

        # Lịch sử kiểm toán các kỳ cập nhật
        history_list = sched_cfg.get("history", [])
        if history_list:
            st.markdown("#### 📜 Nhật ký lịch sử các kỳ cập nhật (Quarterly Audit Log)")
            hist_rows = []
            for h in history_list:
                applied = h.get("applied_thresholds", {})
                hist_rows.append({
                    "Thời gian": h.get("timestamp"),
                    "Kỳ tài chính": h.get("quarter"),
                    "Tệp dữ liệu": h.get("file_used"),
                    "Nguyên vật liệu": f"{applied.get('Basic Materials (Nguyên vật liệu)', 0):.2%}" if applied.get('Basic Materials (Nguyên vật liệu)') else "N/A",
                    "Hàng tiêu dùng": f"{applied.get('Consumer Goods (Hàng tiêu dùng)', 0):.2%}" if applied.get('Consumer Goods (Hàng tiêu dùng)') else "N/A",
                    "Công nghiệp": f"{applied.get('Industrials (Công nghiệp)', 0):.2%}" if applied.get('Industrials (Công nghiệp)') else "N/A",
                    "Dầu khí": f"{applied.get('Oil & Gas (Dầu khí)', 0):.2%}" if applied.get('Oil & Gas (Dầu khí)') else "N/A",
                    "Công nghệ": f"{applied.get('Technology (Công nghệ)', 0):.2%}" if applied.get('Technology (Công nghệ)') else "N/A"
                })
            st.dataframe(pd.DataFrame(hist_rows), use_container_width=True, hide_index=True)

    st.markdown("---")

    # 2. Hiển thị các ngưỡng hiện tại
    st.subheader("📋 Các ngưỡng đòn bẩy tối ưu hiện tại của hệ thống")
    config_file = os.path.join(BASE_DIR, "industry_opt_lev.json")
    default_opt_lev = {
        "Basic Materials (Nguyên vật liệu)": 0.7450,
        "Consumer Goods (Hàng tiêu dùng)": 0.5201,
        "Industrials (Công nghiệp)": 0.3989,
        "Oil & Gas (Dầu khí)": 1.1176,
        "Technology (Công nghệ)": 0.4441
    }
    
    if os.path.exists(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                current_opt_lev = json.load(f)
        except Exception:
            current_opt_lev = default_opt_lev
    else:
        current_opt_lev = default_opt_lev
        
    df_current = pd.DataFrame([
        {"Ngành": k, "Đòn bẩy tối ưu (Ngưỡng hiện tại)": f"{v:.2%}" if pd.notna(v) and v is not None else "N/A"} 
        for k, v in current_opt_lev.items()
    ])
    st.table(df_current)
    
    # 3. Tải lên tệp dữ liệu Panel để ước lượng thủ công
    st.subheader("📥 Ước lượng Thủ công bằng Tệp Dữ liệu Panel Riêng")
    uploaded_panel = st.file_uploader(
        "Tải lên tệp dữ liệu tài chính (Excel hoặc CSV) chứa thông tin nhiều năm", 
        type=["xlsx", "xls", "csv"], 
        key="uploaded_panel"
    )
    
    if uploaded_panel:
        st.info("💡 Tệp dữ liệu cần có các cột chỉ tiêu tài chính chuẩn như Mã chứng khoán, Total_Assets, Total_Liabilities...")
        
        # Thêm nút bấm chạy hồi quy
        if st.button("🚀 Chạy hồi quy Panel OLS (U-Curve)"):
            with st.spinner("Đang xử lý dữ liệu, ánh xạ ngành và chạy hồi quy..."):
                STORAGE_DIR = os.path.join(BASE_DIR, "storage")
                if not os.path.exists(STORAGE_DIR):
                    os.makedirs(STORAGE_DIR)
                temp_path = os.path.join(STORAGE_DIR, f"temp_panel_{datetime.datetime.now().timestamp()}.xlsx" if uploaded_panel.name.endswith(('.xlsx', '.xls')) else "temp_panel.csv")
                with open(temp_path, "wb") as f:
                    f.write(uploaded_panel.read())
                    
                try:
                    from u_curve_regression import process_and_run_regressions
                    reg_results = process_and_run_regressions(temp_path)
                    
                    if not reg_results:
                        st.warning("⚠️ Không tìm thấy ngành nào đủ điều kiện hồi quy (tối thiểu 15 quan sát).")
                    else:
                        st.success("🎉 Đã hoàn thành hồi quy Panel OLS!")
                        
                        # Hiển thị kết quả so sánh
                        comparison_rows = []
                        new_thresholds = {}
                        
                        for ind, res in reg_results.items():
                            old_val = current_opt_lev.get(ind, np.nan)
                            new_val = res['opt_lev']
                            new_thresholds[ind] = new_val if not np.isnan(new_val) else old_val
                            
                            comparison_rows.append({
                                "Ngành": ind,
                                "Số mẫu (N)": res['n'],
                                "Ngưỡng cũ": f"{old_val:.2%}" if not np.isnan(old_val) else "N/A",
                                "Ngưỡng ước lượng mới": f"{new_val:.2%}" if not np.isnan(new_val) else "Không xác định (Convex)",
                                "R-squared": f"{res['r2']:.4f}",
                                "P-value (Hệ số LEV^2)": f"{res['p_b2']:.4f}"
                            })
                            
                        st.subheader("📊 Kết quả so sánh ngưỡng tối ưu")
                        st.dataframe(pd.DataFrame(comparison_rows), use_container_width=True, hide_index=True)
                        
                        # Cho phép lưu ngưỡng mới
                        st.session_state["new_thresholds_to_save"] = {k: float(v) for k, v in new_thresholds.items() if not np.isnan(v)}
                        
                        # Vẽ đồ thị cho từng ngành
                        st.subheader("📈 Đồ thị đường cong chữ U (U-Curve Plots)")
                        import matplotlib.pyplot as plt
                        
                        for ind, res in reg_results.items():
                            fig, ax = plt.subplots(figsize=(8, 4))
                            
                            # Dữ liệu thực tế
                            ax.scatter(res['lev_data'], res['z_data'], alpha=0.3, color='blue', label='Dữ liệu thực tế')
                            
                            # Đường hồi quy fitted
                            x_line = np.linspace(0, 1, 100)
                            y_line = res['b0'] + res['b1'] * x_line + res['b2'] * (x_line ** 2)
                            ax.plot(x_line, y_line, color='red', linewidth=2, label='Đường hồi quy fitted')
                            
                            # Đánh dấu đỉnh tối ưu
                            opt = res['opt_lev']
                            if not np.isnan(opt) and 0 < opt < 1:
                                opt_y = res['b0'] + res['b1'] * opt + res['b2'] * (opt ** 2)
                                ax.axvline(x=opt, color='green', linestyle='--', label=f'Đòn bẩy tối ưu: {opt:.2%}')
                                ax.scatter([opt], [opt_y], color='green', s=100, zorder=5)
                                
                            ax.set_title(f"Đường cong U-Curve - Ngành {ind} (N={res['n']})")
                            ax.set_xlabel("Tỷ lệ Nợ / Tổng tài sản (Leverage)")
                            ax.set_ylabel("Altman Z'-Score")
                            ax.set_xlim(0, 1)
                            ax.grid(True, alpha=0.3)
                            ax.legend()
                            
                            st.pyplot(fig)
                            plt.close(fig)
                            
                except Exception as ex:
                    st.error(f"❌ Đã xảy ra lỗi khi chạy hồi quy: {ex}")
                finally:
                    # Clean up temp file
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                        
        # Nút bấm lưu kết quả
        if "new_thresholds_to_save" in st.session_state and st.session_state["new_thresholds_to_save"]:
            st.markdown("---")
            st.info("👉 Bạn có thể chọn áp dụng các ngưỡng đòn bẩy tối ưu mới ước lượng này cho toàn hệ thống.")
            if st.button("💾 Xác nhận: Áp dụng các ngưỡng tối ưu mới"):
                try:
                    updated_config = current_opt_lev.copy()
                    updated_config.update(st.session_state["new_thresholds_to_save"])
                    
                    with open(config_file, "w", encoding="utf-8") as f:
                        json.dump(updated_config, f, indent=4, ensure_ascii=False)
                    st.success("✅ Đã cập nhật thành công các ngưỡng đòn bẩy tối ưu ngành mới vào hệ thống!")
                    st.session_state.pop("new_thresholds_to_save", None)
                    st.rerun()
                except Exception as ex:
                    st.error(f"Không thể lưu tệp cấu hình: {ex}")

if app_mode == "🎛️ Tái ước lượng đòn bẩy (U-Curve)":
    render_u_curve_workspace()
    st.stop()

st.sidebar.header("⚙️ Nhập liệu BCTC")

# Thư mục lưu trữ cục bộ để cache hồ sơ doanh nghiệp
STORAGE_DIR = os.path.join(BASE_DIR, "storage")
if not os.path.exists(STORAGE_DIR):
    os.makedirs(STORAGE_DIR)

# Khởi tạo db và thực hiện di cư dữ liệu cũ
init_db()
migrate_json_to_sqlite(STORAGE_DIR)

# Wrapper có cache cho load_from_db để tránh đọc SQLite lại trên mỗi rerun
@st.cache_data(ttl=300, show_spinner=False)
def load_from_db_cached(ticker):
    return load_from_db(ticker)


# Lấy danh sách hồ sơ đã lưu từ SQLite và nạp dữ liệu trước
saved_profiles_db = get_saved_tickers_from_db()
saved_profiles = [f"{ticker} - {name}" for ticker, name in saved_profiles_db]

profile_options = ["Tải file mới"] + saved_profiles

curr_profile_idx = 0
if "active_profile" in st.session_state and st.session_state["active_profile"] in profile_options:
    curr_profile_idx = profile_options.index(st.session_state["active_profile"])

selected_profile = st.sidebar.selectbox("📂 Chọn hồ sơ đã lưu", profile_options, index=curr_profile_idx, key="sidebar_selected_profile")

if selected_profile != "Tải file mới":
    st.session_state["active_profile"] = selected_profile

# Khởi tạo dữ liệu từ profile đã chọn để làm giá trị mặc định cho sidebar
db_extracted_data = {}
db_tickers_detected = set()
db_company_names_detected = set()

default_words = 15000
default_risk = 0.5
default_neg = 0.5
default_sim = 0.65
default_is_bds = False
default_ceo_age = 55
default_industry = st.session_state.get("wizard_selected_industry", "Khác / Mặc định")

if selected_profile != "Tải file mới":
    try:
        selected_ticker = selected_profile.split(" - ")[0]
        c_name, db_financial_data = load_from_db_cached(selected_ticker)
        if db_financial_data:
            db_extracted_data = {int(year): val for year, val in db_financial_data.items()}
            db_tickers_detected = {selected_ticker}
            db_company_names_detected = {c_name}
            
            # Đọc các giá trị định tính đã lưu từ năm mới nhất
            latest_y = max(db_extracted_data.keys())
            if "Qual_RiskWord" in db_extracted_data[latest_y]:
                default_risk = db_extracted_data[latest_y]["Qual_RiskWord"]
            if "Qual_NegTone" in db_extracted_data[latest_y]:
                default_neg = db_extracted_data[latest_y]["Qual_NegTone"] * 100.0
            if "Qual_ReportLen" in db_extracted_data[latest_y]:
                default_words = db_extracted_data[latest_y]["Qual_ReportLen"]
            if "Qual_TextSim" in db_extracted_data[latest_y]:
                default_sim = db_extracted_data[latest_y]["Qual_TextSim"]
            if "Qual_IsBDS" in db_extracted_data[latest_y]:
                default_is_bds = bool(db_extracted_data[latest_y]["Qual_IsBDS"])
            if "Qual_CEOAge" in db_extracted_data[latest_y]:
                default_ceo_age = int(db_extracted_data[latest_y]["Qual_CEOAge"])
            if "Qual_Industry" in db_extracted_data[latest_y]:
                default_industry = str(db_extracted_data[latest_y]["Qual_Industry"])
    except Exception as e:
        st.sidebar.error(f"Lỗi nạp dữ liệu SQLite: {e}")

uploaded_files_raw = st.sidebar.file_uploader("Tải lên một hoặc nhiều file BCTC (Excel hoặc PDF)", type=["xlsx", "xls", "pdf"], accept_multiple_files=True)
uploaded_files = list(uploaded_files_raw) if uploaded_files_raw else []
if "uploaded_from_main" in st.session_state and st.session_state["uploaded_from_main"]:
    uploaded_files.extend(st.session_state["uploaded_from_main"])

# Hướng dẫn OCR & Lưu ý chất lượng file
with st.sidebar.expander("ℹ️ Lưu ý chất lượng file & PDF quét ảnh"):
    st.info(
        "📌 **Lưu ý về độ chính xác trích xuất:**\n"
        "- **File Excel (.xlsx) / PDF Text (gốc)**: Độ chính xác 100% do đọc trực tiếp số liệu nhúng và mã số kế toán.\n"
        "- **File PDF Scan (ảnh chụp/quét mờ)**: Dữ liệu được nhận diện qua OCR (chính xác ~75–90%). Các trường hợp bị mờ, nghiêng, watermark đè chữ hoặc bảng lệch cột có thể dẫn đến ô **N/A** (thiếu số liệu).\n\n"
        "🛠️ **Cài đặt Tesseract OCR cho PDF Scan:**\n"
        "1. **Windows**: [Tải Tesseract (.exe)](https://github.com/UB-Mannheim/tesseract/wiki) và cài vào `C:\\Program Files\\Tesseract-OCR`.\n"
        "2. **macOS**: Chạy `brew install tesseract tesseract-lang` trong Terminal."
    )

# Cấu hình Tuổi doanh nghiệp để tính SA Index
st.sidebar.markdown("---")
st.sidebar.subheader("🏢 Thông tin Doanh nghiệp")
is_above_10 = st.sidebar.checkbox("Doanh nghiệp hoạt động >= 10 năm", value=True)
if is_above_10:
    firm_age_input = st.sidebar.number_input("Tuổi doanh nghiệp (năm)", min_value=10, max_value=100, value=10, step=1, help="Số năm hoạt động thực tế từ khi thành lập")
else:
    firm_age_input = st.sidebar.number_input("Tuổi doanh nghiệp (năm)", min_value=1, max_value=9, value=5, step=1, help="Số năm hoạt động thực tế từ khi thành lập")

industry_options = ["Khác / Mặc định", "Basic Materials (Nguyên vật liệu)", "Consumer Goods (Hàng tiêu dùng)", "Industrials (Công nghiệp)", "Oil & Gas (Dầu khí)", "Technology (Công nghệ)"]
default_ind_idx = 0
if default_industry in industry_options:
    default_ind_idx = industry_options.index(default_industry)
industry_input = st.sidebar.selectbox("Ngành hoạt động chính", industry_options, index=default_ind_idx, help="Ngành hoạt động chính để áp dụng đòn bẩy tối ưu theo sheet Chạy chữ U")

# Cấu hình các tham số nâng cao cho 10 chỉ số EWS
st.sidebar.markdown("---")

# Khởi tạo các giá trị session_state cho tham số EWS nâng cao nếu chưa có
if "live_tobin_q" not in st.session_state:
    st.session_state["live_tobin_q"] = 1.2
if "live_div_ratio" not in st.session_state:
    st.session_state["live_div_ratio"] = 0.0
if "live_isg" not in st.session_state:
    st.session_state["live_isg"] = 8.0
if "live_issue" not in st.session_state:
    st.session_state["live_issue"] = False
if "live_ab_return" not in st.session_state:
    st.session_state["live_ab_return"] = 0.0

with st.sidebar.expander("🎛️ Tham số EWS nâng cao"):
    # Xác định mã chứng khoán hiện tại để gọi API trực tuyến
    current_ticker = None
    if selected_profile != "Tải file mới":
        current_ticker = selected_profile.split(" - ")[0]
    elif "detected_ticker" in st.session_state and st.session_state["detected_ticker"] != "N/A":
        current_ticker = st.session_state["detected_ticker"]
        
    if current_ticker:
        st.markdown(f"📊 Mã chứng khoán phát hiện: `{current_ticker}`")
        if st.button("🔄 Tải tham số thị trường từ Vnstock"):
            target_year = 2024
            if "detected_years" in st.session_state and st.session_state["detected_years"]:
                target_year = max(st.session_state["detected_years"])
            total_assets = 1.0
            if "detected_total_assets" in st.session_state:
                total_assets = st.session_state["detected_total_assets"]
                
            with st.spinner(f"Đang tải tham số trực tuyến cho {current_ticker}..."):
                live_params = fetch_live_market_parameters(current_ticker, target_year, total_assets)
                
                st.session_state["live_tobin_q"] = max(0.1, min(10.0, float(live_params["tobin_q"])))
                st.session_state["live_div_ratio"] = float(live_params["div_ratio"]) * 100.0
                st.session_state["live_isg"] = float(live_params["isg"]) * 100.0
                st.session_state["live_issue"] = bool(live_params["issue"])
                st.session_state["live_ab_return"] = float(live_params["ab_return"]) * 100.0
                
                st.success("🎉 Tải xong và tự động đồng bộ!")
                st.rerun()

    tobin_q_input = st.number_input("Tỷ số Q (Tobin's Q)", min_value=0.1, max_value=10.0, value=st.session_state["live_tobin_q"], step=0.1, help="Tỷ số Giá thị trường / Giá trị tài sản (dùng cho KZ Index)")
    div_ratio_input = st.slider("Tỷ lệ chi trả cổ tức (%)", min_value=0.0, max_value=100.0, value=st.session_state["live_div_ratio"], step=5.0, help="Tỷ lệ cổ tức tiền mặt / Lợi nhuận sau thuế (dùng cho KZ & WW Index)") / 100.0
    isg_input = st.slider("Tăng trưởng DT ngành - ISG (%)", min_value=-50.0, max_value=100.0, value=st.session_state["live_isg"], step=1.0, help="Tăng trưởng doanh thu trung bình của toàn ngành (dùng cho WW Index)") / 100.0
    issue_input = st.checkbox("DN có phát hành cổ phiếu/nợ", value=st.session_state["live_issue"], help="Doanh nghiệp có phát hành thêm cổ phiếu hoặc nợ dài hạn (dùng cho Dechow F-Score)")
    ab_return_input = st.slider("Tỷ suất sinh lời bất thường (%)", min_value=-100.0, max_value=100.0, value=st.session_state["live_ab_return"], step=5.0, help="Tỷ suất sinh lời cổ phiếu vượt trội của DN so với thị trường (dùng cho M-Score 12 biến)") / 100.0
    unconditional_prob_input = st.number_input("Ngưỡng xác suất gốc (%)", min_value=0.01, max_value=5.0, value=0.37, step=0.05, format="%.2f", help="Xác suất thao túng trung bình thị trường (dùng cho Dechow F-Score)") / 100.0

# Phân tích định tính & Báo cáo thường niên
with st.sidebar.expander("📝 Tham số Định tính (Báo cáo Thường niên)"):
    uploaded_ar = st.file_uploader("Tải lên PDF Báo cáo thường niên", type=["pdf"], key="uploaded_ar")
    is_bds_input = st.checkbox("Ngành Bất động sản / Xây dựng", value=default_is_bds, help="Điều chỉnh ngưỡng cảnh báo đòn bẩy LEV thêm +0.10")
    
    st.markdown("**Cấu hình các chỉ số định tính:**")
    
    if uploaded_ar:
        try:
            ar_bytes = uploaded_ar.read()
            ar_data = parse_annual_report_pdf(ar_bytes)
            if ar_data:
                st.success("📄 Đã parse xong Báo cáo thường niên!")
                default_words = ar_data["total_words"]
                default_risk = (ar_data["risk_word_count"] / ar_data["total_words"]) * 1000 if ar_data["total_words"] > 0 else 0.0
                default_neg = ar_data["neg_tone_ratio"] * 100.0
        except Exception as e:
            st.error(f"Lỗi parse Báo cáo thường niên: {e}")
            
    risk_words_ratio_input = st.slider("Tần suất từ khóa rủi ro (RiskWord ‰)", min_value=0.0, max_value=10.0, value=float(default_risk), step=0.1)
    neg_tone_ratio_input = st.slider("Sắc thái tiêu cực (NegTone %)", min_value=0.0, max_value=10.0, value=float(default_neg), step=0.1) / 100.0
    report_len_input = st.number_input("Độ dài báo cáo (từ)", min_value=100, max_value=100000, value=int(default_words), step=500)
    text_sim_input = st.slider("Độ tương đồng văn bản (TextSim)", min_value=0.0, max_value=1.0, value=float(default_sim), step=0.05)
    ceo_age_input = st.number_input("Độ tuổi CEO (năm)", min_value=18, max_value=100, value=int(default_ceo_age), step=1, help="Độ tuổi của CEO để đánh giá rủi ro theo sheet Độ tuổi CEO")


# Khởi tạo các biến chứa dữ liệu chính
extracted_data = {}
tickers_detected = set()
company_names_detected = set()
bank_files_detected = []

if selected_profile != "Tải file mới":
    # Luồng 1: Sử dụng dữ liệu đã nạp sẵn từ SQLite ở đầu ứng dụng
    extracted_data = db_extracted_data
    tickers_detected = db_tickers_detected
    company_names_detected = db_company_names_detected
    if extracted_data:
        st.sidebar.success(f"⚡ Đã tải hồ sơ **{list(tickers_detected)[0]}** từ SQLite!")

elif uploaded_files:
    # Luồng 2: Tải file mới và chạy bộ trích xuất dữ liệu (OCR/Excel)
    for uploaded_file in uploaded_files:
        file_bytes = uploaded_file.read()
        filename = uploaded_file.name
        
        st.sidebar.info(f"📁 Đang xử lý: {filename}")
        
        # Kiểm tra xem file có thuộc ngân hàng/TCTD không
        is_bank = any(kw in filename.lower() for kw in ["vcb", "bidv", "vietinbank", "vietcombank", "tcb", "mbb", "agribank", "ngân hàng", "tổ chức tín dụng"])
        if is_bank:
            bank_files_detected.append(filename)
            continue # Bỏ qua không trích xuất BCTC ngân hàng thương mại
            
        # Trích xuất thông tin tóm tắt (Metadata)
        if filename.endswith(".pdf"):
            c_name, ticker = extract_metadata_from_pdf(file_bytes, filename)
        else:
            c_name, ticker = extract_metadata_from_excel(file_bytes, filename)
            
        if ticker != "N/A":
            tickers_detected.add(ticker)
        if c_name != "N/A":
            company_names_detected.add(c_name)
            
        # Xác định năm báo cáo chính Y của file này để làm độ ưu tiên khi gộp
        fn_years = [int(y) for y in re.findall(r'(20[1-2]\d)', filename)]
        Y_file = max(fn_years) if fn_years else None
        
        # Trích xuất dữ liệu tài chính thô của file này
        with st.spinner(f"Đang trích xuất {filename}..."):
            if filename.endswith(".pdf"):
                file_data = parse_bctc_pdf(file_bytes, filename)
                
                # FALLBACK TO OCR: Nếu rỗng, hoặc là PDF_SCANNED, hoặc số chỉ tiêu trích xuất được quá ít (< 5) do lỗi font chữ/quét
                should_run_ocr = False
                if not file_data or (isinstance(file_data, dict) and file_data.get("_error_type") == "PDF_SCANNED"):
                    should_run_ocr = True
                elif isinstance(file_data, dict):
                    # Đếm số lượng chỉ tiêu thực tế khác nan/0
                    valid_vars = 0
                    for y, y_data in file_data.items():
                        for v, val in y_data.items():
                            if not v.startswith("_") and val != 0 and not pd.isna(val):
                                valid_vars += 1
                    if valid_vars < 5:
                        should_run_ocr = True
                        
                if should_run_ocr:
                    file_data = parse_bctc_pdf_ocr(file_bytes, filename)
            else:
                file_data = parse_bctc_excel(file_bytes)
                
        # Gộp dữ liệu của file này vào extracted_data chung (ưu tiên năm báo cáo chính hơn năm so sánh)
        if file_data and not file_data.get("_error_type"):
            for year, year_data in file_data.items():
                is_reporting_year = (Y_file is not None and year == Y_file)
                
                if year not in extracted_data:
                    extracted_data[year] = {}
                    extracted_data[year]["_is_reporting"] = is_reporting_year
                    
                # Cho phép ghi đè nếu dữ liệu hiện tại chỉ là năm so sánh (phụ) và dữ liệu mới là năm báo cáo chính (ưu tiên)
                current_is_reporting = extracted_data[year].get("_is_reporting", False)
                should_overwrite = (not current_is_reporting and is_reporting_year)
                
                for var, val in year_data.items():
                    if var.startswith("_"):
                        continue
                    curr_val = extracted_data[year].get(var, 0)
                    is_curr_invalid = (curr_val == 0 or (0 < abs(curr_val) <= 10000) or pd.isna(curr_val))
                    is_new_valid = (abs(val) > 10000)
                    
                    if var not in extracted_data[year] or is_curr_invalid or (should_overwrite and is_new_valid):
                        extracted_data[year][var] = val
                        
                if should_overwrite:
                    extracted_data[year]["_is_reporting"] = True
                        
    # Hiển thị cảnh báo nếu phát hiện file ngân hàng thương mại
    if bank_files_detected:
        for bank_file in bank_files_detected:
            st.error(f"❌ **Cảnh báo nghiệp vụ: Báo cáo tài chính thuộc Ngân hàng / TCTD ({bank_file})**")
            st.info("""
            **Giải thích từ Giải pháp (Solutions Architect)**:
            * Các chỉ số rủi ro tín dụng EWS (Altman Z'-Score, Beneish M-Score, SA Index) **chỉ dành cho doanh nghiệp phi tài chính** (sản xuất, thương mại, dịch vụ).
            * Ngân hàng thương mại không áp dụng hệ thống tài khoản kế toán Thông tư 200, nên hệ thống tự động bỏ qua file này để tránh lỗi tính toán.
            """)
            
if extracted_data:
    # Lưu các thông tin phát hiện được vào session state phục vụ cho việc tải tham số EWS trực tuyến
    if tickers_detected:
        st.session_state["detected_ticker"] = list(tickers_detected)[0]
    st.session_state["detected_years"] = list(extracted_data.keys())
    latest_y = max(extracted_data.keys())
    st.session_state["detected_total_assets"] = extracted_data[latest_y].get("Total_Assets", 1.0)
    
    # 1. Chạy xác thực & tự động hiệu chỉnh cân đối dữ liệu trước
    validation_is_valid, validation_logs = validate_data(extracted_data)
    
    # 2. Tính toán chỉ số EWS từ dữ liệu đã được hiệu chỉnh
    main_ticker = list(tickers_detected)[0] if tickers_detected else "N/A"
    is_listed_val = 1.0 if (len(main_ticker) == 3 and main_ticker.isalpha()) else 0.0
    
    ews_results = calculate_ews(
        extracted_data, 
        firm_age=firm_age_input,
        tobin_q=tobin_q_input,
        div_ratio=div_ratio_input,
        isg=isg_input,
        issue=issue_input,
        ab_return=ab_return_input,
        unconditional_prob=unconditional_prob_input,
        is_listed=is_listed_val
    )
    
    # Tính điểm quản trị GovDisc từ session state
    if "gov_checklist" not in st.session_state:
        st.session_state["gov_checklist"] = [True] * 9 + [False]
    gov_disc_score = sum(st.session_state["gov_checklist"]) / 10.0
    
    # 2b. Tính toán các biến kiểm soát bổ sung
    control_results = calculate_controls(
        extracted_data,
        firm_age=firm_age_input,
        is_bds=is_bds_input,
        gov_disc_score=gov_disc_score,
        risk_words_ratio=risk_words_ratio_input,
        neg_tone_ratio=neg_tone_ratio_input,
        report_len=report_len_input,
        text_sim=text_sim_input,
        ceo_age=ceo_age_input,
        industry=industry_input
    )
    
    # 2c. Tính toán cân đối vốn vay ngắn hạn và bóc tách Phải thu / Tồn kho
    wc_debt_results = calculate_working_capital_and_debt_analysis(extracted_data)
    
    years_list = sorted(list(extracted_data.keys()))
    
    # 3. Hiển thị thông tin tóm tắt hồ sơ doanh nghiệp & kiểm tra chéo
    
    main_ticker = list(tickers_detected)[0] if tickers_detected else "N/A"
    if main_ticker in TICKER_NAME_MAP:
        summary_company_name = TICKER_NAME_MAP[main_ticker]
    else:
        summary_company_name = list(company_names_detected)[0] if company_names_detected else "Không rõ"
        
    summary_ticker = ", ".join(tickers_detected) if tickers_detected else "N/A"
    summary_years = ", ".join(map(str, years_list))
    
    # Gán các chỉ số định tính và BĐS vào extracted_data để lưu
    for year in years_list:
        extracted_data[year]["Qual_RiskWord"] = risk_words_ratio_input
        extracted_data[year]["Qual_NegTone"] = neg_tone_ratio_input
        extracted_data[year]["Qual_ReportLen"] = report_len_input
        extracted_data[year]["Qual_TextSim"] = text_sim_input
        extracted_data[year]["Qual_IsBDS"] = 1.0 if is_bds_input else 0.0
        extracted_data[year]["Qual_CEOAge"] = float(ceo_age_input)
        extracted_data[year]["Qual_Industry"] = str(industry_input)

    # Tự động lưu hồ sơ vào bộ nhớ cache CHỈ LẦN ĐẦU sau khi trích xuất từ file mới
    # (tránh ghi lại disk mỗi lần rerun/switch tab)
    _save_flag_key = f"_saved_{main_ticker}"
    if selected_profile == "Tải file mới" and main_ticker != "N/A" and not st.session_state.get(_save_flag_key):
        profile_to_save = {
            "ticker": main_ticker,
            "company_name": summary_company_name,
            "financial_data": extracted_data
        }
        cache_path = os.path.join(STORAGE_DIR, f"{main_ticker}.json")
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(profile_to_save, f, ensure_ascii=False, indent=4)
            st.toast(f"💾 Đã tự động lưu hồ sơ **{main_ticker}** vào cache JSON!", icon="💾")
        except Exception as e:
            st.sidebar.warning(f"Không thể lưu cache JSON: {e}")
            
        try:
            save_to_db(main_ticker, summary_company_name, extracted_data)
            st.toast(f"🗄️ Đã tự động lưu hồ sơ **{main_ticker}** vào SQLite!", icon="🗄️")
        except Exception as e:
            st.sidebar.warning(f"Không thể lưu vào SQLite: {e}")
        
        # Đánh dấu đã lưu để các lần rerun sau không ghi lại
        st.session_state[_save_flag_key] = True
        # Invalidate cache load_from_db để hồ sơ mới xuất hiện trong danh sách
        load_from_db_cached.clear()

    # Báo cáo Thẩm định EWS (Xuất PDF chuẩn in ấn & Markdown)
    if main_ticker != "N/A":
        from pdf_report_generator import generate_ews_pdf_bytes
        
        pdf_bytes = generate_ews_pdf_bytes(
            company_name=summary_company_name,
            ticker=main_ticker,
            extracted_data=extracted_data,
            ews_results=ews_results,
            firm_age=firm_age_input,
            tobin_q=tobin_q_input,
            div_ratio=div_ratio_input,
            isg=isg_input,
            ab_return=ab_return_input,
            unconditional_prob=unconditional_prob_input,
            industry=industry_input,
            ceo_age=ceo_age_input,
            is_bds=is_bds_input
        )
        
        md_report_content = generate_markdown_summary(
            summary_company_name,
            main_ticker,
            extracted_data,
            ews_results,
            firm_age_input,
            tobin_q_input,
            div_ratio_input,
            isg_input,
            ab_return_input,
            unconditional_prob_input
        )
        
        st.sidebar.markdown("---")
        st.sidebar.subheader("📄 Báo cáo Thẩm định EWS")
        st.sidebar.download_button(
            label="📄 📥 Tải Báo cáo Thẩm định (PDF)",
            data=pdf_bytes,
            file_name=f"Bao_Cao_Tham_Dinh_EWS_{main_ticker}.pdf",
            mime="application/pdf",
            type="primary",
            help="Tải báo cáo thẩm định rủi ro tín dụng định dạng PDF chuẩn in ấn & trình ký"
        )
        
        with st.sidebar.expander("📝 Tùy chọn xuất Markdown thô"):
            st.download_button(
                label="📥 Tải file Markdown (.md)",
                data=md_report_content,
                file_name=f"EWS_Summary_{main_ticker}.md",
                mime="text/markdown",
                help="Tải báo cáo tóm tắt định dạng Markdown thô"
            )
        
        # Tự động lưu bản sao PDF và Markdown vào thư mục storage
        local_pdf_path = os.path.join(STORAGE_DIR, f"Bao_Cao_Tham_Dinh_EWS_{main_ticker}.pdf")
        local_md_path = os.path.join(STORAGE_DIR, f"EWS_Summary_{main_ticker}.md")
        try:
            with open(local_pdf_path, "wb") as f:
                f.write(pdf_bytes)
            with open(local_md_path, "w", encoding="utf-8") as f:
                f.write(md_report_content)
        except Exception:
            pass
    
    col_hdr_info, col_hdr_btn = st.columns([4, 1.2])
    with col_hdr_info:
        st.markdown(f"""
        <div style="background-color: #f0f4f8; padding: 14px 18px; border-radius: 8px; border-left: 5px solid #1f77b4; margin-bottom: 15px;">
            <table style="width: 100%; border-collapse: collapse; font-family: sans-serif;">
                <tr>
                    <td style="width: 25%; font-weight: bold; padding: 3px 0;">🏢 Doanh nghiệp:</td>
                    <td style="padding: 3px 0; font-size: 1.05em; font-weight: bold; color: #2d3748;">{summary_company_name}</td>
                </tr>
                <tr>
                    <td style="font-weight: bold; padding: 3px 0;">🏷️ Mã chứng khoán:</td>
                    <td style="padding: 3px 0; font-weight: bold; color: #e53e3e;">{summary_ticker} &nbsp;|&nbsp; <b>Ngành:</b> {industry_input}</td>
                </tr>
                <tr>
                    <td style="font-weight: bold; padding: 3px 0;">📅 Các năm báo cáo:</td>
                    <td style="padding: 3px 0; font-weight: bold; color: #2b6cb0;">{summary_years}</td>
                </tr>
            </table>
        </div>
        """, unsafe_allow_html=True)
    with col_hdr_btn:
        st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
        if st.button("🔄 Chọn / Nạp hồ sơ khác", use_container_width=True, help="Quay lại Trung tâm nhập liệu 3 bước để chọn DN khác"):
            st.session_state.pop("active_profile", None)
            st.session_state.pop("uploaded_from_main", None)
            st.session_state.pop("sidebar_selected_profile", None)
            st.rerun()
    
    # Cảnh báo kiểm tra chéo nếu tải lên nhiều mã chứng khoán khác nhau
    if len(tickers_detected) > 1:
        st.error(f"⚠️ **CẢNH BÁO TẢI NHẦM HỒ SƠ**: Phát hiện dữ liệu thuộc về nhiều mã chứng khoán khác nhau: `{', '.join(tickers_detected)}`. Vui lòng kiểm tra lại danh sách file tải lên để tránh phân tích sai doanh nghiệp!")
        
    # Hiển thị cảnh báo trực quan trên trang chính nếu có lỗi nghiêm trọng về tính toàn vẹn (ví dụ: thiếu năm, mất cân đối)
    error_logs = [log["message"] for log in validation_logs if log["type"] == "error"]
    if error_logs:
        st.error("⚠️ **CẢNH BÁO CHẤT LƯỢNG HỒ SƠ / DỮ LIỆU BCTC**:")
        for err in error_logs:
            st.markdown(f"- {err}")
        
    # Khởi tạo câu trả lời 5Cs từ session state hoặc DB
    user_5c_answers = {}
    for k_5c, cfg_5c in DEFAULT_5C_CONFIG.items():
        sess_key = f"5c_{k_5c}"
        if sess_key in st.session_state:
            user_5c_answers[k_5c] = st.session_state[sess_key]
        else:
            val_from_db = None
            if latest_y in extracted_data and f"Qual_5C_{k_5c}" in extracted_data[latest_y]:
                val_from_db = extracted_data[latest_y][f"Qual_5C_{k_5c}"]
            user_5c_answers[k_5c] = val_from_db if (val_from_db and val_from_db in cfg_5c["options"]) else cfg_5c["default"]
            st.session_state[sess_key] = user_5c_answers[k_5c]

    res_5cs = calculate_5c_scores(user_5c_answers)

    # Thiết kế 10 tab nghiệp vụ chuyên sâu theo luồng thẩm định chuẩn mực
    tab_dashboard, tab_wc_debt, tab_5cs, tab_bank_stmt, tab_controls, tab_components, tab_variables, tab_formulas, tab_validation, tab_audit = st.tabs([
        "📊 1. Dashboard Tổng quan & Xếp hạng",
        "⚖️ 2. Cân đối Vốn vay & Chu kỳ tiền mặt (CCC)",
        "🏛️ 3. Đánh giá Định tính 5Cs & Hệ sinh thái",
        "💳 4. Sao kê Dòng tiền & Giám sát Sau Giải ngân",
        "🛡️ 5. Biến kiểm soát",
        "📈 6. Chỉ số EWS thành phần",
        "📋 7. Dữ liệu trích xuất",
        "🧮 8. Số liệu & Công thức",
        "🔍 9. Kiểm tra toàn vẹn & Thuế",
        "🛡️ 10. Truy vết & Chất vấn"
    ])
    
    # ------------------ TAB 1: DASHBOARD TỔNG QUAN ------------------
    with tab_dashboard:
        # Chọn năm để xem chi tiết
        col_y1, col_y2 = st.columns([2, 2])
        with col_y1:
            st.subheader("Bảng điều khiển rủi ro EWS & Xếp hạng Tín dụng")
        with col_y2:
            selected_year = st.selectbox("Chọn năm đánh giá chính:", years_list, index=len(years_list)-1, key="main_eval_year_select")
        
        # Tính trạng thái tổng hợp cho năm được chọn
        res = ews_results[selected_year]
        
        # 1. KHỐI TỔNG HỢP: XẾP HẠNG TÍN DỤNG HỖN HỢP (HYBRID RATING SCORECARD)
        st.markdown("### 🎯 Xếp hạng Tín dụng Hỗn hợp Toàn diện (Financial EWS + 5Cs Qualitative)")
        
        quant_score = calculate_quant_ews_score(res)
        qual_score = res_5cs["total_qual_score"]
        
        quant_w = st.slider(
            "Tỷ trọng Định lượng BCTC (EWS) vs Định tính 5Cs:",
            min_value=0.30, max_value=0.80, value=0.60, step=0.05,
            format="%d%% Định lượng",
            help="Chuẩn mực Ngân hàng Thương mại khuyến nghị: 60% Định lượng BCTC + 40% Định tính 5Cs & Hệ sinh thái.",
            key=f"slider_quant_w_{selected_year}"
        )
        
        hybrid_res = calculate_hybrid_rating(quant_score, qual_score, quant_weight=quant_w)
        
        col_hy1, col_hy2, col_hy3, col_hy4 = st.columns([1.2, 1.2, 1.3, 1.3])
        with col_hy1:
            st.markdown(f"""
            <div style="background-color: {hybrid_res['bg_color']}; border-left: 5px solid {hybrid_res['color']}; padding: 16px; border-radius: 8px;">
                <p style="margin: 0; color: #4A5568; font-size: 0.82em; font-weight: bold;">ĐIỂM XẾP HẠNG HỖN HỢP</p>
                <h1 style="margin: 4px 0; color: {hybrid_res['color']}; font-size: 2.1em;">{hybrid_res['hybrid_score']:.1f}<span style="font-size: 0.5em; color: #718096;"> / 100</span></h1>
                <p style="margin: 0; font-weight: bold; color: {hybrid_res['color']}; font-size: 0.9em;">🏆 {hybrid_res['grade']}</p>
            </div>
            """, unsafe_allow_html=True)
            
        with col_hy2:
            st.markdown(f"""
            <div style="background-color: white; border: 1px solid #E2E8F0; padding: 16px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.02);">
                <p style="margin: 0; color: #718096; font-size: 0.82em; font-weight: bold;">CƠ CẤU ĐIỂM THÀNH PHẦN</p>
                <p style="margin: 6px 0 2px 0; font-size: 0.9em;">📊 <b>Định lượng EWS ({quant_w:.0%}):</b> <span style="color: #3182CE; font-weight: bold;">{quant_score:.1f} đ</span></p>
                <p style="margin: 2px 0; font-size: 0.9em;">🏛️ <b>Định tính 5Cs ({1-quant_w:.0%}):</b> <span style="color: #805AD5; font-weight: bold;">{qual_score:.1f} đ</span></p>
                <p style="margin: 4px 0 0 0; font-size: 0.78em; color: #718096;">BCTC & Thuế: <b>{res_5cs['bctc_trust_level']}</b></p>
            </div>
            """, unsafe_allow_html=True)
            
        with col_hy3:
            st.markdown(f"""
            <div style="background-color: white; border: 1px solid #E2E8F0; padding: 16px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.02);">
                <p style="margin: 0; color: #718096; font-size: 0.82em; font-weight: bold;">HẠN MỨC & TỶ LỆ CHO VAY (LTV)</p>
                <p style="margin: 6px 0 0 0; font-size: 0.88em; font-weight: bold; color: #2D3748;">{hybrid_res['ltv']}</p>
                <p style="margin: 6px 0 0 0; font-size: 0.78em; color: #718096;">Hệ sinh thái: <b>{res_5cs['supply_chain_risk']}</b></p>
            </div>
            """, unsafe_allow_html=True)
            
        with col_hy4:
            st.markdown(f"""
            <div style="background-color: white; border: 1px solid #E2E8F0; padding: 16px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.02);">
                <p style="margin: 0; color: #718096; font-size: 0.82em; font-weight: bold;">QUYẾT ĐỊNH & KHUYẾN NGHỊ</p>
                <p style="margin: 6px 0 0 0; font-size: 0.85em; font-weight: bold; color: {hybrid_res['color']};">{hybrid_res['decision']}</p>
                <p style="margin: 4px 0 0 0; font-size: 0.78em; color: #4A5568;">{hybrid_res['guidance']}</p>
            </div>
            """, unsafe_allow_html=True)
            
        st.markdown("---")
        st.markdown("### 🔍 10 Chỉ số Cảnh báo Sớm (EWS Components)")
        
        # Helper to draw a beautiful metric card
        def render_ews_card(title, data_dict, format_str="{:.3f}"):
            if data_dict:
                score = data_dict["score"]
                zone = data_dict["zone"]
                status = data_dict["status"]
                card_class = f"metric-card metric-red" if status == "error" else (f"metric-card metric-yellow" if status == "warning" else f"metric-card metric-green")
                # Xác định màu chữ trực quan dựa trên mức độ rủi ro để hiển thị rõ ràng trên nền sáng
                text_color = "#9b2c2c" if status == "error" else ("#9c4221" if status == "warning" else "#22543d")
                st.markdown(f"""
                <div class="{card_class}">
                    <h5 style='margin: 0; color: #4a5568; font-size: 0.95em;'>{title}</h5>
                    <h2 style='margin: 8px 0 4px 0; color: #1a202c;'>{format_str.format(score)}</h2>
                    <p style='margin: 0; font-size: 0.9em; font-weight: 600; color: {text_color};'>{zone}</p>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div class="metric-card">
                    <h5 style='margin: 0; color: #718096; font-size: 0.95em;'>{title}</h5>
                    <p style='color: #718096; margin-top: 15px; margin-bottom: 0; font-size: 0.9em; font-weight: 500;'>Không đủ dữ liệu</p>
                </div>
                """, unsafe_allow_html=True)
        
        # Nhóm 1: Thao túng BCTC (FS Manipulation)
        st.markdown("### 🔍 Nhóm 1: Thao túng BCTC (FS Manipulation)")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            render_ews_card("Beneish M-Score (1999 - 8 biến)", res.get("Beneish_M_Score"))
        with col2:
            render_ews_card("Beneish M-Score (1997 - 12 biến)", res.get("Beneish_M_Score_12"), "{:.2%}")
        with col3:
            render_ews_card("Dechow F-Score (2011)", res.get("Dechow_F_Score"))
        with col4:
            render_ews_card("Dự báo ML tùy chỉnh (Gian lận VN)", res.get("Custom_ML_Fraud"), "{:.2%}")
            
        # Nhóm 2: Thao túng thực tế (Real Activity Manipulation - REM)
        st.markdown("### ⚙️ Nhóm 2: Thao túng Hoạt động Thực tế (REM)")
        col1, col2, col3 = st.columns(3)
        with col1:
            render_ews_card("Abnormal CFO (Ab_CFO)", res.get("Abnormal_CFO"))
        with col2:
            render_ews_card("Abnormal Production (Ab_PROD)", res.get("Abnormal_PROD"))
        with col3:
            render_ews_card("Abnormal Discretionary Exp (Ab_DISEXP)", res.get("Abnormal_DISEXP"))
            
        # Nhóm 3: Hạn chế Tài chính (Financial Constraints)
        st.markdown("### 🧱 Nhóm 3: Hạn chế Tài chính & Thanh khoản")
        col1, col2, col3 = st.columns(3)
        with col1:
            render_ews_card("SA Index (Size-Age)", res.get("SA_Index"))
        with col2:
            render_ews_card("KZ Index (Kaplan-Zingales)", res.get("KZ_Index"))
        with col3:
            render_ews_card("WW Index (Whited-Wu)", res.get("WW_Index"))
            
        # Nhóm 4: Kiệt quệ Tài chính (Financial Distress)
        st.markdown("### 🚨 Nhóm 4: Khả năng Phá sản (Financial Distress)")
        col1, col2, col3 = st.columns(3)
        with col1:
            render_ews_card("Altman Z'-Score (Private Firms)", res.get("Altman_Z_Prime"))
                
        # Biểu đồ xu hướng tài chính doanh nghiệp
        st.markdown("---")
        st.subheader("📈 Phân tích Xu hướng các Biến số Tài chính Quan trọng")
        trend_data = []
        for y in years_list:
            y_data = extracted_data[y]
            trend_data.append({
                "Năm": str(y),
                "Khoản phải thu KH (131)": y_data.get("Accounts_Receivable", 0) / 1e9,
                "Doanh thu thuần (10)": y_data.get("Net_Sales", 0) / 1e9,
                "Dòng tiền từ HĐKD (20 LCTT)": y_data.get("OCF", 0) / 1e9
            })
        df_trend = pd.DataFrame(trend_data)
        st.line_chart(df_trend.set_index("Năm"), height=300)
        st.caption("Đơn vị tính: Tỷ đồng (VND)")

    # ------------------ TAB 2: CÂN ĐỐI VỐN VAY & PHẢI THU / TỒN KHO / PHẢI TRẢ (CCC) ------------------
    with tab_wc_debt:
        st.subheader(f"⚖️ Cân đối Vốn vay Ngắn hạn, Chu kỳ Tiền mặt (CCC) & Bóc tách Khoản mục (Năm {selected_year})")
        st.info("""
        💡 **Nguyên lý Kiểm soát Tín dụng Vốn lưu động & Sau Giải ngân tại NHTM:**
        * **Nhu cầu Vốn lưu động ròng (OWC):** $\\text{OWC} = \\text{Phải thu KH (131)} + \\text{Hàng tồn kho (140)} - \\text{Phải trả người bán (311)}$. Vốn vay ngắn hạn ngân hàng chỉ được cấp để bù đắp phần thiếu hụt OWC này.
        * **Chu kỳ Chuyển đổi Tiền mặt (Cash Conversion Cycle - CCC):** $\\text{CCC} = \\text{DSO (Thu tiền)} + \\text{DSI (Tồn kho)} - \\text{DPO (Trả tiền)}$. CCC đo lường số ngày tiền mặt bị "giam" trong chu kỳ kinh doanh trước khi thu hồi lại.
        * **Cảnh báo Đỏ 🚨:** Nếu Vốn vay ngắn hạn vượt quá $(\\text{Phải thu} + \\text{Tồn kho})$ hoặc $\\text{CCC}$ kéo dài bất thường $\\rightarrow$ Doanh nghiệp bị đọng vốn nghiêm trọng, nguy cơ mất thanh khoản hoặc rút vốn ngắn hạn đem tài trợ tài sản dài hạn/bất động sản ngoài ngành.
        """)
        
        wc_curr = wc_debt_results[selected_year]
        
        # 1. Thẻ chỉ số Cân đối Nguồn vốn vay
        st.markdown("### 📊 1. Cân đối Nguồn vốn vay & Nhu cầu Vốn lưu động ròng (OWC)")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric(
                "Vốn vay ngắn hạn (320)", 
                f"{wc_curr['st_debt'] / 1e9:,.2f} tỷ",
                help="Vay và nợ thuê tài chính ngắn hạn (hoặc tổng nợ ngắn hạn nếu chưa bóc tách riêng)"
            )
        with c2:
            st.metric(
                "Nhu cầu Vốn lưu động (OWC)", 
                f"{wc_curr['owc'] / 1e9:,.2f} tỷ",
                help="OWC = Phải thu (131) + Hàng tồn kho (140) - Phải trả người bán (311)"
            )
        with c3:
            ratio_color = "normal" if wc_curr['debt_to_wc_ratio'] <= 1.0 else "inverse"
            st.metric(
                "Tỷ lệ Vay / (Phải thu + Tồn kho)", 
                f"{wc_curr['debt_to_wc_ratio']:.1%}",
                delta=f"{'An toàn (<= 100%)' if wc_curr['debt_to_wc_ratio'] <= 1.0 else 'Mất cân đối (> 100%)'}",
                delta_color=ratio_color
            )
        with c4:
            st.metric(
                "Chênh lệch Cân đối (Funding Gap)", 
                f"{wc_curr['funding_gap'] / 1e9:,.2f} tỷ",
                help="Funding Gap = (Phải thu + Tồn kho) - Vốn vay. Dương (>0) là an toàn, Âm (<0) là mất cân đối"
            )
            
        # Hộp cảnh báo trạng thái
        if wc_curr['status'] == "error":
            st.error(f"🚨 **{wc_curr['zone']}**: {wc_curr['diag']}")
        elif wc_curr['status'] == "warning":
            st.warning(f"⚠️ **{wc_curr['zone']}**: {wc_curr['diag']}")
        else:
            st.success(f"✅ **{wc_curr['zone']}**: {wc_curr['diag']}")
            
        st.markdown("---")
        
        # 2. Khối Chu kỳ Chuyển đổi Tiền mặt (Cash Conversion Cycle - CCC)
        st.markdown("### 🔄 2. Chu kỳ Chuyển đổi Tiền mặt (Cash Conversion Cycle - CCC)")
        st.caption("Chu kỳ kinh doanh = DSO + DSI. Chu kỳ tiền mặt thực tế CCC = DSO + DSI - DPO.")
        
        ccc_val = wc_curr.get('ccc')
        dso_val = wc_curr.get('dso')
        dsi_val = wc_curr.get('dsi')
        dpo_val = wc_curr.get('dpo')
        op_cycle_val = wc_curr.get('operating_cycle')
        
        kpi_ccc1, kpi_ccc2, kpi_ccc3, kpi_ccc4 = st.columns(4)
        with kpi_ccc1:
            ccc_str = f"{ccc_val:.1f} ngày" if ccc_val is not None else "N/A"
            ccc_status = "Đọng vốn dài (>180d)" if (ccc_val is not None and ccc_val > 180) else ("Chiếm dụng vốn tốt (<0d)" if (ccc_val is not None and ccc_val < 0) else "Bình thường")
            ccc_delta_color = "inverse" if (ccc_val is not None and ccc_val > 180) else "normal"
            st.metric("Chu kỳ Tiền mặt (CCC)", ccc_str, delta=ccc_status, delta_color=ccc_delta_color, help="Số ngày tiền bị chiếm dụng trong vòng quay kinh doanh")
        with kpi_ccc2:
            dso_str = f"{dso_val:.1f} ngày" if dso_val is not None else "N/A"
            st.metric("Số ngày thu tiền KH (DSO)", dso_str, help="Số ngày trung bình để thu tiền từ khách hàng nợ (131)")
        with kpi_ccc3:
            dsi_str = f"{dsi_val:.1f} ngày" if dsi_val is not None else "N/A"
            st.metric("Số ngày lưu kho (DSI)", dsi_str, help="Số ngày trung bình để giải phóng hàng tồn kho (140)")
        with kpi_ccc4:
            dpo_str = f"{dpo_val:.1f} ngày" if dpo_val is not None else "N/A"
            st.metric("Số ngày trả tiền NCC (DPO)", dpo_str, help="Số ngày trung bình trì hoãn thanh toán cho nhà cung cấp (311)")
            
        st.markdown("---")
        
        # 3. Bóc tách chuyên sâu 3 Khoản mục Trọng yếu (Phải thu, Tồn kho, Phải trả)
        st.markdown("### 🔍 3. Bóc tách Chất lượng 3 Khoản mục Trọng yếu: Phải thu - Tồn kho - Phải trả")
        col_rec, col_inv, col_pay = st.columns(3)
        
        with col_rec:
            st.markdown("#### 📑 Phải thu khách hàng (131)")
            rec_metrics = []
            rec_metrics.append({"Chỉ tiêu": "Giá trị Phải thu ngắn hạn KH", "Giá trị": f"{wc_curr['rec'] / 1e9:,.2f} tỷ VND"})
            rec_metrics.append({"Chỉ tiêu": "Tỷ trọng Phải thu / Tổng tài sản", "Giá trị": f"{wc_curr['rec_to_assets']:.2%}"})
            rec_metrics.append({"Chỉ tiêu": "Tỷ trọng Phải thu / TS ngắn hạn", "Giá trị": f"{wc_curr['rec_to_ca']:.2%}"})
            if dso_val is not None:
                rec_metrics.append({"Chỉ tiêu": "Số ngày thu tiền bình quân (DSO)", "Giá trị": f"{dso_val:.1f} ngày"})
            if wc_curr['dsri'] is not None:
                dsri_status = "⚠️ Bất thường (> 1.25)" if wc_curr['dsri'] > 1.25 else "🟢 Bình thường"
                rec_metrics.append({"Chỉ tiêu": "Chỉ số tăng Phải thu / Doanh thu (DSRI)", "Giá trị": f"{wc_curr['dsri']:.2f} ({dsri_status})"})
            if wc_curr['rec_growth'] is not None:
                rec_metrics.append({"Chỉ tiêu": "Tốc độ tăng trưởng Phải thu", "Giá trị": f"{wc_curr['rec_growth']:.2%}"})
            st.dataframe(pd.DataFrame(rec_metrics), width="stretch", hide_index=True)
            
        with col_inv:
            st.markdown("#### 📦 Hàng tồn kho (140)")
            inv_metrics = []
            inv_metrics.append({"Chỉ tiêu": "Giá trị Hàng tồn kho", "Giá trị": f"{wc_curr['inv'] / 1e9:,.2f} tỷ VND"})
            inv_metrics.append({"Chỉ tiêu": "Tỷ trọng Tồn kho / Tổng tài sản", "Giá trị": f"{wc_curr['inv_to_assets']:.2%}"})
            inv_metrics.append({"Chỉ tiêu": "Tỷ trọng Tồn kho / TS ngắn hạn", "Giá trị": f"{wc_curr['inv_to_ca']:.2%}"})
            if dsi_val is not None:
                inv_metrics.append({"Chỉ tiêu": "Số ngày tồn kho bình quân (DSI)", "Giá trị": f"{dsi_val:.1f} ngày"})
            if wc_curr['inv_vs_cogs_spread'] is not None:
                spread_status = "⚠️ Tồn kho tăng nhanh hơn Giá vốn" if wc_curr['inv_vs_cogs_spread'] > 0.15 else "🟢 Tương quan hợp lý"
                inv_metrics.append({"Chỉ tiêu": "Độ lệch Tăng Tồn kho vs Giá vốn", "Giá trị": f"{wc_curr['inv_vs_cogs_spread']:+.2%} ({spread_status})"})
            if wc_curr['inv_growth'] is not None:
                inv_metrics.append({"Chỉ tiêu": "Tốc độ tăng trưởng Hàng tồn kho", "Giá trị": f"{wc_curr['inv_growth']:.2%}"})
            st.dataframe(pd.DataFrame(inv_metrics), width="stretch", hide_index=True)
            
        with col_pay:
            st.markdown("#### 🤝 Phải trả người bán (311)")
            pay_metrics = []
            pay_metrics.append({"Chỉ tiêu": "Giá trị Phải trả người bán (311)", "Giá trị": f"{wc_curr['payables'] / 1e9:,.2f} tỷ VND"})
            pay_metrics.append({"Chỉ tiêu": "Tỷ trọng Phải trả / Tổng tài sản", "Giá trị": f"{wc_curr['payables_to_assets']:.2%}"})
            pay_metrics.append({"Chỉ tiêu": "Tỷ trọng Phải trả / Nợ ngắn hạn", "Giá trị": f"{wc_curr['payables_to_cl']:.2%}"})
            if dpo_val is not None:
                dpo_status = "⚠️ Chiếm dụng vốn lớn (>90d)" if dpo_val > 90 else "🟢 Bình thường"
                pay_metrics.append({"Chỉ tiêu": "Số ngày trả tiền bình quân (DPO)", "Giá trị": f"{dpo_val:.1f} ngày ({dpo_status})"})
            if wc_curr['payables_vs_cogs_spread'] is not None:
                pay_spread_status = "⚠️ Nợ người bán tăng vọt" if wc_curr['payables_vs_cogs_spread'] > 0.20 else "🟢 Tương quan hợp lý"
                pay_metrics.append({"Chỉ tiêu": "Độ lệch Tăng Nợ NB vs Giá vốn", "Giá trị": f"{wc_curr['payables_vs_cogs_spread']:+.2%} ({pay_spread_status})"})
            if wc_curr['payables_growth'] is not None:
                pay_metrics.append({"Chỉ tiêu": "Tốc độ tăng trưởng Nợ người bán", "Giá trị": f"{wc_curr['payables_growth']:.2%}"})
            st.dataframe(pd.DataFrame(pay_metrics), width="stretch", hide_index=True)
            
        # 4. Bảng dữ liệu chuỗi thời gian qua các năm & Biểu đồ CCC
        st.markdown("---")
        st.markdown("### 📈 4. Bảng theo dõi Cân đối Vốn & Chu kỳ Chuyển đổi Tiền mặt qua các năm")
        wc_table_rows = []
        for y in years_list:
            y_res = wc_debt_results[y]
            wc_table_rows.append({
                "Năm": str(y),
                "Phải thu (131)": f"{y_res['rec'] / 1e9:,.2f} tỷ",
                "Tồn kho (140)": f"{y_res['inv'] / 1e9:,.2f} tỷ",
                "Phải trả NB (311)": f"{y_res['payables'] / 1e9:,.2f} tỷ",
                "Nhu cầu OWC": f"{y_res['owc'] / 1e9:,.2f} tỷ",
                "Vốn vay ngắn hạn": f"{y_res['st_debt'] / 1e9:,.2f} tỷ",
                "Tỷ lệ Vay/(PT+TK)": f"{y_res['debt_to_wc_ratio']:.1%}",
                "DSO (Thu tiền)": f"{y_res['dso']:.1f} ngày" if y_res['dso'] is not None else "N/A",
                "DSI (Tồn kho)": f"{y_res['dsi']:.1f} ngày" if y_res['dsi'] is not None else "N/A",
                "DPO (Trả tiền)": f"{y_res['dpo']:.1f} ngày" if y_res['dpo'] is not None else "N/A",
                "Chu kỳ CCC": f"{y_res['ccc']:.1f} ngày" if y_res['ccc'] is not None else "N/A",
                "Trạng thái": y_res['zone']
            })
        st.dataframe(pd.DataFrame(wc_table_rows), width="stretch", hide_index=True)
        
        col_chart1, col_chart2 = st.columns(2)
        with col_chart1:
            st.markdown("##### 📊 So sánh Chu kỳ Hoạt động & Tiền mặt (Ngày)")
            ccc_chart_data = []
            for y in years_list:
                y_res = wc_debt_results[y]
                ccc_chart_data.append({
                    "Năm": str(y),
                    "DSO (Thu tiền KH)": y_res['dso'] if y_res['dso'] is not None else 0,
                    "DSI (Lưu kho)": y_res['dsi'] if y_res['dsi'] is not None else 0,
                    "DPO (Chiếm dụng NCC)": y_res['dpo'] if y_res['dpo'] is not None else 0,
                    "CCC (Chu kỳ tiền mặt)": y_res['ccc'] if y_res['ccc'] is not None else 0
                })
            st.bar_chart(pd.DataFrame(ccc_chart_data).set_index("Năm"), height=300)
            
        with col_chart2:
            st.markdown("##### 🏛️ Cân đối Vốn vay vs Nhu cầu OWC (Tỷ VND)")
            debt_chart_data = []
            for y in years_list:
                y_res = wc_debt_results[y]
                debt_chart_data.append({
                    "Năm": str(y),
                    "Vốn vay ngắn hạn (320)": y_res['st_debt'] / 1e9,
                    "Nhu cầu OWC": y_res['owc'] / 1e9,
                    "Phải thu + Tồn kho": y_res['wc_assets'] / 1e9
                })
            st.bar_chart(pd.DataFrame(debt_chart_data).set_index("Năm"), height=300)
            
        # 5. Hướng dẫn kiểm soát sau giải ngân cho Cán bộ Tín dụng (RM / RCO)
        st.markdown("### 📋 5. Checklist Kiểm soát Sau giải ngân & Chất vấn Doanh nghiệp")
        st.markdown("""
        * 🔎 **Kiểm tra Sao kê Dòng tiền Ngân hàng**: Đối chiếu dòng tiền thực thu từ khách hàng nợ (131) về tài khoản ngân hàng xem có khớp với doanh thu ghi nhận hay không.
        * 🔎 **Kiểm tra Hóa đơn GTGT & Hợp đồng kinh tế**: Yêu cầu cung cấp hóa đơn đầu ra/đầu vào tương ứng với biến động hàng tồn kho và các khoản phải thu lớn.
        * 🔎 **Xác thực Đối tác giao dịch (Phải thu & Phải trả)**: Rà soát xem các khoản phải thu/phải trả lớn có phải là bên liên quan (công ty sân sau, cổ đông nội bộ) nhằm mục đích chuyển giá hoặc rút ruột vốn vay hay không.
        * 🔎 **Kiểm tra biến động DPO (Nợ nhà cung cấp)**: Nếu DPO tăng đột biến (> 90 ngày) mà dòng tiền hoạt động âm $\\rightarrow$ DN có nguy cơ bị nhà cung cấp dừng giao hàng hoặc khởi kiện đòi nợ.
        * 🔎 **Kiểm tra mục đích sử dụng vốn thực tế**: Đối với các kỳ có tỷ lệ Vay / (PT + TK) > 100%, bắt buộc yêu cầu chứng từ thanh toán chứng minh vốn vay không bị chuyển hướng tài trợ mua sắm TSCĐ dài hạn hoặc đầu tư BĐS ngoài ngành.
        """)

    # ------------------ TAB 3: ĐÁNH GIÁ ĐỊNH TÍNH 5CS & HỆ SINH THÁI ------------------
    with tab_5cs:
        st.subheader("🏛️ Khung Đánh giá Rủi ro Định tính 5Cs & Hệ sinh thái Chuỗi Cung ứng")
        st.markdown("""
        Mô hình này bổ khuyết hạn chế của BCTC bằng cách chuẩn hóa đánh giá **5Cs**: **Uy tín Lãnh đạo (Character)**, **Năng lực Quản trị (Capacity)**, 
        **Tính Xác thực BCTC & Kiểm toán (Capital/Audit Quality)**, **Môi trường Ngành (Conditions)** và **Quan hệ Chuỗi Cung ứng & RPT (Ecosystem)**.
        """)
        
        # 1. Tổng quan Điểm & Radar 5Cs
        col_5c_sum1, col_5c_sum2 = st.columns([1.5, 2.5])
        with col_5c_sum1:
            st.markdown("#### 🎯 Điểm Định tính 5Cs Tổng Hợp")
            st.metric(
                label="Điểm Định tính Toàn diện",
                value=f"{res_5cs['total_qual_score']:.1f} / 100",
                delta=f"Hạng {hybrid_res['grade']}"
            )
            
            st.markdown("**Phân rã Điểm 5 Nhóm Tiêu chí:**")
            st.markdown(f"- 👤 **C1 - Uy tín Lãnh đạo (20%):** `{res_5cs['group_scores']['C1']:.1f} đ`")
            st.markdown(f"- ⚙️ **C2 - Năng lực Quản trị (20%):** `{res_5cs['group_scores']['C2']:.1f} đ`")
            st.markdown(f"- 📑 **C3 - BCTC & Kiểm toán (25%):** `{res_5cs['group_scores']['C3']:.1f} đ`")
            st.markdown(f"- 🏭 **C4 - Ngành & Cạnh tranh (15%):** `{res_5cs['group_scores']['C4']:.1f} đ`")
            st.markdown(f"- 🌐 **C5 - Chuỗi Cung ứng & RPT (20%):** `{res_5cs['group_scores']['C5']:.1f} đ`")
            
            st.info(f"""
            📌 **Chỉ số Giám sát Đặc biệt:**
            - **Độ tin cậy BCTC & Thuế:** {res_5cs['bctc_trust_level']}
            - **Rủi ro Chuỗi Cung ứng:** {res_5cs['supply_chain_risk']}
            """)
            
        with col_5c_sum2:
            st.markdown("#### 📊 Biểu đồ Radar 5 Trục Định Tính vs Ngưỡng Chuẩn (70đ)")
            radar_fig = render_5c_radar_chart(res_5cs["radar_data"])
            st.pyplot(radar_fig, use_container_width=True)
            
        st.markdown("---")
        st.subheader("📋 Bảng Tiêu chí Chấm điểm Định tính Chi tiết (5Cs Standard Rubrics)")
        
        tab_c1, tab_c2, tab_c3, tab_c4, tab_c5 = st.tabs([
            "👤 C1: Uy tín & Lãnh đạo (20%)",
            "⚙️ C2: Quản trị & Vận hành (20%)",
            "📑 C3: BCTC & Kiểm toán / Thuế (25%)",
            "🏭 C4: Ngành & Cạnh tranh (15%)",
            "🌐 C5: Chuỗi Cung ứng & Hệ sinh thái (20%)"
        ])
        
        updated_answers = {}
        
        # TAB C1
        with tab_c1:
            st.markdown("##### 👤 C1: Đánh giá Năng lực & Uy tín của Ban Lãnh đạo (Trọng số 20%)")
            for k in ["c1_mgmt_exp", "c1_cic_history", "c1_owner_commitment", "c1_legal_compliance"]:
                cfg = DEFAULT_5C_CONFIG[k]
                opt_list = list(cfg["options"].keys())
                curr_val = st.session_state.get(f"5c_{k}", user_5c_answers.get(k, cfg["default"]))
                curr_idx = opt_list.index(curr_val) if curr_val in opt_list else 0
                sel = st.selectbox(f"**{cfg['label']}**", opt_list, index=curr_idx, key=f"sel_5c_{k}")
                st.caption(f"⭐ Điểm tiêu chí: **{cfg['options'][sel]} / 100 điểm**")
                updated_answers[k] = sel
                st.session_state[f"5c_{k}"] = sel
                
        # TAB C2
        with tab_c2:
            st.markdown("##### ⚙️ C2: Năng lực Quản trị, KSoNB & Chuyển đổi số (Trọng số 20%)")
            for k in ["c2_board_structure", "c2_internal_control", "c2_erp_tech", "c2_hr_stability"]:
                cfg = DEFAULT_5C_CONFIG[k]
                opt_list = list(cfg["options"].keys())
                curr_val = st.session_state.get(f"5c_{k}", user_5c_answers.get(k, cfg["default"]))
                curr_idx = opt_list.index(curr_val) if curr_val in opt_list else 0
                sel = st.selectbox(f"**{cfg['label']}**", opt_list, index=curr_idx, key=f"sel_5c_{k}")
                st.caption(f"⭐ Điểm tiêu chí: **{cfg['options'][sel]} / 100 điểm**")
                updated_answers[k] = sel
                st.session_state[f"5c_{k}"] = sel
                
        # TAB C3
        with tab_c3:
            st.markdown("##### 📑 C3: Tính Minh bạch BCTC, Đơn vị Kiểm toán & Đối chiếu Thuế (Trọng số 25%)")
            st.warning("⚠️ **Ghi chú Thẩm định**: BCTC cần được kiểm tra chéo với Tờ khai Thuế GTGT và Thuế TNDN quyết toán để phòng ngừa rủi ro 'hai sổ sách' hoặc bóp méo doanh thu.")
            for k in ["c3_audit_firm", "c3_audit_opinion", "c3_tax_consistency", "c3_disclosure_quality"]:
                cfg = DEFAULT_5C_CONFIG[k]
                opt_list = list(cfg["options"].keys())
                curr_val = st.session_state.get(f"5c_{k}", user_5c_answers.get(k, cfg["default"]))
                curr_idx = opt_list.index(curr_val) if curr_val in opt_list else 0
                sel = st.selectbox(f"**{cfg['label']}**", opt_list, index=curr_idx, key=f"sel_5c_{k}")
                st.caption(f"⭐ Điểm tiêu chí: **{cfg['options'][sel]} / 100 điểm**")
                updated_answers[k] = sel
                st.session_state[f"5c_{k}"] = sel
                
        # TAB C4
        with tab_c4:
            st.markdown("##### 🏭 C4: Môi trường Ngành & Vị thế Cạnh tranh (Trọng số 15%)")
            for k in ["c4_market_position", "c4_entry_barriers", "c4_cyclical_risk"]:
                cfg = DEFAULT_5C_CONFIG[k]
                opt_list = list(cfg["options"].keys())
                curr_val = st.session_state.get(f"5c_{k}", user_5c_answers.get(k, cfg["default"]))
                curr_idx = opt_list.index(curr_val) if curr_val in opt_list else 0
                sel = st.selectbox(f"**{cfg['label']}**", opt_list, index=curr_idx, key=f"sel_5c_{k}")
                st.caption(f"⭐ Điểm tiêu chí: **{cfg['options'][sel]} / 100 điểm**")
                updated_answers[k] = sel
                st.session_state[f"5c_{k}"] = sel
                
        # TAB C5
        with tab_c5:
            st.markdown("##### 🌐 C5: Quan hệ Chuỗi Cung ứng & Giao dịch Bên liên quan (RPT) trong Hệ sinh thái (Trọng số 20%)")
            st.info("💡 **Giải thích từ Ban Giám khảo**: Kiểm soát mức độ tập trung khách hàng/nhà cung cấp và giao dịch nội bộ giúp phát hiện sớm nguy cơ chuyển giá hoặc rút ruột dòng tiền.")
            for k in ["c5_customer_concentration", "c5_supplier_concentration", "c5_related_party_rpt", "c5_bargaining_power"]:
                cfg = DEFAULT_5C_CONFIG[k]
                opt_list = list(cfg["options"].keys())
                curr_val = st.session_state.get(f"5c_{k}", user_5c_answers.get(k, cfg["default"]))
                curr_idx = opt_list.index(curr_val) if curr_val in opt_list else 0
                sel = st.selectbox(f"**{cfg['label']}**", opt_list, index=curr_idx, key=f"sel_5c_{k}")
                st.caption(f"⭐ Điểm tiêu chí: **{cfg['options'][sel]} / 100 điểm**")
                updated_answers[k] = sel
                st.session_state[f"5c_{k}"] = sel

        st.markdown("---")
        col_btn_save1, col_btn_save2 = st.columns([2, 2])
        with col_btn_save1:
            if st.button("💾 Lưu Toàn Bộ Đánh Giá Định Tính 5Cs Vào SQLite Database", type="primary", use_container_width=True, key="btn_save_5cs_to_db"):
                if main_ticker != "N/A":
                    for year in years_list:
                        for k, v in updated_answers.items():
                            extracted_data[year][f"Qual_5C_{k}"] = v
                        extracted_data[year]["Qual_5C_TotalScore"] = res_5cs["total_qual_score"]
                    save_to_db(main_ticker, summary_company_name, extracted_data)
                    st.success("💾 Đã lưu thành công điểm định tính 5Cs vào cơ sở dữ liệu SQLite!")
                    st.toast("Đã lưu hồ sơ định tính 5Cs!", icon="🗄️")
                    st.rerun()

    # ------------------ TAB 4: SAO KÊ DÒNG TIỀN NGÂN HÀNG & GIÁM SÁT SAU GIẢI NGÂN ------------------
    with tab_bank_stmt:
        st.subheader(f"💳 Phân tích Sao kê Dòng tiền Ngân hàng & Giám sát Sau Giải ngân ({main_ticker})")
        st.markdown("""
        Mô hình này giải quyết **độ trễ thông tin của BCTC** (thường chậm 1–3 tháng) bằng cách phân tích dữ liệu dòng tiền tần suất cao 
        (High-Frequency Data) từ sao kê tài khoản ngân hàng. Giúp cán bộ tín dụng kiểm soát tính **đều đặn của dòng tiền**, 
        **mục đích sử dụng vốn vay** và **tính đúng ngành nghề kinh doanh**.
        """)
        
        # 1. Tùy chọn nguồn dữ liệu sao kê
        col_st_opt1, col_st_opt2 = st.columns([2, 2])
        with col_st_opt1:
            data_source_mode = st.radio(
                "Nguồn dữ liệu sao kê tài khoản:",
                [f"⚡ Sử dụng Sao kê Mẫu Thực tế của {main_ticker} (12 tháng)", "📂 Tải tệp Sao kê Ngân hàng (Excel / CSV)"],
                index=0,
                key="bank_stmt_data_source_radio"
            )
            
        ann_sales = extracted_data[selected_year].get("Net_Sales", 0.0) if selected_year in extracted_data else 30000e9
        ann_cogs = extracted_data[selected_year].get("COGS", 0.0) if selected_year in extracted_data else 25000e9
        
        df_statement_raw = None
        
        with col_st_opt2:
            if "Tải tệp" in data_source_mode:
                uploaded_stmt = st.file_uploader("Tải lên file Sao kê (.xlsx, .csv)", type=["xlsx", "xls", "csv"], key="bank_stmt_file_uploader")
                if uploaded_stmt is not None:
                    try:
                        if uploaded_stmt.name.endswith(".csv"):
                            df_statement_raw = pd.read_csv(uploaded_stmt)
                        else:
                            df_statement_raw = pd.read_excel(uploaded_stmt)
                        st.success(f"✅ Đã tải lên {len(df_statement_raw)} dòng giao dịch từ `{uploaded_stmt.name}`!")
                    except Exception as e:
                        st.error(f"Lỗi đọc file sao kê: {e}")
            else:
                st.info(f"💡 Đang áp dụng bộ dữ liệu sao kê 12 tháng mô phỏng thực tế cho doanh nghiệp **{summary_company_name}** theo quy mô doanh thu BCTC năm {selected_year} ({ann_sales/1e9:,.1f} tỷ VND).")
                df_statement_raw = generate_mock_bank_statement_data(
                    ticker=main_ticker,
                    company_name=summary_company_name,
                    annual_revenue=ann_sales,
                    annual_cogs=ann_cogs
                )

        if df_statement_raw is not None and not df_statement_raw.empty:
            stmt_analysis = parse_and_analyze_bank_statement(df_statement_raw, annual_sales_target=ann_sales)
            
            # 2. Bảng 4 Thẻ KPI Giám sát Dòng tiền
            st.markdown("### 📊 1. Chỉ số Giám sát Dòng tiền Thực tế & Độ Đều đặn")
            col_kpi1, col_kpi2, col_kpi3, col_kpi4 = st.columns(4)
            
            with col_kpi1:
                st.markdown(f"""
                <div class="metric-card metric-green">
                    <h5 style='margin: 0; color: #4a5568; font-size: 0.85em;'>TỔNG DÒNG TIỀN VÀO (INFLOW)</h5>
                    <h2 style='margin: 6px 0; color: #22543d; font-size: 1.6em;'>{stmt_analysis['total_inflow'] / 1e9:,.2f} tỷ</h2>
                    <p style='margin: 0; font-size: 0.8em; color: #718096;'>Chi ra: <b>{stmt_analysis['total_outflow'] / 1e9:,.2f} tỷ</b></p>
                </div>
                """, unsafe_allow_html=True)
                
            with col_kpi2:
                cv_pct = stmt_analysis['cv_in']
                cv_color = "#22543d" if cv_pct < 0.30 else ("#9c4221" if cv_pct < 0.60 else "#9b2c2c")
                card_type = "metric-green" if cv_pct < 0.30 else ("metric-yellow" if cv_pct < 0.60 else "metric-red")
                st.markdown(f"""
                <div class="metric-card {card_type}">
                    <h5 style='margin: 0; color: #4a5568; font-size: 0.85em;'>ĐỘ ĐỀU ĐẶN DÒNG TIỀN (CV)</h5>
                    <h2 style='margin: 6px 0; color: {cv_color}; font-size: 1.6em;'>{stmt_analysis['regularity_score']:.1f}<span style='font-size: 0.5em; color: #718096;'> / 100</span></h2>
                    <p style='margin: 0; font-size: 0.8em; font-weight: bold; color: {cv_color};'>{stmt_analysis['reg_status'].split('(')[0]}</p>
                </div>
                """, unsafe_allow_html=True)
                
            with col_kpi3:
                comp_pct = stmt_analysis['compliance_ratio']
                comp_color = "#22543d" if comp_pct >= 0.95 else ("#9c4221" if comp_pct >= 0.85 else "#9b2c2c")
                card_comp = "metric-green" if comp_pct >= 0.95 else ("metric-yellow" if comp_pct >= 0.85 else "metric-red")
                st.markdown(f"""
                <div class="metric-card {card_comp}">
                    <h5 style='margin: 0; color: #4a5568; font-size: 0.85em;'>TUÂN THỦ MỤC ĐÍCH & NGÀNH</h5>
                    <h2 style='margin: 6px 0; color: {comp_color}; font-size: 1.6em;'>{comp_pct:.1%}</h2>
                    <p style='margin: 0; font-size: 0.8em; color: #718096;'>Chi ngoài ngành: <b>{stmt_analysis['flagged_amount'] / 1e9:,.2f} tỷ</b></p>
                </div>
                """, unsafe_allow_html=True)
                
            with col_kpi4:
                cap_pct = stmt_analysis['capture_ratio']
                if cap_pct is not None:
                    cap_color = "#22543d" if cap_pct >= 0.70 else ("#9c4221" if cap_pct >= 0.50 else "#9b2c2c")
                    card_cap = "metric-green" if cap_pct >= 0.70 else ("metric-yellow" if cap_pct >= 0.50 else "metric-red")
                    cap_str = f"{cap_pct:.1%}"
                    cap_desc = "Đạt chuẩn cam kết (>=70%)" if cap_pct >= 0.70 else "CẢNH BÁO: Rò rỉ dòng tiền"
                else:
                    cap_color = "#718096"
                    card_cap = "metric-card"
                    cap_str = "N/A"
                    cap_desc = "Không có số liệu DT"
                st.markdown(f"""
                <div class="metric-card {card_cap}">
                    <h5 style='margin: 0; color: #4a5568; font-size: 0.85em;'>TỶ LỆ DOANH THU VỀ TÀI KHOẢN</h5>
                    <h2 style='margin: 6px 0; color: {cap_color}; font-size: 1.6em;'>{cap_str}</h2>
                    <p style='margin: 0; font-size: 0.8em; font-weight: bold; color: {cap_color};'>{cap_desc}</p>
                </div>
                """, unsafe_allow_html=True)

            # 3. Biểu đồ Dòng tiền theo tháng & Biến động số dư
            st.markdown("---")
            st.markdown("### 📈 2. Diễn biến Dòng tiền Thu/Chi Hàng Tháng & Số dư Thanh khoản")
            
            col_chart_m1, col_chart_m2 = st.columns(2)
            with col_chart_m1:
                st.markdown("##### 💵 So sánh Dòng tiền Vào (Thu) vs Chi (Ra) Từng Tháng (Tỷ VND)")
                if not stmt_analysis['monthly_grp'].empty:
                    m_df = stmt_analysis['monthly_grp'].copy()
                    cols_m = m_df.columns
                    m_df[cols_m[1]] = m_df[cols_m[1]] / 1e9
                    m_df[cols_m[2]] = m_df[cols_m[2]] / 1e9
                    m_df.rename(columns={cols_m[1]: "Dòng tiền Vào (Ghi Có)", cols_m[2]: "Dòng tiền Ra (Ghi Nợ)", "_Month": "Tháng"}, inplace=True)
                    st.bar_chart(m_df.set_index("Tháng"), height=290)
                else:
                    st.info("Không có dữ liệu theo tháng.")
                    
            with col_chart_m2:
                st.markdown("##### 🏛️ Diễn biến Số dư Tài khoản Ngân hàng (Tỷ VND)")
                raw_df_b = stmt_analysis['raw_df'].copy()
                if "Ngày GD" in raw_df_b.columns and "Số dư (VND)" in raw_df_b.columns:
                    raw_df_b["Số dư (Tỷ VND)"] = raw_df_b["Số dư (VND)"] / 1e9
                    st.line_chart(raw_df_b.set_index("Ngày GD")["Số dư (Tỷ VND)"], height=290)
                else:
                    st.info("Không có dữ liệu số dư.")

            # 4. Mạng lưới Đối tác Dòng tiền (Top Counterparties)
            st.markdown("---")
            st.markdown("### 🤝 3. Phân tích Mạng lưới Đối tác Giao dịch (Top Counterparties)")
            col_part1, col_part2 = st.columns(2)
            
            with col_part1:
                st.markdown("##### 📥 Top 5 Khách hàng nộp tiền nhiều nhất (Dòng tiền vào)")
                if not stmt_analysis['top_in_partners'].empty:
                    df_tin = stmt_analysis['top_in_partners'].copy()
                    df_tin["Doanh số vào"] = df_tin["Doanh số vào (VND)"].apply(lambda x: f"{x/1e9:,.2f} tỷ VND")
                    df_tin["Tỷ trọng"] = df_tin["Tỷ trọng"].apply(lambda x: f"{x:.1%}")
                    st.dataframe(df_tin[["Đối tác nộp tiền", "Doanh số vào", "Tỷ trọng"]], width="stretch", hide_index=True)
                else:
                    st.caption("Không có dữ liệu đối tác nộp tiền.")
                    
            with col_part2:
                st.markdown("##### 📤 Top 5 Nhà cung cấp nhận tiền nhiều nhất (Dòng tiền chi)")
                if not stmt_analysis['top_out_partners'].empty:
                    df_tout = stmt_analysis['top_out_partners'].copy()
                    df_tout["Doanh số chi"] = df_tout["Doanh số chi (VND)"].apply(lambda x: f"{x/1e9:,.2f} tỷ VND")
                    df_tout["Tỷ trọng"] = df_tout["Tỷ trọng"].apply(lambda x: f"{x:.1%}")
                    st.dataframe(df_tout[["Đối tác nhận tiền", "Doanh số chi", "Tỷ trọng"]], width="stretch", hide_index=True)
                else:
                    st.caption("Không có dữ liệu đối tác nhận tiền.")

            # 5. Bảng Cảnh báo Giao dịch Bất thường & Rủi ro Sau Giải ngân
            st.markdown("---")
            st.markdown("### ⚠️ 4. Danh mục Giao dịch Bất thường & Cảnh báo Sai Mục đích Vay")
            
            if stmt_analysis['flagged_txns']:
                st.warning(f"🚨 Phát hiện **{len(stmt_analysis['flagged_txns'])} giao dịch** có dấu hiệu sai mục đích sử dụng vốn vay hoặc chuyển tiền ngoài ngành kinh doanh chính (Tổng giá trị: **{stmt_analysis['flagged_amount']/1e9:,.2f} tỷ VND**).")
                df_flags = pd.DataFrame(stmt_analysis['flagged_txns'])
                df_flags["Số tiền Chi"] = df_flags["Số tiền Chi (VND)"].apply(lambda x: f"{x/1e9:,.2f} tỷ VND")
                st.dataframe(df_flags[["Ngày", "Đối tác", "Số tiền Chi", "Nội dung", "Cảnh báo"]], width="stretch", hide_index=True)
            else:
                st.success("🟢 Không phát hiện giao dịch bất thường hoặc sai mục đích sử dụng vốn trong kỳ sao kê.")

            # 6. Sổ tay Thẩm tra Sau Giải ngân cho Cán bộ Tín dụng (RM / RCO Action Sheet)
            st.markdown("---")
            st.markdown("### 📋 5. Khuyến nghị Nghiệp vụ Kiểm soát Sau Giải ngân (RM / RCO Action Sheet)")
            
            cap_action = "🟢 Doanh nghiệp thực hiện nghiêm túc cam kết dòng tiền về tài khoản ngân hàng." if (cap_pct and cap_pct >= 0.70) else "🔴 **CẢNH BÁO RÒ RỈ DÒNG TIỀN**: Tỷ lệ doanh thu về tài khoản dưới 70%. Yêu cầu làm việc với Ban Giám đốc và đối tác mua hàng để nắn dòng tiền về tài khoản ngân hàng tài trợ."
            dscr_action = f"🟢 Khả năng trả nợ tốt (Hệ số DSCR thực tế từ dòng tiền = {stmt_analysis['dscr_bank']:.2f} lần)." if stmt_analysis['dscr_bank'] >= 1.5 else f"🟡 Khả năng bao phủ nghĩa vụ nợ sát ngưỡng (DSCR = {stmt_analysis['dscr_bank']:.2f} lần). Cần theo dõi chặt chẽ dòng thu nợ từng tháng."
            
            st.markdown(f"""
            * 📌 **Đánh giá Cam kết Dòng tiền**: {cap_action}
            * 📌 **Đánh giá Khả năng Trả nợ Vay**: {dscr_action}
            * 📌 **Kiểm tra Chứng từ Gốc**: Yêu cầu cung cấp Hợp đồng mua bán và Hóa đơn GTGT đối với các khoản chi thanh toán lớn cho Top 3 nhà cung cấp.
            * 📌 **Thẩm tra các khoản rút vốn**: Giải trình mục đích sử dụng vốn đối với các khoản tiền rút séc hoặc tạm ứng cá nhân ban điều hành.
            """)
            
            with st.expander("🔍 Xem toàn bộ dữ liệu Bảng Sao kê Chi tiết"):
                st.dataframe(stmt_analysis['raw_df'], width="stretch")
        else:
            st.warning("Vui lòng chọn hoặc tải lên file dữ liệu sao kê để thực hiện phân tích.")

    # ------------------ TAB 5: BIẾN KIỂM SOÁT BỔ SUNG ------------------
    with tab_controls:
        st.subheader(f"Hệ thống Biến Kiểm Soát Thẩm Định (Năm {selected_year})")
        st.info("Các biến kiểm soát bổ trợ được phân loại thành 4 mức rủi ro (Mức 1 = an toàn → Mức 4 = rủi ro cao) nhằm tăng cường độ tin cậy của mô hình EWS chính.")
        
        # A. KHỐI ĐỊNH TÍNH (VĂN BẢN)
        st.markdown("### 📝 A. Biến Kiểm Soát Định Tính / Văn Bản (Báo cáo Thường niên)")
        
        col_qa1, col_qa2 = st.columns([2, 3])
        with col_qa1:
            st.markdown("**10 Tiêu chuẩn Quản trị Công ty (GovDisc)**")
            gov_labels = [
                "1. Cơ cấu HĐQT rõ ràng, minh bạch",
                "2. Có thành viên độc lập HĐQT (>= 20%)",
                "3. Đầy đủ báo cáo giao dịch bên liên quan",
                "4. Công khai chi tiết thù lao HĐQT/Ban giám đốc",
                "5. Công bố sở hữu cổ phần nội bộ rõ ràng",
                "6. Tổ chức ĐHĐCĐ thường niên đúng quy định",
                "7. Có bộ phận kiểm toán nội bộ độc lập",
                "8. Công bố báo cáo Phát triển bền vững (ESG)",
                "9. Không bị xử phạt hành chính thuế/chứng khoán",
                "10. BCTC được kiểm toán bởi Big 4 hoặc uy tín"
            ]
            
            checklist_vals = []
            for idx, label in enumerate(gov_labels):
                val = st.checkbox(label, value=st.session_state["gov_checklist"][idx], key=f"gov_chk_{idx}")
                checklist_vals.append(val)
            
            # Cập nhật session state
            st.session_state["gov_checklist"] = checklist_vals
            
            # Nút lưu thủ công
            if st.button("💾 Lưu Checklist & Tham số Định tính", use_container_width=True):
                if main_ticker != "N/A":
                    for year in years_list:
                        extracted_data[year]["Qual_RiskWord"] = risk_words_ratio_input
                        extracted_data[year]["Qual_NegTone"] = neg_tone_ratio_input
                        extracted_data[year]["Qual_ReportLen"] = report_len_input
                        extracted_data[year]["Qual_TextSim"] = text_sim_input
                        extracted_data[year]["Qual_IsBDS"] = 1.0 if is_bds_input else 0.0
                        extracted_data[year]["Qual_GovDisc"] = sum(checklist_vals) / 10.0
                        extracted_data[year]["Qual_CEOAge"] = float(ceo_age_input)
                        extracted_data[year]["Qual_Industry"] = str(industry_input)
                        
                    save_to_db(main_ticker, summary_company_name, extracted_data)
                    st.success("💾 Đã lưu thay đổi hồ sơ định tính thành công!")
                    st.toast("Đã cập nhật SQLite database!", icon="💾")
                    
        with col_qa2:
            st.markdown("**Bảng điểm rủi ro định tính**")
            res_ctrl = control_results[selected_year]
            
            qual_vars = {
                "RiskWord": ("Tần suất từ rủi ro (RiskWord)", "‰ (phần nghìn)"),
                "NegTone": ("Sắc thái tiêu cực (NegTone)", "%"),
                "ReportLen": ("Độ dài báo cáo (ReportLen)", " từ"),
                "GovDisc": ("Điểm quản trị (GovDisc)", "%"),
                "TextSim": ("Độ tương đồng văn bản (TextSim)", "%"),
                "CEOAge": ("Độ tuổi CEO (CEOAge)", " tuổi")
            }
            
            qual_rows = []
            for var_key, (var_name, unit) in qual_vars.items():
                data_val = res_ctrl.get(var_key)
                if data_val:
                    val = data_val["value"]
                    lvl = data_val["level"]
                    desc = data_val["desc"]
                    
                    if var_key in ["NegTone", "TextSim", "GovDisc"]:
                        val_str = f"{val:.2%}"
                    elif var_key == "CEOAge":
                        val_str = f"{val:.0f} tuổi"
                    else:
                        val_str = f"{val:,.1f}" if var_key == "RiskWord" else f"{val:,.0f}"
                        
                    color = "🟢 Mức 1 (An toàn)" if lvl == 1 else ("🔵 Mức 2 (Nhẹ)" if lvl == 2 else ("🟡 Mức 3 (Trung bình)" if lvl == 3 else "🔴 Mức 4 (Rủi ro cao)"))
                    qual_rows.append({
                        "Chỉ số định tính": var_name,
                        "Giá trị": val_str,
                        "Phân loại rủi ro": color,
                        "Diễn giải chi tiết": desc
                    })
            
            if qual_rows:
                st.table(pd.DataFrame(qual_rows))
            else:
                st.warning("Không có dữ liệu định tính.")
                
        # B. KHỐI TÀI CHÍNH (QUANTITATIVE CONTROLS)
        st.markdown("---")
        st.markdown("### 📊 B. Biến Kiểm Soát Tài Chính Chuẩn (Quantitative Controls)")
        
        fin_vars = {
            "SIZE": ("ln Tổng tài sản (SIZE)", "Quy mô"),
            "LEV": ("Đòn bẩy tài chính (LEV)", "Cơ cấu vốn"),
            "ROA": ("Tỷ suất sinh lời / TS (ROA)", "Hiệu quả sinh lời"),
            "GROWTH": ("Tăng trưởng doanh thu (GROWTH)", "Tăng trưởng"),
            "CR": ("Hệ số thanh toán hiện thời (CR)", "Thanh khoản"),
            "WC_TA": ("Vốn lưu động / Tổng TS (WC/TA)", "Thanh khoản"),
            "RE_TA": ("LN sau thuế chưa PP / Tổng TS (RE/TA)", "Tích lũy"),
            "EBIT_TA": ("EBIT / Tổng tài sản (EBIT/TA)", "Sinh lời HĐKD"),
            "ATO": ("Hiệu suất sử dụng tài sản (ATO)", "Vòng quay TS"),
            "INVEST": ("Cường độ đầu tư ròng (INVEST)", "Tái đầu tư"),
            "CF": ("Dòng tiền hoạt động kinh doanh (CF)", "Chất lượng tiền"),
            "ACCR": ("Dồn tích / Tổng tài sản (ACCR)", "Chất lượng lợi nhuận"),
            "SOFT": ("Tỷ trọng tài sản mềm (SOFT)", "Chất lượng tài sản")
        }
        
        fin_rows = []
        for var_key, (var_name, category) in fin_vars.items():
            data_val = res_ctrl.get(var_key)
            if data_val:
                val = data_val["value"]
                lvl = data_val["level"]
                desc = data_val["desc"]
                
                if pd.isna(val) or val is None:
                    val_str = "N/A"
                elif var_key in ["LEV", "ROA", "GROWTH", "WC_TA", "RE_TA", "EBIT_TA", "INVEST", "CF", "ACCR", "SOFT"]:
                    val_str = f"{val:.2%}"
                else:
                    val_str = f"{val:.2f}"
                    
                color = "🟢 Mức 1 (An toàn)" if lvl == 1 else ("🔵 Mức 2 (Nhẹ)" if lvl == 2 else ("🟡 Mức 3 (Trung bình)" if lvl == 3 else "🔴 Mức 4 (Rủi ro cao)"))
                fin_rows.append({
                    "Nhóm phân tích": category,
                    "Biến kiểm soát tài chính": var_name,
                    "Giá trị": val_str,
                    "Phân loại rủi ro": color,
                    "Diễn giải ngưỡng": desc
                })
        
        if fin_rows:
            st.dataframe(pd.DataFrame(fin_rows), use_container_width=True, hide_index=True)
        else:
            st.warning("Không đủ dữ liệu tài chính để phân tích biến kiểm soát.")

    # ------------------ TAB 2: CHỈ SỐ EWS THÀNH PHẦN ------------------
    with tab_components:
        st.subheader(f"Bảng tổng hợp chi tiết 10 Chỉ số EWS (Năm {selected_year})")
        
        res = ews_results[selected_year]
        rows = []
        
        # Helper to add row
        def add_indicator_row(name, data, threshold_desc, explanation):
            if data:
                rows.append({
                    "Chỉ số": name,
                    "Giá trị": f"{data['score']:.2%}" if name in ["4. Beneish M-Score (1997 - 12 biến)", "11. Dự báo ML tùy chỉnh (Gian lận VN)"] else f"{data['score']:.4f}",
                    "Ngưỡng cảnh báo": threshold_desc,
                    "Trạng thái": data['zone'],
                    "Diễn giải nghiệp vụ": explanation
                })
            else:
                rows.append({
                    "Chỉ số": name,
                    "Giá trị": "N/A",
                    "Ngưỡng cảnh báo": threshold_desc,
                    "Trạng thái": "⚪ Thiếu dữ liệu / Không tìm thấy file model",
                    "Diễn giải nghiệp vụ": explanation
                })
        
        # Add all 11 indicators
        add_indicator_row("1. Altman Z'-Score (Khả năng phá sản)", res.get("Altman_Z_Prime"), "Z' < 1.23 (Nguy hiểm), Z' > 2.90 (An toàn)", "Dự báo xác suất kiệt quệ tài chính trong 2 năm tới của doanh nghiệp sản xuất/tư nhân.")
        add_indicator_row("2. SA Index (Hạn chế tài chính)", res.get("SA_Index"), "Chỉ số càng cao thể hiện khả năng tiếp cận vốn bên ngoài càng khó", "Đo lường mức độ thắt chặt tài chính dựa trên quy mô tài sản và tuổi doanh nghiệp.")
        add_indicator_row("3. Beneish M-Score (1999 - 8 biến)", res.get("Beneish_M_Score"), "M > -1.78 (Nguy cơ cao), M < -2.22 (Rủi ro thấp)", "Đánh giá xác suất doanh nghiệp thao túng báo cáo tài chính bằng 8 tỷ số kế toán cơ bản.")
        add_indicator_row("4. Beneish M-Score (1997 - 12 biến)", res.get("Beneish_M_Score_12"), "P > 6.75% (Cảnh báo đỏ), P <= 3.00% (An toàn)", "Mô hình Probit đầy đủ kết hợp các biến động cơ và bối cảnh (phát hành CK, abnormal return...).")
        add_indicator_row("5. Dechow F-Score (2011)", res.get("Dechow_F_Score"), "F > 1.85 (Rủi ro đáng kể), F <= 1.00 (Rủi ro thấp)", "Đo lường xác suất sai lệch trọng yếu trong BCTC so với xác suất trung bình toàn thị trường.")
        add_indicator_row("6. Abnormal CFO (Ab_CFO)", res.get("Abnormal_CFO"), "Ab_CFO < -0.05 (Dòng tiền thấp bất thường)", "Đo lường việc nới lỏng chính sách bán hàng trả chậm hoặc tăng doanh thu khống gây âm dòng tiền.")
        add_indicator_row("7. Abnormal Production (Ab_PROD)", res.get("Abnormal_PROD"), "Ab_PROD > 0.05 (Chi phí SX cao bất thường)", "Phát hiện hành vi sản xuất vượt mức để giảm chi phí cố định đơn vị, làm giảm giá vốn hàng bán.")
        add_indicator_row("8. Abnormal Discretionary Exp (Ab_DISEXP)", res.get("Abnormal_DISEXP"), "Ab_DISEXP < -0.03 (Chi phí hoạt động thấp bất thường)", "Phát hiện hành vi cắt giảm chi phí bán hàng & quản lý tùy quyết để làm đẹp lợi nhuận ngắn hạn.")
        add_indicator_row("9. KZ Index (Hạn chế tài chính)", res.get("KZ_Index"), "KZ > 3.0 (Thắt chặt cao), KZ <= 1.5 (Rủi ro thấp)", "Mô hình đa chiều đo lường mức độ hạn chế tiếp cận vốn từ 5 chiều (dòng tiền, nợ, tiền mặt, cổ tức, cơ hội Q).")
        add_indicator_row("10. WW Index (Hạn chế tài chính)", res.get("WW_Index"), "WW > -0.20 (Thắt chặt cao), WW <= -0.40 (Rủi ro thấp)", "Mô hình Whited-Wu xác định mức độ khó khăn tài chính kết hợp biến kiểm soát ngành.")
        add_indicator_row("11. Dự báo ML tùy chỉnh (Gian lận VN)", res.get("Custom_ML_Fraud"), "P > 50.00% (Báo động đỏ), P > 20.00% (Nghi vấn)", "Mô hình học máy Logistic Regression được huấn luyện riêng trên tập dữ liệu Việt Nam để dự báo xác suất thao túng.")
        
        df_comp = pd.DataFrame(rows)
        st.dataframe(df_comp, use_container_width=True, hide_index=True)
        
        st.markdown("""
        **Hướng dẫn phân tích từ Giải pháp (Solutions Architect)**:
        * Cán bộ thẩm định tín dụng cần chú ý đặc biệt đến **các cảnh báo đỏ (Red Flags)** trên các mô hình bổ trợ lẫn nhau (ví dụ: cả M-Score và Dechow F-Score cùng cảnh báo).
        * Đối với doanh nghiệp sản xuất, **Ab_PROD (sản xuất quá mức)** và **Ab_CFO (dòng tiền bất thường)** là 2 chỉ số cực kỳ quan trọng thể hiện chất lượng lợi nhuận thực tế.
        """)

    # ------------------ TAB 3: EXTRACED VARIABLES ------------------
    with tab_variables:
        st.subheader("Bảng dữ liệu tài chính trích xuất gốc")
        st.write("Toàn bộ các chỉ tiêu số liệu thô được quét từ file BCTC tải lên dựa trên hệ thống mã tài khoản kế toán chuẩn:")
        
        st.info("""
        💡 **Lưu ý về chất lượng file & ô dữ liệu N/A (Màu vàng):**
        * **Nguyên nhân xuất hiện N/A**: Đối với các tài liệu **PDF dạng ảnh quét (Scan/OCR)**, nếu chất lượng bản scan bị mờ, lệch trục, trang giấy nhăn, dính watermark hoặc có bố cục bảng biểu phi tiêu chuẩn, công cụ OCR có thể không nhận diện được đầy đủ mã số chỉ tiêu.
        * **Khuyến nghị**: Ưu tiên sử dụng file **Excel BCTC (.xlsx)** hoặc **PDF xuất trực tiếp từ phần mềm kế toán/bản điện tử chính thức** để đảm bảo tỷ lệ trích xuất chính xác 100%.
        * **Tính minh bạch**: Hệ thống hiển thị `N/A` thay vì tự ý suy đoán/bịa số liệu (tránh hallucination), giúp chuyên viên thẩm định phát hiện ngay các khoảng trống dữ liệu để đối chiếu lại BCTC gốc.
        """)
        
        table_rows = []
        for var_key, var_name_vn in VAR_NAMES_VN.items():
            row_dict = {"Chỉ tiêu kế toán": var_name_vn}
            for y in years_list:
                # Tuyệt đối tránh hallucination: nếu không trích xuất được thì ghi 'N/A'
                val = extracted_data[y].get(var_key, None)
                row_dict[f"Năm {y}"] = f"{val:,.0f} đ" if val is not None else "N/A"
            table_rows.append(row_dict)
            
        df_display = pd.DataFrame(table_rows)

        # ---- Bảng HTML với cố định hàng tiêu đề (row 1) + cố định cột 1 (Chỉ tiêu kế toán) ----
        cols = list(df_display.columns)   # ["Chỉ tiêu kế toán", "Năm 2023", ...]

        header_html = "".join(
            f'<th style="position:sticky;top:0;{"left:0;" if i==0 else ""}z-index:{"3" if i==0 else "2"};'
            f'background:#1f4e79;color:#ffffff;padding:8px 12px;white-space:nowrap;'
            f'border-right:1px solid #3a6fa0;font-size:0.82rem;">{c}</th>'
            for i, c in enumerate(cols)
        )

        rows_html = ""
        for ridx, row in df_display.iterrows():
            row_bg = "#f7fbff" if ridx % 2 == 0 else "#ffffff"
            cells = ""
            for cidx, c in enumerate(cols):
                val = row[c]
                is_na = (val == "N/A")
                cell_color = "#fff3cd" if is_na else row_bg  # highlight N/A ô vàng
                text_color = "#c0392b" if is_na else "#2d3748"
                sticky_style = (
                    f"position:sticky;left:0;z-index:1;background:{cell_color};"
                    f"font-weight:600;border-right:2px solid #bee3f8;"
                ) if cidx == 0 else f"background:{cell_color};"
                cells += (
                    f'<td style="{sticky_style}color:{text_color};'
                    f'padding:6px 12px;white-space:nowrap;border-bottom:1px solid #e2e8f0;'
                    f'font-size:0.82rem;">{val}</td>'
                )
            rows_html += f"<tr>{cells}</tr>"

        table_html = f"""
        <div style="overflow-x:auto;overflow-y:auto;max-height:520px;border:1px solid #bee3f8;border-radius:6px;">
          <table style="border-collapse:collapse;width:max-content;min-width:100%;">
            <thead><tr>{header_html}</tr></thead>
            <tbody>{rows_html}</tbody>
          </table>
        </div>
        """
        st.markdown(table_html, unsafe_allow_html=True)
        st.info("💡 **Ghi chú chuẩn mực kế toán (TT 200)**: Đối với các doanh nghiệp thuộc ngành **Xây dựng, Xây lắp công trình, Thi công hạ tầng hoặc Sản xuất B2B** (như ALVICO), dòng **Chi phí bán hàng (Mã 25)** trên Báo cáo kết quả hoạt động kinh doanh đã kiểm toán thường **không phát sinh (= 0 đ)**, do toàn bộ chi phí nhân công, máy móc và quản lý dự án được hạch toán trực tiếp vào **Giá vốn hàng bán (Mã 11)** và **Chi phí quản lý doanh nghiệp (Mã 26)**.")


    # ------------------ TAB 3: FORMULAS AND CALCULATIONS ------------------
    with tab_formulas:
        st.subheader("Chi tiết số liệu trung gian & Công thức tính toán của 10 Chỉ số EWS")
        
        selected_f_year = st.selectbox("Chọn năm xem chi tiết công thức:", years_list, index=len(years_list)-1, key="f_year")
        y_ews = ews_results[selected_f_year]
        
        # 1. Altman Z'-Score Breakdown
        st.markdown("### 1. Mô hình Altman Z'-Score (Private Firms)")
        st.latex(r"Z' = 0.717 X_1 + 0.847 X_2 + 3.107 X_3 + 0.420 X_4 + 0.998 X_5")
        z_data = y_ews.get("Altman_Z_Prime", None)
        if z_data:
            details = z_data["details"]
            z_rows = [
                {"Biến số": "X1 (Vốn lưu động / Tổng tài sản)", "Công thức": "(Tài sản ngắn hạn [100] - Nợ ngắn hạn [310]) / Tổng tài sản [270]", "Giá trị tính toán": f"{details['X1']:.4f}"},
                {"Biến số": "X2 (Lợi nhuận giữ lại / Tổng tài sản)", "Công thức": "Lợi nhuận sau thuế chưa phân phối [421] / Tổng tài sản [270]", "Giá trị tính toán": f"{details['X2']:.4f}"},
                {"Biến số": "X3 (EBIT / Tổng tài sản)", "Công thức": "(Lợi nhuận kế toán trước thuế [50] + Chi phí lãi vay [23]) / Tổng tài sản [270]", "Giá trị tính toán": f"{details['X3']:.4f}"},
                {"Biến số": "X4 (VCSH / Tổng nợ)", "Công thức": "Vốn chủ sở hữu [400] / Tổng nợ phải trả [300]", "Giá trị tính toán": f"{details['X4']:.4f}"},
                {"Biến số": "X5 (Doanh thu / Tổng tài sản)", "Công thức": "Doanh thu thuần [10] / Tổng tài sản [270]", "Giá trị tính toán": f"{details['X5']:.4f}"},
            ]
            st.table(pd.DataFrame(z_rows))
            st.markdown(f"**Kết quả tính toán**: $Z' = {z_data['score']:.4f}$ $\\rightarrow$ **{z_data['zone']}**")
        else:
            st.warning("Thiếu các chỉ tiêu cơ bản để tính toán Z'-Score.")
            
        # 2. SA Index Breakdown
        st.markdown("### 2. Mô hình SA Index (Size-Age Index)")
        st.latex(r"SA = -0.737 \times Size + 0.043 \times Size^2 - 0.040 \times Age")
        sa_data = y_ews.get("SA_Index", None)
        if sa_data:
            st.markdown(f"- **Quy mô tài sản chuẩn hóa (Size)**: $ln(Total\\_Assets \\; in \\; M.USD) = {sa_data['size_used']:.4f}$ (Quy đổi theo tỷ giá 25,000 VND/USD)")
            st.markdown(f"- **Tuổi doanh nghiệp (Age)**: {sa_data['age_used']:.0f} năm")
            st.markdown(f"**Kết quả tính toán**: $SA = {sa_data['score']:.4f}$")
        else:
            st.warning("Thiếu chỉ tiêu Tổng tài sản để tính SA Index.")

        # 3. Beneish M-Score (1999) Breakdown
        st.markdown("### 3. Mô hình Beneish M-Score (1999 - 8 biến)")
        st.latex(r"M = -4.84 + 0.920 \times DSRI + 0.528 \times GMI + 0.404 \times AQI + 0.892 \times SGI + 0.115 \times DEPI - 0.172 \times SGAI + 4.679 \times TATA - 0.327 \times LVGI")
        m_data = y_ews.get("Beneish_M_Score", None)
        if m_data:
            m_details = m_data["details"]
            m_rows = [
                {"Biến số": "DSRI (Biến động Phải thu)", "Công thức": "(Phải thu KH_t / Doanh thu_t) / (Phải thu KH_t-1 / Doanh thu_t-1)", "Giá trị": f"{m_details['DSRI']:.4f}"},
                {"Biến số": "GMI (Biến động Biên lợi nhuận gộp)", "Công thức": "Biên LN gộp_t-1 / Biên LN gộp_t", "Giá trị": f"{m_details['GMI']:.4f}"},
                {"Biến số": "AQI (Chất lượng tài sản)", "Công thức": "[1 - (TS ngắn hạn_t + TSCĐ_t)/Tổng TS_t] / [1 - (TS ngắn hạn_t-1 + TSCĐ_t-1)/Tổng TS_t-1]", "Giá trị": f"{m_details['AQI']:.4f}"},
                {"Biến số": "SGI (Tốc độ tăng Doanh thu)", "Công thức": "Doanh thu_t / Doanh thu_t-1", "Giá trị": f"{m_details['SGI']:.4f}"},
                {"Biến số": "TATA (Biến dồn tích)", "Công thức": "(Lợi nhuận sau thuế [60] - Dòng tiền từ HĐKD [20 LCTT]) / Tổng tài sản_t [270]", "Giá trị": f"{m_details['TATA']:.4f}"},
                {"Biến số": "LVGI (Biến động Đòn bẩy nợ)", "Công thức": "(Nợ phải trả_t / Tổng TS_t) / (Nợ phải trả_t-1 / Tổng TS_t-1)", "Giá trị": f"{m_details['LVGI']:.4f}"},
            ]
            st.table(pd.DataFrame(m_rows))
            st.markdown(f"**Kết quả tính toán**: $M = {m_data['score']:.4f}$ $\\rightarrow$ **{m_data['zone']}**")
        else:
            st.warning("Thiếu chỉ tiêu năm trước để tính toán các biến tăng trưởng chuỗi thời gian của Beneish M-Score.")

        # 4. Beneish M-Score (1997 - 12 biến Probit) Breakdown
        st.markdown("### 4. Mô hình Beneish M-Score (1997 - 12 biến Probit)")
        st.latex(r"Z = -3.5 + 0.920 \times DSRI + 0.528 \times GMI + 0.404 \times AQI + 0.892 \times SGI + 0.115 \times DEPI - 0.172 \times SGAI + 4.679 \times TATA - 0.327 \times LVGI")
        st.latex(r" - 0.320 \times AbReturn + 0.35 \times PosAccruals + 0.25 \times DecCashSales + 0.40 \times Issue")
        st.latex(r"Probability (P) = \Phi(Z)")
        m12_data = y_ews.get("Beneish_M_Score_12", None)
        if m12_data:
            m12_details = m12_data["details"]
            m12_rows = [
                {"Biến số": "Z-Index (Probit Z)", "Mô tả": "Tổng chỉ số Z của probit", "Giá trị": f"{m12_details['Z']:.4f}"},
                {"Biến số": "Abnormal Return", "Mô tả": "Tỷ suất sinh lời bất thường (từ sidebar)", "Giá trị": f"{m12_details['Abnormal Return']:.2%}"},
                {"Biến số": "Pos Accruals", "Mô tả": "Biến giả dồn tích dương (TATA > 0)", "Giá trị": f"{m12_details['Pos Accruals']:.0f}"},
                {"Biến số": "Dec Cash Sales", "Mô tả": "Biến giả sụt giảm doanh thu tiền mặt", "Giá trị": f"{m12_details['Dec Cash Sales']:.0f}"},
                {"Biến số": "Issue", "Mô tả": "Biến giả phát hành chứng khoán nợ/vốn", "Giá trị": f"{m12_details['Issue']:.0f}"},
            ]
            st.table(pd.DataFrame(m12_rows))
            st.markdown(f"**Kết quả xác suất**: $P = {m12_data['score']:.4%}$ $\\rightarrow$ **{m12_data['zone']}**")
        else:
            st.warning("Thiếu chỉ tiêu năm trước để tính toán các biến của Beneish 1997 Probit.")

        # 5. Dechow F-Score Breakdown
        st.markdown("### 5. Mô hình Dechow F-Score (2011)")
        st.latex(r"Z = -7.893 + 0.790 \times RSST\_Acc + 2.518 \times Ch\_Rec + 1.191 \times Ch\_Inv + 1.979 \times Soft\_Assets + 0.171 \times Ch\_CS - 0.932 \times Ch\_ROA + 1.029 \times Issue")
        st.latex(r"F-Score = \frac{e^Z / (1 + e^Z)}{Unconditional\_Prob}")
        f_data = y_ews.get("Dechow_F_Score", None)
        if f_data:
            f_details = f_data["details"]
            f_rows = [
                {"Biến số": "RSST_Acc", "Diễn giải": "Biến dồn tích WC + NCO + FIN chuẩn hóa", "Giá trị": f"{f_details['rsst_acc']:.4f}"},
                {"Biến số": "Ch_Rec", "Diễn giải": "Biến động khoản phải thu khách hàng / Tài sản TB", "Giá trị": f"{f_details['ch_rec']:.4f}"},
                {"Biến số": "Ch_Inv", "Diễn giải": "Biến động hàng tồn kho / Tài sản TB", "Giá trị": f"{f_details['ch_inv']:.4f}"},
                {"Biến số": "Soft_Assets", "Diễn giải": "Tỷ trọng tài sản mềm (TA - PPE - Cash) / TA", "Giá trị": f"{f_details['soft_assets']:.4f}"},
                {"Biến số": "Ch_CS", "Diễn giải": "Tăng trưởng doanh thu bằng tiền mặt", "Giá trị": f"{f_details['ch_cs']:.4f}"},
                {"Biến số": "Ch_ROA", "Diễn giải": "Biến động tỷ suất ROA của doanh nghiệp", "Giá trị": f"{f_details['ch_roa']:.4f}"},
            ]
            st.table(pd.DataFrame(f_rows))
            st.markdown(f"**Kết quả tính toán**: $F-Score = {f_data['score']:.4f}$ $\\rightarrow$ **{f_data['zone']}**")
        else:
            st.warning("Thiếu chỉ tiêu năm trước để tính toán Dechow F-Score.")

        # 6, 7, 8. REM Abnormal Variables Breakdown
        st.markdown("### 6, 7, 8. Nhóm chỉ số thao túng thực tế (REM - Roychowdhury 2006)")
        st.markdown("Các mô hình Normal được ước lượng bằng các phương trình chuẩn hóa chéo ngành:")
        st.latex(r"Normal\_CFO_t / A_{t-1} = -0.01 (1/A_{t-1}) + 0.09 (S_t/A_{t-1}) - 0.02 (\Delta S_t/A_{t-1})")
        st.latex(r"Normal\_PROD_t / A_{t-1} = 0.03 (1/A_{t-1}) + 0.82 (S_t/A_{t-1}) + 0.12 (\Delta S_t/A_{t-1}) - 0.05 (\Delta S_{t-1}/A_{t-1})")
        st.latex(r"Normal\_DISEXP_t / A_{t-1} = 0.01 (1/A_{t-1}) + 0.06 (S_{t-1}/A_{t-1})")
        
        cfo_d = y_ews.get("Abnormal_CFO")
        prod_d = y_ews.get("Abnormal_PROD")
        dis_d = y_ews.get("Abnormal_DISEXP")
        
        if cfo_d and prod_d and dis_d:
            rem_rows = [
                {"Biến số": "Abnormal CFO (Ab_CFO)", "Giá trị thực tế": f"{cfo_d['details']['Actual']:.4f}", "Giá trị bình thường ước lượng": f"{cfo_d['details']['Normal']:.4f}", "Chỉ số phần dư (Abnormal)": f"{cfo_d['score']:.4f}", "Trạng thái": cfo_d['zone']},
                {"Biến số": "Abnormal Production (Ab_PROD)", "Giá trị thực tế": f"{prod_d['details']['Actual']:.4f}", "Giá trị bình thường ước lượng": f"{prod_d['details']['Normal']:.4f}", "Chỉ số phần dư (Abnormal)": f"{prod_d['score']:.4f}", "Trạng thái": prod_d['zone']},
                {"Biến số": "Abnormal Discretionary Exp (Ab_DISEXP)", "Giá trị thực tế": f"{dis_d['details']['Actual']:.4f}", "Giá trị bình thường ước lượng": f"{dis_d['details']['Normal']:.4f}", "Chỉ số phần dư (Abnormal)": f"{dis_d['score']:.4f}", "Trạng thái": dis_d['zone']},
            ]
            st.table(pd.DataFrame(rem_rows))
        else:
            st.warning("Thiếu các dữ liệu chuỗi thời gian cần thiết để tính toán chỉ số phần dư REM.")

        # 9, 10. Financial Constraints Breakdown (KZ & WW Index)
        st.markdown("### 9, 10. Nhóm chỉ số Hạn chế tài chính (KZ & WW Index)")
        st.latex(r"KZ = -1.002 (CF/K) + 0.283 \times Q + 3.139 (Debt/K) - 39.368 (Div/K) - 1.315 (Cash/K)")
        st.latex(r"WW = -0.091 \times CF\_TA - 0.062 \times DIVPOS + 0.021 \times TLTD - 0.044 \times LNTA + 0.102 \times ISG - 0.035 \times SG")
        
        kz_d = y_ews.get("KZ_Index")
        ww_d = y_ews.get("WW_Index")
        
        if kz_d and ww_d:
            col_k1, col_k2 = st.columns(2)
            with col_k1:
                st.markdown("**Số liệu trung gian KZ Index**:")
                st.table(pd.DataFrame([
                    {"Biến số": "CF/K (Lợi nhuận + Khấu hao / TSCĐ đầu kỳ)", "Giá trị": f"{kz_d['details']['CF/K']:.4f}"},
                    {"Biến số": "Tobin's Q (Từ sidebar)", "Giá trị": f"{kz_d['details']['Tobin Q']:.4f}"},
                    {"Biến số": "Debt/K (Tổng nợ / TSCĐ đầu kỳ)", "Giá trị": f"{kz_d['details']['Debt/K']:.4f}"},
                    {"Biến số": "Div/K (Cổ tức tiền mặt / TSCĐ đầu kỳ)", "Giá trị": f"{kz_d['details']['Div/K']:.4f}"},
                    {"Biến số": "Cash/K (Tiền / TSCĐ đầu kỳ)", "Giá trị": f"{kz_d['details']['Cash/K']:.4f}"},
                ]))
                st.markdown(f"**KZ Score**: **{kz_d['score']:.4f}** $\\rightarrow$ **{kz_d['zone']}**")
            with col_k2:
                st.markdown("**Số liệu trung gian WW Index**:")
                st.table(pd.DataFrame([
                    {"Biến số": "CF_TA (Dòng tiền / Tổng tài sản)", "Giá trị": f"{ww_d['details']['CF/TA']:.4f}"},
                    {"Biến số": "DIVPOS (Biến giả chi trả cổ tức)", "Giá trị": f"{ww_d['details']['DIVPOS']:.0f}"},
                    {"Biến số": "TLTD (Nợ dài hạn / Tổng tài sản)", "Giá trị": f"{ww_d['details']['TLTD']:.4f}"},
                    {"Biến số": "LNTA (ln Tổng tài sản quy đổi USD triệu)", "Giá trị": f"{ww_d['details']['LNTA']:.4f}"},
                    {"Biến số": "ISG (Tăng trưởng doanh thu ngành từ sidebar)", "Giá trị": f"{ww_d['details']['ISG']:.4%}"},
                    {"Biến số": "SG (Tăng trưởng doanh thu của DN)", "Giá trị": f"{ww_d['details']['SG']:.4%}"},
                ]))
                st.markdown(f"**WW Score**: **{ww_d['score']:.4f}** $\\rightarrow$ **{ww_d['zone']}**")
        else:
            st.warning("Thiếu các chỉ tiêu kế toán cần thiết để tính toán chỉ số KZ & WW.")

    # ------------------ TAB 4: DATA VALIDATION ------------------
    with tab_validation:
        st.subheader("Kiểm tra tính toàn vẹn và cân đối dữ liệu kế toán")
        
        for log in validation_logs:
            if log["type"] == "success":
                st.success(log["message"])
            elif log["type"] == "warning":
                st.warning(log["message"])
            elif log["type"] == "error":
                st.error(log["message"])
                
        if validation_is_valid:
            st.success("🎉 Dữ liệu vượt qua tất cả kiểm tra tính toàn vẹn và cân đối sổ sách kế toán.")
        else:
            st.warning("⚠️ Phát hiện một số cảnh báo rủi ro về chất lượng dữ liệu sổ sách.")

    # ------------------ TAB 5: AUDIT & INTERVIEW GENERATOR ------------------
    with tab_audit:
        st.subheader("Truy vết lý do cảnh báo & Đề xuất bộ câu hỏi chất vấn doanh nghiệp")
        alert_count = 0
        
        for y in sorted(list(ews_results.keys())):
            res_y = ews_results[y]
            m_res_y = res_y.get("Beneish_M_Score", None)
            m12_res_y = res_y.get("Beneish_M_Score_12", None)
            f_res_y = res_y.get("Dechow_F_Score", None)
            z_res_y = res_y.get("Altman_Z_Prime", None)
            cfo_y = res_y.get("Abnormal_CFO", None)
            prod_y = res_y.get("Abnormal_PROD", None)
            kz_y = res_y.get("KZ_Index", None)
            
            # 1. Cảnh báo M-Score 8 biến
            if m_res_y and m_res_y["status"] == "error":
                alert_count += 1
                st.error(f"🚨 **Năm {y}: Phát hiện dấu hiệu thao túng BCTC (Beneish M-Score 8 biến = {m_res_y['score']:.3f})**")
                details = m_res_y["details"]
                
                st.markdown("**Truy vết lý do chi tiết từ hệ thống:**")
                if details["DSRI"] > 1.2:
                    st.markdown(f"- **Chỉ số công nợ phải thu (DSRI = {details['DSRI']:.2f}) tăng bất thường**: Tốc độ tăng các khoản phải thu nhanh gấp {details['DSRI']:.2f} lần tốc độ tăng doanh thu thuần. Dấu hiệu ghi nhận sớm doanh thu khống trước kỳ báo cáo.")
                if details["TATA"] > 0.05:
                    st.markdown(f"- **Tổng biến dồn tích chuẩn hóa (TATA = {details['TATA']:.2f}) dương lớn**: Lợi nhuận báo cáo cao nhưng tiền hoạt động kinh doanh (OCF) bị âm nặng hoặc suy giảm mạnh. Chênh lệch nghiêm trọng giữa dòng tiền thực tế và kế toán dồn tích.")
                    
                st.markdown("**Đề xuất bộ câu hỏi phỏng vấn khách hàng doanh nghiệp:**")
                st.info(f"""
                1. Đề nghị doanh nghiệp cung cấp **Biên bản đối chiếu công nợ chi tiết** của Top 5 khách hàng có số dư phải thu lớn nhất tại thời điểm cuối năm {y}.
                2. Giải trình lý do cụ thể về sự mất cân đối lớn giữa **Lợi nhuận kế toán sau thuế** và **Dòng tiền thuần hoạt động kinh doanh (OCF)**.
                3. Doanh nghiệp có thay đổi chính sách tín dụng thương mại hay thời hạn công nợ cho khách hàng trong năm {y} hay không?
                """)
            
            # 2. Cảnh báo Beneish M-Score 12 biến
            if m12_res_y and m12_res_y["status"] == "error":
                alert_count += 1
                st.error(f"🚨 **Năm {y}: Xác suất thao túng BCTC rất cao (Beneish M-Score 12 biến = {m12_res_y['score']:.2%})**")
                st.markdown(f"- **Chi tiết**: Mô hình Probit 12 biến phát hiện xác suất vi phạm GAAP vượt mức cảnh báo mặc định 6.75% (đã tích hợp các biến động cơ bối cảnh).")
            
            # 3. Cảnh báo Dechow F-Score
            if f_res_y and f_res_y["status"] == "error":
                alert_count += 1
                st.error(f"🚨 **Năm {y}: Xác suất sai lệch trọng yếu cực cao (Dechow F-Score = {f_res_y['score']:.3f})**")
                details = f_res_y["details"]
                st.markdown("**Truy vết lý do chi tiết từ hệ thống:**")
                if details["rsst_acc"] > 0.10:
                    st.markdown(f"- **Biến dồn tích RSST (RSST_Acc = {details['rsst_acc']:.2f}) lớn**: Tổng các khoản dồn tích từ vốn lưu động, tài sản phi lưu động và tài sản tài chính tăng mạnh bất thường so với quy mô tài sản.")
                if details["soft_assets"] > 0.60:
                    st.markdown(f"- **Tỷ lệ tài sản mềm cao (Soft_Assets = {details['soft_assets']:.2%})**: Doanh nghiệp nắm giữ phần lớn tài sản dạng dễ thổi phồng (phải thu, HTK, chi phí trả trước, tài sản dở dang...) thay vì TSCĐ hữu hình hoặc tiền mặt.")
                
                st.markdown("**Đề xuất bộ câu hỏi phỏng vấn khách hàng doanh nghiệp:**")
                st.info(f"""
                1. Đề nghị giải trình sự gia tăng đột biến của các khoản tạm ứng, ký cược, ký quỹ hoặc chi phí dở dang dài hạn trong năm {y}.
                2. Kiểm tra tính hiện hữu và khả năng thanh lý của hàng tồn kho ứ đọng lâu ngày.
                """)

            # 4. Cảnh báo Abnormal CFO & Abnormal PROD (REM)
            if cfo_y and cfo_y["status"] == "error":
                alert_count += 1
                st.error(f"🚨 **Năm {y}: Dòng tiền hoạt động kinh doanh thấp bất thường (Abnormal CFO = {cfo_y['score']:.4f})**")
                st.markdown("- **Nhận diện nghiệp vụ**: Doanh nghiệp có dấu hiệu bán hàng chiết khấu mạnh hoặc ghi nhận doanh thu khống chưa thu được tiền thực tế để đẩy doanh số ngắn hạn.")
                
            if prod_y and prod_y["status"] == "error":
                alert_count += 1
                st.error(f"🚨 **Năm {y}: Chi phí sản xuất cao bất thường (Abnormal Production = {prod_y['score']:.4f})**")
                st.markdown("- **Nhận diện nghiệp vụ**: Có dấu hiệu sản xuất quá mức cần thiết (Overproduction) nhằm chuyển dịch chi phí cố định vào hàng tồn kho, từ đó làm giảm giá vốn hàng bán (COGS) trên báo cáo để làm đẹp lợi nhuận gộp.")
                st.info("💡 **Câu hỏi chất vấn**: Đề nghị doanh nghiệp cung cấp báo cáo công suất sử dụng nhà máy thực tế và kế hoạch sản xuất kinh doanh chi tiết trong năm.")

            # 5. Cảnh báo Z-Score
            if z_res_y and z_res_y["status"] == "error":
                alert_count += 1
                st.warning(f"⚠️ **Năm {y}: Rủi ro kiệt quệ tài chính rất cao (Altman Z'-Score = {z_res_y['score']:.3f})**")
                details = z_res_y["details"]
                
                st.markdown("**Truy vết lý do chi tiết từ hệ thống:**")
                st.markdown(f"- **Đòn bẩy tài chính (X4 = {details['X4']:.2f})**: Vốn chủ sở hữu quá mỏng so với tổng nợ phải trả. Doanh nghiệp phụ thuộc nặng nề vào vốn vay.")
                
                st.markdown("**Đề xuất bộ câu hỏi phỏng vấn khách hàng doanh nghiệp:**")
                st.info(f"""
                1. Đề nghị làm rõ kế hoạch tái cơ cấu nguồn vốn và khả năng thanh toán các khoản nợ vay ngắn hạn sắp đáo hạn.
                2. Doanh nghiệp có phương án bổ sung vốn tự có hoặc tăng vốn điều lệ từ các cổ đông trong năm tới hay không?
                """)

            # 6. Cảnh báo Hạn chế tài chính (KZ Index)
            if kz_y and kz_y["status"] == "error":
                alert_count += 1
                st.warning(f"⚠️ **Năm {y}: Mức độ hạn chế tài chính / Thắt chặt thanh khoản cao (KZ Index = {kz_y['score']:.3f})**")
                st.markdown("- **Mô tả**: Doanh nghiệp đang chịu sức ép thanh khoản lớn, lượng tiền mặt dự trữ mỏng trong khi nợ phải trả cao và dòng tiền tích lũy thấp, hạn chế khả năng tiếp cận thêm tín dụng mới.")
                
            # 7. Cảnh báo từ các biến kiểm soát bổ sung (Control Variables)
            ctrl_y = control_results.get(y, None)
            if ctrl_y:
                for ctrl_var, ctrl_data in ctrl_y.items():
                    if ctrl_data and ctrl_data["level"] == 4:
                        alert_count += 1
                        val = ctrl_data["value"]
                        if ctrl_var in ["LEV", "ROA", "GROWTH", "WC_TA", "RE_TA", "EBIT_TA", "INVEST", "CF", "ACCR", "SOFT", "NegTone", "TextSim", "GovDisc"]:
                            val_str = f"{val:.2%}"
                        else:
                            val_str = f"{val:,.2f}"
                            
                        st.error(f"🚨 **Năm {y}: Biến kiểm soát rủi ro rất cao ({ctrl_var} = {val_str})**")
                        st.markdown(f"- **Chi tiết rủi ro**: {ctrl_data['desc']}")
                        
                        if ctrl_var == "LEV":
                            st.info(f"""
                            💡 **Câu hỏi chất vấn (Đòn bẩy tài chính - LEV)**:
                            1. Doanh nghiệp có phương án cụ thể nào để giảm đòn bẩy tài chính và cơ cấu lại các khoản nợ vay đến hạn trong năm {y} hay không?
                            2. Kế hoạch đàm phán kéo dài kỳ hạn nợ với các ngân hàng chủ nợ lớn nhất của doanh nghiệp đang diễn ra thế nào?
                            """)
                        elif ctrl_var == "ROA":
                            st.info(f"""
                            💡 **Câu hỏi chất vấn (Khả năng sinh lời - ROA)**:
                            1. Phân tích nguyên nhân cốt lõi khiến hoạt động kinh doanh thua lỗ và tỷ suất ROA âm trong năm {y}.
                            2. Doanh nghiệp có kế hoạch cắt giảm mảng kinh doanh kém hiệu quả hoặc tái cấu trúc hoạt động nào để khôi phục khả năng sinh lời?
                            """)
                        elif ctrl_var == "CF":
                            st.info(f"""
                            💡 **Câu hỏi chất vấn (Dòng tiền - CF)**:
                            1. Dòng tiền từ hoạt động kinh doanh (CFO) âm nặng phản ánh sự ứ đọng vốn lưu động lớn. Doanh nghiệp đang bù đắp dòng tiền thiếu hụt này bằng nguồn vốn nào?
                            2. Giải trình tiến độ thu hồi công nợ và kế hoạch giải phóng hàng tồn kho để tạo dòng tiền tự có.
                            """)
                        elif ctrl_var == "ACCR":
                            st.info(f"""
                            💡 **Câu hỏi chất vấn (Chất lượng lợi nhuận - ACCR)**:
                            1. Doanh nghiệp giải trình lý do của việc chênh lệch quá lớn giữa lợi nhuận sau thuế và dòng tiền thuần từ HĐKD (dồn tích ACCR lớn).
                            2. Có hay không việc nới lỏng chính sách ghi nhận doanh thu để thổi phồng kết quả lợi nhuận kế toán?
                            """)
                        elif ctrl_var == "GovDisc":
                            st.info(f"""
                            💡 **Câu hỏi chất vấn (Minh bạch quản trị - GovDisc)**:
                            1. Điểm số công bố quản trị doanh nghiệp quá thấp (< 50%). Giải trình lý do không tuân thủ các quy định về công bố thông tin, đặc biệt là giao dịch với các bên liên quan và thù lao ban điều hành.
                            2. Kế hoạch khắc phục và nâng cao tính minh bạch quản trị để bảo vệ lợi ích của các bên liên quan.
                            """)
                        elif ctrl_var == "TextSim":
                            st.info(f"""
                            💡 **Câu hỏi chất vấn (Độ lặp Báo cáo thường niên - TextSim)**:
                            1. Báo cáo thường niên có tỷ lệ trùng lặp văn bản quá cao (>95%) so với năm trước. Doanh nghiệp giải trình lý do không cập nhật các đánh giá về bối cảnh kinh doanh, rủi ro mới phát sinh.
                            2. Chất lượng và sự trung thực của quy trình đánh giá rủi ro nội bộ có thực sự được chú trọng?
                            """)
                        elif ctrl_var == "CEOAge":
                            st.info(f"""
                            💡 **Câu hỏi chất vấn (Độ tuổi CEO - CEOAge)**:
                            1. Doanh nghiệp hiện có CEO đã trên 70 tuổi (hoặc dưới 30 tuổi). Đề nghị làm rõ kế hoạch nhân sự kế cận và lộ trình chuyển giao quyền lực điều hành tại HĐQT/Ban giám đốc để giảm thiểu rủi ro biến động nhân sự cấp cao.
                            2. Với các áp lực về mặt di sản hoặc khẳng định bản thân của thế hệ điều hành mới, ban kiểm soát có cơ chế giám sát độc lập nào để tránh việc bóp méo/làm đẹp số liệu BCTC?
                            """)
                            
        if alert_count == 0:
            st.success("🟢 Không có cảnh báo đặc biệt nào. Khách hàng nằm trong vùng an toàn lý thuyết.")
            
        # Khu vực tải Báo cáo Thẩm định PDF ở chân trang
        st.markdown("---")
        st.subheader("📑 Xuất Báo cáo Thẩm định Tín dụng (PDF)")
        c_rep1, c_rep2 = st.columns([2, 1])
        with c_rep1:
            st.markdown(f"""
            Báo cáo thẩm định rủi ro toàn diện của **{summary_company_name} ({main_ticker})** đã được biên soạn theo mẫu chuẩn ngân hàng, bao gồm:
            * Bảng số liệu kế toán 21 chỉ tiêu qua các năm.
            * Đánh giá 10 bộ chỉ số EWS kèm mã màu vùng rủi ro (*An toàn / Vùng xám / Nguy hiểm*).
            * Tổng hợp cảnh báo kiệt quệ tài chính, thao túng BCTC và câu hỏi chất vấn.
            * Khung ký duyệt dành cho Cán bộ Thẩm định và Trưởng bộ phận Quản lý Rủi ro.
            """)
        with c_rep2:
            if "pdf_bytes" in locals() and pdf_bytes:
                st.download_button(
                    label="📄 📥 Tải Báo cáo Thẩm định (PDF)",
                    data=pdf_bytes,
                    file_name=f"Bao_Cao_Tham_Dinh_EWS_{main_ticker}.pdf",
                    mime="application/pdf",
                    type="primary",
                    use_container_width=True,
                    key="main_pdf_download_btn",
                    help="Tải báo cáo PDF chuẩn in ấn, dễ đọc cho nhân viên và trình ký lãnh đạo"
                )
elif selected_profile != "Tải file mới" or uploaded_files:
    st.warning("⚠️ Chưa có dữ liệu hợp lệ được trích xuất. Vui lòng kiểm tra lại các tệp tải lên (Đảm bảo đó là BCTC của doanh nghiệp thông thường sản xuất/thương mại).")
else:
    # -------------------------------------------------------------------------
    # TRUNG TÂM NHẬP LIỆU & KHỞI TẠO THẨM ĐỊNH BCTC 3 BƯỚC (MAIN SCREEN WIZARD)
    # -------------------------------------------------------------------------
    st.markdown("""
    <div style='background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); padding: 22px 26px; border-radius: 12px; color: white; margin-bottom: 25px; box-shadow: 0 4px 15px rgba(0,0,0,0.1);'>
        <h2 style='color: #f8fafc; margin: 0 0 6px 0; font-size: 1.5em;'>📥 TRUNG TÂM NHẬP LIỆU & KHỞI TẠO THẨM ĐỊNH BCTC</h2>
        <p style='color: #94a3b8; margin: 0; font-size: 0.95em;'>
            Hệ thống tự động hóa thẩm định theo quy chuẩn kế toán Việt Nam (Thông tư 200/2014/TT-BTC) qua <b>3 Bước</b>:
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    col_step1, col_step2, col_step3 = st.columns([1.1, 1, 1])
    
    with col_step1:
        st.markdown("#### 📂 BƯỚC 1: Nạp Báo cáo Tài chính")
        st.caption("Chọn 1 trong các cách sau để nạp dữ liệu:")
        
        # 1. Kéo thả file trực tiếp
        wiz_files = st.file_uploader(
            "Tải lên file BCTC (.xlsx, .xls, .pdf):",
            type=["xlsx", "xls", "pdf"],
            accept_multiple_files=True,
            key="wiz_main_uploader",
            help="Tải lên BCTC kiểm toán hoặc BCTC nội bộ"
        )
        if wiz_files:
            st.session_state["uploaded_from_main"] = wiz_files
            st.success(f"Đã chọn {len(wiz_files)} tệp BCTC. Nhấn Bắt đầu ở Bước 3 để phân tích!")
            
        st.markdown("---")
        st.markdown("**HOẶC Chọn nhanh Hồ sơ mẫu thực tế (1-Click Demo):**")
        
        c_p1, c_p2 = st.columns(2)
        with c_p1:
            if st.button("🏢 Hoa Sen (HSG)", use_container_width=True, help="Ngành Thép - Nguyên vật liệu"):
                st.session_state["active_profile"] = "HSG - Công ty Cổ phần Tập đoàn Hoa Sen"
                st.session_state["wizard_selected_industry"] = "Basic Materials (Nguyên vật liệu)"
                st.rerun()
            if st.button("🏢 Nam Việt (ANV)", use_container_width=True, help="Ngành Thủy sản - Hàng tiêu dùng"):
                st.session_state["active_profile"] = "ANV - Công ty Cổ phần Nam Việt"
                st.session_state["wizard_selected_industry"] = "Consumer Goods (Hàng tiêu dùng)"
                st.rerun()
            if st.button("🏢 Bao bì HT (BBH)", use_container_width=True, help="Ngành Bao bì - Công nghiệp"):
                st.session_state["active_profile"] = "BBH - A Công Ty Cổ Phần BAO BI HOANG THACH"
                st.session_state["wizard_selected_industry"] = "Industrials (Công nghiệp)"
                st.rerun()
        with c_p2:
            if st.button("🏢 Alvico (ALV)", use_container_width=True, help="Ngành Xây dựng - Công nghiệp"):
                st.session_state["active_profile"] = "ALV - Công ty Cổ phần Xây dựng ALVICO"
                st.session_state["wizard_selected_industry"] = "Industrials (Công nghiệp)"
                st.rerun()
            if st.button("🏢 Nông sản SG (AGX)", use_container_width=True, help="Ngành Nông sản - Hàng tiêu dùng"):
                st.session_state["active_profile"] = "AGX - CÔNG TY CỔ PHẦN THỰC PHẨM NÔNG SẢN XUẤT KHẨU SÀI GÒN"
                st.session_state["wizard_selected_industry"] = "Consumer Goods (Hàng tiêu dùng)"
                st.rerun()
            if st.button("🏢 Vincom (VRE)", use_container_width=True, help="Ngành BĐS Bán lẻ"):
                st.session_state["active_profile"] = "VRE - Công ty Cổ phần Vincom Retail"
                st.session_state["wizard_selected_industry"] = "Industrials (Công nghiệp)"
                st.rerun()
                
        tpl_path = os.path.join(BASE_DIR, "Fintech_EWS_GroundTruth_Template.xlsx")
        if os.path.exists(tpl_path):
            with open(tpl_path, "rb") as f_tpl:
                st.download_button(
                    label="📥 Tải File Mẫu BCTC Excel (.xlsx)",
                    data=f_tpl.read(),
                    file_name="BCTC_Mau_TT200.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
                
    with col_step2:
        st.markdown("#### ⚙️ BƯỚC 2: Cấu hình Doanh nghiệp")
        st.caption("Thiết lập đặc thù ngành và quản trị:")
        
        wiz_ind = st.selectbox(
            "Ngành hoạt động chính (Áp dụng U-Curve):",
            industry_options,
            index=default_ind_idx,
            key="wiz_step2_industry",
            help="Hệ thống sẽ áp dụng ngưỡng đòn bẩy tối ưu theo ngành này"
        )
        
        wiz_age = st.number_input(
            "Tuổi doanh nghiệp (Năm hoạt động):",
            min_value=1,
            max_value=100,
            value=firm_age_input,
            key="wiz_step2_age"
        )
        
        wiz_bds = st.checkbox(
            "Doanh nghiệp Bất động sản / Xây dựng",
            value=default_is_bds,
            key="wiz_step2_bds",
            help="Nới lỏng biên an toàn đòn bẩy theo đặc thù chu kỳ đầu tư dài"
        )
        
        wiz_ceo = st.number_input(
            "Độ tuổi CEO / Đại diện pháp luật:",
            min_value=18,
            max_value=100,
            value=int(default_ceo_age),
            key="wiz_step2_ceo"
        )
        
        with st.expander("🛠️ Tham số Thị trường (Tùy chọn)"):
            st.caption("Tự động gán mặc định nếu không có dữ liệu chứng khoán:")
            st.number_input("Tỷ số Tobin's Q", value=float(st.session_state["live_tobin_q"]), key="wiz_step2_q")
            st.slider("Tỷ lệ cổ tức (%)", 0.0, 100.0, float(st.session_state["live_div_ratio"]), key="wiz_step2_div")
            st.slider("Tăng trưởng DT ngành ISG (%)", -50.0, 100.0, float(st.session_state["live_isg"]), key="wiz_step2_isg")

    with col_step3:
        st.markdown("#### 🚀 BƯỚC 3: Khởi chạy Phân tích")
        st.caption("Kích hoạt toàn bộ bộ máy EWS & Cân đối vốn:")
        
        st.markdown("""
        <div style='background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px; margin-bottom: 18px;'>
            <p style='margin: 0; font-size: 0.88em; color: #475569; line-height: 1.6;'>
                <b>Quy trình tự động hóa:</b><br>
                ✅ Tự động trích xuất 21 chỉ tiêu BCTC.<br>
                ✅ Nhận diện 10 chỉ số EWS & Thao túng.<br>
                ✅ Cân đối Vốn vay & Chu kỳ tiền mặt CCC.<br>
                ✅ Phân tích Bóc tách Phải thu - Tồn kho - Phải trả.<br>
                ✅ Xuất Báo cáo Thẩm định chuẩn PDF.
            </p>
        </div>
        """, unsafe_allow_html=True)
        
        if st.button("🚀 BẮT ĐẦU ĐÁNH GIÁ RỦI RO & MỞ DASHBOARD", type="primary", use_container_width=True):
            if wiz_files:
                st.session_state["uploaded_from_main"] = wiz_files
                st.session_state["wizard_selected_industry"] = wiz_ind
                st.rerun()
            elif "active_profile" in st.session_state and st.session_state["active_profile"] != "Tải file mới":
                st.session_state["wizard_selected_industry"] = wiz_ind
                st.rerun()
            else:
                # Default to HSG demo if nothing selected
                st.session_state["active_profile"] = "HSG - Công ty Cổ phần Tập đoàn Hoa Sen"
                st.session_state["wizard_selected_industry"] = "Basic Materials (Nguyên vật liệu)"
                st.rerun()
