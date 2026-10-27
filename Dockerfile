# Sử dụng Python 3.10 slim làm base image để tối ưu dung lượng
FROM python:3.10-slim

# Thiết lập các biến môi trường
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Cài đặt các thư viện hệ thống cần thiết, Tesseract OCR kèm tiếng Việt, và font DejaVu cho PDF ReportLab
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-vie \
    fonts-dejavu-core \
    libgl1-mesa-glx \
    libglib2.0-0 \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Thiết lập thư mục làm việc trong container
WORKDIR /app

# Sao chép file requirements.txt và cài đặt các thư viện Python
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Sao chép toàn bộ mã nguồn ứng dụng và tài nguyên cần thiết
COPY fintrust_app.py /app/
COPY credit_underwriting_engine.py /app/
COPY pdf_report_generator.py /app/
COPY u_curve_regression.py /app/
COPY quarterly_leverage_updater.py /app/
COPY quarterly_scheduler_config.json /app/
COPY best_ews_model.joblib /app/
COPY industry_opt_lev.json /app/
COPY Fintech_EWS_GroundTruth_Template.xlsx /app/
COPY fintrust_ews.db /app/

# Khai báo cổng chạy Streamlit
EXPOSE 8501

# Thiết lập điểm chạy chính của container
ENTRYPOINT ["streamlit", "run", "fintrust_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
