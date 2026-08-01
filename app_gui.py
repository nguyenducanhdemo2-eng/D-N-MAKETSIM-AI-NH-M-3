# ==============================================================================
# APP_GUI.PY - GIAO DIỆN DESKTOP HIỆN ĐẠI (CUSTOMTKINTER - PRO VERSION)
# Đã chuẩn hóa 100% layout grid/pack cho Python 3.11 & 3.14
# ==============================================================================

import customtkinter as ctk
import tkinter as tk
from tkinter import ttk
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import sqlite3
import os
import threading

# Import logic backend từ các file của dự án
from config import DB_PATH, OLLAMA_MODEL
from data_collector import collect_all
from clustering import cluster_customer_psychology
from persona_simulator import generate_personas, simulate_marketing_scenario, chat_with_ollama
from database import save_simulation

# Cấu hình giao diện chung (Dark Mode hiện đại)
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class ModernMarketSimApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        # Cấu hình cửa sổ chính
        self.title("🚀 MarketSim AI — Desktop Dashboard (Pro Version)")
        self.geometry("1100x750")
        self.minsize(900, 600)
        
        # Layout chính: Sidebar bên trái + Vùng nội dung bên phải
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        self._build_sidebar()
        self._build_main_content()
        
    def _build_sidebar(self):
        """Vẽ thanh điều hướng bên trái"""
        self.sidebar_frame = ctk.CTkFrame(self, width=220, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(5, weight=1)
        
        # Logo & Tiêu đề
        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="🚀 MarketSim AI", font=ctk.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))
        
        self.status_label = ctk.CTkLabel(self.sidebar_frame, text=f"🧠 Model: {OLLAMA_MODEL}\n⚡ Backend: Ready", 
                                         text_color="lightgreen", font=ctk.CTkFont(size=12))
        self.status_label.grid(row=1, column=0, padx=20, pady=(0, 20))
        
        # Các nút chuyển Tab
        self.btn_tab1 = ctk.CTkButton(self.sidebar_frame, text="🎯 [1] Mô Phỏng & SWOT", command=lambda: self.select_tab(0))
        self.btn_tab1.grid(row=2, column=0, padx=20, pady=10)
        
        self.btn_tab2 = ctk.CTkButton(self.sidebar_frame, text="📈 [2] Phân Cụm K-Means", command=lambda: self.select_tab(1))
        self.btn_tab2.grid(row=3, column=0, padx=20, pady=10)
        
        self.btn_tab3 = ctk.CTkButton(self.sidebar_frame, text="💬 [3] Trò Chuyện 1-1", command=lambda: self.select_tab(2))
        self.btn_tab3.grid(row=4, column=0, padx=20, pady=10)
        
        # Chuyển đổi Dark/Light mode ở dưới cùng
        self.appearance_mode_optionemenu = ctk.CTkOptionMenu(self.sidebar_frame, values=["Dark", "Light", "System"],
                                                             command=self.change_appearance_mode)
        self.appearance_mode_optionemenu.grid(row=6, column=0, padx=20, pady=20)

    def _build_main_content(self):
        """Vẽ vùng nội dung chính bên phải (Chứa 3 Tab)"""
        self.main_frame = ctk.CTkFrame(self, corner_radius=15)
        self.main_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(0, weight=1)
        
        # Tạo 3 thẻ Frame tương ứng với 3 Tab
        self.tabs = [
            ctk.CTkScrollableFrame(self.main_frame, corner_radius=10), # Tab 1
            ctk.CTkScrollableFrame(self.main_frame, corner_radius=10), # Tab 2
            ctk.CTkFrame(self.main_frame, corner_radius=10)            # Tab 3
        ]
        
        self._init_tab_1(self.tabs[0])
        self._init_tab_2(self.tabs[1])
        self._init_tab_3(self.tabs[2])
        
        # Mặc định hiển thị Tab 1
        self.select_tab(0)

    def select_tab(self, index):
        """Hàm chuyển đổi giữa các Tab"""
        for i, tab in enumerate(self.tabs):
            if i == index:
                tab.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
            else:
                tab.grid_forget()

    # =========================================================================
    # TAB 1: MÔ PHỎNG & SWOT (AI Analyst + Biểu đồ Matplotlib)
    # =========================================================================
    def _init_tab_1(self, frame):
        ctk.CTkLabel(frame, text="⚡ Chạy Mô Phỏng Phản Ứng Khách Hàng Đa Luồng", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=10, anchor="w")
        
        # Form nhập kịch bản
        self.entry_scenario = ctk.CTkTextbox(frame, height=80, font=ctk.CTkFont(size=14))
        self.entry_scenario.insert("0.0", "CHIẾN DỊCH GIẢM GIÁ 30% cho các sản phẩm quần áo mùa hè")
        self.entry_scenario.pack(fill="x", pady=5)
        
        self.btn_run_sim = ctk.CTkButton(frame, text="🚀 BẮT ĐẦU PHÂN TÍCH & MÔ PHỎNG", fg_color="#2ecc71", hover_color="#27ae60",
                                         font=ctk.CTkFont(size=14, weight="bold"), height=40, command=self.start_simulation_thread)
        self.btn_run_sim.pack(fill="x", pady=10)
        
        self.lbl_status = ctk.CTkLabel(frame, text="", text_color="yellow")
        self.lbl_status.pack(pady=5)
        
        # Khu vực hiển thị kết quả SWOT
        self.swot_frame = ctk.CTkFrame(frame)
        self.swot_frame.pack(fill="x", pady=10)
        
        self.lbl_stars = ctk.CTkLabel(self.swot_frame, text="★ ★ ★ ★ ☆ (4/5 Sao)", font=ctk.CTkFont(size=20, weight="bold"), text_color="gold")
        self.lbl_stars.pack(pady=5)
        
        self.txt_summary = ctk.CTkLabel(self.swot_frame, text="Tóm tắt: Hãy chạy mô phỏng để xem kết quả...", wraplength=700)
        self.txt_summary.pack(pady=5)
        
        # Chi tiết Điểm mạnh / Yếu
        self.txt_swot_details = ctk.CTkTextbox(self.swot_frame, height=120)
        self.txt_swot_details.pack(fill="x", padx=10, pady=10)
        
        # Khu vực nhúng Biểu đồ tròn Matplotlib
        self.chart_frame = ctk.CTkFrame(frame)
        self.chart_frame.pack(fill="x", pady=10)
        ctk.CTkLabel(self.chart_frame, text="📊 Biểu Đồ Quyết Định Mua Hàng", font=ctk.CTkFont(weight="bold")).pack(pady=5)
        self.canvas_container = ctk.CTkFrame(self.chart_frame, height=300)
        self.canvas_container.pack(fill="x", padx=10, pady=5)

    def start_simulation_thread(self):
        """Chạy AI trong luồng riêng để không bị đơ giao diện Desktop"""
        self.btn_run_sim.configure(state="disabled", text="⏳ ĐANG CHẠY MÔ PHỎNG AI...")
        self.lbl_status.configure(text="Hệ thống đang cào dữ liệu và gọi luồng AI Qwen... Vui lòng đợi trong giây lát!")
        threading.Thread(target=self._execute_pipeline, daemon=True).start()

    def _execute_pipeline(self):
        scenario = self.entry_scenario.get("0.0", "end").strip()
        try:
            raw_df = collect_all()
            cluster_result = cluster_customer_psychology(raw_df)
            personas = generate_personas(cluster_result, total_personas=30)
            results, analysis, fail_count = simulate_marketing_scenario(personas, scenario)
            save_simulation(scenario, results, analysis)
            
            # Cập nhật UI sau khi chạy xong
            self.after(0, self._update_tab_1_ui)
        except Exception as e:
            self.after(0, lambda: self.lbl_status.configure(text=f"❌ Lỗi: {e}", text_color="red"))
        finally:
            self.after(0, lambda: self.btn_run_sim.configure(state="normal", text="🚀 BẮT ĐẦU PHÂN TÍCH & MÔ PHỎNG"))

    def _update_tab_1_ui(self):
        self.lbl_status.configure(text="✅ Hoàn tất phân tích!", text_color="lightgreen")
        if not os.path.exists(DB_PATH): return
        
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT * FROM scenarios ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        if row:
            sid, _, s, w, summ, stars = row
            self.lbl_stars.configure(text="★"*stars + "☆"*(5-stars) + f" ({stars}/5 Sao)")
            self.txt_summary.configure(text=f"💡 Tóm tắt AI: {summ}")
            
            self.txt_swot_details.delete("0.0", "end")
            self.txt_swot_details.insert("0.0", f"✅ ĐIỂM MẠNH:\n{s}\n\n⚠️ ĐIỂM YẾU:\n{w}")
            
            # Vẽ lại biểu đồ
            df_res = pd.read_sql_query(f"SELECT sentiment FROM simulation_results WHERE scenario_id={sid}", conn)
            if not df_res.empty:
                for widget in self.canvas_container.winfo_children(): widget.destroy()
                
                fig, ax = plt.subplots(figsize=(6, 3), facecolor='#2b2b2b')
                counts = df_res['sentiment'].value_counts()
                ax.pie(counts, labels=counts.index, autopct='%1.1f%%', startangle=90, 
                       colors=['#2ecc71', '#e74c3c', '#f39c12'], textprops={'color':"w"})
                ax.axis('equal')
                
                canvas = FigureCanvasTkAgg(fig, master=self.canvas_container)
                canvas.draw()
                canvas.get_tk_widget().pack(fill="both", expand=True)
        conn.close()

    # =========================================================================
    # TAB 2: PHÂN CỤM K-MEANS & DỮ LIỆU NÓNG
    # =========================================================================
    def _init_tab_2(self, frame):
        ctk.CTkLabel(frame, text="🔍 Dữ Liệu Ngữ Nghĩa & Phân Cụm K-Means", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=10, anchor="w")
        self.btn_load_data = ctk.CTkButton(frame, text="🔄 Tải & Phân Cụm Dữ Liệu Mới Nhất", command=self._load_kmeans_data)
        self.btn_load_data.pack(anchor="w", pady=5)
        
        self.txt_kmeans_result = ctk.CTkTextbox(frame, height=450, font=ctk.CTkFont(size=13))
        self.txt_kmeans_result.pack(fill="both", expand=True, pady=10)
        self.txt_kmeans_result.insert("0.0", "Bấm nút phía trên để cào dữ liệu tin tức nóng và chạy thuật toán phân cụm K-Means...")

    def _load_kmeans_data(self):
        self.btn_load_data.configure(state="disabled", text="⏳ Đang xử lý K-Means...")
        def run():
            df_raw = collect_all()
            clusters = cluster_customer_psychology(df_raw)
            text_out = f"✅ ĐÃ THU THẬP {len(df_raw)} BẢN GHI DỮ LIỆU THÔ\n"
            text_out += "="*50 + "\n\n🧩 KẾT QUẢ PHÂN CỤM TÂM LÝ KHÁCH HÀNG:\n\n"
            for c_id, keywords in clusters["cluster_keywords"].items():
                size = clusters["cluster_sizes"].get(c_id, 0)
                text_out += f"📌 NHÓM TÂM LÝ #{c_id} ({size} người):\n"
                text_out += f"   🔑 Từ khóa sở thích: {', '.join(keywords[:6])}\n\n"
            
            self.after(0, lambda: self.txt_kmeans_result.delete("0.0", "end"))
            self.after(0, lambda: self.txt_kmeans_result.insert("0.0", text_out))
            self.after(0, lambda: self.btn_load_data.configure(state="normal", text="🔄 Tải & Phân Cụm Dữ Liệu Mới Nhất"))
        threading.Thread(target=run, daemon=True).start()

    # =========================================================================
    # TAB 3: TRÒ CHUYỆN 1-1 VỚI KHÁCH HÀNG ẢO
    # =========================================================================
    def _init_tab_3(self, frame):
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)
        
        ctk.CTkLabel(frame, text="💬 Phỏng Vấn Sâu Khách Hàng Ảo (Roleplay Chat)", font=ctk.CTkFont(size=18, weight="bold")).grid(row=0, column=0, pady=10, padx=10, sticky="w")
        
        # Khung hiển thị tin nhắn
        self.chat_history = ctk.CTkTextbox(frame, font=ctk.CTkFont(size=14))
        self.chat_history.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        self.chat_history.insert("0.0", "AI: Xin chào! Tôi là AI đại diện cho tệp khách hàng của bạn. Bạn muốn phỏng vấn tôi về điều gì?\n\n")
        self.chat_history.configure(state="disabled")
        
        # Vùng nhập tin nhắn
        input_frame = ctk.CTkFrame(frame, height=50)
        input_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=10)
        input_frame.grid_columnconfigure(0, weight=1)
        
        self.entry_chat = ctk.CTkEntry(input_frame, placeholder_text="Gõ câu hỏi phỏng vấn ở đây...", font=ctk.CTkFont(size=14), height=40)
        self.entry_chat.grid(row=0, column=0, sticky="ew", padx=(10, 5), pady=10)
        self.entry_chat.bind("<Return>", lambda event: self.send_chat_message())
        
        self.btn_send = ctk.CTkButton(input_frame, text="Gửi", width=80, height=40, command=self.send_chat_message)
        self.btn_send.grid(row=0, column=1, padx=(5, 10), pady=10)

    def send_chat_message(self):
        user_text = self.entry_chat.get().strip()
        if not user_text: return
        self.entry_chat.delete(0, "end")
        
        self._append_chat(f"🧑‍💻 Bạn: {user_text}\n")
        self.btn_send.configure(state="disabled", text="...")
        
        def run_chat():
            resp = chat_with_ollama(user_text)
            self.after(0, lambda: self._append_chat(f"🤖 Khách hàng AI: {resp}\n\n"))
            self.after(0, lambda: self.btn_send.configure(state="normal", text="Gửi"))
        threading.Thread(target=run_chat, daemon=True).start()

    def _append_chat(self, text):
        self.chat_history.configure(state="normal")
        self.chat_history.insert("end", text)
        self.chat_history.see("end")
        self.chat_history.configure(state="disabled")

    def change_appearance_mode(self, new_appearance_mode: str):
        ctk.set_appearance_mode(new_appearance_mode)

if __name__ == "__main__":
    app = ModernMarketSimApp()
    app.mainloop()