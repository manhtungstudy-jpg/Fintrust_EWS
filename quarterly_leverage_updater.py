# -*- coding: utf-8 -*-
"""
quarterly_leverage_updater.py
-----------------------------
Bộ điều phối và thực thi tính năng Tự động Tái ước lượng Đòn bẩy Tối ưu (U-Curve Regression)
theo chu kỳ 1 Quý / 1 Lần (Quarterly Auto-Update Scheduler).

Chức năng:
1. Tự động kiểm tra thời hạn (sau mỗi 90 ngày hoặc khi bước sang quý tài chính mới).
2. Tự động nạp dữ liệu BCTC Panel toàn diện.
3. Chạy mô hình hồi quy Panel OLS bậc hai (Z' = b0 + b1*LEV + b2*LEV^2) cho 5 nhóm ngành phi tài chính.
4. Tự động cập nhật các ngưỡng đòn bẩy tối ưu mới vào `industry_opt_lev.json`.
5. Ghi nhật ký chi tiết các chu kỳ cập nhật vào `quarterly_scheduler_config.json`.
"""

import os
import json
import datetime
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "quarterly_scheduler_config.json")
INDUSTRY_CONFIG_FILE = os.path.join(BASE_DIR, "industry_opt_lev.json")
DEFAULT_PANEL_FILE = os.path.join(BASE_DIR, "BCTC_Tu_Dong_Vnstock.xlsx")

DEFAULT_SCHEDULER_CONFIG = {
    "auto_update_enabled": True,
    "interval_days": 90,  # 1 quý (khoảng 90 ngày)
    "last_run": None,
    "next_run": None,
    "auto_apply_thresholds": True,
    "last_status": "Chưa khởi chạy",
    "last_error": None,
    "last_summary": {},
    "history": []
}

def get_next_quarter_date(from_date=None):
    """
    Tính thời điểm cập nhật kế tiếp (khoảng 90 ngày sau hoặc đầu quý kế tiếp).
    """
    if from_date is None:
        from_date = datetime.datetime.now()
    next_date = from_date + datetime.timedelta(days=90)
    return next_date.strftime("%Y-%m-%d %H:%M:%S")

def load_scheduler_config():
    """Đọc cấu hình lập lịch cập nhật định kỳ."""
    if not os.path.exists(CONFIG_FILE):
        cfg = DEFAULT_SCHEDULER_CONFIG.copy()
        now = datetime.datetime.now()
        cfg["next_run"] = get_next_quarter_date(now)
        save_scheduler_config(cfg)
        return cfg
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            for k, v in DEFAULT_SCHEDULER_CONFIG.items():
                if k not in cfg:
                    cfg[k] = v
            return cfg
    except Exception as e:
        print(f"[WARN] Lỗi khi đọc {CONFIG_FILE}: {e}")
        return DEFAULT_SCHEDULER_CONFIG.copy()

def save_scheduler_config(cfg):
    """Lưu cấu hình lập lịch cập nhật định kỳ."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[ERROR] Không thể lưu {CONFIG_FILE}: {e}")
        return False

def execute_quarterly_update(panel_file_path=None, force=False):
    """
    Thực hiện quy trình tái ước lượng đòn bẩy tối ưu theo chu kỳ quý.
    
    Args:
        panel_file_path: Đường dẫn tệp Panel Data (Excel/CSV). Mặc định lấy tệp chuẩn BCTC_Tu_Dong_Vnstock.xlsx.
        force: Nếu True, bỏ qua kiểm tra ngày hẹn và thực hiện ngay lập tức.
        
    Returns:
        tuple: (success: bool, message: str, results: dict)
    """
    cfg = load_scheduler_config()
    now_dt = datetime.datetime.now()
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    
    # Kiểm tra điều kiện thực thi
    if not force and not cfg.get("auto_update_enabled", True):
        return False, "Tính năng tự động cập nhật định kỳ đang bị TẮT.", {}
        
    if not force and cfg.get("next_run"):
        try:
            next_run_dt = datetime.datetime.strptime(cfg["next_run"], "%Y-%m-%d %H:%M:%S")
            if now_dt < next_run_dt:
                days_left = (next_run_dt - now_dt).days
                return False, f"Chưa đến hạn cập nhật quý tiếp theo (còn {days_left} ngày, dự kiến: {cfg['next_run']}).", {}
        except Exception:
            pass

    # Xác định tệp dữ liệu panel
    target_file = panel_file_path or DEFAULT_PANEL_FILE
    if not os.path.exists(target_file):
        error_msg = f"Không tìm thấy tệp dữ liệu Panel chuẩn tại: {target_file}"
        cfg["last_status"] = "Thất bại"
        cfg["last_error"] = error_msg
        save_scheduler_config(cfg)
        return False, error_msg, {}

    try:
        from u_curve_regression import process_and_run_regressions
        reg_results = process_and_run_regressions(target_file)
        
        if not reg_results:
            error_msg = "Không có ngành nào đủ điều kiện hồi quy (N >= 15 quan sát)."
            cfg["last_status"] = "Thất bại"
            cfg["last_error"] = error_msg
            save_scheduler_config(cfg)
            return False, error_msg, {}
            
        # Đọc ngưỡng hiện tại
        current_thresholds = {
            "Basic Materials (Nguyên vật liệu)": 0.7450,
            "Consumer Goods (Hàng tiêu dùng)": 0.5201,
            "Industrials (Công nghiệp)": 0.3989,
            "Oil & Gas (Dầu khí)": 1.1176,
            "Technology (Công nghệ)": 0.4441
        }
        if os.path.exists(INDUSTRY_CONFIG_FILE):
            try:
                with open(INDUSTRY_CONFIG_FILE, "r", encoding="utf-8") as f:
                    current_thresholds.update(json.load(f))
            except Exception:
                pass
                
        # Tổng hợp kết quả mới
        new_thresholds = current_thresholds.copy()
        summary_results = {}
        
        for ind, res in reg_results.items():
            opt = res.get('opt_lev', np.nan)
            if not np.isnan(opt) and 0 < opt < 2.0:
                new_thresholds[ind] = round(float(opt), 4)
            
            summary_results[ind] = {
                "n_samples": int(res['n']),
                "optimal_leverage": round(float(opt), 4) if not np.isnan(opt) else None,
                "r_squared": round(float(res['r2']), 4),
                "adj_r_squared": round(float(res['adj_r2']), 4),
                "p_value_b2": round(float(res['p_b2']), 4),
                "b0": round(float(res['b0']), 4),
                "b1": round(float(res['b1']), 4),
                "b2": round(float(res['b2']), 4)
            }
            
        # Áp dụng ngưỡng mới vào industry_opt_lev.json nếu được cấu hình
        if cfg.get("auto_apply_thresholds", True):
            with open(INDUSTRY_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(new_thresholds, f, indent=4, ensure_ascii=False)
                
        # Cập nhật thông tin scheduler
        next_run_str = get_next_quarter_date(now_dt)
        cfg["last_run"] = now_str
        cfg["next_run"] = next_run_str
        cfg["last_status"] = "Thành công"
        cfg["last_error"] = None
        cfg["last_summary"] = summary_results
        
        # Thêm vào lịch sử (giữ tối đa 20 kỳ gần nhất)
        quarter_name = f"Q{(now_dt.month - 1) // 3 + 1}/{now_dt.year}"
        history_entry = {
            "timestamp": now_str,
            "quarter": quarter_name,
            "file_used": os.path.basename(target_file),
            "sectors_count": len(summary_results),
            "applied_thresholds": new_thresholds
        }
        history = cfg.get("history", [])
        # Tránh trùng lặp timestamp
        history = [h for h in history if h.get("timestamp") != now_str]
        history.insert(0, history_entry)
        cfg["history"] = history[:20]
        
        save_scheduler_config(cfg)
        return True, f"Tái ước lượng quý {quarter_name} thành công! Đã cập nhật {len(summary_results)} ngành.", summary_results

    except Exception as e:
        error_msg = f"Lỗi trong quá trình hồi quy: {str(e)}"
        cfg["last_status"] = "Thất bại"
        cfg["last_error"] = error_msg
        save_scheduler_config(cfg)
        return False, error_msg, {}

def check_and_auto_update_if_due():
    """
    Hàm kiểm tra nhanh không chặn (non-blocking) được gọi khi ứng dụng khởi động.
    Nếu đã đến hạn 1 quý/1 lần thì tự động chạy cập nhật.
    """
    cfg = load_scheduler_config()
    if not cfg.get("auto_update_enabled", True):
        return False
        
    next_run = cfg.get("next_run")
    if not next_run:
        return False
        
    try:
        now_dt = datetime.datetime.now()
        next_run_dt = datetime.datetime.strptime(next_run, "%Y-%m-%d %H:%M:%S")
        if now_dt >= next_run_dt:
            # Đến hạn cập nhật
            success, msg, _ = execute_quarterly_update(force=True)
            print(f"[QUARTERLY-SCHEDULER] {msg}")
            return success
    except Exception as ex:
        print(f"[QUARTERLY-SCHEDULER-ERROR] {ex}")
    return False

if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    
    if "--force" in args or "-f" in args or "--run" in args:
        print("[*] Đang thực thi tái ước lượng đòn bẩy tối ưu quý ngay lập tức...")
        success, msg, res = execute_quarterly_update(force=True)
        print(f"[{'SUCCESS' if success else 'FAILED'}] {msg}")
        if success:
            for ind, details in res.items():
                opt_str = f"{details['optimal_leverage']:.2%}" if details.get('optimal_leverage') is not None else "Không xác định"
                print(f" - {ind}: Đòn bẩy tối ưu = {opt_str}, R2 = {details['r_squared']:.4f}, N = {details['n_samples']}")
    elif "--status" in args or "-s" in args:
        cfg = load_scheduler_config()
        print(json.dumps(cfg, indent=4, ensure_ascii=False))
    else:
        print("[*] Đang kiểm tra lịch trình cập nhật 1 quý/1 lần...")
        success, msg, _ = execute_quarterly_update(force=False)
        print(f"Status: {msg}")
