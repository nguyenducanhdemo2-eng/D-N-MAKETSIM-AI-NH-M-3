import pandas as pd

# Dữ liệu bảng WBS chi tiết cho người mới
data = [
    (1, "1. Môi trường", "CẢ NHÓM", "N/A", "Cài đặt Python 3.10+ và IDE VS Code", "Tải Python từ python.org (tích Add to PATH). Tải VS Code cài Extension Python. Output: Mở CMD gõ python --version lên từ 3.10+."),
    (2, "1. Môi trường", "CẢ NHÓM", "N/A", "Tạo cấu trúc thư mục dự án chuẩn", "Tạo folder gốc ITA108_DuAn1/. Bên trong tạo 3 folder: data/ (chứa CSV), src/ (chứa code xử lý), ui/ (chứa giao diện)."),
    (3, "1. Môi trường", "CẢ NHÓM", "N/A", "Tạo các file code gốc (Tránh lỗi import)", "Tạo file trống: main.py ở thư mục gốc; src/db_manager.py (xử lý DB); src/ai_core.py (xử lý AI). Giúp cấu trúc rõ ràng ngay từ đầu."),
    (4, "1. Môi trường", "CẢ NHÓM", "N/A", "Cài đặt các thư viện lõi (Đợt 1)", "Mở Terminal trong VS Code gõ: pip install pandas scikit-learn chromadb ollama openpyxl matplotlib. Output: Báo Successfully installed."),
    (5, "2. Vector DB", "Data Engineer", "test_chroma.py", "Test kết nối ChromaDB cơ bản", "Import chromadb. Tạo client lưu xuống ổ cứng: client = chromadb.PersistentClient(path='./chroma_data'). Output: Chạy không lỗi, tạo ra folder chroma_data/."),
    (6, "2. Vector DB", "Data Engineer", "db_manager.py", "Viết hàm tạo Collection (Kho dữ liệu)", "Viết hàm create_or_get_collection(). Dùng lệnh client.get_or_create_collection(name='khach_hang_doanh_nghiep'). Đây là bảng lưu data khách hàng."),
    (7, "2. Vector DB", "AI/ML Dev", "test_embed.py", "Test tính năng nhúng từ (Embedding)", "Dùng mô hình 'all-MiniLM-L6-v2' của ChromaDB để biến 1 câu text thành vector số. Output: In ra mảng khoảng 384 con số."),
    (8, "2. Vector DB", "AI/ML Dev", "db_manager.py", "Đọc dữ liệu từ file Excel/CSV", "Viết hàm load_data_from_file(). Dùng pandas (pd.read_csv / read_excel) đọc file thô từ folder data/. Output: In ra 5 dòng đầu tiên (df.head()) để kiểm tra."),
    (9, "2. Vector DB", "AI/ML & Data", "db_manager.py", "Nạp dữ liệu vào ChromaDB (Vectorize)", "Dùng vòng lặp for index, row in df.iterrows(): lấy từng dòng khách hàng, gộp thành câu text mô tả rồi đẩy vào DB bằng lệnh collection.add()."),
    (10, "2. Vector DB", "Data Engineer", "db_manager.py", "Viết hàm Tìm kiếm theo Ngữ nghĩa (Search)", "Viết hàm search_customers(query_text). Dùng lệnh collection.query(query_texts=[query_text], n_results=5). Output: Nhập 'khách thích cafe' -> Trả về 5 người giống nhất."),
    (11, "3. Local AI", "AI/ML Dev", "N/A", "Cài đặt Ollama & Tải mô hình Qwen", "Vào ollama.com tải Ollama. Mở CMD gõ: ollama run qwen:0.5b (máy yếu) hoặc qwen:1.8b. Output: Có thể chat trực tiếp với AI trên CMD."),
    (12, "3. Local AI", "AI/ML Dev", "test_ollama.py", "Test gọi Ollama từ code Python", "Import ollama. Dùng lệnh response = ollama.chat(model='qwen:0.5b', messages=[{'role': 'user', 'content': 'Xin chào'}]). Output: In ra câu trả lời của AI trên VS Code."),
    (13, "3. Local AI", "AI/ML Dev", "ai_core.py", "Ép AI trả về định dạng chuẩn JSON", "Thêm tham số format='json' và viết prompt yêu cầu AI: 'Chỉ trả về JSON cấu trúc {\"score\": 80, \"sentiment\": \"Positive\"}'. Giúp Python dễ xử lý không lỗi."),
    (14, "4. AI Analyst", "Product", "prompts.txt", "Soạn thảo Câu lệnh (Prompt) Phân tích SWOT", "Viết mẫu prompt: 'Bạn là Chuyên gia Marketing. Dưới đây là chiến dịch Sale: {scenario} và tệp khách hàng {data}. Hãy phân tích SWOT và chấm điểm...'."),
    (15, "4. AI Analyst", "AI/ML Dev", "ai_core.py", "Viết hàm RAG (Retrieval-Augmented Generation)", "Viết hàm analyze_campaign(scenario). Bước 1: Gọi hàm search lấy 10 khách hàng liên quan nhất. Bước 2: Ghép kịch bản + 10 khách vào Prompt rồi gửi cho Qwen."),
    (16, "4. AI Analyst", "AI/ML Dev", "ai_core.py", "Test hàm Phân tích chiến dịch", "Gọi thử analyze_campaign('Giảm giá 30% cho sinh viên'). Output: Trả về dict Python có đủ key: strengths, weaknesses, summary, star_rating."),
    (17, "5. Sinh Khách", "Product", "prompts.txt", "Soạn Prompt Tạo tệp Khách hàng giả định", "Viết prompt yêu cầu AI: 'Tạo danh sách 10 khách hàng giả định thích cafe, gồm: Tên, Tuổi, Thu nhập, Nỗi đau. Trả về JSON Array'."),
    (18, "5. Sinh Khách", "Data Engineer", "db_manager.py", "Kéo toàn bộ dữ liệu làm vật liệu phân cụm", "Viết hàm get_all_customers_for_clustering(). Dùng collection.get() lấy toàn bộ vector và metadata của 10.000 khách từ ChromaDB ra bộ nhớ RAM."),
    (19, "5. Sinh Khách", "AI/ML Dev", "ai_core.py", "Gom nhóm K-Means (Thuật toán Học máy)", "Import KMeans từ sklearn.cluster. Khởi tạo kmeans = KMeans(n_clusters=100). Dùng .fit_predict(vectors) chia 10.000 khách thành 100 cụm tâm lý giống nhau."),
    (20, "5. Sinh Khách", "Data Engineer", "db_manager.py", "Tính tâm cụm & Lưu 100 nhóm đại diện", "Với mỗi cụm, chọn ra 1 khách hàng gần tâm cụm nhất làm đại diện. Lưu 100 người này kèm số lượng thành viên mỗi cụm vào file data/cohorts_temp.csv."),
    (21, "6. Mô phỏng", "AI/ML Dev", "test_async.py", "Học & Test lập trình Bất đồng bộ (Asyncio)", "Import asyncio. Viết hàm async có await asyncio.sleep(1). Dùng asyncio.gather() chạy 5 hàm cùng lúc. Output: 5 câu Hello in ra gần như đồng thời sau 1s."),
    (22, "6. Mô phỏng", "AI/ML Dev", "ai_core.py", "Code hàm Mô phỏng phản ứng 1 người", "Viết hàm async def simulate_one_persona(persona, scenario). Gửi profile 1 người và chiến dịch cho Ollama. Yêu cầu trả về: Quyết định (MUA/KHÔNG MUA/LƯỢNG LỰ) & Lý do."),
    (23, "6. Mô phỏng", "AI/ML Dev", "ai_core.py", "Chạy Mô phỏng Đa luồng cho 100 nhóm", "Viết hàm async def run_mass_simulation(). Tạo list 100 tasks từ hàm bước 22 và chạy đồng thời bằng asyncio.gather(*tasks). Output: Nhận mảng 100 kết quả JSON cực nhanh."),
    (24, "6. Mô phỏng", "Data Engineer", "ai_core.py", "Tính toán Nội suy ra quy mô 10.000 người", "Duyệt qua 100 kết quả. Nếu Nhóm 1 (đại diện 150 người) quyết định MUA -> Cộng 150 vào total_buy. Làm tương tự để suy ra số liệu tổng trên 10.000 người."),
    (25, "6. Mô phỏng", "Data Engineer", "db_manager.py", "Lưu Báo cáo tổng kết cuối cùng", "Tính % Mua/Không mua. Lưu tổng kết này cùng chi tiết 100 nhóm vào file Excel data/Bao_Cao_Cuoi.xlsx (dùng pandas.to_excel) để làm minh chứng báo cáo."),
    (26, "7. Chat 1-1", "Product", "prompts.txt", "Soạn Prompt cho tính năng Roleplay Chat", "Viết prompt nhập vai: 'Bạn là {tên}, 35t, vừa từ chối mua Sale vì lý do: {lý_do}. Hãy trả lời tin nhắn của nhân viên tư vấn tự nhiên, đúng tính cách'."),
    (27, "7. Chat 1-1", "AI/ML Dev", "ai_core.py", "Code tính năng Trò chuyện dòng chảy (Stream)", "Viết hàm chat_with_persona_stream(). Khi gọi ollama.chat đặt stream=True. Dùng vòng lặp for chunk in response và yield để tạo hiệu ứng chữ hiện ra từng chữ như ChatGPT."),
    (28, "7. Chat 1-1", "AI/ML Dev", "ai_core.py", "Quản lý Bộ nhớ Lịch sử hội thoại (Chat History)", "Tạo list chat_history = []. Mỗi khi user hỏi append role user; AI trả lời append role assistant. Gửi toàn bộ list này mỗi lần gọi để AI nhớ ngữ cảnh cũ."),
    (29, "8. Giao diện", "Product", "test_ui.py", "Test tạo cửa sổ giao diện Tkinter cơ bản", "Import tkinter as tk. Tạo cửa sổ root = tk.Tk(), geometry('1000x600'). Thêm 1 nút bấm tk.Button(text='Test'). Output: Cửa sổ hiện lên chạy mượt."),
    (30, "8. Giao diện", "Product", "ui/main_window.py", "Dựng Bố cục App 3 Phân vùng (3 Columns)", "Dùng tk.Frame và grid/pack chia màn hình thành 3 cột: Cột 1 (Nhập chiến dịch Sale); Cột 2 (Hiển thị biểu đồ & SWOT); Cột 3 (Khung Chat 1-1 với khách)."),
    (31, "8. Giao diện", "Product", "ui/main_window.py", "Dựng Form nhập liệu & Nút kích hoạt", "Ở Cột 1, thêm Label, 1 ô văn bản lớn tk.Text(height=10) để gõ nội dung Sale, và nút bấm tk.Button(text='Bắt đầu Phân tích & Mô phỏng', bg='green')."),
    (32, "8. Giao diện", "Product", "ui/main_window.py", "Dựng vùng hiển thị báo cáo SWOT (JSON)", "Ở phần trên Cột 2, tạo các LabelFrame 'Ưu điểm', 'Nhược điểm'. Bên trong dùng Listbox hoặc Text (khóa Read-only) để in đẹp danh sách lấy từ AI."),
    (33, "8. Giao diện", "Product", "test_plot.py", "Test vẽ Biểu đồ tròn với Matplotlib", "Import matplotlib.pyplot as plt. Vẽ test: plt.pie([60, 30, 10], labels=['Mua', 'Không', 'Phân vân'], autopct='%1.1f%%'). Output: Hiện cửa sổ biểu đồ đẹp."),
    (34, "8. Giao diện", "Product", "ui/main_window.py", "Nhúng (Embed) Biểu đồ Matplotlib vào Tkinter", "Import FigureCanvasTkAgg. Vẽ biểu đồ lên Figure, sau đó đưa canvas đó chui vào nằm gọn phía dưới Cột 2 của Tkinter bằng lệnh canvas.get_tk_widget().pack()."),
    (35, "8. Giao diện", "Product", "ui/main_window.py", "Dựng khung Chat trực tiếp (Cột 3)", "Tạo 1 tk.Text lớn ở trên để hiện lịch sử chat (Read-only). Phía dưới tạo tk.Entry (ô nhập tin) và nút Gửi. Thêm Combobox để chọn Persona muốn chat."),
    (36, "9. Ráp nối", "CẢ NHÓM", "main.py", "Ghép Nút 'Phân tích' với Logic AI & UI", "Bấm nút ở bước 31 -> Gọi hàm xử lý: Hiện 'Đang xử lý...' -> Gọi analyze_campaign() từ ai_core.py -> Lấy JSON trả về gán vào các ô văn bản SWOT ở bước 32."),
    (37, "9. Ráp nối", "CẢ NHÓM", "main.py", "Ghép Biểu đồ với Kết quả Mô phỏng 100 nhóm", "Ngay sau khi SWOT xong -> Gọi tiếp hàm run_mass_simulation() -> Lấy 3 con số % (Mua, Không, Lưỡng lự) -> Truyền vào hàm vẽ -> canvas.draw() để cập nhật UI."),
    (38, "9. Ráp nối", "CẢ NHÓM", "main.py", "Ghép tính năng Chat 1-1 với Khung UI", "Chọn 1 Khách từ Menu và bấm Gửi -> Lấy text từ Entry -> Gọi chat_with_persona_stream() -> Dùng root.after() hoặc Threading chèn từng chữ AI trả lời vào ô Text chat."),
    (39, "10. Fix Bug", "CẢ NHÓM", "N/A", "Bẫy lỗi Crash App (Fault Tolerance)", "Dùng try...except bao quanh các hàm gọi AI/Đọc file. Nếu Ollama chưa bật hoặc lỗi, dùng messagebox.showerror() hiện thông báo lịch sự thay vì văng tắt app."),
    (40, "10. Fix Bug", "CẢ NHÓM", "N/A", "Kiểm thử Toàn bộ Hệ thống (End-to-End Test)", "Nạp file Excel mới. Nhập 1 chiến dịch ngớ ngẩn (vd: Giảm 1% cho đơn 1 tỷ). Output kỳ vọng: AI phải 'chê' chiến dịch này, tỷ lệ KHÔNG MUA trên biểu đồ >90%.")
]

# Tạo DataFrame
columns = ["STT", "GIAI ĐOẠN", "PHÂN VÙNG (ROLE)", "TÊN FILE CODE", "VIỆC CẦN LÀM (MICRO-TASK - CHI TIẾT)", "MÔ TẢ & ĐẦU RA KỲ VỌNG (HƯỚNG DẪN CẨM TAY CHỈ VIỆC)"]
df = pd.DataFrame(data, columns=columns)

# Xuất ra file Excel
file_name = "WBS_Du_An_1_Chi_Tiet.xlsx"
with pd.ExcelWriter(file_name, engine='openpyxl') as writer:
    df.to_excel(writer, index=False, sheet_name="WBS_Chi_Tiet")
    
    # Căn chỉnh độ rộng cột tự động cho đẹp
    worksheet = writer.sheets["WBS_Chi_Tiet"]
    worksheet.column_dimensions['A'].width = 6
    worksheet.column_dimensions['B'].width = 15
    worksheet.column_dimensions['C'].width = 15
    worksheet.column_dimensions['D'].width = 18
    worksheet.column_dimensions['E'].width = 45
    worksheet.column_dimensions['F'].width = 65

print(f"🎉 Đã xuất bảng WBS chi tiết ra file: {file_name} thành công!")