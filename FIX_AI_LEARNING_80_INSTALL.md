# BẢN SỬA AI LEARNING 80%, CHI TIẾT DATASET, GOOGLE TRENDS VÀ ĐĂNG KÝ DOANH NGHIỆP

Ngày cập nhật: 2026-08-17

## Hiện tượng đã sửa

- AI Learning dừng tại 80% ở bước "Lưu audit dữ liệu".
- Dataset đã xuất hiện nhưng hiển thị 0 khách hàng đã lưu.
- Background job tiếp tục ở trạng thái `running` và không có audit để xác nhận.
- Các bộ dữ liệu trong "Kho dữ liệu tài khoản" không bấm chọn được và không
  hiển thị trực tiếp AI đã học những gì.
- Nút "Lấy xu hướng tìm kiếm" không lấy được dữ liệu Pytrends.
- Biểu mẫu tạo doanh nghiệp yêu cầu một mã cấp phép chưa tồn tại đối với người
  đăng ký mới.

Nguyên nhân là AI có thể trả `candidate_values` dạng object, ví dụ:

```json
{"value": "Thận trọng", "count": 103}
```

Object này bị đưa thẳng vào cột `personality`. SQLite chỉ chấp nhận giá trị vô
hướng như chuỗi hoặc số nên phát sinh lỗi `type 'dict' is not supported`.

## Chức năng mới

Trong trang **Dữ liệu khách hàng**, mỗi bộ dữ liệu trong **Kho dữ liệu tài
khoản** giờ là một nút có thể chọn. Khi bấm, hệ thống hiển thị:

- Trạng thái: đã xác nhận, chờ xác nhận audit hoặc chưa có kết quả AI.
- Tỷ lệ dữ liệu gốc, dữ liệu dẫn xuất, AI bổ sung và còn thiếu.
- Từng trường AI đã học, độ chắc chắn, bằng chứng và chiến lược xử lý.
- Những giá trị quan sát mà AI được phép dùng để bổ sung dữ liệu.
- Bảng nguồn hình thành dữ liệu theo từng trường.

API chi tiết mới kiểm tra quyền sở hữu tài khoản trước khi trả audit. Người dùng
không thể xem dataset của tài khoản khác bằng cách đoán ID.

## Đăng ký doanh nghiệp không cần mã cấp phép

Biểu mẫu **Đăng ký doanh nghiệp** giờ chỉ cần tên người quản trị, tên doanh
nghiệp, email và mật khẩu. Backend không còn đọc hoặc kiểm tra
`ADMIN_BOOTSTRAP_CODE`. Sau khi tạo thành công, hệ thống vẫn tự sinh mã dạng
`MS-XXXX-XXXX` để quản trị viên gửi cho nhân viên.

API vẫn giới hạn tối đa 5 lần thử đăng ký trong một giờ cho mỗi nguồn yêu cầu,
nhằm hạn chế thao tác lặp hoặc tạo tài khoản hàng loạt ngoài ý muốn.

## Bản sửa Google Trends / Pytrends

Nguyên nhân trực tiếp trong mã cũ là backend import hàm `fetch_pytrends`, nhưng
`data_collector.py` chỉ có hàm `fetch_google_trends`. Lệnh import lỗi trước khi
gửi yêu cầu tới Google.

Luồng mới đã được sửa như sau:

- Bổ sung đúng hàm `fetch_pytrends` và vẫn giữ `fetch_google_trends` để tương
  thích với pipeline cũ.
- Trả đủ điểm trung bình, điểm hiện tại và điểm đỉnh cho giao diện.
- Chạy yêu cầu mạng ngoài event loop của FastAPI, tránh làm treo các API khác.
- Cache kết quả 15 phút để nhiều lần bấm không tạo chùm yêu cầu dẫn tới HTTP
  429.
- Nhận diện riêng lỗi 429, 403, timeout và lỗi nguồn; log server bắt đầu bằng
  `[PYTRENDS ...]`.
- Khi endpoint không chính thức mà Pytrends dùng bị Google giới hạn, hệ thống
  tự chuyển sang feed RSS được xuất từ Google Trends. Giao diện ghi rõ đang dùng
  nguồn dự phòng, không báo thành công giả với bảng rỗng.
- Không bật cơ chế retry cũ của Pytrends 4.9 vì cơ chế đó dùng tham số urllib3
  đã lỗi thời; ứng dụng tự retry có giới hạn đối với lỗi mạng tạm thời.

## File cần chép đè

Giải nén gói ZIP tại thư mục gốc dự án rồi chép đè các đường dẫn:

- `staged_data_workflow.py`
- `database.py`
- `backend/main.py`
- `backend/admin_db.py`
- `frontend/pages/login.html`
- `frontend/index.html`
- `frontend/js/app.js`
- `frontend/css/app.css`
- `data_collector.py`
- `config.py`
- `backend/config.py`
- `.env.example`
- `requirements.txt`
- `tests/test_security_regressions.py`

## Cách cài đặt

1. Dừng server MarketSim AI.
2. Sao lưu các file ở trên và file `marketsim.db`.
3. Giải nén gói sửa vào thư mục gốc dự án, cho phép chép đè file cũ.
4. Cài/đồng bộ thư viện bằng lệnh `pip install -r requirements.txt` trong đúng
   môi trường Python đang chạy server.
5. Khởi động lại server.
6. Xóa dataset lỗi cũ rồi tải lại file CSV và chạy AI Learning từ đầu.
7. Nếu trình duyệt vẫn hiện giao diện cũ, bấm `Ctrl + F5` một lần. Phiên bản
   CSS/JavaScript trong gói đã được đổi mã cache để trình duyệt tự tải bản mới.

Nếu file `.env` cũ còn dòng `ADMIN_BOOTSTRAP_CODE=...`, có thể xóa dòng này;
phiên bản mới không còn sử dụng biến đó.

Không chép đè file `.env` đang dùng bằng `.env.example`. Các tùy chọn Google
Trends mới đã có giá trị mặc định an toàn. Chỉ cần thêm chúng vào `.env` nếu
muốn thay đổi từ khóa, khu vực, thời gian cache hoặc timeout.

Trong database được kiểm tra, dataset lỗi cũ có `upload_id = 27` và thuộc
`user_id = 9`. Khi đang đăng nhập đúng tài khoản, có thể xóa an toàn qua API
sẵn có của ứng dụng bằng Console của trình duyệt:

```javascript
fetch('/api/learning/history/27', {method: 'DELETE'})
  .then(response => response.json())
  .then(console.log)
```

API có kiểm tra chủ sở hữu, nên không xóa dữ liệu của tài khoản khác. Không xóa
hai dataset đã hoàn thành có `upload_id` 25 và 26.

## Kết quả mong đợi sau khi sửa

Tiến độ sẽ hiển thị rõ các mốc:

- 80%: chuẩn bị lưu dữ liệu
- 84%: lưu khách hàng đã chuẩn hóa
- 88%: lưu báo cáo audit
- 91%: tính Customer Intelligence
- 95%: phân nhóm khách hàng
- 98%: tạo chân dung khách hàng
- 100%: hoàn thành và chờ xác nhận audit

Nếu vẫn có lỗi, log server sẽ xuất dòng bắt đầu bằng
`[AI LEARNING JOB ERROR]` kèm đúng loại lỗi và nội dung lỗi.

## Kiểm thử đã thực hiện

- Dữ liệu đầu vào: 1.000 khách hàng, gồm 46 giá trị `personality` dạng object.
- Kết quả: lưu thành công 1.000/1.000 khách hàng.
- Số object bị ghi nguyên dạng vào SQLite: 0.
- `PRAGMA integrity_check`: `ok`.
- Thử ép lỗi giữa giao dịch: rollback về 0 dòng và database không bị khóa.
- Dataset đã xác nhận: trả đủ audit của 26 trường.
- Dataset chưa hoàn thành: hiển thị đúng trạng thái chưa có kết quả AI.
- Dataset đã học nhưng chưa xác nhận: hiển thị đúng trạng thái chờ xác nhận audit.
- Truy cập chéo tài khoản bằng `upload_id`: bị chặn.
- Pytrends thành công: trả đủ `trend_score`, `latest_score`, `peak_score`.
- Bấm lại trong 15 phút: dùng cache, không gửi thêm yêu cầu Google.
- Pytrends trả 429: không crash; tự chuyển sang Google Trends RSS.
- Chưa cài Pytrends: thông báo đúng và vẫn thử nguồn RSS.
- Cả hai nguồn lỗi: trả bảng rỗng ổn định và thông báo tiếng Việt, không trả
  thành công giả.
- Tạo doanh nghiệp khi không có `ADMIN_BOOTSTRAP_CODE`: biểu mẫu và backend
  cùng chấp nhận, sau đó sinh mã tham gia cho nhân viên.
- Bộ kiểm thử hồi quy: 11/11 bài kiểm thử đạt.
- JavaScript, Python và cấu trúc HTML: kiểm tra cú pháp thành công.
