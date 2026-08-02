# ==============================================================================
# DATA_COLLECTOR.PY - BƯỚC 1: THU THẬP DỮ LIỆU
#   - pytrends       -> xu hướng tìm kiếm Google Trends
#   - BeautifulSoup   -> tin tức nóng trong ngày
#   - Regex           -> làm sạch văn bản thô
#   - Tự sinh dữ liệu mẫu nếu thư mục DATA trống
#   - MỚI: cho phép nạp file khách hàng trực tiếp từ web (upload), không cần lưu ổ cứng
#   - MỚI: enable_online_scrape để tắt cào online khi cần chạy nhanh / mạng yếu
# ==============================================================================
import os
import re
import time
import json
import requests
import pandas as pd
import random
import glob
from datetime import datetime

try:
    from database import load_persisted_uploaded_records, load_canonical_customers
except ImportError:
    load_persisted_uploaded_records = None
    load_canonical_customers = None

# Các thư viện cào dữ liệu online là TUỲ CHỌN - nếu máy chưa cài (hoặc cài lỗi),
# ứng dụng vẫn phải chạy được với dữ liệu khách hàng thật / file upload, không crash.
try:
    from bs4 import BeautifulSoup
    _BS4_AVAILABLE = True
except ImportError:
    _BS4_AVAILABLE = False

try:
    from pytrends.request import TrendReq
    from pytrends.exceptions import TooManyRequestsError
    _PYTRENDS_AVAILABLE = True
except ImportError:
    _PYTRENDS_AVAILABLE = False

    class TooManyRequestsError(Exception):
        pass

# Đảm bảo import an toàn từ config.py
try:
    from config import TREND_KEYWORDS, NEWS_URLS, TRENDS_TIMEFRAME, TRENDS_GEO, MAX_UPLOAD_BYTES
except ImportError:
    TREND_KEYWORDS = ["mỹ phẩm", "công nghệ", "kinh doanh"]
    NEWS_URLS = ["https://vnexpress.net"]
    TRENDS_TIMEFRAME = "today 12-m"
    TRENDS_GEO = "VN"
    MAX_UPLOAD_BYTES = 1_000_000_000
except AttributeError:
    from config import TREND_KEYWORDS, NEWS_URLS, TRENDS_TIMEFRAME, TRENDS_GEO
    MAX_UPLOAD_BYTES = 1_000_000_000


def clean_text(raw_text: str) -> str:
    """Làm sạch văn bản thô: loại thẻ HTML còn sót, URL, ký tự rác, khoảng trắng thừa."""
    if not raw_text:
        return ""
    text = re.sub(r"<[^>]+>", " ", str(raw_text))          # loại thẻ HTML
    text = re.sub(r"http\S+|www\.\S+", " ", text)          # loại URL
    text = re.sub(r"[^\w\sÀ-ỹ]", " ", text)                # giữ chữ/số/dấu tiếng Việt
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _get_first_value(row, candidate_names, default=""):
    """Lấy giá trị đầu tiên hợp lệ từ nhiều tên cột có thể khác nhau."""
    for name in candidate_names:
        if name in row:
            value = row.get(name)
            if pd.notna(value):
                if isinstance(value, str):
                    return value.strip()
                return str(value)
    return default


def _normalize_json_value(value):
    if pd.isna(value):
        return None
    if isinstance(value, (str, bool, int, float)):
        return value
    try:
        if isinstance(value, (pd.Timestamp,)):
            return str(value)
        if isinstance(value, (pd.Int64Dtype, pd.Float64Dtype)):
            return value.item()
    except Exception:
        pass
    try:
        return int(value)
    except (ValueError, TypeError, OverflowError):
        pass
    try:
        return float(value)
    except (ValueError, TypeError, OverflowError):
        pass
    try:
        return str(value)
    except Exception:
        return None


def _reset_file_pointer(file_source):
    try:
        file_source.seek(0)
    except Exception:
        pass


def _try_read_csv(file_source, **kwargs):
    _reset_file_pointer(file_source)
    encodings = ["utf-8-sig", "utf-8", "cp1252", "latin1", "utf-16"]
    sep_options = [None, ",", ";", "\t"]

    for encoding in encodings:
        for sep in sep_options:
            _reset_file_pointer(file_source)
            try:
                if sep is None:
                    return pd.read_csv(file_source, encoding=encoding, engine="python", sep=None, dtype=str, low_memory=False, **kwargs)
                return pd.read_csv(file_source, encoding=encoding, sep=sep, engine="python", dtype=str, low_memory=False, **kwargs)
            except Exception:
                continue

    _reset_file_pointer(file_source)
    return pd.read_csv(file_source, encoding="utf-8-sig", dtype=str, low_memory=False, **kwargs)


def _read_dataframe(source, source_name="file") -> pd.DataFrame:
    """Đọc được cả CSV/XLSX từ đường dẫn hoặc file-like object, với fallback encoding."""
    try:
        if isinstance(source, str):
            filename = source
            if filename.lower().endswith((".xlsx", ".xls")):
                return pd.read_excel(source, dtype=str)
            return _try_read_csv(source)

        filename = getattr(source, "name", source_name) or source_name
        if filename.lower().endswith((".xlsx", ".xls")):
            _reset_file_pointer(source)
            return pd.read_excel(source, dtype=str)

        return _try_read_csv(source)
    except Exception as e:
        raise ValueError(f"Không đọc được file '{filename}'. Hãy chắc chắn đây là file CSV/XLSX hợp lệ. Chi tiết: {e}")


def _aggregate_generic_row_text(row):
    """Ghép các cột có giá trị của một dòng thành một mô tả văn bản chung."""
    pieces = []
    try:
        row_dict = row.to_dict()
    except Exception:
        row_dict = dict(row)

    # Nếu có các cột gợi ý chuyên biệt, giữ lại chúng trước.
    interest = _get_first_value(row_dict, ["tu_khoa_so_thich", "so_thich", "interests", "interest", "preferences", "mo_ta"], "")
    job = _get_first_value(row_dict, ["nghe_nghiep", "job", "profession", "nghe_nghiep_kh", "nghe"], "")
    pain = _get_first_value(row_dict, ["noi_dau_khach_hang", "pain_point", "pain", "van_de", "problem", "mo_ta_van_de"], "")
    trait = _get_first_value(row_dict, ["tinh_cach", "personality", "character", "dac_diem"], "")

    if interest:
        pieces.append(f"Sở thích: {interest}")
    if job:
        pieces.append(f"Nghề nghiệp: {job}")
    if pain:
        pieces.append(f"Nỗi đau: {pain}")
    if trait:
        pieces.append(f"Tính cách: {trait}")

    # Dùng tất cả cột còn lại làm dữ liệu ngữ nghĩa nếu có thể.
    generic_parts = []
    for key, value in row_dict.items():
        if value is None or pd.isna(value):
            continue
        if key in {"tu_khoa_so_thich", "so_thich", "interests", "interest", "preferences", "mo_ta",
                   "nghe_nghiep", "job", "profession", "nghe_nghiep_kh", "nghe",
                   "noi_dau_khach_hang", "pain_point", "pain", "van_de", "problem", "mo_ta_van_de",
                   "tinh_cach", "personality", "character", "dac_diem", "tuoi", "age", "tuoi_khach_hang"}:
            continue
        if isinstance(value, str) and value.strip():
            generic_parts.append(f"{key}: {value.strip()}")
        elif isinstance(value, (int, float)):
            generic_parts.append(f"{key}: {value}")

    if generic_parts:
        pieces.append(". ".join(generic_parts))

    return " ".join(pieces).strip()


def fetch_google_trends(keywords=None, timeframe=TRENDS_TIMEFRAME, geo=TRENDS_GEO) -> pd.DataFrame:
    print("[1a] Đang lấy dữ liệu xu hướng từ Google Trends...")
    if not _PYTRENDS_AVAILABLE:
        print("    ⚠ Chưa cài thư viện 'pytrends' (pip install pytrends). Bỏ qua Google Trends.")
        return pd.DataFrame()

    keywords = keywords or TREND_KEYWORDS
    try:
        pytrends = TrendReq(hl="vi-VN", tz=420)
    except Exception as e:
        print(f"    ⚠ Không khởi tạo được kết nối Google Trends: {e}")
        return pd.DataFrame()

    records = []
    for i in range(0, len(keywords), 5):
        batch = keywords[i:i + 5]
        try:
            pytrends.build_payload(batch, timeframe=timeframe, geo=geo)
            trend_df = pytrends.interest_over_time()
            if not trend_df.empty:
                for kw in batch:
                    if kw in trend_df.columns:
                        records.append({"keyword": kw, "trend_score": float(trend_df[kw].mean())})
            time.sleep(2)
        except TooManyRequestsError:
            print("    ⚠ CẢNH BÁO: Bị Google chặn (429). Đang bỏ qua Google Trends để tránh lỗi...")
            return pd.DataFrame()
        except Exception as e:
            print(f"    ⚠ Lỗi không xác định khi lấy Google Trends: {e}")
            return pd.DataFrame()

    return pd.DataFrame(records)


def fetch_news(urls=None) -> list:
    """Thu thập tiêu đề tin tức nóng trong ngày từ các nguồn online bằng BeautifulSoup."""
    print("[1b] Đang thu thập tin tức nóng trong ngày...")
    if not _BS4_AVAILABLE:
        print("    ⚠ Chưa cài thư viện 'beautifulsoup4' (pip install beautifulsoup4). Bỏ qua tin tức online.")
        return []

    urls = urls or NEWS_URLS
    headers = {"User-Agent": "Mozilla/5.0 (MarketSim-AI Data Collector)"}
    headlines = []

    for url in urls:
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            candidates = soup.find_all(["h1", "h2", "h3"])
            for tag in candidates:
                title = clean_text(tag.get_text())
                if len(title) > 15:
                    headlines.append(title)
        except requests.RequestException as e:
            print(f"    ⚠ Không thể lấy dữ liệu từ {url}: {e}")
        except Exception as e:
            print(f"    ⚠ Lỗi không xác định khi cào {url}: {e}")

    headlines = list(dict.fromkeys(headlines))  # loại trùng lặp, giữ thứ tự
    print(f"    ✔ Đã thu thập {len(headlines)} tiêu đề tin tức.")
    return headlines


def _normalize_column_name(column_name) -> str:
    if column_name is None:
        return ""
    text = str(column_name).strip().lower()
    text = text.replace(" ", "_")
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def _infer_canonical_column(column_name: str) -> tuple:
    normalized = _normalize_column_name(column_name)
    if not normalized:
        return "unknown_column", 0.25

    # Bộ quy tắc ánh xạ khớp 100% với MASTER_SCHEMA trong data_preprocessor.py
    rules = {
        "customer_id": ["ma_kh", "id", "customer_id", "stt", "makh", "khach_hang"],
        "age": ["tuoi", "age", "nam_sinh", "dob", "tuoi_kh", "do_tuoi"],
        "gender": ["gioi_tinh", "gender", "sex", "phai", "gioitinh"],
        "location": ["dia_chi", "khu_vuc", "location", "tinh_thanh", "region", "dia_ban"],
        "total_spending": ["gia_tri_don_hang", "chi_tieu", "thu_nhap", "spending", "doanh_thu", "price", "tong_tien", "thu_nhap_thang"],
        "last_purchase_date": ["ngay_mua", "lan_cuoi", "date", "ngay_dat", "ngay", "created_at", "tan_suat_mua"],
        "job": ["nghe_nghiep", "job", "linh_vuc", "chuyen_mon", "nganh_nghe", "chuc_vu"],
        "pain_point": ["noi_dau", "van_de", "pain_point", "kho_khan", "thach_thuc", "khieu_nai"],
        "personality": ["tinh_cach", "hanh_vi", "yeu_to_quyet_dinh", "personality", "so_thich", "tu_khoa", "hanh_vi_tuong_tac"]
    }

    # 1. So khớp chính xác tuyệt đối (Độ tin cậy 99%)
    for canonical, aliases in rules.items():
        if normalized in aliases:
            return canonical, 0.99

    # 2. So khớp chứa từ khóa (Độ tin cậy 85%)
    for canonical, aliases in rules.items():
        for alias in aliases:
            if alias in normalized or normalized in alias:
                return canonical, 0.85

    return "unknown_column", 0.35


def _parse_date_value(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    cleaned = text.replace("Z", "")
    for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"]:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return None


def build_ai_learning_report(records: list, file_name: str = "uploaded_file") -> dict:
    """Tạo báo cáo AI Understanding Report cho một file dữ liệu upload mới."""
    records = records or []

    raw_fields_list = []
    for record in records:
        if isinstance(record, dict):
            raw_fields = record.get("raw_fields", {})
            if isinstance(raw_fields, dict):
                raw_fields_list.append(raw_fields)

    if not raw_fields_list:
        return {
            "file_name": file_name,
            "business_type": "Doanh nghiệp chưa xác định",
            "business_confidence": 0.35,
            "total_customers": 0,
            "total_orders": 0,
            "date_range": "Không xác định",
            "column_count": 0,
            "valid_columns": 0,
            "missing_columns": 0,
            "mapping": [],
            "insights": ["Không có dữ liệu để phân tích."],
        }

    combined_text = " ".join([
        str(record.get("text", "")) for record in records if isinstance(record, dict)
    ]).lower()
    if any(keyword in combined_text for keyword in ["studio", "chụp ảnh", "photo", "ảnh"]):
        business_type = "Studio chụp ảnh"
        business_confidence = 0.985
    elif any(keyword in combined_text for keyword in ["shop", "cửa hàng", "bán lẻ", "sản phẩm", "product"]):
        business_type = "Cửa hàng bán lẻ"
        business_confidence = 0.94
    elif any(keyword in combined_text for keyword in ["dịch vụ", "service", "booking", "reservation"]):
        business_type = "Doanh nghiệp dịch vụ"
        business_confidence = 0.91
    else:
        business_type = "Doanh nghiệp chưa xác định"
        business_confidence = 0.62

    ordered_columns = []
    seen_columns = set()
    for raw_fields in raw_fields_list:
        for column in raw_fields.keys():
            if column not in seen_columns:
                seen_columns.add(column)
                ordered_columns.append(column)

    columns = ordered_columns

    # Mapping schema giờ do Ollama đảm nhiệm (xem schema_mapper.py), dựa trên
    # tên cột + giá trị mẫu thực tế, thay vì chỉ so khớp alias cứng như trước.
    # KHÔNG fallback ngầm nếu Ollama lỗi -- báo lỗi rõ ràng để người dùng biết
    # và tự map tay qua bảng chỉnh sửa trên UI (theo yêu cầu đã xác nhận).
    from schema_mapper import map_columns_with_ai, missing_required_fields, SchemaMappingError

    mapping_error = None
    ai_mapping = []
    try:
        ai_mapping = map_columns_with_ai(columns, raw_fields_list)
    except SchemaMappingError as e:
        mapping_error = str(e)

    mapping = [
        {
            "source_column": m["source_column"],
            "ai_column": m["canonical_field"],
            "confidence": m["confidence"],
            "editable": True,
            "confidence_display": m["confidence_display"],
            "reasoning": m.get("reasoning", ""),
        }
        for m in ai_mapping
    ]

    missing_required = missing_required_fields(ai_mapping) if ai_mapping else []
    valid_columns = sum(1 for item in mapping if item["confidence"] >= 0.7 and item["ai_column"] != "unmapped")
    missing_columns = max(0, len(mapping) - valid_columns)

    total_orders = len(records)
    for column in columns:
        values = []
        for raw_fields in raw_fields_list:
            value = raw_fields.get(column)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values.append(float(value))
        if values and any(token in _normalize_column_name(column) for token in ["order", "don_hang", "so_don", "orders"]):
            total_orders = int(sum(values))
            break

    parsed_dates = []
    for column in ["order_date", "date", "created_at", "ngay_dat", "ngay", "created"]:
        if column in columns:
            for raw_fields in raw_fields_list:
                parsed_date = _parse_date_value(raw_fields.get(column))
                if parsed_date is not None:
                    parsed_dates.append(parsed_date)
            if parsed_dates:
                break

    if parsed_dates:
        date_range = f"{min(parsed_dates).strftime('%d/%m/%Y')} - {max(parsed_dates).strftime('%d/%m/%Y')}"
    else:
        date_range = "Không xác định"

    insights = [
        f"Loại doanh nghiệp: {business_type}",
        f"Độ tin cậy nhận diện: {int(business_confidence * 100)}%",
        f"Tổng số khách hàng: {len(records)}",
        f"Tổng số đơn hàng: {total_orders}",
        f"Khoảng thời gian dữ liệu: {date_range}",
        f"Số cột: {len(columns)}",
        f"Số trường hợp lệ: {valid_columns}",
        f"Số trường thiếu: {missing_columns}",
    ]

    if mapping_error:
        insights.append(f"⚠ Lỗi mapping AI: {mapping_error}")
    if missing_required:
        insights.append(f"⚠ Thiếu trường bắt buộc chưa được map: {', '.join(missing_required)}")

    return {
        "file_name": file_name,
        "business_type": business_type,
        "business_confidence": business_confidence,
        "total_customers": len(records),
        "total_orders": total_orders,
        "date_range": date_range,
        "column_count": len(columns),
        "valid_columns": valid_columns,
        "missing_columns": missing_columns,
        "mapping": mapping,
        "mapping_error": mapping_error,
        "missing_required_fields": missing_required,
        "insights": insights,
    }


def process_customer_rows(df: pd.DataFrame, source_label: str = "real_customer") -> list:
    """
    Hàm dùng chung: nhận 1 DataFrame khách hàng thô (đọc từ CSV/XLSX, dù từ ổ cứng
    hay từ file upload trên web) và chuẩn hoá thành list record cho pipeline.
    """
    records = []
    _NOT_FOUND = object()  # sentinel: phân biệt "không tìm thấy cột nào khớp" với "tìm thấy nhưng giá trị rỗng"
    for _, row in df.iterrows():
        row_dict = row.to_dict()
        interest_raw = _get_first_value(row_dict, ["tu_khoa_so_thich", "so_thich", "interests", "interest", "preferences", "mo_ta"], _NOT_FOUND)
        job_raw = _get_first_value(row_dict, ["nghe_nghiep", "job", "profession", "nghe_nghiep_kh", "nghe"], _NOT_FOUND)
        pain_raw = _get_first_value(row_dict, ["noi_dau_khach_hang", "pain_point", "pain", "van_de", "problem", "mo_ta_van_de"], _NOT_FOUND)
        trait_raw = _get_first_value(row_dict, ["tinh_cach", "personality", "character", "dac_diem"], _NOT_FOUND)

        # BUG CŨ: dùng default không rỗng ("Khách hàng", "Thận trọng"...) khiến điều kiện
        # "đã tìm thấy cột phù hợp" LUÔN đúng, nên nhánh _aggregate_generic_row_text()
        # (dùng để phân biệt từng dòng khi tên cột lạ) không bao giờ được gọi tới -- mọi
        # dòng không khớp alias tiếng Việt đều ra CÙNG 1 đoạn text -> bước lọc trùng lặp
        # phía dưới coi 10.000 khách hàng khác nhau là "trùng nhau" và chỉ giữ lại 1 dòng.
        found_known_column = any(v is not _NOT_FOUND and str(v).strip() for v in (interest_raw, job_raw, pain_raw, trait_raw))

        interest_value = "" if interest_raw is _NOT_FOUND else interest_raw
        job_value = "Khách hàng" if job_raw is _NOT_FOUND else job_raw
        pain_value = "Sợ mua phải sản phẩm không tốt" if pain_raw is _NOT_FOUND else pain_raw
        trait_value = "Thận trọng" if trait_raw is _NOT_FOUND else trait_raw

        if found_known_column:
            desc_text = f"{interest_value} {job_value} {pain_value} {trait_value}"
        else:
            desc_text = _aggregate_generic_row_text(row)

        try:
            age_val = _get_first_value(row_dict, ["tuoi", "age", "tuoi_khach_hang"], None)
            age_val = int(age_val) if age_val is not None and str(age_val).strip() != "" else random.randint(22, 45)
        except (ValueError, TypeError):
            age_val = random.randint(22, 45)

        raw_fields = {str(k): _normalize_json_value(v) for k, v in row_dict.items()}

        records.append({
            "text": clean_text(desc_text),
            "source": source_label,
            "weight": 2.5,
            "real_age": age_val,
            "real_job": job_value or "Khách hàng",
            "real_pain": pain_value or "Sợ mua phải sản phẩm không tốt",
            "real_trait": trait_value or "Thận trọng",
            "raw_fields": raw_fields,
        })
    return records


def load_customer_file_from_path(file_path: str, source_label: str = "local_customer") -> list:
    """Đọc trực tiếp 1 file khách hàng từ ổ cứng máy tính (CSV/XLSX) và chuẩn hoá thành dữ liệu cho AI."""
    if not file_path:
        return []
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Không tìm thấy file: {file_path}")

    if os.path.getsize(file_path) > MAX_UPLOAD_BYTES:
        raise ValueError(f"File '{os.path.basename(file_path)}' quá lớn (>1GB). Vui lòng chọn file nhỏ hơn 1GB.")

    name = os.path.basename(file_path)
    df = _read_dataframe(file_path, source_name=name)

    if df.empty:
        raise ValueError(f"File '{name}' không chứa dữ liệu nào.")

    return preprocess_customer_records(process_customer_rows(df, source_label=source_label))


def preprocess_customer_records(records: list) -> list:
    """Loại bỏ bản ghi trùng lặp và chuẩn hoá text trước khi vào pipeline AI.
    Khóa so trùng gồm cả hash dữ liệu gốc (raw_fields), không chỉ text/job/pain
    đã suy luận -- để 2 khách hàng thật khác nhau không bao giờ bị gộp nhầm chỉ vì
    mô tả suy luận ra giống nhau (ví dụ khi file không khớp alias cột đã biết)."""
    unique_records = []
    seen = set()
    for record in records:
        text = clean_text(record.get("text", ""))
        if not text:
            continue

        raw_fields = record.get("raw_fields", {}) or {}
        raw_signature = json.dumps(raw_fields, sort_keys=True, ensure_ascii=False, default=str)

        key = (
            text.strip().lower(),
            str(record.get("real_job", "")).strip().lower(),
            str(record.get("real_pain", "")).strip().lower(),
            raw_signature,
        )
        if key in seen:
            continue
        seen.add(key)
        record["text"] = text
        unique_records.append(record)

    return unique_records


def load_uploaded_dataframe(uploaded_file) -> list:
    """
    MỚI: Đọc trực tiếp 1 file được tải lên qua giao diện web (Streamlit UploadedFile),
    KHÔNG cần lưu vào ổ cứng trước. Ném ValueError với thông điệp rõ ràng nếu lỗi,
    để giao diện web hiển thị lỗi thân thiện thay vì crash.
    """
    if uploaded_file is None:
        return []
    name = getattr(uploaded_file, "name", "file")
    df = _read_dataframe(uploaded_file, source_name=name)

    if df.empty:
        raise ValueError(f"File '{name}' không chứa dữ liệu nào.")

    return preprocess_customer_records(process_customer_rows(df, source_label="web_upload"))


def load_real_customer_data(folder_path="DATA") -> list:
    """Tự động quét toàn bộ file trong thư mục DATA/ và nạp hết vào AI.
    Nếu không có file nào, tự sinh một file mẫu CSV có đầy đủ tiếng Việt chuẩn chỉnh."""
    all_records = []

    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
        print(f"⚠️ Thư mục '{folder_path}' chưa tồn tại. Đã tự động tạo mới.")

    files = glob.glob(os.path.join(folder_path, "*.csv")) + glob.glob(os.path.join(folder_path, "*.xlsx"))

    if not files:
        sample_file_path = os.path.join(folder_path, "khach_hang_mau.csv")
        print(f"📂 Không tìm thấy file dữ liệu nào trong thư mục {folder_path}/")
        print(f"💡 Đang tự động sinh file dữ liệu mẫu: '{sample_file_path}'...")

        sample_data = {
            "tu_khoa_so_thich": [
                "mỹ phẩm thiên nhiên, skincare Hàn Quốc, son môi không chì",
                "laptop gaming cấu hình cao, bàn phím cơ, đồ công nghệ mới",
                "khóa học chạy quảng cáo Facebook, xây kênh Tiktok, MMO",
                "tour du lịch tự túc Sapa, homestay đẹp, chụp ảnh phong cảnh",
                "chế độ ăn kiêng Keto, bột protein, phòng tập gym chất lượng cao"
            ],
            "nghe_nghiep": [
                "Nhân viên văn phòng", "Lập trình viên", "Chủ shop online",
                "Nhiếp ảnh gia tự do", "Huấn luyện viên cá nhân (PT)"
            ],
            "noi_dau_khach_hang": [
                "Da nhạy cảm dễ kích ứng, lo sợ hóa chất độc hại",
                "Máy tính cũ chạy chậm, đau mỏi vai gáy do ngồi lâu",
                "Chi phí quảng cáo ngày càng đắt, không biết cách viết content",
                "Không có thời gian lên lịch trình chi tiết, sợ bị chặt chém giá",
                "Cân nặng khó giảm, không duy trì được kỷ luật tự tập"
            ],
            "tuoi": [24, 28, 32, 27, 30],
            "tinh_cach": [
                "Cẩn thận, thích làm đẹp", "Thực tế, đam mê công nghệ",
                "Năng động, thích thử thách", "Tự do, bay bổng, hướng ngoại",
                "Kiên trì, thích kỷ luật"
            ]
        }

        df_sample = pd.DataFrame(sample_data)
        df_sample.to_csv(sample_file_path, index=False, encoding="utf-8-sig")
        print(f"✔ Đã sinh file mẫu thành công! Bạn có thể mở file này để điền dữ liệu thật.")
        files = [sample_file_path]

    for file_path in files:
        print(f"📂 Đang tự động nạp dữ liệu từ: {file_path}")
        try:
            if file_path.endswith(".xlsx"):
                df = pd.read_excel(file_path, dtype=str)
            else:
                df = pd.read_csv(file_path, encoding="utf-8-sig", dtype=str, low_memory=False)
            all_records.extend(process_customer_rows(df, source_label="real_customer"))
        except Exception as e:
            print(f"    ⚠ Lỗi đọc file {file_path}: {e}")

    all_records = preprocess_customer_records(all_records)
    print(f"    ✔ Tổng cộng đã nạp {len(all_records)} hồ sơ từ thư mục {folder_path}!")
    return all_records


def canonical_records_to_pipeline_format(canonical_rows: list) -> list:
    """
    CẦU NỐI: chuyển dữ liệu đã CHUẨN HÓA (từ bảng canonical_customers, xem
    schema_mapper.py + database.save_canonical_customers) sang định dạng mà
    clustering.py (TF-IDF trên cột 'text') và persona_simulator.py
    (real_age/real_job/real_pain/real_trait) đang tiêu thụ.

    Đây là nơi DUY NHẤT nối dữ liệu đã chuẩn hóa vào pipeline AI — thay thế
    hoàn toàn cho việc process_customer_rows() tự đoán cột bằng alias cứng
    (bộ alias đó vẫn còn để đọc các file KHÔNG đi qua bước chuẩn hóa AI,
    xem load_customer_file_from_path/load_uploaded_dataframe bên dưới).
    """
    records = []
    for row in canonical_rows or []:
        interest = str(row.get("interest_keywords") or "").strip()
        job = str(row.get("job") or "Khách hàng").strip() or "Khách hàng"
        pain = str(row.get("pain_point") or "Sợ mua phải sản phẩm không tốt").strip()
        trait = str(row.get("personality") or "Thận trọng").strip()

        desc_text = f"{interest} {job} {pain} {trait}".strip()
        try:
            age_val = int(row.get("age")) if row.get("age") not in (None, "") else random.randint(22, 45)
        except (ValueError, TypeError):
            age_val = random.randint(22, 45)

        records.append({
            "text": clean_text(desc_text),
            "source": "canonical",
            "weight": 3.0,
            "real_age": age_val,
            "real_job": job,
            "real_pain": pain or "Sợ mua phải sản phẩm không tốt",
            "real_trait": trait or "Thận trọng",
            "raw_fields": row,
        })
    return records


def collect_all(uploaded_records: list = None, enable_online_scrape: bool = True, local_customer_file: str = None) -> pd.DataFrame:
    """
    Chạy toàn bộ Bước 1: GỘP CHUNG dữ liệu trực tuyến (Trends + News),
    dữ liệu khách hàng thực tế trong thư mục DATA/, và (MỚI) dữ liệu khách hàng
    được người dùng tải lên trực tiếp qua giao diện web (uploaded_records),
    hoặc đọc trực tiếp từ 1 file khách hàng trên máy qua local_customer_file.

    uploaded_records     : list record đã xử lý sẵn từ load_uploaded_dataframe() (có thể None)
    enable_online_scrape : False -> bỏ qua Google Trends & tin tức online (chạy nhanh, ổn định hơn)
    local_customer_file  : đường dẫn tới 1 file CSV/XLSX khách hàng trên máy tính
    """
    print("\n[1] BƯỚC 1: THU THẬP & HỢP NHẤT DỮ LIỆU (ONLINE + OFFLINE)\n")

    records = []

    # 1. Thu thập dữ liệu trực tuyến (Online Scraper) - có thể tắt để chạy nhanh/ổn định hơn
    if enable_online_scrape:
        trends_df = fetch_google_trends()
        headlines = fetch_news()

        if trends_df is not None and not trends_df.empty:
            for _, row in trends_df.iterrows():
                records.append({
                    "text": clean_text(row["keyword"]),
                    "source": "google_trends",
                    "weight": row["trend_score"],
                })

        for h in headlines:
            records.append({"text": h, "source": "news", "weight": 1.0})
    else:
        print("    ⏭ Đã tắt cào dữ liệu online theo yêu cầu.")

    # 2. NGUỒN CHUẨN ƯU TIÊN: dữ liệu đã được AI map + người dùng xác nhận,
    #    lưu trong bảng canonical_customers (xem schema_mapper.py). Đây là
    #    dữ liệu "sạch" nhất vì đã qua bước ánh xạ schema + bù dữ liệu thiếu.
    canonical_used = False
    if load_canonical_customers is not None:
        canonical_rows = load_canonical_customers()
        if canonical_rows:
            print(f"    ✔ Dùng {len(canonical_rows)} khách hàng ĐÃ CHUẨN HÓA từ canonical_customers.")
            records.extend(canonical_records_to_pipeline_format(canonical_rows))
            canonical_used = True

    # 2b. Dữ liệu khách hàng thô CHƯA qua bước chuẩn hóa (vd người dùng chưa
    #     xác nhận mapping ở AI Learning Center) -- vẫn nạp để không chặn app,
    #     nhưng dữ liệu này chưa được ánh xạ vào canonical schema.
    if uploaded_records and not canonical_used:
        print(f"    ✔ Dùng {len(uploaded_records)} khách hàng do người dùng tải lên qua web (CHƯA chuẩn hóa schema).")
        records.extend(uploaded_records)

    if load_persisted_uploaded_records is not None and not canonical_used:
        remembered = load_persisted_uploaded_records(max_records=300)
        if remembered:
            print(f"    ✔ Thêm {len(remembered)} khách hàng ghi nhớ từ lần upload trước (CHƯA chuẩn hóa schema).")
            records.extend(remembered)

    if not uploaded_records and not canonical_used:
        if local_customer_file:
            print(f"    ✔ Đang đọc file khách hàng cục bộ: {local_customer_file}")
            try:
                real_records = load_customer_file_from_path(local_customer_file, source_label="local_customer")
                records.extend(real_records)
            except Exception as e:
                print(f"    ⚠ Không thể đọc file khách hàng cục bộ: {e}")
        else:
            real_records = load_real_customer_data("DATA")
            records.extend(real_records)

    # 3. Tạo DataFrame tổng hợp
    combined_df = pd.DataFrame(records)
    if not combined_df.empty:
        combined_df = combined_df[combined_df["text"].str.len() > 0].reset_index(drop=True)

    print(f"\n    ✔ TỔNG HỢP: {len(combined_df)} bản ghi đã sẵn sàng cho K-Means!\n")
    return combined_df


if __name__ == "__main__":
    df = collect_all()
    print(df.head(10))
