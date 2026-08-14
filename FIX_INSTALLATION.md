# Cài các file sửa lỗi MarketSim AI

Gói bàn giao chỉ chứa các file đã sửa hoặc file mới cần thêm. Chép toàn bộ nội
dung của gói vào **thư mục gốc dự án**, giữ nguyên các thư mục con như
`backend/`, `frontend/` và `scripts/`, rồi cho phép ghi đè các file trùng tên.

Các file trong gói:

- Cấu hình/bảo mật: `.gitignore`, `.env.example`, `config.py`, `backend/config.py`,
  `backend/security.py`, `backend/auth_db.py`, `backend/admin_db.py`.
- API và giao diện phân quyền: `backend/main.py`, `frontend/admin.html`,
  `frontend/pages/login.html`, `frontend/js/app.js`.
- Nghiệp vụ/dữ liệu: `database.py`, `advanced_simulation.py`,
  `marketing_learning.py`.
- Migration/kiểm thử: `scripts/migrate_ownership.py`,
  `scripts/ownership_plan.example.json`, `tests/test_security_regressions.py`.

## Việc bắt buộc trước khi chạy

1. Thu hồi khóa Groq cũ và tạo khóa mới.
2. Không chép `.env` hoặc `marketsim.db*` từ bản dự án đã chia sẻ sang máy khác.
3. Sao chép `.env.example` thành `.env`, điền khóa mới và một
   `ADMIN_BOOTSTRAP_CODE` dài, ngẫu nhiên.
4. Production phải đặt `APP_ENV=production`, `SESSION_COOKIE_SECURE=true` và dùng
   đường dẫn database nằm trên persistent disk hoặc chuyển sang PostgreSQL.

`.gitignore` không tự bỏ theo dõi những file đã từng commit. Sau khi sao lưu dữ
liệu thật ở nơi an toàn, bỏ chúng khỏi Git index bằng lệnh phù hợp với repository,
ví dụ:

```bash
git rm --cached -- .env marketsim.db marketsim.db-shm marketsim.db-wal
```

Sau đó commit `.gitignore` và `.env.example`. Vì khóa cũ đã xuất hiện trong lịch
sử Git/ZIP, xóa file ở commit mới là chưa đủ: vẫn phải thu hồi khóa cũ; nếu repo
đã được chia sẻ công khai, dùng công cụ làm sạch lịch sử Git theo quy trình của
nhóm trước khi push lại.

Khi khởi động lần đầu, toàn bộ session theo schema cũ bị thu hồi có chủ đích;
mọi người cần đăng nhập lại. Mật khẩu cũ vẫn đăng nhập được và tự được nâng cấp
sang PBKDF2 sau lần đăng nhập thành công đầu tiên.

## Migration dữ liệu cũ chưa có chủ sở hữu

Không tự gán dữ liệu cho một tài khoản bằng phỏng đoán. Trước tiên chạy:

```bash
python scripts/migrate_ownership.py --db ./marketsim.db --audit
```

Sao chép `scripts/ownership_plan.example.json` thành một file plan riêng, thay
ID mẫu bằng quan hệ sở hữu đã được doanh nghiệp xác nhận. Kiểm tra dry-run:

```bash
python scripts/migrate_ownership.py --db ./marketsim.db --plan ownership_plan.json
```

Chỉ khi kết quả đúng mới áp dụng:

```bash
python scripts/migrate_ownership.py --db ./marketsim.db --plan ownership_plan.json --apply
```

Lệnh áp dụng tự tạo một bản backup database trước khi thay đổi. Không đưa file
plan có dữ liệu thật hoặc bản backup vào Git/ZIP chia sẻ.
