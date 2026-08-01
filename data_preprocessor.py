import pandas as pd
import numpy as np
import re
import asyncio
import json

# Import hàm gọi AI nội bộ từ file của bạn để tái sử dụng kết nối Ollama
from persona_simulator import _call_ollama

MASTER_SCHEMA = {
    "customer_id": {"type": "string"},
    "age": {"type": "numeric"},
    "gender": {"type": "category"},
    "location": {"type": "string"},
    "total_spending": {"type": "numeric"},
    "job": {"type": "string"},
    "pain_point": {"type": "string"},
    "personality": {"type": "string"}
}

class AdvancedETLPipeline:
    def __init__(self, raw_records, mapping_config):
        flat_records = [r.get("raw_fields", r) for r in raw_records]
        self.raw_df = pd.DataFrame(flat_records)
        self.mapping_config = mapping_config

    def apply_semantic_mapping(self):
        """Map cột của doanh nghiệp về Master Schema"""
        rename_dict = {}
        for item in self.mapping_config:
            source_col = item.get("Tên cột gốc", item.get("source_column"))
            ai_col = item.get("AI hiểu là", item.get("ai_column"))
            if ai_col and ai_col != "unknown_column" and source_col in self.raw_df.columns:
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
                # Giới hạn giá trị phi lý
                if col == "age":
                    self.mapped_df[col] = self.mapped_df[col].clip(12, 100)
                elif col == "total_spending":
                    self.mapped_df[col] = self.mapped_df[col].clip(lower=0.0)
            elif schema["type"] in ["string", "category"]:
                self.mapped_df[col] = self.mapped_df[col].apply(self._clean_text)

        # Trừ Tuổi, Nghề nghiệp và Nỗi đau (sẽ để AI đoán), các cột khác điền nội suy cơ bản
        if self.mapped_df['total_spending'].isna().any():
            self.mapped_df['total_spending'].fillna(self.mapped_df['total_spending'].median() or 0.0, inplace=True)
        if self.mapped_df['gender'].isna().any():
            self.mapped_df['gender'].fillna("Chưa rõ", inplace=True)
            
        return self

    async def _ask_ollama_to_fill_missing(self, idx, row_data):
        """Gửi 1 hồ sơ thiếu dữ liệu cho AI để suy luận ngữ cảnh"""
        prompt = f"""
        Phân tích hồ sơ khách hàng sau:
        - Giới tính: {row_data.get('gender', 'Không rõ')}
        - Nghề nghiệp / Ghi chú: {row_data.get('job', 'Không rõ')}
        - Hành vi / Sở thích: {row_data.get('interest_keywords', 'Không rõ')}
        
        Nhiệm vụ: Hãy suy luận logic độ tuổi (age), nghề nghiệp chuẩn hóa (job), nỗi đau mua sắm (pain_point) và tính cách (personality).
        Chỉ trả về JSON duy nhất (không giải thích):
        {{"age": 25, "job": "Sinh viên", "pain_point": "Sợ giá cao", "personality": "Thực tế, tiết kiệm"}}
        """
        response = await _call_ollama(prompt)
        try:
            clean_json = response[response.find("{"): response.rfind("}") + 1]
            return idx, json.loads(clean_json)
        except:
            return idx, None

    async def ai_enhanced_imputation(self, limit_ai_calls=50):
        """Gọi Ollama nội suy các dòng thiếu Tuổi, Nghề nghiệp hoặc Nỗi đau"""
        # Lọc các dòng thiếu dữ liệu quan trọng
        missing_mask = self.mapped_df['age'].isna() | self.mapped_df['job'].isna() | self.mapped_df['pain_point'].isna()
        missing_indices = self.mapped_df[missing_mask].index[:limit_ai_calls] # Giới hạn batch để tránh nghẽn GPU

        if len(missing_indices) > 0:
            tasks = [self._ask_ollama_to_fill_missing(idx, self.mapped_df.loc[idx].to_dict()) for idx in missing_indices]
            results = await asyncio.gather(*tasks)

            # Ghi đè kết quả thông minh từ AI vào DataFrame
            for idx, ai_data in results:
                if ai_data:
                    if pd.isna(self.mapped_df.loc[idx, 'age']) and 'age' in ai_data:
                        self.mapped_df.loc[idx, 'age'] = ai_data['age']
                    if pd.isna(self.mapped_df.loc[idx, 'job']) and 'job' in ai_data:
                        self.mapped_df.loc[idx, 'job'] = ai_data['job']
                    if pd.isna(self.mapped_df.loc[idx, 'pain_point']) and 'pain_point' in ai_data:
                        self.mapped_df.loc[idx, 'pain_point'] = ai_data['pain_point']
                    if pd.isna(self.mapped_df.loc[idx, 'personality']) and 'personality' in ai_data:
                        self.mapped_df.loc[idx, 'personality'] = ai_data['personality']

        # Xử lý nốt những dòng còn rỗng (vượt quá limit_ai_calls) bằng giá trị mặc định
        self.mapped_df['age'].fillna(self.mapped_df['age'].median() or 25, inplace=True)
        self.mapped_df['job'].fillna("Khách hàng tự do", inplace=True)
        self.mapped_df['pain_point'].fillna("Quan tâm đến chất lượng và giá cả", inplace=True)
        self.mapped_df['personality'].fillna("Thận trọng", inplace=True)
        
        return self

    def export(self):
        return self.mapped_df.to_dict("records")

async def run_advanced_etl(raw_records, mapping_config):
    if not raw_records or not mapping_config: return []
    pipeline = AdvancedETLPipeline(raw_records, mapping_config)
    pipeline.apply_semantic_mapping()
    pipeline.clean_and_impute_pandas()
    await pipeline.ai_enhanced_imputation(limit_ai_calls=50)
    return pipeline.export()