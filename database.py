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
            star_rating INTEGER,
            user_id INTEGER
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
            reasoning TEXT,
            purchase_intent TEXT
        )
    """)
    # Migrations bổ sung, giữ nguyên dữ liệu cũ.
    for table, column, definition in [
        ("scenarios", "user_id", "INTEGER"),
        ("simulation_results", "purchase_intent", "TEXT"),
    ]:
        cols = [r[1] for r in cursor.execute(f"PRAGMA table_info({table})").fetchall()]
        if column not in cols:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    # Bản database hiện tại chỉ có một tài khoản cũ: gán các chiến dịch lịch sử
    # chưa có user_id cho tài khoản duy nhất để không làm mất lịch sử.
    user_rows = cursor.execute("SELECT id FROM users ORDER BY id").fetchall()
    if len(user_rows) == 1:
        cursor.execute("UPDATE scenarios SET user_id=? WHERE user_id IS NULL", (user_rows[0][0],))

    # Các kết quả cũ chưa có ý định mua: suy ra theo đúng quy tắc hiển thị hiện tại.
    cursor.execute("""
        UPDATE simulation_results
        SET purchase_intent = CASE
            WHEN LOWER(COALESCE(sentiment,''))='negative' OR COALESCE(score,5)<=3 THEN 'not_buy'
            WHEN LOWER(COALESCE(sentiment,''))='positive' AND COALESCE(score,5)>=7 THEN 'buy'
            ELSE 'hesitate'
        END
        WHERE purchase_intent IS NULL OR purchase_intent=''
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
    # ------------------------------------------------------------------------
    # NHẬT KÝ HỌC AI (AI LEARNING AUDIT) — mỗi lần chuẩn hóa 1 file, lưu lại
    # % dữ liệu THẬT so với AI tự suy luận cho từng trường bắt buộc, để người
    # vận hành theo dõi & xác nhận chất lượng trước khi tin dùng cho mô phỏng.
    # ------------------------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS learning_audit (
            id INTEGER PRIMARY KEY,
            upload_id INTEGER,
            upload_name TEXT,
            total_records INTEGER,
            overall_real_data_pct REAL,
            field_coverage_json TEXT,
            mapping_json TEXT,
            missing_required_json TEXT,
            confirmed INTEGER DEFAULT 0,
            confirmed_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # ------------------------------------------------------------------------
    # ACCOUNT OWNERSHIP - dữ liệu khách hàng phải thuộc đúng tài khoản đã tải lên.
    # Migration chỉ thêm cột, không xóa hoặc thay đổi dữ liệu cũ.
    # ------------------------------------------------------------------------
    for table, col, sql_type in [
        ("uploaded_datasets", "user_id", "INTEGER"),
        ("learning_audit", "user_id", "INTEGER"),
    ]:
        cols = {row[1] for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()}
        if col not in cols:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {sql_type}")

    # Full per-session learning details for the new AI Learning History UI.
    # Additive migration only; old audit rows remain valid and readable.
    audit_cols = {row[1] for row in cursor.execute("PRAGMA table_info(learning_audit)").fetchall()}
    if "learning_details_json" not in audit_cols:
        cursor.execute("ALTER TABLE learning_audit ADD COLUMN learning_details_json TEXT")

    # ------------------------------------------------------------------------
    # CUSTOMER INTELLIGENCE - các cột mở rộng đều OPTIONAL để tương thích dữ liệu cũ.
    # SQLite không cho CREATE TABLE IF NOT EXISTS bổ sung cột vào bảng đã tồn tại,
    # nên migration này chỉ thêm cột nếu chưa có. Không xóa/sửa dữ liệu cũ.
    # ------------------------------------------------------------------------
    existing_cols = {row[1] for row in cursor.execute("PRAGMA table_info(canonical_customers)").fetchall()}
    intelligence_columns = {
        "order_count": "REAL",
        "average_order_value": "REAL",
        "discount_usage": "REAL",
        "product_category": "TEXT",
        "channel": "TEXT",
        "device": "TEXT",
        "acquisition_source": "TEXT",
        "review_text": "TEXT",
        "monthly_income": "REAL",
        "signup_date": "TEXT",
        "return_count": "REAL",
        "website_visits_30d": "REAL",
        "email_open_rate": "REAL",
        "cart_abandon_rate": "REAL",
        "satisfaction_score": "REAL",
        "loyalty_tier": "TEXT",
    }
    for col, sql_type in intelligence_columns.items():
        if col not in existing_cols:
            cursor.execute(f"ALTER TABLE canonical_customers ADD COLUMN {col} {sql_type}")
    existing_cols = {row[1] for row in cursor.execute("PRAGMA table_info(canonical_customers)").fetchall()}
    if "provenance_json" not in existing_cols:
        cursor.execute("ALTER TABLE canonical_customers ADD COLUMN provenance_json TEXT")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customer_segments (
            id INTEGER PRIMARY KEY,
            upload_id INTEGER,
            customer_id TEXT,
            segment_id INTEGER,
            segment_name TEXT,
            clustering_method TEXT,
            silhouette_score REAL,
            profile_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Segmentation quality migrations are additive. Existing customer_segments
    # rows remain readable; new rows can store customer-level confidence/reason.
    segment_cols = {row[1] for row in cursor.execute("PRAGMA table_info(customer_segments)").fetchall()}
    if "segment_confidence" not in segment_cols:
        cursor.execute("ALTER TABLE customer_segments ADD COLUMN segment_confidence REAL")
    if "segment_reason" not in segment_cols:
        cursor.execute("ALTER TABLE customer_segments ADD COLUMN segment_reason TEXT")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS segmentation_runs (
            id INTEGER PRIMARY KEY,
            upload_id INTEGER,
            n_clusters INTEGER,
            silhouette REAL,
            stability REAL,
            quality_score REAL,
            quality_status TEXT,
            metrics_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customer_intelligence_features (
            id INTEGER PRIMARY KEY,
            canonical_customer_id INTEGER,
            upload_id INTEGER,
            customer_id TEXT,
            recency_days REAL,
            frequency REAL,
            monetary REAL,
            r_score INTEGER,
            f_score INTEGER,
            m_score INTEGER,
            rfm_score INTEGER,
            price_sensitivity REAL,
            data_reliability REAL,
            feature_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customer_personas (
            id INTEGER PRIMARY KEY,
            upload_id INTEGER,
            segment_id INTEGER,
            persona_name TEXT,
            segment_size INTEGER,
            confidence REAL,
            generation_source TEXT,
            persona_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS synthetic_customer_twins (
            id INTEGER PRIMARY KEY,
            upload_id INTEGER,
            twin_id TEXT UNIQUE,
            segment_id INTEGER,
            confidence REAL,
            generation_method TEXT,
            proxy_scores_json TEXT,
            twin_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS advanced_experiments (
            id INTEGER PRIMARY KEY,
            experiment_type TEXT,
            campaign_text TEXT,
            population_size INTEGER,
            conversion_rate REAL,
            click_rate REAL,
            purchase_intent REAL,
            expected_revenue REAL,
            budget REAL,
            roi_index REAL,
            model_version TEXT,
            result_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS advanced_experiment_results (
            id INTEGER PRIMARY KEY,
            experiment_id INTEGER,
            twin_id TEXT,
            segment_id INTEGER,
            conversion_probability REAL,
            click_probability REAL,
            purchase_intent REAL,
            expected_revenue REAL,
            sentiment TEXT,
            score INTEGER,
            result_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ------------------------------------------------------------------------
    # CHAT MEMORY - lịch sử hội thoại bền vững theo từng tài khoản/doanh nghiệp.
    # Chỉ bổ sung bảng mới, không thay đổi hay reset các bảng nghiệp vụ hiện có.
    # ------------------------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            company_id INTEGER,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            provider TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_user_id ON chat_messages(user_id, id DESC)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS campaign_feedback (
            id INTEGER PRIMARY KEY,
            experiment_id INTEGER,
            predicted_conversion REAL,
            actual_conversion REAL,
            predicted_revenue REAL,
            actual_revenue REAL,
            mae REAL,
            bias REAL,
            calibration_factor REAL,
            calibration_offset REAL,
            notes TEXT,
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
                pain_point, personality, interest_keywords, last_purchase_date,
                order_count, average_order_value, discount_usage, product_category,
                channel, device, acquisition_source, review_text, monthly_income,
                signup_date, return_count, website_visits_30d, email_open_rate,
                cart_abandon_rate, satisfaction_score, loyalty_tier, provenance_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                upload_id, r.get("customer_id"), r.get("age"), r.get("gender"),
                r.get("job"), r.get("location"), r.get("total_spending"),
                r.get("pain_point"), r.get("personality"), r.get("interest_keywords"),
                r.get("last_purchase_date"), r.get("order_count"), r.get("average_order_value"),
                r.get("discount_usage"), r.get("product_category"), r.get("channel"),
                r.get("device"), r.get("acquisition_source"), r.get("review_text"),
                r.get("monthly_income"), r.get("signup_date"), r.get("return_count"),
                r.get("website_visits_30d"), r.get("email_open_rate"), r.get("cart_abandon_rate"),
                r.get("satisfaction_score"), r.get("loyalty_tier"),
                json.dumps(r.get("_field_sources", {}), ensure_ascii=False),
            ),
        )
    conn.commit()
    conn.close()


def load_canonical_customers(upload_id: int = None, limit: int = 5000, user_id: int | None = None, confirmed_only: bool = True) -> list:
    """Đọc canonical customers. Khi có user_id chỉ đọc dữ liệu thuộc tài khoản đó.
    Mặc định chỉ dùng dataset đã xác nhận AI Learning để làm knowledge base tích lũy."""
    init_db(); conn=sqlite3.connect(DB_PATH); cursor=conn.cursor()
    cols=["customer_id","age","gender","job","location","total_spending","pain_point","personality","interest_keywords","last_purchase_date","order_count","average_order_value","discount_usage","product_category","channel","device","acquisition_source","review_text","monthly_income","signup_date","return_count","website_visits_30d","email_open_rate","cart_abandon_rate","satisfaction_score","loyalty_tier","provenance_json"]
    select=", ".join("cc."+c for c in cols)
    sql=f"SELECT {select} FROM canonical_customers cc JOIN uploaded_datasets u ON u.id=cc.upload_id"
    where=[]; params=[]
    if upload_id is not None: where.append("cc.upload_id=?"); params.append(upload_id)
    if user_id is not None: where.append("u.user_id=?"); params.append(user_id)
    if confirmed_only: where.append("EXISTS (SELECT 1 FROM learning_audit a WHERE a.upload_id=cc.upload_id AND a.confirmed=1)")
    if where: sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY cc.id DESC LIMIT ?"; params.append(limit)
    cursor.execute(sql,tuple(params)); rows=cursor.fetchall(); conn.close()
    result=[]
    for row in rows:
        item=dict(zip(cols,row))
        raw=item.pop("provenance_json",None)
        try: item["_field_sources"]=json.loads(raw) if raw else {}
        except Exception: item["_field_sources"]={}
        result.append(item)
    return result


def save_learning_audit(upload_id: int, upload_name: str, audit_summary: dict, mapping: list, missing_required: list, user_id: int | None = None) -> int:
    """Lưu 1 bản ghi 'AI đã học được gì' cho 1 lần upload -- để người vận hành
    xem lại và xác nhận. Trả về id của bản ghi audit vừa lưu."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO learning_audit
           (upload_id, upload_name, total_records, overall_real_data_pct,
            field_coverage_json, mapping_json, missing_required_json, user_id, learning_details_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            upload_id,
            upload_name,
            audit_summary.get("total_records", 0),
            audit_summary.get("overall_real_data_pct", 0.0),
            json.dumps(audit_summary.get("field_coverage", {}), ensure_ascii=False),
            json.dumps(mapping or [], ensure_ascii=False),
            json.dumps(missing_required or [], ensure_ascii=False),
            user_id,
            json.dumps(audit_summary or {}, ensure_ascii=False, default=str),
        ),
    )
    audit_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return audit_id


def _row_to_audit_dict(row) -> dict:
    (audit_id, upload_id, upload_name, total_records, overall_real_data_pct,
     field_coverage_json, mapping_json, missing_required_json, confirmed, confirmed_at, created_at, user_id, learning_details_json) = row
    return {
        "id": audit_id, "upload_id": upload_id, "upload_name": upload_name,
        "total_records": total_records, "overall_real_data_pct": overall_real_data_pct,
        "field_coverage": json.loads(field_coverage_json) if field_coverage_json else {},
        "mapping": json.loads(mapping_json) if mapping_json else [],
        "missing_required_fields": json.loads(missing_required_json) if missing_required_json else [],
        "confirmed": bool(confirmed), "confirmed_at": confirmed_at, "created_at": created_at,
        "user_id": user_id,
        "learning_details": json.loads(learning_details_json) if learning_details_json else {},
    }

def get_learning_audit_by_upload(upload_id: int, user_id: int | None = None) -> dict:
    init_db(); conn=sqlite3.connect(DB_PATH); cursor=conn.cursor()
    sql=("SELECT id, upload_id, upload_name, total_records, overall_real_data_pct, "
         "field_coverage_json, mapping_json, missing_required_json, confirmed, confirmed_at, created_at, user_id, learning_details_json "
         "FROM learning_audit WHERE upload_id=?")
    params=[upload_id]
    if user_id is not None: sql += " AND user_id=?"; params.append(user_id)
    sql += " ORDER BY id DESC LIMIT 1"
    cursor.execute(sql, tuple(params)); row=cursor.fetchone(); conn.close()
    return _row_to_audit_dict(row) if row else None

def get_all_learning_audits(limit: int = 50, user_id: int | None = None) -> list:
    init_db(); conn=sqlite3.connect(DB_PATH); cursor=conn.cursor()
    sql=("SELECT id, upload_id, upload_name, total_records, overall_real_data_pct, "
         "field_coverage_json, mapping_json, missing_required_json, confirmed, confirmed_at, created_at, user_id, learning_details_json "
         "FROM learning_audit")
    params=[]
    if user_id is not None: sql += " WHERE user_id=?"; params.append(user_id)
    sql += " ORDER BY id DESC LIMIT ?"; params.append(limit)
    cursor.execute(sql, tuple(params)); rows=cursor.fetchall(); conn.close()
    return [_row_to_audit_dict(row) for row in rows]


def confirm_learning_audit(audit_id: int, user_id: int | None = None):
    """Người vận hành xác nhận đã xem & chấp nhận chất lượng dữ liệu AI học được
    cho 1 lần upload cụ thể."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    if user_id is None:
        cursor.execute("UPDATE learning_audit SET confirmed=1, confirmed_at=datetime('now') WHERE id=?", (audit_id,))
    else:
        cursor.execute("UPDATE learning_audit SET confirmed=1, confirmed_at=datetime('now') WHERE id=? AND user_id=?", (audit_id, user_id))
    conn.commit()
    conn.close()



def get_ai_learning_history(user_id: int, limit: int = 200) -> list:
    """Return complete learning sessions owned by one account."""
    init_db(); conn=sqlite3.connect(DB_PATH); conn.row_factory=sqlite3.Row
    rows=conn.execute("""
        SELECT a.id AS audit_id,a.upload_id,a.upload_name,a.total_records,a.overall_real_data_pct,
               a.confirmed,a.confirmed_at,a.created_at,a.learning_details_json,
               u.uploaded_at,u.record_count,u.columns,u.upload_source
        FROM learning_audit a
        JOIN uploaded_datasets u ON u.id=a.upload_id
        WHERE a.user_id=? AND u.user_id=?
        ORDER BY a.id DESC LIMIT ?
    """,(user_id,user_id,limit)).fetchall(); conn.close()
    items=[]
    for r in rows:
        details={}
        try: details=json.loads(r['learning_details_json']) if r['learning_details_json'] else {}
        except Exception: details={}
        columns=[]
        try: columns=json.loads(r['columns']) if r['columns'] else []
        except Exception: columns=[]
        items.append({
            'audit_id':r['audit_id'],'upload_id':r['upload_id'],'upload_name':r['upload_name'],
            'total_records':r['total_records'] or r['record_count'] or 0,'real_data_pct':r['overall_real_data_pct'] or 0,
            'confirmed':bool(r['confirmed']),'confirmed_at':r['confirmed_at'],'learned_at':r['created_at'],
            'uploaded_at':r['uploaded_at'],'source':r['upload_source'],'columns':columns,
            'learning_details':details,
        })
    return items

def delete_ai_learning_dataset(user_id: int, upload_id: int) -> dict:
    """Delete one owned learning source and its derived customer artifacts.

    Campaign/scenario/simulation history is deliberately preserved because it is a
    historical output, not a learning source. No other account can be affected.
    """
    init_db(); conn=sqlite3.connect(DB_PATH); cur=conn.cursor()
    row=cur.execute("SELECT id,upload_name FROM uploaded_datasets WHERE id=? AND user_id=?",(upload_id,user_id)).fetchone()
    if not row:
        conn.close(); return {'deleted':False,'reason':'not_found'}
    counts={}
    for table in ['synthetic_customer_twins','customer_personas','customer_segments','customer_intelligence_features','canonical_customers','learning_audit']:
        try:
            counts[table]=cur.execute(f"SELECT COUNT(*) FROM {table} WHERE upload_id=?",(upload_id,)).fetchone()[0]
            cur.execute(f"DELETE FROM {table} WHERE upload_id=?",(upload_id,))
        except sqlite3.OperationalError:
            counts[table]=0
    cur.execute("DELETE FROM uploaded_datasets WHERE id=? AND user_id=?",(upload_id,user_id))
    conn.commit(); conn.close()
    return {'deleted':True,'upload_id':upload_id,'upload_name':row[1],'deleted_rows':counts}


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


def save_uploaded_dataset(upload_name: str, records: list, columns: list, upload_source: str = "web_upload", user_id: int | None = None):
    """Lưu toàn bộ dữ liệu chuẩn hóa của dataset và gắn với tài khoản sở hữu."""
    init_db(); conn=sqlite3.connect(DB_PATH); cursor=conn.cursor()
    sample_texts=[r.get("text","") for r in (records[:20] if records else [])]
    sample_text=" | ".join([t for t in sample_texts if t])[:2000]
    # Giữ toàn bộ records trong bản ghi upload để phục vụ lịch sử/khôi phục;
    # canonical_customers đồng thời lưu từng khách hàng để truy vấn hiệu quả.
    raw_records_json=json.dumps(records, ensure_ascii=False, default=str)
    cursor.execute(
        "INSERT INTO uploaded_datasets (upload_name, upload_source, uploaded_at, record_count, columns, sample_text, raw_records_json, user_id) VALUES (?, ?, datetime('now'), ?, ?, ?, ?, ?)",
        (upload_name, upload_source, len(records), json.dumps(columns, ensure_ascii=False), sample_text, raw_records_json, user_id)
    )
    upload_id=cursor.lastrowid; conn.commit(); conn.close(); return upload_id

def load_persisted_uploaded_records(max_records: int = 300, user_id: int | None = None) -> list:
    """Tải dữ liệu đã lưu của đúng tài khoản; chỉ lấy dataset đã được xác nhận AI Learning."""
    init_db(); conn=sqlite3.connect(DB_PATH); cursor=conn.cursor()
    sql=("SELECT u.raw_records_json FROM uploaded_datasets u "
         "JOIN learning_audit a ON a.upload_id=u.id AND a.confirmed=1 "
         "WHERE u.raw_records_json IS NOT NULL")
    params=[]
    if user_id is not None: sql += " AND u.user_id=?"; params.append(user_id)
    sql += " ORDER BY u.id DESC"
    cursor.execute(sql, tuple(params)); rows=cursor.fetchall(); conn.close()
    records=[]
    for (raw_json,) in rows:
        try: batch=json.loads(raw_json) if raw_json else []
        except Exception: continue
        for item in batch:
            records.append(item)
            if len(records)>=max_records: return records
    return records

def get_uploaded_dataset_count(user_id: int | None = None) -> int:
    init_db(); conn=sqlite3.connect(DB_PATH); cursor=conn.cursor()
    sql="SELECT COUNT(*) FROM uploaded_datasets"; params=[]
    if user_id is not None: sql += " WHERE user_id=?"; params.append(user_id)
    cursor.execute(sql, tuple(params)); count=cursor.fetchone()[0]; conn.close(); return count

def get_user_dataset_history(user_id: int, limit: int = 50) -> list:
    init_db(); conn=sqlite3.connect(DB_PATH); cursor=conn.cursor()
    cursor.execute("""SELECT u.id,u.upload_name,u.uploaded_at,u.record_count,u.columns,
                           COALESCE(a.confirmed,0),COALESCE(a.overall_real_data_pct,0),
                           COALESCE(a.created_at,u.uploaded_at)
                    FROM uploaded_datasets u
                    LEFT JOIN learning_audit a ON a.id=(SELECT aa.id FROM learning_audit aa WHERE aa.upload_id=u.id ORDER BY aa.id DESC LIMIT 1)
                    WHERE u.user_id=? ORDER BY u.id DESC LIMIT ?""",(user_id,limit))
    rows=cursor.fetchall(); conn.close()
    return [{"id":r[0],"name":r[1],"uploaded_at":r[2],"records":r[3],"columns":json.loads(r[4]) if r[4] else [],"learning_confirmed":bool(r[5]),"real_data_pct":r[6],"learning_at":r[7]} for r in rows]

def get_user_dataset_stats(user_id: int) -> dict:
    init_db(); conn=sqlite3.connect(DB_PATH); c=conn.cursor()
    c.execute("SELECT COUNT(*), COALESCE(SUM(record_count),0) FROM uploaded_datasets WHERE user_id=?",(user_id,)); datasets,total_rows=c.fetchone()
    c.execute("SELECT COUNT(*) FROM canonical_customers cc JOIN uploaded_datasets u ON u.id=cc.upload_id WHERE u.user_id=?",(user_id,)); canonical=c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM learning_audit WHERE user_id=? AND confirmed=1",(user_id,)); confirmed=c.fetchone()[0]
    conn.close(); return {"datasets":datasets,"uploaded_rows":total_rows,"canonical_customers":canonical,"confirmed_learning_sessions":confirmed}


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


def save_customer_intelligence_features(features_df, upload_id: int = None):
    """Lưu feature engineering của Customer Intelligence.

    Hàm này chỉ lưu feature đã tính từ dữ liệu canonical; không ghi đè canonical
    và không tạo dữ liệu giả cho các trường đang thiếu.
    """
    if features_df is None or getattr(features_df, "empty", True):
        return 0
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    saved = 0
    for _, row in features_df.iterrows():
        feature_json = {}
        for key in [
            "age", "gender", "job", "location", "total_spending",
            "order_count", "average_order_value", "discount_usage",
            "product_category", "channel", "device", "acquisition_source",
            "review_text", "rfm_segment", "monthly_income", "signup_date", "return_count",
            "website_visits_30d", "email_open_rate", "cart_abandon_rate", "satisfaction_score",
            "loyalty_tier", "average_order_value_final", "customer_tenure_days",
            "purchase_frequency_per_month", "return_rate", "discount_dependency",
            "engagement_score", "customer_value_score", "customer_value_tier",
            "behavioral_loyalty_index", "churn_signal_score", "_feature_sources",
        ]:
            value = row.get(key)
            if pd.isna(value) if not isinstance(value, (dict, list)) else False:
                continue
            feature_json[key] = value.item() if hasattr(value, "item") else value

        cur.execute("""
            INSERT INTO customer_intelligence_features
            (canonical_customer_id, upload_id, customer_id, recency_days,
             frequency, monetary, r_score, f_score, m_score, rfm_score,
             price_sensitivity, data_reliability, feature_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            None,
            upload_id,
            row.get("customer_id"),
            row.get("recency_days"), row.get("frequency"), row.get("monetary"),
            row.get("r_score"), row.get("f_score"), row.get("m_score"),
            row.get("rfm_score"), row.get("price_sensitivity"),
            row.get("data_reliability"), json.dumps(feature_json, ensure_ascii=False, default=str),
        ))
        saved += 1
    conn.commit()
    conn.close()
    return saved


def get_customer_intelligence_features(upload_id: int = None, limit: int = 5000):
    """Đọc feature đã lưu; trả về list dict để UI/analytics dùng tiếp."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    if upload_id is None:
        rows = conn.execute(
            "SELECT * FROM customer_intelligence_features ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM customer_intelligence_features WHERE upload_id=? ORDER BY id DESC LIMIT ?",
            (upload_id, limit),
        ).fetchall()
    result = [dict(r) for r in rows]
    conn.close()
    return result


def save_customer_segments(segmented_df, profiles, upload_id=None, silhouette=None):
    """Lưu kết quả Hybrid Segmentation; không sửa canonical_customers."""
    if segmented_df is None or getattr(segmented_df, "empty", True):
        return 0
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    saved = 0
    for _, row in segmented_df.iterrows():
        sid = int(row.get("segment_id", 0))
        profile = profiles.get(sid, {}) if isinstance(profiles, dict) else {}
        cur.execute("""
            INSERT INTO customer_segments
            (upload_id, customer_id, segment_id, segment_name, clustering_method, silhouette_score, profile_json, segment_confidence, segment_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            upload_id, row.get("customer_id"), sid, profile.get("segment_name", "Customer Segment"),
            "hybrid_provenance_aware_v2", silhouette, json.dumps(profile, ensure_ascii=False, default=str),
            row.get("segment_confidence"), row.get("segment_reason")
        ))
        saved += 1
    conn.commit()
    conn.close()
    return saved


def save_segmentation_run(upload_id: int, segmentation_result: dict):
    """Persist one overall segmentation-quality snapshot for an upload."""
    if not segmentation_result or segmentation_result.get("status") != "ok":
        return None
    init_db(); conn=sqlite3.connect(DB_PATH); cur=conn.cursor()
    quality=segmentation_result.get("quality") or {}
    cur.execute("DELETE FROM segmentation_runs WHERE upload_id=?", (upload_id,))
    cur.execute("""INSERT INTO segmentation_runs
        (upload_id,n_clusters,silhouette,stability,quality_score,quality_status,metrics_json)
        VALUES (?,?,?,?,?,?,?)""", (
        upload_id, segmentation_result.get("n_clusters"), segmentation_result.get("silhouette"),
        quality.get("stability"), quality.get("score"), quality.get("status"),
        json.dumps(quality,ensure_ascii=False,default=str),
    ))
    rid=cur.lastrowid; conn.commit(); conn.close(); return rid


def get_segmentation_run(upload_id: int):
    init_db(); conn=sqlite3.connect(DB_PATH); conn.row_factory=sqlite3.Row
    row=conn.execute("SELECT * FROM segmentation_runs WHERE upload_id=? ORDER BY id DESC LIMIT 1",(upload_id,)).fetchone(); conn.close()
    if not row: return None
    d=dict(row)
    try: d["metrics"]=json.loads(d.pop("metrics_json") or "{}")
    except Exception: d["metrics"]={}
    return d


def get_customer_segments(upload_id=None, limit=5000):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    if upload_id is None:
        rows = conn.execute("SELECT * FROM customer_segments ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM customer_segments WHERE upload_id=? ORDER BY id DESC LIMIT ?", (upload_id, limit)).fetchall()
    result = [dict(r) for r in rows]
    conn.close()
    return result


def classify_purchase_intent(score, sentiment):
    """Suy ra ý định mua mô phỏng từ điểm và cảm xúc; đây không phải tỷ lệ mua thực tế."""
    try:
        score = int(score)
    except (ValueError, TypeError):
        score = 5
    sentiment = str(sentiment or 'neutral').lower()
    if sentiment == 'negative' or score <= 3:
        return 'not_buy'
    if sentiment == 'positive' and score >= 7:
        return 'buy'
    return 'hesitate'


def save_simulation(scenario, results, analysis, user_id=None):
    """Lưu chiến dịch và phản hồi theo tài khoản, giữ nguyên lịch sử cũ."""
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
    star_rating = max(1, min(5, star_rating))
    cursor.execute("INSERT INTO scenarios (scenario_text,strengths,weaknesses,summary,star_rating,user_id) VALUES (?,?,?,?,?,?)",
                   (scenario, strengths, weaknesses, summary, star_rating, user_id))
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
        if sentiment not in ('positive', 'negative', 'neutral'):
            sentiment = 'neutral'
        reasoning = str(r.get('reasoning', 'Khách hàng không để lại bình luận chi tiết.'))
        intent = str(r.get('purchase_intent') or classify_purchase_intent(score, sentiment))
        cursor.execute("INSERT INTO simulation_results (scenario_id,persona_name,score,sentiment,reasoning,purchase_intent) VALUES (?,?,?,?,?,?)",
                       (sid, persona_name, score, sentiment, reasoning, intent))
    conn.commit()
    conn.close()
    return sid


def get_all_scenarios(user_id=None):
    """Danh sách chiến dịch theo tài khoản nếu user_id được cung cấp."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    if user_id is None:
        cur.execute("SELECT id, scenario_text, star_rating FROM scenarios ORDER BY id DESC")
    else:
        cur.execute("SELECT id, scenario_text, star_rating FROM scenarios WHERE user_id=? ORDER BY id DESC", (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_scenario_by_id(sid, user_id=None):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    if user_id is None:
        cur.execute("SELECT * FROM scenarios WHERE id=?", (sid,))
    else:
        cur.execute("SELECT * FROM scenarios WHERE id=? AND user_id=?", (sid, user_id))
    row = cur.fetchone()
    conn.close()
    return row


def get_results_by_scenario(sid, user_id=None) -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    if user_id is None:
        df = pd.read_sql_query("SELECT persona_name, score, sentiment, reasoning, purchase_intent FROM simulation_results WHERE scenario_id=?", conn, params=(sid,))
    else:
        df = pd.read_sql_query("""
            SELECT r.persona_name, r.score, r.sentiment, r.reasoning, r.purchase_intent
            FROM simulation_results r JOIN scenarios s ON s.id=r.scenario_id
            WHERE r.scenario_id=? AND s.user_id=?
        """, conn, params=(sid, user_id))
    conn.close()
    return df


def get_user_campaign_overview(user_id: int) -> dict:
    """Tổng hợp dashboard chiến dịch theo tài khoản hiện tại."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    row = cur.execute("SELECT COUNT(*) FROM scenarios WHERE user_id=?", (user_id,)).fetchone()
    projects = int(row[0] or 0)
    total_responses = cur.execute("""
        SELECT COUNT(*) FROM simulation_results r
        JOIN scenarios s ON s.id=r.scenario_id
        WHERE s.user_id=?
    """, (user_id,)).fetchone()[0] or 0
    counts = {'buy': 0, 'hesitate': 0, 'not_buy': 0}
    for intent, n in cur.execute("""
        SELECT r.purchase_intent, COUNT(*)
        FROM simulation_results r JOIN scenarios s ON s.id=r.scenario_id
        WHERE s.user_id=? GROUP BY r.purchase_intent
    """, (user_id,)).fetchall():
        if intent in counts:
            counts[intent] = int(n or 0)
    sentiments = {'positive':0,'neutral':0,'negative':0}
    for sentiment, n in cur.execute("""
        SELECT LOWER(COALESCE(r.sentiment,'neutral')), COUNT(*)
        FROM simulation_results r JOIN scenarios s ON s.id=r.scenario_id
        WHERE s.user_id=? GROUP BY LOWER(COALESCE(r.sentiment,'neutral'))
    """, (user_id,)).fetchall():
        if sentiment in sentiments: sentiments[sentiment] = int(n or 0)
    avg_score = cur.execute("""SELECT AVG(r.score) FROM simulation_results r JOIN scenarios s ON s.id=r.scenario_id WHERE s.user_id=?""", (user_id,)).fetchone()[0]
    latest = cur.execute("SELECT id,scenario_text,star_rating FROM scenarios WHERE user_id=? ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
    conn.close()
    def pct(n): return round((n/total_responses*100),1) if total_responses else 0.0
    return {
        'projects': projects, 'responses': int(total_responses),
        'purchase_intent': {k:{'count':v,'pct':pct(v)} for k,v in counts.items()},
        'sentiment': {k:{'count':v,'pct':pct(v)} for k,v in sentiments.items()},
        'avg_score': round(float(avg_score),2) if avg_score is not None else 0,
        'latest_campaign': {'id':latest[0],'name':latest[1],'rating':latest[2]} if latest else None
    }

def save_customer_personas(personas, upload_id=None):
    if not personas:
        return 0
    conn = sqlite3.connect(DB_PATH)
    try:
        for persona in personas:
            conn.execute(
                """INSERT INTO customer_personas
                (upload_id, segment_id, persona_name, segment_size, confidence, generation_source, persona_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (upload_id, int(persona.get('segment_id', 0)),
                 str(persona.get('persona_name', 'Customer Persona')),
                 int(persona.get('segment_size', 0)), float(persona.get('confidence', 0)),
                 str(persona.get('generation_source', 'real_data_profile')),
                 json.dumps(persona, ensure_ascii=False)),
            )
        conn.commit()
        return len(personas)
    finally:
        conn.close()


def get_customer_personas(upload_id=None, limit=100):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        if upload_id is None:
            rows = conn.execute("SELECT * FROM customer_personas ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM customer_personas WHERE upload_id=? ORDER BY id DESC LIMIT ?", (upload_id, limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def save_synthetic_customer_twins(twins, upload_id=None):
    """Lưu Synthetic Twins; không đụng vào canonical_customers."""
    if not twins:
        return 0
    init_db()
    conn = sqlite3.connect(DB_PATH)
    try:
        saved = 0
        for twin in twins:
            twin_id = str(twin.get("twin_id"))
            conn.execute(
                """INSERT OR REPLACE INTO synthetic_customer_twins
                (upload_id, twin_id, segment_id, confidence, generation_method, proxy_scores_json, twin_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (upload_id, twin_id, int(twin.get("segment_id", 0)),
                 float(twin.get("confidence", 0)), str(twin.get("generation_method", "")),
                 json.dumps(twin.get("proxy_scores", {}), ensure_ascii=False),
                 json.dumps(twin, ensure_ascii=False)),
            )
            saved += 1
        conn.commit()
        return saved
    finally:
        conn.close()


def get_synthetic_customer_twins(upload_id=None, segment_id=None, limit=5000):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        where, params = [], []
        if upload_id is not None:
            where.append("upload_id=?"); params.append(upload_id)
        if segment_id is not None:
            where.append("segment_id=?"); params.append(int(segment_id))
        sql = "SELECT * FROM synthetic_customer_twins"
        if where: sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"; params.append(int(limit))
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        for r in rows:
            try: r["twin"] = json.loads(r["twin_json"] or "{}")
            except Exception: r["twin"] = {}
        return rows
    finally:
        conn.close()


def save_advanced_experiment(experiment_type, campaign_text, summary, results, budget=0, model_version="heuristic_v1"):
    init_db(); con=sqlite3.connect(DB_PATH); cur=con.cursor()
    cur.execute("INSERT INTO advanced_experiments (experiment_type,campaign_text,population_size,conversion_rate,click_rate,purchase_intent,expected_revenue,budget,roi_index,model_version,result_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (experiment_type,campaign_text,int(summary.get("population",len(results))),summary.get("conversion_rate"),summary.get("click_rate"),summary.get("purchase_intent"),summary.get("expected_revenue"),budget,summary.get("roi_index"),model_version,json.dumps(summary,ensure_ascii=False)))
    eid=cur.lastrowid
    for r in results:
        cur.execute("INSERT INTO advanced_experiment_results (experiment_id,twin_id,segment_id,conversion_probability,click_probability,purchase_intent,expected_revenue,sentiment,score,result_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (eid,r.get("twin_id"),r.get("segment_id"),r.get("conversion_probability"),r.get("click_probability"),r.get("purchase_intent"),r.get("expected_revenue"),r.get("sentiment"),r.get("score"),json.dumps(r,ensure_ascii=False)))
    con.commit(); con.close(); return eid

def get_advanced_experiments(limit=100):
    init_db(); con=sqlite3.connect(DB_PATH); con.row_factory=sqlite3.Row
    rows=[dict(r) for r in con.execute("SELECT * FROM advanced_experiments ORDER BY id DESC LIMIT ?",(limit,)).fetchall()]; con.close(); return rows

def get_advanced_results(experiment_id):
    init_db(); con=sqlite3.connect(DB_PATH); df=pd.read_sql_query("SELECT * FROM advanced_experiment_results WHERE experiment_id=?",con,params=(experiment_id,)); con.close(); return df


# ==============================================================================
# CHAT MEMORY - persistent assistant conversation per user
# ==============================================================================
def save_chat_message(user_id: int, role: str, content: str, provider: str | None = None, company_id: int | None = None) -> int:
    init_db()
    role = str(role or '').strip().lower()
    if role not in ('user', 'assistant'):
        raise ValueError('role chat phải là user hoặc assistant')
    content = str(content or '').strip()
    if not content:
        return 0
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO chat_messages(user_id,company_id,role,content,provider) VALUES(?,?,?,?,?)",
        (int(user_id), company_id, role, content, provider),
    )
    msg_id = int(cur.lastrowid)
    conn.commit(); conn.close()
    return msg_id


def get_chat_history(user_id: int, limit: int = 100, company_id: int | None = None) -> list:
    """Trả lịch sử theo thứ tự cũ -> mới. company_id là lớp cách ly bổ sung."""
    init_db(); limit=max(1,min(int(limit or 100),1000))
    conn=sqlite3.connect(DB_PATH); conn.row_factory=sqlite3.Row; cur=conn.cursor()
    sql="SELECT id,user_id,company_id,role,content,provider,created_at FROM chat_messages WHERE user_id=?"
    params=[int(user_id)]
    if company_id is not None:
        sql += " AND (company_id=? OR company_id IS NULL)"; params.append(int(company_id))
    sql += " ORDER BY id DESC LIMIT ?"; params.append(limit)
    rows=cur.execute(sql,tuple(params)).fetchall(); conn.close()
    return [dict(r) for r in reversed(rows)]


def clear_chat_history(user_id: int, company_id: int | None = None) -> int:
    init_db(); conn=sqlite3.connect(DB_PATH); cur=conn.cursor()
    if company_id is None:
        cur.execute("DELETE FROM chat_messages WHERE user_id=?",(int(user_id),))
    else:
        cur.execute("DELETE FROM chat_messages WHERE user_id=? AND (company_id=? OR company_id IS NULL)",(int(user_id),int(company_id)))
    deleted=int(cur.rowcount or 0); conn.commit(); conn.close(); return deleted
