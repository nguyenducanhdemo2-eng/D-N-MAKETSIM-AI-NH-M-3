
import httpx
import config
from .ai_bridge import call_text, AIProviderError
async def check_groq():
    if not config.GROQ_API_KEY:return {'ok':False,'provider':'groq','error':'Chưa cấu hình GROQ_API_KEY trong .env'}
    try:
        async with httpx.AsyncClient(timeout=15) as c:r=await c.get(config.GROQ_BASE_URL+'/models',headers={'Authorization':'Bearer '+config.GROQ_API_KEY})
        if r.status_code>=400:return {'ok':False,'provider':'groq','status_code':r.status_code,'error':r.text[:1000]}
        models=[x.get('id') for x in r.json().get('data',[])]
        ok_model=config.GROQ_MODEL in models if models else True
        return {'ok':ok_model,'provider':'groq','model':config.GROQ_MODEL,'models':models[:30],'error':None if ok_model else 'API key hoạt động nhưng model chưa khả dụng.'}
    except Exception as e:return {'ok':False,'provider':'groq','error':str(e)}
async def check_ollama():
    try:
        async with httpx.AsyncClient(timeout=8) as c:r=await c.get(config.OLLAMA_HOST+'/api/tags')
        if r.status_code>=400:return {'ok':False,'provider':'ollama','status_code':r.status_code,'error':r.text[:1000]}
        models=[x.get('name') for x in r.json().get('models',[])]
        return {'ok':config.OLLAMA_MODEL in models,'provider':'ollama','model':config.OLLAMA_MODEL,'models':models,'error':None if config.OLLAMA_MODEL in models else 'Ollama đang chạy nhưng chưa có model đã cấu hình.'}
    except Exception as e:return {'ok':False,'provider':'ollama','error':str(e)}
async def check_all():return {'groq':await check_groq(),'ollama':await check_ollama(),'configured_provider':config.AI_PROVIDER}
async def chat(messages,provider=None,temperature=.4):
    prompt='\n'.join([f"{m.get('role')}: {m.get('content')}" for m in messages])
    return await call_text(prompt,provider,temperature,False)
