import pandas as pd
import numpy as np
import re
import asyncio
import json

# Import hàm gọi AI nội bộ từ file của bạn để tái sử dụng kết nối Ollama
from persona_simulator import _call_ollama

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
        for item in self.mapping_config:
            source_col = item.get("Tên cột gốc", item.get("source_column"))
            ai_col = item.get("AI hiểu là", item.get("ai_column"))
            if ai_col and ai_col not in ("unknown_column", "unmapped") and source_col in self.raw_df.columns:
                rename_dict[source_col] = ai_col

        self.mapped_df = self.raw_df.rename(columns=rename_dict)
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
            elif schema["type"] in ["string", "category"]:
                self.mapped_df[col] = self.mapped_df[col].apply(self._clean_text)

        if self.mapped_df['total_spending'].isna().any():
            self.mapped_df['total_spending'].fillna(self.mapped_df['total_spending'].median() or 0.0, inplace=True)
        if self.mapped_df['gender'].isna().any():
            self.mapped_df['gender'].fillna("Chưa rõ", inplace=True)

        # Chốt trạng thái "original" NGAY SAU khi map + dọn dẹp, TRƯỚC khi AI
        # hoặc default-fallback đụng vào -- đây là mốc để so sánh về sau.
        self.source_flags = pd.DataFrame(index=self.mapped_df.index)
        for field in TRACKED_FIELDS:
            self.source_flags[field] = np.where(self.mapped_df[field].isna(), "missing", "original")

        return self

    async def _ask_ollama_to_fill_missing(self, idx, row_data):
        """Gửi 1 hồ sơ thiếu dữ liệu cho AI để suy luận ngữ cảnh"""
        prompt = f"""
        Phân tích hồ sơ khách hàng sau:
        - Giới tính: {row_data.get('gender', 'Không rõ')}
        - Nghề nghiệp / Ghi chú: {row_data.get('job', 'Không rõ')}
        - Hành vi / Sở thích: {row_data.get('interest_keywords', 'Không rõ')}

        Nhiệm vụ: Hãy suy luận logic độ tuổi (age), nghề nghiệp chuẩn hóa (job), nỗi đau mua sắm (pain_point),
        tính cách (personality) và từ khóa sở thích (interest_keywords, 3-5 từ khóa cách nhau bởi dấu phẩy).
        Chỉ trả về JSON duy nhất (không giải thích):
        {{"age": 25, "job": "Sinh viên", "pain_point": "Sợ giá cao", "personality": "Thực tế, tiết kiệm", "interest_keywords": "công nghệ, tiết kiệm, khuyến mãi"}}
        """
        response = await _call_ollama(prompt)
        try:
            clean_json = response[response.find("{"): response.rfind("}") + 1]
            return idx, json.loads(clean_json)
        except Exception:
            return idx, None

    async def ai_enhanced_imputation(self, limit_ai_calls=50):
        """Gọi Ollama nội suy các dòng thiếu dữ liệu quan trọng. Mỗi ô được AI
        điền đều được đánh dấu 'ai_inferred' trong self.source_flags."""
        if 'interest_keywords' not in self.mapped_df.columns:
            self.mapped_df['interest_keywords'] = np.nan

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
        defaults = {
            "age": self.mapped_df['age'].median() or 25,
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
