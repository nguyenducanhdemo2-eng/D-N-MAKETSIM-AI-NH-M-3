# ==============================================================================
# CONFIG.PY - Cấu hình trung tâm cho MarketSim AI
# ==============================================================================

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "marketsim.db")

# --------------------------------------------------------------------------
# BƯỚC 1 - THU THẬP DỮ LIỆU
# --------------------------------------------------------------------------
# Từ khóa để lấy xu hướng tìm kiếm Google Trends. Sửa lại theo ngành hàng của bạn.
TREND_KEYWORDS = ["thời trang", "công nghệ", "ẩm thực", "du lịch", "làm đẹp"]

# Danh sách trang tin để cào tiêu đề nóng trong ngày (BeautifulSoup)
NEWS_URLS = [
    "https://vnexpress.net/kinh-doanh",
    "https://cafef.vn",
]

TRENDS_TIMEFRAME = "now 7-d"   # 7 ngày gần nhất
TRENDS_GEO = "VN"              # Việt Nam

# --------------------------------------------------------------------------
# BƯỚC 2 - PHÂN CỤM TÂM LÝ KHÁCH HÀNG (K-MEANS)
# --------------------------------------------------------------------------
NUM_CLUSTERS = 3       # 3 nhóm tâm lý khách hàng chính, theo đúng kiến trúc đã mô tả
RANDOM_STATE = 42

# --------------------------------------------------------------------------
# BƯỚC 3 - AI CORE: MÔ HÌNH NHẬP VAI (QWEN QUA OLLAMA)
# --------------------------------------------------------------------------
OLLAMA_HOST = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5:7b"       # đổi tên model nếu bạn pull bản khác (vd: qwen2.5:14b)
NUM_PERSONAS_PER_CLUSTER = 10     # 10 persona/nhóm x 3 nhóm = 30 AI khách hàng
MAX_CONCURRENT_REQUESTS = 8       # số request Ollama chạy song song tối đa (tùy VRAM RTX 3060)
MAX_SIMULATED_PERSONAS = 100      # giới hạn tổng số persona được mô phỏng trong 1 lần chạy
MAX_UPLOAD_BYTES = 1_000_000_000  # 1GB, hạn chế file upload quá lớn gây treo trình duyệt / server
REQUEST_TIMEOUT_SEC = 120        # tăng lên 120s vì model 7B chạy CPU/máy yếu có thể mất 30-90s/câu trả lời

# Tính cách mẫu, được ghép ngẫu nhiên vào mỗi persona để tạo sự đa dạng
PERSONALITY_TRAITS = [
    "thận trọng, hay so sánh giá trước khi mua",
    "bốc đồng, dễ bị thu hút bởi khuyến mãi",
    "trung thành với thương hiệu quen thuộc",
    "quan tâm đến yếu tố bền vững, thân thiện môi trường",
    "nhạy cảm về giá, luôn tìm ưu đãi tốt nhất",
    "thích trải nghiệm mới, sẵn sàng thử sản phẩm lạ",
    "hoài nghi quảng cáo, cần bằng chứng cụ thể",
    "bị ảnh hưởng mạnh bởi đánh giá của người khác",
]

# --------------------------------------------------------------------------
# BƯỚC 4 - XUẤT KẾT QUẢ & GIAO DIỆN BÁO CÁO
# --------------------------------------------------------------------------
GUI_TITLE = "MarketSim AI — Báo cáo mô phỏng khách hàng ảo"
GUI_WINDOW_SIZE = "1000x700"
