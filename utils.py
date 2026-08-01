# ==============================================================================
# UTILS.PY - Các hàm tiện ích dùng chung cho nhiều bước
# ==============================================================================

import pandas as pd


def downcast_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    """
    Nén kiểu dữ liệu để giảm dung lượng RAM:
      - int64  -> int32/int16 (tùy giá trị)
      - float64 -> float32
      - object có ít giá trị khác nhau -> category
    LƯU Ý: các cột đã ở dạng datetime64 sẽ được bỏ qua, không bị ép về category.
    """
    for col in df.select_dtypes(include=["int64"]).columns:
        df[col] = pd.to_numeric(df[col], downcast="integer")

    for col in df.select_dtypes(include=["float64"]).columns:
        df[col] = pd.to_numeric(df[col], downcast="float")

    for col in df.select_dtypes(include=["object"]).columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            continue  # không đụng vào cột ngày tháng
        num_unique = df[col].nunique()
        num_total = len(df[col])
        if num_total > 0 and num_unique / num_total < 0.5:
            df[col] = df[col].astype("category")

    return df


def print_memory_usage(df: pd.DataFrame, name: str) -> None:
    """In ra số dòng, số cột và dung lượng RAM của một DataFrame."""
    mem_mb = df.memory_usage(deep=True).sum() / 1024**2
    print(f"    - '{name}': {df.shape[0]:,} dòng, {df.shape[1]} cột ({mem_mb:.2f} MB)")
