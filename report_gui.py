import tkinter as tk
from tkinter import ttk, scrolledtext
import sqlite3
import threading
from config import DB_PATH
from persona_simulator import chat_with_ollama # Import hàm chat mới

class MarketSimReportApp:
    def __init__(self, root, scenario_id):
        self.root = root
        self.root.title("MarketSim AI Dashboard")
        self.root.geometry("900x750")
        
        # Tabs
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        
        self.tab_report = ttk.Frame(self.notebook)
        self.tab_chat = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_report, text="Báo cáo & SWOT")
        self.notebook.add(self.tab_chat, text="Trợ lý AI (Chat)")
        
        # --- TAB 1: BÁO CÁO (Dữ liệu cũ) ---
        self._build_report_tab(scenario_id)
        
        # --- TAB 2: CHAT AI (Mới) ---
        self._build_chat_tab()

    def _build_report_tab(self, scenario_id):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT * FROM scenarios WHERE id=?", (scenario_id,))
        row = cur.fetchone()
        
        # Đảm bảo row không bị None
        if not row:
            conn.close()
            return

        _, text, s, w, summ, stars = row
        
        # 1. Phần hiển thị Sao và Tóm tắt
        tk.Label(self.tab_report, text="★"*stars + "☆"*(5-stars), font=("Arial", 25), fg="gold").pack(pady=5)
        tk.Label(self.tab_report, text=f"Tóm tắt: {summ}", wraplength=800, font=("Arial", 11)).pack(pady=5)
        
        # 2. SWOT Area (Giảm height một chút để nhường chỗ cho Feed)
        tk.Label(self.tab_report, text="SWOT ANALYSIS", font=("Arial", 12, "bold")).pack()
        swot_area = scrolledtext.ScrolledText(self.tab_report, height=8) 
        swot_area.insert(tk.INSERT, f"ĐIỂM MẠNH:\n{s}\n\nĐIỂM YẾU:\n{w}")
        swot_area.pack(fill=tk.BOTH, padx=20, pady=5)
        
        # 3. PHẦN BỔ SUNG: Feed Bình luận Khách hàng
        tk.Label(self.tab_report, text="FEED BÌNH LUẬN KHÁCH HÀNG", font=("Arial", 12, "bold")).pack(pady=5)
        review_area = scrolledtext.ScrolledText(self.tab_report, height=10)
        
        # Truy vấn dữ liệu bình luận từ bảng simulation_results
        cur.execute("SELECT persona_name, reasoning FROM simulation_results WHERE scenario_id=?", (scenario_id,))
        results = cur.fetchall()
        for n, r in results:
            review_area.insert(tk.INSERT, f"{n}: {r}\n{'-'*40}\n")
        
        review_area.pack(fill=tk.BOTH, padx=20, pady=5)
        conn.close()

    def _build_chat_tab(self):
        self.chat_display = scrolledtext.ScrolledText(self.tab_chat, height=20)
        self.chat_display.pack(fill=tk.BOTH, padx=10, pady=10)
        
        self.chat_input = tk.Entry(self.tab_chat, font=("Arial", 12))
        self.chat_input.pack(fill=tk.X, padx=10, pady=5)
        
        self.btn_send = tk.Button(self.tab_chat, text="Gửi câu hỏi", command=self.send_message)
        self.btn_send.pack(pady=5)
        self.chat_display.insert(tk.INSERT, "AI: Xin chào, tôi là trợ lý MarketSim. Bạn muốn phân tích gì về chiến dịch này?\n")

    def send_message(self):
        user_text = self.chat_input.get()
        if not user_text: return
        self.chat_display.insert(tk.INSERT, f"Bạn: {user_text}\n")
        self.chat_input.delete(0, tk.END)
        
        # Chạy trong luồng riêng để không bị đơ UI
        threading.Thread(target=self.run_chat_logic, args=(user_text,)).start()

    def run_chat_logic(self, text):
        response = chat_with_ollama(text)
        self.chat_display.insert(tk.INSERT, f"AI: {response}\n\n")
        self.chat_display.see(tk.END)

def launch_report_gui(sid):
    root = tk.Tk()
    MarketSimReportApp(root, sid)
    root.mainloop()