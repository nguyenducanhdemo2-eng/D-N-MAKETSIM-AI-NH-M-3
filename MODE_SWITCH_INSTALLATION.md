# Cập nhật chuyển chế độ ADMIN / Nhân viên

Chép các file trong gói vào thư mục gốc dự án MarketSim AI, giữ nguyên cấu
trúc `backend/`, `frontend/` và `tests/`, sau đó chọn ghi đè file trùng tên.
Gói này được xây dựng trên bản đã áp dụng `MAKETSIM_AI_FIX_FILES_STEP_1`.

Không cần thay `.env` và không cần sửa database thủ công. Khi server khởi động,
bảng `web_sessions` tự được bổ sung cột `active_mode`.

Sau khi cập nhật:

- Trang ADMIN có nút **Chuyển sang chế độ nhân viên**.
- Khi Admin ở khu vực nhân viên, thanh tài khoản có nút **Trở về chế độ ADMIN**.
- Chế độ được lưu ở session trên server; nhân viên không thể tự nâng quyền.
- Dữ liệu Admin tạo trong chế độ nhân viên thuộc chính tài khoản Admin và vẫn
  nằm trong doanh nghiệp của Admin.

Khởi động lại ứng dụng:

```bash
python run.py
```
