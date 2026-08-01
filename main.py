# ============================================================================== 
# MAIN.PY - ĐẦU NÃO ĐIỀU HÀNH HỆ THỐNG MARKETSIM AI
# Tích hợp 2 chế độ: Desktop (CustomTkinter) và Web (Streamlit)
# ============================================================================== 

import argparse
import os
import subprocess
import sys
import webbrowser

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Ensure UTF-8 output on Windows to avoid 'charmap' codec errors when
# printing or logging Unicode characters. This sets PYTHONUTF8 and attempts
# to reconfigure stdout/stderr to UTF-8 where supported.
os.environ.setdefault("PYTHONUTF8", "1")
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ------------------------------------------------------------------------------
# 1. IMPORT CÁC MODULE CHÍNH
# ------------------------------------------------------------------------------
try:
    from config import DB_PATH, OLLAMA_MODEL
    from data_collector import collect_all
    from clustering import cluster_customer_psychology
    from persona_simulator import generate_personas, simulate_marketing_scenario
    from database import save_simulation
except Exception as e:
    print(f"⚠️ Không thể import đầy đủ module cốt lõi: {e}")
    collect_all = None
    cluster_customer_psychology = None
    generate_personas = None
    simulate_marketing_scenario = None
    save_simulation = None

# ------------------------------------------------------------------------------
# 2. IMPORT GIAO DIỆN CHO CÁC CHẾ ĐỘ
# ------------------------------------------------------------------------------
try:
    from app_gui import ModernMarketSimApp
except Exception:
    ModernMarketSimApp = None


# ============================================================================== 
# 3. HÀM HỖ TRỢ CHỌN CHẾ ĐỘ
# ============================================================================== 
def print_launcher_menu():
    print("\n" + "=" * 72)
    print("🚀 MARKETSIM AI — TRÌNH KHỞI CHẠY")
    print("=" * 72)
    print("Chọn cách mở hệ thống:")
    print("  [1] 🌐 WE      — Mở giao diện Streamlit trên trình duyệt")
    print("  [2] 🖥️ DESKTOP  — Mở ứng dụng Desktop bằng CustomTkinter")
    print("  [3] 🔎 CHECK    — Chỉ kiểm tra môi trường trước khi chạy")
    print("=" * 72)


def prompt_mode():
    print_launcher_menu()
    while True:
        choice = input("Nhập lựa chọn [1/2/3 hoặc web/desktop/check]: ").strip().lower()
        mapping = {
            "1": "web",
            "web": "web",
            "2": "desktop",
            "desktop": "desktop",
            "3": "check",
            "check": "check",
        }
        if choice in mapping:
            return mapping[choice]
        print("⚠️ Lựa chọn không hợp lệ. Hãy nhập 1, 2, 3 hoặc web/desktop/check.")


def validate_environment(mode: str):
    issues = []

    if mode == "web":
        try:
            import streamlit  # noqa: F401
        except ImportError:
            issues.append("Thiếu thư viện streamlit")
        if not os.path.exists(os.path.join(BASE_DIR, "web_app.py")):
            issues.append("Không tìm thấy file web_app.py")
    elif mode == "desktop":
        try:
            import customtkinter  # noqa: F401
        except ImportError:
            issues.append("Thiếu thư viện customtkinter")
        if not os.path.exists(os.path.join(BASE_DIR, "app_gui.py")):
            issues.append("Không tìm thấy file app_gui.py")

    if issues:
        print("⚠️ Một số thành phần cần thiết chưa sẵn sàng:")
        for item in issues:
            print(f"   - {item}")
        return False

    print("✅ Môi trường đã sẵn sàng.")
    return True


def launch_web():
    file_web = os.path.join(BASE_DIR, "web_app.py")
    if not os.path.exists(file_web):
        print(f"❌ Không tìm thấy {file_web}")
        return 1

    print("🌐 Đang khởi chạy giao diện Web (Streamlit)...")
    print("🔗 Truy cập: http://localhost:8501")
    try:
        webbrowser.open("http://localhost:8501")
    except Exception:
        pass

    try:
        subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", file_web, "--server.headless", "true", "--server.port", "8501"],
            cwd=BASE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
        print("✅ Streamlit đã được mở ở nền. Nhấn Ctrl+C để dừng.")
        return 0
    except Exception as e:
        print(f"❌ Không thể khởi chạy Streamlit: {e}")
        return 1


def launch_desktop():
    print("🖥️ Đang mở giao diện Desktop (CustomTkinter)...")
    if ModernMarketSimApp is None:
        print("❌ Không thể khởi động Desktop vì module app_gui chưa sẵn sàng.")
        return 1

    try:
        app = ModernMarketSimApp()
        app.mainloop()
        return 0
    except Exception as e:
        print(f"❌ Lỗi khi mở Desktop UI: {e}")
        return 1


def run_pipeline_and_launch(mode: str = None):
    if mode is None:
        mode = prompt_mode()

    mode = mode.lower()
    print(f"⚙️  Chế độ được chọn: {mode.upper()}")

    if mode == "check":
        validate_environment("web")
        validate_environment("desktop")
        return 0

    if not validate_environment(mode):
        return 1

    if mode == "web":
        return launch_web()
    if mode == "desktop":
        return launch_desktop()

    print("⚠️ Chế độ không hợp lệ. Hãy chọn web hoặc desktop.")
    return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Khởi chạy MarketSim AI ở chế độ Web hoặc Desktop")
    parser.add_argument("mode", nargs="?", choices=["web", "desktop", "check"], help="Chế độ chạy")
    parser.add_argument("--check", action="store_true", help="Chỉ kiểm tra môi trường mà không mở ứng dụng")
    args = parser.parse_args()

    selected_mode = args.mode
    if args.check:
        selected_mode = "check"

    sys.exit(run_pipeline_and_launch(selected_mode))
