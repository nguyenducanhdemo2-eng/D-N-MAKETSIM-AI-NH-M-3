# ==============================================================================
# SCHEMA_MAPPER.PY - NGUỒN CHUẨN DUY NHẤT (SINGLE SOURCE OF TRUTH) CHO SCHEMA
# ==============================================================================
# Trước đây dự án có 3 bộ "hiểu schema" độc lập và không liên thông:
#   1. data_collector._infer_canonical_column()  (rule-based, alias riêng)
#   2. data_collector.process_customer_rows()    (alias riêng khác, dùng thật
#      cho clustering/persona -> đây là chỗ dữ liệu THỰC SỰ chảy vào AI)
#   3. data_preprocessor.MASTER_SCHEMA           (dùng cho ETL, nhưng kết quả
#      "clean_customer_data" không được bất kỳ module nào đọc lại -> dead code)
#
# File này thay thế cả 3: MỘT schema, MỘT hàm mapping (AI/Ollama), và mapping
# này bắt buộc phải được lưu vào bảng canonical_customers (database.py) rồi
# mọi module khác (clustering, persona, chat) CHỈ đọc từ bảng đó.
# ==============================================================================

import json
import requests
from config import OLLAMA_HOST, OLLAMA_MODEL, REQUEST_TIMEOUT_SEC


# ------------------------------------------------------------------------------
# CANONICAL SCHEMA — nguồn chuẩn duy nhất, mọi nơi khác import từ đây
# ------------------------------------------------------------------------------
# required=True nghĩa là: nếu doanh nghiệp không có cột này, AI phải tự suy luận
# (Ollama contextual imputation ở data_preprocessor.py), vì persona_simulator.py
# bắt buộc cần giá trị này để xây prompt nhập vai.
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
}

REQUIRED_FIELDS = [k for k, v in CANONICAL_SCHEMA.items() if v["required"]]


class SchemaMappingError(Exception):
    """Ném ra khi Ollama không map được cột (mất kết nối, timeout, JSON hỏng).
    Theo yêu cầu: KHÔNG fallback ngầm về rule-based — phải báo lỗi rõ ràng để
    người dùng tự map tay qua UI (st.data_editor), tránh việc AI "đoán bừa"
    một mapping sai mà người dùng không biết để sửa."""
    pass


def _sample_values(raw_fields_list: list, column: str, n: int = 5) -> list:
    values = []
    for raw in raw_fields_list:
        v = raw.get(column)
        if v is not None and str(v).strip() != "":
            values.append(str(v).strip())
        if len(values) >= n:
            break
    return values


def map_columns_with_ai(columns: list, raw_fields_list: list) -> list:
    """
    Gửi tên cột + vài giá trị mẫu thực tế cho Ollama, để nó tự suy luận cột
    nào tương ứng với trường nào trong CANONICAL_SCHEMA. Dùng giá trị mẫu là
    bắt buộc vì tên cột doanh nghiệp đặt tùy tiện (vd "col_5", "field_a")
    nhưng giá trị mẫu luôn có ý nghĩa để suy luận.

    Trả về list[dict]: [{source_column, canonical_field, confidence, reasoning}]
    Ném SchemaMappingError nếu Ollama lỗi/timeout/JSON không hợp lệ -- KHÔNG
    tự ý fallback sang rule-based.
    """
    if not columns:
        return []

    sample_block = "\n".join(
        f'- "{col}": ví dụ giá trị = {_sample_values(raw_fields_list, col)}'
        for col in columns
    )
    canonical_list = "\n".join(
        f'- {name} ({"BẮT BUỘC" if meta["required"] else "tùy chọn"}, kiểu {meta["type"]})'
        for name, meta in CANONICAL_SCHEMA.items()
    )

    prompt = f"""Bạn là chuyên gia chuẩn hóa dữ liệu khách hàng (data engineer).
Dưới đây là các cột trong 1 file dữ liệu khách hàng do doanh nghiệp tải lên, kèm vài giá trị mẫu thực tế:

{sample_block}

Danh sách trường CHUẨN (canonical) cần ánh xạ tới:
{canonical_list}

Nếu 1 cột không khớp với trường chuẩn nào, gán canonical_field = "unmapped".
Chỉ trả về JSON duy nhất, không kèm giải thích, đúng định dạng mảng:
[{{"source_column": "<tên cột gốc>", "canonical_field": "<tên trường chuẩn hoặc unmapped>", "confidence": <0.0-1.0>, "reasoning": "<lý do ngắn gọn>"}}]
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
            f"Không kết nối được tới Ollama tại {OLLAMA_HOST}. Hãy chạy 'ollama serve' rồi thử lại, "
            f"hoặc bấm 'Tự map tay' để chỉnh sửa mapping thủ công."
        )
    except requests.exceptions.Timeout:
        raise SchemaMappingError(
            "Ollama phản hồi quá lâu khi phân tích schema. Hãy thử lại, hoặc map tay."
        )
    except Exception as e:
        raise SchemaMappingError(f"Lỗi hệ thống khi gọi Ollama để map schema: {e}")

    try:
        clean = raw_text.strip()
        start, end = clean.find("["), clean.rfind("]")
        if start == -1 or end == -1:
            raise ValueError("Không tìm thấy mảng JSON trong phản hồi.")
        mapping = json.loads(clean[start:end + 1])
    except Exception as e:
        raise SchemaMappingError(
            f"Ollama trả về JSON không hợp lệ khi map schema ({e}). Hãy thử lại, hoặc map tay."
        )

    # Chuẩn hoá + validate kết quả, đảm bảo mọi cột gốc đều có mặt
    mapped_by_source = {item.get("source_column"): item for item in mapping if isinstance(item, dict)}
    result = []
    for col in columns:
        item = mapped_by_source.get(col, {})
        canonical_field = item.get("canonical_field", "unmapped")
        if canonical_field not in CANONICAL_SCHEMA:
            canonical_field = "unmapped"
        confidence = item.get("confidence", 0.5)
        try:
            confidence = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            confidence = 0.5
        result.append({
            "source_column": col,
            "canonical_field": canonical_field,
            "confidence": round(confidence, 2),
            "confidence_display": f"{int(confidence * 100)}%",
            "reasoning": item.get("reasoning", ""),
            "editable": True,
        })
    return result


def apply_mapping(raw_fields_list: list, mapping: list) -> list:
    """Áp dụng mapping đã xác nhận (có thể đã được người dùng sửa tay trên UI)
    để đổi tên cột gốc -> tên trường canonical. Không suy luận gì thêm ở đây;
    việc bù dữ liệu thiếu cho REQUIRED_FIELDS do data_preprocessor.py đảm nhiệm."""
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
    """Trả về danh sách trường BẮT BUỘC chưa được map tới cột nào -> UI cảnh báo
    trước khi cho xác nhận, để không lặp lại lỗi 'im lặng thiếu dữ liệu'."""
    mapped_fields = {m["canonical_field"] for m in mapping}
    return [f for f in REQUIRED_FIELDS if f not in mapped_fields]
