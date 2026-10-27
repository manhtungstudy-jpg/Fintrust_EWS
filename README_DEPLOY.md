# HƯỚNG DẪN TRIỂN KHAI HỆ THỐNG FINTRUST EWS & CREDIT UNDERWRITING

Tài liệu hướng dẫn cài đặt và vận hành hệ thống **FinTrust EWS** (Bao gồm Báo cáo Thẩm định Cấp Tín dụng Toàn diện 10 trụ cột & Hệ thống Giám định Cảnh báo Sớm EWS).

---

## CÁCH 1: KHỞI CHẠY TRỰC TIẾP TRÊN MÁY TÍNH CÁ NHÂN (1-CLICK)

### Dành cho Windows:
1. Giải nén thư mục dự án ra một thư mục trên máy (ví dụ: `D:\FinTrust_EWS`).
2. Nhấp đúp chuột vào file **`run_local.bat`**.
3. Hệ thống sẽ tự động:
   - Kiểm tra Python (nếu chưa có sẽ hướng dẫn cài qua Microsoft Store hoặc python.org).
   - Tự động tạo môi trường ảo `venv` và cài đặt các thư viện cần thiết (`requirements.txt`).
   - Mở giao diện trên trình duyệt web tại địa chỉ: `http://localhost:8501`.

### Dành cho macOS / Linux:
1. Mở ứng dụng **Terminal** và điều hướng vào thư mục dự án.
2. Cấp quyền thực thi và chạy script:
   ```bash
   chmod +x run_local.sh
   ./run_local.sh
   ```
3. Trình duyệt sẽ tự động mở trang chủ FinTrust.

---

## CÁCH 2: TRIỂN KHAI BẰNG DOCKER & DOCKER COMPOSE (VPS / SERVER)

Phù hợp khi triển khai lên máy chủ Linux (Ubuntu, Debian, CentOS), VPS Cloud (DigitalOcean, AWS, GCP, Linode):

1. Đảm bảo máy chủ đã cài đặt **Docker** và **Docker Compose**.
2. Đặt toàn bộ các file dự án vào máy chủ.
3. Chạy lệnh:
   ```bash
   docker compose up -d --build
   ```
4. Truy cập hệ thống tại: `http://<IP_MAY_CHU>:8501`.
5. Dữ liệu và database được bảo toàn bền vững tại thư mục `./data`.

---

## CÁCH 3: TRIỂN KHAI MIỄN PHÍ TRÊN STREAMLIT COMMUNITY CLOUD

1. Đưa mã nguồn lên một kho lưu trữ **GitHub** cá nhân (Private hoặc Public).
2. Truy cập [share.streamlit.io](https://share.streamlit.io) và đăng nhập bằng GitHub.
3. Nhấn **New app**:
   - **Repository**: Chọn repository của bạn.
   - **Branch**: `main` (hoặc `master`).
   - **Main file path**: `fintrust_app.py`.
4. Nhấn **Deploy!**. Streamlit Cloud sẽ tự động đọc `packages.txt` (để cài Tesseract OCR và Font tiếng Việt) và `requirements.txt`.

---

## DANH MỤC CÁC TỆP TIN CỐT LÕI CẦN THIẾT
1. **`fintrust_app.py`**: Giao diện và luồng nghiệp vụ trung tâm của ứng dụng.
2. **`credit_underwriting_engine.py`**: Bộ vi xử lý thẩm định tín dụng, định mức vốn lưu động, định giá TSBĐ & LTV, Smart Covenants, ma trận rủi ro.
3. **`pdf_report_generator.py`**: Module xuất báo cáo PDF chuẩn Ngân hàng thương mại (Memo toàn diện) và EWS.
4. **`u_curve_regression.py`**: Thuật toán tính đòn bẩy tài chính tối ưu theo ngành.
5. **`quarterly_leverage_updater.py`**: Module tự động cập nhật hệ số đòn bẩy tối ưu theo quý.
6. **`quarterly_scheduler_config.json`**: Cấu hình chu kỳ và lịch biểu cập nhật đòn bẩy theo quý.
7. **`best_ews_model.joblib`**: Mô hình Machine Learning dự báo rủi ro kiệt quệ tài chính.
8. **`industry_opt_lev.json`**: Tham số cấu hình cấu trúc vốn tối ưu từng ngành kinh tế.
9. **`Fintech_EWS_GroundTruth_Template.xlsx`**: File mẫu Excel chuẩn BCTC Thông tư 200.
10. **`fintrust_ews.db`**: Cơ sở dữ liệu SQLite lưu trữ lịch sử hồ sơ.
11. **`requirements.txt`**: Danh sách thư viện Python.
12. **`packages.txt`**: Danh sách gói hệ điều hành (OCR & Fonts tiếng Việt).
13. **`Dockerfile` & `docker-compose.yml`**: Cấu hình đóng gói container.
14. **`run_local.bat` & `run_local.sh`**: File chạy tự động 1-click.
