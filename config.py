
import os
from pathlib import Path
from dotenv import load_dotenv
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR/'.env')

def _env_bool(name: str, default: bool = False) -> bool:
    value=os.getenv(name)
    if value is None:
        return bool(default)
    return value.strip().lower() in {'1','true','yes','on'}

APP_ENV=os.getenv('APP_ENV','development').strip().lower()
_db_path_env = os.getenv('MARKETSIM_DB_PATH','').strip()
_data_dir_env = os.getenv('MARKETSIM_DATA_DIR','').strip()
if _db_path_env:
    _candidate = Path(_db_path_env).expanduser()
    DB_PATH = str(_candidate if _candidate.is_absolute() else (BASE_DIR / _candidate).resolve())
elif _data_dir_env:
    DB_PATH = str((Path(_data_dir_env).expanduser() / 'marketsim.db').resolve())
else:
    DB_PATH = str(BASE_DIR/'marketsim.db')
TREND_KEYWORDS = [x.strip() for x in os.getenv('TREND_KEYWORDS','thời trang,công nghệ,ẩm thực,du lịch,làm đẹp').split(',') if x.strip()]
NEWS_URLS = [x.strip() for x in os.getenv('NEWS_URLS','https://vnexpress.net/kinh-doanh,https://cafef.vn').split(',') if x.strip()]
TRENDS_TIMEFRAME=os.getenv('TRENDS_TIMEFRAME','now 7-d'); TRENDS_GEO=os.getenv('TRENDS_GEO','VN')
# Pytrends calls an unofficial Google endpoint, so keep requests conservative and
# cache successful responses to avoid repeated-click bursts and HTTP 429 blocks.
TRENDS_CACHE_TTL_SECONDS=max(60,int(os.getenv('TRENDS_CACHE_TTL_SECONDS','900')))
TRENDS_STALE_CACHE_SECONDS=max(TRENDS_CACHE_TTL_SECONDS,int(os.getenv('TRENDS_STALE_CACHE_SECONDS','86400')))
TRENDS_CONNECT_TIMEOUT_SECONDS=max(2,int(os.getenv('TRENDS_CONNECT_TIMEOUT_SECONDS','10')))
TRENDS_READ_TIMEOUT_SECONDS=max(5,int(os.getenv('TRENDS_READ_TIMEOUT_SECONDS','25')))
TRENDS_MAX_RETRIES=max(0,min(3,int(os.getenv('TRENDS_MAX_RETRIES','1'))))
TRENDS_BATCH_DELAY_SECONDS=max(0.0,float(os.getenv('TRENDS_BATCH_DELAY_SECONDS','1.5')))
NUM_CLUSTERS=int(os.getenv('NUM_CLUSTERS','3')); RANDOM_STATE=int(os.getenv('RANDOM_STATE','42'))
OLLAMA_HOST=os.getenv('OLLAMA_HOST','http://127.0.0.1:11434').rstrip('/')
OLLAMA_MODEL=os.getenv('OLLAMA_MODEL','qwen2.5:7b')
NUM_PERSONAS_PER_CLUSTER=int(os.getenv('NUM_PERSONAS_PER_CLUSTER','10'))
MAX_CONCURRENT_REQUESTS=int(os.getenv('MAX_CONCURRENT_REQUESTS','8'))
MAX_SIMULATED_PERSONAS=int(os.getenv('MAX_SIMULATED_PERSONAS','1000'))
# 50 MiB is a safer default for a synchronous pandas/Excel ingestion pipeline.
# The upload reader also enforces this limit while streaming, before the entire
# request body can be retained in application memory.
MAX_UPLOAD_BYTES=int(os.getenv('MAX_UPLOAD_BYTES',str(50*1024**2)))
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
SESSION_MAX_AGE_SECONDS=max(300,int(os.getenv('SESSION_MAX_AGE_SECONDS','604800')))
SESSION_IDLE_TIMEOUT_SECONDS=max(300,min(
    SESSION_MAX_AGE_SECONDS,
    int(os.getenv('SESSION_IDLE_TIMEOUT_SECONDS','43200')),
))
SESSION_COOKIE_SECURE=_env_bool('SESSION_COOKIE_SECURE',APP_ENV=='production')
ADMIN_BOOTSTRAP_CODE=os.getenv('ADMIN_BOOTSTRAP_CODE','').strip()
PASSWORD_MIN_LENGTH=max(8,int(os.getenv('PASSWORD_MIN_LENGTH','8')))
PBKDF2_ITERATIONS=max(310000,int(os.getenv('PBKDF2_ITERATIONS','600000')))
STAGED_SESSION_TTL_SECONDS=max(900,int(os.getenv('STAGED_SESSION_TTL_SECONDS','14400')))
IN_MEMORY_RESULT_TTL_SECONDS=max(300,int(os.getenv('IN_MEMORY_RESULT_TTL_SECONDS','3600')))
MAX_IN_MEMORY_JOBS=max(20,int(os.getenv('MAX_IN_MEMORY_JOBS','200')))
