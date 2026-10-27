# -*- coding: utf-8 -*-
"""
credit_underwriting_engine.py
------------------------------
Động cơ Thẩm định Tín dụng Doanh nghiệp Chuẩn Ngân hàng Thương mại (Bank-Grade Underwriting Engine).
Bổ sung các trụ cột nghiệp vụ thẩm định thực tế:
1. Tính toán Nhu cầu Vốn lưu động & Hạn mức Cấp tín dụng (Working Capital Sizing)
2. Thẩm định & Định giá Danh mục Tài sản Bảo đảm (Collateral & LTV Evaluation)
3. Động cơ Sinh Điều kiện Tín dụng Tự động (Smart Credit Covenants Generator) dựa trên EWS & 5Cs
4. Ma trận Nhận diện Rủi ro & Biện pháp Giảm thiểu (Risk Matrix)
5. Phân cấp Thẩm quyền Phê duyệt & Đối chiếu Khác biệt Chính sách (ĐVKD vs Khối Thẩm định)
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional

def calculate_working_capital_need(
    extracted_data: Dict[int, Dict[str, float]],
    selected_year: int,
    expected_sales_growth: float = 0.15,
    custom_planned_sales: Optional[float] = None,
    equity_contribution_pct: float = 0.25,
    max_tenor_months: int = 5
) -> Dict[str, Any]:
    """
    Tính toán Nhu cầu Vốn lưu động ròng và Hạn mức Tín dụng theo chuẩn nghiệp vụ NHTM
    (Tương đương phương pháp tính trong Phụ lục Báo cáo Thẩm định MB Bank).
    
    Công thức cốt lõi:
    - Vòng quay VLĐ (T) = Doanh thu thuần / Vốn lưu động bình quân
    - Tổng nhu cầu VLĐ = Doanh thu kế hoạch / Vòng quay VLĐ
    - Vốn tự có tham gia = Tổng nhu cầu VLĐ * Tỷ lệ vốn tự có (tối thiểu 20-30%)
    - Vốn chiếm dụng nhà cung cấp = Phải trả người bán kế hoạch
    - Hạn mức Vay VLĐ Tối đa = Tổng nhu cầu VLĐ - Vốn tự có - Vốn chiếm dụng
    """
    try:
        yr_int = int(selected_year)
    except (ValueError, TypeError):
        yr_int = datetime.datetime.now().year

    curr_data = extracted_data.get(yr_int) or extracted_data.get(selected_year) or {}
    prev_year = yr_int - 1
    prev_data = extracted_data.get(prev_year) or extracted_data.get(str(prev_year)) or curr_data
    
    curr_sales = curr_data.get("Net_Sales", 0.0) or 0.0
    curr_cogs = curr_data.get("COGS", 0.0) or 0.0
    curr_rec = curr_data.get("Accounts_Receivable", 0.0) or curr_data.get("Current_Receivables", 0.0) or 0.0
    curr_inv = curr_data.get("Inventories", 0.0) or 0.0
    curr_pay = curr_data.get("Payables", 0.0) or curr_data.get("Current_Liabilities", 0.0) * 0.35
    curr_ca = curr_data.get("Current_Assets", 0.0) or (curr_rec + curr_inv)
    curr_cl = curr_data.get("Current_Liabilities", 0.0) or 0.0
    curr_st_debt = curr_data.get("Short_Term_Debt", 0.0) or (curr_cl * 0.6)
    curr_cash = curr_data.get("Cash_Equivalents", 0.0) or 0.0
    
    # 1. Doanh thu kế hoạch
    if custom_planned_sales and custom_planned_sales > 0:
        planned_sales = float(custom_planned_sales)
    elif curr_sales > 0:
        planned_sales = curr_sales * (1.0 + expected_sales_growth)
    else:
        planned_sales = 100_000_000_000.0  # Mặc định 100 tỷ nếu chưa có số
        
    cogs_ratio = (curr_cogs / curr_sales) if (curr_sales > 0 and curr_cogs > 0) else 0.82
    planned_cogs = planned_sales * cogs_ratio
    
    # 2. Tính toán các chu kỳ hoạt động và vòng quay
    dso = (curr_rec / curr_sales * 365.0) if curr_sales > 0 else 45.0
    dsi = (curr_inv / curr_cogs * 365.0) if curr_cogs > 0 else 60.0
    dpo = (curr_pay / curr_cogs * 365.0) if curr_cogs > 0 else 35.0
    operating_cycle = dso + dsi
    ccc = operating_cycle - dpo
    
    # Vòng quay VLĐ lịch sử
    avg_ca = (curr_ca + prev_data.get("Current_Assets", curr_ca)) / 2.0
    wc_turnover = (curr_sales / avg_ca) if (avg_ca > 0 and curr_sales > 0) else (365.0 / max(30.0, operating_cycle))
    wc_turnover = max(1.2, min(12.0, wc_turnover))  # Giới hạn ngưỡng thực tế
    
    # 3. Tính toán Tổng nhu cầu VLĐ & Nguồn bù đắp
    total_wc_need = planned_sales / wc_turnover
    equity_contribution = total_wc_need * equity_contribution_pct
    
    # Ước tính vốn chiếm dụng nhà cung cấp trong năm kế hoạch
    planned_supplier_credit = planned_cogs * (dpo / 365.0)
    
    # Nhu cầu vay vốn lưu động tối đa đề xuất
    uncovered_wc_need = total_wc_need - equity_contribution - planned_supplier_credit
    recommended_credit_limit = max(0.0, uncovered_wc_need)
    
    # Làm tròn đến 100 triệu
    recommended_credit_limit_rounded = round(recommended_credit_limit / 100_000_000.0) * 100_000_000.0
    
    # 4. Cân đối tiền hàng và khả năng tự tài trợ
    wc_assets = curr_rec + curr_inv
    debt_to_wc_assets_ratio = (curr_st_debt / wc_assets) if wc_assets > 0 else 1.0
    funding_gap = wc_assets - curr_st_debt
    
    # Thời gian vay tối đa trên mỗi khế ước nhận nợ (KUNN)
    recommended_ku_tenor = min(max_tenor_months, max(2, int(round(365.0 / wc_turnover / 30.0))))
    
    return {
        "selected_year": selected_year,
        "curr_sales": curr_sales,
        "planned_sales": planned_sales,
        "planned_cogs": planned_cogs,
        "cogs_ratio": cogs_ratio,
        "dso": dso,
        "dsi": dsi,
        "dpo": dpo,
        "operating_cycle": operating_cycle,
        "ccc": ccc,
        "wc_turnover": wc_turnover,
        "total_wc_need": total_wc_need,
        "equity_contribution_pct": equity_contribution_pct,
        "equity_contribution": equity_contribution,
        "planned_supplier_credit": planned_supplier_credit,
        "uncovered_wc_need": uncovered_wc_need,
        "recommended_credit_limit": recommended_credit_limit_rounded,
        "recommended_ku_tenor_months": recommended_ku_tenor,
        "curr_st_debt": curr_st_debt,
        "curr_rec": curr_rec,
        "curr_inv": curr_inv,
        "wc_assets": wc_assets,
        "debt_to_wc_assets_ratio": debt_to_wc_assets_ratio,
        "funding_gap": funding_gap,
        "curr_cash": curr_cash
    }


def evaluate_collaterals(
    collateral_items: List[Dict[str, Any]],
    total_requested_limit: float
) -> Dict[str, Any]:
    """
    Thẩm định danh mục Tài sản bảo đảm (TSBĐ), áp dụng LTV và phân tách dư nợ có TSBĐ / Tín chấp.
    
    Mỗi phần tử trong collateral_items gồm:
    - type: 'Bất động sản' | 'Tiền gửi / STK' | 'Phương tiện / Máy móc' | 'Hàng hóa / Quyền đòi nợ'
    - description: Mô tả chi tiết (ví dụ: Căn hộ chung cư Midtown, Giấy chứng nhận CX 655935)
    - market_value: Giá trị định giá thị trường (VND)
    - ltv_rate: Tỷ lệ cho vay tối đa (0.75 đối với BĐS, 0.95 đối với STK, 0.50 đối với máy móc...)
    """
    if not collateral_items:
        # Trường hợp không nhập TSBĐ: Mặc định cấu hình giả định an toàn
        collateral_items = [
            {
                "type": "Bất động sản",
                "description": "Bất động sản độc lập thế chấp (Nhà đất / Căn hộ)",
                "market_value": total_requested_limit * 1.1,
                "ltv_rate": 0.75
            }
        ]
        
    total_market_val = 0.0
    total_secured_capacity = 0.0
    processed_items = []
    
    for item in collateral_items:
        m_val = float(item.get("market_value", 0.0))
        ltv = float(item.get("ltv_rate", 0.75))
        sec_cap = m_val * ltv
        
        total_market_val += m_val
        total_secured_capacity += sec_cap
        
        processed_items.append({
            "type": item.get("type", "BĐS"),
            "description": item.get("description", "Tài sản bảo đảm"),
            "market_value": m_val,
            "ltv_rate": ltv,
            "secured_capacity": sec_cap
        })
        
    secured_facility_amount = min(total_requested_limit, total_secured_capacity)
    unsecured_facility_amount = max(0.0, total_requested_limit - secured_facility_amount)
    
    secured_ratio = (secured_facility_amount / total_requested_limit) if total_requested_limit > 0 else 1.0
    unsecured_ratio = 1.0 - secured_ratio
    
    coverage_ratio = (total_market_val / total_requested_limit) if total_requested_limit > 0 else 0.0
    
    # Đánh giá tính đáp ứng chuẩn chính sách TSBĐ (Ví dụ MB: TSBĐ độc lập tối thiểu 80%)
    meets_80_secured_rule = secured_ratio >= 0.80
    
    return {
        "items": processed_items,
        "total_market_value": total_market_val,
        "total_secured_capacity": total_secured_capacity,
        "total_requested_limit": total_requested_limit,
        "secured_facility_amount": secured_facility_amount,
        "unsecured_facility_amount": unsecured_facility_amount,
        "secured_ratio": secured_ratio,
        "unsecured_ratio": unsecured_ratio,
        "coverage_ratio": coverage_ratio,
        "meets_80_secured_rule": meets_80_secured_rule
    }


def generate_smart_credit_covenants(
    ticker: str,
    company_name: str,
    selected_year: int,
    ews_res: Dict[str, Any],
    wc_res: Dict[str, Any],
    qual_res: Optional[Dict[str, Any]] = None
) -> Dict[str, List[Dict[str, str]]]:
    """
    Động cơ Sinh Điều kiện Tín dụng Tự động (Smart Credit Covenants Generator).
    Dựa trên kết quả định lượng EWS, sức khỏe tài chính và 5Cs để sinh bộ điều kiện ràng buộc giải ngân.
    
    Chia thành 3 nhóm chuẩn:
    - Nhóm 1: Điều kiện tiên quyết trước giải ngân (Pre-disbursement Conditions)
    - Nhóm 2: Điều kiện quản lý & kiểm soát trong quá trình vay vốn (Post-disbursement & Cash Flow Monitoring)
    - Nhóm 3: Cam kết tài chính Covenants & Hạn chế quyền tài phán (Financial & Governance Covenants)
    """
    pre_conditions = []
    post_conditions = []
    covenants = []
    
    # 1. Điều kiện cơ bản mặc định
    pre_conditions.append({
        "code": "PRE-01",
        "title": "Hoàn tất thủ tục Thế chấp & Đăng ký Giao dịch Bảo đảm",
        "content": "Hoàn tất ký kết Hợp đồng thế chấp công chứng và đăng ký biện pháp bảo đảm tại Trung tâm Đăng ký giao dịch bảo đảm (hoặc Văn phòng Đăng ký đất đai) trước khi thực hiện giải ngân lần đầu.",
        "level": "Bắt buộc"
    })
    
    pre_conditions.append({
        "code": "PRE-02",
        "title": "Ủy quyền trích nợ tự động & Mở tài khoản chuyên dụng",
        "content": "Khách hàng ký Giấy ủy quyền vô điều kiện và không hủy ngang cho phép Ngân hàng tự động trích nợ từ tất cả các tài khoản thanh toán mở tại Ngân hàng để thu hồi nợ gốc, lãi và phí đến hạn.",
        "level": "Bắt buộc"
    })
    
    post_conditions.append({
        "code": "POST-01",
        "title": "Kiểm soát Dòng tiền Doanh thu qua Tài khoản",
        "content": f"Khách hàng cam kết chuyển tối thiểu tương ứng tỷ lệ dư nợ tại Ngân hàng trên tổng dư nợ các TCTD (tối thiểu không thấp hơn 70% tổng doanh thu thực tế) về tài khoản thanh toán mở tại Ngân hàng để quản lý dòng tiền.",
        "level": "Trọng yếu"
    })
    
    post_conditions.append({
        "code": "POST-02",
        "title": "Định kỳ Cung cấp Báo cáo Tài chính & Tờ khai Thuế",
        "content": "Định kỳ chậm nhất 45 ngày sau khi kết thúc quý, Khách hàng phải cung cấp Báo cáo tài chính nội bộ, Báo cáo tài chính gửi cơ quan thuế và Tờ khai thuế GTGT kèm sao kê tài khoản ngân hàng để Ngân hàng rà soát.",
        "level": "Trọng yếu"
    })
    
    # 2. Điều kiện sinh ra từ Rủi ro Gian lận BCTC (Beneish M-Score & Dechow F-Score)
    m_score = ews_res.get("Beneish_M_Score", {}).get("score")
    f_score = ews_res.get("Dechow_F_Score", {}).get("score")
    
    if (m_score is not None and m_score > -1.78) or (f_score is not None and f_score > 1.85):
        pre_conditions.append({
            "code": "EWS-PRE-FRAUD",
            "title": "Kiểm tra Hóa đơn VAT Điện tử & Hợp đồng Đầu vào/Đầu ra",
            "content": "Đối với mỗi khế ước nhận nợ (KUNN), Chuyên viên quản lý tín dụng phải thực hiện tra cứu 100% hóa đơn GTGT đầu vào/đầu ra trên Cổng thông tin Tổng cục Thuế (tracuuhoadon.gdt.gov.vn) để xác thực tính hợp pháp, không giải ngân đối với hóa đơn doanh nghiệp rủi ro cao về thuế.",
            "level": "Cảnh báo Đỏ (Gian lận BCTC)"
        })
        post_conditions.append({
            "code": "EWS-POST-AUDIT",
            "title": "Yêu cầu Kiểm toán Độc lập uy tín",
            "content": "Khách hàng phải thuê công ty kiểm toán độc lập thuộc danh sách các hãng kiểm toán uy tín (Big 4 hoặc Top 10 tại Việt Nam) thực hiện kiểm toán Báo cáo tài chính năm.",
            "level": "Cảnh báo Đỏ"
        })

    # 3. Điều kiện sinh ra từ Thao túng hoạt động thực (Roychowdhury REM)
    prod_score = ews_res.get("Abnormal_PROD", {}).get("score")
    cfo_score = ews_res.get("Abnormal_CFO", {}).get("score")
    
    if prod_score is not None and prod_score > 0.05:
        post_conditions.append({
            "code": "EWS-POST-INV",
            "title": "Kiểm kê Kho & Giám sát Hàng Tồn kho Chậm luân chuyển",
            "content": "Định kỳ hàng quý, Ngân hàng phối hợp cùng Khách hàng thực hiện kiểm kê thực tế kho hàng. Ngân hàng không chấp nhận tài trợ hoặc nhận làm TSBĐ đối với các lô hàng tồn kho hư hỏng, cận hạn sử dụng (dưới 6 tháng đối với thực phẩm/hàng tiêu dùng) hoặc không có biến động xuất nhập tồn.",
            "level": "Giám sát Tồn kho"
        })
        
    if cfo_score is not None and cfo_score < -0.05:
        post_conditions.append({
            "code": "EWS-POST-REC",
            "title": "Giám sát Phải thu Khách hàng & Điều khoản Thanh toán Bán chịu",
            "content": "Khách hàng cam kết duy trì kỳ thu tiền bình quân (DSO) không quá 60 ngày. Ngân hàng có quyền từ chối giải ngân đối với các khoản phải thu của đối tác phát sinh nợ quá hạn hoặc đối tác có quan hệ liên kết/sân sau với cổ đông công ty.",
            "level": "Giám sát Phải thu"
        })

    # 4. Điều kiện sinh ra từ Kiệt quệ Tài chính & Đòn bẩy (Altman Z' & Debt/WC)
    z_score = ews_res.get("Altman_Z_Prime", {}).get("score")
    debt_ratio = wc_res.get("debt_to_wc_assets_ratio", 1.0)
    
    if (z_score is not None and z_score <= 1.23) or (debt_ratio > 1.0):
        covenants.append({
            "code": "COV-01-DIVIDEND",
            "title": "Ràng buộc Cổ tức & Rút vốn (Dividend Lockup)",
            "content": "Khách hàng cam kết không thực hiện chia cổ tức, không rút vốn, không tạm ứng vốn cho các cổ đông sáng lập hoặc thành viên góp vốn chừng nào chưa hoàn thành đầy đủ nghĩa vụ trả nợ gốc và lãi theo các KUNN tại Ngân hàng.",
            "level": "Ràng buộc Pháp lý"
        })
        covenants.append({
            "code": "COV-02-LEVERAGE",
            "title": "Duy trì Tỷ lệ Đòn bẩy Tài chính Tối đa",
            "content": "Khách hàng cam kết duy trì Tỷ lệ Tổng nợ phải trả / Vốn chủ sở hữu (D/E) không vượt quá 3.5 lần và Hệ số thanh toán hiện hành (Current Ratio) luôn duy trì lớn hơn hoặc bằng 1.1 lần tại mọi thời điểm lập BCTC.",
            "level": "Financial Covenant"
        })
        covenants.append({
            "code": "COV-03-DEBT-LIMIT",
            "title": "Hạn chế Phát sinh Nợ vay Mới ngoài Kế hoạch",
            "content": "Khách hàng không được vay nợ mới hoặc bảo lãnh cho bên thứ ba vượt quá 10 tỷ đồng tại các TCTD khác nếu không có sự chấp thuận trước bằng văn bản của Ngân hàng.",
            "level": "Negative Pledge"
        })
    else:
        covenants.append({
            "code": "COV-01-STD",
            "title": "Duy trì Hệ số Thanh toán Ngắn hạn",
            "content": "Khách hàng cam kết duy trì Hệ số Thanh toán ngắn hạn (CR) >= 1.05 và Hệ số Thanh toán nhanh (QR) >= 0.65 trong suốt thời gian duy trì hạn mức.",
            "level": "Financial Covenant"
        })
        covenants.append({
            "code": "COV-02-PURPOSE",
            "title": "Cam kết Sử dụng Vốn đúng Mục đích",
            "content": "Vốn vay ngắn hạn chỉ được sử dụng thanh toán tiền hàng cho các nhà cung cấp phục vụ trực tiếp ngành nghề kinh doanh chính, tuyệt đối không sử dụng để đầu tư chứng khoán, bất động sản hoặc góp vốn công ty liên kết.",
            "level": "Mục đích Vốn"
        })

    return {
        "pre_conditions": pre_conditions,
        "post_conditions": post_conditions,
        "financial_covenants": covenants
    }


def build_credit_risk_matrix(
    ews_res: Dict[str, Any],
    wc_res: Dict[str, Any],
    collateral_res: Optional[Dict[str, Any]] = None,
    qual_res: Optional[Dict[str, Any]] = None
) -> List[Dict[str, str]]:
    """
    Xây dựng Ma trận Nhận diện Rủi ro & Biện pháp Giảm thiểu Toàn diện
    (Chuẩn Phụ lục Rủi ro trong Báo cáo Thẩm định MB Bank).
    """
    matrix = []
    
    # 1. Rủi ro Cân đối Vốn & Dòng tiền
    debt_ratio = wc_res.get("debt_to_wc_assets_ratio", 0.0)
    ccc_days = wc_res.get("ccc", 0.0)
    
    if debt_ratio > 1.0:
        matrix.append({
            "category": "Rủi ro Cân đối Nguồn vốn",
            "risk_detail": f"Vốn vay ngắn hạn ngân hàng ({wc_res.get('curr_st_debt', 0)/1e9:,.2f} tỷ) vượt quá tổng giá trị Phải thu khách hàng và Hàng tồn kho ({wc_res.get('wc_assets', 0)/1e9:,.2f} tỷ). Tỷ lệ Vay / (PT + TK) = {debt_ratio:.1%}. Có nguy cơ doanh nghiệp sử dụng vốn ngắn hạn tài trợ cho tài sản dài hạn ngoài ngành.",
            "mitigation": "Yêu cầu cung cấp hồ sơ kiểm tra mục đích sử dụng vốn của tất cả các KUNN; áp dụng điều kiện thu nợ từng đợt theo dòng tiền thu từ đối tác; khống chế giải ngân thanh toán chuyển khoản trực tiếp cho nhà cung cấp."
        })
    else:
        matrix.append({
            "category": "Rủi ro Cân đối Nguồn vốn",
            "risk_detail": f"Khách hàng có cơ cấu vốn lưu động tương đối an toàn, Vốn vay ngắn hạn nằm trong giới hạn tự tài trợ của Phải thu và Hàng tồn kho (Tỷ lệ {debt_ratio:.1%}).",
            "mitigation": "Duy trì giám sát chu kỳ thu hồi công nợ và tỷ lệ luân chuyển hàng tồn kho định kỳ hàng quý."
        })
        
    # 2. Rủi ro Gian lận & Tính xác thực BCTC
    m_score = ews_res.get("Beneish_M_Score", {}).get("score")
    f_score = ews_res.get("Dechow_F_Score", {}).get("score")
    
    if (m_score is not None and m_score > -1.78) or (f_score is not None and f_score > 1.85):
        m_str = f"{m_score:.2f}" if m_score is not None else "N/A"
        f_str = f"{f_score:.2f}" if f_score is not None else "N/A"
        matrix.append({
            "category": "Rủi ro Tính Xác thực BCTC",
            "risk_detail": f"Mô hình cảnh báo gian lận phát hiện dấu hiệu bất thường (Beneish M-Score = {m_str} > -1.78 hoặc Dechow F-Score = {f_str} > 1.85). Xác suất doanh nghiệp ghi nhận doanh thu non hoặc bóp méo chi phí là đáng kể.",
            "mitigation": "Không phê duyệt giải ngân dựa trên BCTC nội bộ chưa xác thực. Bắt buộc tra cứu hóa đơn điện tử tại Cổng Tổng cục Thuế và đối chiếu sao kê tài khoản ngân hàng để xác nhận dòng tiền thanh toán thực."
        })
    else:
        matrix.append({
            "category": "Rủi ro Tính Xác thực BCTC",
            "risk_detail": "Các chỉ số Beneish M-Score và Dechow F-Score nằm trong vùng an toàn, không phát hiện dấu hiệu sai lệch số liệu kế toán trọng yếu.",
            "mitigation": "Tiếp tục thu thập BCTC kiểm toán định kỳ hàng năm và tờ khai thuế quý."
        })
        
    # 3. Rủi ro Kiệt quệ & Khả năng Thanh toán
    z_score = ews_res.get("Altman_Z_Prime", {}).get("score")
    if z_score is not None and z_score <= 1.23:
        matrix.append({
            "category": "Rủi ro Khả năng Trả nợ & Phá sản",
            "risk_detail": f"Chỉ số Altman Z''-Score = {z_score:.2f} rơi vào Vùng Nguy hiểm (Distress Zone). Khả năng kiệt quệ tài chính và mất khả năng trả nợ trong vòng 1-2 năm tới ở mức báo động.",
            "mitigation": "Tăng tỷ lệ Tài sản bảo đảm lên tối thiểu 90 - 100% bằng Bất động sản thanh khoản cao; rút ngắn thời hạn tối đa mỗi KUNN xuống dưới 4 tháng; thiết lập ngưỡng cảnh báo sớm thu nợ trước hạn."
        })
    elif z_score is not None and z_score <= 2.90:
        matrix.append({
            "category": "Rủi ro Khả năng Trả nợ & Phá sản",
            "risk_detail": f"Chỉ số Altman Z''-Score = {z_score:.2f} nằm trong Vùng Xám (Grey Zone). Cần giám sát chặt chẽ áp lực dòng tiền trả nợ ngân hàng.",
            "mitigation": "Yêu cầu Khách hàng mở tài khoản chuyên thu tại Ngân hàng, cam kết duy trì số dư tiền gửi bình quân (CASA) tối thiểu bù đắp lãi vay hàng tháng."
        })
        
    # 4. Rủi ro Tài sản bảo đảm
    if collateral_res:
        sec_ratio = collateral_res.get("secured_ratio", 1.0)
        unsec_amt = collateral_res.get("unsecured_facility_amount", 0.0)
        if unsec_amt > 0:
            matrix.append({
                "category": "Rủi ro Tài sản Bảo đảm",
                "risk_detail": f"Phương án đề xuất có phần cấp tín dụng không có TSBĐ (tín chấp) trị giá {unsec_amt/1e9:,.2f} tỷ đồng (tương ứng {collateral_res.get('unsecured_ratio', 0.0):.1%} tổng hạn mức). Tiềm ẩn nguy cơ thất thoát vốn nếu khách hàng mất khả năng thanh toán.",
                "mitigation": "Áp dụng điều kiện tiến độ bổ sung TSBĐ (thế chấp bổ sung BĐS trong vòng 20 - 30 ngày); khống chế thời gian duy trì phần dư nợ tín chấp tối đa không quá 60 ngày kể từ ngày giải ngân đầu tiên."
            })
            
    # 5. Rủi ro Chuỗi cung ứng & Tập trung Khách hàng
    matrix.append({
        "category": "Rủi ro Chuỗi Cung ứng & Đối tác",
        "risk_detail": "Doanh nghiệp có thể bị phụ thuộc vào số lượng ít nhà phân phối hoặc nhà cung cấp chiến lược (rủi ro đứt gãy nguồn hàng hoặc bị cắt chiết khấu).",
        "mitigation": "Quy định trong hợp đồng tín dụng: Ngân hàng chỉ tài trợ vốn mua hàng từ các nhà cung cấp có hợp đồng đại lý/phân phối chính thức; định kỳ rà soát dư nợ của các nhà cung cấp chính qua CIC."
    })
    
    return matrix


def determine_approval_authority(
    total_facility_amount: float,
    unsecured_facility_amount: float,
    internal_credit_grade: str = "BBB",
    customer_segment: str = "SME"
) -> Dict[str, str]:
    """
    Xác định Cấp Thẩm quyền Phê duyệt Tín dụng theo Hạn mức Ủy quyền của Ngân hàng
    (Ví dụ: Cấp Giám đốc Chi nhánh, C1, C2, C3 hoặc Hội đồng Tín dụng Trụ sở chính).
    """
    amt_bil = total_facility_amount / 1e9
    unsec_bil = unsecured_facility_amount / 1e9
    
    if unsec_bil > 20.0 or amt_bil > 100.0:
        authority = "Hội đồng Tín dụng Trụ sở chính (HO Credit Committee)"
        rationale = f"Tổng hạn mức ({amt_bil:.1f} tỷ) > 100 tỷ hoặc dư nợ tín chấp ({unsec_bil:.1f} tỷ) > 20 tỷ đồng, vượt thẩm quyền khối."
    elif unsec_bil > 10.0 or amt_bil > 50.0:
        authority = "Giám đốc Phê duyệt Tín dụng Cấp 3 (C3) - Khối Thẩm định"
        rationale = f"Tổng hạn mức ({amt_bil:.1f} tỷ) từ 50-100 tỷ hoặc phần tín chấp ({unsec_bil:.1f} tỷ) > 10 tỷ đồng."
    elif unsec_bil > 0.0 or amt_bil > 20.0:
        authority = "Giám đốc Phê duyệt Tín dụng Cấp 2 (C2) - Khối Thẩm định"
        rationale = f"Tổng hạn mức ({amt_bil:.1f} tỷ) từ 20-50 tỷ và có nội dung cấp tín chấp/ngoại lệ chính sách TSBĐ."
    elif amt_bil > 10.0:
        authority = "Giám đốc Phê duyệt Tín dụng Cấp 1 (C1) - Khối Thẩm định"
        rationale = f"Tổng hạn mức ({amt_bil:.1f} tỷ) từ 10-20 tỷ đồng, đảm bảo 100% TSBĐ độc lập."
    else:
        authority = "Giám đốc Chi nhánh (Theo ủy quyền tín dụng nhóm SME)"
        rationale = f"Hạn mức nhỏ ({amt_bil:.1f} tỷ) <= 10 tỷ đồng, tuân thủ hoàn toàn quy chuẩn sản phẩm."
        
    return {
        "approval_authority": authority,
        "rationale": rationale,
        "internal_grade": internal_credit_grade,
        "customer_segment": customer_segment
    }
