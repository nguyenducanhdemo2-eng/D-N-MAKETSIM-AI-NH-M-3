
import json, httpx
import config
class AIProviderError(RuntimeError): pass
async def call_text(prompt, provider=None, temperature=0.3, json_mode=False, max_completion_tokens=None):
    p=(provider or config.AI_PROVIDER).lower()
    if p=='groq':
        if not config.GROQ_API_KEY: raise AIProviderError('Thiếu GROQ_API_KEY trong .env')
        body={'model':config.GROQ_MODEL,'messages':[{'role':'system','content':'Bạn là thành phần AI của MarketSim AI. Chỉ dùng dữ liệu được cung cấp.'},{'role':'user','content':prompt}],'temperature':temperature}
        # GPT-OSS uses part of max_completion_tokens for reasoning.  Keeping the
        # effort low and excluding reasoning leaves enough room for the required
        # JSON document while reducing quota consumption.
        if str(config.GROQ_MODEL).startswith('openai/gpt-oss-'):
            body['reasoning_effort']='low'
            body['include_reasoning']=False
        if json_mode: body['response_format']={'type':'json_object'}
        # Optional and backward-compatible: only callers that explicitly request a cap are affected.
        if max_completion_tokens is not None:
            body['max_completion_tokens']=max(1,int(max_completion_tokens))
        async with httpx.AsyncClient(timeout=config.AI_TIMEOUT_SECONDS) as c:
            r=await c.post(config.GROQ_BASE_URL+'/chat/completions',headers={'Authorization':'Bearer '+config.GROQ_API_KEY,'Content-Type':'application/json'},json=body)
        if r.status_code>=400:
            retry_after=r.headers.get('retry-after')
            suffix=f' retry-after={retry_after}' if retry_after else ''
            raise AIProviderError(f'Groq HTTP {r.status_code}: {r.text[:1000]}{suffix}')
        return r.json()['choices'][0]['message']['content']
    if p=='ollama':
        body={'model':config.OLLAMA_MODEL,'prompt':prompt,'stream':False}
        if json_mode: body['format']='json'
        if max_completion_tokens is not None:
            body['options']={'num_predict':max(1,int(max_completion_tokens))}
        async with httpx.AsyncClient(timeout=config.AI_TIMEOUT_SECONDS) as c:r=await c.post(config.OLLAMA_HOST+'/api/generate',json=body)
        if r.status_code>=400: raise AIProviderError(f'Ollama HTTP {r.status_code}: {r.text[:1000]}')
        return r.json().get('response','')
    raise AIProviderError('Provider không hỗ trợ: '+p)
