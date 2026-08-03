# ==============================================================================
# WEB_APP.PY - GIAO DIỆN WEB HOÀN CHỈNH (STREAMLIT DASHBOARD)
# Bản nâng cấp giao diện v3:
#   - Sidebar màu xanh navy tối (giống phong cách dashboard chuyên nghiệp)
#   - Công tắc bật/tắt Chế độ Tối (Dark Mode) cho toàn bộ nội dung chính
#   - Banner gradient, badge màu theo cảm xúc, thẻ bo góc, biểu đồ donut...
# KHÔNG đổi bất kỳ logic backend nào so với bản trước.
#
# Hội tụ đầy đủ các tính năng của dự án MarketSim AI:
#   [1] Mô phỏng phản ứng khách hàng đa luồng + Phân tích SWOT
#   [2] Nạp & tìm kiếm dữ liệu khách hàng (upload CSV/XLSX qua web) + Phân cụm K-Means
#   [3] Trò chuyện nhập vai 1-1 với TỪNG khách hàng ảo cụ thể (Roleplay Chat)
#   [+] Health-check Ollama, bẫy lỗi toàn diện chống văng app, lịch sử chiến dịch
# ==============================================================================

import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import os
import sys
import inspect
import importlib

# Ensure UTF-8 output on Windows to avoid 'charmap' codec errors when
# printing or logging Unicode characters (sets PYTHONUTF8 and reconfigures
# stdout/stderr where supported).
os.environ.setdefault("PYTHONUTF8", "1")
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
importlib.invalidate_caches()


def _safe_reload(module):
    """Thử nạp lại module để lấy code mới nhất khi Streamlit tự chạy lại script.
    Trên 1 số máy Windows (đặc biệt khi đường dẫn thư mục có ký tự đặc biệt),
    importlib.reload() có thể không tìm lại được 'spec' của module và raise
    ModuleNotFoundError dù file hoàn toàn hợp lệ. Trước đây lỗi này làm SẬP
    TOÀN BỘ app -- giờ chỉ cảnh báo và dùng tạm bản module đã nạp sẵn."""
    try:
        importlib.reload(module)
    except Exception as e:
        st.warning(
            f"⚠ Không thể tự động nạp lại module '{module.__name__}' ({e}). "
            f"Ứng dụng vẫn chạy với bản đã nạp trước đó. Nếu bạn vừa sửa file "
            f"'{module.__name__}.py', hãy dừng hẳn Streamlit (Ctrl+C) rồi chạy lại "
            f"để chắc chắn dùng đúng bản mới nhất."
        )
    return module

try:
    from config import DB_PATH, OLLAMA_MODEL, OLLAMA_HOST, NUM_CLUSTERS
except ImportError:
    DB_PATH = "marketsim.db"
    OLLAMA_MODEL = "ggml-gpt4o-mini"
    OLLAMA_HOST = "http://localhost:11434"
    NUM_CLUSTERS = 5

import data_collector as data_collector_module
_safe_reload(data_collector_module)
collect_all = data_collector_module.collect_all
load_uploaded_dataframe = data_collector_module.load_uploaded_dataframe
build_ai_learning_report = data_collector_module.build_ai_learning_report

try:
    from config import MAX_SIMULATED_PERSONAS, MAX_UPLOAD_BYTES
except ImportError:
    MAX_SIMULATED_PERSONAS = 100
    MAX_UPLOAD_BYTES = 1_000_000_000
from clustering import cluster_customer_psychology
from persona_simulator import (
    generate_personas, simulate_marketing_scenario, chat_with_ollama,
    chat_with_persona, check_ollama_connection,
)
import database as database_module
_safe_reload(database_module)
save_simulation = getattr(database_module, 'save_simulation', None)
save_uploaded_dataset = getattr(database_module, 'save_uploaded_dataset', None)
get_uploaded_dataset_count = getattr(database_module, 'get_uploaded_dataset_count', None)
save_learning_memory = getattr(database_module, 'save_learning_memory', None)
get_ai_learning_snapshot = getattr(database_module, 'get_ai_learning_snapshot', None)
init_db = getattr(database_module, 'init_db', None)
reset_db = getattr(database_module, 'reset_db', None)
get_all_scenarios = getattr(database_module, 'get_all_scenarios', None)
get_scenario_by_id = getattr(database_module, 'get_scenario_by_id', None)
get_results_by_scenario = getattr(database_module, 'get_results_by_scenario', None)
create_user = getattr(database_module, 'create_user', None)
verify_user = getattr(database_module, 'verify_user', None)

# Đảm bảo DB & bảng đã tồn tại ngay khi mở app (KHÔNG xoá dữ liệu cũ)
init_db()

# Cấu hình trang Web
st.set_page_config(
    page_title="MarketSim AI — Web Dashboard",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==============================================================================
# BẢNG MÀU
# ĐÃ BỎ công tắc Sáng/Tối theo yêu cầu — toàn bộ giao diện (sidebar + nội dung
# chính) giờ dùng CỐ ĐỊNH 1 bảng màu Tối (navy), không còn LIGHT nữa.
# ==============================================================================
SIDEBAR = {
    "bg_from": "#0B2545", "bg_to": "#132F58",
    "text": "#EAF0FB", "muted": "#8FA3C7",
    "card_bg": "rgba(255,255,255,0.06)", "border": "rgba(255,255,255,0.10)",
    "accent": "#2D82B7", "accent2": "#5AA6D6",
    "success": "#33C481", "success_bg": "rgba(51,196,129,0.15)",
    "warning": "#E0A542", "warning_bg": "rgba(224,165,66,0.15)",
    "error": "#E2635A", "error_bg": "rgba(226,99,90,0.15)",
}

DARK = {
    "bg": "#0B2545", "card_bg": "#132F58", "text": "#EAF0FB", "muted": "#8FA3C7",
    "border": "#22406E", "accent": "#2D82B7",
    "positive": "#33C481", "positive_bg": "rgba(51,196,129,0.15)",
    "negative": "#E2635A", "negative_bg": "rgba(226,99,90,0.15)",
    "neutral": "#E0A542", "neutral_bg": "rgba(224,165,66,0.15)",
    "chip_bg": "rgba(45,130,183,0.20)", "chip_text": "#BEE0F5",
    "score_track": "rgba(255,255,255,0.08)",
}
PAL = DARK

# ==============================================================================
# CSS TUỲ CHỈNH (chỉ ảnh hưởng thẩm mỹ, không đụng logic).
# LƯU Ý: 1 vài widget gốc của Streamlit (vùng chọn dropdown, bảng dữ liệu...)
# là "best effort" - nếu phiên bản Streamlit khác đi chút, cùng lắm 1-2 chi
# tiết nhỏ không lên đúng màu, KHÔNG ảnh hưởng chức năng. Bạn có thể kết hợp
# thêm nút Light/Dark có sẵn của Streamlit ở menu ☰ > Settings nếu cần.
# ==============================================================================
st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"] {{
    font-family: 'Be Vietnam Pro', sans-serif;
}}

/* ---------- NỀN & MÀU CHỮ TOÀN TRANG (theo Chế độ Sáng/Tối) ---------- */
[data-testid="stAppViewContainer"] {{ background-color: {PAL['bg']}; }}
[data-testid="stHeader"] {{ background-color: transparent; }}
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
[data-testid="stMarkdownContainer"] span {{ color: {PAL['text']}; }}
h1, h2, h3, h4, h5, h6 {{ color: {PAL['text']}; }}
hr {{ border-color: {PAL['border']}; }}
[data-testid="stCaptionContainer"] {{ color: {PAL['muted']}; }}

/* Banner tiêu đề gradient (giữ nguyên ở cả 2 chế độ) */
.msai-hero {{
    background: linear-gradient(135deg, #0B2545 0%, #1B4F91 100%);
    padding: 30px 36px;
    border-radius: 20px;
    margin-bottom: 26px;
    box-shadow: 0 10px 30px rgba(11, 37, 69, 0.28);
}}
.msai-hero h1 {{ color: #ffffff !important; margin: 0; font-size: 30px; font-weight: 800; }}
.msai-hero p {{ color: rgba(255,255,255,0.9); margin: 8px 0 0 0; font-size: 15px; }}

/* Tiêu đề mục có gạch màu bên trái */
.msai-section-title {{
    font-size: 19px; font-weight: 700; color: {PAL['text']};
    border-left: 5px solid {PAL['accent']};
    padding-left: 12px; margin: 6px 0 14px 0;
}}

/* Badge cảm xúc & chip từ khóa */
.msai-badge {{ display:inline-block; padding:5px 14px; border-radius:999px; font-weight:700; font-size:13px; }}
.msai-chip {{
    display:inline-block; background:{PAL['chip_bg']}; color:{PAL['chip_text']};
    padding:5px 12px; border-radius:999px; font-size:13px; margin:3px 4px 3px 0; font-weight:600;
}}

/* Thanh điểm số gradient */
.msai-score-track {{ background:{PAL['score_track']}; border-radius:8px; height:10px; width:100%; overflow:hidden; }}
.msai-score-fill {{ height:100%; background:linear-gradient(90deg,#1B4F91,#2D82B7); border-radius:8px; }}

/* Nút bấm bo tròn dạng viên thuốc, nền gradient nổi bật, chữ trắng đậm luôn rõ
   (mặc định - vùng nội dung chính). Sửa lỗi chữ "biến mất" trên nền trắng cũ. */
div.stButton > button, div.stFormSubmitButton > button {{
    border-radius: 999px !important;
    font-weight: 700 !important;
    background: linear-gradient(90deg, #1B4F91, #2D82B7) !important;
    border: none !important;
    box-shadow: 0 4px 14px rgba(11, 37, 69, 0.3);
    transition: transform 0.15s ease, box-shadow 0.15s ease;
}}
div.stButton > button p, div.stFormSubmitButton > button p,
div.stButton > button span, div.stFormSubmitButton > button span,
div.stButton > button div, div.stFormSubmitButton > button div {{
    color: #FFFFFF !important;
}}
div.stButton > button:hover, div.stFormSubmitButton > button:hover {{
    transform: translateY(-1px);
    box-shadow: 0 6px 20px rgba(11, 37, 69, 0.45);
}}

/* Tab dạng viên thuốc (pill) bo tròn, có màu khi active.
   Streamlit đổi cấu trúc DOM của tab qua từng phiên bản, nên mình liệt kê CÙNG LÚC
   mọi kiểu selector đã từng được dùng (class .stTabs, data-testid, data-baseweb,
   role="tab") - cái nào khớp với bản Streamlit đang chạy sẽ tự áp dụng. */
.stTabs [data-baseweb="tab-list"],
[data-testid="stTabs"] [data-baseweb="tab-list"],
[data-testid="stTabs"] [role="tablist"] {{
    gap: 10px !important;
    border-bottom: none !important;
}}

.stTabs [data-baseweb="tab"],
.stTabs [data-testid="stTab"],
.stTabs [role="tab"],
[data-testid="stTabs"] [data-baseweb="tab"],
[data-testid="stTabs"] [data-testid="stTab"],
[data-testid="stTabs"] [role="tab"],
[data-testid="stTab"] {{
    height: auto !important;
    background-color: {PAL['card_bg']} !important;
    border: 1px solid {PAL['border']} !important;
    border-radius: 999px !important;
    padding: 10px 22px !important;
    margin: 0 !important;
    font-size: 15px !important;
    font-weight: 700 !important;
    transition: all 0.15s ease !important;
}}
.stTabs [data-baseweb="tab"] p, .stTabs [data-baseweb="tab"] span, .stTabs [data-baseweb="tab"] div,
.stTabs [data-testid="stTab"] p, .stTabs [data-testid="stTab"] span, .stTabs [data-testid="stTab"] div,
[data-testid="stTabs"] [data-baseweb="tab"] p, [data-testid="stTabs"] [data-baseweb="tab"] span,
[data-testid="stTabs"] [data-testid="stTab"] p, [data-testid="stTabs"] [data-testid="stTab"] span,
[data-testid="stTab"] p, [data-testid="stTab"] span {{
    color:{PAL['muted']} !important; font-weight:700 !important;
}}

.stTabs [data-baseweb="tab"]:hover, .stTabs [data-testid="stTab"]:hover,
[data-testid="stTabs"] [data-baseweb="tab"]:hover, [data-testid="stTab"]:hover {{
    border-color:{PAL['accent']} !important;
}}
.stTabs [data-baseweb="tab"]:hover p, .stTabs [data-baseweb="tab"]:hover span,
[data-testid="stTab"]:hover p, [data-testid="stTab"]:hover span {{
    color:{PAL['accent']} !important;
}}

.stTabs [data-baseweb="tab"][aria-selected="true"],
.stTabs [data-testid="stTab"][aria-selected="true"],
[data-testid="stTabs"] [data-baseweb="tab"][aria-selected="true"],
[data-testid="stTabs"] [data-testid="stTab"][aria-selected="true"],
[data-testid="stTab"][aria-selected="true"] {{
    background: linear-gradient(90deg, #1B4F91, #2D82B7) !important;
    border-color: transparent !important;
    box-shadow: 0 4px 14px rgba(11,37,69,0.35) !important;
}}
.stTabs [data-baseweb="tab"][aria-selected="true"] p,
.stTabs [data-baseweb="tab"][aria-selected="true"] span,
.stTabs [data-baseweb="tab"][aria-selected="true"] div,
.stTabs [data-testid="stTab"][aria-selected="true"] p,
.stTabs [data-testid="stTab"][aria-selected="true"] span,
[data-testid="stTab"][aria-selected="true"] p,
[data-testid="stTab"][aria-selected="true"] span {{
    color:#FFFFFF !important;
}}

.stTabs [data-baseweb="tab-highlight"],
[data-testid="stTabs"] [data-baseweb="tab-highlight"] {{ display:none !important; }}
.stTabs [data-baseweb="tab-border"] {{ display:none !important; }}

/* Khung info/success/warning/error mặc định (chỉ vùng nội dung chính) */
[data-testid="stAlert"] {{
    border-radius: 12px; background-color:{PAL['card_bg']}; border:1px solid {PAL['border']};
}}
[data-testid="stAlert"] p {{ color:{PAL['text']} !important; }}

/* Ô nhập liệu / dropdown */
[data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea,
[data-baseweb="select"] > div, [data-baseweb="input"] {{
    background-color:{PAL['card_bg']} !important; color:{PAL['text']} !important;
    border-color:{PAL['border']} !important;
}}

/* Ô upload file (vùng nội dung chính) */
[data-testid="stFileUploaderDropzone"] {{ background-color:{PAL['card_bg']}; border:1px dashed {PAL['border']}; }}

/* Khung chat */
[data-testid="stChatMessage"] {{ background-color:{PAL['card_bg']}; border:1px solid {PAL['border']}; border-radius:12px; }}

/* Bảng dữ liệu */
[data-testid="stDataFrame"] {{ border:1px solid {PAL['border']}; border-radius:12px; overflow:hidden; }}

/* Metric */
[data-testid="stMetric"] {{
    background-color:{PAL['card_bg']}; padding:10px 14px; border-radius:12px; border:1px solid {PAL['border']};
}}

/* Expander */
[data-testid="stExpander"] {{ background-color:{PAL['card_bg']}; border:1px solid {PAL['border']}; border-radius:12px; }}

/* Container bo góc có viền (st.container(border=True)) - best effort */
[data-testid="stVerticalBlockBorderWrapper"] {{
    background-color:{PAL['card_bg']}; border-color:{PAL['border']} !important; border-radius:14px;
}}

/* ================================================================
   SIDEBAR: LUÔN mang tông xanh navy tối, mát mắt (không đổi theo toggle)
   ================================================================ */
[data-testid="stSidebar"] {{
    background: linear-gradient(180deg, {SIDEBAR['bg_from']} 0%, {SIDEBAR['bg_to']} 100%);
}}
[data-testid="stSidebar"] * {{ color: {SIDEBAR['text']}; }}
[data-testid="stSidebar"] hr {{ border-color:{SIDEBAR['border']}; }}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {{ color:{SIDEBAR['muted']} !important; }}

.msai-sidebar-brand {{
    background: linear-gradient(90deg, {SIDEBAR['accent']}, {SIDEBAR['accent2']});
    padding: 14px 16px; border-radius: 14px; margin-bottom: 18px; text-align:center;
}}
.msai-sidebar-brand span {{ color: white !important; font-weight: 800; font-size: 18px; }}

.msai-sidebar-label {{
    color:{SIDEBAR['muted']}; text-transform:uppercase; letter-spacing:0.8px;
    font-size:12px; font-weight:700; margin: 4px 0 10px 0;
}}

.msai-sidebar-chip {{
    display:inline-block; background:{SIDEBAR['card_bg']}; color:{SIDEBAR['accent2']};
    padding:6px 14px; border-radius:999px; font-size:13px; font-weight:700;
    border:1px solid {SIDEBAR['border']};
}}

.msai-sidebar-status {{
    padding:12px 14px; border-radius:12px; font-size:13.5px; font-weight:600; line-height:1.5; margin:6px 0;
}}

/* Ô upload trong sidebar */
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {{
    background-color:{SIDEBAR['card_bg']}; border:1px dashed {SIDEBAR['border']};
}}
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] > * {{ color:{SIDEBAR['text']} !important; }}
/* Nút "Browse files/Upload" bên trong ô tải file - đổi sang viên thuốc gradient
   để luôn đọc được chữ (bản cũ bị nền trắng + chữ sáng đè lên nên gần như vô hình) */
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button {{
    background: linear-gradient(90deg, {SIDEBAR['accent']}, {SIDEBAR['accent2']}) !important;
    border: none !important;
    border-radius: 999px !important;
    font-weight: 700 !important;
}}
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button p,
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button span,
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button div {{
    color: #FFFFFF !important;
}}

/* Nút bấm trong sidebar: kiểu "kính mờ" thay vì gradient tím rực */
[data-testid="stSidebar"] div.stButton > button {{
    background: rgba(255,255,255,0.06) !important;
    color: {SIDEBAR['text']} !important;
    border: 1px solid {SIDEBAR['border']} !important;
    box-shadow: none !important;
    border-radius: 12px !important;
}}
[data-testid="stSidebar"] div.stButton > button:hover {{
    background: rgba(139,124,255,0.25) !important;
    border-color: {SIDEBAR['accent']} !important;
}}

/* ================================================================
   MENU ĐIỀU HƯỚNG SIDEBAR (st.radio "hoá trang" thành nav-list, thay
   cho pill-tab ngang cũ) — best effort: BaseWeb/Streamlit có thể đổi
   cấu trúc DOM giữa các phiên bản, :has() cần trình duyệt tương đối
   mới (Chrome/Edge/Safari bản gần đây); nếu không khớp, radio vẫn
   hoạt động bình thường, chỉ mất phần tô nổi bật mục đang chọn.
   ================================================================ */
[data-testid="stSidebar"] div[data-testid="stRadio"] > div[role="radiogroup"] {{
    gap: 2px !important;
}}
[data-testid="stSidebar"] div[data-testid="stRadio"] label {{
    width: 100%;
    padding: 9px 10px !important;
    border-radius: 8px !important;
    margin: 0 !important;
    border-left: 2px solid transparent;
}}
[data-testid="stSidebar"] div[data-testid="stRadio"] label:hover {{
    background: rgba(255,255,255,0.06);
}}
[data-testid="stSidebar"] div[data-testid="stRadio"] label > div:first-child {{
    display: none !important; /* ẩn chấm tròn radio mặc định */
}}
[data-testid="stSidebar"] div[data-testid="stRadio"] label > div:last-child {{
    font-size: 13.5px !important;
    color: {SIDEBAR['muted']} !important;
}}
[data-testid="stSidebar"] div[data-testid="stRadio"] label:has(input:checked) {{
    background: rgba(45,130,183,0.18);
    border-left: 2px solid {SIDEBAR['accent']};
}}
[data-testid="stSidebar"] div[data-testid="stRadio"] label:has(input:checked) > div:last-child {{
    color: #FFFFFF !important;
    font-weight: 600 !important;
}}

/* Nhãn nhóm điều hướng chèn bằng ::before trước từng mục tương ứng trong
   NAV_OPTIONS — CSS thuần, KHÔNG đụng vào logic Python của st.radio (an
   toàn, không có rủi ro gãy state điều hướng). Thứ tự phải khớp đúng thứ tự
   NAV_OPTIONS bên dưới: 1=Tổng quan, 2=Dữ liệu khách hàng thật,
   3=Chiến dịch & SWOT, 4=Dữ liệu & phân cụm, 5=Trò chuyện 1-1,
   6=Lịch sử học AI. */
[data-testid="stSidebar"] div[data-testid="stRadio"] > div[role="radiogroup"] > label:nth-of-type(1)::before {{
    content: "TỔNG QUAN";
}}
[data-testid="stSidebar"] div[data-testid="stRadio"] > div[role="radiogroup"] > label:nth-of-type(2)::before {{
    content: "DỮ LIỆU KHÁCH HÀNG";
}}
[data-testid="stSidebar"] div[data-testid="stRadio"] > div[role="radiogroup"] > label:nth-of-type(3)::before {{
    content: "CHIẾN DỊCH";
}}
[data-testid="stSidebar"] div[data-testid="stRadio"] > div[role="radiogroup"] > label:nth-of-type(4)::before {{
    content: "DỮ LIỆU & PHÂN TÍCH";
}}
[data-testid="stSidebar"] div[data-testid="stRadio"] > div[role="radiogroup"] > label:nth-of-type(6)::before {{
    content: "HỆ THỐNG";
}}
[data-testid="stSidebar"] div[data-testid="stRadio"] > div[role="radiogroup"] > label:nth-of-type(1)::before,
[data-testid="stSidebar"] div[data-testid="stRadio"] > div[role="radiogroup"] > label:nth-of-type(2)::before,
[data-testid="stSidebar"] div[data-testid="stRadio"] > div[role="radiogroup"] > label:nth-of-type(3)::before,
[data-testid="stSidebar"] div[data-testid="stRadio"] > div[role="radiogroup"] > label:nth-of-type(4)::before,
[data-testid="stSidebar"] div[data-testid="stRadio"] > div[role="radiogroup"] > label:nth-of-type(6)::before {{
    display: block;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.8px;
    color: {SIDEBAR['muted']};
    margin: 14px 0 6px 10px;
}}
[data-testid="stSidebar"] div[data-testid="stRadio"] > div[role="radiogroup"] > label:nth-of-type(1)::before {{
    margin-top: 2px;
}}

/* Bộ chọn dạng viên thuốc (pill) cho st.radio nằm trong NỘI DUNG CHÍNH
   (vd: công tắc "Xem: Tổng quan / Xem: Kết quả chiến dịch") — tách riêng
   khỏi CSS của sidebar ở trên để không đổi màu menu điều hướng bên trái. */
section.main div[data-testid="stRadio"] > div[role="radiogroup"] {{
    gap: 8px !important;
}}
section.main div[data-testid="stRadio"] > div[role="radiogroup"] > label {{
    background-color: {PAL['card_bg']} !important;
    border: 1px solid {PAL['border']} !important;
    border-radius: 999px !important;
    padding: 8px 18px !important;
    margin: 0 !important;
}}
section.main div[data-testid="stRadio"] > div[role="radiogroup"] > label > div:last-child {{
    color: {PAL['muted']} !important;
    font-weight: 700 !important;
    font-size: 14px !important;
}}
section.main div[data-testid="stRadio"] > div[role="radiogroup"] > label:has(input:checked) {{
    background: linear-gradient(90deg, #1B4F91, #2D82B7) !important;
    border-color: transparent !important;
}}
section.main div[data-testid="stRadio"] > div[role="radiogroup"] > label:has(input:checked) > div:last-child {{
    color: #FFFFFF !important;
}}

/* ---------- Thanh trên cùng + Lời chào (Tổng quan) ---------- */
.msai-topbar-crumb {{ font-size:13px; color:{PAL['muted']}; margin-bottom:2px; }}
.msai-topbar-crumb b {{ color:{PAL['text']}; font-weight:700; }}
.msai-greeting h2 {{ color:{PAL['text']}; font-size:26px; font-weight:800; margin:6px 0 2px 0; }}
.msai-greeting p {{ color:{PAL['muted']}; font-size:14.5px; margin:0 0 18px 0; }}

/* ---------- Thẻ KPI kiểu mới (icon tròn góc phải, số lớn, dòng phụ) ---------- */
.msai-kpi-card {{
    background:{PAL['card_bg']}; border:1px solid {PAL['border']}; border-radius:16px;
    padding:18px 20px; box-shadow: 0 2px 10px rgba(20,33,61,0.04);
}}
.msai-kpi-label {{ font-size:12.5px; color:{PAL['muted']}; font-weight:600; }}
.msai-kpi-icon {{
    width:30px; height:30px; border-radius:8px; display:flex; align-items:center;
    justify-content:center; font-size:15px; float:right;
}}
.msai-kpi-value {{ font-size:26px; font-weight:800; color:{PAL['text']}; margin-top:14px; clear:both; }}
.msai-kpi-sub {{ font-size:12.5px; color:{PAL['muted']}; margin-top:4px; }}

/* ---------- Thẻ trạng thái rỗng (chưa có dữ liệu) kiểu CTA ---------- */
.msai-empty-card {{
    background: linear-gradient(135deg, #0B2545 0%, #1B4F91 100%);
    border-radius:16px; padding:20px 22px;
}}
.msai-empty-card h4 {{ color:#FFFFFF !important; margin:0 0 6px 0; font-size:16px; }}
.msai-empty-card p {{ color:rgba(255,255,255,0.85) !important; font-size:13.5px; margin:0 0 14px 0; }}
</style>
""", unsafe_allow_html=True)


def sentiment_style_map(sentiment: str):
    s = str(sentiment).lower()
    return {
        "positive": (PAL["positive"], PAL["positive_bg"], "TÍCH CỰC"),
        "negative": (PAL["negative"], PAL["negative_bg"], "TIÊU CỰC"),
        "neutral": (PAL["neutral"], PAL["neutral_bg"], "TRUNG LẬP"),
    }.get(s, (PAL["muted"], PAL["card_bg"], s.upper() if s else "?"))


def sentiment_badge_html(sentiment: str) -> str:
    color, bg, label = sentiment_style_map(sentiment)
    return f'<span class="msai-badge" style="background:{bg};color:{color};">{label}</span>'


def score_bar_html(score, max_score=10) -> str:
    try:
        pct = max(0, min(100, float(score) / max_score * 100))
    except (ValueError, TypeError):
        pct = 0
    return f'<div class="msai-score-track"><div class="msai-score-fill" style="width:{pct}%;"></div></div>'


def keyword_chips_html(keywords) -> str:
    return "".join([f'<span class="msai-chip">{kw}</span>' for kw in keywords])


def section_title(text: str):
    st.markdown(f'<div class="msai-section-title">{text}</div>', unsafe_allow_html=True)


def build_personas_with_fallback(cluster_result, total_personas):
    try:
        return generate_personas(cluster_result, total_personas=total_personas)
    except TypeError:
        # Nếu phiên bản cũ không chấp nhận total_personas, chuyển về cách gọi cũ.
        n_clusters = len(cluster_result.get("cluster_keywords", {}))
        if n_clusters <= 0:
            return generate_personas(cluster_result, total_personas)

        num_per_cluster = max(1, total_personas // n_clusters)
        return generate_personas(cluster_result, num_per_cluster=num_per_cluster)


def run_simulation_with_progress(personas, scenario, progress_callback):
    try:
        return simulate_marketing_scenario(personas, scenario, progress_callback=progress_callback)
    except TypeError:
        return simulate_marketing_scenario(personas, scenario)


def sidebar_status(kind: str, text: str):
    """Hộp trạng thái tự vẽ (không dùng st.success/error mặc định) để LUÔN khớp
    với tông màu navy tối của sidebar, bất kể Chế độ Sáng/Tối của nội dung chính."""
    styles = {
        "success": (SIDEBAR["success_bg"], SIDEBAR["success"]),
        "warning": (SIDEBAR["warning_bg"], SIDEBAR["warning"]),
        "error": (SIDEBAR["error_bg"], SIDEBAR["error"]),
        "muted": (SIDEBAR["card_bg"], SIDEBAR["muted"]),
    }
    bg, color = styles.get(kind, styles["muted"])
    st.markdown(
        f'<div class="msai-sidebar-status" style="background:{bg};color:{color};">{text}</div>',
        unsafe_allow_html=True
    )


def style_sentiment_column(df: pd.DataFrame, col: str = "Thái Độ"):
    """Tô màu cột cảm xúc trong bảng feed (hỗ trợ cả pandas mới/cũ)."""
    def _style(v):
        color, bg, _ = sentiment_style_map(v)
        return f"background-color:{bg};color:{color};font-weight:700;border-radius:6px;"
    try:
        return df.style.map(_style, subset=[col])
    except AttributeError:
        return df.style.applymap(_style, subset=[col])


# ==============================================================================
# CỔNG ĐĂNG NHẬP / ĐĂNG KÝ
# ==============================================================================
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    st.session_state["user_email"] = None


def render_auth_gate():
    st.markdown("""
    <style>
    .auth-card {
        background: linear-gradient(135deg, rgba(10,16,33,0.95), rgba(25,46,92,0.92));
        border-radius: 20px;
        padding: 24px;
        box-shadow: 0 12px 34px rgba(0,0,0,0.25);
        border: 1px solid rgba(255,255,255,0.12);
    }
    .auth-card h3, .auth-card p, .auth-card label, .auth-card span {
        color: #F6F8FF !important;
    }
    </style>
    """, unsafe_allow_html=True)

    st.markdown('<div class="auth-card">', unsafe_allow_html=True)
    with st.container():
        st.markdown("### Đăng nhập hệ thống")
        st.caption("Đăng nhập hoặc tạo tài khoản để tiếp tục sử dụng MarketSim AI")
        mode = st.radio("Chế độ", ["Đăng nhập", "Đăng ký"], horizontal=True)

        if mode == "Đăng nhập":
            with st.form("form_login"):
                email_in = st.text_input("Email")
                pw_in = st.text_input("Mật khẩu", type="password")
                submit_login = st.form_submit_button("Đăng nhập", use_container_width=True)
            if submit_login:
                if verify_user(email_in, pw_in):
                    st.session_state["logged_in"] = True
                    st.session_state["user_email"] = email_in.strip().lower()
                    st.rerun()
                else:
                    st.error("Email hoặc mật khẩu không đúng.")
        else:
            with st.form("form_register"):
                email_r = st.text_input("Email")
                pw_r = st.text_input("Mật khẩu (tối thiểu 6 ký tự)", type="password")
                pw_r2 = st.text_input("Nhập lại mật khẩu", type="password")
                submit_register = st.form_submit_button("Tạo tài khoản", use_container_width=True)
            if submit_register:
                if pw_r != pw_r2:
                    st.error("Mật khẩu nhập lại không khớp.")
                else:
                    try:
                        create_user(email_r, pw_r)
                        st.success("Tạo tài khoản thành công. Hãy đăng nhập bằng tài khoản mới.")
                    except ValueError as e:
                        st.error(str(e))
    st.markdown('</div>', unsafe_allow_html=True)


if not st.session_state["logged_in"]:
    render_auth_gate()
    st.stop()

# ==============================================================================
# BANNER TIÊU ĐỀ
# ==============================================================================
st.markdown("""
<div class="msai-hero">
    <h1>Hệ thống mô phỏng và phân tích marketing</h1>
    <p>MarketSim AI — Mô phỏng phản ứng khách hàng đa luồng, phân tích SWOT tự động và phỏng vấn khách hàng ảo bằng Qwen / Ollama</p>
</div>
""", unsafe_allow_html=True)

FIELD_LABELS_VI = {
    "age": "Tuổi",
    "job": "Nghề nghiệp",
    "pain_point": "Nỗi đau khách hàng",
    "personality": "Tính cách",
    "interest_keywords": "Từ khóa sở thích",
}


def render_learning_audit_panel(audit_summary: dict, audit_id: int = None, clean_data: list = None):
    """Hiển thị RÕ RÀNG: với mỗi trường bắt buộc AI dùng để mô phỏng persona,
    bao nhiêu % là dữ liệu THẬT của doanh nghiệp, bao nhiêu % là AI tự suy luận
    (ai_inferred) hoặc chỉ là giá trị mặc định an toàn (default_fallback).
    Đây là câu trả lời trực tiếp cho câu hỏi 'AI học được gì, học đến đâu'."""
    st.markdown("#### 🔍 AI Learning Audit — AI đã học được gì, đến đâu?")

    overall = audit_summary.get("overall_real_data_pct", 0.0)
    total = audit_summary.get("total_records", 0)
    c1, c2 = st.columns(2)
    c1.metric("Tổng số hồ sơ đã chuẩn hóa", total)
    c2.metric("Tỉ lệ dữ liệu THẬT (trung bình)", f"{overall}%")

    if overall < 50:
        st.error(
            "⚠ Hơn một nửa dữ liệu bắt buộc là do AI TỰ SUY LUẬN hoặc giá trị mặc định, "
            "không phải dữ liệu thật từ doanh nghiệp. Kết quả mô phỏng có thể KHÔNG phản ánh "
            "đúng khách hàng thật. Khuyến nghị: kiểm tra lại file gốc có đủ cột cần thiết chưa."
        )
    elif overall < 80:
        st.warning("Một phần đáng kể dữ liệu là do AI suy luận. Nên xem kỹ bảng chi tiết bên dưới trước khi tin dùng.")
    else:
        st.success("Phần lớn dữ liệu là thật từ doanh nghiệp. Chất lượng học tốt.")

    field_coverage = audit_summary.get("field_coverage", {})
    if field_coverage:
        rows = []
        for field, stats in field_coverage.items():
            rows.append({
                "Trường dữ liệu": FIELD_LABELS_VI.get(field, field),
                "Dữ liệu thật (%)": stats.get("original_pct", 0.0),
                "AI tự suy luận (%)": stats.get("ai_inferred_pct", 0.0),
                "Giá trị mặc định (%)": stats.get("default_fallback_pct", 0.0),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    if clean_data:
        with st.expander("👀 Xem trước dữ liệu đã chuẩn hóa (Canonical Data)"):
            st.dataframe(pd.DataFrame(clean_data).drop(columns=["_field_sources"], errors="ignore").head(100),
                         use_container_width=True)

    if audit_id is not None:
        if st.button("✅ Tôi đã xem & xác nhận chất lượng dữ liệu học được này", key=f"confirm_audit_{audit_id}"):
            confirm_fn = getattr(database_module, "confirm_learning_audit", None)
            if confirm_fn is not None:
                confirm_fn(audit_id)
                st.success("Đã ghi nhận xác nhận của bạn cho lần học dữ liệu này.")


def render_ai_learning_center(report: dict):
    if not report:
        return

    st.markdown("---")
    st.markdown('<div class="msai-section-title">🧠 AI Learning Center</div>', unsafe_allow_html=True)

    with st.container(border=True):
        st.markdown("### AI Learning Center")
        st.caption("Bước quan trọng nhất: hệ thống học trước khi sinh Synthetic Data hoặc chạy Digital Twin.")

        progress_steps = [
            "Đang đọc dữ liệu...",
            "Đang nhận diện doanh nghiệp...",
            "Đang chuẩn hóa dữ liệu...",
            "Đang học hành vi...",
            "Đang phát hiện Insight...",
            "Đang kiểm tra chất lượng dữ liệu...",
            "Đang xây dựng Data Model...",
        ]
        progress_bar = st.progress(0)
        for index, step in enumerate(progress_steps, start=1):
            progress_bar.progress(int(index / len(progress_steps) * 100))
            st.caption(step)

        st.success("AI đã hoàn tất việc học dữ liệu và sẵn sàng xác nhận trước khi tạo Synthetic Data.")

        st.markdown("### AI đã học được")
        metrics_col1, metrics_col2, metrics_col3, metrics_col4 = st.columns(4)
        metrics_col1.metric("Loại doanh nghiệp", report.get("business_type", "Chưa rõ"))
        metrics_col2.metric("Độ tin cậy", f"{int(report.get('business_confidence', 0) * 100)}%")
        metrics_col3.metric("Tổng số khách hàng", report.get("total_customers", 0))
        metrics_col4.metric("Tổng số đơn hàng", report.get("total_orders", 0))

        st.markdown("---")
        st.write("**Khoảng thời gian dữ liệu:**", report.get("date_range", "Không xác định"))
        st.write("**Số cột:**", report.get("column_count", 0))
        st.write("**Số trường hợp lệ:**", report.get("valid_columns", 0))
        st.write("**Số trường thiếu:**", report.get("missing_columns", 0))

        if report.get("mapping_error"):
            st.error(
                f"⚠ AI (Ollama) không map được {report['missing_columns']} cột sau: {report['mapping_error']}\n\n"
                f"Các cột khác (đã khớp tự động bằng luật/AI) vẫn giữ nguyên kết quả -- chỉ những cột lỗi ở trên "
                f"cần bạn tự chọn thủ công ở bảng bên dưới rồi bấm Xác nhận."
            )
        if report.get("missing_required_fields"):
            st.warning(
                f"Còn thiếu trường BẮT BUỘC chưa được map tới cột nào: "
                f"{', '.join(report['missing_required_fields'])}. "
                f"Hãy chọn cột phù hợp trong bảng bên dưới (hoặc để AI tự suy luận bù nếu doanh nghiệp thực sự không có dữ liệu này)."
            )
        low_confidence_rows = [row for row in report.get("mapping", []) if row.get("confidence", 0) < 0.7]
        if low_confidence_rows:
            st.warning(f"Có {len(low_confidence_rows)} cột có độ tin cậy thấp (<70%). Hãy kiểm tra lại trước khi vào bước Synthetic Data.")
        import pandas as pd
        mapping_df = pd.DataFrame(report.get("mapping", []))
        if not mapping_df.empty:
            mapping_view = mapping_df[["source_column", "ai_column", "confidence_display", "editable"]].copy()
            mapping_view = mapping_view.rename(columns={
                "source_column": "Tên cột gốc",
                "ai_column": "AI hiểu là",
                "confidence_display": "Độ tin cậy",
                "editable": "Cho phép sửa",
            })
            edited_mapping = st.data_editor(
                mapping_view,
                use_container_width=True,
                hide_index=True,
                disabled=["Tên cột gốc", "Độ tin cậy"],
                key="ai_mapping_editor",
            )
            if edited_mapping is not None:
                st.session_state["ai_learning_mapping"] = edited_mapping.to_dict("records")

        if st.button("✅ Xác nhận & tiếp tục", key="confirm_ai_learning", use_container_width=True):
            st.session_state["ai_learning_confirmed"] = True
            
            # Khởi tạo giao diện Loading hiển thị luồng xử lý ETL
            with st.status("🚀 Đang khởi chạy quy trình Tiền xử lý dữ liệu (ETL & AI)...", expanded=True) as status:
                try:
                    import asyncio
                    import data_preprocessor as data_preprocessor_module
                    _safe_reload(data_preprocessor_module)
                    run_advanced_etl = data_preprocessor_module.run_advanced_etl
                    
                    raw_data = st.session_state.get("uploaded_records", [])
                    mapping = st.session_state.get("ai_learning_mapping", [])
                    if not mapping and report.get("mapping"):
                        mapping = report.get("mapping")
                    
                    if not raw_data:
                        status.update(label="Không có dữ liệu để xử lý!", state="error")
                        st.stop()
                    
                    st.write("🔄 Đang chuẩn hóa cấu trúc và ép kiểu dữ liệu bằng Pandas...")
                    st.write("🧠 Đang gọi Ollama nội suy các hồ sơ bị khuyết (Contextual Imputation)...")
                    
                    # Kích hoạt luồng bất đồng bộ để gọi AI nội suy dữ liệu khuyết.
                    # run_advanced_etl giờ trả về (records, audit_summary): audit_summary
                    # cho biết % dữ liệu THẬT vs AI tự suy luận cho từng trường.
                    clean_data, audit_summary = asyncio.run(
                        run_advanced_etl(raw_data, mapping, upload_name=report.get("file_name", ""))
                    )

                    # Lưu lại tệp dữ liệu đã sạch 100% vào bộ nhớ phiên (để xem trước trên UI)
                    st.session_state["clean_customer_data"] = clean_data

                    # QUAN TRỌNG: lưu vào bảng canonical_customers -- đây là bước trước đây
                    # BỊ THIẾU, khiến dữ liệu đã chuẩn hóa không bao giờ được clustering/persona
                    # đọc lại. Từ giờ collect_all() sẽ ưu tiên đọc từ đúng bảng này.
                    save_canonical_customers_fn = getattr(database_module, "save_canonical_customers", None)
                    upload_id = st.session_state.get("current_upload_id")
                    if save_canonical_customers_fn is not None and clean_data:
                        save_canonical_customers_fn(upload_id, clean_data)
                        st.write(f"💾 Đã lưu {len(clean_data)} hồ sơ vào bảng dữ liệu chuẩn (canonical_customers).")

                    # Lưu NHẬT KÝ HỌC AI: để trả lời đúng câu hỏi "AI đã học được gì,
                    # học đến đâu" -- xem lại được bất cứ lúc nào, không chỉ trong phiên này.
                    save_learning_audit_fn = getattr(database_module, "save_learning_audit", None)
                    if save_learning_audit_fn is not None:
                        audit_id = save_learning_audit_fn(
                            upload_id, report.get("file_name", ""), audit_summary,
                            mapping, report.get("missing_required_fields", []),
                        )
                        st.session_state["last_audit_id"] = audit_id

                    status.update(label=f"Hoàn tất! Chuẩn hóa thành công {len(clean_data)} hồ sơ khách hàng.", state="complete")
                    st.success("Hệ thống đã khóa dữ liệu chuẩn (Canonical Data Model). Sẵn sàng chuyển sang Mô phỏng Synthetic Data.")
                    st.info("👉 Xem chi tiết đầy đủ (kể cả các lần trước) ở tab **[4] Lịch sử học AI** phía dưới.")
                    
                    render_learning_audit_panel(audit_summary, audit_id=st.session_state.get("last_audit_id"), clean_data=clean_data)

                except ModuleNotFoundError:
                    status.update(label="Lỗi cấu trúc thư mục", state="error")
                    st.error("Không tìm thấy module 'data_preprocessor'. Hãy đảm bảo file 'data_preprocessor.py' nằm cùng thư mục với 'web_app.py'.")
                except Exception as e:
                    status.update(label="Lỗi trong quá trình xử lý dữ liệu!", state="error")
                    st.error(f"Chi tiết lỗi hệ thống: {str(e)}")

        if st.session_state.get("ai_learning_confirmed"):
            st.success("AI Confirmation: dữ liệu đã được hệ thống hiểu và chấp thuận để đi tiếp.")
        else:
            st.caption("Chưa xác nhận. Hệ thống sẽ chặn bước mô phỏng/Synthetic Data cho đến khi bạn xác nhận ở đây.")

        st.info("Sau bước xác nhận này, hệ thống sẽ chuyển sang Data Cleaning, Canonical Data Model và Synthetic Data.")


# ==============================================================================
# SIDEBAR: TRẠNG THÁI HỆ THỐNG + NẠP DỮ LIỆU KHÁCH HÀNG QUA WEB + CÔNG TẮC DARK MODE
# ==============================================================================
with st.sidebar:
    st.markdown('<div class="msai-sidebar-brand"><span>MarketSim</span></div>', unsafe_allow_html=True)

    if st.session_state.get("user_email"):
        st.markdown(f'<span class="msai-sidebar-chip">👤 {st.session_state["user_email"]}</span>', unsafe_allow_html=True)
    if st.button("Đăng xuất", use_container_width=True):
        st.session_state["logged_in"] = False
        st.session_state["user_email"] = None
        st.rerun()

    st.markdown("---")
    st.markdown('<div class="msai-sidebar-label">Điều hướng</div>', unsafe_allow_html=True)
    NAV_OPTIONS = [
        "🏠 Tổng quan",
        "📤 Dữ liệu khách hàng thật",
        "🎯 Chiến dịch & SWOT",
        "🗂️ Dữ liệu & phân cụm",
        "💬 Trò chuyện 1-1",
        "📈 Lịch sử học AI",
    ]
    nav_choice = st.radio("Điều hướng", NAV_OPTIONS, label_visibility="collapsed", key="nav_choice")

    st.markdown("---")
    st.markdown('<div class="msai-sidebar-label">Trạng thái hệ thống</div>', unsafe_allow_html=True)
    st.markdown(f'<span class="msai-sidebar-chip">Model: {OLLAMA_MODEL}</span>', unsafe_allow_html=True)
    try:
        from data_preprocessor import DATA_PREPROCESSOR_BUILD
        st.caption(f"🏷 data_preprocessor build: `{DATA_PREPROCESSOR_BUILD}`")
    except Exception:
        st.caption("🏷 Không đọc được phiên bản data_preprocessor.py hiện tại.")
    st.write("")

    if st.button("Kiểm tra kết nối Ollama", use_container_width=True):
        with st.spinner("Đang kiểm tra kết nối..."):
            st.session_state["ollama_status"] = check_ollama_connection()

    status = st.session_state.get("ollama_status")
    if status:
        connected, model_ready, models = status
        if connected and model_ready:
            sidebar_status("success", "Ollama đang chạy và model đã sẵn sàng")
        elif connected and not model_ready:
            model_list_txt = ", ".join(models) if models else "không có model nào"
            sidebar_status("warning", f"Ollama đang chạy nhưng chưa thấy model <b>{OLLAMA_MODEL}</b>.<br>Model hiện có: {model_list_txt}")
        else:
            sidebar_status("error", f"Không kết nối được Ollama tại <b>{OLLAMA_HOST}</b>.<br>Hãy mở terminal chạy: <code>ollama serve</code>")
    else:
        sidebar_status("muted", "Bấm nút trên để kiểm tra trước khi chạy mô phỏng.")

    # Đã chuyển "Nạp dữ liệu khách hàng thật" + "Dữ liệu & lịch sử" sang tab
    # riêng "📤 Dữ liệu khách hàng thật" (xem bên dưới, ngay sau nav_choice ==
    # "🏠 Tổng quan") vì đây là phần quan trọng nhất của dự án, cần một trang
    # riêng thay vì nằm gọn trong sidebar hẹp.


# ĐÃ THAY st.tabs() BẰNG MENU ĐIỀU HƯỚNG Ở SIDEBAR (biến `nav_choice` được đọc
# từ st.radio trong khối `with st.sidebar:` phía trên) — khớp với bản thiết kế
# Corporate/Doanh nghiệp đã duyệt (điều hướng nằm ở sidebar, không phải tab
# ngang phía trên). Mỗi khối nội dung bên dưới chỉ hiển thị khi đúng mục đang
# được chọn.

# ==============================================================================
# TAB TỔNG QUAN (MỚI) — Dashboard tổng hợp KPI, thêm theo bản thiết kế lại giao
# diện Corporate/Doanh nghiệp. KHÔNG gọi thêm logic AI/pipeline nào mới — chỉ
# đọc lại dữ liệu đã có sẵn trong SQLite qua get_all_scenarios()/
# get_results_by_scenario() (đã tồn tại từ trước) để tổng hợp số liệu hiển thị.
# ==============================================================================
if nav_choice == "🏠 Tổng quan":
    import datetime as _dt

    def _greeting_name() -> str:
        """Suy ra tên hiển thị từ email đăng nhập (KHÔNG bịa tên — nếu chưa có
        email thì dùng 'bạn' chung chung)."""
        email = st.session_state.get("user_email")
        if not email:
            return "bạn"
        local_part = email.split("@")[0]
        cleaned = local_part.replace(".", " ").replace("_", " ").replace("-", " ").strip()
        return cleaned.title() if cleaned else "bạn"

    def _greeting_phrase() -> str:
        hour = _dt.datetime.now().hour
        if hour < 11:
            return "Chào buổi sáng"
        elif hour < 14:
            return "Chào buổi trưa"
        elif hour < 18:
            return "Chào buổi chiều"
        return "Chào buổi tối"

    # ---------- Thanh trên cùng: breadcrumb + nút hành động ----------
    top_l, top_r = st.columns([3, 1])
    with top_l:
        st.markdown('<div class="msai-topbar-crumb">Tổng quan / <b>Dashboard</b></div>', unsafe_allow_html=True)
    with top_r:
        if st.button("➕ Chiến dịch mới", use_container_width=True):
            st.session_state["nav_choice"] = "🎯 Chiến dịch & SWOT"
            st.rerun()

    st.markdown(
        f'<div class="msai-greeting"><h2>{_greeting_phrase()}, {_greeting_name()}</h2>'
        f'<p>Đây là tình hình mô phỏng khách hàng AI của bạn.</p></div>',
        unsafe_allow_html=True,
    )

    all_scenarios = get_all_scenarios() if os.path.exists(DB_PATH) else []

    if not all_scenarios:
        st.markdown(
            '<div class="msai-empty-card"><h4>Bắt đầu mô phỏng đầu tiên</h4>'
            '<p>Nhập một ý tưởng chiến dịch và xem hàng chục khách hàng ảo phản ứng chỉ trong vài phút.</p></div>',
            unsafe_allow_html=True,
        )
        st.write("")
        if st.button("Tạo chiến dịch mới", type="primary"):
            st.session_state["nav_choice"] = "🎯 Chiến dịch & SWOT"
            st.rerun()
    else:
        view_choice = st.radio(
            "Chế độ xem", ["Xem: Tổng quan", "Xem: Kết quả chiến dịch"],
            horizontal=True, label_visibility="collapsed", key="overview_view_toggle",
        )

        total_campaigns = len(all_scenarios)
        total_personas = 0
        total_pos = total_all = 0
        star_sum = 0
        per_scenario_rows = []
        for sid, txt, stars in all_scenarios:
            df_r = get_results_by_scenario(sid)
            n = len(df_r)
            pos = int((df_r["sentiment"] == "positive").sum()) if n else 0
            total_personas += n
            total_all += n
            total_pos += pos
            star_sum += stars
            per_scenario_rows.append((sid, txt, stars, df_r, n, pos))

        avg_positive_pct = round(100 * total_pos / total_all, 1) if total_all else 0.0
        avg_stars = round(star_sum / total_campaigns, 1) if total_campaigns else 0.0

        # Thẻ KPI dạng HTML tuỳ chỉnh. LƯU Ý: hệ thống hiện KHÔNG lưu lịch sử
        # theo thời gian (không có mốc "tuần trước") nên các thẻ này CHỈ hiển
        # thị số liệu thật tính đến hiện tại — không bịa % tăng/giảm giả.
        def _kpi_card(label, value, icon, tint_bg, tint_fg, sub=""):
            sub_html = f'<div class="msai-kpi-sub">{sub}</div>' if sub else ""
            return f'''
            <div class="msai-kpi-card">
                <div class="msai-kpi-icon" style="background:{tint_bg};color:{tint_fg};">{icon}</div>
                <div class="msai-kpi-label">{label}</div>
                <div class="msai-kpi-value">{value}</div>
                {sub_html}
            </div>
            '''

        k1, k2, k3, k4 = st.columns(4)
        with k1:
            st.markdown(_kpi_card("Chiến dịch đã chạy", total_campaigns, "🎯", PAL["chip_bg"], PAL["accent"]), unsafe_allow_html=True)
        with k2:
            st.markdown(_kpi_card("Persona đã mô phỏng", f"{total_personas:,}", "🗂️", PAL["positive_bg"], PAL["positive"],
                                   sub=f"trên {total_campaigns} chiến dịch"), unsafe_allow_html=True)
        with k3:
            st.markdown(_kpi_card("Tỉ lệ phản hồi tích cực TB", f"{avg_positive_pct}%", "📈", PAL["neutral_bg"], PAL["neutral"],
                                   sub=f"trên {total_all} phản hồi"), unsafe_allow_html=True)
        with k4:
            st.markdown(_kpi_card("Đánh giá sao trung bình", f"{avg_stars}/5", "⭐", PAL["chip_bg"], PAL["accent"]), unsafe_allow_html=True)

        st.write("")

        if view_choice == "Xem: Kết quả chiến dịch":
            # ---------- Bảng đầy đủ tất cả chiến dịch (thay cho danh sách rút gọn) ----------
            section_title("Kết quả tất cả chiến dịch")
            table_rows = [{
                "Mã": sid,
                "Kịch bản": txt[:90] + ("..." if len(txt) > 90 else ""),
                "Sao": stars,
                "Số persona": n,
                "Tích cực (%)": round(100 * pos / n, 1) if n else 0.0,
            } for sid, txt, stars, _df_r, n, pos in per_scenario_rows]
            st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)
            st.caption("Bấm vào một chiến dịch cụ thể ở mục **Chiến dịch & SWOT** (sidebar) để xem đầy đủ báo cáo và phỏng vấn từng khách hàng ảo.")
        else:
            # ---------- 2 cột: Hoạt động gần đây | Phân bố tâm lý khách hàng ----------
            col_left, col_right = st.columns([3, 2])

            with col_left:
                section_title("Hoạt động mô phỏng gần đây")
                search_kw = st.text_input(
                    "Tìm chiến dịch", placeholder="🔍 Tìm chiến dịch theo từ khoá...",
                    label_visibility="collapsed", key="overview_search",
                )
                filtered = per_scenario_rows
                if search_kw.strip():
                    kw = search_kw.strip().lower()
                    filtered = [r for r in per_scenario_rows if kw in r[1].lower()]

                with st.container(border=True):
                    if not filtered:
                        st.caption("Không tìm thấy chiến dịch nào khớp từ khoá.")
                    for sid, txt, stars, df_r, n, pos in filtered[:6]:
                        neu = int((df_r["sentiment"] == "neutral").sum()) if n else 0
                        neg = max(0, n - pos - neu)
                        pos_pct = round(100 * pos / n) if n else 0
                        neu_pct = round(100 * neu / n) if n else 0
                        neg_pct = max(0, 100 - pos_pct - neu_pct) if n else 0
                        overall_sentiment = "positive" if pos >= neu and pos >= neg else ("neutral" if neu >= neg else "negative")

                        c1, c2, c3 = st.columns([4, 2, 2])
                        with c1:
                            st.markdown(f"**#{sid} — {txt[:60]}{'...' if len(txt) > 60 else ''}**")
                            st.caption(f"{n} persona")
                        with c2:
                            st.markdown("★" * stars + "☆" * (5 - stars))
                        with c3:
                            st.markdown(sentiment_badge_html(overall_sentiment), unsafe_allow_html=True)
                        st.markdown(
                            f'<div style="display:flex;height:8px;border-radius:5px;overflow:hidden;margin:4px 0 2px 0;">'
                            f'<div style="width:{pos_pct}%;background:{PAL["positive"]};"></div>'
                            f'<div style="width:{neu_pct}%;background:{PAL["neutral"]};"></div>'
                            f'<div style="width:{neg_pct}%;background:{PAL["negative"]};"></div>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
                        st.markdown("---")

                if len(filtered) > 6:
                    st.caption(f"...và {len(filtered) - 6} chiến dịch khác. Xem đầy đủ ở chế độ **Xem: Kết quả chiến dịch** phía trên.")

            with col_right:
                section_title("Phân bố tâm lý khách hàng")
                if 'df_raw' in st.session_state and not st.session_state['df_raw'].empty:
                    try:
                        with st.spinner("Đang phân cụm..."):
                            n_eff = max(1, min(NUM_CLUSTERS, len(st.session_state['df_raw'])))
                            clusters = cluster_customer_psychology(st.session_state['df_raw'], n_clusters=n_eff)
                        sizes = clusters.get("cluster_sizes", {})
                        total_sz = sum(sizes.values()) or 1
                        with st.container(border=True):
                            for c_id, keywords in clusters.get("cluster_keywords", {}).items():
                                size = sizes.get(c_id, 0)
                                pct = round(100 * size / total_sz)
                                st.markdown(f"**Nhóm tâm lý #{c_id}** &nbsp; <span style='color:{PAL['muted']};font-size:12.5px;'>{size} người</span>", unsafe_allow_html=True)
                                st.markdown(
                                    f'<div class="msai-score-track" style="margin:4px 0 8px 0;">'
                                    f'<div class="msai-score-fill" style="width:{pct}%;"></div></div>',
                                    unsafe_allow_html=True,
                                )
                                st.markdown(keyword_chips_html(keywords[:4]), unsafe_allow_html=True)
                                st.write("")
                    except Exception as e:
                        st.error(f"Lỗi khi phân cụm: {e}")
                else:
                    st.markdown(
                        '<div class="msai-empty-card"><h4>Chưa có dữ liệu khách hàng</h4>'
                        '<p>Sang tab \u201cDữ liệu khách hàng thật\u201d ở menu bên trái để tải file khách hàng lên.</p></div>',
                        unsafe_allow_html=True,
                    )

# ==============================================================================
# TAB: DỮ LIỆU KHÁCH HÀNG THẬT (được tách thành tab riêng theo yêu cầu, vì đây
# là phần quan trọng nhất của dự án — trước đó nằm gọn trong sidebar hẹp, nay
# có không gian rộng để nhìn rõ trạng thái nạp dữ liệu & AI Learning Center).
# KHÔNG đổi logic xử lý file so với bản trước — chỉ chuyển vị trí hiển thị.
# ==============================================================================
if nav_choice == "📤 Dữ liệu khách hàng thật":
    section_title("Nạp dữ liệu khách hàng thật")
    st.caption("Đây là bước quan trọng nhất: AI chỉ mô phỏng đúng khách hàng của bạn nếu được học từ dữ liệu thật ở đây.")

    with st.container(border=True):
        uploaded_file = st.file_uploader(
            "Tải file CSV/XLSX khách hàng",
            type=["csv", "xlsx"],
            help="Tối đa 1GB. Hỗ trợ schema tùy ý; app sẽ tự động trích xuất thông tin quan trọng để AI mô phỏng hành vi."
        )
        if uploaded_file is not None:
            current_upload_name = getattr(uploaded_file, "name", None)
            last_upload_name = st.session_state.get("ai_learning_file_name")
            if current_upload_name and current_upload_name != last_upload_name:
                try:
                    st.session_state["ai_learning_file_name"] = current_upload_name
                    file_size = getattr(uploaded_file, "size", None)
                    if file_size is not None and file_size > MAX_UPLOAD_BYTES:
                        raise ValueError("File quá lớn (>1GB). Vui lòng chọn file nhỏ hơn 1GB.")

                    with st.spinner("AI đang mở AI Learning Center và học dữ liệu..."):
                        new_records = load_uploaded_dataframe(uploaded_file)
                        st.session_state["uploaded_records"] = new_records
                        column_names = []
                        if new_records:
                            first_raw = new_records[0].get("raw_fields", {})
                            column_names = sorted(first_raw.keys())

                        learning_report = build_ai_learning_report(new_records, uploaded_file.name)
                        st.session_state["ai_learning_report"] = learning_report

                        if save_uploaded_dataset is not None:
                            st.session_state["current_upload_id"] = save_uploaded_dataset(
                                uploaded_file.name, new_records, column_names, upload_source="web_upload"
                            )
                        if save_learning_memory is not None:
                            learning_summary = save_learning_memory(uploaded_file.name, new_records, column_names, upload_source="web_upload")
                            st.session_state["ai_learning_summary"] = learning_summary

                        persisted_count = get_uploaded_dataset_count() if get_uploaded_dataset_count is not None else None
                        learning_snapshot = get_ai_learning_snapshot() if get_ai_learning_snapshot is not None else None

                        if save_uploaded_dataset is not None and get_uploaded_dataset_count is not None:
                            st.success(f"✔ AI Learning Center đã sẵn sàng cho '{uploaded_file.name}'. Lần upload được nhớ thứ {persisted_count}.")
                            if learning_snapshot:
                                st.info(f"🧠 AI đã học được {learning_snapshot.get('total_records', len(new_records))} hồ sơ tích lũy. Chủ đề: {', '.join(learning_snapshot.get('top_keywords', [])[:2]) or 'đang cập nhật'}")
                        else:
                            st.success(f"✔ AI Learning Center đã sẵn sàng cho '{uploaded_file.name}'.")
                except ValueError as e:
                    st.error(f"{e}")
                except Exception as e:
                    st.error(f"Lỗi không xác định khi đọc file: {e}")

            st.caption("📌 File đã được chọn. AI sẽ tự động mở AI Learning Center và chờ bạn xác nhận trước khi sang Synthetic Data.")

        if st.session_state.get("uploaded_records"):
            st.caption(f"Đang dùng {len(st.session_state['uploaded_records'])} khách hàng từ file bạn tải lên (thay cho dữ liệu mẫu trong thư mục DATA/).")
            st.caption("Dữ liệu upload được ghi nhớ để hệ thống học hành vi và dùng lại trong các lần chạy sau.")

            ai_snapshot = get_ai_learning_snapshot() if get_ai_learning_snapshot is not None else None
            if ai_snapshot:
                st.markdown("<div class='msai-section-title'>🧠 Trạng thái học AI</div>", unsafe_allow_html=True)
                st.info(
                    f"AI đã học tổng cộng {ai_snapshot.get('total_records', 0)} khách hàng từ {ai_snapshot.get('upload_count', 0)} lần upload. "
                    f"Chủ đề phổ biến: {', '.join(ai_snapshot.get('top_keywords', [])[:3]) or 'đang cập nhật'}. "
                    f"Tính cách phổ biến: {', '.join(ai_snapshot.get('top_traits', [])[:3]) or 'đang cập nhật'}."
                )

            if st.button("Bỏ file đã tải, dùng lại dữ liệu mẫu", use_container_width=True):
                st.session_state["uploaded_records"] = None
                st.rerun()

    if st.session_state.get("ai_learning_report"):
        render_ai_learning_center(st.session_state["ai_learning_report"])

    st.write("")
    section_title("Dữ liệu & lịch sử")
    with st.container(border=True):
        if os.path.exists(DB_PATH):
            scenarios_sidebar = get_all_scenarios()
            st.info(f"SQLite Database sẵn sàng — đã lưu {len(scenarios_sidebar)} chiến dịch.")
            if scenarios_sidebar and st.button("Xoá toàn bộ lịch sử", use_container_width=True):
                reset_db()
                st.session_state.pop("selected_scenario_id", None)
                st.rerun()
        else:
            st.warning("Chưa có dữ liệu mô phỏng.")

# ==============================================================================
# TAB 1: MÔ PHỎNG CHIẾN DỊCH & BÁO CÁO SWOT
# ==============================================================================
if nav_choice == "🎯 Chiến dịch & SWOT":
    section_title("Chạy mô phỏng phản ứng khách hàng đa luồng")

    with st.container(border=True):
        if st.session_state.get("ai_learning_report") and not st.session_state.get("ai_learning_confirmed", False):       
                        st.warning("Hãy xác nhận ở AI Learning Center trước khi chạy Synthetic Data hoặc mô phỏng Digital Twin.")
                        submit_btn = False
        else:
                        submit_btn = None

        with st.form("form_scenario"):
                        scenario_input = st.text_area(
                            "Nhập kịch bản chương trình Marketing / Sale:",
                            value="CHIẾN DỊCH GIẢM GIÁ 30% cho các sản phẩm quần áo mùa hè",
                            height=100
                        )
                        col_a, col_b = st.columns(2)
                        with col_a:
                            n_persona = st.slider(
                                "Tổng số khách hàng ảo mô phỏng (tối đa 100)",
                                5, MAX_SIMULATED_PERSONAS, 30,
                                help="Hệ thống sẽ phân bổ đều số persona vào các nhóm tâm lý.")
                            st.caption("Giới hạn tối đa 100 khách hàng ảo mỗi lần chạy. Dữ liệu gốc vẫn có thể nhiều hơn để đảm bảo đa dạng.")
                        with col_b:
                            use_online = st.checkbox("Cào thêm tin tức/xu hướng online (có thể chậm)", value=True)
                        submit_btn = st.form_submit_button("Bắt đầu phân tích & mô phỏng", use_container_width=True) if submit_btn is None else submit_btn

        if submit_btn:
                if not scenario_input.strip():
                    st.error("Vui lòng nhập nội dung chiến dịch trước khi chạy.")
                else:
                    connected, model_ready, _ = check_ollama_connection()
                    st.session_state["ollama_status"] = (connected, model_ready, st.session_state.get("ollama_status", (0, 0, []))[2])

                    if not connected:
                        st.error(f"Không kết nối được Ollama tại `{OLLAMA_HOST}`. Hãy bật Ollama (`ollama serve`) rồi bấm chạy lại.")
                    else:
                        if not model_ready:
                            st.warning(f"Chưa thấy model `{OLLAMA_MODEL}` trên máy — hệ thống vẫn sẽ thử chạy, có thể lỗi.")
                        try:
                            with st.status("Hệ thống đang thực thi luồng AI (Pipeline)...", expanded=True) as status:
                                st.write("[Bước 1/4] Thu thập dữ liệu (Online + File tải lên / DATA/)...")
                                raw_df = collect_all(
                                    uploaded_records=st.session_state.get("uploaded_records"),
                                    enable_online_scrape=use_online,
                                )

                                if raw_df.empty:
                                    status.update(label="Không có dữ liệu nào để phân tích!", state="error")
                                    st.error("Không thu thập được dữ liệu nào (cả online lẫn file). "
                                            "Hãy tải file khách hàng lên ở sidebar hoặc bật cào online.")
                                    st.stop()

                                st.write("[Bước 2/4] Phân cụm tâm lý khách hàng bằng K-Means...")
                                n_clusters_eff = max(1, min(NUM_CLUSTERS, len(raw_df)))
                                cluster_result = cluster_customer_psychology(raw_df, n_clusters=n_clusters_eff)

                                st.write("[Bước 3/4] Sinh Persona ảo & chạy mô phỏng Asyncio đa luồng...")
                                personas = build_personas_with_fallback(cluster_result, n_persona)

                                progress_bar = st.progress(0)
                                progress_text = st.empty()
                                def _update_progress(done, total):
                                    pct = int(done / total * 100) if total else 0
                                    progress_bar.progress(pct)
                                    progress_text.info(f"Đang mô phỏng {done}/{total} khách hàng ảo ({pct}%)")

                                results, analysis, fail_count = run_simulation_with_progress(
                                    personas, scenario_input, progress_callback=_update_progress
                                )
                                progress_text.success("Mô phỏng đã hoàn tất.")

                                if not results:
                                    status.update(label="AI không phản hồi được lượt mô phỏng nào!", state="error")
                                    st.error("Không nhận được phản hồi hợp lệ nào từ AI. Kiểm tra lại Ollama rồi thử lại.")
                                    st.stop()

                                st.write("[Bước 4/4] Lưu kết quả vào SQLite Database...")
                                sid = save_simulation(scenario_input, results, analysis)

                                status.update(label="Hoàn tất mô phỏng! Xem báo cáo bên dưới.", state="complete", expanded=False)

                            if fail_count > 0:
                                st.warning(f"Có {fail_count}/{len(personas)} khách hàng ảo bị lỗi kết nối trong lúc mô phỏng "
                                        f"(đã tự động bỏ qua, không tính vào kết quả).")
                            st.toast("Đã lưu kết quả thành công vào Database!", icon="💾")
                            st.session_state["selected_scenario_id"] = sid

                        except Exception as e:
                            st.error(f"Đã có lỗi ngoài dự kiến trong quá trình mô phỏng: {e}")

        st.write("")

        # --- XEM BÁO CÁO: chiến dịch vừa chạy hoặc bất kỳ chiến dịch nào trong lịch sử ---
        scenarios = get_all_scenarios() if os.path.exists(DB_PATH) else []
        if scenarios:
            options = {
                f"#{sid} - {txt[:60]}{'...' if len(txt) > 60 else ''} ({stars}⭐)": sid
                for sid, txt, stars in scenarios
            }
            label_list = list(options.keys())
            default_sid = st.session_state.get("selected_scenario_id", scenarios[0][0])
            default_label = next((k for k, v in options.items() if v == default_sid), label_list[0])

            section_title("Báo cáo chiến dịch")
            chosen_label = st.selectbox("Xem lại báo cáo chiến dịch:", label_list, index=label_list.index(default_label))
            sid = options[chosen_label]
            st.session_state["selected_scenario_id"] = sid

            row = get_scenario_by_id(sid)
            if row:
                _, text, s, w, summ, stars = row
                df_res_all = get_results_by_scenario(sid)

                # --- HÀNG CHỈ SỐ NHANH ---
                with st.container(border=True):
                    total_n = len(df_res_all)
                    pos_n = int((df_res_all["sentiment"] == "positive").sum()) if total_n else 0
                    neg_n = int((df_res_all["sentiment"] == "negative").sum()) if total_n else 0
                    neu_n = int((df_res_all["sentiment"] == "neutral").sum()) if total_n else 0

                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Đánh giá", f"{stars} / 5")
                    m2.metric("Tích cực", f"{pos_n}/{total_n}" if total_n else "0")
                    m3.metric("Tiêu cực", f"{neg_n}/{total_n}" if total_n else "0")
                    m4.metric("Trung lập", f"{neu_n}/{total_n}" if total_n else "0")
                    st.info(f"**Tóm tắt chiến lược:** {summ}")

                st.write("")
                col1, col2 = st.columns([1, 1])
                with col1:
                    section_title("Phân tích SWOT")
                    with st.container(border=True):
                        st.markdown(
                            f'<span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:{PAL["positive"]};margin-right:7px;"></span>'
                            f'**Điểm mạnh (Strengths)**',
                            unsafe_allow_html=True,
                        )
                        st.write(s)
                    with st.container(border=True):
                        st.markdown(
                            f'<span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:{PAL["negative"]};margin-right:7px;"></span>'
                            f'**Điểm yếu (Weaknesses)**',
                            unsafe_allow_html=True,
                        )
                        st.write(w)
                with col2:
                    section_title("Tỉ lệ quyết định mua hàng")
                    with st.container(border=True):
                        if not df_res_all.empty:
                            n_total = len(df_res_all)
                            n_pos = int((df_res_all["sentiment"] == "positive").sum())
                            n_neu = int((df_res_all["sentiment"] == "neutral").sum())
                            n_neg = n_total - n_pos - n_neu
                            pct_pos = round(100 * n_pos / n_total) if n_total else 0
                            pct_neu = round(100 * n_neu / n_total) if n_total else 0
                            pct_neg = max(0, 100 - pct_pos - pct_neu) if n_total else 0

                            # Thanh ngang phân đoạn (segmented bar) thay cho biểu đồ tròn
                            # trước đây — dễ so sánh tỉ lệ và đồng bộ với bảng màu Corporate.
                            st.markdown(
                                f'''
                                <div style="display:flex;height:34px;border-radius:8px;overflow:hidden;margin-bottom:10px;">
                                    <div style="width:{pct_pos}%;background:{PAL["positive"]};display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:12.5px;">{pct_pos}%</div>
                                    <div style="width:{pct_neu}%;background:{PAL["neutral"]};display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:12.5px;">{pct_neu}%</div>
                                    <div style="width:{pct_neg}%;background:{PAL["negative"]};display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:12.5px;">{pct_neg}%</div>
                                </div>
                                <div style="display:flex;gap:16px;font-size:12px;color:{PAL["muted"]};">
                                    <span><span style="display:inline-block;width:9px;height:9px;border-radius:2px;background:{PAL["positive"]};margin-right:5px;"></span>Sẽ mua ({n_pos})</span>
                                    <span><span style="display:inline-block;width:9px;height:9px;border-radius:2px;background:{PAL["neutral"]};margin-right:5px;"></span>Lưỡng lự ({n_neu})</span>
                                    <span><span style="display:inline-block;width:9px;height:9px;border-radius:2px;background:{PAL["negative"]};margin-right:5px;"></span>Không mua ({n_neg})</span>
                                </div>
                                ''',
                                unsafe_allow_html=True,
                            )
                        else:
                            st.info("Chưa có dữ liệu phản hồi chi tiết cho chiến dịch này.")

                st.write("")
                section_title("Feed phản hồi từ khách hàng ảo")
                with st.container(border=True):
                    df_details = df_res_all.rename(columns={
                        "persona_name": "Khách Hàng", "score": "Điểm",
                        "sentiment": "Thái Độ", "reasoning": "Lý Do Tâm Lý"
                    })
                    if not df_details.empty:
                        st.dataframe(style_sentiment_column(df_details, "Thái Độ"), use_container_width=True)
                    else:
                        st.caption("Chưa có phản hồi nào.")
        else:
            st.info("Chưa có chiến dịch nào được chạy. Hãy nhập kịch bản và bấm nút phía trên.")

# ==============================================================================
# TAB 2: DỮ LIỆU NGỮ NGHĨA & PHÂN CỤM K-MEANS
# ==============================================================================
if nav_choice == "🗂️ Dữ liệu & phân cụm":
    section_title("Dữ liệu ngữ nghĩa & phân cụm K-Means")

    col_a, col_b = st.columns([1, 1])
    with col_a:
        with st.container(border=True):
            st.markdown("**Cào dữ liệu nóng (Google Trends & News)**")
            use_online2 = st.checkbox("Bật cào dữ liệu online", value=True, key="use_online_tab2")
            if st.button("Cập nhật dữ liệu xu hướng mới nhất", use_container_width=True):
                try:
                    with st.spinner("Đang cào & hợp nhất dữ liệu..."):
                        df_raw = collect_all(
                            uploaded_records=st.session_state.get("uploaded_records"),
                            enable_online_scrape=use_online2,
                        )
                        st.session_state['df_raw'] = df_raw
                    if df_raw.empty:
                        st.warning("Không thu thập được dữ liệu nào.")
                    else:
                        st.success(f"Đã tải {len(df_raw)} bản ghi thành công!")
                except Exception as e:
                    st.error(f"Lỗi khi thu thập dữ liệu: {e}")

            if 'df_raw' in st.session_state and not st.session_state['df_raw'].empty:
                search_kw = st.text_input("Tìm kiếm nhanh theo từ khóa (vd: 'cafe', 'du lịch')")
                df_show = st.session_state['df_raw']
                if search_kw.strip():
                    df_show = df_show[df_show['text'].str.contains(search_kw.strip(), case=False, na=False)]
                    st.caption(f"Tìm thấy {len(df_show)} bản ghi khớp từ khóa.")
                st.dataframe(df_show, height=300, use_container_width=True)
            elif 'df_raw' not in st.session_state:
                st.caption("Chưa có dữ liệu trong phiên này — bấm nút phía trên để tải.")

    with col_b:
        with st.container(border=True):
            st.markdown("**Cụm tâm lý khách hàng (K-Means)**")
            if 'df_raw' in st.session_state and not st.session_state['df_raw'].empty:
                try:
                    with st.spinner("Đang chạy thuật toán K-Means Clustering..."):
                        n_eff = max(1, min(NUM_CLUSTERS, len(st.session_state['df_raw'])))
                        clusters = cluster_customer_psychology(st.session_state['df_raw'], n_clusters=n_eff)
                    for c_id, keywords in clusters["cluster_keywords"].items():
                        size = clusters["cluster_sizes"].get(c_id, 0)
                        with st.expander(f"Nhóm tâm lý #{c_id} ({size} dữ liệu)", expanded=True):
                            st.markdown(keyword_chips_html(keywords[:6]), unsafe_allow_html=True)
                except Exception as e:
                    st.error(f"Lỗi khi phân cụm: {e}")
            else:
                st.info("Hãy bấm nút Cập nhật dữ liệu bên trái để xem phân cụm.")

# ==============================================================================
# TAB 3: TRÒ CHUYỆN 1-1 — CHỌN NHẬP VAI 1 KHÁCH HÀNG CỤ THỂ, HOẶC CHAT CHUNG
# ==============================================================================
if nav_choice == "💬 Trò chuyện 1-1":
    section_title("Trò chuyện với khách hàng ảo")

    chat_mode = st.radio(
        "Chọn chế độ chat:",
        ["Nhập vai 1 khách hàng cụ thể", "Chat chung với trợ lý"],
        horizontal=True,
    )

    # --- CHẾ ĐỘ 1: PHỎNG VẤN SÂU 1 KHÁCH HÀNG CỤ THỂ TỪ 1 CHIẾN DỊCH ĐÃ CHẠY ---
    if chat_mode.startswith("Nhập vai"):
        st.caption("Trò chuyện trực tiếp với đúng 1 khách hàng ảo trong kết quả mô phỏng, để hiểu sâu lý do họ mua/từ chối.")

        scenarios = get_all_scenarios() if os.path.exists(DB_PATH) else []
        if not scenarios:
            st.info("Chưa có chiến dịch nào được mô phỏng. Hãy chạy mô phỏng ở Tab [1] trước để có khách hàng ảo để phỏng vấn.")
        else:
            scen_options = {f"#{sid} - {txt[:50]}{'...' if len(txt) > 50 else ''}": sid for sid, txt, stars in scenarios}
            chosen = st.selectbox("Chọn chiến dịch:", list(scen_options.keys()), key="chat_scenario_select")
            sid = scen_options[chosen]
            scenario_row = get_scenario_by_id(sid)
            scenario_text = scenario_row[1] if scenario_row else ""

            df_res = get_results_by_scenario(sid)
            if df_res.empty:
                st.warning("Chiến dịch này chưa có dữ liệu phản hồi khách hàng.")
            else:
                persona_options = {
                    f"{row.persona_name} — {str(row.sentiment).upper()} ({row.score}/10)": idx
                    for idx, row in df_res.iterrows()
                }
                chosen_persona_label = st.selectbox("Chọn khách hàng ảo muốn phỏng vấn:", list(persona_options.keys()))
                p_idx = persona_options[chosen_persona_label]
                p_row = df_res.loc[p_idx]

                persona_key = f"{sid}_{p_row['persona_name']}"
                st.session_state.setdefault("persona_chats", {})
                st.session_state["persona_chats"].setdefault(persona_key, [])

                persona_ctx = {
                    "name": p_row["persona_name"],
                    "scenario": scenario_text,
                    "sentiment": p_row["sentiment"],
                    "reasoning": p_row["reasoning"],
                    "score": p_row["score"],
                }

                with st.container(border=True):
                    c1, c2 = st.columns([3, 2])
                    with c1:
                        st.markdown(f"**{p_row['persona_name']}**")
                        st.markdown(sentiment_badge_html(p_row['sentiment']), unsafe_allow_html=True)
                    with c2:
                        st.caption(f"Điểm hài lòng: {p_row['score']}/10")
                        st.markdown(score_bar_html(p_row['score']), unsafe_allow_html=True)
                    st.caption(f"Lý do: {p_row['reasoning']}")

                history = st.session_state["persona_chats"][persona_key]

                for msg in history:
                    with st.chat_message(msg["role"]):
                        st.markdown(msg["content"])

                user_msg = st.chat_input(f"Hỏi {p_row['persona_name']}...", key="persona_chat_input")
                if user_msg:
                    history.append({"role": "user", "content": user_msg})
                    with st.chat_message("user"):
                        st.markdown(user_msg)
                    with st.chat_message("assistant"):
                        with st.spinner("Khách hàng đang suy nghĩ..."):
                            try:
                                reply = chat_with_persona(persona_ctx, history[:-1], user_msg)
                                st.markdown(reply)
                                history.append({"role": "assistant", "content": reply})
                            except (ConnectionError, TimeoutError, RuntimeError) as e:
                                st.error(f"{e}")

                if history and st.button("Xoá hội thoại với khách hàng này"):
                    st.session_state["persona_chats"][persona_key] = []
                    st.rerun()

    # --- CHẾ ĐỘ 2: CHAT CHUNG VỚI TRỢ LÝ AI (KHÔNG NHẬP VAI PERSONA CỤ THỂ) ---
    else:
        if "messages" not in st.session_state:
            st.session_state.messages = [
                {"role": "assistant", "content": "Xin chào! Tôi là trợ lý phân tích marketing của MarketSim. Bạn cần hỏi gì?"}
            ]
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        if prompt := st.chat_input("Gõ câu hỏi cho trợ lý AI ở đây..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant"):
                with st.spinner("Đang suy nghĩ..."):
                    try:
                        response_text = chat_with_ollama(prompt)
                        st.markdown(response_text)
                        st.session_state.messages.append({"role": "assistant", "content": response_text})
                    except (ConnectionError, TimeoutError, RuntimeError) as e:
                        st.error(f"{e}")

# ==============================================================================
# TAB 4: LỊCH SỬ HỌC AI — theo dõi AI đã học được gì, đến đâu, qua từng lần
# doanh nghiệp tải dữ liệu lên, không chỉ trong phiên làm việc hiện tại.
# ==============================================================================
if nav_choice == "📈 Lịch sử học AI":
    section_title("Lịch sử học dữ liệu của AI")
    st.caption("Mỗi lần bạn tải file khách hàng mới lên và xác nhận mapping, hệ thống ghi lại 1 bản audit ở đây.")

    get_all_audits_fn = getattr(database_module, "get_all_learning_audits", None)
    audits = get_all_audits_fn() if get_all_audits_fn is not None else []

    if not audits:
        st.info("Chưa có lần học dữ liệu nào được ghi nhận. Hãy tải file khách hàng lên ở sidebar và xác nhận mapping.")
    else:
        summary_rows = [{
            "Thời điểm": a["created_at"],
            "Tên file": a["upload_name"],
            "Số hồ sơ": a["total_records"],
            "Dữ liệu thật (%)": a["overall_real_data_pct"],
            "Đã xác nhận?": "✅ Đã xác nhận" if a["confirmed"] else "⏳ Chưa xác nhận",
        } for a in audits]
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

        st.markdown("---")
        st.markdown("**Xem chi tiết 1 lần học:**")
        options = {f"#{a['id']} — {a['upload_name']} ({a['created_at']})": a for a in audits}
        chosen_key = st.selectbox("Chọn lần upload:", list(options.keys()), key="audit_history_select")
        chosen_audit = options[chosen_key]

        render_learning_audit_panel(
            {
                "overall_real_data_pct": chosen_audit["overall_real_data_pct"],
                "total_records": chosen_audit["total_records"],
                "field_coverage": chosen_audit["field_coverage"],
            },
            audit_id=chosen_audit["id"],
        )

        if chosen_audit.get("missing_required_fields"):
            st.warning(f"Lần này còn thiếu trường bắt buộc: {', '.join(chosen_audit['missing_required_fields'])}")

        with st.expander("Xem bảng mapping đã dùng cho lần upload này"):
            mapping_hist_df = pd.DataFrame(chosen_audit.get("mapping", []))
            if not mapping_hist_df.empty:
                st.dataframe(mapping_hist_df, use_container_width=True, hide_index=True)
            else:
                st.caption("Không có dữ liệu mapping lưu lại cho lần này.")
