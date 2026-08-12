\
"""MarketSim AI - kiểm tra an toàn trước khi cập nhật/deploy.

Mục tiêu:
- Không gọi Groq/Ollama/Pytrends hay Internet.
- Không chạm vào marketsim.db thật: mọi kiểm tra dữ liệu chạy trên SQLite tạm.
- Bắt sớm lỗi lệch phiên bản giữa các file, route bị mất, mã doanh nghiệp/nhân viên
  bị hỏng và lỗi cách ly dữ liệu cơ bản.

Chạy:
    python VERIFY_MARKETSIM_ENTERPRISE.py
"""
from __future__ import annotations

import ast
import importlib
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parent
PASS = []
FAIL = []


def ok(name: str, detail: str = ""):
    PASS.append(name)
    print(f"[OK] {name}" + (f" - {detail}" if detail else ""))


def bad(name: str, exc):
    FAIL.append((name, str(exc)))
    print(f"[LOI] {name} - {exc}")


def check(name, fn):
    try:
        fn()
        ok(name)
    except Exception as exc:
        bad(name, exc)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def syntax_check():
    errors = []
    for p in ROOT.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        try:
            ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except Exception as exc:
            errors.append(f"{p.relative_to(ROOT)}: {exc}")
    require(not errors, " | ".join(errors))


def required_files_check():
    required = [
        "backend/main.py", "backend/admin_db.py", "backend/auth_db.py",
        "database.py", "config.py", "schema_mapper.py", "data_preprocessor.py",
        "customer_intelligence.py", "hybrid_segmentation.py", "digital_twin.py",
        "advanced_simulation.py", "staged_data_workflow.py", "data_quality_engine.py",
        "frontend/index.html", "frontend/admin.html", "frontend/pages/login.html",
        "frontend/js/app.js", "frontend/js/admin.js",
    ]
    missing = [x for x in required if not (ROOT / x).exists()]
    require(not missing, "Thiếu file: " + ", ".join(missing))


def cross_file_import_check():
    main_ast = ast.parse((ROOT / "backend/main.py").read_text(encoding="utf-8"))
    requested = []
    for node in ast.walk(main_ast):
        if isinstance(node, ast.ImportFrom) and node.module == "admin_db" and node.level == 1:
            requested.extend(a.name for a in node.names)
    admin_ast = ast.parse((ROOT / "backend/admin_db.py").read_text(encoding="utf-8"))
    available = {n.name for n in admin_ast.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    missing = sorted(set(requested) - available)
    require(not missing, "backend/main.py đang gọi hàm không tồn tại trong admin_db.py: " + ", ".join(missing))


def route_check():
    # Import only after the temporary DB path is configured by runtime_checks().
    main = importlib.import_module("backend.main")
    routes = {(getattr(r, "path", ""), tuple(sorted(getattr(r, "methods", set()) or []))) for r in main.app.routes}
    paths = {p for p, _ in routes}
    required = {
        "/api/auth/validate-company-code",
        "/api/auth/register",
        "/api/auth/register-admin",
        "/api/admin/staff",
        "/api/admin/team-status",
        "/api/admin/team-repair",
        "/api/customers/inspect",
        "/api/customers/learning/history",
        "/api/chat/history",
        "/api/chat/memory",
        "/api/system/health",
    }
    missing = sorted(required - paths)
    require(not missing, "Thiếu API quan trọng: " + ", ".join(missing))


def runtime_checks():
    # This test DB is disposable and is never the user's real marketsim.db.
    tmp = tempfile.TemporaryDirectory(prefix="marketsim_verify_")
    test_db = Path(tmp.name) / "verify.db"
    os.environ["MARKETSIM_DB_PATH"] = str(test_db)
    os.environ.setdefault("GROQ_API_KEY", "")

    # Ensure a previous accidental import cannot point to the real DB.
    for name in [x for x in list(sys.modules) if x == "config" or x == "database" or x.startswith("backend.")]:
        sys.modules.pop(name, None)

    config = importlib.import_module("config")
    require(Path(config.DB_PATH).resolve() == test_db.resolve(), "Kiểm tra đang trỏ nhầm database thật")
    db = importlib.import_module("database")
    auth = importlib.import_module("backend.auth_db")
    adm = importlib.import_module("backend.admin_db")

    db.init_db(); auth.init_auth(); adm.init_admin_schema(); db.init_db()

    # 1) Account + password.
    a = db.create_user("admin-a@verify.local", "123456")
    b = db.create_user("admin-b@verify.local", "123456")
    require(db.verify_user("admin-a@verify.local", "123456"), "Đăng nhập thử ADMIN A thất bại")

    # 2) Two businesses, each with its own join code.
    ca = adm.create_company_admin(a, "Quản trị A", "Doanh nghiệp A")
    cb = adm.create_company_admin(b, "Quản trị B", "Doanh nghiệp B")
    code_a = ca["join_code"]
    require(adm.find_admin_by_join_code(code_a.lower())["id"] == a, "Mã doanh nghiệp viết thường không được nhận")
    compact = code_a.replace("-", "")
    require(adm.find_admin_by_join_code(compact)["id"] == a, "Mã doanh nghiệp không dấu gạch không được nhận")

    # 3) Employees attach to the correct company and ADMIN only sees its own staff.
    ea = db.create_user("employee-a@verify.local", "123456")
    eb = db.create_user("employee-b@verify.local", "123456")
    ma = adm.attach_employee(ea, a, "Nhân viên A")
    mb = adm.attach_employee(eb, b, "Nhân viên B")
    require(ma["company_id"] != mb["company_id"], "Hai doanh nghiệp bị dùng chung company_id")
    staff_a = {x["id"] for x in adm.admin_staff(a)}
    staff_b = {x["id"] for x in adm.admin_staff(b)}
    require(ea in staff_a and eb not in staff_a, "ADMIN A nhìn thấy sai nhân viên")
    require(eb in staff_b and ea not in staff_b, "ADMIN B nhìn thấy sai nhân viên")
    require(adm.employee_visible_to_admin(a, ea), "Tài khoản nhân viên A đã tạo nhưng ADMIN A chưa nhìn thấy")

    # Dedicated membership mirror must exist and match the visible ADMIN list.
    with sqlite3.connect(test_db) as c:
        membership = c.execute(
            "SELECT company_id,admin_id FROM company_memberships WHERE user_id=?",
            (ea,),
        ).fetchone()
        require(membership is not None, "Không lưu được liên kết nhân viên với doanh nghiệp")
        require(int(membership[0]) == int(ma["company_id"]) and int(membership[1]) == int(a),
                "Liên kết nhân viên A đang trỏ sai doanh nghiệp")

        # Simulate an older/partially migrated install: remove the mirror only.
        c.execute("DELETE FROM company_memberships WHERE user_id=?", (ea,))
        c.commit()
    repaired_staff = {x["id"] for x in adm.admin_staff(a)}
    require(ea in repaired_staff, "ADMIN không tự khôi phục được nhân viên khi bản ghi liên kết cũ bị thiếu")
    with sqlite3.connect(test_db) as c:
        require(c.execute("SELECT 1 FROM company_memberships WHERE user_id=?", (ea,)).fetchone() is not None,
                "Danh sách ADMIN không tạo lại được liên kết bền vững cho nhân viên")

    # Simulate a legacy employee that only has admin_owner_id.
    legacy = db.create_user("legacy-a@verify.local", "123456")
    with sqlite3.connect(test_db) as c:
        c.execute("UPDATE users SET role='employee',admin_owner_id=?,company_id=NULL,display_name='Nhân viên cũ' WHERE id=?", (a, legacy))
        c.commit()
    adm.repair_company_memberships(a)
    legacy_staff = {x["id"] for x in adm.admin_staff(a)}
    require(legacy in legacy_staff, "Không khôi phục được nhân viên cũ đã có chủ doanh nghiệp rõ ràng")

    # 4) Dataset ownership isolation.
    ua = db.save_uploaded_dataset("a.csv", [{"customer_id":"A-1","age":25}], ["customer_id","age"], user_id=ea)
    ub = db.save_uploaded_dataset("b.csv", [{"customer_id":"B-1","age":31}], ["customer_id","age"], user_id=eb)
    ha = {x["id"] for x in db.get_user_dataset_history(ea)}
    hb = {x["id"] for x in db.get_user_dataset_history(eb)}
    require(ua in ha and ub not in ha, "Nhân viên A nhìn thấy bộ dữ liệu của doanh nghiệp khác")
    require(ub in hb and ua not in hb, "Nhân viên B nhìn thấy bộ dữ liệu của doanh nghiệp khác")

    # 5) Background job ownership isolation.
    db.create_background_job("JOB-A", ea, ma["company_id"], "verify", {})
    require(db.get_background_job("JOB-A", ea) is not None, "Chủ tiến trình không đọc được tiến trình của mình")
    require(db.get_background_job("JOB-A", eb) is None, "Tài khoản khác đọc được tiến trình không thuộc mình")

    # 6) Chat history + long-term memory ownership isolation.
    db.save_chat_message(ea, "user", "Tin nhắn A", company_id=ma["company_id"])
    db.save_chat_message(eb, "user", "Tin nhắn B", company_id=mb["company_id"])
    cha = db.get_chat_history(ea, company_id=ma["company_id"])
    chb = db.get_chat_history(eb, company_id=mb["company_id"])
    require(any(x.get("content") == "Tin nhắn A" for x in cha), "Không đọc được lịch sử chat A")
    require(not any(x.get("content") == "Tin nhắn B" for x in cha), "Chat của B bị lẫn sang A")
    require(any(x.get("content") == "Tin nhắn B" for x in chb), "Không đọc được lịch sử chat B")

    db.upsert_chat_memory(ea, "preferred_name", "Nguyễn Đức Anh", company_id=ma["company_id"])
    db.upsert_chat_memory(eb, "preferred_name", "Nhân viên B", company_id=mb["company_id"])
    mem_a = db.get_chat_memories(ea, company_id=ma["company_id"])
    mem_b = db.get_chat_memories(eb, company_id=mb["company_id"])
    require(any(x.get("memory_value") == "Nguyễn Đức Anh" for x in mem_a), "Trí nhớ dài hạn A không lưu được")
    require(not any(x.get("memory_value") == "Nhân viên B" for x in mem_a), "Trí nhớ chat của B bị lẫn sang A")
    require(any(x.get("memory_value") == "Nhân viên B" for x in mem_b), "Trí nhớ dài hạn B không lưu được")

    # Verify the conversation layer can recognize an explicit preferred name
    # without calling any AI provider.
    main_mod = importlib.import_module("backend.main")
    extracted = main_mod._extract_explicit_chat_memories("Từ giờ hãy gọi tôi là Nguyễn Đức Anh")
    require(any(x.get("key") == "preferred_name" and x.get("value") == "Nguyễn Đức Anh" for x in extracted),
            "Không nhận ra tên người dùng đã nói rõ")
    question_mem = main_mod._extract_explicit_chat_memories("Tôi tên là gì?")
    require(not any(x.get("key") == "preferred_name" for x in question_mem),
            "Câu hỏi 'Tôi tên là gì?' không được ghi đè tên đã nhớ")
    built, _ = main_mod._build_chat_messages(
        [{"id":1,"role":"user","content":"Tôi tên là Nguyễn Đức Anh"}],
        [{"memory_key":"preferred_name","memory_value":"Nguyễn Đức Anh"}],
        "Tôi tên là gì?"
    )
    require(any("Nguyễn Đức Anh" in x.get("content","") for x in built if x.get("role")=="system"),
            "Bộ nhớ tên chưa được đưa vào ngữ cảnh trả lời")

    # 7) Important migrations exist.
    with sqlite3.connect(test_db) as c:
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in ["users","companies","company_memberships","uploaded_datasets","canonical_customers","learning_audit","background_jobs","chat_messages","chat_memory"]:
        require(table in tables, f"Thiếu bảng {table}")

    # 8) Backend import + route compatibility, catches stale patch combinations.
    route_check()
    tmp.cleanup()


def friendly_ui_check():
    index = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
    admin = (ROOT / "frontend/admin.html").read_text(encoding="utf-8")
    login = (ROOT / "frontend/pages/login.html").read_text(encoding="utf-8")
    must_have = [
        "ĐIỂM CHẤT LƯỢNG DỮ LIỆU",
        "MỨC SẴN SÀNG TẠO KHÁCH HÀNG ẢO",
        "CHẤT LƯỢNG PHÂN NHÓM",
        "Mã nội bộ hệ thống",
        "quản trị viên riêng",
    ]
    all_text = index + admin + login
    missing = [x for x in must_have if x not in all_text]
    require(not missing, "Giao diện dễ hiểu bị thiếu nhãn: " + ", ".join(missing))


def main():
    print("=" * 64)
    print("MARKETSIM AI - KIỂM TRA AN TOÀN TRƯỚC KHI CẬP NHẬT")
    print("Không gọi AI/Internet và không sử dụng marketsim.db thật.")
    print("=" * 64)
    check("Cấu trúc file quan trọng", required_files_check)
    check("Cú pháp Python", syntax_check)
    check("Các file backend khớp phiên bản", cross_file_import_check)
    check("Ngôn ngữ giao diện dễ hiểu", friendly_ui_check)
    check("Tài khoản, mã doanh nghiệp, nhân viên và cách ly dữ liệu", runtime_checks)
    print("-" * 64)
    if FAIL:
        print(f"KẾT QUẢ: CẦN SỬA - {len(FAIL)} mục chưa đạt")
        for name, detail in FAIL:
            print(f"  • {name}: {detail}")
        return 1
    print(f"KẾT QUẢ: AN TOÀN - {len(PASS)} nhóm kiểm tra đều đạt")
    print("Bạn có thể tiếp tục chạy local hoặc commit/deploy bản cập nhật này.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
