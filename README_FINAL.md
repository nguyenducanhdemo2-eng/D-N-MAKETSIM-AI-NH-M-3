
# MarketSim AI — Final Cloud

Bản này chuyển hoàn toàn khỏi Streamlit: FastAPI + HTML/CSS/JavaScript.

## Core logic preserved
- data_collector / schema_mapper / data_preprocessor
- Customer Intelligence + RFM/provenance
- Hybrid Segmentation
- Data-driven Persona
- Digital Twin
- Campaign simulation + A/B + optimization
- Calibration + feedback learning
- SQLite database 14 bảng cốt lõi và dữ liệu cũ được giữ nguyên

## AI
- Groq Cloud: khuyến nghị khi deploy domain; chỉ server cần API key.
- Ollama: tùy chọn khi server có Ollama.
- Không đặt API key trong frontend.

## Chạy local
1. Python 3.11 khuyến nghị.
2. `python -m venv .venv`
3. Windows PowerShell: `Set-ExecutionPolicy -Scope Process Bypass` rồi `\.venv\Scripts\Activate.ps1`.
4. `python -m pip install -r requirements.txt`
5. copy `.env.example` thành `.env`, điền `GROQ_API_KEY`.
6. `python run.py`
7. mở http://127.0.0.1:8000

## Database
`marketsim.db` là database cũ được giữ nguyên. App chỉ bổ sung bảng `web_sessions`, không reset dữ liệu cũ.

## Bổ sung trong bản Enhanced (không cắt luồng cũ)

Bản này giữ nguyên toàn bộ cấu trúc/login/API/simulation của `MarketSim_AI_FINAL_COMPLETE_GROQ` và bổ sung một luồng onboarding dữ liệu có xác nhận:

1. **Đọc dữ liệu trước AI** — `/api/customers/inspect`: chỉ đọc CSV/XLSX, thống kê số dòng/cột, kiểu dữ liệu, dữ liệu trống, duplicate và mẫu dữ liệu. Không gọi AI.
2. **Xác nhận dữ liệu** — người dùng xem bảng preview rồi mới bấm xác nhận.
3. **Mapping 2 lớp** — rule-based chạy trước; Groq chỉ xử lý cột chưa nhận diện.
4. **AI Learning** — `/api/customers/learning/start/{session_id}` học từ dữ liệu real đã mapping, bổ sung phần thiếu và lưu provenance `REAL` / `AI_INFERRED` / `MISSING`.
5. **Audit** — hiển thị tỷ lệ dữ liệu thật, AI bổ sung, còn thiếu; từng trường có coverage; có confidence/evidence/strategy của AI.
6. **Xác nhận Audit** — chỉ sau bước này luồng staged mới mở Digital Twin và mô phỏng.
7. **Digital Twin** — giữ nguyên progress bar, danh sách khách hàng ảo, propensity heuristic và provenance của bản Groq gốc.
8. **Mô phỏng / A-B / tối ưu / calibration / marketing learning** — giữ nguyên các endpoint và logic hiện có.

Endpoint `/api/customers/upload` cũ vẫn được giữ nguyên để bảo đảm tương thích ngược. Luồng upload cũ tự đánh dấu audit đã hoàn tất vì nó vốn đã chạy toàn bộ ETL trước khi trả kết quả.

## Bổ sung quản lý dữ liệu theo tài khoản

- Giao diện chỉ còn **một** luồng upload chính: Đọc & kiểm tra → Xác nhận → Mapping → AI Learning → Audit → Xác nhận → Digital Twin.
- Luồng giao diện upload cũ “Tải lên và xử lý” đã được loại khỏi UI để tránh trùng workflow. Endpoint backend cũ vẫn được giữ để không phá tương thích logic/API hiện hữu.
- Mỗi dataset mới được gắn `user_id` của tài khoản đăng nhập.
- Dữ liệu canonical của dataset được lưu đầy đủ trong SQLite; bản upload cũng giữ toàn bộ records đã chuẩn hóa để phục vụ lịch sử/khôi phục.
- Chỉ dataset có **AI Learning đã được người dùng xác nhận** mới được dùng làm knowledge base tích lũy cho các lần học tiếp theo.
- Lần AI Learning tiếp theo kết hợp dữ liệu hiện tại với toàn bộ dữ liệu canonical đã xác nhận của **chính tài khoản đó**.
- Dữ liệu của tài khoản khác không được đưa vào knowledge base của tài khoản hiện tại.
- Trang Dữ liệu khách hàng có thêm lịch sử dataset và thống kê số bản ghi đã lưu.
