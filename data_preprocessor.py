import pandas as pd
import numpy as np
import re
import asyncio
import json

# ĐÁNH DẤU PHIÊN BẢN: hiển thị ở sidebar "Trạng thái hệ thống" trên web_app.py.
# Nếu con số này KHÔNG khớp với bản mới nhất bạn được cung cấp, nghĩa là
# Streamlit đang chạy module data_preprocessor CŨ còn nằm trong bộ nhớ (do
# import cục bộ + chưa khởi động lại hẳn process) -- không phải lỗi code.
DATA_PREPROCESSOR_BUILD = "2026-08-02-fix3-dtype-duplicate-columns"

# Import hàm gọi AI nội bộ từ file của bạn để tái sử dụng kết nối Ollama
from backend.ai_bridge import call_text

# Schema chuẩn giờ có 1 nguồn DUY NHẤT: schema_mapper.py. Trước đây file này
# tự định nghĩa MASTER_SCHEMA riêng (thiếu interest_keywords/last_purchase_date
# so với bảng canonical_customers), gây lệch dữ liệu giữa các module.
from schema_mapper import CANONICAL_SCHEMA as MASTER_SCHEMA, REQUIRED_FIELDS

# Các trường AI có thể tự suy luận khi thiếu (đúng bằng REQUIRED_FIELDS hiện tại,
# nhưng khai báo riêng để rõ ràng nếu sau này 2 danh sách tách nhau).
TRACKED_FIELDS = REQUIRED_FIELDS


class AdvancedETLPipeline:
    """
    Ngoài việc chuẩn hóa dữ liệu, pipeline này còn TRACK nguồn gốc của từng
    giá trị (original / ai_inferred / default_fallback) cho từng dòng, từng
    trường bắt buộc -- để build "AI Learning Audit": doanh nghiệp/người vận
    hành biết chính xác AI đã "bịa" bao nhiêu % dữ liệu, ở trường nào, để
    quyết định có tin tưởng dùng để mô phỏng hay không.
    """

    def __init__(self, raw_records, mapping_config):
        flat_records = [r.get("raw_fields", r) for r in raw_records]
        self.raw_df = pd.DataFrame(flat_records)
        self.mapping_config = mapping_config
        self.source_flags = None  # DataFrame cùng index, cột = TRACKED_FIELDS, giá trị = "original"/"ai_inferred"/"default_fallback"

    def apply_semantic_mapping(self):
        """Map cột của doanh nghiệp về Master Schema"""
        rename_dict = {}
        used_canonical_fields = set()
        for item in self.mapping_config:
            source_col = item.get("Tên cột gốc", item.get("source_column"))
            ai_col = item.get("AI hiểu là", item.get("ai_column"))
            if not ai_col or ai_col in ("unknown_column", "unmapped") or source_col not in self.raw_df.columns:
                continue
            if ai_col in used_canonical_fields:
                # QUAN TRỌNG: nếu để 2 cột gốc khác nhau cùng map tới 1 trường chuẩn,
                # DataFrame sau rename() sẽ có 2 CỘT TRÙNG TÊN -- khi đó mọi thao tác
                # như .isna().any() không còn trả về 1 giá trị True/False đơn mà trả về
                # 1 Series (1 giá trị cho mỗi cột trùng), gây lỗi "truth value of a
                # Series is ambiguous". Chỉ giữ cột ĐẦU TIÊN map tới field này, các cột
                # trùng sau đó coi như chưa map (giữ nguyên tên gốc, bị bỏ qua bên dưới).
                continue
            rename_dict[source_col] = ai_col
            used_canonical_fields.add(ai_col)

        self.mapped_df = self.raw_df.rename(columns=rename_dict)
        # Lưới an toàn bổ sung: phòng trường hợp trùng tên đến từ nguồn khác (không
        # qua rename_dict ở trên), loại bỏ cột trùng tên, chỉ giữ cột xuất hiện đầu tiên.
        if self.mapped_df.columns.duplicated().any():
            self.mapped_df = self.mapped_df.loc[:, ~self.mapped_df.columns.duplicated()]

        available_cols = [col for col in MASTER_SCHEMA.keys() if col in self.mapped_df.columns]
        self.mapped_df = self.mapped_df[available_cols].copy()
        return self

    def _clean_text(self, text):
        if pd.isna(text): return np.nan
        text = re.sub(r'\s+', ' ', str(text).strip())
        return text if text else np.nan

    def clean_and_impute_pandas(self):
        """Dọn dẹp cơ bản và xử lý nhiễu bằng Pandas"""
        for col, schema in MASTER_SCHEMA.items():
            if col not in self.mapped_df.columns:
                self.mapped_df[col] = np.nan

            if schema["type"] == "numeric":
                self.mapped_df[col] = pd.to_numeric(self.mapped_df[col], errors='coerce')
                if col == "age":
                    self.mapped_df[col] = self.mapped_df[col].clip(12, 100)
                elif col == "total_spending":
                    self.mapped_df[col] = self.mapped_df[col].clip(lower=0.0)
            elif schema["type"] in ["string", "category", "date"]:
                # QUAN TRỌNG: 1 cột thiếu mapping được tạo bằng `= np.nan` ở trên sẽ bị
                # pandas suy ra dtype float64 (vì np.nan là số thực). Nếu không ép về
                # object NGAY tại đây, bước AI suy luận / điền giá trị mặc định phía sau
                # ghi chuỗi (vd "Sinh viên") vào cột đó sẽ bị pandas từ chối với lỗi
                # "Invalid value ... for dtype 'float64'".
                self.mapped_df[col] = self.mapped_df[col].astype("object")
                self.mapped_df[col] = self.mapped_df[col].apply(self._clean_text).astype("object")

        if self.mapped_df['total_spending'].isna().any():
            median_spending = self.mapped_df['total_spending'].median()
            # LƯU Ý: `NaN or 0.0` trả về NaN (NaN được Python coi là truthy), không phải
            # 0.0 -- nên khi TOÀN BỘ giá trị đều thiếu, phải kiểm tra pd.notna() tường minh.
            fallback_spending = median_spending if pd.notna(median_spending) else 0.0
            self.mapped_df.fillna({'total_spending': fallback_spending}, inplace=True)
        if self.mapped_df['gender'].isna().any():
            self.mapped_df.fillna({'gender': "Chưa rõ"}, inplace=True)

        # Chốt trạng thái "original" NGAY SAU khi map + dọn dẹp, TRƯỚC khi AI
        # hoặc default-fallback đụng vào -- đây là mốc để so sánh về sau.
        self.source_flags = pd.DataFrame(index=self.mapped_df.index)
        for field in TRACKED_FIELDS:
            self.source_flags[field] = np.where(self.mapped_df[field].isna(), "missing", "original")

        return self


    async def _ask_ollama_to_fill_missing(self, idx, row_data):
        prompt = f"""Phân tích hồ sơ khách hàng sau. Chỉ suy luận từ các tín hiệu được cung cấp, không bịa đặc điểm cá nhân nhạy cảm.
Giới tính: {row_data.get('gender','Không rõ')}
Nghề nghiệp: {row_data.get('job','Không rõ')}
Sở thích: {row_data.get('interest_keywords','Không rõ')}
Hãy trả JSON duy nhất gồm age, job, pain_point, personality, interest_keywords. Nếu không đủ bằng chứng, để null.
"""
        try:
            response = await call_text(prompt, temperature=0.2, json_mode=True)
            clean_json = response[response.find('{'): response.rfind('}') + 1]
            return idx, json.loads(clean_json)
        except Exception:
            return idx, None

    async def ai_enhanced_imputation(self, limit_ai_calls=50):
        """Gọi Ollama nội suy các dòng thiếu dữ liệu quan trọng. Mỗi ô được AI
        điền đều được đánh dấu 'ai_inferred' trong self.source_flags."""
        if 'interest_keywords' not in self.mapped_df.columns:
            self.mapped_df['interest_keywords'] = pd.Series([np.nan] * len(self.mapped_df), dtype="object")

        missing_mask = (
            self.mapped_df['age'].isna() | self.mapped_df['job'].isna() |
            self.mapped_df['pain_point'].isna() | self.mapped_df['interest_keywords'].isna()
        )
        missing_indices = self.mapped_df[missing_mask].index[:limit_ai_calls]

        if len(missing_indices) > 0:
            tasks = [self._ask_ollama_to_fill_missing(idx, self.mapped_df.loc[idx].to_dict()) for idx in missing_indices]
            results = await asyncio.gather(*tasks)

            for idx, ai_data in results:
                if ai_data:
                    for field in ["age", "job", "pain_point", "personality", "interest_keywords"]:
                        if pd.isna(self.mapped_df.loc[idx, field]) and field in ai_data:
                            self.mapped_df.loc[idx, field] = ai_data[field]
                            self.source_flags.loc[idx, field] = "ai_inferred"

        # Những ô còn rỗng (vượt limit_ai_calls, hoặc Ollama không trả field đó)
        # được điền bằng giá trị mặc định chung -- đánh dấu riêng 'default_fallback'
        # vì đây KHÔNG phải AI hiểu khách hàng, chỉ là placeholder an toàn.
        median_age = self.mapped_df['age'].median()
        defaults = {
            "age": median_age if pd.notna(median_age) else 25,
            "job": "Khách hàng tự do",
            "pain_point": "Quan tâm đến chất lượng và giá cả",
            "personality": "Thận trọng",
            "interest_keywords": "mua sắm, khuyến mãi",
        }
        for field, default_value in defaults.items():
            still_missing = self.mapped_df[field].isna()
            if still_missing.any():
                self.source_flags.loc[still_missing, field] = "default_fallback"
                self.mapped_df.loc[still_missing, field] = default_value

        return self

    def export(self):
        return self.mapped_df.to_dict("records")

    def export_with_audit(self, upload_name: str = "") -> tuple:
        """Trả về (records, audit_summary). audit_summary cho biết, với TỪNG
        trường bắt buộc, bao nhiêu % dữ liệu là THẬT (từ doanh nghiệp) so với
        AI tự suy luận / mặc định -- để người vận hành xác nhận trước khi tin
        dùng cho mô phỏng."""
        records = self.export()
        total = len(records)

        field_coverage = {}
        for field in TRACKED_FIELDS:
            counts = self.source_flags[field].value_counts().to_dict() if self.source_flags is not None else {}
            original = int(counts.get("original", 0))
            ai_inferred = int(counts.get("ai_inferred", 0))
            default_fallback = int(counts.get("default_fallback", 0))
            field_coverage[field] = {
                "original": original,
                "ai_inferred": ai_inferred,
                "default_fallback": default_fallback,
                "original_pct": round(100 * original / total, 1) if total else 0.0,
                "ai_inferred_pct": round(100 * ai_inferred / total, 1) if total else 0.0,
                "default_fallback_pct": round(100 * default_fallback / total, 1) if total else 0.0,
            }

        # Điểm "độ tin cậy học được" tổng quát: trung bình % dữ liệu thật trên
        # các trường bắt buộc. Thấp -> phần lớn là AI bịa ra, nên cảnh báo.
        if field_coverage:
            overall_real_pct = round(
                sum(v["original_pct"] for v in field_coverage.values()) / len(field_coverage), 1
            )
        else:
            overall_real_pct = 0.0

        # Đính kèm per-row: field nào của dòng đó là AI/default, để UI có thể
        # cho xem chi tiết từng khách hàng nếu người dùng muốn soi kỹ.
        if self.source_flags is not None:
            for i, rec in enumerate(records):
                idx = self.source_flags.index[i]
                rec["_field_sources"] = {
                    field: self.source_flags.loc[idx, field] for field in TRACKED_FIELDS
                }

        audit_summary = {
            "upload_name": upload_name,
            "total_records": total,
            "field_coverage": field_coverage,
            "overall_real_data_pct": overall_real_pct,
        }
        return records, audit_summary


async def run_advanced_etl(raw_records, mapping_config, upload_name: str = ""):
    """Trả về (records, audit_summary). Giữ tương thích ngược: nếu chỗ gọi cũ
    chỉ unpack 1 giá trị sẽ lỗi rõ ràng thay vì âm thầm sai -- xem web_app.py."""
    if not raw_records or not mapping_config:
        return [], {"upload_name": upload_name, "total_records": 0, "field_coverage": {}, "overall_real_data_pct": 0.0}
    pipeline = AdvancedETLPipeline(raw_records, mapping_config)
    pipeline.apply_semantic_mapping()
    pipeline.clean_and_impute_pandas()
    await pipeline.ai_enhanced_imputation(limit_ai_calls=50)
    return pipeline.export_with_audit(upload_name=upload_name)
