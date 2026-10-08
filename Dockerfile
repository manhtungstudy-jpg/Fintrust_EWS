# Sử dụng Python 3.10 slim làm base image để tối ưu dung lượng
FROM python:3.10-slim

# Thiết lập các biến môi trường
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Cài đặt các thư viện hệ thống cần thiết và Tesseract OCR kèm ngôn ngữ Tiếng Việt (vie)
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-vie \
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

# Sao chép mã nguồn giao diện chính vào container
COPY fintrust_app.py /app/

# Khai báo cổng chạy Streamlit
EXPOSE 8501

# Thiết lập điểm chạy chính của container
ENTRYPOINT ["streamlit", "run", "fintrust_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
