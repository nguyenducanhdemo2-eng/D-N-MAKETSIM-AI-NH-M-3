# ==============================================================================
# DATABASE.PY - Lưu trữ & truy vấn kết quả mô phỏng (SQLite)
# ĐÃ SỬA LỖI QUAN TRỌNG: bản gốc gọi os.remove(DB_PATH) mỗi lần lưu -> XOÁ SẠCH
# lịch sử các chiến dịch cũ mỗi khi chạy mô phỏng mới. Giờ dữ liệu được giữ lại,
# chỉ xoá khi người dùng CHỦ ĐỘNG bấm nút "Xoá lịch sử" (reset_db).
# ==============================================================================
import sqlite3
import os
import json
import re
import hashlib
import secrets
from collections import Counter
import pandas as pd
from config import DB_PATH


def init_db():
    """Tạo bảng nếu CHƯA tồn tại. Không đụng tới dữ liệu cũ (an toàn để gọi nhiều lần)."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scenarios (
            id INTEGER PRIMARY KEY,
            scenario_text TEXT,
            strengths TEXT,
            weaknesses TEXT,
            summary TEXT,
            star_rating INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS uploaded_datasets (
            id INTEGER PRIMARY KEY,
            upload_name TEXT,
            upload_source TEXT,
            uploaded_at TEXT,
            record_count INTEGER,
            columns TEXT,
            sample_text TEXT,
            raw_records_json TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ai_learning_memory (
            id INTEGER PRIMARY KEY,
            upload_name TEXT,
            upload_source TEXT,
            learned_at TEXT,
            record_count INTEGER,
            columns TEXT,
            top_keywords TEXT,
            top_traits TEXT,
            summary_text TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS simulation_results (
            scenario_id INTEGER,
            persona_name TEXT,
            score INTEGER,
            sentiment TEXT,
            reasoning TEXT
        )
    """)
    # ------------------------------------------------------------------------
    # BẢNG DỮ LIỆU CHUẨN HÓA (CANONICAL) — nguồn dữ liệu DUY NHẤT mà clustering,
    # persona, chat phải đọc từ đây, thay vì đọc thẳng file upload thô như
    # trước (khiến mapping đã xác nhận bị "mất tích", không được dùng thật).
    # ------------------------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS canonical_customers (
            id INTEGER PRIMARY KEY,
            upload_id INTEGER,
            customer_id TEXT,
            age INTEGER,
            gender TEXT,
            job TEXT,
            location TEXT,
            total_spending REAL,
            pain_point TEXT,
            personality TEXT,
            interest_keywords TEXT,
            last_purchase_date TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def save_canonical_customers(upload_id: int, records: list):
    """Lưu danh sách khách hàng ĐÃ CHUẨN HÓA (sau schema_mapper.apply_mapping()
    + data_preprocessor bù dữ liệu thiếu) vào bảng canonical_customers.
    Đây là bước bắt buộc: nếu bỏ qua bước này, dữ liệu chuẩn hóa sẽ không
    được clustering/persona đọc thấy (lặp lại đúng lỗi 'clean_customer_data'
    trước đây chỉ nằm trong session_state mà không ai đọc lại)."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    for r in records:
        cursor.execute(
            """INSERT INTO canonical_customers
               (upload_id, customer_id, age, gender, job, location, total_spending,
                pain_point, personality, interest_keywords, last_purchase_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                upload_id,
                r.get("customer_id"),
                r.get("age"),
                r.get("gender"),
                r.get("job"),
                r.get("location"),
                r.get("total_spending"),
                r.get("pain_point"),
                r.get("personality"),
                r.get("interest_keywords"),
                r.get("last_purchase_date"),
            ),
        )
    conn.commit()
    conn.close()


def load_canonical_customers(upload_id: int = None, limit: int = 5000) -> list:
    """Đọc dữ liệu khách hàng đã chuẩn hóa. upload_id=None -> lấy TẤT CẢ các lần
    upload đã chuẩn hóa (để AI học tích lũy qua nhiều lần), dùng cho
    tất cả module cần dữ liệu khách hàng (clustering, persona)."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    if upload_id is not None:
        cursor.execute(
            "SELECT customer_id, age, gender, job, location, total_spending, "
            "pain_point, personality, interest_keywords, last_purchase_date "
            "FROM canonical_customers WHERE upload_id=? ORDER BY id DESC LIMIT ?",
            (upload_id, limit),
        )
    else:
        cursor.execute(
            "SELECT customer_id, age, gender, job, location, total_spending, "
            "pain_point, personality, interest_keywords, last_purchase_date "
            "FROM canonical_customers ORDER BY id DESC LIMIT ?",
            (limit,),
        )
    cols = ["customer_id", "age", "gender", "job", "location", "total_spending",
            "pain_point", "personality", "interest_keywords", "last_purchase_date"]
    rows = [dict(zip(cols, row)) for row in cursor.fetchall()]
    conn.close()
    return rows


def reset_db():
    """Xoá TOÀN BỘ lịch sử. Chỉ nên gọi khi người dùng chủ động bấm nút xoá trên UI."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_db()


def _hash_password(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def create_user(email: str, password: str) -> int:
    """Tạo tài khoản mới bằng mật khẩu đã băm với salt ngẫu nhiên."""
    email = (email or "").strip().lower()
    password = password or ""
    if not email:
        raise ValueError("Vui lòng nhập email.")
    if len(password) < 6:
        raise ValueError("Mật khẩu phải có ít nhất 6 ký tự.")

    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE email=?", (email,))
    if cur.fetchone():
        conn.close()
        raise ValueError("Email này đã tồn tại.")

    salt = secrets.token_hex(8)
    password_hash = _hash_password(password, salt)
    cur.execute(
        "INSERT INTO users (email, password_hash, salt) VALUES (?, ?, ?)",
        (email, password_hash, salt),
    )
    conn.commit()
    user_id = cur.lastrowid
    conn.close()
    return user_id


def verify_user(email: str, password: str) -> bool:
    """Xác thực email và mật khẩu đã lưu trong SQLite."""
    email = (email or "").strip().lower()
    password = password or ""
    if not email or not password:
        return False

    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT password_hash, salt FROM users WHERE email=?", (email,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return False

    stored_hash, salt = row
    return _hash_password(password, salt) == stored_hash


def save_uploaded_dataset(upload_name: str, records: list, columns: list, upload_source: str = "web_upload"):
    """Lưu metadata và mẫu dữ liệu đã xử lý từ file upload để AI có thể nhớ lại ở lần chạy sau."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    sample_texts = [r.get("text", "") for r in (records[:20] if records else [])]
    sample_text = " | ".join([t for t in sample_texts if t])[:2000]
    raw_records_json = json.dumps(records[:200], ensure_ascii=False)
    cursor.execute(
        "INSERT INTO uploaded_datasets VALUES (NULL, ?, ?, datetime('now'), ?, ?, ?, ?)",
        (upload_name, upload_source, len(records), json.dumps(columns, ensure_ascii=False), sample_text, raw_records_json)
    )
    upload_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return upload_id


def load_persisted_uploaded_records(max_records: int = 300) -> list:
    """Tải lại dữ liệu đã xử lý từ lần upload trước, để AI có thể nhớ hành vi đã train trước đó."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT raw_records_json FROM uploaded_datasets ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()

    records = []
    for (raw_json,) in rows:
        if not raw_json:
            continue
        try:
            batch = json.loads(raw_json)
        except Exception:
            continue
        for item in batch:
            records.append(item)
            if len(records) >= max_records:
                return records
    return records


def get_uploaded_dataset_count():
    """Đếm số lần upload dữ liệu đã được ghi nhớ."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM uploaded_datasets")
    count = cursor.fetchone()[0]
    conn.close()
    return count


def _extract_learning_tokens(text_value: str) -> list:
    """Trích rút từ khóa học tập từ dữ liệu khách hàng bằng regex đơn giản, hỗ trợ tiếng Việt."""
    if not text_value:
        return []
    tokens = re.findall(r"[A-Za-zÀ-ỹ0-9]+", str(text_value).lower())
    cleaned = [token for token in tokens if len(token) >= 3]
    return cleaned


def summarize_ai_learning(records: list, columns: list = None) -> dict:
    """Tạo tóm tắt AI học được từ dữ liệu upload mới để hiển thị tiến độ và lưu bộ nhớ."""
    records = records or []
    columns = columns or []
    keyword_counter = Counter()
    trait_counter = Counter()

    for record in records:
        raw_fields = record.get("raw_fields", {}) if isinstance(record, dict) else {}
        merged_text = []
        for key in ["text", "tinh_cach", "personality", "character", "dac_diem", "nghe_nghiep", "job", "noi_dau_khach_hang", "interest_keywords"]:
            val = record.get(key)
            if val:
                merged_text.append(str(val))
        if isinstance(raw_fields, dict):
            for key, val in raw_fields.items():
                if isinstance(val, (str, int, float)):
                    merged_text.append(str(val))

        joined_text = " ".join(merged_text)
        for token in _extract_learning_tokens(joined_text):
            keyword_counter[token] += 1

        trait_values = []
        for trait_key in ["tinh_cach", "personality", "character", "dac_diem"]:
            val = record.get(trait_key)
            if val:
                trait_values.append(str(val))
        if isinstance(raw_fields, dict):
            for trait_key in ["tinh_cach", "personality", "character", "dac_diem"]:
                val = raw_fields.get(trait_key)
                if val:
                    trait_values.append(str(val))
        for val in trait_values:
            trait_counter[val.strip()] += 1

    top_keywords = ", ".join([f"{kw} ({count})" for kw, count in keyword_counter.most_common(5)])
    top_traits = ", ".join([f"{trait} ({count})" for trait, count in trait_counter.most_common(5)])
    summary_text = (
        f"AI đã học {len(records)} khách hàng mới. "
        f"Các chủ đề nổi bật: {top_keywords or 'chưa xác định'}. "
        f"Tính cách phổ biến: {top_traits or 'chưa xác định'}."
    )

    return {
        "record_count": len(records),
        "columns": columns,
        "top_keywords": top_keywords,
        "top_traits": top_traits,
        "summary_text": summary_text,
    }


def save_learning_memory(upload_name: str, records: list, columns: list, upload_source: str = "web_upload"):
    """Lưu bản tóm tắt bộ nhớ học dữ liệu của AI để UI hiển thị tiến độ học tập, không cần nén toàn bộ file."""
    init_db()
    summary = summarize_ai_learning(records, columns=columns)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO ai_learning_memory VALUES (NULL, ?, ?, datetime('now'), ?, ?, ?, ?, ?)",
        (
            upload_name,
            upload_source,
            summary["record_count"],
            json.dumps(summary["columns"], ensure_ascii=False),
            summary["top_keywords"],
            summary["top_traits"],
            summary["summary_text"],
        )
    )
    conn.commit()
    conn.close()
    return summary


def get_ai_learning_snapshot() -> dict:
    """Trả về snapshot bộ nhớ AI sau khi đã học đủ dữ liệu từ nhiều lần upload."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT record_count, top_keywords, top_traits, summary_text FROM ai_learning_memory ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()

    total_records = 0
    top_keywords_counter = Counter()
    top_traits_counter = Counter()
    summaries = []

    for record_count, top_keywords, top_traits, summary_text in rows:
        total_records += int(record_count or 0)
        summaries.append(summary_text)
        for token_text in (top_keywords or "").split(","):
            token = token_text.strip()
            if token:
                top_keywords_counter[token] += 1
        for trait_text in (top_traits or "").split(","):
            trait = trait_text.strip()
            if trait:
                top_traits_counter[trait] += 1

    return {
        "upload_count": len(rows),
        "total_records": total_records,
        "top_keywords": [f"{k} ({v})" for k, v in top_keywords_counter.most_common(5)],
        "top_traits": [f"{k} ({v})" for k, v in top_traits_counter.most_common(5)],
        "summary_text": " ".join(summaries[:3]),
    }


def save_simulation(scenario, results, analysis):
    """Lưu 1 chiến dịch mới + toàn bộ phản hồi khách hàng. Giữ nguyên lịch sử cũ.
    Trả về id (sid) của chiến dịch vừa lưu để UI có thể mở lại ngay báo cáo này."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    strengths = str(analysis.get('strengths', '[]'))
    weaknesses = str(analysis.get('weaknesses', '[]'))
    summary = str(analysis.get('summary', 'Không có tóm tắt.'))
    try:
        star_rating = int(analysis.get('star_rating', 3))
    except (ValueError, TypeError):
        star_rating = 3
    star_rating = max(1, min(5, star_rating))  # kẹp trong khoảng 1-5 sao cho an toàn

    cursor.execute("INSERT INTO scenarios VALUES (NULL, ?, ?, ?, ?, ?)",
                   (scenario, strengths, weaknesses, summary, star_rating))
    sid = cursor.lastrowid

    for r in results:
        fallback_name = f"User_{r.get('persona_id', 'AI')}"
        persona_name = str(r.get('persona_name', r.get('name', r.get('customer_name', fallback_name))))

        try:
            score = int(r.get('score', 5))
        except (ValueError, TypeError):
            score = 5
        score = max(1, min(10, score))

        sentiment = str(r.get('sentiment', 'neutral')).lower()
        if sentiment not in ("positive", "negative", "neutral"):
            sentiment = "neutral"

        reasoning = str(r.get('reasoning', 'Khách hàng không để lại bình luận chi tiết.'))

        cursor.execute("INSERT INTO simulation_results VALUES (?, ?, ?, ?, ?)",
                       (sid, persona_name, score, sentiment, reasoning))

    conn.commit()
    conn.close()
    return sid


def get_all_scenarios():
    """Trả về danh sách (id, scenario_text, star_rating) của tất cả chiến dịch, mới nhất trước."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, scenario_text, star_rating FROM scenarios ORDER BY id DESC")
    rows = cur.fetchall()
    conn.close()
    return rows


def get_scenario_by_id(sid):
    """Trả về 1 dòng đầy đủ của bảng scenarios theo id, hoặc None nếu không tồn tại."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT * FROM scenarios WHERE id=?", (sid,))
    row = cur.fetchone()
    conn.close()
    return row


def get_results_by_scenario(sid) -> pd.DataFrame:
    """Trả về DataFrame các phản hồi khách hàng của 1 chiến dịch."""
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "SELECT persona_name, score, sentiment, reasoning FROM simulation_results WHERE scenario_id=?",
        conn, params=(sid,)
    )
    conn.close()
    return df
