import httpx
import config
from .ai_bridge import call_text, AIProviderError


async def check_groq():
    if not config.GROQ_API_KEY:
        return {'ok':False,'provider':'groq','error':'Chưa cấu hình GROQ_API_KEY trong .env'}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r=await c.get(config.GROQ_BASE_URL+'/models',headers={'Authorization':'Bearer '+config.GROQ_API_KEY})
        if r.status_code>=400:
            return {'ok':False,'provider':'groq','status_code':r.status_code,'error':r.text[:1000]}
        models=[x.get('id') for x in r.json().get('data',[])]
        ok_model=config.GROQ_MODEL in models if models else True
        return {'ok':ok_model,'provider':'groq','model':config.GROQ_MODEL,'models':models[:30],
                'error':None if ok_model else 'API key hoạt động nhưng model chưa khả dụng.'}
    except Exception as e:
        return {'ok':False,'provider':'groq','error':str(e)}


async def check_ollama():
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r=await c.get(config.OLLAMA_HOST+'/api/tags')
        if r.status_code>=400:
            return {'ok':False,'provider':'ollama','status_code':r.status_code,'error':r.text[:1000]}
        models=[x.get('name') for x in r.json().get('models',[])]
        return {'ok':config.OLLAMA_MODEL in models,'provider':'ollama','model':config.OLLAMA_MODEL,
                'models':models,'error':None if config.OLLAMA_MODEL in models else 'Ollama đang chạy nhưng chưa có model đã cấu hình.'}
    except Exception as e:
        return {'ok':False,'provider':'ollama','error':str(e)}


async def check_all():
    return {'groq':await check_groq(),'ollama':await check_ollama(),'configured_provider':config.AI_PROVIDER}


def _clean_chat_messages(messages):
    """Keep real chat roles instead of flattening the whole conversation into one prompt."""
    cleaned=[]
    for item in messages or []:
        role=str(item.get('role') or '').strip().lower()
        if role not in ('system','user','assistant'):
            continue
        content=str(item.get('content') or '').strip()
        if not content:
            continue
        cleaned.append({'role':role,'content':content})
    return cleaned


async def chat(messages,provider=None,temperature=.4):
    """Structured transport used only by the MarketSim conversation assistant.

    Other AI tasks continue using call_text exactly as before. Preserving each
    message as a real system/user/assistant turn is essential for memory.
    """
    p=(provider or config.AI_PROVIDER).lower()
    cleaned=_clean_chat_messages(messages)
    if not cleaned:
        raise AIProviderError('Hội thoại không có nội dung để gửi.')

    if p=='groq':
        if not config.GROQ_API_KEY:
            raise AIProviderError('Thiếu GROQ_API_KEY trong .env')
        body={
            'model':config.GROQ_MODEL,
            'messages':cleaned,
            'temperature':temperature,
        }
        async with httpx.AsyncClient(timeout=config.AI_TIMEOUT_SECONDS) as c:
            r=await c.post(
                config.GROQ_BASE_URL+'/chat/completions',
                headers={'Authorization':'Bearer '+config.GROQ_API_KEY,'Content-Type':'application/json'},
                json=body,
            )
        if r.status_code>=400:
            retry_after=r.headers.get('retry-after')
            suffix=f' retry-after={retry_after}' if retry_after else ''
            raise AIProviderError(f'Groq HTTP {r.status_code}: {r.text[:1000]}{suffix}')
        return r.json()['choices'][0]['message']['content']

    if p=='ollama':
        # Modern Ollama supports structured /api/chat. If an older server does
        # not, we keep the previous text fallback for compatibility.
        body={'model':config.OLLAMA_MODEL,'messages':cleaned,'stream':False}
        try:
            async with httpx.AsyncClient(timeout=config.AI_TIMEOUT_SECONDS) as c:
                r=await c.post(config.OLLAMA_HOST+'/api/chat',json=body)
            if r.status_code<400:
                data=r.json()
                return str((data.get('message') or {}).get('content') or '')
            if r.status_code not in (404,405):
                raise AIProviderError(f'Ollama HTTP {r.status_code}: {r.text[:1000]}')
        except AIProviderError:
            raise
        except Exception:
            pass

    prompt='\n\n'.join(
        f"[{m['role'].upper()}]\n{m['content']}" for m in cleaned
    )
    return await call_text(prompt,p,temperature,False)
