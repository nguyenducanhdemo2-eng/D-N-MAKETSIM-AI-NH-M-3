# ==============================================================================
# SCHEMA_MAPPER.PY - NGUON CHUAN DUY NHAT (SINGLE SOURCE OF TRUTH) CHO SCHEMA
# ==============================================================================
# Thiet ke 2 lop, on dinh hon nhieu so voi ban dau (1 lan goi Ollama cho ca
# 12+ cot -> model 7B local rat de tra JSON hong):
#   Lop 1 (RULE-BASED, nhanh, khong can AI): tu khop cot co ten ro rang/gan
#     giong alias da biet (vd "nghe_nghiep", "tuoi", "job"...). Chinh xac
#     100% cho cot dat ten chuan, khong ton chi phi goi Ollama.
#   Lop 2 (AI, tung cot mot): CHI goi Ollama cho nhung cot con lai (ten la,
#     mo ho). Moi cot 1 lan goi rieng, JSON tra ve don gian (1 object, khong
#     phai mang) -> it loi hon rat nhieu so voi bat AI tra ca mang 12 object
#     cung luc. Loi o cot nao chi lam cot do "unmapped" kem ly do, KHONG lam
#     hong toan bo cac cot khac da map duoc (rule hoac AI) -- dung tinh than
#     "khong am tham doan mo" da thong nhat: loi van duoc bao ro theo tung cot.
# ==============================================================================

import json
import re
import unicodedata
import requests
from config import OLLAMA_HOST, OLLAMA_MODEL, REQUEST_TIMEOUT_SEC


# ------------------------------------------------------------------------------
# CANONICAL SCHEMA - nguon chuan duy nhat, moi noi khac import tu day
# ------------------------------------------------------------------------------
CANONICAL_SCHEMA = {
    "customer_id":        {"type": "string",  "required": False},
    "age":                {"type": "numeric", "required": True},
    "gender":              {"type": "category", "required": False},
    "job":                {"type": "string",  "required": True},
    "location":            {"type": "string",  "required": False},
    "total_spending":      {"type": "numeric", "required": False},
    "pain_point":           {"type": "string",  "required": True},
    "personality":          {"type": "string",  "required": True},
    "interest_keywords":    {"type": "string",  "required": True},
    "last_purchase_date":   {"type": "date",    "required": False},
    # --- Customer Intelligence fields (optional, backward-compatible) ---
    "order_count":          {"type": "numeric", "required": False},
    "average_order_value":  {"type": "numeric", "required": False},
    "discount_usage":       {"type": "numeric", "required": False},
    "product_category":     {"type": "string",  "required": False},
    "channel":              {"type": "string",  "required": False},
    "device":               {"type": "string",  "required": False},
    "acquisition_source":   {"type": "string",  "required": False},
    "review_text":          {"type": "string",  "required": False},
    # --- Enterprise behavioral / CRM fields (optional) ---
    "monthly_income":        {"type": "numeric", "required": False},
    "signup_date":           {"type": "date",    "required": False},
    "return_count":          {"type": "numeric", "required": False},
    "website_visits_30d":    {"type": "numeric", "required": False},
    "email_open_rate":       {"type": "numeric", "required": False},
    "cart_abandon_rate":     {"type": "numeric", "required": False},
    "satisfaction_score":    {"type": "numeric", "required": False},
    "loyalty_tier":          {"type": "category", "required": False},
}

REQUIRED_FIELDS = [k for k, v in CANONICAL_SCHEMA.items() if v["required"]]

# ------------------------------------------------------------------------------
# LOP 1: RULE-BASED ALIAS TABLE
# ------------------------------------------------------------------------------
# Danh sach alias cho tung truong chuan, khong dau, chu thuong, _ thay khoang trang.
# Khop CHINH XAC ten cot (sau khi chuan hoa) -> confidence 0.97
# Khop MOT PHAN (alias nam trong ten cot hoac nguoc lai) -> confidence 0.8
CANONICAL_ALIASES = {
    "customer_id": ["customer_id", "ma_khach_hang", "id_khach_hang", "ma_kh", "customer id", "id"],
    "age": ["age", "tuoi", "do_tuoi", "tuoi_khach_hang", "nam_sinh"],
    "gender": ["gender", "gioi_tinh", "sex"],
    "job": ["job", "nghe_nghiep", "profession", "cong_viec", "nghe", "chuc_vu", "chuc_danh"],
    "location": ["location", "dia_chi", "khu_vuc", "tinh_thanh", "address", "city", "region", "noi_o", "thanh_pho"],
    "total_spending": ["total_spending", "tong_chi_tieu", "doanh_thu", "chi_tieu", "spending", "revenue", "gia_tri_don_hang", "tong_tien"],
    "pain_point": ["pain_point", "noi_dau", "noi_dau_khach_hang", "van_de", "problem", "kho_khan", "ghi_chu_van_de"],
    "personality": ["personality", "tinh_cach", "character", "dac_diem", "tinh_cach_khach_hang"],
    "interest_keywords": ["interest", "so_thich", "tu_khoa_so_thich", "interests", "preferences", "mo_ta", "sthich", "hanh_vi"],
    "last_purchase_date": ["last_purchase_date", "ngay_mua_gan_nhat", "ngay_mua", "purchase_date", "ngay_dat_hang"],
    "order_count": ["order_count", "so_don_hang", "so_lan_mua", "so_don", "orders", "number_of_orders"],
    "average_order_value": ["average_order_value", "aov", "gia_tri_don_hang_tb", "chi_tieu_trung_binh_don", "avg_order_value"],
    "discount_usage": ["discount_usage", "discount_rate", "ty_le_giam_gia", "muc_do_su_dung_khuyen_mai", "coupon_usage", "voucher_usage"],
    "product_category": ["product_category", "category", "danh_muc_san_pham", "nhom_san_pham", "loai_san_pham"],
    "channel": ["channel", "kenh", "kenh_mua_hang", "sales_channel", "purchase_channel", "preferred_channel", "kenh_uu_tien"],
    "device": ["device", "thiet_bi", "device_type", "thiet_bi_su_dung"],
    "acquisition_source": ["acquisition_source", "nguon_khach_hang", "nguon_tiep_can", "traffic_source", "source_channel"],
    "review_text": ["review_text", "review", "danh_gia", "noi_dung_danh_gia", "feedback", "customer_feedback"],
    "monthly_income": ["monthly_income", "monthly_income_vnd", "thu_nhap", "thu_nhap_thang", "income", "salary", "luong_thang"],
    "signup_date": ["signup_date", "registration_date", "registered_at", "ngay_dang_ky", "ngay_tao_khach_hang", "customer_since"],
    "return_count": ["return_count", "returns", "refund_count", "so_lan_hoan", "so_don_hoan", "so_lan_tra_hang"],
    "website_visits_30d": ["website_visits_30d", "website_visits", "visits_30d", "luot_truy_cap_30d", "luot_truy_cap_web"],
    "email_open_rate": ["email_open_rate", "open_rate", "ty_le_mo_email", "email_open"],
    "cart_abandon_rate": ["cart_abandon_rate", "abandon_rate", "ty_le_bo_gio", "cart_abandon"],
    "satisfaction_score": ["satisfaction_score", "satisfaction", "csat", "diem_hai_long", "muc_do_hai_long"],
    "loyalty_tier": ["loyalty_tier", "member_tier", "vip_level", "hang_thanh_vien", "cap_do_thanh_vien"],
}

RULE_EXACT_CONFIDENCE = 0.97
RULE_PARTIAL_CONFIDENCE = 0.80
RULE_MATCH_THRESHOLD = 0.75  # >= nguong nay thi CHAP NHAN LUON, khong goi AI nua


def _normalize_column_name(name: str) -> str:
    """Bo dau tieng Viet, chu thuong, thay khoang trang/ky tu dac biet bang '_'."""
    text = str(name or "").strip().lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("đ", "d").replace("Đ", "d")
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text


def _rule_based_match(column_name: str):
    """Tra ve (canonical_field, confidence, reasoning) hoac (None, 0.0, '') neu khong khop."""
    norm_col = _normalize_column_name(column_name)
    if not norm_col:
        return None, 0.0, ""

    # Uu tien khop CHINH XAC truoc
    for field, aliases in CANONICAL_ALIASES.items():
        for alias in aliases:
            if _normalize_column_name(alias) == norm_col:
                return field, RULE_EXACT_CONFIDENCE, f"Tên cột khớp chính xác alias '{alias}'"

    # Roi moi den khop MOT PHAN (alias nam trong ten cot hoac nguoc lai)
    best_field, best_alias, best_len = None, None, 0
    for field, aliases in CANONICAL_ALIASES.items():
        for alias in aliases:
            norm_alias = _normalize_column_name(alias)
            if len(norm_alias) < 3:
                continue  # tranh khop nham voi alias qua ngan nhu "id", "job"
            # Partial matching must be directional. A short source column such as
            # "email" must NOT match the longer alias "email_open_rate" merely
            # because it is a substring. We accept alias->column freely for useful
            # suffixes (e.g. total_spending_vnd) and only accept column->alias when
            # the source name itself is long/specific enough.
            partial = norm_alias in norm_col
            reverse_partial = norm_col in norm_alias and len(norm_col) >= 8 and (len(norm_alias)-len(norm_col) <= 8)
            if partial or reverse_partial:
                if len(norm_alias) > best_len:
                    best_field, best_alias, best_len = field, alias, len(norm_alias)

    if best_field:
        return best_field, RULE_PARTIAL_CONFIDENCE, f"Tên cột chứa/gần giống alias '{best_alias}'"
    return None, 0.0, ""


class SchemaMappingError(Exception):
    """Dung noi bo trong module nay khi 1 loi goi Ollama xay ra cho 1 cot cu the.
    fatal=True nghia la loi ket noi/timeout (goi tiep cac cot khac cung se that bai
    ngay, nen dung lai som thay vi cho tung cot 1 mot cach vo ich)."""
    def __init__(self, message, fatal=False):
        super().__init__(message)
        self.fatal = fatal


def _sample_values(raw_fields_list: list, column: str, n: int = 5) -> list:
    values = []
    for raw in raw_fields_list:
        v = raw.get(column)
        if v is not None and str(v).strip() != "":
            values.append(str(v).strip())
        if len(values) >= n:
            break
    return values


def _clamp_confidence(value) -> float:
    try:
        return round(max(0.0, min(1.0, float(value))), 2)
    except (TypeError, ValueError):
        return 0.5


def _map_single_column_with_ai(column: str, samples: list) -> dict:
    """Goi Ollama cho DUY NHAT 1 cot -> JSON OBJECT don gian (khong phai mang),
    de model 7B cuc it co co hoi tra JSON hong so voi phai tra 1 mang nhieu object."""
    canonical_list = "\n".join(
        f'- {name} ({"BẮT BUỘC" if meta["required"] else "tùy chọn"}, kiểu {meta["type"]})'
        for name, meta in CANONICAL_SCHEMA.items()
    )
    prompt = f"""Bạn là chuyên gia chuẩn hóa dữ liệu khách hàng.
Tên cột: "{column}"
Giá trị mẫu thực tế trong cột này: {samples if samples else "(không có giá trị mẫu)"}

Danh sách trường CHUẨN có thể ánh xạ tới:
{canonical_list}

Nếu cột này không khớp trường chuẩn nào, trả canonical_field = "unmapped".
Chỉ trả về DUY NHẤT 1 JSON OBJECT (không phải mảng, không giải thích thêm), đúng định dạng:
{{"canonical_field": "<tên trường chuẩn hoặc unmapped>", "confidence": <0.0-1.0>, "reasoning": "<lý do ngắn gọn>"}}
"""
    try:
        resp = requests.post(
            f"{OLLAMA_HOST}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False, "format": "json"},
            timeout=REQUEST_TIMEOUT_SEC,
        )
        resp.raise_for_status()
        raw_text = resp.json().get("response", "")
    except requests.exceptions.ConnectionError:
        raise SchemaMappingError(
            f"Không kết nối được tới Ollama tại {OLLAMA_HOST}. Hãy chạy 'ollama serve' rồi thử lại.",
            fatal=True,
        )
    except requests.exceptions.Timeout:
        raise SchemaMappingError("Ollama phản hồi quá lâu.", fatal=True)
    except Exception as e:
        raise SchemaMappingError(f"Lỗi hệ thống khi gọi Ollama: {e}", fatal=True)

    try:
        clean = raw_text.strip()
        start, end = clean.find("{"), clean.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("Không tìm thấy JSON object trong phản hồi.")
        return json.loads(clean[start:end + 1])
    except Exception as e:
        raise SchemaMappingError(f"Ollama trả về JSON không hợp lệ cho cột '{column}': {e}", fatal=False)


def _unmapped_row(column: str, reasoning: str, source: str) -> dict:
    return {
        "source_column": column,
        "canonical_field": "unmapped",
        "confidence": 0.0,
        "confidence_display": "0%",
        "reasoning": reasoning,
        "source": source,
    }


def map_columns_with_ai(columns: list, raw_fields_list: list) -> list:
    """
    Lop 1: khop rule-based ngay cho cot ten ro rang (khong can Ollama).
    Lop 2: CHI goi Ollama cho cot con lai, TUNG COT MOT (khong phai ca mang
    cung luc) -- de giam toi da rui ro Ollama tra JSON hong. Loi o 1 cot
    khong lam hong ket qua cua cac cot khac; neu Ollama mat ket noi hoan
    toan, dung lai ngay (khong thu tung cot con lai mot cach vo ich) va bao
    ro cho nguoi dung.
    """
    if not columns:
        return []

    result_by_col = {}
    unresolved = []
    for col in columns:
        field, confidence, reasoning = _rule_based_match(col)
        if field and confidence >= RULE_MATCH_THRESHOLD:
            result_by_col[col] = {
                "source_column": col,
                "canonical_field": field,
                "confidence": confidence,
                "confidence_display": f"{int(confidence * 100)}%",
                "reasoning": reasoning,
                "source": "rule",
            }
        else:
            unresolved.append(col)

    ollama_down = False
    for col in unresolved:
        if ollama_down:
            result_by_col[col] = _unmapped_row(
                col, "Bỏ qua: Ollama đã mất kết nối ở cột trước đó.", "ai_skipped"
            )
            continue

        samples = _sample_values(raw_fields_list, col)
        mapped, last_error = None, None
        for _attempt in range(2):  # thử tối đa 2 lần cho lỗi JSON không hợp lệ (không phải lỗi kết nối)
            try:
                mapped = _map_single_column_with_ai(col, samples)
                break
            except SchemaMappingError as e:
                last_error = e
                if e.fatal:
                    break  # lỗi kết nối/timeout -- thử lại ngay cũng vô ích

        if mapped is None:
            result_by_col[col] = _unmapped_row(col, str(last_error) if last_error else "Lỗi không xác định", "ai_failed")
            if last_error is not None and getattr(last_error, "fatal", False):
                ollama_down = True
        else:
            canonical_field = mapped.get("canonical_field", "unmapped")
            if canonical_field not in CANONICAL_SCHEMA:
                canonical_field = "unmapped"
            confidence = _clamp_confidence(mapped.get("confidence", 0.5))
            result_by_col[col] = {
                "source_column": col,
                "canonical_field": canonical_field,
                "confidence": confidence,
                "confidence_display": f"{int(confidence * 100)}%",
                "reasoning": mapped.get("reasoning", ""),
                "source": "ai",
            }

    return [result_by_col[c] for c in columns]


def apply_mapping(raw_fields_list: list, mapping: list) -> list:
    """Ap dung mapping da xac nhan (co the da duoc nguoi dung sua tay tren UI)
    de doi ten cot goc -> ten truong canonical."""
    col_to_canonical = {
        m["source_column"]: m["canonical_field"]
        for m in mapping
        if m.get("canonical_field") not in (None, "unmapped")
    }
    canonical_records = []
    for raw in raw_fields_list:
        rec = {field: None for field in CANONICAL_SCHEMA}
        for source_col, value in raw.items():
            field = col_to_canonical.get(source_col)
            if field:
                rec[field] = value
        canonical_records.append(rec)
    return canonical_records


def missing_required_fields(mapping: list) -> list:
    """Tra ve danh sach truong BAT BUOC chua duoc map toi cot nao."""
    mapped_fields = {m["canonical_field"] for m in mapping}
    return [f for f in REQUIRED_FIELDS if f not in mapped_fields]


def failed_columns(mapping: list) -> list:
    """Danh sach cot ma Ollama KHONG map duoc (loi ket noi/JSON hong), de UI
    canh bao dung cho nguoi dung tu map tay dung nhung cot do -- khong che lap
    thanh cong cua cac cot khac."""
    return [m for m in mapping if m.get("source") in ("ai_failed", "ai_skipped")]
