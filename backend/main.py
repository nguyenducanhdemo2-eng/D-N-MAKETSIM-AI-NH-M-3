
import asyncio, json, uuid, math, re, time
from pathlib import Path
import pandas as pd
import numpy as np
from fastapi import FastAPI, UploadFile, File, Request, Response, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import config
from database import *
from schema_mapper import _rule_based_match, _normalize_column_name, CANONICAL_SCHEMA, REQUIRED_FIELDS, apply_mapping, missing_required_fields
from data_preprocessor import AdvancedETLPipeline
from customer_intelligence import build_customer_intelligence, summarize_customer_intelligence
from hybrid_segmentation import hybrid_segment_customers
from persona_engine import build_data_driven_personas
from digital_twin import generate_synthetic_twins, twins_to_dataframe
from advanced_simulation import simulate_twins, paired_compare, optimize_marketing
from .auth_db import init_auth, create_session, get_user, delete_session, set_session_mode
from .admin_db import (init_admin_schema, admin_count, company_count, get_account, find_admin_by_join_code, attach_employee,
    employee_visible_to_admin, repair_company_memberships,
    create_company_admin, require_admin_account, require_employee_account,
    get_admin_profile, regenerate_join_code, set_user_ai_provider,
    admin_overview, admin_staff, admin_employee_detail, admin_activity, admin_team_health, set_employee_active,
    normalize_join_code, record_activity, activity_name, get_company_schema_mapping, save_company_schema_mappings)
from .ai_provider import check_all, check_groq, check_ollama, chat
from .ai_bridge import call_text
from staged_data_workflow import inspect_dataframe, apply_learned_fields, build_audit
from data_quality_engine import detect_possible_duplicates, sanitize_canonical, derive_real_features, data_drift
from .security import enforce_rate_limit, rate_limiter, read_upload_limited

BASE_DIR=Path(__file__).resolve().parent.parent; FRONTEND=BASE_DIR/'frontend'
app=FastAPI(title='MarketSim AI',version='Final Cloud')
app.mount('/static',StaticFiles(directory=FRONTEND),name='static')
jobs={}
persona_jobs={}
latest_state={}
staged_sessions={}
staged_learning_jobs={}
_ephemeral_created={}


# Simulation transport optimization only.
# These helpers do NOT change Digital Twin generation, segmentation, quantitative simulation,
# AI Learning, or fallback scoring. They only reduce request size and handle provider throttling.
_GROQ_SIM_LOCK = asyncio.Lock()
_GROQ_COOLDOWN_UNTIL = 0.0
_GROQ_SIM_MAX_RETRIES = 2
_GROQ_SIM_MAX_WAIT_SECONDS = 600.0
_GROQ_SIM_MAX_COMPLETION_TOKENS = 180

def _compact_twin_for_ai(twin: dict) -> dict:
    """Return only simulation-relevant synthetic fields; never raw customer identity/provenance."""
    allowed = (
        'twin_id','segment_id','age','gender','job','location','product_category','channel','device',
        'acquisition_source','rfm_segment','total_spending','order_count','average_order_value',
        'discount_usage','recency_days','frequency','monetary','rfm_score','price_sensitivity',
        'interest_keywords','pain_point','personality','review_text','proxy_scores','confidence',
        'source_data_reliability'
    )
    out={}
    for key in allowed:
        value=twin.get(key)
        if value is None or value=='' or value==[] or value=={}:
            continue
        out[key]=value
    return out

def _retry_seconds_from_error(error_text: str) -> float | None:
    """Parse Groq's retry guidance such as 'try again in 4m10.5s'."""
    text=str(error_text or '')
    m=re.search(r'(?:try\s+again\s+in|retry(?:[- ]after)?[=: ]+)\s*(?:(\d+(?:\.\d+)?)m)?\s*(?:(\d+(?:\.\d+)?)s)?', text, re.I)
    if m and (m.group(1) or m.group(2)):
        return float(m.group(1) or 0)*60.0 + float(m.group(2) or 0)
    # Some responses contain only a plain Retry-After style number.
    m=re.search(r'retry[- ]after[=: ]+(\d+(?:\.\d+)?)', text, re.I)
    return float(m.group(1)) if m else None

async def _wait_for_groq_cooldown():
    global _GROQ_COOLDOWN_UNTIL
    remaining=_GROQ_COOLDOWN_UNTIL-time.monotonic()
    if remaining>0:
        await asyncio.sleep(min(remaining,_GROQ_SIM_MAX_WAIT_SECONDS))

async def _simulation_ai_call(prompt: str, provider: str):
    """Call the existing AI bridge with conservative Groq throttling/retry.

    Non-Groq providers keep the existing behavior. Groq calls are serialized across simulation jobs
    so many employees do not burst the same organization quota at once.
    """
    global _GROQ_COOLDOWN_UNTIL
    if provider!='groq':
        return await call_text(prompt,provider,.5,True,max_completion_tokens=_GROQ_SIM_MAX_COMPLETION_TOKENS)
    async with _GROQ_SIM_LOCK:
        for attempt in range(_GROQ_SIM_MAX_RETRIES+1):
            await _wait_for_groq_cooldown()
            try:
                return await call_text(prompt,provider,.5,True,max_completion_tokens=_GROQ_SIM_MAX_COMPLETION_TOKENS)
            except Exception as e:
                msg=f'{type(e).__name__}: {e}'
                is_429='HTTP 429' in msg or 'rate_limit_exceeded' in msg.lower() or 'too many requests' in msg.lower()
                if not is_429 or attempt>=_GROQ_SIM_MAX_RETRIES:
                    raise
                retry=_retry_seconds_from_error(msg)
                # Respect provider guidance when present; otherwise use a small exponential delay.
                wait=min(_GROQ_SIM_MAX_WAIT_SECONDS, max(2.0, (retry if retry is not None else 2.0*(2**attempt))) + 1.0)
                _GROQ_COOLDOWN_UNTIL=max(_GROQ_COOLDOWN_UNTIL,time.monotonic()+wait)
                print(f'[GROQ RATE LIMIT] waiting={wait:.1f}s attempt={attempt+1}/{_GROQ_SIM_MAX_RETRIES} before retry',flush=True)
        raise RuntimeError('Groq retry loop ended unexpectedly.')

class Auth(BaseModel): email:str; password:str
class EmployeeRegister(BaseModel):
    email:str; password:str; leader_code:str; display_name:str=''
class AdminRegister(BaseModel):
    email:str; password:str; display_name:str=''; organization_name:str=''
class CompanyCodeBody(BaseModel): code:str
class ActiveBody(BaseModel): active:bool
class Provider(BaseModel): provider:str
class SessionModeBody(BaseModel): mode:str
class MappingBody(BaseModel): mappings:list[dict]
class Sim(BaseModel): campaign:str; count:int=Field(default=100,ge=1,le=1000); provider:str|None=None; name:str='Chiến dịch mô phỏng'
class Chat(BaseModel): message:str; provider:str|None=None
class TwinBody(BaseModel): count_per_segment:int=Field(default=25,ge=1,le=500)
class ABBody(BaseModel): campaigns:list[str]
class OptBody(BaseModel): budget:float=0; discount_options:list[float]|None=None; channel_options:list[str]|None=None
class FeedbackBody(BaseModel): experiment_id:int; predicted_conversion:float; actual_conversion:float; predicted_revenue:float|None=None; actual_revenue:float|None=None; notes:str=''

@app.on_event('startup')
def startup():
    # Two-pass init keeps legacy SQLite migrations safe: admin schema adds users.company_id,
    # then init_db backfills tenant ownership onto business records.
    init_db(); init_admin_schema(); init_auth(); init_db(); mark_interrupted_background_jobs()

def current_account(req):
    u=get_user(req.cookies.get(config.SESSION_COOKIE))
    if not u: raise HTTPException(401,'Bạn chưa đăng nhập.')
    account=get_account(u['id'])
    if not account or not int(account.get('is_active') or 0):
        raise HTTPException(403,'Tài khoản đã bị vô hiệu hóa.')
    account['active_mode']=u.get('active_mode') or ('admin' if account.get('role')=='admin' else 'employee')
    return account

def current_user(req):
    """Employee workspace guard, including an ADMIN explicitly in employee mode."""
    account=current_account(req)
    if account.get('active_mode')!='employee':
        raise HTTPException(403,'Hãy chuyển sang chế độ nhân viên để sử dụng khu vực này.')
    if account.get('role')=='employee':
        try:
            require_employee_account(account['id'])
        except PermissionError as e:
            raise HTTPException(403,str(e))
    elif account.get('role')!='admin' or account.get('company_id') is None:
        raise HTTPException(403,'Tài khoản không có quyền sử dụng khu vực nhân viên.')
    return account

def current_admin(req):
    u=current_account(req)
    if u.get('active_mode')!='admin':
        raise HTTPException(403,'Hãy chuyển về chế độ ADMIN để sử dụng trang quản trị.')
    try:
        require_admin_account(u['id'])
    except PermissionError as e:
        raise HTTPException(403,str(e))
    return u

def _provider_for(account: dict) -> str:
    provider=str(account.get('ai_provider') or config.AI_PROVIDER).lower().strip()
    return provider if provider in ('groq','ollama') else 'groq'

def _user_rate_limit(account: dict, bucket: str, limit: int, window_seconds: int):
    rate_limiter.check(f"{bucket}:user:{int(account['id'])}",limit,window_seconds)


def _job_register(store: dict, job_id: str, user: dict, job_type: str, initial: dict, payload: dict | None = None):
    """Register an in-memory job plus durable ownership/status metadata."""
    _prune_job_store(store)
    item=dict(initial or {})
    item['user_id']=int(user['id'])
    item['company_id']=user.get('company_id')
    store[job_id]=item
    _ephemeral_created[job_id]=time.monotonic()
    create_background_job(job_id,int(user['id']),user.get('company_id'),job_type,payload or {})
    return item

def _prune_job_store(store: dict):
    now=time.monotonic()
    removable=[]
    for job_id,item in store.items():
        age=now-_ephemeral_created.get(job_id,now)
        if item.get('status') not in ('running','queued') and age>config.IN_MEMORY_RESULT_TTL_SECONDS:
            removable.append(job_id)
    if len(store)-len(removable)>config.MAX_IN_MEMORY_JOBS:
        remaining=[jid for jid in store if jid not in removable and store[jid].get('status') not in ('running','queued')]
        remaining.sort(key=lambda jid:_ephemeral_created.get(jid,0))
        removable.extend(remaining[:len(store)-len(removable)-config.MAX_IN_MEMORY_JOBS])
    for job_id in set(removable):
        store.pop(job_id,None); _ephemeral_created.pop(job_id,None)

def _prune_staged_sessions():
    now=time.monotonic()
    expired=[sid for sid,item in staged_sessions.items() if now-float(item.get('_created_monotonic',now))>config.STAGED_SESSION_TTL_SECONDS]
    for sid in expired:
        staged_sessions.pop(sid,None)

def _job_owned(store: dict, job_id: str, user: dict):
    """Never reveal another account's job by guessing UUID/path."""
    item=store.get(job_id)
    if item is not None:
        if int(item.get('user_id') or -1) != int(user['id']):
            raise HTTPException(404,'Không tìm thấy tiến trình.')
        try:
            update_background_job(job_id,user['id'],status=item.get('status'),progress=item.get('progress'),error=item.get('error'))
        except Exception:
            pass
        return item
    persisted=get_background_job(job_id,user['id'])
    if not persisted:
        raise HTTPException(404,'Không tìm thấy tiến trình.')
    # After a server restart the execution task no longer exists, but the owner can
    # still see the persisted state/interruption reason.
    return persisted

@app.middleware('http')
async def audit_employee_actions(req:Request, call_next):
    response=await call_next(req)
    try:
        if req.method.upper() in ('POST','PUT','PATCH','DELETE') and req.url.path.startswith('/api/') and not req.url.path.startswith('/api/admin/') and req.url.path not in ('/api/auth/login','/api/auth/logout','/api/auth/register','/api/auth/register-admin','/api/auth/switch-mode'):
            u=get_user(req.cookies.get(config.SESSION_COOKIE))
            if u and response.status_code < 400:
                record_activity(u['id'],activity_name(req.url.path,req.method),req.url.path,req.method,response.status_code,'')
    except Exception:
        pass
    return response

def json_safe(v):
    if isinstance(v,dict): return {k:json_safe(x) for k,x in v.items()}
    if isinstance(v,list): return [json_safe(x) for x in v]
    if hasattr(v,'item'):
        try:return json_safe(v.item())
        except Exception:pass
    if isinstance(v,float) and not math.isfinite(v):return None
    return v

def records_df(user_id=None):
    rows=load_canonical_customers(limit=100000, user_id=user_id)
    return pd.DataFrame(rows)

def _restore_employee_state(account: dict) -> dict | None:
    """Rebuild the latest confirmed workspace from SQLite after a restart."""
    cached=latest_state.get(account['id'])
    if cached:
        return cached
    history=[x for x in get_user_dataset_history(account['id'],50) if x.get('learning_confirmed')]
    upload_id=history[0]['id'] if history else None
    if not upload_id:
        return None
    rows=load_canonical_customers(
        upload_id=upload_id,limit=100000,user_id=account['id'],confirmed_only=True,
    )
    if not rows:
        return None
    df=build_customer_intelligence(rows)
    segment_rows=get_customer_segments(upload_id=upload_id,limit=100000,user_id=account['id'])
    profiles={}
    segment_by_customer={}
    for row in segment_rows:
        segment_by_customer[str(row.get('customer_id'))]=row.get('segment_id')
        sid=int(row.get('segment_id') or 0)
        if sid not in profiles:
            try:profiles[sid]=json.loads(row.get('profile_json') or '{}')
            except Exception:profiles[sid]={}
    if not df.empty and 'customer_id' in df.columns and segment_by_customer:
        df['segment_id']=df['customer_id'].astype(str).map(segment_by_customer)
    persisted_twins=get_synthetic_customer_twins(
        upload_id=upload_id,limit=5000,user_id=account['id'],
    )
    twins=[r.get('twin') or r for r in persisted_twins]
    audit=get_learning_audit_by_upload(upload_id,user_id=account['id']) or {}
    run=get_segmentation_run(upload_id,user_id=account['id']) or {}
    state={
        'upload_id':upload_id,'df':df,'personas':[],'profiles':profiles,
        'segmentation_quality':run.get('metrics') or {},'twins':twins,
        'audit':audit,'audit_id':audit.get('id'),'learning_confirmed':bool(audit.get('confirmed')),
    }
    latest_state[account['id']]=state
    return state

async def map_columns_two_layer(columns, raw_records, provider, company_id=None):
    result=[]; used=set()
    unresolved=[]
    for col in columns:
        memory=get_company_schema_mapping(company_id,col) if company_id else None
        if memory and memory.get('canonical_field') in CANONICAL_SCHEMA and memory.get('canonical_field') not in used:
            field=memory['canonical_field']; used.add(field)
            result.append({'source_column':col,'canonical_field':field,'confidence':1.0,'confidence_display':'100%','reasoning':f"Doanh nghiệp đã xác nhận mapping này {int(memory.get('confirmation_count') or 1)} lần trước đó.",'source':'company_memory'})
            continue
        # Known PII/display columns and externally supplied proxy scores are not
        # needed for MarketSim clustering. Skipping them avoids unnecessary LLM
        # calls and prevents a proxy column from being mistaken for raw evidence.
        norm=_normalize_column_name(col)
        if norm in {'full_name','name','customer_name','phone','phone_number','mobile','email','email_address'} or norm.endswith('_proxy'):
            result.append({'source_column':col,'canonical_field':'unmapped','confidence':1.0,'confidence_display':'100%','reasoning':'Cột nhận diện/điểm proxy được chủ động bỏ qua để không đưa PII hoặc chỉ số tính sẵn vào mô hình phân nhóm.','source':'safe_ignore'})
            continue
        field,conf,reason=_rule_based_match(col)
        if field and field not in used:
            result.append({'source_column':col,'canonical_field':field,'confidence':conf,'confidence_display':f'{int(conf*100)}%','reasoning':reason,'source':'rule'}); used.add(field)
        else: unresolved.append(col)
    for col in unresolved:
        samples=[]
        for r in raw_records[:5]:
            if r.get(col) not in (None,''): samples.append(str(r.get(col))[:120])
        prompt=f"""Chuẩn hóa cột dữ liệu khách hàng. Tên cột: {col}. Mẫu: {samples}. Các trường chuẩn: {list(CANONICAL_SCHEMA.keys())}. Chọn đúng một trường hoặc unmapped. Trả JSON duy nhất: {{"canonical_field":"...","confidence":0.0,"reasoning":"..."}}"""
        try:
            raw=await call_text(prompt,provider,0.1,True); a,b=raw.find('{'),raw.rfind('}'); data=json.loads(raw[a:b+1]); field=data.get('canonical_field','unmapped')
            if field not in CANONICAL_SCHEMA or field in used: field='unmapped'
            conf=max(0,min(1,float(data.get('confidence',0.5))))
            if field!='unmapped': used.add(field)
            result.append({'source_column':col,'canonical_field':field,'confidence':round(conf,2),'confidence_display':f'{int(conf*100)}%','reasoning':str(data.get('reasoning','')),'source':'ai'})
        except Exception as e:
            result.append({'source_column':col,'canonical_field':'unmapped','confidence':0,'confidence_display':'0%','reasoning':f'AI mapping không khả dụng: {e}','source':'ai_failed'})
    return result

@app.get('/')
def root(req:Request):
    try:
        account=current_account(req)
        if account.get('role')=='admin' and account.get('active_mode')=='admin':
            current_admin(req); return RedirectResponse('/admin',status_code=303)
        current_user(req); return RedirectResponse('/app',status_code=303)
    except HTTPException:
        return FileResponse(FRONTEND/'pages/login.html')
@app.get('/app')
def app_page(req:Request):
    try:
        current_user(req)
    except HTTPException:
        return RedirectResponse('/',status_code=303)
    return FileResponse(FRONTEND/'index.html')
@app.get('/admin')
def admin_page(req:Request):
    try:
        current_admin(req)
    except HTTPException:
        try:
            current_user(req); return RedirectResponse('/app',status_code=303)
        except HTTPException:
            return RedirectResponse('/',status_code=303)
    return FileResponse(FRONTEND/'admin.html')

@app.get('/api/auth/admin-status')
def auth_admin_status():
    return {
        'admin_exists': admin_count() > 0,
        'admin_count': admin_count(),
        'company_count': company_count(),
        # New businesses may register directly. Keep these response fields so
        # older cached login pages remain compatible during deployment.
        'admin_registration_open': True,
        'bootstrap_protected': False,
    }

@app.post('/api/auth/validate-company-code')
def validate_company_code(req:Request,b:CompanyCodeBody):
    enforce_rate_limit(req,'company-code',30,300)
    code=normalize_join_code(b.code)
    admin=find_admin_by_join_code(code)
    if not admin:
        return {'valid':False,'normalized_code':code,'message':'Mã tham gia doanh nghiệp không hợp lệ hoặc đã hết hiệu lực.'}
    return {
        'valid':True,
        'normalized_code':admin.get('join_code') or code,
        'company_id':admin.get('company_id'),
        'organization':admin.get('organization_name'),
        'admin_name':admin.get('display_name') or 'ADMIN',
    }

@app.post('/api/auth/register')
def register(req:Request,b:EmployeeRegister):
    enforce_rate_limit(req,'employee-register',8,3600)
    code=normalize_join_code(b.leader_code)
    admin=find_admin_by_join_code(code)
    if not admin:
        raise HTTPException(400,'Mã tham gia doanh nghiệp không đúng hoặc đã hết hiệu lực. Hãy sao chép lại mã mới nhất từ ADMIN.')
    uid=None
    membership=None
    before_ids={int(x['id']) for x in admin_staff(admin['id'])}
    try:
        uid=create_user(b.email,b.password)
        membership=attach_employee(uid,admin['id'],b.display_name)
        # Verify the new account AND prove that no previously visible employee
        # disappeared as a side effect of this registration.
        if not employee_visible_to_admin(admin['id'], uid):
            raise ValueError('Tài khoản chưa được thêm vào danh sách nhân viên của doanh nghiệp. Hệ thống đã hủy thao tác; vui lòng thử lại.')
        current_staff=admin_staff(admin['id'])
        current_ids={int(x['id']) for x in current_staff}
        if int(uid) not in current_ids or not before_ids.issubset(current_ids):
            raise ValueError('Danh sách nhân viên thay đổi bất thường sau khi đăng ký. Hệ thống đã hủy tài khoản mới để bảo toàn nhân viên cũ.')
        record_activity(uid,'Tạo tài khoản nhân viên','/api/auth/register','POST',200,f"Gia nhập {admin.get('organization_name','doanh nghiệp')} · company_id={membership.get('company_id')}")
    except Exception as e:
        # Remove only the account created by THIS request. Never delete or update
        # any pre-existing employee when a new employee registration fails.
        if uid:
            try:
                import sqlite3
                with sqlite3.connect(config.DB_PATH) as c:
                    c.execute("DELETE FROM company_memberships WHERE user_id=?",(int(uid),))
                    c.execute("DELETE FROM users WHERE id=? AND email=? AND role='employee'",(int(uid),(b.email or '').strip().lower()))
                    c.commit()
            except Exception:
                pass
        raise HTTPException(400,str(e))
    return {
        'ok':True,
        'user_id':uid,
        'company_id':membership.get('company_id'),
        'organization':membership.get('organization_name') or admin.get('organization_name'),
        'join_code':admin.get('join_code'),
        'membership_verified':True,
        'staff_count':len(current_staff),
        'message':'Tài khoản đã được thêm vào danh sách nhân viên của doanh nghiệp mà không thay thế nhân viên cũ.',
    }

@app.post('/api/auth/register-admin')
def register_admin(req:Request,b:AdminRegister):
    enforce_rate_limit(req,'admin-register',5,3600)
    # Multi-company: every business may create its own independent ADMIN account.
    if len(b.password)<config.PASSWORD_MIN_LENGTH:
        raise HTTPException(400,f'Mật khẩu phải có ít nhất {config.PASSWORD_MIN_LENGTH} ký tự.')
    if not (b.organization_name or '').strip():
        raise HTTPException(400,'Vui lòng nhập tên doanh nghiệp.')
    uid=None
    try:
        uid=create_user(b.email,b.password)
        if not uid:
            raise ValueError('Email đã tồn tại.')
        company=create_company_admin(uid,b.display_name,b.organization_name)
        record_activity(uid,'Tạo doanh nghiệp & tài khoản ADMIN','/api/auth/register-admin','POST',200,company.get('organization_name',''))
    except Exception as e:
        if uid:
            try:
                import sqlite3
                with sqlite3.connect(config.DB_PATH) as c:
                    c.execute('DELETE FROM users WHERE id=? AND company_id IS NULL',(uid,)); c.commit()
            except Exception:
                pass
        raise HTTPException(400,str(e))
    return {'ok':True,'user_id':uid,**company}

@app.post('/api/auth/login')
def login(req:Request,b:Auth,res:Response):
    enforce_rate_limit(req,'login',10,300)
    if not verify_user(b.email,b.password): raise HTTPException(401,'Email hoặc mật khẩu không đúng.')
    import sqlite3
    with sqlite3.connect(config.DB_PATH) as c: uid=c.execute('SELECT id FROM users WHERE email=?',(b.email.lower().strip(),)).fetchone()[0]
    account=get_account(uid)
    if not account or not int(account.get('is_active') or 0):
        raise HTTPException(403,'Tài khoản đã bị vô hiệu hóa. Hãy liên hệ ADMIN.')
    token=create_session(uid)
    account['active_mode']='admin' if account.get('role')=='admin' else 'employee'
    res.set_cookie(
        config.SESSION_COOKIE,
        token,
        httponly=True,
        secure=config.SESSION_COOKIE_SECURE,
        samesite='lax',
        max_age=config.SESSION_MAX_AGE_SECONDS,
        path='/',
    )
    record_activity(uid,'Đăng nhập hệ thống','/api/auth/login','POST',200,'')
    return {'ok':True,'user':account,'redirect':'/admin' if account.get('role')=='admin' else '/app'}
@app.post('/api/auth/logout')
def logout(req:Request,res:Response):
    u=get_user(req.cookies.get(config.SESSION_COOKIE))
    if u: record_activity(u['id'],'Đăng xuất hệ thống','/api/auth/logout','POST',200,'')
    delete_session(req.cookies.get(config.SESSION_COOKIE))
    res.delete_cookie(config.SESSION_COOKIE,path='/',secure=config.SESSION_COOKIE_SECURE,samesite='lax')
    return {'ok':True}
@app.get('/api/auth/me')
def me(req:Request):return current_account(req)

@app.post('/api/auth/switch-mode')
def switch_mode(req:Request,b:SessionModeBody):
    enforce_rate_limit(req,'switch-mode',30,60)
    account=current_account(req)
    mode=str(b.mode or '').strip().lower()
    if account.get('role')!='admin' and mode!='employee':
        raise HTTPException(403,'Nhân viên không thể chuyển sang chế độ ADMIN.')
    try:
        changed=set_session_mode(req.cookies.get(config.SESSION_COOKIE),account['id'],mode)
    except ValueError as e:
        raise HTTPException(400,str(e))
    except PermissionError as e:
        raise HTTPException(403,str(e))
    if not changed:
        raise HTTPException(401,'Phiên đăng nhập không còn hợp lệ.')
    redirect='/admin' if mode=='admin' else '/app'
    record_activity(account['id'],f'Chuyển sang chế độ {"ADMIN" if mode=="admin" else "nhân viên"}','/api/auth/switch-mode','POST',200,mode)
    return {'ok':True,'active_mode':mode,'redirect':redirect}

@app.get('/api/admin/profile')
def admin_profile(req:Request):
    u=current_admin(req); return json_safe(get_admin_profile(u['id']) or {})
@app.post('/api/admin/join-code/regenerate')
def admin_regenerate_code(req:Request):
    u=current_admin(req); code=regenerate_join_code(u['id']); record_activity(u['id'],'Đổi mã đăng ký nhân viên','/api/admin/join-code/regenerate','POST',200,''); return {'ok':True,'join_code':code}
@app.get('/api/admin/overview')
def admin_overview_api(req:Request):
    u=current_admin(req); return json_safe(admin_overview(u['id']))
@app.get('/api/admin/staff')
def admin_staff_api(req:Request):
    u=current_admin(req)
    return json_safe({'items':admin_staff(u['id']),'health':admin_team_health(u['id'])})

@app.get('/api/admin/team-status')
def admin_team_status_api(req:Request):
    u=current_admin(req)
    return json_safe(admin_team_health(u['id']))

@app.post('/api/admin/team-repair')
def admin_team_repair_api(req:Request):
    """Đồng bộ an toàn các liên kết nhân viên có thể xác định chắc chắn."""
    u=current_admin(req)
    result=repair_company_memberships(u['id'])
    health=admin_team_health(u['id'])
    record_activity(u['id'],'Đồng bộ danh sách nhân viên','/api/admin/team-repair','POST',200,
                    f"Đã kiểm tra {health.get('employees',0)} nhân viên")
    return json_safe({'ok':True,'result':result,'health':health,'items':admin_staff(u['id'])})
@app.get('/api/admin/staff/{employee_id}')
def admin_staff_detail_api(req:Request,employee_id:int):
    u=current_admin(req)
    try:return json_safe(admin_employee_detail(u['id'],employee_id))
    except ValueError as e: raise HTTPException(404,str(e))
@app.post('/api/admin/staff/{employee_id}/active')
def admin_staff_active_api(req:Request,employee_id:int,b:ActiveBody):
    u=current_admin(req)
    try:set_employee_active(u['id'],employee_id,b.active)
    except ValueError as e: raise HTTPException(404,str(e))
    record_activity(u['id'],'Mở khóa tài khoản nhân viên' if b.active else 'Khóa tài khoản nhân viên',f'/api/admin/staff/{employee_id}/active','POST',200,str(employee_id))
    return {'ok':True,'active':b.active}
@app.get('/api/admin/activity')
def admin_activity_api(req:Request,limit:int=200):
    u=current_admin(req); return json_safe({'items':admin_activity(u['id'],limit)})

@app.get('/api/system/health')
async def health(req:Request):
    u=current_user(req); _user_rate_limit(u,'system-health',30,60)
    data=await check_all()
    try: data['storage']=database_runtime_info()
    except Exception as e: data['storage']={'engine':'sqlite','error':str(e)}
    return data
@app.post('/api/system/test/groq')
async def tg(req:Request):
    u=current_user(req); _user_rate_limit(u,'provider-test',10,300); return await check_groq()
@app.post('/api/system/test/ollama')
async def to(req:Request):
    u=current_user(req); _user_rate_limit(u,'provider-test',10,300); return await check_ollama()
@app.post('/api/system/provider')
def set_provider(req:Request,b:Provider):
    u=current_user(req)
    try:p=set_user_ai_provider(u['id'],b.provider)
    except ValueError as e:raise HTTPException(400,str(e))
    return {'ok':True,'provider':p}


@app.post('/api/customers/upload')
async def legacy_customer_upload(req: Request, file: UploadFile = File(...)):
    """Luồng upload cũ được giữ nguyên để tương thích. Luồng mới dùng /inspect.
    Endpoint này đọc file -> mapping -> ETL -> lưu DB -> phân tích/phân nhóm.
    """
    u=current_user(req); _user_rate_limit(u,'data-upload',10,3600)
    raw=await read_upload_limited(file,config.MAX_UPLOAD_BYTES)
    filename=file.filename or 'dataset'
    try:
        from .data_pipeline_compat import read_dataframe
        df=read_dataframe(raw, filename)
        if df is None or df.empty:
            raise ValueError('File không có dữ liệu.')
        # Chuẩn hóa tên cột và bỏ cột trùng để tránh lỗi pandas phía sau.
        df.columns=[str(c).strip() for c in df.columns]
        df=df.loc[:, ~df.columns.duplicated()].copy()
        raw_records=df.to_dict('records')
        # Mapping hai lớp: rule trước, Groq chỉ xử lý cột chưa nhận diện.
        mapping=await map_columns_two_layer(list(df.columns),raw_records,_provider_for(u),u.get('company_id'))
        mapping_config=[]
        for m in mapping:
            mapping_config.append({'Tên cột gốc':m['source_column'],'AI hiểu là':m['canonical_field'] if m.get('canonical_field') not in ('unmapped','unknown_column') else 'unmapped'})
        from data_preprocessor import run_advanced_etl
        safe_records,audit=await run_advanced_etl(raw_records,mapping_config,filename)
        if not safe_records:
            raise ValueError('Không tạo được dữ liệu chuẩn hóa từ file.')
        upload_id=save_uploaded_dataset(filename,safe_records,list(safe_records[0].keys()),'legacy_web_upload',user_id=u['id'])
        save_canonical_customers(upload_id,safe_records)
        audit_id=save_learning_audit(upload_id,filename,audit,mapping,audit.get('missing_required_fields',[]),user_id=u['id'])
        confirm_learning_audit(audit_id,user_id=u['id'])
        intelligence=build_customer_intelligence(safe_records); save_customer_intelligence_features(intelligence,upload_id)
        seg=hybrid_segment_customers(intelligence,n_clusters=None,random_state=config.RANDOM_STATE) if len(intelligence)>=2 else {'labeled_df':intelligence,'data':intelligence,'profiles':{},'n_clusters':0,'silhouette':None,'quality':{'score':0,'status':'LOW'}}
        labeled=seg.get('labeled_df',seg.get('data',intelligence)); profiles=seg.get('profiles',{})
        if not labeled.empty and 'segment_id' in labeled.columns:
            save_customer_segments(labeled,profiles,upload_id,seg.get('silhouette'))
            save_segmentation_run(upload_id,seg)
        personas=[]
        if personas: save_customer_personas(personas,upload_id)
        latest_state[u['id']]={'upload_id':upload_id,'df':labeled,'personas':personas,'profiles':profiles,'segmentation_quality':seg.get('quality',{}),'twins':[],'mapping':mapping,'audit':audit,'audit_id':audit_id,'learning_confirmed':True}
        return json_safe({'ok':True,'summary':{'rows':len(safe_records),'columns':list(df.columns),'audit':audit,'mapping':mapping,'segmentation':{'n_clusters':seg.get('n_clusters',0),'silhouette':seg.get('silhouette')},'upload_id':upload_id}})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f'Không thể tải/xử lý file: {type(e).__name__}: {e}')

@app.post('/api/customers/inspect')
async def staged_inspect(req:Request,file:UploadFile=File(...)):
    """Bước 1: chỉ đọc/kiểm tra file. Không gọi AI và không lưu vào dữ liệu mô phỏng."""
    u=current_user(req); _user_rate_limit(u,'data-upload',10,3600)
    raw=await read_upload_limited(file,config.MAX_UPLOAD_BYTES)
    from .data_pipeline_compat import read_dataframe
    try:
        df=read_dataframe(raw,file.filename or '')
        if df.empty: raise ValueError('File không có dữ liệu.')
        _prune_staged_sessions(); sid=str(uuid.uuid4())
        inspection=inspect_dataframe(df,file.filename or 'dataset',_rule_based_match)
        staged_sessions[sid]={'user_id':u['id'],'filename':file.filename or 'dataset','df':df,'inspection':inspection,'mapping':None,'inspection_confirmed':False,'learning_confirmed':False,'upload_id':None,'audit_id':None,'learned_records':None,'audit':None,'_created_monotonic':time.monotonic()}
        return json_safe({'ok':True,'session_id':sid,'inspection':inspection,'message':'Đã đọc dữ liệu. Chưa gọi AI và chưa đưa dữ liệu vào pipeline mô phỏng.'})
    except Exception as e:
        raise HTTPException(400,'Không thể đọc dữ liệu: '+str(e))

@app.post('/api/customers/inspect/{session_id}/confirm')
async def staged_confirm_inspection(req:Request,session_id:str):
    """Bước 2: người dùng xác nhận preview, sau đó mới cho phép AI mapping."""
    u=current_user(req); _prune_staged_sessions(); st=staged_sessions.get(session_id)
    if not st or st.get('user_id')!=u['id']: raise HTTPException(404,'Không tìm thấy phiên dữ liệu.')
    if st.get('inspection_confirmed'):
        return json_safe({'ok':True,'session_id':session_id,'mapping':st.get('mapping') or [],'already_confirmed':True})
    df=st['df']; records=df.head(100).where(pd.notna(df.head(100)),None).to_dict('records')
    try:
        mapping=await map_columns_two_layer(list(df.columns),records,_provider_for(u),u.get('company_id'))
        missing=missing_required_fields(mapping)
        duplicates=detect_possible_duplicates(df,mapping)
        current_rows=apply_mapping(df.where(pd.notna(df),None).to_dict('records'),mapping)
        current_canonical=pd.DataFrame(current_rows)
        historical_rows=load_canonical_customers(limit=50000,user_id=u['id'],confirmed_only=True)
        drift=data_drift(current_canonical,pd.DataFrame(historical_rows) if historical_rows else pd.DataFrame())
        st['mapping']=mapping; st['inspection_confirmed']=True; st['missing_required']=missing; st['duplicates']=duplicates; st['drift']=drift
        return json_safe({'ok':True,'session_id':session_id,'mapping':mapping,'missing_required_fields':missing,'duplicates':duplicates,'drift':drift,'message':'Đã xác nhận dữ liệu. Mapping hoàn thành; hệ thống cũng đã kiểm tra trùng lặp và độ lệch so với lịch sử.'})
    except Exception as e:
        raise HTTPException(400,'Không thể mapping dữ liệu: '+str(e))

@app.get('/api/customers/inspect/{session_id}')
def staged_inspection_status(req:Request,session_id:str):
    u=current_user(req); _prune_staged_sessions(); st=staged_sessions.get(session_id)
    if not st or st.get('user_id')!=u['id']: raise HTTPException(404,'Không tìm thấy phiên dữ liệu.')
    return json_safe({'session_id':session_id,'inspection':st['inspection'],'mapping':st.get('mapping'),'inspection_confirmed':st.get('inspection_confirmed',False),'learning_confirmed':st.get('learning_confirmed',False),'audit':st.get('audit'),'dataset_id':st.get('upload_id'),'audit_id':st.get('audit_id')})


@app.put('/api/customers/inspect/{session_id}/mapping')
def staged_update_mapping(req:Request,session_id:str,body:MappingBody):
    # Human correction layer for schema mapping. Does not call AI.
    u=current_user(req); _prune_staged_sessions(); st=staged_sessions.get(session_id)
    if not st or st.get('user_id')!=u['id']: raise HTTPException(404,'Không tìm thấy phiên dữ liệu.')
    if not st.get('inspection_confirmed'): raise HTTPException(400,'Hãy xác nhận dữ liệu trước.')
    allowed=set(CANONICAL_SCHEMA.keys())|{'unmapped'}; used=set(); cleaned=[]
    source_cols=set(map(str,st['df'].columns))
    for m in body.mappings or []:
        src=str(m.get('source_column') or '').strip(); field=str(m.get('canonical_field') or 'unmapped').strip()
        if src not in source_cols: continue
        if field not in allowed: raise HTTPException(400,f'Trường chuẩn không hợp lệ: {field}')
        if field!='unmapped' and field in used: raise HTTPException(400,f'Mỗi trường chuẩn chỉ được map một lần: {field}')
        if field!='unmapped': used.add(field)
        cleaned.append({'source_column':src,'canonical_field':field,'confidence':1.0 if field!='unmapped' else 0.0,'confidence_display':'100%' if field!='unmapped' else '0%','reasoning':'Người dùng đã xác nhận thủ công.','source':'human_confirmed'})
    existing={m.get('source_column'):m for m in (st.get('mapping') or [])}
    sent={m['source_column'] for m in cleaned}
    for col in source_cols-sent:
        m=existing.get(col)
        if m: cleaned.append(m)
    missing=missing_required_fields(cleaned)
    df=st['df']; duplicates=detect_possible_duplicates(df,cleaned)
    current_rows=apply_mapping(df.where(pd.notna(df),None).to_dict('records'),cleaned)
    current_canonical=pd.DataFrame(current_rows)
    historical_rows=load_canonical_customers(limit=50000,user_id=u['id'],confirmed_only=True)
    drift=data_drift(current_canonical,pd.DataFrame(historical_rows) if historical_rows else pd.DataFrame())
    st['mapping']=cleaned; st['missing_required']=missing; st['duplicates']=duplicates; st['drift']=drift
    return json_safe({'ok':True,'mapping':cleaned,'missing_required_fields':missing,'duplicates':duplicates,'drift':drift,'message':'Đã lưu mapping bạn xác nhận. Bước này không gọi AI.'})

@app.post('/api/customers/learning/start/{session_id}')
async def staged_learning_start(req:Request,session_id:str):
    """Bước 3: AI học từ dữ liệu real sau khi preview đã được xác nhận."""
    u=current_user(req); _prune_staged_sessions(); st=staged_sessions.get(session_id)
    if not st or st.get('user_id')!=u['id']: raise HTTPException(404,'Không tìm thấy phiên dữ liệu.')
    if not st.get('inspection_confirmed') or not st.get('mapping'):
        raise HTTPException(400,'Hãy xác nhận bước đọc dữ liệu trước khi AI học.')
    _user_rate_limit(u,'ai-learning',10,3600)
    provider=_provider_for(u)
    jid=str(uuid.uuid4())
    _job_register(staged_learning_jobs,jid,u,'ai_learning',{'status':'running','progress':0,'step':'Chuẩn bị dữ liệu','session_id':session_id,'error':None,'audit':None},{'session_id':session_id})
    async def worker():
        upload_id=None
        try:
            from schema_mapper import CANONICAL_SCHEMA
            df=st['df'].copy()
            mapping=st['mapping']
            canonical_rows=apply_mapping(df.where(pd.notna(df),None).to_dict('records'),mapping)
            canonical_df=pd.DataFrame(canonical_rows)
            for field,meta in CANONICAL_SCHEMA.items():
                if field not in canonical_df.columns: canonical_df[field]=np.nan
                if meta['type']=='numeric': canonical_df[field]=pd.to_numeric(canonical_df[field],errors='coerce')
                else: canonical_df[field]=canonical_df[field].astype('object')
            # Enterprise data foundation: invalid source values are quarantined as missing-invalid,
            # and deterministic features derived from REAL fields are labeled DERIVED_REAL.
            canonical_df,initial_provenance,invalid_summary=sanitize_canonical(canonical_df)
            canonical_df,initial_provenance,derived_summary=derive_real_features(canonical_df,initial_provenance)
            staged_learning_jobs[jid].update(progress=10,step='Phân tích dữ liệu real, dữ liệu dẫn xuất và dữ liệu đã xác nhận trước đó')
            # Knowledge base tích lũy: chỉ dùng dataset của đúng tài khoản và đã được
            # người dùng xác nhận ở các lần trước. Dataset hiện tại chưa xác nhận nên
            # không được tự đưa vào knowledge base của lần sau.
            historical_rows=load_canonical_customers(limit=100000, user_id=u['id'], confirmed_only=True)
            historical_df=pd.DataFrame(historical_rows) if historical_rows else pd.DataFrame()
            learning_source_df=canonical_df
            if not historical_df.empty:
                learning_source_df=pd.concat([historical_df, canonical_df], ignore_index=True, sort=False)
            learning={}
            from schema_mapper import REQUIRED_FIELDS
            for idx,field in enumerate(REQUIRED_FIELDS):
                staged_learning_jobs[jid].update(progress=10+int((idx/max(1,len(REQUIRED_FIELDS)))*55),step=f'AI đang học trường: {field}')
                try:
                    from staged_data_workflow import _learn_field
                    learning[field]=await _learn_field(field,learning_source_df,provider)
                except Exception as e:
                    learning[field]={'field':field,'learned':False,'confidence':0,'strategy':'not_enough_evidence','evidence':f'AI không thể học trường này: {e}','candidate_values':[],'notes':''}
            staged_learning_jobs[jid].update(progress=70,step='Bổ sung các trường còn thiếu')
            learned_df,provenance,filled=apply_learned_fields(canonical_df,learning,initial_provenance=initial_provenance)
            audit=build_audit(canonical_df,learned_df,provenance,learning)
            audit['filled_counts']=filled
            audit['invalid_source_summary']=invalid_summary
            audit['derived_real_summary']=derived_summary
            audit['data_quality']=st.get('inspection',{}).get('quality',{})
            audit['duplicates']=st.get('duplicates',{})
            audit['data_drift']=st.get('drift',{})
            audit['learning_provider']=provider
            audit['learned_summary']=[x for x in audit.get('learned_fields',[]) if x.get('learned')]
            staged_learning_jobs[jid].update(progress=80,step='Lưu audit dữ liệu')
            safe_records=json_safe(learned_df.where(pd.notna(learned_df),None).to_dict('records'))
            for _i,_rec in enumerate(safe_records):
                if _i < len(provenance):
                    _rec['_field_sources']={str(k):str(v) for k,v in provenance.iloc[_i].to_dict().items()}
            upload_id=save_uploaded_dataset(st['filename'],safe_records,list(learned_df.columns),'staged_web_upload',user_id=u['id'])
            staged_learning_jobs[jid].update(progress=84,step='Lưu khách hàng đã chuẩn hóa')
            await asyncio.sleep(0)
            save_canonical_customers(upload_id,safe_records)
            staged_learning_jobs[jid].update(progress=88,step='Lưu báo cáo audit')
            await asyncio.sleep(0)
            audit_id=save_learning_audit(upload_id,st['filename'],audit,mapping,audit.get('remaining_missing_fields',[]),user_id=u['id'])
            # Downstream logic is the SAME existing MarketSim pipeline.
            staged_learning_jobs[jid].update(progress=91,step='Tính Customer Intelligence')
            await asyncio.sleep(0)
            intelligence=build_customer_intelligence(safe_records); save_customer_intelligence_features(intelligence,upload_id)
            staged_learning_jobs[jid].update(progress=95,step='Phân nhóm khách hàng')
            await asyncio.sleep(0)
            seg=hybrid_segment_customers(intelligence,n_clusters=None,random_state=config.RANDOM_STATE)
            labeled=seg.get('labeled_df',intelligence); profiles=seg.get('profiles',{})
            if not labeled.empty and 'segment_id' in labeled.columns:
                save_customer_segments(labeled,profiles,upload_id,seg.get('silhouette'))
                save_segmentation_run(upload_id,seg)
            staged_learning_jobs[jid].update(progress=98,step='Tạo chân dung khách hàng')
            await asyncio.sleep(0)
            personas=build_data_driven_personas(labeled,profiles) if not labeled.empty else []
            if personas: save_customer_personas(personas,upload_id)
            st.update({'upload_id':upload_id,'audit_id':audit_id,'learned_records':safe_records,'audit':audit,'learning':learning,'df':labeled,'personas':personas,'profiles':profiles,'segmentation_quality':seg.get('quality',{}),'twins':[]})
            # This staged path deliberately requires explicit audit confirmation.
            latest_state[u['id']]={'upload_id':upload_id,'df':labeled,'personas':personas,'profiles':profiles,'segmentation_quality':seg.get('quality',{}),'twins':[],'mapping':mapping,'audit':audit,'audit_id':audit_id,'learning_confirmed':False,'staged_session_id':session_id}
            staged_learning_jobs[jid].update(status='completed',progress=100,step='Hoàn thành — chờ người dùng xác nhận audit',audit=audit,audit_id=audit_id,dataset_id=upload_id,filled_counts=filled)
            update_background_job(jid,u['id'],status='completed',progress=100,result={'audit_id':audit_id,'dataset_id':upload_id,'session_id':session_id})
        except Exception as e:
            print(f'[AI LEARNING JOB ERROR] job={jid} error={type(e).__name__}: {e}', flush=True)
            staged_learning_jobs[jid].update(status='failed',error=str(e))
            # A failed unconfirmed run must not leave a misleading dataset card.
            if upload_id is not None:
                try:
                    delete_ai_learning_dataset(u['id'],upload_id)
                except Exception as cleanup_error:
                    print(f'[AI LEARNING CLEANUP ERROR] job={jid} upload_id={upload_id} error={type(cleanup_error).__name__}: {cleanup_error}', flush=True)
            try:
                update_background_job(jid,u['id'],status='failed',progress=staged_learning_jobs[jid].get('progress',0),error=str(e))
            except Exception as persist_error:
                print(f'[AI LEARNING STATUS ERROR] job={jid} error={type(persist_error).__name__}: {persist_error}', flush=True)
    asyncio.create_task(worker())
    return {'ok':True,'job_id':jid}

@app.get('/api/customers/learning/status/{job_id}')
def staged_learning_status(req:Request,job_id:str):
    u=current_user(req); j=_job_owned(staged_learning_jobs,job_id,u)
    return json_safe(j)

@app.post('/api/customers/learning/confirm/{session_id}')
def staged_learning_confirm(req:Request,session_id:str):
    u=current_user(req)
    _prune_staged_sessions(); st=staged_sessions.get(session_id)
    state=latest_state.get(u['id'],{})
    if not st or st.get('user_id')!=u['id']:
        if state.get('staged_session_id')==session_id and state.get('audit_id'):
            st={'user_id':u['id'],'audit_id':state.get('audit_id'),'upload_id':state.get('upload_id'),'df':state.get('df'),'personas':state.get('personas',[]),'profiles':state.get('profiles',{}),'segmentation_quality':state.get('segmentation_quality',{}),'audit':state.get('audit')}
        else:
            raise HTTPException(404,'Không tìm thấy phiên dữ liệu. Hãy mở lại dữ liệu khách hàng và kiểm tra trạng thái AI Learning.')
    if not st.get('audit_id') or not st.get('audit'): raise HTTPException(400,'AI Learning chưa hoàn thành.')
    confirm_learning_audit(st['audit_id'], user_id=u['id'])
    save_company_schema_mappings(u.get('company_id'),u['id'],st.get('mapping') or state.get('mapping') or [])
    state.update({'learning_confirmed':True,'audit_id':st['audit_id'],'upload_id':st.get('upload_id'),'df':st.get('df'),'personas':st.get('personas',[]),'profiles':st.get('profiles',{}),'segmentation_quality':st.get('segmentation_quality',state.get('segmentation_quality',{})),'twins':[],'staged_session_id':session_id,'audit':st.get('audit')})
    latest_state[u['id']]=state
    if session_id in staged_sessions: staged_sessions[session_id]['learning_confirmed']=True
    return {'ok':True,'confirmed':True,'session_id':session_id,'message':'Đã xác nhận chất lượng dữ liệu. Các bước Digital Twin và mô phỏng đã được mở.'}

@app.post('/api/customers/learning/confirm-latest')
def staged_learning_confirm_latest(req:Request):
    u=current_user(req); state=latest_state.get(u['id'],{})
    if not state.get('audit_id') or not state.get('audit'):
        raise HTTPException(400,'AI Learning chưa hoàn thành.')
    confirm_learning_audit(state['audit_id'], user_id=u['id'])
    save_company_schema_mappings(u.get('company_id'),u['id'],state.get('mapping') or [])
    state['learning_confirmed']=True
    latest_state[u['id']]=state
    sid=state.get('staged_session_id')
    if sid in staged_sessions: staged_sessions[sid]['learning_confirmed']=True
    return {'ok':True,'confirmed':True,'session_id':sid,'message':'Đã xác nhận chất lượng dữ liệu. Các bước Digital Twin và mô phỏng đã được mở.'}

@app.get('/api/customers/learning/audit/latest')
def staged_latest_audit(req:Request):
    u=current_user(req)
    st=latest_state.get(u['id'],{})
    audit_id=st.get('audit_id')
    audit=st.get('audit')
    if audit_id and not audit:
        try: audit=get_learning_audit_by_upload(st.get('upload_id'), user_id=u['id'])
        except Exception: audit=None
    return json_safe({'ok':True,'id':audit_id,'audit_id':audit_id,'session_id':st.get('staged_session_id'),'confirmed':bool(st.get('learning_confirmed')),'audit':audit or {},'dataset_id':st.get('upload_id')})

@app.get('/api/customers')
def customers_list(req:Request, limit:int=100):
    u=current_user(req); limit=max(1,min(limit,5000))
    rows=load_canonical_customers(limit=limit,user_id=u['id'],confirmed_only=True)
    st=latest_state.get(u['id'],{})
    # Nếu phiên hiện tại vừa học xong nhưng chưa xác nhận, không đưa vào knowledge base.
    return json_safe({'items':[{'row':r,'segment_id':None} for r in rows],'count':len(rows)})

@app.get('/api/customers/latest')
def customers_latest(req:Request):
    u=current_user(req); items=get_user_dataset_history(u['id'],1)
    return json_safe({'dataset':({'filename':items[0]['name'],'rows':items[0]['records'],'confirmed':items[0]['learning_confirmed']} if items else None)})

@app.get('/api/customers/datasets')
def customer_dataset_history(req:Request):
    u=current_user(req)
    return json_safe({'stats':get_user_dataset_stats(u['id']),'items':get_user_dataset_history(u['id'],50)})

@app.get('/api/customers/datasets/{upload_id}/learning')
def customer_dataset_learning_detail(req:Request,upload_id:int):
    """Show what AI learned for one dataset owned by the current account."""
    u=current_user(req)
    detail=get_dataset_learning_detail(u['id'],upload_id)
    if not detail:
        # Do not reveal whether another account owns the guessed upload id.
        raise HTTPException(404,'Không tìm thấy bộ dữ liệu thuộc tài khoản này.')
    return json_safe({'ok':True,'dataset':detail})

@app.post('/api/trends/collect')
async def collect_trends(req:Request):
    u=current_user(req); _user_rate_limit(u,'trend-collection',10,600)
    try:
        from data_collector import fetch_pytrends
        # Pytrends performs blocking HTTP calls. Run it outside FastAPI's event
        # loop so one slow Google response cannot freeze other users' requests.
        trends=await asyncio.to_thread(fetch_pytrends)
        rows=[] if trends is None or trends.empty else trends.to_dict('records')
        meta=dict(getattr(trends,'attrs',{}) or {}) if trends is not None else {}
        status=str(meta.get('status') or ('live' if rows else 'empty'))
        message=str(meta.get('message') or ('Đã cập nhật Google Trends.' if rows else 'Google Trends chưa trả dữ liệu.'))
        internal_error=str(meta.get('error') or '')
        if internal_error:
            print(f'[PYTRENDS {status.upper()}] {internal_error}',flush=True)
        return json_safe({
            'ok':bool(rows),
            'items':rows,
            'count':len(rows),
            'source':meta.get('source') or 'Google Trends (Pytrends)',
            'status':status,
            'cached':bool(meta.get('cached')),
            'message':message,
            # Do not expose raw network exceptions/cookies/URLs to the browser.
            'error':None if rows else message,
        })
    except Exception as e:
        print(f'[PYTRENDS ENDPOINT ERROR] {type(e).__name__}: {e}',flush=True)
        message='Không thể khởi chạy bộ thu thập Google Trends. Kiểm tra requirements.txt và log máy chủ.'
        return {'ok':False,'items':[],'count':0,'source':'Google Trends (Pytrends)','status':'server_error','message':message,'error':message}

@app.get('/api/trends')
async def get_trends(req:Request):
    return await collect_trends(req)

@app.get('/api/analysis')
def analysis(req:Request):
    u=current_user(req); st=latest_state.get(u['id'])
    if st and st.get('df') is not None:
        df=st['df']; intel=summarize_customer_intelligence(df); profiles=st.get('profiles',{}) or {}
        seg_quality=st.get('segmentation_quality') or {}
        return json_safe({'ok':True,'intelligence':intel,'segmentation':{'profiles':profiles,'count':len(df),'n_clusters':len(profiles),'quality':seg_quality},'audit':st.get('audit',{}),'learning_confirmed':bool(st.get('learning_confirmed')),'upload_id':st.get('upload_id')})

    # After server restart, rebuild deterministic Customer Intelligence from the
    # latest confirmed dataset and read persisted segmentation quality.
    history=[x for x in get_user_dataset_history(u['id'],50) if x.get('learning_confirmed')]
    upload_id=history[0]['id'] if history else None
    rows=load_canonical_customers(upload_id=upload_id,limit=5000,user_id=u['id'],confirmed_only=True) if upload_id else []
    df=build_customer_intelligence(rows) if rows else pd.DataFrame()
    intel=summarize_customer_intelligence(df) if not df.empty else summarize_customer_intelligence(pd.DataFrame())
    run=get_segmentation_run(upload_id,user_id=u['id']) if upload_id else None
    seg_quality=(run or {}).get('metrics',{}) if run else {}
    seg_rows=get_customer_segments(upload_id=upload_id,limit=5000,user_id=u['id']) if upload_id else []
    profiles={}
    for r in seg_rows:
        sid=int(r.get('segment_id') or 0)
        if sid not in profiles:
            try: profiles[sid]=json.loads(r.get('profile_json') or '{}')
            except Exception: profiles[sid]={}
    return json_safe({'ok':True,'intelligence':intel,'segmentation':{'profiles':profiles,'count':len(df),'n_clusters':len(profiles),'quality':seg_quality},'audit':{},'learning_confirmed':bool(upload_id),'upload_id':upload_id})

@app.get('/api/segments')
def segments(req:Request):
    u=current_user(req); st=latest_state.get(u['id'],{})
    upload_id=st.get('upload_id')
    if not upload_id:
        history=[x for x in get_user_dataset_history(u['id'],50) if x.get('learning_confirmed')]
        upload_id=history[0]['id'] if history else None
    if not upload_id:
        return json_safe({'items':[],'quality':{},'upload_id':None})
    items=get_customer_segments(upload_id=upload_id,limit=5000,user_id=u['id'])
    run=get_segmentation_run(upload_id,user_id=u['id'])
    quality=st.get('segmentation_quality') or ((run or {}).get('metrics',{}) if run else {})
    return json_safe({'items':items,'quality':quality,'upload_id':upload_id})

@app.get('/api/audit')
def audit(req:Request):
    u=current_user(req); return json_safe({'items':get_all_learning_audits(100, user_id=u['id'])})


@app.get('/api/customers/learning/history')
@app.get('/api/learning/history')
def ai_learning_history(req:Request):
    u=current_user(req)
    return json_safe({'ok':True,'items':get_ai_learning_history(u['id'],200)})

@app.delete('/api/customers/learning/history/{upload_id}')
@app.delete('/api/learning/history/{upload_id}')
def ai_learning_history_delete(req:Request,upload_id:int):
    u=current_user(req)
    result=delete_ai_learning_dataset(u['id'],upload_id)
    if not result.get('deleted'):
        raise HTTPException(404,'Không tìm thấy dữ liệu học AI thuộc tài khoản này.')
    state=latest_state.get(u['id'])
    if state and state.get('upload_id')==upload_id:
        latest_state.pop(u['id'],None)
    for sid,st in list(staged_sessions.items()):
        if st.get('user_id')==u['id'] and st.get('upload_id')==upload_id:
            staged_sessions.pop(sid,None)
    try: record_activity(u['id'],'delete_learning_dataset',f"Xóa nguồn AI Learning: {result.get('upload_name','')}")
    except Exception: pass
    return json_safe({'ok':True,'message':'Đã xóa nguồn học AI. Dữ liệu này sẽ không còn được dùng cho các lần AI Learning sau. Lịch sử chiến dịch/mô phỏng vẫn được giữ nguyên.','result':result})

@app.post('/api/personas/generate/start')
async def generate_personas_start(req:Request,b:TwinBody):
    u=current_user(req); _user_rate_limit(u,'digital-twin',20,3600); st=_restore_employee_state(u)
    if not st: raise HTTPException(400,'Hãy tải dữ liệu khách hàng trước.')
    if st.get('audit_id') and not st.get('learning_confirmed'):
        raise HTTPException(400,'Bạn cần xem và xác nhận báo cáo AI Learning trước khi tạo khách hàng ảo.')
    labeled=st['df']; segment_ids=sorted(labeled['segment_id'].dropna().astype(int).unique().tolist()) if 'segment_id' in labeled.columns else [0]
    total=len(segment_ids)*b.count_per_segment; jid=str(uuid.uuid4())
    _job_register(persona_jobs,jid,u,'digital_twin_generation',{'status':'running','progress':0,'created':0,'total':total,'error':None,'twins':[]},{'upload_id':st.get('upload_id'),'total':total})
    async def worker():
        try:
            all_twins=[]
            for idx,sid in enumerate(segment_ids):
                part=generate_synthetic_twins(labeled,segment_id=sid,twins_per_segment=b.count_per_segment)
                all_twins.extend(part.get('twins',[])); persona_jobs[jid]['created']=len(all_twins); persona_jobs[jid]['progress']=round(len(all_twins)/max(total,1)*100,1)
                await asyncio.sleep(0)
            st['twins']=all_twins; save_synthetic_customer_twins(all_twins,st['upload_id'])
            persona_jobs[jid].update(status='completed',progress=100,created=len(all_twins),twins=all_twins)
            update_background_job(jid,u['id'],status='completed',progress=100,result={'count':len(all_twins),'upload_id':st.get('upload_id')})
        except Exception as e:
            persona_jobs[jid].update(status='failed',error=str(e))
            update_background_job(jid,u['id'],status='failed',progress=persona_jobs[jid].get('progress',0),error=str(e))
    asyncio.create_task(worker()); return {'ok':True,'job_id':jid,'total':total}
@app.get('/api/personas/generate/{job_id}')
def generate_personas_status(req:Request,job_id:str):
    u=current_user(req); j=_job_owned(persona_jobs,job_id,u)
    d={k:v for k,v in j.items() if k not in ('twins','payload_json','result_json')}
    if j.get('status')=='completed':
        if 'twins' in j: d['count']=len(j.get('twins') or [])
        elif isinstance(j.get('result'),dict): d['count']=j['result'].get('count',0)
    return json_safe(d)
@app.post('/api/personas/generate')
def generate_personas(req:Request,b:TwinBody):
    # Backward-compatible synchronous endpoint.
    u=current_user(req); _user_rate_limit(u,'digital-twin',20,3600); st=_restore_employee_state(u)
    if not st: raise HTTPException(400,'Hãy tải dữ liệu khách hàng trước.')
    if st.get('audit_id') and not st.get('learning_confirmed'):
        raise HTTPException(400,'Bạn cần xác nhận báo cáo AI Learning trước khi tạo khách hàng ảo.')
    result=generate_synthetic_twins(st['df'],twins_per_segment=b.count_per_segment); twins=result.get('twins',[]); st['twins']=twins; save_synthetic_customer_twins(twins,st['upload_id'])
    return json_safe({'ok':True,'count':len(twins),'twins':twins,'note':result.get('note')})
@app.get('/api/personas')
def personas(req:Request,limit:int=5000):
    u=current_user(req); st=_restore_employee_state(u)
    if st and st.get('twins'): return json_safe({'items':st['twins'][:max(1,min(limit,5000))]})
    # Never fall back to a global twins query: resolve only this account's latest confirmed upload.
    history=[x for x in get_user_dataset_history(u['id'],50) if x.get('learning_confirmed')]
    upload_id=history[0]['id'] if history else None
    if not upload_id: return json_safe({'items':[]})
    rows=get_synthetic_customer_twins(upload_id=upload_id,limit=max(1,min(limit,5000)),user_id=u['id'])
    return json_safe({'items':[r.get('twin') or r for r in rows]})

@app.post('/api/simulations/start')
async def start(req:Request,b:Sim):
    u=current_user(req); _user_rate_limit(u,'simulation',20,3600); st=_restore_employee_state(u)
    if not st: raise HTTPException(400,'Hãy tải dữ liệu và tạo khách hàng ảo trước.')
    if st.get('audit_id') and not st.get('learning_confirmed'):
        raise HTTPException(400,'Bạn cần xác nhận báo cáo AI Learning trước khi mô phỏng.')
    twins=st.get('twins') or generate_synthetic_twins(st['df'],twins_per_segment=max(1,b.count//max(1,st.get('seg_count',1) or 1))).get('twins',[])
    if not twins: raise HTTPException(400,'Không có khách hàng ảo để mô phỏng.')
    twins=twins[:b.count]; provider=str(b.provider or _provider_for(u)).lower().strip()
    if provider not in ('groq','ollama'):
        raise HTTPException(400,'Provider phải là groq hoặc ollama.')
    jid=str(uuid.uuid4())
    _job_register(jobs,jid,u,'simulation',{
        'status':'running',
        'progress':0,
        'total':len(twins),
        'results':[],
        'scenario_id':None,
        'error':None,
        # Diagnostics only: these fields do not change simulation logic/results.
        'provider':provider,
        'ai_success':0,
        'fallback_count':0,
        'ai_errors':[],
    },{'campaign_name':b.name or b.campaign,'count':len(twins),'provider':provider,'upload_id':st.get('upload_id')})
    async def worker():
        try:
            # quantitative twin model first
            from marketing_learning import latest_calibration
            calibration=latest_calibration(config.DB_PATH,user_id=u['id'])
            tdf=twins_to_dataframe(twins); model=simulate_twins(tdf,b.campaign,calibration=calibration)
            # LLM comments run concurrently with semaphore; use provider after real data is transformed to twins
            sem=asyncio.Semaphore(config.MAX_CONCURRENT_AI); done=0; lock=asyncio.Lock(); results=[None]*len(twins)
            async def one(i,t):
                nonlocal done
                async with sem:
                    base=model['results'].iloc[i] if i < len(model.get('results',[])) else {}
                    ai_twin=_compact_twin_for_ai(t)
                    # Same evaluation task as before, but internal generation/provenance metadata is omitted
                    # to reduce tokens. The campaign text and simulation-relevant twin evidence are preserved.
                    prompt=(
                        'Bạn đang đóng vai CHÍNH khách hàng tổng hợp trong hồ sơ dưới đây để phản ứng với chiến dịch marketing. '
                        'Chỉ dựa trên bằng chứng có trong hồ sơ; không suy luận danh tính thật và không tự thêm đặc điểm chưa có. '
                        'COMMENT phải là một câu phản ứng thật của khách hàng ở ngôi thứ nhất hoặc lời nhận xét tự nhiên, KHÔNG được '
                        'chép lại hướng dẫn, tên trường JSON, hoặc các cụm như "tiếng Việt tự nhiên, ngắn gọn". '
                        'REASON phải nêu 1-2 yếu tố cụ thể từ hồ sơ (ví dụ sở thích, pain point, độ nhạy giá, RFM/proxy) giải thích điểm số. '
                        'Nếu hồ sơ thiếu một thuộc tính thì không được bịa thuộc tính đó; hãy đánh giá bằng các bằng chứng còn lại. '
                        'Mô hình định lượng đã tính điểm; bạn chỉ giải thích, không tự chấm lại điểm. '
                        'Trả đúng MỘT JSON, không markdown, schema: '
                        '{"comment":"phản ứng của khách hàng","reason":"lý do dựa trên hồ sơ"}.\n'
                        'Chiến dịch: '+str(b.campaign)+'\n'
                        'Hồ sơ khách hàng tổng hợp: '+json.dumps(ai_twin,ensure_ascii=False,separators=(',',':'))
                    )
                    try:
                        raw=await _simulation_ai_call(prompt,provider); a,c=raw.find('{'),raw.rfind('}'); rr=json.loads(raw[a:c+1])
                        reaction={
                            'score':int(base.get('score',5)),
                            'sentiment':str(base.get('sentiment','neutral')),
                            'comment':str(rr.get('comment','')),
                            'reason':str(rr.get('reason','')),
                            'source':'quantitative_with_ai_explanation',
                            'conversion_probability':base.get('conversion_probability'),
                            'raw_conversion_probability':base.get('raw_conversion_probability'),
                            'calibration':calibration,
                        }
                        ai_ok=True
                        ai_error=None
                    except Exception as e:
                        # Keep the original fallback behavior exactly as-is.
                        # We only expose the real AI/provider/JSON error for diagnosis.
                        ai_ok=False
                        ai_error=f'{type(e).__name__}: {e}'
                        twin_id=t.get('twin_id') or t.get('id') or f'index-{i}'
                        print(f'[SIMULATION AI ERROR] job={jid} provider={provider} twin={twin_id} error={ai_error}', flush=True)
                        reaction={'score':int(base.get('score',5)),'sentiment':base.get('sentiment','neutral'),'comment':'Phản ứng được ước lượng từ mô hình định lượng của digital twin.','reason':'AI giải thích không khả dụng; điểm số vẫn do mô hình định lượng tạo.','source':'quantitative_fallback','conversion_probability':base.get('conversion_probability'),'raw_conversion_probability':base.get('raw_conversion_probability'),'calibration':calibration}
                    async with lock:
                        if ai_ok:
                            jobs[jid]['ai_success']+=1
                        else:
                            jobs[jid]['fallback_count']+=1
                            # Keep only a small diagnostic sample to avoid bloating memory/API responses.
                            if len(jobs[jid]['ai_errors']) < 20:
                                jobs[jid]['ai_errors'].append({
                                    'index':i,
                                    'twin_id':t.get('twin_id') or t.get('id'),
                                    'provider':provider,
                                    'error':ai_error,
                                })
                        done+=1; jobs[jid]['progress']=round(done/len(twins)*100,1)
                    results[i]={'persona':t,'reaction':reaction}
            await asyncio.gather(*(one(i,t) for i,t in enumerate(twins)))
            analysis={'summary':f'Mô phỏng {len(results)} khách hàng ảo bằng mô hình định lượng digital twin; AI chỉ diễn giải phản ứng.','strengths':[],'weaknesses':[],'star_rating':3}
            # Persist both the flat legacy fields and the full Digital Twin + reaction
            # payload. The flat columns keep old reports compatible; details preserves
            # the complete customer feed after refresh/reopen.
            persisted_results=[]
            for x in results:
                persona=x.get('persona') or {}
                reaction=x.get('reaction') or {}
                persisted_results.append({
                    'persona_name':persona.get('twin_id') or persona.get('name'),
                    'score':reaction.get('score',5),
                    'sentiment':reaction.get('sentiment','neutral'),
                    'reasoning':reaction.get('comment') or reaction.get('reason') or '',
                    'comment':reaction.get('comment') or '',
                    'reason':reaction.get('reason') or '',
                    'details':{'persona':persona,'reaction':reaction},
                })
            sid=save_simulation(b.name or b.campaign, persisted_results, analysis, user_id=u['id'])
            jobs[jid].update(status='completed',progress=100,results=json_safe(results),scenario_id=sid)
            update_background_job(jid,u['id'],status='completed',progress=100,result={'scenario_id':sid,'results_count':len(results),'provider':provider})
            print(
                f"[SIMULATION DIAGNOSTIC] job={jid} provider={provider} total={len(twins)} "
                f"ai_success={jobs[jid]['ai_success']} fallback={jobs[jid]['fallback_count']}",
                flush=True,
            )
        except Exception as e:
            print(f'[SIMULATION JOB ERROR] job={jid} provider={provider} error={type(e).__name__}: {e}', flush=True)
            jobs[jid].update(status='failed',error=str(e))
    asyncio.create_task(worker()); return {'ok':True,'job_id':jid,'count':len(twins)}
@app.get('/api/simulations/{job_id}')
def sim_status(req:Request,job_id:str):
    u=current_user(req); j=_job_owned(jobs,job_id,u)
    d={k:v for k,v in j.items() if k not in ('results','payload_json','result_json')}
    if j.get('status')=='completed':
        if 'results' in j:
            d['results_count']=len(j.get('results') or []); d['results_preview']=(j.get('results') or [])[:100]
        elif isinstance(j.get('result'),dict):
            d['results_count']=j['result'].get('results_count',0); d['scenario_id']=j['result'].get('scenario_id')
    return json_safe(d)
@app.get('/api/simulations/{sid}/results')
def sim_results(req:Request,sid:int):
    u=current_user(req)
    if get_scenario_by_id(sid,u['id']) is None:
        raise HTTPException(404,'Không tìm thấy chiến dịch.')

    rows=get_results_by_scenario(sid,u['id']).to_dict('records')
    items=[]
    for row in rows:
        raw_details=row.pop('details_json',None)
        details=None
        if raw_details:
            try:
                details=json.loads(raw_details) if isinstance(raw_details,str) else raw_details
            except Exception:
                details=None
        if isinstance(details,dict):
            persona=details.get('persona') if isinstance(details.get('persona'),dict) else {}
            reaction=details.get('reaction') if isinstance(details.get('reaction'),dict) else {}
            reaction=dict(reaction)
            reaction.setdefault('score',row.get('score',5))
            reaction.setdefault('sentiment',row.get('sentiment','neutral'))
            reaction.setdefault('comment',row.get('reasoning') or '')
            reaction.setdefault('reason',row.get('reasoning') or '')
            reaction.setdefault('purchase_intent',row.get('purchase_intent'))
            items.append({'persona':persona,'reaction':reaction,'persona_name':row.get('persona_name')})
        else:
            # Legacy simulations created before details_json still open normally.
            items.append(row)
    return json_safe({'items':items})
@app.get('/api/scenarios')
def scenarios(req:Request):
    u=current_user(req); return json_safe({'items':[{'id':r[0],'name':r[1],'rating':r[2]} for r in get_all_scenarios(u['id'])]})

@app.get('/api/overview')
def overview(req:Request):
    u=current_user(req)
    data=get_user_campaign_overview(u['id'])
    ds=get_user_dataset_stats(u['id'])
    history=get_user_dataset_history(u['id'],1)
    latest=history[0] if history else None
    data['datasets']=int(ds.get('datasets',0) or 0)
    data['customers_saved']=int(ds.get('canonical_customers',0) or 0)
    data['data_confidence_pct']=round(sum(float(x.get('real_data_pct',0) or 0) for x in history if x.get('learning_confirmed')) / max(1,sum(1 for x in history if x.get('learning_confirmed'))),1)
    data['latest_dataset']=latest
    return json_safe(data)

@app.post('/api/advanced/ab')
def advanced_ab(req:Request,b:ABBody):
    u=current_user(req); st=_restore_employee_state(u); twins=st.get('twins') if st else []
    if not twins:raise HTTPException(400,'Hãy tạo digital twin trước.')
    campaigns=[str(x or '').strip() for x in b.campaigns if str(x or '').strip()]
    if len(campaigns)<2 or len(campaigns)>10:
        raise HTTPException(400,'A/B test cần từ 2 đến 10 phương án hợp lệ.')
    from marketing_learning import latest_calibration
    calibration=latest_calibration(config.DB_PATH,user_id=u['id'])
    r=paired_compare(twins_to_dataframe(twins),campaigns,calibration=calibration)
    table=r.get('table',pd.DataFrame()); rows=table.to_dict('records') if not table.empty else []
    experiment_ids=[]
    for campaign,run in (r.get('runs') or {}).items():
        result_df=run.get('results',pd.DataFrame())
        experiment_ids.append(save_advanced_experiment(
            'ab',campaign,run.get('summary') or {},
            result_df.to_dict('records') if isinstance(result_df,pd.DataFrame) else [],
            model_version='heuristic_v1_calibrated',user_id=u['id'],company_id=u.get('company_id'),
        ))
    return json_safe({'status':r['status'],'results':rows,'experiment_ids':experiment_ids,'calibration':calibration})
@app.post('/api/advanced/optimize')
def advanced_opt(req:Request,b:OptBody):
    u=current_user(req); st=_restore_employee_state(u); twins=st.get('twins') if st else []
    if not twins:raise HTTPException(400,'Hãy tạo digital twin trước.')
    if len(b.discount_options or [])>20 or len(b.channel_options or [])>20:
        raise HTTPException(400,'Mỗi danh sách tùy chọn chỉ được tối đa 20 giá trị.')
    from marketing_learning import latest_calibration
    calibration=latest_calibration(config.DB_PATH,user_id=u['id'])
    r=optimize_marketing(twins_to_dataframe(twins),b.budget,b.discount_options,b.channel_options,calibration=calibration)
    candidates=r.get('candidates',pd.DataFrame()); candidate_rows=candidates.head(100).to_dict('records') if not candidates.empty else []
    experiment_id=None
    if r.get('status')=='ok' and r.get('best'):
        best=dict(r['best']); best['population']=len(twins); best['calibration']=calibration
        experiment_id=save_advanced_experiment(
            'optimization',str(best.get('campaign') or 'Tối ưu chiến dịch'),best,candidate_rows,
            budget=b.budget,model_version='heuristic_v1_calibrated',user_id=u['id'],company_id=u.get('company_id'),
        )
    return json_safe({'status':r['status'],'best':r.get('best'),'candidates':candidate_rows,'experiment_id':experiment_id,'calibration':calibration})
@app.get('/api/advanced/experiments')
def advanced_experiments(req:Request):
    u=current_user(req); return json_safe({'items':get_advanced_experiments(100,user_id=u['id'])})

@app.post('/api/feedback')
def feedback(req:Request,b:FeedbackBody):
    u=current_user(req)
    if int(b.experiment_id or 0)>0 and not user_owns_experiment(u['id'],b.experiment_id):
        raise HTTPException(404,'Không tìm thấy thử nghiệm thuộc tài khoản này.')
    from marketing_learning import record_outcome
    try:
        metrics,cal=record_outcome(config.DB_PATH,b.experiment_id,b.predicted_conversion,b.actual_conversion,b.predicted_revenue,b.actual_revenue,b.notes,user_id=u['id'],company_id=u.get('company_id'))
    except ValueError as e:
        raise HTTPException(400,str(e))
    return {'ok':True,'metrics':metrics,'calibration':cal}
@app.get('/api/feedback')
def feedback_list(req:Request):
    u=current_user(req); from marketing_learning import feedback_history,latest_calibration
    return json_safe({'items':feedback_history(config.DB_PATH,100,user_id=u['id']).to_dict('records'),'calibration':latest_calibration(config.DB_PATH,user_id=u['id'])})

# Chat assistant memory.
# This only changes the assistant conversation layer. AI Learning, Digital Twin,
# segmentation, simulation and calibration logic are untouched.
_CHAT_CONTEXT_MESSAGES = 28
_CHAT_RETRIEVAL_MESSAGES = 8
_CHAT_HISTORY_SEARCH_LIMIT = 400
_CHAT_MESSAGE_CHAR_LIMIT = 1600

_CHAT_STOP_WORDS = {
    'la','là','va','và','cua','của','cho','toi','tôi','ban','bạn','mot','một',
    'nhung','những','cac','các','thi','thì','ma','mà','o','ở','co','có','nay','này',
    'do','đó','voi','với','duoc','được','gi','gì','hay','hãy','se','sẽ','da','đã',
    'dang','đang','tu','từ','tren','trên','trong','the','thế','nao','nào'
}


def _compact_chat_context(items: list[dict]) -> list[dict]:
    """Keep a token-conscious recent window while preserving real chat roles."""
    compact=[]
    for item in (items or [])[-_CHAT_CONTEXT_MESSAGES:]:
        role=str(item.get('role') or '').lower()
        if role not in ('user','assistant'):
            continue
        content=str(item.get('content') or '').strip()
        if not content:
            continue
        if len(content)>_CHAT_MESSAGE_CHAR_LIMIT:
            half=_CHAT_MESSAGE_CHAR_LIMIT//2
            content=content[:half]+' … '+content[-half:]
        compact.append({'role':role,'content':content})
    return compact


def _clean_memory_value(value: str, max_len: int = 160) -> str:
    value=re.sub(r'\s+',' ',str(value or '')).strip(" \t\r\n,.;:!?\"'")
    return value[:max_len].strip()


def _valid_explicit_memory_value(value: str) -> bool:
    """Reject question words/placeholders so 'tôi tên là gì?' never overwrites a real name."""
    norm=_clean_memory_value(value,220).casefold()
    if not norm:
        return False
    blocked={
        'gì','gi','ai','gì vậy','gi vay','gì nhỉ','gi nhi','gì thế','gi the',
        'không biết','khong biet','chưa biết','chua biet','không rõ','khong ro',
    }
    return norm not in blocked and not norm.startswith(('gì ','gi ','ai '))


def _extract_explicit_chat_memories(message: str) -> list[dict]:
    """Extract only facts explicitly stated by the user; never infer hidden traits."""
    raw=str(message or '').strip()
    if not raw:
        return []
    out=[]

    name_patterns=[
        r'(?i)(?:từ\s+giờ\s+)?(?:hãy\s+)?gọi\s+tôi\s+là\s+([^\n,.!?]{1,80}?)(?=\s+và\s+|$|[,.!?])',
        r'(?i)tôi\s+tên\s+là\s+([^\n,.!?]{1,80}?)(?=\s+và\s+|$|[,.!?])',
        r'(?i)tên\s+(?:của\s+)?tôi\s+là\s+([^\n,.!?]{1,80}?)(?=\s+và\s+|$|[,.!?])',
    ]
    for pat in name_patterns:
        m=re.search(pat,raw)
        if m:
            value=_clean_memory_value(m.group(1),80)
            if _valid_explicit_memory_value(value):
                out.append({'key':'preferred_name','value':value})
                break

    company_patterns=[
        r'(?i)công\s+ty\s+(?:của\s+)?tôi\s+(?:tên\s+)?là\s+([^\n,.!?]{1,120}?)(?=\s+và\s+|$|[,.!?])',
        r'(?i)doanh\s+nghiệp\s+(?:của\s+)?tôi\s+(?:tên\s+)?là\s+([^\n,.!?]{1,120}?)(?=\s+và\s+|$|[,.!?])',
    ]
    for pat in company_patterns:
        m=re.search(pat,raw)
        if m:
            value=_clean_memory_value(m.group(1),120)
            if _valid_explicit_memory_value(value):
                out.append({'key':'company_name','value':value})
                break

    m=re.search(r'(?is)(?:hãy\s+nhớ|nhớ\s+rằng|ghi\s+nhớ\s+rằng)\s+(.{3,220})$',raw)
    if m:
        value=_clean_memory_value(m.group(1),220)
        if value and not any(x['value'].casefold()==value.casefold() for x in out):
            import hashlib
            key='note_'+hashlib.sha1(value.casefold().encode('utf-8')).hexdigest()[:12]
            out.append({'key':key,'value':value})
    return out


def _memory_label(item: dict) -> str:
    key=str(item.get('memory_key') or '')
    value=str(item.get('memory_value') or '').strip()
    if key=='preferred_name':
        return f'Tên người dùng muốn được gọi: {value}'
    if key=='company_name':
        return f'Doanh nghiệp người dùng đã nhắc đến: {value}'
    return f'Điều người dùng đã yêu cầu ghi nhớ: {value}'


def _chat_terms(text: str) -> set[str]:
    import unicodedata
    norm=unicodedata.normalize('NFD',str(text or '').casefold())
    norm=''.join(c for c in norm if unicodedata.category(c)!='Mn')
    words=re.findall(r'[a-z0-9_]{2,}',norm)
    return {w for w in words if w not in _CHAT_STOP_WORDS}


def _relevant_older_chat(history: list[dict], query: str, recent_ids: set[int], limit: int = _CHAT_RETRIEVAL_MESSAGES) -> list[dict]:
    """Retrieve a few older turns that are textually relevant to the current question."""
    q_terms=_chat_terms(query)
    q_norm=str(query or '').casefold()
    scored=[]
    total=max(1,len(history))
    for pos,item in enumerate(history):
        try:
            mid=int(item.get('id') or 0)
        except Exception:
            mid=0
        if mid and mid in recent_ids:
            continue
        role=str(item.get('role') or '').lower()
        if role not in ('user','assistant'):
            continue
        content=str(item.get('content') or '').strip()
        if not content:
            continue
        c_terms=_chat_terms(content)
        overlap=len(q_terms & c_terms)
        score=float(overlap)*4.0
        if any(x in q_norm for x in ('tên là gì','tên tôi','gọi tôi','tôi là ai')):
            c_norm=content.casefold()
            if any(x in c_norm for x in ('tôi tên là','tên tôi là','gọi tôi là','gọi tôi')):
                score+=20.0
        score+=(pos+1)/total*0.25
        if score>0.5:
            scored.append((score,pos,item))
    top=sorted(scored,key=lambda x:(-x[0],-x[1]))[:max(0,int(limit))]
    return [x[2] for x in sorted(top,key=lambda x:x[1])]


def _build_chat_messages(history: list[dict], memories: list[dict], query: str) -> tuple[list[dict], int]:
    recent=(history or [])[-_CHAT_CONTEXT_MESSAGES:]
    recent_ids={int(x.get('id') or 0) for x in recent if x.get('id')}
    relevant=_relevant_older_chat(history or [],query,recent_ids)

    system=(
        'Bạn là Trợ lý MarketSim AI dành cho người làm kinh doanh và marketing. '
        'Trả lời bằng tiếng Việt rõ ràng, thân thiện, tránh thuật ngữ kỹ thuật khi không cần thiết. '
        'Hãy giữ mạch hội thoại: dùng các tin nhắn trước và bộ nhớ đã xác nhận để hiểu những câu '
        'như "phần đó", "nhóm vừa rồi", "tôi tên là gì" hoặc yêu cầu tiếp nối. '
        'Nếu một thông tin đã có trong bộ nhớ hoặc lịch sử thì không được nói rằng bạn không biết. '
        'Nếu thực sự chưa có thông tin thì nói rõ là chưa có, không tự bịa. '
        'Không biến kết quả mô phỏng thành sự thật tuyệt đối.'
    )
    messages=[{'role':'system','content':system}]

    if memories:
        memory_text='BỘ NHỚ ĐÃ ĐƯỢC NGƯỜI DÙNG NÓI RÕ:\n' + '\n'.join(
            f'- {_memory_label(x)}' for x in memories[:50]
        )
        memory_text+=(
            '\nCác thông tin trên do chính người dùng đã nói hoặc yêu cầu ghi nhớ. '
            'Ưu tiên dùng chúng khi câu hỏi liên quan.'
        )
        messages.append({'role':'system','content':memory_text})

    if relevant:
        old_text='MỘT SỐ ĐOẠN HỘI THOẠI CŨ CÓ LIÊN QUAN:\n'
        for item in relevant:
            who='Người dùng' if item.get('role')=='user' else 'Trợ lý'
            content=str(item.get('content') or '')
            if len(content)>900:
                content=content[:450]+' … '+content[-450:]
            old_text+=f'- {who}: {content}\n'
        messages.append({'role':'system','content':old_text.strip()})

    messages.extend(_compact_chat_context(recent))
    return messages,len(relevant)


@app.get('/api/chat/history')
def assistant_history(req:Request, limit:int=200):
    u=current_user(req)
    items=get_chat_history(u['id'],limit=max(1,min(limit,500)),company_id=u.get('company_id'))
    memories=get_chat_memories(u['id'],company_id=u.get('company_id'),limit=50)
    return json_safe({'ok':True,'items':items,'count':len(items),'memory_count':len(memories)})


@app.get('/api/chat/memory')
def assistant_memory(req:Request):
    u=current_user(req)
    memories=get_chat_memories(u['id'],company_id=u.get('company_id'),limit=50)
    return json_safe({
        'ok':True,
        'count':len(memories),
        'items':[{'label':_memory_label(x),'updated_at':x.get('updated_at')} for x in memories],
    })


@app.delete('/api/chat/history')
def assistant_clear_history(req:Request):
    u=current_user(req)
    deleted=clear_chat_history(u['id'],company_id=u.get('company_id'))
    deleted_memory=clear_chat_memory(u['id'],company_id=u.get('company_id'))
    return {'ok':True,'deleted':deleted,'deleted_memory':deleted_memory}


@app.post('/api/chat')
async def assistant(req:Request,b:Chat):
    u=current_user(req); _user_rate_limit(u,'chat-ai',30,60)
    provider=str(b.provider or _provider_for(u)).lower().strip()
    if provider not in ('groq','ollama'):
        raise HTTPException(400,'Provider phải là groq hoặc ollama.')
    message=str(b.message or '').strip()
    if not message:
        raise HTTPException(400,'Tin nhắn không được để trống.')

    message_id=save_chat_message(u['id'],'user',message,provider,u.get('company_id'))

    for item in _extract_explicit_chat_memories(message):
        upsert_chat_memory(
            u['id'],item['key'],item['value'],
            company_id=u.get('company_id'),source_message_id=message_id,
        )

    full_history=get_chat_history(
        u['id'],limit=_CHAT_HISTORY_SEARCH_LIMIT,company_id=u.get('company_id')
    )

    # One-time bootstrap for users who already had chat history before this upgrade:
    # recover only explicit memories from their existing user messages. No AI call.
    memories=get_chat_memories(u['id'],company_id=u.get('company_id'),limit=50)
    if not memories:
        for old in full_history:
            if str(old.get('role') or '').lower()!='user':
                continue
            for item in _extract_explicit_chat_memories(old.get('content') or ''):
                upsert_chat_memory(
                    u['id'],item['key'],item['value'],
                    company_id=u.get('company_id'),source_message_id=old.get('id'),
                )
        memories=get_chat_memories(u['id'],company_id=u.get('company_id'),limit=50)

    messages,retrieved_count=_build_chat_messages(full_history,memories,message)

    try:
        answer=await chat(messages,provider)
        save_chat_message(u['id'],'assistant',answer,provider,u.get('company_id'))
        return {
            'ok':True,'provider':provider,'answer':answer,
            'memory_messages':len(_compact_chat_context(full_history)),
            'memory_count':len(memories),
            'older_context_used':retrieved_count,
        }
    except Exception as e:
        raise HTTPException(502,str(e))

@app.get('/api/help')
def help_content(req:Request):
    current_user(req); return {'sections':[
      {'title':'Thu thập & chuẩn hóa','text':'Tải CSV/Excel. Rule-based sẽ khớp alias trước; AI chỉ được gọi cho cột chưa khớp. ETL ghi rõ ô nào là dữ liệu thật, AI suy luận hoặc mặc định.'},
      {'title':'Customer Intelligence','text':'RFM, độ nhạy giá và các chỉ số hành vi chỉ được tính khi dữ liệu nguồn có đủ bằng chứng. Mỗi chỉ số có nguồn và độ tin cậy.'},
      {'title':'Phân khúc lai','text':'Kết hợp numeric, categorical và text; tự chọn số cụm bằng silhouette khi không chỉ định.'},
      {'title':'Persona','text':'Persona được dựng từ dữ liệu thật của từng phân khúc. Số liệu bằng chứng không bị AI ghi đè.'},
      {'title':'Digital Twin','text':'Khách hàng ảo được bootstrap từ phân phối thật của từng phân khúc, jitter có giới hạn và sampling danh mục. Propensity là heuristic.'},
      {'title':'Mô phỏng chiến dịch','text':'Mô hình định lượng chạy trước, sau đó AI tạo điểm, cảm xúc, bình luận và lý do cho từng khách hàng ảo. Có thanh tiến trình và fallback nếu AI lỗi.'},
      {'title':'A/B và tối ưu','text':'Có so sánh nhiều phương án và dò tổ hợp giảm giá/kênh trong ngân sách để tìm phương án mô phỏng tốt nhất.'},
      {'title':'Hiệu chỉnh','text':'Sau campaign thật, nhập actual conversion/revenue để tính MAE, RMSE, bias, MAPE và fit hệ số calibration cho các lần dự đoán sau.'},
      {'title':'Groq Cloud','text':'Khi deploy domain, chỉ máy chủ cần GROQ_API_KEY. Máy khách không cần cài Ollama.'},
      {'title':'Ollama','text':'Chỉ chọn Ollama khi máy chủ thực sự có Ollama và model đã cấu hình.'},
      {'title':'Bảo mật','text':'Không đưa API key vào frontend. Không gửi nguyên bảng khách hàng thật lên Groq; AI cloud chỉ nhận dữ liệu tổng hợp/đã lọc theo luồng ứng dụng.'}
    ]}
