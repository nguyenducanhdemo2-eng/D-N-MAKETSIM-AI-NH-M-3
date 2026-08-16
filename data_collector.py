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
import threading
import xml.etree.ElementTree as ET
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
    from pytrends.exceptions import TooManyRequestsError, ResponseError
    _PYTRENDS_AVAILABLE = True
except ImportError:
    _PYTRENDS_AVAILABLE = False

    class TooManyRequestsError(Exception):
        pass

    class ResponseError(Exception):
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

try:
    import config as _app_config
    TRENDS_CACHE_TTL_SECONDS = max(60, int(getattr(_app_config, "TRENDS_CACHE_TTL_SECONDS", 900)))
    TRENDS_STALE_CACHE_SECONDS = max(TRENDS_CACHE_TTL_SECONDS, int(getattr(_app_config, "TRENDS_STALE_CACHE_SECONDS", 86400)))
    TRENDS_CONNECT_TIMEOUT_SECONDS = max(2, int(getattr(_app_config, "TRENDS_CONNECT_TIMEOUT_SECONDS", 10)))
    TRENDS_READ_TIMEOUT_SECONDS = max(5, int(getattr(_app_config, "TRENDS_READ_TIMEOUT_SECONDS", 25)))
    TRENDS_MAX_RETRIES = max(0, min(3, int(getattr(_app_config, "TRENDS_MAX_RETRIES", 1))))
    TRENDS_BATCH_DELAY_SECONDS = max(0.0, float(getattr(_app_config, "TRENDS_BATCH_DELAY_SECONDS", 1.5)))
except (ImportError, TypeError, ValueError):
    TRENDS_CACHE_TTL_SECONDS = 900
    TRENDS_STALE_CACHE_SECONDS = 86400
    TRENDS_CONNECT_TIMEOUT_SECONDS = 10
    TRENDS_READ_TIMEOUT_SECONDS = 25
    TRENDS_MAX_RETRIES = 1
    TRENDS_BATCH_DELAY_SECONDS = 1.5


_TRENDS_COLUMNS = ["keyword", "trend_score", "latest_score", "peak_score", "sample_count", "search_volume"]
_TRENDS_CACHE = {}
_TRENDS_CACHE_LOCK = threading.Lock()
_TRENDS_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


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


def _trend_frame(records=None, *, status, source, message, error="", cached=False) -> pd.DataFrame:
    """Create one stable DataFrame contract plus user-facing collection metadata."""
    frame = pd.DataFrame(records or [], columns=_TRENDS_COLUMNS)
    frame.attrs.update({
        "status": status,
        "source": source,
        "message": message,
        "error": str(error or ""),
        "cached": bool(cached),
    })
    return frame


def _copy_trend_frame(frame: pd.DataFrame, **meta_updates) -> pd.DataFrame:
    copied = frame.copy(deep=True)
    copied.attrs = dict(getattr(frame, "attrs", {}) or {})
    copied.attrs.update(meta_updates)
    return copied


def _trend_cache_key(keywords, timeframe, geo):
    return (tuple(str(item).strip().lower() for item in keywords), str(timeframe), str(geo).upper())


def _get_cached_trends(cache_key, max_age_seconds):
    now = time.time()
    with _TRENDS_CACHE_LOCK:
        cached = _TRENDS_CACHE.get(cache_key)
        if not cached:
            return None
        stored_at, frame = cached
        age = max(0, now - stored_at)
        if age > max_age_seconds:
            return None
        return _copy_trend_frame(frame, cache_age_seconds=int(age), cached=True)


def _store_trends_cache(cache_key, frame):
    if frame is None or frame.empty:
        return
    with _TRENDS_CACHE_LOCK:
        _TRENDS_CACHE[cache_key] = (time.time(), _copy_trend_frame(frame))


def _normalize_trend_keywords(keywords):
    if isinstance(keywords, str):
        keywords = keywords.split(",")
    normalized = []
    seen = set()
    for item in keywords or []:
        value = str(item or "").strip()
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            normalized.append(value)
    return normalized


def _classify_trends_error(exc):
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    text = f"{type(exc).__name__}: {exc}"
    lowered = text.lower()
    if isinstance(exc, TooManyRequestsError) or status_code == 429 or " 429" in lowered or "code 429" in lowered:
        return "rate_limited", "Google Trends đang giới hạn tần suất truy cập (HTTP 429)."
    if status_code == 403 or " 403" in lowered or "code 403" in lowered or "forbidden" in lowered:
        return "blocked", "Google Trends đang từ chối truy cập từ địa chỉ máy chủ này (HTTP 403)."
    if isinstance(exc, (requests.Timeout, TimeoutError)) or "timed out" in lowered or "timeout" in lowered:
        return "timeout", "Kết nối Google Trends quá thời gian chờ."
    return "upstream_error", "Google Trends hoặc Pytrends trả về phản hồi không hợp lệ."


def _new_pytrends_client():
    # pytrends 4.9 still uses urllib3's removed `method_whitelist` argument when
    # its built-in retries are enabled. Keep retries at zero here and retry
    # transient failures explicitly below so modern urllib3 remains compatible.
    return TrendReq(
        hl="vi-VN",
        tz=420,
        timeout=(TRENDS_CONNECT_TIMEOUT_SECONDS, TRENDS_READ_TIMEOUT_SECONDS),
        retries=0,
        backoff_factor=0,
        requests_args={"headers": {"User-Agent": _TRENDS_USER_AGENT}},
    )


def _fetch_pytrends_interest(keywords, timeframe, geo):
    records = []
    last_status = "empty"
    last_message = "Pytrends không trả dữ liệu cho các từ khóa đã cấu hình."
    last_error = ""

    for start in range(0, len(keywords), 5):
        batch = keywords[start:start + 5]
        batch_ok = False
        for attempt in range(TRENDS_MAX_RETRIES + 1):
            try:
                client = _new_pytrends_client()
                client.build_payload(batch, timeframe=timeframe, geo=geo)
                trend_df = client.interest_over_time()
                if trend_df is not None and not trend_df.empty:
                    for keyword in batch:
                        if keyword not in trend_df.columns:
                            continue
                        values = pd.to_numeric(trend_df[keyword], errors="coerce").dropna()
                        if values.empty:
                            continue
                        records.append({
                            "keyword": keyword,
                            "trend_score": round(float(values.mean()), 2),
                            "latest_score": round(float(values.iloc[-1]), 2),
                            "peak_score": round(float(values.max()), 2),
                            "sample_count": int(values.size),
                            "search_volume": None,
                        })
                batch_ok = True
                break
            except Exception as exc:
                last_status, last_message = _classify_trends_error(exc)
                last_error = f"{type(exc).__name__}: {exc}"
                # Retrying a block/rate-limit immediately makes the block worse.
                if last_status in {"rate_limited", "blocked"} or attempt >= TRENDS_MAX_RETRIES:
                    break
                time.sleep(min(4.0, 1.0 * (2 ** attempt)))

        if not batch_ok:
            if records:
                return _trend_frame(
                    records,
                    status="partial",
                    source="Google Trends (Pytrends)",
                    message=f"Đã lấy một phần dữ liệu. {last_message}",
                    error=last_error,
                )
            return _trend_frame(
                status=last_status,
                source="Google Trends (Pytrends)",
                message=last_message,
                error=last_error,
            )

        if start + 5 < len(keywords) and TRENDS_BATCH_DELAY_SECONDS:
            time.sleep(TRENDS_BATCH_DELAY_SECONDS)

    if records:
        return _trend_frame(
            records,
            status="live",
            source="Google Trends (Pytrends)",
            message=f"Đã cập nhật {len(records)} từ khóa trực tiếp từ Google Trends.",
        )
    return _trend_frame(
        status="empty",
        source="Google Trends (Pytrends)",
        message="Pytrends kết nối thành công nhưng không có dữ liệu cho từ khóa và khoảng thời gian đã chọn.",
    )


def _parse_approx_traffic(value):
    text = str(value or "").upper().replace(",", "").replace("+", "").strip()
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*([KMB]?)", text)
    if not match:
        return 0
    multipliers = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
    return int(float(match.group(1)) * multipliers.get(match.group(2), 1))


def _xml_local_text(node, local_name):
    for child in list(node):
        if str(child.tag).split("}")[-1] == local_name:
            return (child.text or "").strip()
    return ""


def _fetch_google_trends_rss(geo, reason_message=""):
    """Fallback to Google's exported Trending Now RSS when the unofficial API is blocked."""
    try:
        response = requests.get(
            "https://trends.google.com/trending/rss",
            params={"geo": str(geo or "VN").upper()},
            headers={"User-Agent": _TRENDS_USER_AGENT, "Accept": "application/rss+xml, application/xml;q=0.9"},
            timeout=(TRENDS_CONNECT_TIMEOUT_SECONDS, TRENDS_READ_TIMEOUT_SECONDS),
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
        raw_items = []
        seen = set()
        for item in root.findall(".//item"):
            title = _xml_local_text(item, "title")
            if not title or title.casefold() in seen:
                continue
            seen.add(title.casefold())
            traffic_text = _xml_local_text(item, "approx_traffic")
            raw_items.append((title, traffic_text, _parse_approx_traffic(traffic_text)))
        if not raw_items:
            return _trend_frame(
                status="rss_empty",
                source="Google Trends RSS",
                message="Google Trends RSS đã phản hồi nhưng không có xu hướng cho khu vực này.",
            )

        max_volume = max((item[2] for item in raw_items), default=0)
        records = []
        for rank, (title, traffic_text, volume) in enumerate(raw_items[:20], start=1):
            score = round((volume / max_volume) * 100, 2) if max_volume else round(max(1.0, 101.0 - rank * 5.0), 2)
            records.append({
                "keyword": title,
                "trend_score": score,
                "latest_score": score,
                "peak_score": score,
                "sample_count": 1,
                "search_volume": traffic_text or None,
            })
        prefix = f"{reason_message} " if reason_message else ""
        return _trend_frame(
            records,
            status="rss_fallback",
            source="Google Trends RSS",
            message=f"{prefix}Đang hiển thị {len(records)} xu hướng mới nhất từ RSS chính thức của Google Trends.",
        )
    except Exception as exc:
        status, message = _classify_trends_error(exc)
        return _trend_frame(
            status=f"rss_{status}",
            source="Google Trends RSS",
            message=f"Không thể lấy cả dữ liệu Pytrends lẫn Google Trends RSS. {message}",
            error=f"{type(exc).__name__}: {exc}",
        )


def fetch_pytrends(keywords=None, timeframe=TRENDS_TIMEFRAME, geo=TRENDS_GEO) -> pd.DataFrame:
    """Collect Trends data without crashing the API when Google's unofficial endpoint changes.

    Pytrends remains the primary source for configured keywords. A short-lived
    cache prevents repeated clicks from creating a burst of Google requests.
    If Google blocks the unofficial endpoint, the function first reuses a stale
    successful result and then falls back to Google's exported Trending Now RSS.
    Status, source and a Vietnamese explanation are stored in ``DataFrame.attrs``.
    """
    print("[1a] Đang lấy dữ liệu xu hướng từ Google Trends...")
    normalized_keywords = _normalize_trend_keywords(keywords or TREND_KEYWORDS)
    cache_key = _trend_cache_key(normalized_keywords, timeframe, geo)

    fresh = _get_cached_trends(cache_key, TRENDS_CACHE_TTL_SECONDS)
    if fresh is not None:
        age = int(fresh.attrs.get("cache_age_seconds", 0))
        return _copy_trend_frame(
            fresh,
            status="cache",
            message=f"Dùng dữ liệu Google Trends đã cập nhật cách đây {age} giây để tránh gửi yêu cầu lặp.",
            cached=True,
        )

    if not normalized_keywords:
        return _trend_frame(
            status="invalid_config",
            source="Google Trends",
            message="Chưa cấu hình từ khóa. Hãy thêm TREND_KEYWORDS trong file .env.",
        )

    if _PYTRENDS_AVAILABLE:
        primary = _fetch_pytrends_interest(normalized_keywords, timeframe, geo)
    else:
        primary = _trend_frame(
            status="unavailable",
            source="Google Trends (Pytrends)",
            message="Máy chủ chưa cài Pytrends. Hãy chạy pip install -r requirements.txt rồi khởi động lại.",
            error="ModuleNotFoundError: pytrends",
        )

    if not primary.empty:
        _store_trends_cache(cache_key, primary)
        return primary

    stale = _get_cached_trends(cache_key, TRENDS_STALE_CACHE_SECONDS)
    if stale is not None:
        age = int(stale.attrs.get("cache_age_seconds", 0))
        return _copy_trend_frame(
            stale,
            status="stale_cache",
            source=f"{stale.attrs.get('source', 'Google Trends')} (bộ nhớ đệm)",
            message=f"{primary.attrs.get('message', '')} Đang dùng bản gần nhất cách đây {age} giây.",
            error=primary.attrs.get("error", ""),
            cached=True,
        )

    fallback = _fetch_google_trends_rss(geo, primary.attrs.get("message", ""))
    if not fallback.empty:
        _store_trends_cache(cache_key, fallback)
        return fallback

    combined_error = "; ".join(filter(None, [primary.attrs.get("error", ""), fallback.attrs.get("error", "")]))
    return _copy_trend_frame(
        fallback,
        status=primary.attrs.get("status", fallback.attrs.get("status", "upstream_error")),
        message=fallback.attrs.get("message") or primary.attrs.get("message"),
        error=combined_error,
    )


def fetch_google_trends(keywords=None, timeframe=TRENDS_TIMEFRAME, geo=TRENDS_GEO) -> pd.DataFrame:
    """Backward-compatible name used by the offline/online collection pipeline."""
    return fetch_pytrends(keywords=keywords, timeframe=timeframe, geo=geo)


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

    # Mapping schema giờ 2 lớp (xem schema_mapper.py):
    #  (1) rule-based tự khớp NGAY cột tên rõ ràng, không cần Ollama
    #  (2) Ollama CHỈ xử lý cột còn lại, TỪNG CỘT MỘT (không phải cả mảng cùng
    #      lúc) để giảm rủi ro model 7B trả JSON hỏng. Lỗi ở 1 cột không làm
    #      hỏng kết quả của các cột khác -- vẫn báo lỗi rõ theo từng cột, không
    #      âm thầm đoán mò (đúng yêu cầu đã xác nhận).
    from schema_mapper import map_columns_with_ai, missing_required_fields, failed_columns

    ai_mapping = map_columns_with_ai(columns, raw_fields_list)
    failed_cols = failed_columns(ai_mapping)
    mapping_error = None
    if failed_cols:
        mapping_error = "; ".join(f"cột '{f['source_column']}': {f['reasoning']}" for f in failed_cols)

    mapping = [
        {
            "source_column": m["source_column"],
            "ai_column": m["canonical_field"],
            "confidence": m["confidence"],
            "editable": True,
            "confidence_display": m["confidence_display"],
            "reasoning": m.get("reasoning", ""),
            "source": m.get("source", "ai"),
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
