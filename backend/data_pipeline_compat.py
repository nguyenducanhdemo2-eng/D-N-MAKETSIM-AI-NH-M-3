import io
import pandas as pd

def read_dataframe(raw, fn):
    """Đọc CSV/XLS/XLSX bền vững: tự thử BOM/UTF-8/CP1258/CP1252 và báo lỗi rõ ràng."""
    name=(fn or "").lower().strip()
    if name.endswith(".csv"):
        errors=[]
        for enc in ("utf-8-sig","utf-8","cp1258","cp1252","latin1"):
            try:
                df=pd.read_csv(io.BytesIO(raw), encoding=enc)
                if df.shape[1] == 1 and len(df.columns)==1:
                    # Một số CSV dùng ; hoặc tab. Thử lại nếu toàn bộ header bị dồn vào 1 cột.
                    first=str(df.columns[0])
                    for sep in (";", "\t", "|"):
                        if sep in first:
                            df=pd.read_csv(io.BytesIO(raw), encoding=enc, sep=sep)
                            break
                return df
            except Exception as e:
                errors.append(f"{enc}: {e}")
        raise ValueError("Không đọc được CSV. Hãy kiểm tra encoding/dấu phân cách. " + " | ".join(errors[-2:]))
    if name.endswith((".xlsx",".xls")):
        try:
            return pd.read_excel(io.BytesIO(raw))
        except ImportError as e:
            raise ValueError("Thiếu thư viện đọc Excel. Hãy chạy: pip install openpyxl xlrd") from e
        except Exception as e:
            raise ValueError(f"Không đọc được file Excel: {e}")
    raise ValueError("Chỉ hỗ trợ file CSV, XLSX hoặc XLS.")
