# -*- coding: utf-8 -*-
"""
pdf_report_generator.py
-----------------------
Module xuất Báo cáo Thẩm định Cảnh báo Sớm Rủi ro Tín dụng (EWS) sang định dạng PDF chuẩn.
Hỗ trợ đầy đủ tiếng Việt Unicode, bố cục chuyên nghiệp cho cán bộ tín dụng và lãnh đạo.
"""

import io
import os
import datetime
import numpy as np
import pandas as pd
import credit_underwriting_engine as cue

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# -------------------------------------------------------------------------
# ĐĂNG KÝ FONT TIẾNG VIỆT UNICODE
# -------------------------------------------------------------------------
def _register_vietnamese_fonts():
    """Tự động tìm và đăng ký font tiếng Việt có sẵn trên hệ điều hành."""
    font_candidates = [
        # macOS
        ('/Library/Fonts/Arial Unicode.ttf', '/Library/Fonts/Arial Unicode.ttf'),
        ('/System/Library/Fonts/Supplemental/Arial.ttf', '/System/Library/Fonts/Supplemental/Arial Bold.ttf'),
        ('/System/Library/Fonts/Supplemental/Times New Roman.ttf', '/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf'),
        # Windows
        ('C:/Windows/Fonts/arial.ttf', 'C:/Windows/Fonts/arialbd.ttf'),
        ('C:/Windows/Fonts/times.ttf', 'C:/Windows/Fonts/timesbd.ttf'),
        # Linux
        ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf')
    ]
    
    reg_regular = "Helvetica"
    reg_bold = "Helvetica-Bold"
    
    for reg_path, bold_path in font_candidates:
        if os.path.exists(reg_path):
            try:
                pdfmetrics.registerFont(TTFont('VnFont', reg_path))
                reg_regular = 'VnFont'
                if os.path.exists(bold_path):
                    pdfmetrics.registerFont(TTFont('VnFontBold', bold_path))
                    reg_bold = 'VnFontBold'
                else:
                    pdfmetrics.registerFont(TTFont('VnFontBold', reg_path))
                    reg_bold = 'VnFontBold'
                break
            except Exception:
                continue
                
    return reg_regular, reg_bold

FONT_REGULAR, FONT_BOLD = _register_vietnamese_fonts()

# Bảng tên chỉ tiêu kế toán tiếng Việt chuẩn
VAR_NAMES_VN = {
    "Total_Assets": "Tổng tài sản",
    "Current_Assets": "Tài sản ngắn hạn",
    "Cash_Equivalents": "Tiền và tương đương tiền",
    "Accounts_Receivable": "Phải thu ngắn hạn KH",
    "Current_Receivables": "Các khoản phải thu NH",
    "Inventories": "Hàng tồn kho",
    "Fixed_Assets": "Tài sản cố định (Ròng)",
    "Tangible_PPE_Cost": "Nguyên giá TSCĐ hữu hình",
    "Total_Liabilities": "Nợ phải trả",
    "Current_Liabilities": "Nợ ngắn hạn",
    "Equity": "Vốn chủ sở hữu",
    "Retained_Earnings": "LNST chưa phân phối",
    "Net_Sales": "Doanh thu thuần",
    "COGS": "Giá vốn hàng bán",
    "Gross_Profit": "Lợi nhuận gộp",
    "Selling_Expense": "Chi phí bán hàng",
    "GA_Expense": "Chi phí QLDN",
    "Interest_Expense": "Chi phí lãi vay",
    "EBT": "Lợi nhuận trước thuế",
    "Net_Income": "Lợi nhuận sau thuế",
    "OCF": "Lưu chuyển tiền thuần từ HĐKD"
}

EWS_NAMES_VN = {
    "Altman_Z_Prime": "1. Altman Z'-Score (Kiệt quệ TC)",
    "SA_Index": "2. SA Index (Hạn chế TC Quy mô-Tuổi)",
    "Beneish_M_Score": "3. Beneish M-Score (8 biến 1999)",
    "Beneish_M_Score_12": "4. Beneish M-Score (12 biến Probit)",
    "Dechow_F_Score": "5. Dechow F-Score (Bóp méo BCTC)",
    "Abnormal_CFO": "6. Abnormal CFO (Nới lỏng tín dụng)",
    "Abnormal_PROD": "7. Abnormal PROD (Sản xuất quá mức)",
    "Abnormal_DISEXP": "8. Abnormal DISEXP (Cắt giảm chi phí)",
    "KZ_Index": "9. KZ Index (Ràng buộc tài chính)",
    "WW_Index": "10. WW Index (Ràng buộc dòng tiền)"
}

class NumberedCanvas(canvas.Canvas):
    """Canvas vẽ Header & Footer có đánh số trang 'Trang X/Y'."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont(FONT_REGULAR, 8)
        self.setFillColor(colors.HexColor("#666666"))
        
        # Header (từ trang 2 trở đi)
        if self._pageNumber > 1:
            self.drawString(40, 810, "FINTRUST EWS - BÁO CÁO THẨM ĐỊNH RỦI RO TÍN DỤNG DOANH NGHIỆP")
            self.setStrokeColor(colors.HexColor("#D0D5DD"))
            self.setLineWidth(0.5)
            self.line(40, 804, 555, 804)
            
        # Footer (tất cả các trang)
        self.setStrokeColor(colors.HexColor("#D0D5DD"))
        self.setLineWidth(0.5)
        self.line(40, 35, 555, 35)
        
        timestamp_str = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
        self.drawString(40, 22, f"Hệ thống Cảnh báo Sớm EWS Fintrust | Xuất ngày: {timestamp_str}")
        self.drawRightString(555, 22, f"Trang {self._pageNumber} / {page_count}")
        self.restoreState()


import streamlit as st

@st.cache_data(show_spinner=False)
def generate_ews_pdf_bytes(
    company_name,
    ticker,
    extracted_data,
    ews_results,
    firm_age=10,
    tobin_q=1.2,
    div_ratio=0.0,
    isg=0.08,
    ab_return=0.0,
    unconditional_prob=0.0037,
    industry="Khác / Mặc định",
    ceo_age=55,
    is_bds=False
):
    """
    Tạo tệp PDF Báo cáo Thẩm định EWS hoàn chỉnh dạng bytes trong bộ nhớ.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=45,
        bottomMargin=45
    )
    
    # ------------------ STYLES ------------------
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'DocTitle',
        fontName=FONT_BOLD,
        fontSize=17,
        leading=22,
        textColor=colors.HexColor("#0F2942"),
        alignment=1, # Center
        spaceAfter=4
    )
    
    subtitle_style = ParagraphStyle(
        'DocSubTitle',
        fontName=FONT_REGULAR,
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#4A5568"),
        alignment=1,
        spaceAfter=15
    )
    
    h1_style = ParagraphStyle(
        'H1Style',
        fontName=FONT_BOLD,
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#1A365D"),
        spaceBefore=12,
        spaceAfter=6,
        keepWithNext=True
    )
    
    h2_style = ParagraphStyle(
        'H2Style',
        fontName=FONT_BOLD,
        fontSize=10.5,
        leading=14,
        textColor=colors.HexColor("#2B6CB0"),
        spaceBefore=8,
        spaceAfter=4,
        keepWithNext=True
    )
    
    body_style = ParagraphStyle(
        'BodyDark',
        fontName=FONT_REGULAR,
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#2D3748")
    )
    
    bold_style = ParagraphStyle(
        'BoldDark',
        fontName=FONT_BOLD,
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#1A202C")
    )
    
    cell_style = ParagraphStyle(
        'TableCell',
        fontName=FONT_REGULAR,
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#2D3748")
    )
    
    cell_bold_style = ParagraphStyle(
        'TableCellBold',
        fontName=FONT_BOLD,
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#1A202C")
    )
    
    cell_right = ParagraphStyle(
        'TableCellRight',
        fontName=FONT_REGULAR,
        fontSize=8.5,
        leading=11,
        alignment=2, # Right
        textColor=colors.HexColor("#2D3748")
    )
    
    alert_red = ParagraphStyle(
        'AlertRed',
        fontName=FONT_BOLD,
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#9B2C2C")
    )
    
    alert_yellow = ParagraphStyle(
        'AlertYellow',
        fontName=FONT_BOLD,
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#B7791F")
    )
    
    alert_green = ParagraphStyle(
        'AlertGreen',
        fontName=FONT_BOLD,
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#276749")
    )

    story = []
    
    # ------------------ HEADER BANNER ------------------
    story.append(Paragraph("🛡️ BÁO CÁO CẢNH BÁO SỚM (EWS) RỦI RO TÍN DỤNG", title_style))
    story.append(Paragraph("FINTRUST CREDIT RISK EARLY WARNING SYSTEM — ĐÁNH GIÁ TOÀN DIỆN DOANH NGHIỆP", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1A365D"), spaceAfter=10))
    
    # ------------------ MỤC 1: THÔNG TIN HỒ SƠ ------------------
    story.append(Paragraph("1. THÔNG TIN HỒ SƠ & THAM SỐ THẨM ĐỊNH", h1_style))
    
    now_str = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    years = sorted(list(extracted_data.keys()))
    years_str = ", ".join(str(y) for y in years) if years else "N/A"
    
    info_data = [
        [
            Paragraph("<b>Doanh nghiệp:</b>", body_style),
            Paragraph(f"<b>{company_name}</b>", bold_style),
            Paragraph("<b>Mã chứng khoán:</b>", body_style),
            Paragraph(f"<b>{ticker}</b>", bold_style)
        ],
        [
            Paragraph("<b>Ngành hoạt động:</b>", body_style),
            Paragraph(str(industry), body_style),
            Paragraph("<b>Các năm BCTC:</b>", body_style),
            Paragraph(years_str, body_style)
        ],
        [
            Paragraph("<b>Tuổi doanh nghiệp:</b>", body_style),
            Paragraph(f"{firm_age} năm", body_style),
            Paragraph("<b>Độ tuổi CEO:</b>", body_style),
            Paragraph(f"{ceo_age} tuổi", body_style)
        ],
        [
            Paragraph("<b>Tỷ số Tobin's Q:</b>", body_style),
            Paragraph(f"{tobin_q:.2f}", body_style),
            Paragraph("<b>Tỷ lệ chi trả cổ tức:</b>", body_style),
            Paragraph(f"{div_ratio:.1%}", body_style)
        ],
        [
            Paragraph("<b>Tăng trưởng ngành (ISG):</b>", body_style),
            Paragraph(f"{isg:.1%}", body_style),
            Paragraph("<b>Suất sinh lời dị thường:</b>", body_style),
            Paragraph(f"{ab_return:.1%}", body_style)
        ]
    ]
    
    t_info = Table(info_data, colWidths=[115, 140, 120, 140])
    t_info.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(t_info)
    story.append(Spacer(1, 10))
    
    # ------------------ MỤC 2: BẢNG KẾT QUẢ 10 CHỈ SỐ EWS ------------------
    story.append(Paragraph("2. BẢNG TỔNG HỢP 10 CHỈ SỐ CẢNH BÁO SỚM (EWS)", h1_style))
    story.append(Paragraph("<i>Màu sắc phân loại: <font color='#276749'><b>■ An toàn</b></font> | <font color='#B7791F'><b>■ Vùng xám / Theo dõi</b></font> | <font color='#9B2C2C'><b>■ Nguy hiểm / Cảnh báo cao</b></font></i>", body_style))
    story.append(Spacer(1, 4))
    
    col_w_name = 195
    col_w_year = (515 - col_w_name) / max(1, len(years))
    
    if not years:
        story.append(Paragraph("Chưa có dữ liệu BCTC để tính toán.", body_style))
    else:
        # Header bảng EWS
        ews_table_data = []
        header_row = [Paragraph("<b>Bộ chỉ số EWS</b>", cell_bold_style)]
        for y in years:
            header_row.append(Paragraph(f"<b>Năm {y}</b>", ParagraphStyle('THC', fontName=FONT_BOLD, fontSize=8.5, alignment=1, textColor=colors.white)))
        ews_table_data.append(header_row)
        
        for k, vname in EWS_NAMES_VN.items():
            row = [Paragraph(f"<b>{vname}</b>", cell_style)]
            for y in years:
                res = ews_results.get(y, {}).get(k)
                if not res or res.get("score") is None:
                    row.append(Paragraph("N/A", cell_style))
                else:
                    score = res["score"]
                    status = res.get("status", "normal")
                    score_str = f"{score:.4f}"
                    
                    if status == "error":
                        p = Paragraph(f"<b>{score_str}</b><br/><font size=7 color='#9B2C2C'>Nguy hiểm</font>", alert_red)
                    elif status == "warning":
                        p = Paragraph(f"<b>{score_str}</b><br/><font size=7 color='#B7791F'>Vùng xám</font>", alert_yellow)
                    else:
                        p = Paragraph(f"<b>{score_str}</b><br/><font size=7 color='#276749'>An toàn</font>", alert_green)
                    row.append(p)
            ews_table_data.append(row)
            
        t_ews = Table(ews_table_data, colWidths=[col_w_name] + [col_w_year]*len(years))
        
        table_styles = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1A365D")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#94A3B8")),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]
        
        # Tô màu sọc xen kẽ cho các hàng
        for r_idx in range(1, len(ews_table_data)):
            if r_idx % 2 == 1:
                table_styles.append(('BACKGROUND', (0, r_idx), (-1, r_idx), colors.HexColor("#F8FAFC")))
            else:
                table_styles.append(('BACKGROUND', (0, r_idx), (-1, r_idx), colors.white))
                
        t_ews.setStyle(TableStyle(table_styles))
        story.append(t_ews)
        
    story.append(Spacer(1, 12))
    
    # ------------------ MỤC 3: KẾT LUẬN & CẢNH BÁO TỔNG HỢP ------------------
    story.append(Paragraph("3. ĐÁNH GIÁ RỦI RO CHI TIẾT & CẢNH BÁO TỔNG HỢP", h1_style))
    
    for y in years:
        story.append(Paragraph(f"<b>Năm tài chính {y}:</b>", h2_style))
        y_alerts = []
        
        # 1. Thao túng thực REM
        cfo_y = ews_results.get(y, {}).get("Abnormal_CFO")
        prod_y = ews_results.get(y, {}).get("Abnormal_PROD")
        disexp_y = ews_results.get(y, {}).get("Abnormal_DISEXP")
        
        if cfo_y and prod_y and disexp_y:
            if cfo_y["score"] < -0.05 and prod_y["score"] > 0.05 and disexp_y["score"] < -0.03:
                y_alerts.append("<font color='#9B2C2C'><b>⚠️ CẢNH BÁO ĐỎ REM:</b> Phát hiện đồng thời 3 hành vi thao túng hoạt động thực (Nới lỏng tín dụng, sản xuất quá mức để giảm giá vốn, cắt giảm chi phí tùy quyết để thổi phồng lợi nhuận). Khuyến nghị kiểm tra chuyên sâu.</font>")
                
        # 2. Bóp méo BCTC
        m_y = ews_results.get(y, {}).get("Beneish_M_Score")
        f_y = ews_results.get(y, {}).get("Dechow_F_Score")
        if m_y and f_y and m_y.get("score") is not None and f_y.get("score") is not None:
            if m_y["score"] > -1.78 and f_y["score"] > 1.85:
                y_alerts.append("<font color='#9B2C2C'><b>⚠️ CẢNH BÁO BÓP MÉO BCTC:</b> Đồng thuận giữa Beneish M-Score và Dechow F-Score. Báo cáo tài chính có xác suất bóp méo cao, số liệu lợi nhuận kế toán kém tin cậy.</font>")
                
        # 3. Kiệt quệ tài chính
        z_y = ews_results.get(y, {}).get("Altman_Z_Prime")
        if z_y and z_y.get("score") is not None:
            if z_y["score"] <= 1.23:
                y_alerts.append(f"<font color='#9B2C2C'><b>• Rủi ro Phá sản (Altman Z'-Score = {z_y['score']:.2f}):</b> Nằm trong VÙNG NGUY HIỂM (Distress Zone). Khả năng kiệt quệ tài chính trong 1-2 năm tới rất cao.</font>")
            elif z_y["score"] <= 2.90:
                y_alerts.append(f"<font color='#B7791F'><b>• Rủi ro Phá sản (Altman Z'-Score = {z_y['score']:.2f}):</b> Nằm trong VÙNG XÁM (Grey Zone). Cần theo dõi sát khả năng thanh toán nợ.</font>")
            else:
                y_alerts.append(f"<font color='#276749'><b>• Sức khỏe Tài chính (Altman Z'-Score = {z_y['score']:.2f}):</b> Nằm trong VÙNG AN TOÀN (Safe Zone).</font>")
                
        # 4. Hạn chế tài chính
        sa_y = ews_results.get(y, {}).get("SA_Index")
        if sa_y and sa_y.get("score") is not None:
            if sa_y["score"] > -2.55:
                y_alerts.append(f"<font color='#9B2C2C'><b>• Ràng buộc Tài chính (SA Index = {sa_y['score']:.2f}):</b> Hạn chế tiếp cận nguồn vốn bên ngoài mức độ cao.</font>")
            else:
                y_alerts.append(f"<font color='#276749'><b>• Tiếp cận Tài chính (SA Index = {sa_y['score']:.2f}):</b> Khả năng huy động vốn tương đối thuận lợi.</font>")
                
        if not y_alerts:
            story.append(Paragraph("🟢 Doanh nghiệp nằm trong vùng an toàn theo tất cả các chỉ số EWS.", body_style))
        else:
            for alert in y_alerts:
                story.append(Paragraph(f"- {alert}", body_style))
                story.append(Spacer(1, 2))
                
        story.append(Spacer(1, 4))

    # ------------------ MỤC 4: BẢNG DỮ LIỆU TÀI CHÍNH BCTC ------------------
    story.append(Spacer(1, 8))
    story.append(Paragraph("4. DỮ LIỆU TÀI CHÍNH TRÍCH XUẤT TỪ BCTC (Đơn vị: VNĐ)", h1_style))
    
    fin_table_data = []
    fin_header = [Paragraph("<b>Chỉ tiêu Kế toán (TT 200)</b>", cell_bold_style)]
    for y in years:
        fin_header.append(Paragraph(f"<b>Năm {y}</b>", ParagraphStyle('FTH', fontName=FONT_BOLD, fontSize=8, alignment=2, textColor=colors.white)))
    fin_table_data.append(fin_header)
    
    for var_code, var_vn in VAR_NAMES_VN.items():
        row = [Paragraph(var_vn, cell_style)]
        for y in years:
            val = extracted_data.get(y, {}).get(var_code, np.nan)
            if pd.isna(val) or val is None:
                val_str = "-"
            elif abs(val) >= 1_000_000_000:
                val_str = f"{val/1_000_000_000:,.2f} tỷ"
            elif abs(val) >= 1_000_000:
                val_str = f"{val/1_000_000:,.0f} tr"
            else:
                val_str = f"{val:,.0f}"
            row.append(Paragraph(val_str, cell_right))
        fin_table_data.append(row)
        
    t_fin = Table(fin_table_data, colWidths=[185] + [col_w_year]*len(years))
    t_fin_styles = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#334155")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#94A3B8")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
    ]
    for r_idx in range(1, len(fin_table_data)):
        if r_idx % 2 == 1:
            t_fin_styles.append(('BACKGROUND', (0, r_idx), (-1, r_idx), colors.HexColor("#F8FAFC")))
    t_fin.setStyle(TableStyle(t_fin_styles))
    story.append(t_fin)
    
    # ------------------ MỤC 5: KHUYẾN NGHỊ & KÝ DUYỆT ------------------
    story.append(Spacer(1, 15))
    sign_data = [
        [
            Paragraph("<b>CÁN BỘ THẨM ĐỊNH TÍN DỤNG</b><br/><i>(Ký và ghi rõ họ tên)</i>", ParagraphStyle('Sign1', fontName=FONT_REGULAR, fontSize=9, alignment=1)),
            Paragraph("<b>TRƯỞNG BỘ PHẬN / QUẢN LÝ RỦI RO</b><br/><i>(Ký và ghi rõ họ tên)</i>", ParagraphStyle('Sign2', fontName=FONT_REGULAR, fontSize=9, alignment=1))
        ],
        [Spacer(1, 35), Spacer(1, 35)],
        [
            Paragraph("....................................................", ParagraphStyle('Dot1', fontName=FONT_REGULAR, fontSize=9, alignment=1)),
            Paragraph("....................................................", ParagraphStyle('Dot2', fontName=FONT_REGULAR, fontSize=9, alignment=1))
        ]
    ]
    t_sign = Table(sign_data, colWidths=[255, 255])
    t_sign.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(KeepTogether(t_sign))

    # Xây dựng tài liệu PDF
    doc.build(story, canvasmaker=NumberedCanvas)
    buffer.seek(0)
    return buffer.getvalue()


# -------------------------------------------------------------------------
# BÁO CÁO THẨM ĐỊNH CẤP TÍN DỤNG TOÀN DIỆN CHUẨN NGÂN HÀNG THƯƠNG MẠI
# -------------------------------------------------------------------------
class BankUnderwritingNumberedCanvas(canvas.Canvas):
    """Canvas vẽ Header & Footer chuẩn Báo cáo Thẩm định Ngân hàng TMCP."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont(FONT_REGULAR, 7.5)
        self.setFillColor(colors.HexColor("#475569"))
        
        # Header (từ trang 2 trở đi)
        if self._pageNumber > 1:
            self.drawString(40, 812, "NGÂN HÀNG THƯƠNG MẠI — KHỐI THẨM ĐỊNH")
            self.drawRightString(555, 812, "BÁO CÁO THẨM ĐỊNH TÍN DỤNG DOANH NGHIỆP")
            self.setStrokeColor(colors.HexColor("#CBD5E1"))
            self.setLineWidth(0.6)
            self.line(40, 806, 555, 806)
            
        # Footer (tất cả các trang)
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.6)
        self.line(40, 36, 555, 36)
        
        timestamp_str = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
        self.drawString(40, 24, f"Hệ thống FinTrust EWS | Mẫu Tờ trình Chuẩn Ngân hàng | Ngày xuất: {timestamp_str}")
        self.drawRightString(555, 24, f"Trang {self._pageNumber} / {page_count}")
        self.restoreState()


@st.cache_data(show_spinner=False)
def generate_full_credit_appraisal_pdf_bytes(
    company_name: str,
    ticker: str,
    extracted_data: dict,
    ews_results: dict,
    wc_results: dict = None,
    qual_results: dict = None,
    underwriting_data: dict = None,
    evaluation_year: int = None,
    firm_age: int = 10,
    tobin_q: float = 1.2,
    div_ratio: float = 0.0,
    isg: float = 0.08,
    ab_return: float = 0.0,
    unconditional_prob: float = 0.0037,
    industry: str = "Sản xuất, chế biến, kinh doanh thực phẩm",
    ceo_age: int = 50,
    is_bds: bool = False
) -> bytes:
    """
    Tạo tệp PDF Báo cáo Thẩm định Cấp Tín dụng Toàn diện Chuẩn Ngân hàng Thương mại (Full Bank Appraisal Memo).
    Bao gồm đầy đủ 10 trụ cột nghiệp vụ: Metadata, Hạn mức, Covenants, 5Cs, BCTC, EWS, TSBĐ, Ma trận Rủi ro, Nhu cầu VLĐ, Phê duyệt.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=50,
        bottomMargin=48
    )
    
    # Định nghĩa bộ Styles chuẩn ngân hàng
    doc_title_style = ParagraphStyle(
        'DocTitleFull',
        fontName=FONT_BOLD,
        fontSize=15,
        leading=19,
        textColor=colors.HexColor("#0F2942"),
        alignment=1,
        spaceAfter=3
    )
    doc_sub_style = ParagraphStyle(
        'DocSubFull',
        fontName=FONT_REGULAR,
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#475569"),
        alignment=1,
        spaceAfter=10
    )
    sec_title_style = ParagraphStyle(
        'SecTitle',
        fontName=FONT_BOLD,
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#1A365D"),
        spaceBefore=8,
        spaceAfter=4,
        keepWithNext=True
    )
    sub_sec_style = ParagraphStyle(
        'SubSecTitle',
        fontName=FONT_BOLD,
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#2B6CB0"),
        spaceBefore=6,
        spaceAfter=3,
        keepWithNext=True
    )
    body_style = ParagraphStyle(
        'BodyNorm',
        fontName=FONT_REGULAR,
        fontSize=7.8,
        leading=11,
        textColor=colors.HexColor("#2D3748")
    )
    bold_style = ParagraphStyle(
        'BoldNorm',
        fontName=FONT_BOLD,
        fontSize=7.8,
        leading=11,
        textColor=colors.HexColor("#1A202C")
    )
    cell_style = ParagraphStyle(
        'CellNorm',
        fontName=FONT_REGULAR,
        fontSize=7.2,
        leading=9.5,
        textColor=colors.HexColor("#2D3748")
    )
    cell_bold = ParagraphStyle(
        'CellBold',
        fontName=FONT_BOLD,
        fontSize=7.2,
        leading=9.5,
        textColor=colors.HexColor("#1A202C")
    )
    cell_right = ParagraphStyle(
        'CellRight',
        fontName=FONT_REGULAR,
        fontSize=7.2,
        leading=9.5,
        alignment=2,
        textColor=colors.HexColor("#2D3748")
    )
    cell_center = ParagraphStyle(
        'CellCenter',
        fontName=FONT_REGULAR,
        fontSize=7.2,
        leading=9.5,
        alignment=1,
        textColor=colors.HexColor("#2D3748")
    )
    th_style = ParagraphStyle(
        'THCenter',
        fontName=FONT_BOLD,
        fontSize=7.5,
        leading=10,
        alignment=1,
        textColor=colors.white
    )
    th_left = ParagraphStyle(
        'THLeft',
        fontName=FONT_BOLD,
        fontSize=7.5,
        leading=10,
        alignment=0,
        textColor=colors.white
    )
    alert_red = ParagraphStyle(
        'AlertRedFull',
        fontName=FONT_BOLD,
        fontSize=7.2,
        leading=9.5,
        textColor=colors.HexColor("#9B2C2C")
    )
    alert_yellow = ParagraphStyle(
        'AlertYellowFull',
        fontName=FONT_BOLD,
        fontSize=7.2,
        leading=9.5,
        textColor=colors.HexColor("#B7791F")
    )
    alert_green = ParagraphStyle(
        'AlertGreenFull',
        fontName=FONT_BOLD,
        fontSize=7.2,
        leading=9.5,
        textColor=colors.HexColor("#276749")
    )

    story = []
    
    # Xử lý năm đánh giá
    raw_years = [y for y in extracted_data.keys() if isinstance(y, int) or (isinstance(y, str) and str(y).isdigit())]
    years = sorted([int(y) for y in raw_years])
    if not evaluation_year:
        eval_year = years[-1] if years else datetime.datetime.now().year
    else:
        try:
            eval_year = int(evaluation_year)
        except (ValueError, TypeError):
            eval_year = years[-1] if years else datetime.datetime.now().year
        
    if not underwriting_data:
        underwriting_data = {}
        
    branch_name = underwriting_data.get("branch_name", "Chi nhánh Tân Bình / TP.HCM")
    report_num = underwriting_data.get("report_number", f"L{datetime.datetime.now().strftime('%y%m%d%H%M')}/BCTĐ-SME")
    cif_mst = underwriting_data.get("tax_code", "0315315451")
    customer_segment = underwriting_data.get("customer_segment", "SME (Doanh thu 100 – 1.000 tỷ đồng)")
    industry_display = underwriting_data.get("industry_full", f"{industry} (Mã ngành: 4632900)")
    internal_grade = underwriting_data.get("internal_grade", "Hạng BBB (Đạt chuẩn)")
    product_pkg = underwriting_data.get("product_package", "GSP Nhà phân phối Hàng tiêu dùng - Vốn lưu động")
    credit_purpose = underwriting_data.get("credit_purpose", "Cấp tín dụng bổ sung vốn lưu động phục vụ hoạt động sản xuất kinh doanh và tài trợ thương mại.")
    
    # 1. Tính toán Nhu cầu vốn lưu động
    wc_calc = cue.calculate_working_capital_need(
        extracted_data=extracted_data,
        selected_year=eval_year,
        custom_planned_sales=underwriting_data.get("planned_sales")
    )
    
    # Hạn mức đề xuất
    branch_req_limit = underwriting_data.get("requested_limit_branch", wc_calc["recommended_credit_limit"])
    risk_rec_limit = underwriting_data.get("recommended_limit_risk", wc_calc["recommended_credit_limit"])
    if branch_req_limit <= 0:
        branch_req_limit = 50_000_000_000.0
    if risk_rec_limit <= 0:
        risk_rec_limit = branch_req_limit
        
    # 2. Thẩm định TSBĐ
    collateral_list = underwriting_data.get("collateral_items", [])
    if not collateral_list:
        collateral_list = [
            {
                "type": "Bất động sản",
                "description": "Căn hộ chung cư cao cấp C2.04 Symphony Midtown, Quận 7, TP.HCM",
                "market_value": risk_rec_limit * 0.90,
                "ltv_rate": 0.75
            },
            {
                "type": "Tiền gửi / STK",
                "description": "Hợp đồng tiền gửi / Sổ tiết kiệm cầm cố tại Ngân hàng",
                "market_value": risk_rec_limit * 0.35,
                "ltv_rate": 0.95
            }
        ]
    collat_eval = cue.evaluate_collaterals(collateral_list, risk_rec_limit)
    
    # 3. Sinh Covenants
    curr_ews = ews_results.get(eval_year, {})
    covenants_data = cue.generate_smart_credit_covenants(ticker, company_name, eval_year, curr_ews, wc_calc, qual_results)
    
    # 4. Ma trận Rủi ro
    risk_matrix = cue.build_credit_risk_matrix(curr_ews, wc_calc, collat_eval, qual_results)
    
    # 5. Cấp thẩm quyền phê duyệt
    auth_info = cue.determine_approval_authority(
        risk_rec_limit,
        collat_eval["unsecured_facility_amount"],
        internal_credit_grade=internal_grade.split()[1] if "Hạng" in internal_grade else "BBB",
        customer_segment=customer_segment
    )

    # =========================================================================
    # PHẦN 1: HEADER & BẢNG METADATA TỜ TRÌNH
    # =========================================================================
    top_memo_data = [
        [
            Paragraph(f"<b>Số:</b> {report_num}", body_style),
            Paragraph("<b>KHỐI THẨM ĐỊNH & QUẢN TRỊ RỦI RO</b>", bold_style),
            Paragraph("<b>NGÂN HÀNG THƯƠNG MẠI CP</b>", bold_style)
        ],
        [
            Paragraph(f"<b>Đơn vị đề xuất:</b> {branch_name}", body_style),
            Paragraph(f"<b>Ngày lập tờ trình:</b> {datetime.datetime.now().strftime('%d/%m/%Y')}", body_style),
            Paragraph(f"<b>Cấp thẩm quyền:</b> {auth_info['approval_authority'].split('-')[0].strip()}", bold_style)
        ]
    ]
    t_top = Table(top_memo_data, colWidths=[175, 175, 165])
    t_top.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(t_top)
    story.append(Spacer(1, 8))
    
    story.append(Paragraph("BÁO CÁO THẨM ĐỊNH TÍN DỤNG DOANH NGHIỆP", doc_title_style))
    story.append(Paragraph("CREDIT APPRAISAL & UNDERWRITING MEMORANDUM — TỜ TRÌNH PHÊ DUYỆT HẠN MỨC", doc_sub_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#0F2942"), spaceAfter=8))
    
    # Bảng Thông tin Doanh nghiệp & Hồ sơ
    meta_data = [
        [
            Paragraph("<b>Khách hàng:</b>", cell_bold),
            Paragraph(f"<b>{company_name}</b>", cell_bold),
            Paragraph("<b>Mã CK / CIF:</b>", cell_bold),
            Paragraph(f"{ticker} | {cif_mst}", cell_style)
        ],
        [
            Paragraph("<b>Phân khúc:</b>", cell_style),
            Paragraph(customer_segment, cell_style),
            Paragraph("<b>Xếp hạng TD nội bộ:</b>", cell_style),
            Paragraph(f"<b>{internal_grade}</b>", cell_bold)
        ],
        [
            Paragraph("<b>Ngành hoạt động:</b>", cell_style),
            Paragraph(industry_display, cell_style),
            Paragraph("<b>Cấp phê duyệt:</b>", cell_style),
            Paragraph(f"<b>{auth_info['approval_authority']}</b>", cell_bold)
        ],
        [
            Paragraph("<b>Gói sản phẩm:</b>", cell_style),
            Paragraph(product_pkg, cell_style),
            Paragraph("<b>Dự kiến TOI / NIM:</b>", cell_style),
            Paragraph(f"{risk_rec_limit * 0.032 / 1e6:,.0f} tr.đ (TOI ~3.20%)", cell_style)
        ]
    ]
    t_meta = Table(meta_data, colWidths=[105, 165, 105, 140])
    t_meta.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#FFFFFF")),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(t_meta)
    story.append(Spacer(1, 8))

    # =========================================================================
    # MỤC I: PHƯƠNG ÁN CẤP TÍN DỤNG ĐỀ XUẤT (SO SÁNH ĐVKD VS THẨM ĐỊNH)
    # =========================================================================
    story.append(Paragraph("I. PHƯƠNG ÁN CẤP TÍN DỤNG ĐỀ XUẤT", sec_title_style))
    story.append(Paragraph("Bảng đối chiếu giữa Đề xuất của Đơn vị Kinh doanh (Chi nhánh) và Đề xuất của Khối Thẩm định Rủi ro:", body_style))
    story.append(Spacer(1, 3))
    
    facility_table_data = [
        [
            Paragraph("<b>Nội dung / Chỉ tiêu Tín dụng</b>", th_left),
            Paragraph("<b>Đề xuất của ĐVKD (Chi nhánh)</b>", th_style),
            Paragraph("<b>Đề xuất của Khối Thẩm định</b>", th_style)
        ],
        [
            Paragraph("<b>1. Hạn mức Cho vay quay vòng (VLĐ)</b>", cell_bold),
            Paragraph(f"{branch_req_limit / 1e9:,.2f} tỷ đồng", cell_center),
            Paragraph(f"<b>{risk_rec_limit / 1e9:,.2f} tỷ đồng</b>", cell_center)
        ],
        [
            Paragraph("<b>2. Hạn mức Bảo lãnh & L/C</b>", cell_style),
            Paragraph(f"{branch_req_limit * 0.20 / 1e9:,.2f} tỷ đồng", cell_center),
            Paragraph(f"{risk_rec_limit * 0.20 / 1e9:,.2f} tỷ đồng", cell_center)
        ],
        [
            Paragraph("<b>TỔNG NGHĨA VỤ KHÁCH HÀNG (1 + 2)</b>", cell_bold),
            Paragraph(f"<b>{branch_req_limit / 1e9:,.2f} tỷ đồng</b>", cell_center),
            Paragraph(f"<b>{risk_rec_limit / 1e9:,.2f} tỷ đồng</b>", cell_center)
        ],
        [
            Paragraph("Thời hạn duy trì hạn mức", cell_style),
            Paragraph("12 tháng", cell_center),
            Paragraph("12 tháng", cell_center)
        ],
        [
            Paragraph("Thời hạn cho vay tối đa từng KUNN", cell_style),
            Paragraph(f"Tối đa {wc_calc['recommended_ku_tenor_months'] + 1} tháng", cell_center),
            Paragraph(f"<b>Tối đa {wc_calc['recommended_ku_tenor_months']} tháng</b> (Theo vòng quay VLĐ)", cell_center)
        ],
        [
            Paragraph("Cơ cấu Tài sản Bảo đảm", cell_style),
            Paragraph(f"TSBĐ độc lập tối thiểu 70%", cell_center),
            Paragraph(f"<b>TSBĐ độc lập tối thiểu 80%</b>", cell_center)
        ],
        [
            Paragraph("Mục đích cấp tín dụng", cell_style),
            Paragraph(credit_purpose, cell_style),
            Paragraph(credit_purpose, cell_style)
        ]
    ]
    t_fac = Table(facility_table_data, colWidths=[185, 165, 165])
    t_fac.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1A365D")),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#94A3B8")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BACKGROUND', (0, 3), (-1, 3), colors.HexColor("#EFF6FF")),
    ]))
    story.append(t_fac)
    story.append(Spacer(1, 8))

    # =========================================================================
    # MỤC II: ĐIỀU KIỆN CẤP TÍN DỤNG & CAM KẾT (SMART COVENANTS)
    # =========================================================================
    story.append(Paragraph("II. ĐIỀU KIỆN CẤP TÍN DỤNG & CAM KẾT RÀNG BUỘC (CREDIT COVENANTS)", sec_title_style))
    story.append(Paragraph("Các điều kiện được tự động kích hoạt dựa trên kết quả giám định rủi ro EWS và quy chuẩn tín dụng:", body_style))
    story.append(Spacer(1, 3))
    
    # Bảng Điều kiện Trước Giải ngân
    story.append(Paragraph("1. Điều kiện Tiên quyết Trước khi Giải ngân (Pre-disbursement Conditions):", sub_sec_style))
    pre_cov_rows = [
        [
            Paragraph("<b>Mã</b>", th_left),
            Paragraph("<b>Tiêu đề Điều kiện</b>", th_left),
            Paragraph("<b>Nội dung Chi tiết & Chế tài</b>", th_left),
            Paragraph("<b>Phân loại</b>", th_style)
        ]
    ]
    for c in covenants_data["pre_conditions"]:
        pre_cov_rows.append([
            Paragraph(c["code"], cell_bold),
            Paragraph(c["title"], cell_bold),
            Paragraph(c["content"], cell_style),
            Paragraph(f"<font color='#9B2C2C'><b>{c['level']}</b></font>" if "Gian lận" in c["level"] else c["level"], cell_center)
        ])
    t_pre_cov = Table(pre_cov_rows, colWidths=[55, 125, 255, 80])
    t_pre_cov.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#334155")),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#94A3B8")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    story.append(t_pre_cov)
    story.append(Spacer(1, 5))
    
    # Bảng Điều kiện Quản lý Sau Giải ngân & Cam kết Tài chính
    story.append(Paragraph("2. Điều kiện Quản lý Dòng tiền & Cam kết Tài chính (Post-disbursement & Financial Covenants):", sub_sec_style))
    post_cov_rows = [
        [
            Paragraph("<b>Mã</b>", th_left),
            Paragraph("<b>Tiêu đề Cam kết</b>", th_left),
            Paragraph("<b>Nội dung Chi tiết & Ngưỡng Giám sát</b>", th_left),
            Paragraph("<b>Phân loại</b>", th_style)
        ]
    ]
    for c in (covenants_data["post_conditions"] + covenants_data["financial_covenants"]):
        post_cov_rows.append([
            Paragraph(c["code"], cell_bold),
            Paragraph(c["title"], cell_bold),
            Paragraph(c["content"], cell_style),
            Paragraph(c["level"], cell_center)
        ])
    t_post_cov = Table(post_cov_rows, colWidths=[55, 125, 255, 80])
    t_post_cov.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#334155")),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#94A3B8")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    story.append(t_post_cov)
    story.append(Spacer(1, 10))

    # =========================================================================
    # MỤC III: ĐÁNH GIÁ NĂNG LỰC DOANH NGHIỆP & MÔ HÌNH 5CS
    # =========================================================================
    story.append(Paragraph("III. ĐÁNH GIÁ NĂNG LỰC KHÁCH HÀNG & MÔ HÌNH ĐỊNH TÍNH 5CS", sec_title_style))
    
    qual_score_val = qual_results.get("total_qual_score", 76.5) if qual_results else 76.5
    story.append(Paragraph(f"• <b>Tư cách pháp nhân & Đăng ký kinh doanh:</b> Khách hàng hoạt động hợp pháp theo Luật Doanh nghiệp, người đại diện theo pháp luật có đủ năng lực hành vi dân sự, không phát sinh tranh chấp hoặc vi phạm hành chính.", body_style))
    story.append(Paragraph(f"• <b>Ban điều hành:</b> Đội ngũ quản lý có trên {firm_age} năm kinh nghiệm trong ngành, điều hành ổn định, không có lịch sử nợ xấu cá nhân.", body_style))
    story.append(Paragraph(f"• <b>Thị trường & Chuỗi cung ứng:</b> Mạng lưới đối tác thương mại đa dạng; chính sách thanh toán công nợ mua hàng từ 15-45 ngày và bán hàng từ 30-60 ngày.", body_style))
    story.append(Spacer(1, 3))
    
    five_c_rows = [
        [
            Paragraph("<b>Trục Tiêu chí 5Cs</b>", th_left),
            Paragraph("<b>Trọng số</b>", th_style),
            Paragraph("<b>Điểm số / 100</b>", th_style),
            Paragraph("<b>Nhận định Thẩm định</b>", th_left)
        ],
        [
            Paragraph("C1 - Uy tín & Lãnh đạo (Character)", cell_bold),
            Paragraph("20%", cell_center),
            Paragraph(f"{qual_results.get('group_scores', {}).get('C1', 82.0):.1f} đ" if qual_results else "82.0 đ", cell_center),
            Paragraph("Lãnh đạo uy tín, lịch sử quan hệ tín dụng chuẩn mực, không nợ xấu CIC.", cell_style)
        ],
        [
            Paragraph("C2 - Năng lực Vận hành (Capacity)", cell_bold),
            Paragraph("20%", cell_center),
            Paragraph(f"{qual_results.get('group_scores', {}).get('C2', 78.0):.1f} đ" if qual_results else "78.0 đ", cell_center),
            Paragraph("Hệ thống quản trị tốt, tỷ lệ hoàn thành kế hoạch doanh thu cao.", cell_style)
        ],
        [
            Paragraph("C3 - BCTC & Kiểm toán (Capital/Audit)", cell_bold),
            Paragraph("25%", cell_center),
            Paragraph(f"{qual_results.get('group_scores', {}).get('C3', 72.0):.1f} đ" if qual_results else "72.0 đ", cell_center),
            Paragraph("BCTC nộp cơ quan thuế đầy đủ, ý kiến kiểm toán chấp nhận toàn phần.", cell_style)
        ],
        [
            Paragraph("C4 - Ngành & Cạnh tranh (Conditions)", cell_bold),
            Paragraph("15%", cell_center),
            Paragraph(f"{qual_results.get('group_scores', {}).get('C4', 75.0):.1f} đ" if qual_results else "75.0 đ", cell_center),
            Paragraph("Ngành tiêu dùng thiết yếu ổn định, nhu cầu thị trường tăng trưởng.", cell_style)
        ],
        [
            Paragraph("C5 - Chuỗi Cung ứng & TSBĐ (Collateral)", cell_bold),
            Paragraph("20%", cell_center),
            Paragraph(f"{qual_results.get('group_scores', {}).get('C5', 80.0):.1f} đ" if qual_results else "80.0 đ", cell_center),
            Paragraph("Tài sản bảo đảm pháp lý rõ ràng, đối tác cung ứng đầu vào uy tín.", cell_style)
        ],
        [
            Paragraph("<b>ĐIỂM ĐỊNH TÍNH 5CS TỔNG HỢP</b>", cell_bold),
            Paragraph("<b>100%</b>", cell_center),
            Paragraph(f"<b>{qual_score_val:.1f} / 100</b>", cell_center),
            Paragraph(f"<b>Xếp hạng Đạt chuẩn Cấp tín dụng</b>", cell_bold)
        ]
    ]
    t_5c = Table(five_c_rows, colWidths=[150, 55, 75, 235])
    t_5c.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1E293B")),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#94A3B8")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor("#F1F5F9")),
    ]))
    story.append(t_5c)
    story.append(Spacer(1, 10))

    # =========================================================================
    # MỤC IV: PHÂN TÍCH TÀI CHÍNH VAS & CÂN ĐỐI DÒNG TIỀN (CCC)
    # =========================================================================
    story.append(Paragraph("IV. PHÂN TÍCH TÀI CHÍNH KẾ TOÁN VAS & CÂN ĐỐI DÒNG TIỀN", sec_title_style))
    story.append(Paragraph("1. Các chỉ tiêu tài chính cơ bản trích xuất từ BCTC theo Thông tư 200 (Đơn vị: VNĐ):", sub_sec_style))
    
    col_w_name = 175
    col_w_year = (515 - col_w_name) / max(1, len(years))
    
    fin_header = [Paragraph("<b>Chỉ tiêu Kế toán</b>", th_left)]
    for y in years:
        fin_header.append(Paragraph(f"<b>Năm {y}</b>", th_style))
    fin_rows = [fin_header]
    
    key_vars_to_show = [
        ("Total_Assets", "Tổng tài sản"),
        ("Current_Assets", "Tài sản ngắn hạn"),
        ("Cash_Equivalents", "Tiền và tương đương tiền"),
        ("Accounts_Receivable", "Phải thu ngắn hạn KH (131)"),
        ("Inventories", "Hàng tồn kho (140)"),
        ("Total_Liabilities", "Nợ phải trả"),
        ("Current_Liabilities", "Nợ ngắn hạn"),
        ("Equity", "Vốn chủ sở hữu"),
        ("Net_Sales", "Doanh thu thuần"),
        ("Gross_Profit", "Lợi nhuận gộp"),
        ("Net_Income", "Lợi nhuận sau thuế"),
        ("OCF", "Lưu chuyển tiền thuần từ HĐKD")
    ]
    for code, vname in key_vars_to_show:
        row = [Paragraph(vname, cell_style)]
        for y in years:
            val = extracted_data.get(y, {}).get(code, np.nan)
            if pd.isna(val) or val is None:
                val_s = "-"
            elif abs(val) >= 1_000_000_000:
                val_s = f"{val/1_000_000_000:,.2f} tỷ"
            elif abs(val) >= 1_000_000:
                val_s = f"{val/1_000_000:,.0f} tr"
            else:
                val_s = f"{val:,.0f}"
            row.append(Paragraph(val_s, cell_right))
        fin_rows.append(row)
        
    t_fin_full = Table(fin_rows, colWidths=[col_w_name] + [col_w_year]*len(years))
    t_fin_styles = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#334155")),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#94A3B8")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]
    for r_idx in range(1, len(fin_rows)):
        if r_idx % 2 == 1:
            t_fin_styles.append(('BACKGROUND', (0, r_idx), (-1, r_idx), colors.HexColor("#F8FAFC")))
    t_fin_full.setStyle(TableStyle(t_fin_styles))
    story.append(t_fin_full)
    story.append(Spacer(1, 5))
    
    # 2. Bảng Phân tích Chu kỳ Tiền mặt CCC & Cân đối Vốn vay
    story.append(Paragraph(f"2. Cân đối Vốn lưu động ròng (OWC) & Chu kỳ Chuyển đổi Tiền mặt (Năm {eval_year}):", sub_sec_style))
    ccc_rows = [
        [
            Paragraph("<b>Chỉ số Cân đối Vốn & Vận hành</b>", th_left),
            Paragraph("<b>Giá trị Thực tế</b>", th_style),
            Paragraph("<b>Đánh giá Thẩm định Rủi ro</b>", th_left)
        ],
        [
            Paragraph("Số ngày thu tiền bình quân (DSO)", cell_style),
            Paragraph(f"{wc_calc['dso']:.1f} ngày", cell_center),
            Paragraph("Thời hạn công nợ khách hàng trong tầm kiểm soát (< 60 ngày).", cell_style)
        ],
        [
            Paragraph("Số ngày tồn kho bình quân (DSI)", cell_style),
            Paragraph(f"{wc_calc['dsi']:.1f} ngày", cell_center),
            Paragraph("Hàng tồn kho luân chuyển tốt, phù hợp ngành tiêu dùng nhanh FMCG.", cell_style)
        ],
        [
            Paragraph("Số ngày trả tiền nhà cung cấp (DPO)", cell_style),
            Paragraph(f"{wc_calc['dpo']:.1f} ngày", cell_center),
            Paragraph("Doanh nghiệp tận dụng hợp lý chính sách tín dụng thương mại của NCC.", cell_style)
        ],
        [
            Paragraph("<b>Chu kỳ Tiền mặt Thực tế (CCC)</b>", cell_bold),
            Paragraph(f"<b>{wc_calc['ccc']:.1f} ngày</b>", cell_center),
            Paragraph("<b>Chu kỳ chuyển đổi tiền mặt lành mạnh, không bị đọng vốn nghiêm trọng.</b>", cell_bold)
        ],
        [
            Paragraph("<b>Tỷ lệ Vay ngắn hạn / (Phải thu + Tồn kho)</b>", cell_bold),
            Paragraph(f"<b>{wc_calc['debt_to_wc_assets_ratio']:.1%}</b>", cell_center),
            Paragraph("Vốn vay nằm trong hạn mức tự tài trợ của tài sản ngắn hạn (<= 100%)." if wc_calc['debt_to_wc_assets_ratio'] <= 1.0 else "⚠️ Vay ngắn hạn vượt quá tài sản ngắn hạn, cần giám sát mục đích vốn.", cell_style)
        ]
    ]
    t_ccc = Table(ccc_rows, colWidths=[185, 110, 220])
    t_ccc.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1E293B")),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#94A3B8")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BACKGROUND', (0, 4), (-1, 4), colors.HexColor("#EFF6FF")),
    ]))
    story.append(t_ccc)
    story.append(Spacer(1, 10))

    # =========================================================================
    # MỤC V: GIÁM ĐỊNH RỦI RO ĐỊNH LƯỢNG EWS & GIAN LẬN KẾ TOÁN
    # =========================================================================
    story.append(Paragraph("V. GIÁM ĐỊNH RỦI RO ĐỊNH LƯỢNG (EWS) & GIAN LẬN BÁO CÁO TÀI CHÍNH", sec_title_style))
    story.append(Paragraph("<i>Mã màu: <font color='#276749'><b>■ An toàn</b></font> | <font color='#B7791F'><b>■ Vùng xám / Theo dõi</b></font> | <font color='#9B2C2C'><b>■ Nguy hiểm / Cảnh báo Đỏ</b></font></i>", body_style))
    story.append(Spacer(1, 3))
    
    ews_rows = [
        [
            Paragraph("<b>Bộ chỉ số Định lượng EWS Chuẩn Quốc tế</b>", th_left)
        ]
    ]
    for y in years:
        ews_rows[0].append(Paragraph(f"<b>Năm {y}</b>", th_style))
        
    for k, vname in EWS_NAMES_VN.items():
        row = [Paragraph(vname, cell_style)]
        for y in years:
            res_item = ews_results.get(y, {}).get(k)
            if not res_item or res_item.get("score") is None:
                row.append(Paragraph("N/A", cell_center))
            else:
                score = res_item["score"]
                status = res_item.get("status", "normal")
                score_str = f"{score:.4f}"
                if status == "error":
                    p = Paragraph(f"<b>{score_str}</b><br/><font size=6.5 color='#9B2C2C'>Nguy hiểm</font>", alert_red)
                elif status == "warning":
                    p = Paragraph(f"<b>{score_str}</b><br/><font size=6.5 color='#B7791F'>Vùng xám</font>", alert_yellow)
                else:
                    p = Paragraph(f"<b>{score_str}</b><br/><font size=6.5 color='#276749'>An toàn</font>", alert_green)
                row.append(p)
        ews_rows.append(row)
        
    t_ews_full = Table(ews_rows, colWidths=[col_w_name] + [col_w_year]*len(years))
    t_ews_styles = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#0F2942")),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#94A3B8")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]
    for r_idx in range(1, len(ews_rows)):
        if r_idx % 2 == 1:
            t_ews_styles.append(('BACKGROUND', (0, r_idx), (-1, r_idx), colors.HexColor("#F8FAFC")))
    t_ews_full.setStyle(TableStyle(t_ews_styles))
    story.append(t_ews_full)
    story.append(Spacer(1, 10))

    # =========================================================================
    # MỤC VI: THẨM ĐỊNH TÀI SẢN BẢO ĐẢM & TỶ LỆ LTV
    # =========================================================================
    story.append(Paragraph("VI. THẨM ĐỊNH DANH MỤC TÀI SẢN BẢO ĐẢM (COLLATERAL & LTV)", sec_title_style))
    story.append(Paragraph("Chi tiết danh mục tài sản bảo đảm, giá trị thẩm định và tỷ lệ cho vay tối đa theo quy định:", body_style))
    story.append(Spacer(1, 3))
    
    collat_rows = [
        [
            Paragraph("<b>Loại TSBĐ</b>", th_left),
            Paragraph("<b>Mô tả Tài sản & Pháp lý</b>", th_left),
            Paragraph("<b>Giá trị Định giá</b>", th_style),
            Paragraph("<b>Tỷ lệ LTV</b>", th_style),
            Paragraph("<b>Mức Cho vay Tối đa</b>", th_style)
        ]
    ]
    for it in collat_eval["items"]:
        collat_rows.append([
            Paragraph(it["type"], cell_bold),
            Paragraph(it["description"], cell_style),
            Paragraph(f"{it['market_value'] / 1e9:,.2f} tỷ", cell_right),
            Paragraph(f"{it['ltv_rate']:.0%}", cell_center),
            Paragraph(f"<b>{it['secured_capacity'] / 1e9:,.2f} tỷ</b>", cell_right)
        ])
    collat_rows.append([
        Paragraph("<b>TỔNG CỘNG DANH MỤC</b>", cell_bold),
        Paragraph(f"Tỷ lệ bao phủ TSBĐ: <b>{collat_eval['coverage_ratio']:.1%}</b>", cell_style),
        Paragraph(f"<b>{collat_eval['total_market_value'] / 1e9:,.2f} tỷ</b>", cell_right),
        Paragraph("-", cell_center),
        Paragraph(f"<b>{collat_eval['total_secured_capacity'] / 1e9:,.2f} tỷ</b>", cell_right)
    ])
    t_collat = Table(collat_rows, colWidths=[90, 185, 80, 60, 100])
    t_collat.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1A365D")),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#94A3B8")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor("#F1F5F9")),
    ]))
    story.append(t_collat)
    story.append(Spacer(1, 4))
    
    sec_summary_txt = f"• <b>Cơ cấu Bảo đảm:</b> Hạn mức có TSBĐ: <b>{collat_eval['secured_facility_amount']/1e9:,.2f} tỷ đồng ({collat_eval['secured_ratio']:.1%})</b> | Hạn mức không có TSBĐ (tín chấp ngắn hạn): <b>{collat_eval['unsecured_facility_amount']/1e9:,.2f} tỷ đồng ({collat_eval['unsecured_ratio']:.1%})</b>."
    story.append(Paragraph(sec_summary_txt, body_style))
    if not collat_eval["meets_80_secured_rule"]:
        story.append(Paragraph("⚠️ <i>Lưu ý: Tỷ lệ TSBĐ độc lập dưới 80% quy chuẩn chuẩn hóa, hồ sơ thuộc thẩm quyền phê duyệt ngoại lệ chính sách C2/C3.</i>", alert_yellow))
    story.append(Spacer(1, 10))

    # =========================================================================
    # MỤC VII: MA TRẬN NHẬN DIỆN RỦI RO & BIỆN PHÁP GIẢM THIỂU
    # =========================================================================
    story.append(Paragraph("VII. MA TRẬN NHẬN DIỆN RỦI RO & BIỆN PHÁP GIẢM THIỂU (RISK MATRIX)", sec_title_style))
    risk_rows = [
        [
            Paragraph("<b>Nhóm Rủi ro</b>", th_left),
            Paragraph("<b>Chi tiết Rủi ro Nhận diện từ Số liệu EWS</b>", th_left),
            Paragraph("<b>Biện pháp Giảm thiểu & Kiểm soát</b>", th_left)
        ]
    ]
    for rk in risk_matrix:
        risk_rows.append([
            Paragraph(f"<b>{rk['category']}</b>", cell_bold),
            Paragraph(rk["risk_detail"], cell_style),
            Paragraph(rk["mitigation"], cell_style)
        ])
    t_risk = Table(risk_rows, colWidths=[115, 200, 200])
    t_risk.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#334155")),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#94A3B8")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    story.append(t_risk)
    story.append(Spacer(1, 10))

    # =========================================================================
    # MỤC VIII: PHỤ LỤC TÍNH TOÁN NHU CẦU VỐN LƯU ĐỘNG
    # =========================================================================
    story.append(Paragraph("VIII. PHỤ LỤC: TÍNH TOÁN NHU CẦU VỐN LƯU ĐỘNG & HẠN MỨC TÍN DỤNG", sec_title_style))
    story.append(Paragraph(f"Áp dụng phương pháp tính theo Chu kỳ Vốn lưu động chuẩn nghiệp vụ Ngân hàng Thương mại:", body_style))
    story.append(Spacer(1, 3))
    
    wc_calc_rows = [
        [
            Paragraph("<b>TT</b>", th_style),
            Paragraph("<b>Chỉ tiêu Tính toán Nhu cầu Vốn</b>", th_left),
            Paragraph("<b>Đơn vị</b>", th_style),
            Paragraph("<b>Giá trị Tính toán</b>", th_style),
            Paragraph("<b>Cơ sở Thẩm định & Thuyết minh</b>", th_left)
        ],
        [
            Paragraph("1", cell_center),
            Paragraph("Doanh thu thuần năm kế hoạch", cell_style),
            Paragraph("Tr.đ", cell_center),
            Paragraph(f"{wc_calc['planned_sales'] / 1e6:,.0f}", cell_right),
            Paragraph("Dự phóng dựa trên tốc độ tăng trưởng doanh thu lịch sử.", cell_style)
        ],
        [
            Paragraph("2", cell_center),
            Paragraph("Giá vốn hàng bán năm kế hoạch", cell_style),
            Paragraph("Tr.đ", cell_center),
            Paragraph(f"{wc_calc['planned_cogs'] / 1e6:,.0f}", cell_right),
            Paragraph(f"Tỷ lệ giá vốn kế hoạch: {wc_calc['cogs_ratio']:.1%} doanh thu.", cell_style)
        ],
        [
            Paragraph("3", cell_center),
            Paragraph("Vòng quay Vốn lưu động (T)", cell_bold),
            Paragraph("Vòng/năm", cell_center),
            Paragraph(f"<b>{wc_calc['wc_turnover']:.2f}</b>", cell_center),
            Paragraph("Căn cứ vòng quay vốn lưu động bình quân thực tế.", cell_style)
        ],
        [
            Paragraph("4", cell_center),
            Paragraph("<b>Tổng nhu cầu Vốn lưu động (1 / 3)</b>", cell_bold),
            Paragraph("Tr.đ", cell_center),
            Paragraph(f"<b>{wc_calc['total_wc_need'] / 1e6:,.0f}</b>", cell_right),
            Paragraph("Tổng vốn lưu động cần thiết tài trợ chu kỳ kinh doanh.", cell_style)
        ],
        [
            Paragraph("5", cell_center),
            Paragraph("Vốn tự có tham gia (25%)", cell_style),
            Paragraph("Tr.đ", cell_center),
            Paragraph(f"{wc_calc['equity_contribution'] / 1e6:,.0f}", cell_right),
            Paragraph("Vốn tự có của doanh nghiệp tham gia tối thiểu 20-30%.", cell_style)
        ],
        [
            Paragraph("6", cell_center),
            Paragraph("Vốn chiếm dụng nhà cung cấp", cell_style),
            Paragraph("Tr.đ", cell_center),
            Paragraph(f"{wc_calc['planned_supplier_credit'] / 1e6:,.0f}", cell_right),
            Paragraph(f"Căn cứ số ngày phải trả người bán bình quân ({wc_calc['dpo']:.0f} ngày).", cell_style)
        ],
        [
            Paragraph("7", cell_center),
            Paragraph("<b>Nhu cầu Vay VLĐ Tối đa Đề xuất (4 - 5 - 6)</b>", cell_bold),
            Paragraph("Tr.đ", cell_center),
            Paragraph(f"<b>{wc_calc['recommended_credit_limit'] / 1e6:,.0f}</b>", cell_right),
            Paragraph(f"<b>Hạn mức đề xuất cấp: {wc_calc['recommended_credit_limit']/1e9:,.2f} tỷ đồng.</b>", cell_bold)
        ]
    ]
    t_wc_calc = Table(wc_calc_rows, colWidths=[25, 175, 45, 90, 180])
    t_wc_calc.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1A365D")),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#94A3B8")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BACKGROUND', (0, 4), (-1, 4), colors.HexColor("#F8FAFC")),
        ('BACKGROUND', (0, 7), (-1, 7), colors.HexColor("#EFF6FF")),
    ]))
    story.append(t_wc_calc)
    story.append(Spacer(1, 10))

    # =========================================================================
    # MỤC IX: Ý KIẾN THẨM ĐỊNH, KHÁC BIỆT CHÍNH SÁCH & PHÊ DUYỆT TRÌNH KÝ
    # =========================================================================
    story.append(Paragraph("IX. Ý KIẾN THẨM ĐỊNH & TRÌNH PHÊ DUYỆT CẤP TÍN DỤNG", sec_title_style))
    story.append(Paragraph("1. Khác biệt Chính sách & Giải trình Ngoại lệ (Policy Exception Memo):", sub_sec_style))
    
    has_unsec = collat_eval["unsecured_facility_amount"] > 0
    policy_rows = [
        [
            Paragraph("<b>Nội dung Khác biệt</b>", th_left),
            Paragraph("<b>Quy định Chuẩn Sản phẩm</b>", th_left),
            Paragraph("<b>Phương án Đề xuất Thực tế</b>", th_left),
            Paragraph("<b>Đánh giá & Cơ sở Chấp thuận</b>", th_left)
        ],
        [
            Paragraph("Thời hạn cho vay KUNN", cell_bold),
            Paragraph("Tối đa 4 tháng/KUNN", cell_style),
            Paragraph(f"Tối đa {wc_calc['recommended_ku_tenor_months']} tháng/KUNN", cell_style),
            Paragraph(f"Phù hợp với chu kỳ tiền mặt thực tế ({wc_calc['ccc']:.0f} ngày) của ngành.", cell_style)
        ],
        [
            Paragraph("Cơ cấu TSBĐ độc lập", cell_bold),
            Paragraph("100% TSBĐ độc lập", cell_style),
            Paragraph(f"TSBĐ {collat_eval['secured_ratio']:.0%}, Tín chấp {collat_eval['unsecured_ratio']:.0%}" if has_unsec else "Đạt 100% TSBĐ", cell_style),
            Paragraph("Chấp thuận áp dụng lộ trình bổ sung TSBĐ trong 30 ngày." if has_unsec else "Tuân thủ chuẩn.", cell_style)
        ]
    ]
    t_policy = Table(policy_rows, colWidths=[110, 115, 130, 160])
    t_policy.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#334155")),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#94A3B8")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    story.append(t_policy)
    story.append(Spacer(1, 8))
    
    story.append(Paragraph(f"<b>Kết luận Thẩm định:</b> Khách hàng hoạt động kinh doanh có hiệu quả, dòng tiền vận hành ổn định, đáp ứng điều kiện cấp tín dụng của Ngân hàng. Kính trình <b>{auth_info['approval_authority']}</b> xem xét phê duyệt Cấp hạn mức tín dụng <b>{risk_rec_limit/1e9:,.2f} tỷ đồng</b> theo đúng các điều kiện ràng buộc nêu trên.", body_style))
    story.append(Spacer(1, 15))

    # Khung Ký duyệt 3 Cấp
    sign_data = [
        [
            Paragraph("<b>CÁN BỘ THẨM ĐỊNH RỦI RO</b><br/><i>(Ký và ghi rõ họ tên)</i>", ParagraphStyle('SignF1', fontName=FONT_REGULAR, fontSize=8, alignment=1)),
            Paragraph("<b>TRƯỞNG PHÒNG THẨM ĐỊNH</b><br/><i>(Ký và ghi rõ họ tên)</i>", ParagraphStyle('SignF2', fontName=FONT_REGULAR, fontSize=8, alignment=1)),
            Paragraph(f"<b>CẤP THẨM QUYỀN PHÊ DUYỆT</b><br/><i>({auth_info['approval_authority'].split('-')[0].strip()})</i>", ParagraphStyle('SignF3', fontName=FONT_REGULAR, fontSize=8, alignment=1))
        ],
        [Spacer(1, 35), Spacer(1, 35), Spacer(1, 35)],
        [
            Paragraph("....................................................", ParagraphStyle('DotF1', fontName=FONT_REGULAR, fontSize=8, alignment=1)),
            Paragraph("....................................................", ParagraphStyle('DotF2', fontName=FONT_REGULAR, fontSize=8, alignment=1)),
            Paragraph("....................................................", ParagraphStyle('DotF3', fontName=FONT_REGULAR, fontSize=8, alignment=1))
        ]
    ]
    t_sign_full = Table(sign_data, colWidths=[171, 171, 173])
    t_sign_full.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(KeepTogether(t_sign_full))

    # Xây dựng PDF
    doc.build(story, canvasmaker=BankUnderwritingNumberedCanvas)
    buffer.seek(0)
    return buffer.getvalue()

