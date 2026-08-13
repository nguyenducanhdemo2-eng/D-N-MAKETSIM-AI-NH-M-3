
import os
from pathlib import Path
from dotenv import load_dotenv
PROJECT_DIR = Path(__file__).resolve().parent.parent
BASE_DIR = PROJECT_DIR
load_dotenv(PROJECT_DIR/'.env')
_db_path_env = os.getenv('MARKETSIM_DB_PATH','').strip()
_data_dir_env = os.getenv('MARKETSIM_DATA_DIR','').strip()
if _db_path_env:
    _candidate = Path(_db_path_env).expanduser()
    DB_PATH = str(_candidate if _candidate.is_absolute() else (PROJECT_DIR / _candidate).resolve())
elif _data_dir_env:
    DB_PATH = str((Path(_data_dir_env).expanduser() / 'marketsim.db').resolve())
else:
    DB_PATH = str(PROJECT_DIR/'marketsim.db')
TREND_KEYWORDS = [x.strip() for x in os.getenv('TREND_KEYWORDS','thời trang,công nghệ,ẩm thực,du lịch,làm đẹp').split(',') if x.strip()]
NEWS_URLS = [x.strip() for x in os.getenv('NEWS_URLS','https://vnexpress.net/kinh-doanh,https://cafef.vn').split(',') if x.strip()]
TRENDS_TIMEFRAME=os.getenv('TRENDS_TIMEFRAME','now 7-d'); TRENDS_GEO=os.getenv('TRENDS_GEO','VN')
NUM_CLUSTERS=int(os.getenv('NUM_CLUSTERS','3')); RANDOM_STATE=int(os.getenv('RANDOM_STATE','42'))
OLLAMA_HOST=os.getenv('OLLAMA_HOST','http://127.0.0.1:11434').rstrip('/')
OLLAMA_MODEL=os.getenv('OLLAMA_MODEL','qwen2.5:7b')
NUM_PERSONAS_PER_CLUSTER=int(os.getenv('NUM_PERSONAS_PER_CLUSTER','10'))
MAX_CONCURRENT_REQUESTS=int(os.getenv('MAX_CONCURRENT_REQUESTS','8'))
MAX_SIMULATED_PERSONAS=int(os.getenv('MAX_SIMULATED_PERSONAS','1000'))
MAX_UPLOAD_BYTES=int(os.getenv('MAX_UPLOAD_BYTES',str(1024**3)))
REQUEST_TIMEOUT_SEC=int(os.getenv('REQUEST_TIMEOUT_SEC','120'))
AI_PROVIDER=os.getenv('AI_PROVIDER','groq').lower().strip()
GROQ_API_KEY=os.getenv('GROQ_API_KEY','').strip()
# MarketSim AI: dùng 8B cho toàn bộ lời gọi Groq.
# GROQ_FORCE_8B=true (mặc định) sẽ ưu tiên 8B ngay cả khi file .env cũ vẫn còn GROQ_MODEL=llama-3.3-70b-versatile.
# Khi muốn cho phép chọn model khác trong tương lai, đặt GROQ_FORCE_8B=false rồi cấu hình GROQ_MODEL trong .env.
GROQ_FORCE_8B=os.getenv('GROQ_FORCE_8B','true').lower().strip() in {'1','true','yes','on'}
GROQ_MODEL_ENV=os.getenv('GROQ_MODEL','llama-3.1-8b-instant').strip()
GROQ_MODEL='llama-3.1-8b-instant' if GROQ_FORCE_8B else GROQ_MODEL_ENV
GROQ_BASE_URL=os.getenv('GROQ_BASE_URL','https://api.groq.com/openai/v1').rstrip('/')
AI_TIMEOUT_SECONDS=float(os.getenv('AI_TIMEOUT_SECONDS','90'))
MAX_CONCURRENT_AI=int(os.getenv('MAX_CONCURRENT_AI',str(MAX_CONCURRENT_REQUESTS)))
SESSION_COOKIE=os.getenv('SESSION_COOKIE','marketsim_session')
