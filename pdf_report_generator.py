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
    
    if not years:
        story.append(Paragraph("Chưa có dữ liệu BCTC để tính toán.", body_style))
    else:
        # Header bảng EWS
        col_w_name = 195
        col_w_year = (515 - col_w_name) / len(years)
        
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
