# ==============================================================================
# PERSONA_SIMULATOR.PY - AI CORE: SINH PERSONA, MÔ PHỎNG & CHAT NHẬP VAI
# Đã bổ sung: health-check Ollama, chat nhập vai 1-1 với từng khách hàng cụ thể,
# đếm số lượt lỗi trong mô phỏng để UI cảnh báo thay vì âm thầm bỏ qua.
# ==============================================================================

import json
import random
import asyncio
import aiohttp
import requests
from tqdm import tqdm
from config import (OLLAMA_HOST, OLLAMA_MODEL, NUM_PERSONAS_PER_CLUSTER,
                    MAX_CONCURRENT_REQUESTS, REQUEST_TIMEOUT_SEC,
                    PERSONALITY_TRAITS)

try:
    from config import MAX_SIMULATED_PERSONAS
except ImportError:
    MAX_SIMULATED_PERSONAS = 100
except AttributeError:
    MAX_SIMULATED_PERSONAS = 100


# ==============================================================================
# HEALTH CHECK - KIỂM TRA KẾT NỐI OLLAMA (chống văng app khi chưa bật Ollama)
# ==============================================================================
def check_ollama_connection(timeout: int = 4):
    """
    Kiểm tra Ollama có đang chạy không và model cấu hình đã sẵn sàng chưa.
    Trả về (is_connected, model_ready, model_list) - KHÔNG BAO GIỜ raise lỗi ra ngoài.
    """
    try:
        resp = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=timeout)
        if resp.status_code != 200:
            return False, False, []
        models = [m.get("name", "") for m in resp.json().get("models", [])]
        model_ready = any(OLLAMA_MODEL.split(":")[0] in m for m in models)
        return True, model_ready, models
    except Exception:
        return False, False, []


# ==============================================================================
# SINH PERSONA ẢO TỪ KẾT QUẢ K-MEANS
# ==============================================================================
def generate_personas(cluster_result: dict, num_per_cluster: int = NUM_PERSONAS_PER_CLUSTER,
                      total_personas: int = None, max_total_personas: int = MAX_SIMULATED_PERSONAS, **kwargs) -> list:
    # Hỗ trợ cả lời gọi cũ và mới: nếu function chưa được reload đúng cách,
    # `total_personas` vẫn được chấp nhận từ web_app.py.
    total_personas = kwargs.get("total_personas", total_personas)
    personas = []
    cluster_keywords = cluster_result["cluster_keywords"]
    n_clusters = len(cluster_keywords)
    if n_clusters == 0:
        return personas

    if total_personas is None:
        total_personas = num_per_cluster * n_clusters
    total_personas = min(max(1, total_personas), max_total_personas)

    base_count = total_personas // n_clusters
    remainder = total_personas % n_clusters
    per_cluster_counts = [
        base_count + (1 if idx < remainder else 0)
        for idx in range(n_clusters)
    ]

    persona_id = 0
    for idx, (cluster_id, keywords) in enumerate(cluster_keywords.items()):
        for _ in range(per_cluster_counts[idx]):
            persona_id += 1
            personas.append({
                "id": persona_id, "cluster_id": cluster_id,
                "name": f"User_{persona_id:03d}",
                "interest_keywords": keywords[:5],
                "personality": random.choice(PERSONALITY_TRAITS),
            })
    return personas


def build_prompt(persona: dict, marketing_scenario: str) -> str:
    keywords = ", ".join(persona.get("interest_keywords", []))
    age = persona.get("real_age", random.randint(22, 45))
    job = persona.get("real_job", "Nhân viên văn phòng")
    pain = persona.get("real_pain", "Sợ sản phẩm không đúng như quảng cáo hoặc giá quá đắt")
    trait = persona.get("personality", "Thận trọng, hay so sánh giá")

    return f"""Bạn hãy nhập vai một khách hàng đang sống trong thời điểm hiện tại với hồ sơ sau:
- Tên nhân vật: {persona['name']} ({age} tuổi, nghề nghiệp: {job})
- Sở thích & Mối quan tâm hiện tại (Từ mạng xã hội & Cá nhân): {keywords}
- Tính cách chi tiêu: {trait}
- Nỗi lo / Nỗi đau lớn nhất khi mua sắm: {pain}

CÓ MỘT CHIẾN DỊCH MARKETING ĐANG DIỄN RA: "{marketing_scenario}"

Nhiệm vụ: Hãy đứng trên góc độ thu nhập, độ tuổi và nỗi đau của bạn, kết hợp với xu hướng bạn đang quan tâm để đánh giá chiến dịch này.
Trả về JSON duy nhất không kèm lời dẫn khác theo đúng định dạng:
{{"persona_name": "{persona['name']} ({job} {age}t)", "score": <1-10>, "sentiment": "<positive|neutral|negative>", "reasoning": "<Lý do tâm lý giải thích sâu sắc vì sao quyết định Mua hay Không mua>"}}"""


async def _call_ollama(prompt: str) -> str:
    """Gọi Ollama bất đồng bộ cho vòng lặp mô phỏng hàng loạt.
    KHÔNG raise lỗi ra ngoài (để 1 persona lỗi không làm sập cả mẻ) -> trả '{}' nếu lỗi,
    caller (_simulate_all_async) tự đếm số lượt thất bại để cảnh báo UI."""
    try:
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SEC)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            payload = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": False, "format": "json"}
            async with session.post(f"{OLLAMA_HOST}/api/generate", json=payload) as resp:
                data = await resp.json()
                return data.get("response", "{}")
    except Exception:
        return "{}"


async def analyze_scenario_with_ai(results: list, scenario: str) -> dict:
    """Phiên bản phân tích SWOT chuẩn, tiếng Việt, không trùng lặp."""
    sample_reviews = "\n".join([f"- {r.get('persona_name')}: {r.get('reasoning')}" for r in results[:20]])

    prompt = f"""
    Bạn là Trợ lý phân tích Marketing của MarketSim. Hãy phân tích chiến dịch dựa trên phản hồi thực tế của khách hàng.

    Kịch bản chiến dịch: "{scenario}"
    Dữ liệu khách hàng thực tế (Mẫu):
    {sample_reviews if sample_reviews else "(Không có phản hồi nào - có thể do lỗi kết nối AI khi mô phỏng)"}

    YÊU CẦU BẮT BUỘC:
    1. Trả lời bằng tiếng Việt chuyên nghiệp, tuyệt đối không dùng tiếng Trung.
    2. Không viết liệt kê lý thuyết. Phải phân tích dựa trên dữ liệu khách hàng bên trên.
    3. Định dạng JSON duy nhất.

    Trả về cấu trúc JSON:
    {{
        "strengths": ["Điểm mạnh 1", "Điểm mạnh 2"],
        "weaknesses": ["Điểm yếu 1", "Điểm yếu 2"],
        "star_rating": 4,
        "summary": "Phân tích sâu sắc về sự phù hợp của chiến dịch."
    }}
    """

    raw = await _call_ollama(prompt)
    try:
        clean_raw = raw.strip()
        if not clean_raw.startswith("{"):
            clean_raw = clean_raw[clean_raw.find("{"): clean_raw.rfind("}") + 1]
        return json.loads(clean_raw)
    except Exception:
        return {
            "strengths": ["Dữ liệu phản hồi chưa đủ hoặc AI đang gặp sự cố kết nối"],
            "weaknesses": ["Hệ thống cần thêm thời gian / kiểm tra lại Ollama"],
            "star_rating": 3,
            "summary": "Không thể phân tích SWOT tự động lúc này. Vui lòng kiểm tra Ollama và thử lại."
        }


async def _simulate_all_async(personas: list, scenario: str, progress_callback=None):
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    fail_count = 0
    completed = 0
    total = len(personas)

    async def task(p):
        nonlocal fail_count
        async with semaphore:
            resp = await _call_ollama(build_prompt(p, scenario))
            try:
                data = json.loads(resp)
                data["persona_id"] = p["id"]
                data["cluster_id"] = p["cluster_id"]
                return data
            except Exception:
                fail_count += 1
                return None

    tasks = [task(p) for p in personas]
    results = []
    iterator = asyncio.as_completed(tasks)
    if progress_callback is None:
        iterator = tqdm(iterator, total=total, desc="🚀 Train AI Khách hàng")

    for f in iterator:
        res = await f
        completed += 1
        if progress_callback:
            progress_callback(completed, total)
        results.append(res)
    return [r for r in results if r is not None], fail_count


def simulate_marketing_scenario(personas: list, scenario: str, progress_callback=None, **kwargs):
    """
    Trả về (results, analysis, fail_count).
    fail_count = số persona bị lỗi kết nối/không parse được JSON trong lúc mô phỏng,
    dùng để UI cảnh báo thay vì âm thầm mất dữ liệu.
    """
    results, fail_count = asyncio.run(_simulate_all_async(personas, scenario, progress_callback=progress_callback))
    print("🧠 Đang phân tích SWOT...")
    analysis = asyncio.run(analyze_scenario_with_ai(results, scenario))
    return results, analysis, fail_count


# ==============================================================================
# CHAT CHUNG VỚI TRỢ LÝ AI (chế độ mặc định, không nhập vai persona nào cụ thể)
# ==============================================================================
def chat_with_ollama(user_input: str) -> str:
    """Hàm gọi AI trực tiếp cho khung chat chung. Raise lỗi có thông điệp rõ ràng
    thay vì trả về chuỗi lỗi chung chung, để UI phân biệt được và hiển thị đẹp."""
    try:
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": f"Bạn là trợ lý phân tích marketing của MarketSim. Hãy trả lời ngắn gọn: {user_input}",
            "stream": False
        }
        response = requests.post(f"{OLLAMA_HOST}/api/generate", json=payload, timeout=REQUEST_TIMEOUT_SEC)
        response.raise_for_status()
        return response.json().get("response", "AI không trả về nội dung.")
    except requests.exceptions.ConnectionError:
        raise ConnectionError(f"Không kết nối được tới Ollama tại {OLLAMA_HOST}. Hãy chắc chắn đã chạy lệnh 'ollama serve'.")
    except requests.exceptions.Timeout:
        raise TimeoutError("Ollama phản hồi quá lâu (timeout). Model có thể đang tải hoặc máy đang quá tải.")
    except Exception as e:
        raise RuntimeError(f"Lỗi hệ thống khi gọi AI: {e}")


# ==============================================================================
# CHAT NHẬP VAI 1-1 VỚI ĐÚNG 1 KHÁCH HÀNG ẢO CỤ THỂ (Roleplay Chat)
# ==============================================================================
def build_persona_system_prompt(persona_ctx: dict) -> str:
    name = persona_ctx.get("name", "Khách hàng ẩn danh")
    scenario = persona_ctx.get("scenario", "(không rõ chiến dịch)")
    sentiment = persona_ctx.get("sentiment", "neutral")
    reasoning = persona_ctx.get("reasoning", "chưa có lý do cụ thể")
    score = persona_ctx.get("score", "?")

    sentiment_vn = {
        "positive": "khá HÀI LÒNG và có xu hướng MUA sản phẩm",
        "negative": "KHÔNG HÀI LÒNG và có xu hướng TỪ CHỐI, không mua",
        "neutral": "còn LƯỠNG LỰ, chưa quyết định hẳn",
    }.get(str(sentiment).lower(), "còn lưỡng lự")

    return f"""Bạn PHẢI nhập vai đúng nhân vật sau trong SUỐT cuộc trò chuyện. Tuyệt đối không được nói bạn là AI hay trợ lý ảo, không thoát vai.
- Bạn là khách hàng tên: {name}
- Bạn vừa được xem chiến dịch marketing sau: "{scenario}"
- Thái độ của bạn: bạn {sentiment_vn} (mức độ hài lòng tự chấm: {score}/10)
- Lý do tâm lý sâu xa đằng sau quyết định của bạn: {reasoning}

Hãy trả lời các câu hỏi phỏng vấn của nhân viên tư vấn marketing một cách tự nhiên, đúng cảm xúc và lý do đã nêu ở trên.
Trả lời ngắn gọn như đời thường (2-4 câu), không dùng markdown, không liệt kê gạch đầu dòng.
"""


def chat_with_persona(persona_ctx: dict, chat_history: list, user_input: str) -> str:
    """
    Chat nhập vai với 1 khách hàng ảo cụ thể đã có trong kết quả mô phỏng.
    chat_history: list [{"role": "user"/"assistant", "content": "..."}] (ngữ cảnh hội thoại cũ)
    Raise lỗi rõ ràng (ConnectionError/TimeoutError/RuntimeError) để UI hiển thị, không âm thầm trả rác.
    """
    messages = [{"role": "system", "content": build_persona_system_prompt(persona_ctx)}]
    messages.extend(chat_history[-10:])  # giữ 10 lượt gần nhất để prompt không phình quá to
    messages.append({"role": "user", "content": user_input})

    payload = {"model": OLLAMA_MODEL, "messages": messages, "stream": False}
    try:
        response = requests.post(f"{OLLAMA_HOST}/api/chat", json=payload, timeout=REQUEST_TIMEOUT_SEC)
        response.raise_for_status()
        data = response.json()
        content = data.get("message", {}).get("content", "").strip()
        return content or "(Khách hàng im lặng không phản hồi...)"
    except requests.exceptions.ConnectionError:
        raise ConnectionError(f"Không kết nối được tới Ollama tại {OLLAMA_HOST}. Hãy bật Ollama (ollama serve) rồi thử lại.")
    except requests.exceptions.Timeout:
        raise TimeoutError("Khách hàng ảo phản hồi quá lâu (timeout). Thử lại sau vài giây.")
    except Exception as e:
        raise RuntimeError(f"Lỗi hệ thống khi chat với persona: {e}")
