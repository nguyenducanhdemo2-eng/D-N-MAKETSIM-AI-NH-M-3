"""
desktop_app.py — Trình khởi chạy giao diện DESKTOP cho MarketSim AI.

CÁCH HOẠT ĐỘNG (đơn giản, không viết lại UI):
  1. Chạy server Streamlit của chính "web_app.py" hiện có, NGAY TRONG CÙNG
     tiến trình (dùng streamlit.web.cli), lắng nghe ở 127.0.0.1 (localhost)
     tại 1 cổng còn trống — không ai bên ngoài máy truy cập được.
  2. Mở 1 cửa sổ desktop gốc (pywebview) trỏ vào địa chỉ localhost đó.
  Kết quả: giao diện HIỂN THỊ Y HỆT bản web, vì dùng chung 100% code
  web_app.py — không có bản UI thứ hai nào phải bảo trì song song.

TẠI SAO chạy Streamlit "trong cùng tiến trình" thay vì mở tiến trình con
(subprocess gọi `python -m streamlit run ...`)?
  Vì sau khi đóng gói bằng PyInstaller thành file .exe/.app, bên trong KHÔNG
  còn một trình thông dịch `python` độc lập để subprocess gọi lại — cách
  "gọi hàm main() của Streamlit ngay trong tiến trình hiện tại, chạy ở 1
  luồng nền (thread)" là cách chuẩn, hoạt động giống nhau cho cả lúc chạy
  bằng lệnh `python desktop_app.py` (khi đang phát triển) LẪN lúc đã đóng
  gói thành .exe/.app.

YÊU CẦU CÀI ĐẶT (trên máy dùng để BUILD hoặc để CHẠY THỬ bằng mã nguồn):
    pip install pywebview
  Windows: cần Microsoft Edge WebView2 Runtime (mặc định đã có sẵn trên
  Windows 10/11 bản cập nhật gần đây; nếu thiếu, cài tại
  https://developer.microsoft.com/microsoft-edge/webview2/).
  macOS: dùng WKWebView có sẵn trong hệ điều hành, không cần cài thêm.

LƯU Ý QUAN TRỌNG (tôi chưa build/chạy thử được file này trên máy Windows
hay macOS thật — môi trường của tôi không có 2 hệ điều hành đó, cũng không
có mạng để cài pywebview và kiểm tra API thực tế). Hãy chạy thử bằng:
    python desktop_app.py
trước, đảm bảo cửa sổ mở lên đúng như bản web, RỒI mới build thành .exe/.app.
"""
import os
import sys
import socket
import threading
import time

APP_TITLE = "MarketSim AI"
ENTRY_SCRIPT = "web_app.py"  # phải nằm cùng thư mục với desktop_app.py / file .exe


def _resource_dir() -> str:
    """Thư mục chứa web_app.py và các module đi kèm.
    - Khi chạy bằng `python desktop_app.py`: là thư mục chứa file này.
    - Khi đã đóng gói bằng PyInstaller (--onefile): PyInstaller giải nén
      các file được khai báo qua --add-data vào thư mục tạm sys._MEIPASS.
    - Khi đóng gói kiểu --onedir: các file đi kèm nằm cạnh chính file .exe.
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass and os.path.exists(os.path.join(meipass, ENTRY_SCRIPT)):
            return meipass
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(port: int, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def _run_streamlit_in_background(port: int) -> None:
    """Gọi thẳng vào Streamlit CLI (không mở tiến trình con) — chạy trong
    1 luồng nền daemon để không chặn cửa sổ desktop."""
    entry_path = os.path.join(_resource_dir(), ENTRY_SCRIPT)
    if not os.path.exists(entry_path):
        raise FileNotFoundError(
            f"Không tìm thấy '{ENTRY_SCRIPT}' tại: {entry_path}\n"
            f"Hãy đảm bảo web_app.py (và các module đi kèm: database.py, "
            f"config.py, clustering.py, persona_simulator.py, "
            f"data_collector.py, data_preprocessor.py, thư mục DATA/...) "
            f"nằm cùng chỗ với desktop_app.py / file .exe đã build."
        )

    import streamlit.web.cli as stcli

    sys.argv = [
        "streamlit", "run", entry_path,
        "--server.port", str(port),
        "--server.address", "127.0.0.1",
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
        "--global.developmentMode", "false",
    ]

    def _target():
        stcli.main()

    t = threading.Thread(target=_target, daemon=True)
    t.start()


def main():
    port = _find_free_port()
    _run_streamlit_in_background(port)

    if not _wait_for_server(port):
        raise RuntimeError(
            "Không khởi động được server nội bộ (Streamlit) sau 30 giây. "
            "Kiểm tra lại các module phụ trợ có nằm cùng thư mục với "
            "web_app.py không, hoặc mở terminal chạy trực tiếp "
            "`streamlit run web_app.py` để xem lỗi chi tiết."
        )

    import webview  # import trễ để thông báo lỗi thiếu server rõ ràng trước

    webview.create_window(
        APP_TITLE,
        f"http://127.0.0.1:{port}",
        width=1440,
        height=900,
        min_size=(1024, 700),
    )

    # Đóng cửa sổ desktop -> thoát hẳn tiến trình (kể cả luồng Streamlit nền).
    # Vì Streamlit chạy CÙNG tiến trình (không phải subprocess), thoát tiến
    # trình chính là dọn sạch, không để sót server chạy ngầm.
    webview.start()
    os._exit(0)


if __name__ == "__main__":
    main()
