# -*- coding: utf-8 -*-
"""
u_curve_regression.py
---------------------
Mô hình hồi quy đường cong chữ U (U-Curve Regression) để xác định ngưỡng đòn bẩy tối ưu
cho 5 nhóm ngành phi tài chính tại Việt Nam.
"""

import os
import json
import numpy as np
import pandas as pd
import scipy.stats as stats

# Mapping dictionary for ICB sectors to standard 5 groups
SECTOR_MAPPING = {
    'SX Nhựa - Hóa chất': 'Basic Materials (Nguyên vật liệu)',
    'Vật liệu xây dựng': 'Basic Materials (Nguyên vật liệu)',
    'Khai khoáng': 'Basic Materials (Nguyên vật liệu)',
    'Sản phẩm cao su': 'Basic Materials (Nguyên vật liệu)',
    'Tài nguyên Cơ bản': 'Basic Materials (Nguyên vật liệu)',
    'Hóa chất': 'Basic Materials (Nguyên vật liệu)',
    'Kim loại': 'Basic Materials (Nguyên vật liệu)',
    'Tài nguyên': 'Basic Materials (Nguyên vật liệu)',
    'Basic Materials': 'Basic Materials (Nguyên vật liệu)',
    'Nguyên vật liệu': 'Basic Materials (Nguyên vật liệu)',
    
    'Thực phẩm - Đồ uống': 'Consumer Goods (Hàng tiêu dùng)',
    'SX Hàng gia dụng': 'Consumer Goods (Hàng tiêu dùng)',
    'Chế biến Thủy sản': 'Consumer Goods (Hàng tiêu dùng)',
    'Nông - Lâm - Ngư': 'Consumer Goods (Hàng tiêu dùng)',
    'Hàng tiêu dùng cá nhân & gia đình': 'Consumer Goods (Hàng tiêu dùng)',
    'Thực phẩm và đồ uống': 'Consumer Goods (Hàng tiêu dùng)',
    'Bán lẻ': 'Consumer Goods (Hàng tiêu dùng)',
    'Dược phẩm và Y tế': 'Consumer Goods (Hàng tiêu dùng)',
    'Y tế': 'Consumer Goods (Hàng tiêu dùng)',
    'Consumer Goods': 'Consumer Goods (Hàng tiêu dùng)',
    'Hàng tiêu dùng': 'Consumer Goods (Hàng tiêu dùng)',
    
    'Xây dựng': 'Industrials (Công nghiệp)',
    'Vận tải - kho bãi': 'Industrials (Công nghiệp)',
    'SX Phụ trợ': 'Industrials (Công nghiệp)',
    'Thiết bị điện': 'Industrials (Công nghiệp)',
    'SX Thiết bị, máy móc': 'Industrials (Công nghiệp)',
    'Dịch vụ tư vấn, hỗ trợ': 'Industrials (Công nghiệp)',
    'Hàng & Dịch vụ Công nghiệp': 'Industrials (Công nghiệp)',
    'Xây dựng và Vật liệu': 'Industrials (Công nghiệp)',
    'Xây dựng & Vật liệu': 'Industrials (Công nghiệp)',
    'Bất động sản': 'Industrials (Công nghiệp)',
    'Du lịch & Giải trí': 'Industrials (Công nghiệp)',
    'Industrials': 'Industrials (Công nghiệp)',
    'Công nghiệp': 'Industrials (Công nghiệp)',
    
    'Dầu khí': 'Oil & Gas (Dầu khí)',
    'Oil & Gas': 'Oil & Gas (Dầu khí)',
    'Năng lượng': 'Oil & Gas (Dầu khí)',
    'Điện, nước & xăng dầu khí đốt': 'Oil & Gas (Dầu khí)',
    
    'Công nghệ và thông tin': 'Technology (Công nghệ)',
    'Công nghệ Thông tin': 'Technology (Công nghệ)',
    'Công nghệ thông tin': 'Technology (Công nghệ)',
    'Viễn thông': 'Technology (Công nghệ)',
    'Technology': 'Technology (Công nghệ)',
    'Công nghệ': 'Technology (Công nghệ)'
}

# Danh mục ánh xạ trực tiếp các mã cổ phiếu chuẩn theo 5 ngành phi tài chính
SYMBOL_TO_SECTOR_DICT = {
    # 1. Basic Materials (Nguyên vật liệu)
    'HPG': 'Basic Materials (Nguyên vật liệu)', 'HSG': 'Basic Materials (Nguyên vật liệu)', 'NKG': 'Basic Materials (Nguyên vật liệu)',
    'DGC': 'Basic Materials (Nguyên vật liệu)', 'DCM': 'Basic Materials (Nguyên vật liệu)', 'DPM': 'Basic Materials (Nguyên vật liệu)',
    'CSV': 'Basic Materials (Nguyên vật liệu)', 'LAS': 'Basic Materials (Nguyên vật liệu)', 'BFC': 'Basic Materials (Nguyên vật liệu)',
    'GVR': 'Basic Materials (Nguyên vật liệu)', 'DRC': 'Basic Materials (Nguyên vật liệu)', 'CSM': 'Basic Materials (Nguyên vật liệu)',
    'PHR': 'Basic Materials (Nguyên vật liệu)', 'DPR': 'Basic Materials (Nguyên vật liệu)', 'TRC': 'Basic Materials (Nguyên vật liệu)',
    'VCS': 'Basic Materials (Nguyên vật liệu)', 'HT1': 'Basic Materials (Nguyên vật liệu)', 'BCC': 'Basic Materials (Nguyên vật liệu)',
    'KSB': 'Basic Materials (Nguyên vật liệu)', 'DHA': 'Basic Materials (Nguyên vật liệu)', 'BMC': 'Basic Materials (Nguyên vật liệu)',
    'MSR': 'Basic Materials (Nguyên vật liệu)', 'TNT': 'Basic Materials (Nguyên vật liệu)', 'TVN': 'Basic Materials (Nguyên vật liệu)',
    'POM': 'Basic Materials (Nguyên vật liệu)', 'TLH': 'Basic Materials (Nguyên vật liệu)', 'SMC': 'Basic Materials (Nguyên vật liệu)',
    'VGS': 'Basic Materials (Nguyên vật liệu)', 'TIS': 'Basic Materials (Nguyên vật liệu)', 'VAF': 'Basic Materials (Nguyên vật liệu)',
    'DDV': 'Basic Materials (Nguyên vật liệu)', 'SFG': 'Basic Materials (Nguyên vật liệu)', 'HII': 'Basic Materials (Nguyên vật liệu)',
    'AAA': 'Basic Materials (Nguyên vật liệu)', 'APH': 'Basic Materials (Nguyên vật liệu)', 'PLP': 'Basic Materials (Nguyên vật liệu)',
    'NHH': 'Basic Materials (Nguyên vật liệu)', 'DAG': 'Basic Materials (Nguyên vật liệu)', 'RDP': 'Basic Materials (Nguyên vật liệu)',
    'C32': 'Basic Materials (Nguyên vật liệu)', 'NNC': 'Basic Materials (Nguyên vật liệu)', 'HOM': 'Basic Materials (Nguyên vật liệu)',
    
    # 2. Consumer Goods (Hàng tiêu dùng)
    'VNM': 'Consumer Goods (Hàng tiêu dùng)', 'MSN': 'Consumer Goods (Hàng tiêu dùng)', 'SAB': 'Consumer Goods (Hàng tiêu dùng)',
    'MWG': 'Consumer Goods (Hàng tiêu dùng)', 'PNJ': 'Consumer Goods (Hàng tiêu dùng)', 'KDC': 'Consumer Goods (Hàng tiêu dùng)',
    'MCH': 'Consumer Goods (Hàng tiêu dùng)', 'QNS': 'Consumer Goods (Hàng tiêu dùng)', 'SBT': 'Consumer Goods (Hàng tiêu dùng)',
    'VHC': 'Consumer Goods (Hàng tiêu dùng)', 'ANV': 'Consumer Goods (Hàng tiêu dùng)', 'IDI': 'Consumer Goods (Hàng tiêu dùng)',
    'FMC': 'Consumer Goods (Hàng tiêu dùng)', 'MPC': 'Consumer Goods (Hàng tiêu dùng)', 'CMX': 'Consumer Goods (Hàng tiêu dùng)',
    'ACL': 'Consumer Goods (Hàng tiêu dùng)', 'BAF': 'Consumer Goods (Hàng tiêu dùng)', 'DBC': 'Consumer Goods (Hàng tiêu dùng)',
    'HAG': 'Consumer Goods (Hàng tiêu dùng)', 'HNG': 'Consumer Goods (Hàng tiêu dùng)', 'TNG': 'Consumer Goods (Hàng tiêu dùng)',
    'MSH': 'Consumer Goods (Hàng tiêu dùng)', 'STK': 'Consumer Goods (Hàng tiêu dùng)', 'GIL': 'Consumer Goods (Hàng tiêu dùng)',
    'TCM': 'Consumer Goods (Hàng tiêu dùng)', 'VGT': 'Consumer Goods (Hàng tiêu dùng)', 'BHN': 'Consumer Goods (Hàng tiêu dùng)',
    'TLG': 'Consumer Goods (Hàng tiêu dùng)', 'SAV': 'Consumer Goods (Hàng tiêu dùng)', 'TTF': 'Consumer Goods (Hàng tiêu dùng)',
    'GDT': 'Consumer Goods (Hàng tiêu dùng)', 'PAN': 'Consumer Goods (Hàng tiêu dùng)', 'TAR': 'Consumer Goods (Hàng tiêu dùng)',
    'LTG': 'Consumer Goods (Hàng tiêu dùng)', 'AGX': 'Consumer Goods (Hàng tiêu dùng)', 'ABT': 'Consumer Goods (Hàng tiêu dùng)',
    'CAT': 'Consumer Goods (Hàng tiêu dùng)', 'CLC': 'Consumer Goods (Hàng tiêu dùng)', 'BIO': 'Consumer Goods (Hàng tiêu dùng)',
    'BBH': 'Consumer Goods (Hàng tiêu dùng)', 'BCV': 'Consumer Goods (Hàng tiêu dùng)', 'DCR': 'Consumer Goods (Hàng tiêu dùng)',
    
    # 3. Industrials (Công nghiệp)
    'REE': 'Industrials (Công nghiệp)', 'GMD': 'Industrials (Công nghiệp)', 'VSC': 'Industrials (Công nghiệp)',
    'HAH': 'Industrials (Công nghiệp)', 'PHP': 'Industrials (Công nghiệp)', 'DXP': 'Industrials (Công nghiệp)',
    'SGP': 'Industrials (Công nghiệp)', 'TCL': 'Industrials (Công nghiệp)', 'CII': 'Industrials (Công nghiệp)',
    'HHV': 'Industrials (Công nghiệp)', 'VCG': 'Industrials (Công nghiệp)', 'LCG': 'Industrials (Công nghiệp)',
    'FCN': 'Industrials (Công nghiệp)', 'CTD': 'Industrials (Công nghiệp)', 'HBC': 'Industrials (Công nghiệp)',
    'PC1': 'Industrials (Công nghiệp)', 'TV2': 'Industrials (Công nghiệp)', 'GEG': 'Industrials (Công nghiệp)',
    'VNE': 'Industrials (Công nghiệp)', 'GEX': 'Industrials (Công nghiệp)', 'CAV': 'Industrials (Công nghiệp)',
    'SAM': 'Industrials (Công nghiệp)', 'TMS': 'Industrials (Công nghiệp)', 'VOS': 'Industrials (Công nghiệp)',
    'VNA': 'Industrials (Công nghiệp)', 'VIP': 'Industrials (Công nghiệp)', 'PVP': 'Industrials (Công nghiệp)',
    'PVT': 'Industrials (Công nghiệp)', 'VTO': 'Industrials (Công nghiệp)', 'VJC': 'Industrials (Công nghiệp)',
    'HVN': 'Industrials (Công nghiệp)', 'SGN': 'Industrials (Công nghiệp)', 'NCT': 'Industrials (Công nghiệp)',
    'ACV': 'Industrials (Công nghiệp)', 'ALV': 'Industrials (Công nghiệp)', 'VGP': 'Industrials (Công nghiệp)',
    'DVP': 'Industrials (Công nghiệp)', 'TCO': 'Industrials (Công nghiệp)', 'SKG': 'Industrials (Công nghiệp)',
    'C47': 'Industrials (Công nghiệp)', 'HTN': 'Industrials (Công nghiệp)', 'PHC': 'Industrials (Công nghiệp)',
    'SCG': 'Industrials (Công nghiệp)', 'DAT': 'Industrials (Công nghiệp)', 'VIC': 'Industrials (Công nghiệp)',
    'VHM': 'Industrials (Công nghiệp)', 'VRE': 'Industrials (Công nghiệp)', 'NVL': 'Industrials (Công nghiệp)',
    'KBC': 'Industrials (Công nghiệp)', 'DXG': 'Industrials (Công nghiệp)', 'NLG': 'Industrials (Công nghiệp)',
    'KDH': 'Industrials (Công nghiệp)', 'PDR': 'Industrials (Công nghiệp)', 'DIG': 'Industrials (Công nghiệp)',
    'HQC': 'Industrials (Công nghiệp)', 'SZC': 'Industrials (Công nghiệp)', 'IDC': 'Industrials (Công nghiệp)',
    
    # 4. Oil & Gas (Dầu khí)
    'GAS': 'Oil & Gas (Dầu khí)', 'PLX': 'Oil & Gas (Dầu khí)', 'PVD': 'Oil & Gas (Dầu khí)',
    'PVS': 'Oil & Gas (Dầu khí)', 'PVB': 'Oil & Gas (Dầu khí)', 'PVC': 'Oil & Gas (Dầu khí)',
    'PVG': 'Oil & Gas (Dầu khí)', 'PGS': 'Oil & Gas (Dầu khí)', 'BSR': 'Oil & Gas (Dầu khí)',
    'OIL': 'Oil & Gas (Dầu khí)', 'CNG': 'Oil & Gas (Dầu khí)', 'POS': 'Oil & Gas (Dầu khí)',
    'TDG': 'Oil & Gas (Dầu khí)', 'PSH': 'Oil & Gas (Dầu khí)', 'PPC': 'Oil & Gas (Dầu khí)',
    'POW': 'Oil & Gas (Dầu khí)', 'NT2': 'Oil & Gas (Dầu khí)', 'PGD': 'Oil & Gas (Dầu khí)',
    'ASP': 'Oil & Gas (Dầu khí)', 'PMB': 'Oil & Gas (Dầu khí)',
    
    # 5. Technology (Công nghệ)
    'FPT': 'Technology (Công nghệ)', 'CMG': 'Technology (Công nghệ)', 'ELC': 'Technology (Công nghệ)',
    'ITD': 'Technology (Công nghệ)', 'FOX': 'Technology (Công nghệ)', 'CTR': 'Technology (Công nghệ)',
    'VGI': 'Technology (Công nghệ)', 'TTN': 'Technology (Công nghệ)', 'SGT': 'Technology (Công nghệ)',
    'ST8': 'Technology (Công nghệ)', 'ONE': 'Technology (Công nghệ)', 'ICT': 'Technology (Công nghệ)',
    'VTC': 'Technology (Công nghệ)', 'VNT': 'Technology (Công nghệ)'
}

def run_ols_regression(X_vals, y_vals):
    """
    Fits y = X * b + e and calculates Stata-like regression statistics:
    Coefficients, Standard Errors, t-statistics, p-values, R-squared, Adj R-squared
    """
    y_arr = np.asarray(y_vals, dtype=float)
    X_mat = np.asarray(X_vals, dtype=float)
    n = len(y_arr)
    
    # Add constant column for Intercept
    X = np.column_stack([np.ones(n, dtype=float), X_mat])
    p = X.shape[1]  # Number of features including constant
    
    # Solve OLS: beta = (X^T * X)^-1 * X^T * y
    try:
        beta = np.linalg.solve(X.T @ X, X.T @ y_arr)
    except np.linalg.LinAlgError:
        # Fallback to pseudoinverse if matrix is singular
        beta = np.linalg.pinv(X) @ y_arr
        
    y_pred = X @ beta
    residuals = y_arr - y_pred
    
    # Sum of squares
    sse = float(np.sum(residuals ** 2))
    sst = float(np.sum((y_arr - np.mean(y_arr)) ** 2))
    
    # R-squared and Adj R-squared
    r2 = 1.0 - (sse / sst) if sst != 0 else 0.0
    adj_r2 = 1.0 - ((sse / (n - p)) / (sst / (n - 1))) if (n - p) > 0 and sst != 0 else r2
    
    # Standard errors of coefficients
    s2 = sse / (n - p) if (n - p) > 0 else 0.0
    try:
        inv_xtx = np.linalg.inv(X.T @ X)
        se = np.sqrt(s2 * np.diag(inv_xtx))
    except np.linalg.LinAlgError:
        inv_xtx = np.linalg.pinv(X.T @ X)
        se = np.sqrt(s2 * np.diag(inv_xtx))
        
    t_stats = np.divide(beta, se, out=np.zeros_like(beta), where=se != 0)
    p_values = 2 * (1.0 - stats.t.cdf(np.abs(t_stats), df=n - p)) if (n - p) > 0 else np.zeros_like(t_stats)
    
    return {
        'n': int(n),
        'beta': [float(b) for b in beta],       # [intercept, beta1, beta2]
        'se': [float(s) for s in se],
        't_stats': [float(t) for t in t_stats],
        'p_values': [float(pv) for pv in p_values],
        'r2': float(r2),
        'adj_r2': float(adj_r2)
    }

def process_and_run_regressions(file_path):
    """
    Đọc tệp Panel Data, ánh xạ ngành, tính toán Z'-Score, chạy hồi quy bậc hai OLS
    và trả về hệ số đòn bẩy tối ưu cùng các thông số thống kê.
    """
    # 1. Kiểm tra định dạng tệp và nạp dữ liệu
    _, ext = os.path.splitext(file_path)
    if ext.lower() in ['.xlsx', '.xls']:
        try:
            df_raw = pd.read_excel(file_path, sheet_name="Data_Entry")
        except Exception:
            df_raw = pd.read_excel(file_path)
    else:
        df_raw = pd.read_csv(file_path)
        
    # 2. Chuẩn hóa tên cột
    cols_to_use = {
        'Mã chứng khoán': 'symbol',
        'Mã CK': 'symbol',
        'Total_Assets\n[270]': 'ta',
        'Total_Assets': 'ta',
        'Total_Liabilities\n[300]': 'liab',
        'Total_Liabilities': 'liab',
        'Current_Assets\n[100]': 'ca',
        'Current_Assets': 'ca',
        'Current_Liabilities\n[310]': 'cl',
        'Current_Liabilities': 'cl',
        'Retained_Earnings\n[421]': 're',
        'Retained_Earnings': 're',
        'EBT\n[50]': 'ebt',
        'EBT': 'ebt',
        'Interest_Expense\n[23]': 'interest',
        'Interest_Expense': 'interest',
        'Equity\n[400]': 'eq',
        'Equity': 'eq',
        'Net_Sales\n[10]': 'sales',
        'Net_Sales': 'sales'
    }
    
    # Chuẩn hóa khoảng trắng và dấu xuống dòng trong tên cột
    cleaned_cols = {col: col.replace('\r\n', '\n').replace('\r', '\n').strip() for col in df_raw.columns}
    df_renamed = df_raw.rename(columns=cleaned_cols)
    
    for orig_name, standard_name in cols_to_use.items():
        clean_orig = orig_name.replace('\r\n', '\n').strip()
        if clean_orig in df_renamed.columns and standard_name not in df_renamed.columns:
            df_renamed[standard_name] = df_renamed[clean_orig]
            
    # Bổ sung các cột còn thiếu dạng NaN
    for std_name in ['symbol', 'ta', 'liab', 'ca', 'cl', 're', 'ebt', 'interest', 'eq', 'sales']:
        if std_name not in df_renamed.columns:
            df_renamed[std_name] = np.nan
            
    df = df_renamed[['symbol', 'ta', 'liab', 'ca', 'cl', 're', 'ebt', 'interest', 'eq', 'sales']].dropna(subset=['symbol', 'ta', 'liab']).copy()
    df['symbol'] = df['symbol'].astype(str).str.strip().str.upper()
    df['ta'] = pd.to_numeric(df['ta'], errors='coerce')
    df['liab'] = pd.to_numeric(df['liab'], errors='coerce')
    df = df[df['ta'] > 0].copy()
    
    if len(df) == 0:
        raise ValueError("Tệp không chứa đủ dữ liệu tài chính hợp lệ (thiếu Tài sản, Nợ hoặc Mã chứng khoán).")
        
    # 3. Ánh xạ ngành
    # Cách 1: Kiểm tra cột Ngành sẵn có trong file
    if 'Ngành' in df_renamed.columns:
        df['raw_ind'] = df_renamed['Ngành']
        df['mapped_industry'] = df['raw_ind'].map(SECTOR_MAPPING)
    else:
        df['mapped_industry'] = np.nan
        
    # Cách 2: Bổ sung từ từ điển SYMBOL_TO_SECTOR_DICT
    df['mapped_industry'] = df['mapped_industry'].fillna(df['symbol'].map(SYMBOL_TO_SECTOR_DICT))

    # Lọc các dòng đã có phân ngành chuẩn
    df = df.dropna(subset=['mapped_industry']).copy()
    if len(df) == 0:
        raise ValueError("Không khớp được mã cổ phiếu nào với 5 nhóm ngành chuẩn. Hãy kiểm tra lại cột 'Mã chứng khoán'.")
        
    # 4. Tính toán các thành phần của Altman Z'-Score
    for col in ['ca', 'cl', 're', 'ebt', 'interest', 'eq', 'sales']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    
    df['x1'] = (df['ca'] - df['cl']) / df['ta']
    df['x2'] = df['re'] / df['ta']
    df['x3'] = (df['ebt'] + df['interest']) / df['ta']
    df['x4'] = np.where(df['liab'] > 0, df['eq'] / df['liab'], 0)
    df['x5'] = df['sales'] / df['ta']
    df['lev'] = df['liab'] / df['ta']
    
    # 5. Chạy hồi quy Panel OLS cho từng nhóm ngành
    results = {}
    for name, group in df.groupby('mapped_industry'):
        if len(group) < 15:
            continue
            
        # Winsorize components tại 1% và 99%
        x1_w = np.asarray(stats.mstats.winsorize(group['x1'].values, limits=[0.01, 0.01]), dtype=float)
        x2_w = np.asarray(stats.mstats.winsorize(group['x2'].values, limits=[0.01, 0.01]), dtype=float)
        x3_w = np.asarray(stats.mstats.winsorize(group['x3'].values, limits=[0.01, 0.01]), dtype=float)
        x4_w = np.asarray(stats.mstats.winsorize(group['x4'].values, limits=[0.01, 0.01]), dtype=float)
        x5_w = np.asarray(stats.mstats.winsorize(group['x5'].values, limits=[0.01, 0.01]), dtype=float)
        
        # Altman Z'-Score (Phiên bản thị trường mới nổi)
        z_prime = 0.717 * x1_w + 0.847 * x2_w + 3.107 * x3_w + 0.420 * x4_w + 0.998 * x5_w
        lev_w = np.asarray(stats.mstats.winsorize(group['lev'].values, limits=[0.01, 0.01]), dtype=float)
        z_prime_w = np.asarray(stats.mstats.winsorize(z_prime, limits=[0.01, 0.01]), dtype=float)
        
        X_vals = np.column_stack([lev_w, lev_w ** 2])
        
        # Chạy OLS
        model_stats = run_ols_regression(X_vals, z_prime_w)
        
        b0 = model_stats['beta'][0]
        b1 = model_stats['beta'][1]
        b2 = model_stats['beta'][2]
        
        # Tính điểm đòn bẩy tối ưu: opt_lev = -b1 / (2 * b2) (khi b2 < 0)
        opt_lev = -b1 / (2 * b2) if b2 < 0 else np.nan
        
        results[name] = {
            'n': model_stats['n'],
            'b0': b0,
            'b1': b1,
            'b2': b2,
            'p_b0': model_stats['p_values'][0],
            'p_b1': model_stats['p_values'][1],
            'p_b2': model_stats['p_values'][2],
            'r2': model_stats['r2'],
            'adj_r2': model_stats['adj_r2'],
            'opt_lev': opt_lev,
            'lev_data': lev_w.tolist(),
            'z_data': z_prime_w.tolist()
        }
        
    return results
