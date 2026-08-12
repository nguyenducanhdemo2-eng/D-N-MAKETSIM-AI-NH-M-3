
import asyncio, json, uuid, math, re, time
from pathlib import Path
import pandas as pd
import numpy as np
from fastapi import FastAPI, UploadFile, File, Request, Response, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import config
from database import *
from schema_mapper import _rule_based_match, CANONICAL_SCHEMA, REQUIRED_FIELDS, apply_mapping, missing_required_fields
from data_preprocessor import AdvancedETLPipeline
from customer_intelligence import build_customer_intelligence, summarize_customer_intelligence
from hybrid_segmentation import hybrid_segment_customers
from persona_engine import build_data_driven_personas
from digital_twin import generate_synthetic_twins, twins_to_dataframe
from advanced_simulation import simulate_twins, paired_compare, optimize_marketing
from .auth_db import init_auth, create_session, get_user, delete_session
from .admin_db import (init_admin_schema, admin_count, company_count, get_account, find_admin_by_join_code, attach_employee,
    create_company_admin, bootstrap_code_valid, require_admin_account, get_admin_profile, regenerate_join_code,
    admin_overview, admin_staff, admin_employee_detail, admin_activity, set_employee_active,
    record_activity, activity_name)
from .ai_provider import check_all, check_groq, check_ollama, chat
from .ai_bridge import call_text
from staged_data_workflow import inspect_dataframe, apply_learned_fields, build_audit

BASE_DIR=Path(__file__).resolve().parent.parent; FRONTEND=BASE_DIR/'frontend'
app=FastAPI(title='MarketSim AI',version='Final Cloud')
app.mount('/static',StaticFiles(directory=FRONTEND),name='static')
jobs={}
persona_jobs={}
latest_state={}
staged_sessions={}
staged_learning_jobs={}


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
    email:str; password:str; display_name:str=''; organization_name:str=''; bootstrap_code:str=''
class ActiveBody(BaseModel): active:bool
class Provider(BaseModel): provider:str
class MappingBody(BaseModel): mappings:list[dict]
class Sim(BaseModel): campaign:str; count:int=Field(default=100,ge=1,le=1000); provider:str|None=None; name:str='Chiến dịch mô phỏng'
class Chat(BaseModel): message:str; provider:str|None=None
class TwinBody(BaseModel): count_per_segment:int=Field(default=25,ge=1,le=500)
class ABBody(BaseModel): campaigns:list[str]
class OptBody(BaseModel): budget:float=0; discount_options:list[float]|None=None; channel_options:list[str]|None=None
class FeedbackBody(BaseModel): experiment_id:int; predicted_conversion:float; actual_conversion:float; predicted_revenue:float|None=None; actual_revenue:float|None=None; notes:str=''

@app.on_event('startup')
def startup(): init_db(); init_auth(); init_admin_schema()

def current_user(req):
    u=get_user(req.cookies.get(config.SESSION_COOKIE))
    if not u: raise HTTPException(401,'Bạn chưa đăng nhập.')
    account=get_account(u['id'])
    if not account or not int(account.get('is_active') or 0):
        raise HTTPException(403,'Tài khoản đã bị vô hiệu hóa.')
    return account

def current_admin(req):
    u=current_user(req)
    try:
        require_admin_account(u['id'])
    except PermissionError as e:
        raise HTTPException(403,str(e))
    return u

@app.middleware('http')
async def audit_employee_actions(req:Request, call_next):
    response=await call_next(req)
    try:
        if req.method.upper() in ('POST','PUT','PATCH','DELETE') and req.url.path.startswith('/api/') and not req.url.path.startswith('/api/admin/') and req.url.path not in ('/api/auth/login','/api/auth/logout','/api/auth/register','/api/auth/register-admin'):
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

async def map_columns_two_layer(columns, raw_records, provider):
    result=[]; used=set()
    unresolved=[]
    for col in columns:
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
def root():return FileResponse(FRONTEND/'pages/login.html')
@app.get('/app')
def app_page():return FileResponse(FRONTEND/'index.html')
@app.get('/admin')
def admin_page():return FileResponse(FRONTEND/'admin.html')

@app.get('/api/auth/admin-status')
def auth_admin_status():
    return {
        'admin_exists': admin_count() > 0,
        'admin_count': admin_count(),
        'company_count': company_count(),
        'admin_registration_open': True,
        'bootstrap_protected': bool(__import__('os').getenv('ADMIN_BOOTSTRAP_CODE','').strip()),
    }

@app.post('/api/auth/register')
def register(b:EmployeeRegister):
    admin=find_admin_by_join_code(b.leader_code)
    if not admin:
        raise HTTPException(400,'Mã doanh nghiệp / mã của người đứng đầu không đúng hoặc đã hết hiệu lực.')
    try:
        uid=create_user(b.email,b.password)
        attach_employee(uid,admin['id'],b.display_name)
        record_activity(uid,'Tạo tài khoản nhân viên','/api/auth/register','POST',200,f"Thuộc {admin.get('organization_name','doanh nghiệp')}")
    except Exception as e:
        raise HTTPException(400,str(e))
    return {'ok':True,'user_id':uid,'organization':admin.get('organization_name')}

@app.post('/api/auth/register-admin')
def register_admin(b:AdminRegister):
    # Multi-company: every business may create its own independent ADMIN account.
    if not bootstrap_code_valid(b.bootstrap_code):
        raise HTTPException(403,'Mã khởi tạo ADMIN không đúng.')
    if len(b.password)<6:
        raise HTTPException(400,'Mật khẩu phải có ít nhất 6 ký tự.')
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
def login(b:Auth,res:Response):
    if not verify_user(b.email,b.password): raise HTTPException(401,'Email hoặc mật khẩu không đúng.')
    import sqlite3
    with sqlite3.connect(config.DB_PATH) as c: uid=c.execute('SELECT id FROM users WHERE email=?',(b.email.lower().strip(),)).fetchone()[0]
    account=get_account(uid)
    if not account or not int(account.get('is_active') or 0):
        raise HTTPException(403,'Tài khoản đã bị vô hiệu hóa. Hãy liên hệ ADMIN.')
    res.set_cookie(config.SESSION_COOKIE,create_session(uid),httponly=True,samesite='lax',max_age=604800)
    record_activity(uid,'Đăng nhập hệ thống','/api/auth/login','POST',200,'')
    return {'ok':True,'user':account,'redirect':'/admin' if account.get('role')=='admin' else '/app'}
@app.post('/api/auth/logout')
def logout(req:Request,res:Response):
    u=get_user(req.cookies.get(config.SESSION_COOKIE))
    if u: record_activity(u['id'],'Đăng xuất hệ thống','/api/auth/logout','POST',200,'')
    delete_session(req.cookies.get(config.SESSION_COOKIE));res.delete_cookie(config.SESSION_COOKIE);return {'ok':True}
@app.get('/api/auth/me')
def me(req:Request):return current_user(req)

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
    u=current_admin(req); return json_safe({'items':admin_staff(u['id'])})
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
async def health(req:Request):current_user(req);return await check_all()
@app.post('/api/system/test/groq')
async def tg(req:Request):current_user(req);return await check_groq()
@app.post('/api/system/test/ollama')
async def to(req:Request):current_user(req);return await check_ollama()
@app.post('/api/system/provider')
def set_provider(req:Request,b:Provider):
    current_user(req); p=b.provider.lower()
    if p not in ('groq','ollama'):raise HTTPException(400,'Provider phải là groq hoặc ollama.')
    config.AI_PROVIDER=p;return {'ok':True,'provider':p}


@app.post('/api/customers/upload')
async def legacy_customer_upload(req: Request, file: UploadFile = File(...)):
    """Luồng upload cũ được giữ nguyên để tương thích. Luồng mới dùng /inspect.
    Endpoint này đọc file -> mapping -> ETL -> lưu DB -> phân tích/phân nhóm.
    """
    u=current_user(req)
    raw=await file.read()
    if not raw:
        raise HTTPException(400, 'File rỗng hoặc không đọc được.')
    if len(raw)>config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, f'File vượt quá giới hạn {config.MAX_UPLOAD_BYTES//1024//1024} MB.')
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
        mapping=await map_columns_two_layer(list(df.columns), raw_records, config.AI_PROVIDER)
        mapping_config=[]
        for m in mapping:
            mapping_config.append({'Tên cột gốc':m['source_column'],'AI hiểu là':m['canonical_field'] if m.get('canonical_field') not in ('unmapped','unknown_column') else 'unmapped'})
        from data_preprocessor import run_advanced_etl
        safe_records,audit=await run_advanced_etl(raw_records,mapping_config,filename)
        if not safe_records:
            raise ValueError('Không tạo được dữ liệu chuẩn hóa từ file.')
        upload_id=save_uploaded_dataset(filename,safe_records,list(safe_records[0].keys()),'legacy_web_upload',user_id=u['id'])
        save_canonical_customers(upload_id,safe_records)
        save_learning_audit(upload_id,filename,audit,mapping,audit.get('missing_required_fields',[]),user_id=u['id'])
        intelligence=build_customer_intelligence(safe_records); save_customer_intelligence_features(intelligence,upload_id)
        seg=hybrid_segment_customers(intelligence,n_clusters=None,random_state=config.RANDOM_STATE) if len(intelligence)>=2 else {'data':intelligence,'labels':[],'profiles':{},'n_clusters':0,'silhouette':None}
        labeled=seg.get('data',intelligence); profiles=seg.get('profiles',{})
        if not labeled.empty and 'segment_id' in labeled.columns: save_customer_segments(labeled,profiles,upload_id,seg.get('silhouette'))
        personas=[]
        if personas: save_customer_personas(personas,upload_id)
        latest_state[u['id']]={'upload_id':upload_id,'df':labeled,'personas':personas,'profiles':profiles,'twins':[],'mapping':mapping,'audit':audit,'audit_id':get_learning_audit_by_upload(upload_id).get('id') if get_learning_audit_by_upload(upload_id) else None,'learning_confirmed':True}
        return json_safe({'ok':True,'summary':{'rows':len(safe_records),'columns':list(df.columns),'audit':audit,'mapping':mapping,'segmentation':{'n_clusters':seg.get('n_clusters',0),'silhouette':seg.get('silhouette')},'upload_id':upload_id}})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f'Không thể tải/xử lý file: {type(e).__name__}: {e}')

@app.post('/api/customers/inspect')
async def staged_inspect(req:Request,file:UploadFile=File(...)):
    """Bước 1: chỉ đọc/kiểm tra file. Không gọi AI và không lưu vào dữ liệu mô phỏng."""
    u=current_user(req); raw=await file.read()
    if len(raw)>config.MAX_UPLOAD_BYTES: raise HTTPException(413,'File vượt quá giới hạn.')
    from .data_pipeline_compat import read_dataframe
    try:
        df=read_dataframe(raw,file.filename or '')
        if df.empty: raise ValueError('File không có dữ liệu.')
        sid=str(uuid.uuid4())
        inspection=inspect_dataframe(df,file.filename or 'dataset',_rule_based_match)
        staged_sessions[sid]={'user_id':u['id'],'filename':file.filename or 'dataset','df':df,'inspection':inspection,'mapping':None,'inspection_confirmed':False,'learning_confirmed':False,'upload_id':None,'audit_id':None,'learned_records':None,'audit':None}
        return json_safe({'ok':True,'session_id':sid,'inspection':inspection,'message':'Đã đọc dữ liệu. Chưa gọi AI và chưa đưa dữ liệu vào pipeline mô phỏng.'})
    except Exception as e:
        raise HTTPException(400,'Không thể đọc dữ liệu: '+str(e))

@app.post('/api/customers/inspect/{session_id}/confirm')
async def staged_confirm_inspection(req:Request,session_id:str):
    """Bước 2: người dùng xác nhận preview, sau đó mới cho phép AI mapping."""
    u=current_user(req); st=staged_sessions.get(session_id)
    if not st or st.get('user_id')!=u['id']: raise HTTPException(404,'Không tìm thấy phiên dữ liệu.')
    if st.get('inspection_confirmed'):
        return json_safe({'ok':True,'session_id':session_id,'mapping':st.get('mapping') or [],'already_confirmed':True})
    df=st['df']; records=df.head(100).where(pd.notna(df.head(100)),None).to_dict('records')
    try:
        mapping=await map_columns_two_layer(list(df.columns),records,config.AI_PROVIDER)
        missing=missing_required_fields(mapping)
        st['mapping']=mapping; st['inspection_confirmed']=True; st['missing_required']=missing
        return json_safe({'ok':True,'session_id':session_id,'mapping':mapping,'missing_required_fields':missing,'message':'Đã xác nhận dữ liệu. AI mapping đã được chạy cho các cột chưa nhận diện.'})
    except Exception as e:
        raise HTTPException(400,'Không thể mapping dữ liệu: '+str(e))

@app.get('/api/customers/inspect/{session_id}')
def staged_inspection_status(req:Request,session_id:str):
    u=current_user(req); st=staged_sessions.get(session_id)
    if not st or st.get('user_id')!=u['id']: raise HTTPException(404,'Không tìm thấy phiên dữ liệu.')
    return json_safe({'session_id':session_id,'inspection':st['inspection'],'mapping':st.get('mapping'),'inspection_confirmed':st.get('inspection_confirmed',False),'learning_confirmed':st.get('learning_confirmed',False),'audit':st.get('audit'),'dataset_id':st.get('upload_id'),'audit_id':st.get('audit_id')})

@app.post('/api/customers/learning/start/{session_id}')
async def staged_learning_start(req:Request,session_id:str):
    """Bước 3: AI học từ dữ liệu real sau khi preview đã được xác nhận."""
    u=current_user(req); st=staged_sessions.get(session_id)
    if not st or st.get('user_id')!=u['id']: raise HTTPException(404,'Không tìm thấy phiên dữ liệu.')
    if not st.get('inspection_confirmed') or not st.get('mapping'):
        raise HTTPException(400,'Hãy xác nhận bước đọc dữ liệu trước khi AI học.')
    jid=str(uuid.uuid4())
    staged_learning_jobs[jid]={'status':'running','progress':0,'step':'Chuẩn bị dữ liệu','session_id':session_id,'error':None,'audit':None}
    async def worker():
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
            staged_learning_jobs[jid].update(progress=10,step='Phân tích dữ liệu real và dữ liệu đã xác nhận trước đó')
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
                    learning[field]=await _learn_field(field,learning_source_df,config.AI_PROVIDER)
                except Exception as e:
                    learning[field]={'field':field,'learned':False,'confidence':0,'strategy':'not_enough_evidence','evidence':f'AI không thể học trường này: {e}','candidate_values':[],'notes':''}
            staged_learning_jobs[jid].update(progress=70,step='Bổ sung các trường còn thiếu')
            learned_df,provenance,filled=apply_learned_fields(canonical_df,learning)
            audit=build_audit(canonical_df,learned_df,provenance,learning)
            audit['filled_counts']=filled
            audit['learning_provider']=config.AI_PROVIDER
            audit['learned_summary']=[x for x in audit.get('learned_fields',[]) if x.get('learned')]
            staged_learning_jobs[jid].update(progress=80,step='Lưu audit dữ liệu')
            safe_records=json_safe(learned_df.where(pd.notna(learned_df),None).to_dict('records'))
            upload_id=save_uploaded_dataset(st['filename'],safe_records,list(learned_df.columns),'staged_web_upload',user_id=u['id'])
            save_canonical_customers(upload_id,safe_records)
            audit_id=save_learning_audit(upload_id,st['filename'],audit,mapping,audit.get('remaining_missing_fields',[]),user_id=u['id'])
            # Downstream logic is the SAME existing MarketSim pipeline.
            intelligence=build_customer_intelligence(safe_records); save_customer_intelligence_features(intelligence,upload_id)
            seg=hybrid_segment_customers(intelligence,n_clusters=None,random_state=config.RANDOM_STATE)
            labeled=seg.get('labeled_df',intelligence); profiles=seg.get('profiles',{})
            if not labeled.empty and 'segment_id' in labeled.columns: save_customer_segments(labeled,profiles,upload_id,seg.get('silhouette'))
            personas=build_data_driven_personas(labeled,profiles) if not labeled.empty else []
            if personas: save_customer_personas(personas,upload_id)
            st.update({'upload_id':upload_id,'audit_id':audit_id,'learned_records':safe_records,'audit':audit,'learning':learning,'df':labeled,'personas':personas,'profiles':profiles,'twins':[]})
            # This staged path deliberately requires explicit audit confirmation.
            latest_state[u['id']]={'upload_id':upload_id,'df':labeled,'personas':personas,'profiles':profiles,'twins':[],'mapping':mapping,'audit':audit,'audit_id':audit_id,'learning_confirmed':False,'staged_session_id':session_id}
            staged_learning_jobs[jid].update(status='completed',progress=100,step='Hoàn thành — chờ người dùng xác nhận audit',audit=audit,audit_id=audit_id,dataset_id=upload_id,filled_counts=filled)
        except Exception as e:
            staged_learning_jobs[jid].update(status='failed',error=str(e))
    asyncio.create_task(worker())
    return {'ok':True,'job_id':jid}

@app.get('/api/customers/learning/status/{job_id}')
def staged_learning_status(req:Request,job_id:str):
    current_user(req); j=staged_learning_jobs.get(job_id)
    if not j: raise HTTPException(404,'Không tìm thấy tiến trình AI Learning.')
    return json_safe(j)

@app.post('/api/customers/learning/confirm/{session_id}')
def staged_learning_confirm(req:Request,session_id:str):
    u=current_user(req)
    st=staged_sessions.get(session_id)
    state=latest_state.get(u['id'],{})
    if not st or st.get('user_id')!=u['id']:
        if state.get('staged_session_id')==session_id and state.get('audit_id'):
            st={'user_id':u['id'],'audit_id':state.get('audit_id'),'upload_id':state.get('upload_id'),'df':state.get('df'),'personas':state.get('personas',[]),'profiles':state.get('profiles',{}),'audit':state.get('audit')}
        else:
            raise HTTPException(404,'Không tìm thấy phiên dữ liệu. Hãy mở lại dữ liệu khách hàng và kiểm tra trạng thái AI Learning.')
    if not st.get('audit_id') or not st.get('audit'): raise HTTPException(400,'AI Learning chưa hoàn thành.')
    confirm_learning_audit(st['audit_id'], user_id=u['id'])
    state.update({'learning_confirmed':True,'audit_id':st['audit_id'],'upload_id':st.get('upload_id'),'df':st.get('df'),'personas':st.get('personas',[]),'profiles':st.get('profiles',{}),'twins':[],'staged_session_id':session_id,'audit':st.get('audit')})
    latest_state[u['id']]=state
    if session_id in staged_sessions: staged_sessions[session_id]['learning_confirmed']=True
    return {'ok':True,'confirmed':True,'session_id':session_id,'message':'Đã xác nhận chất lượng dữ liệu. Các bước Digital Twin và mô phỏng đã được mở.'}

@app.post('/api/customers/learning/confirm-latest')
def staged_learning_confirm_latest(req:Request):
    u=current_user(req); state=latest_state.get(u['id'],{})
    if not state.get('audit_id') or not state.get('audit'):
        raise HTTPException(400,'AI Learning chưa hoàn thành.')
    confirm_learning_audit(state['audit_id'], user_id=u['id'])
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

@app.post('/api/trends/collect')
async def collect_trends(req:Request):
    current_user(req)
    try:
        from data_collector import fetch_google_trends
        trends=fetch_google_trends()
        rows=[] if trends is None or trends.empty else trends.to_dict('records')
        return json_safe({'ok':True,'items':rows,'count':len(rows),'source':'Google Trends','message':('Đã lấy dữ liệu Google Trends.' if rows else 'Google Trends không trả dữ liệu. Có thể bị giới hạn truy cập hoặc từ khóa chưa có dữ liệu.')})
    except Exception as e:
        return {'ok':False,'items':[],'count':0,'source':'Google Trends','error':str(e)}

@app.get('/api/trends')
async def get_trends(req:Request):
    return await collect_trends(req)

@app.get('/api/analysis')
def analysis(req:Request):
    u=current_user(req); st=latest_state.get(u['id'])
    if st and st.get('df') is not None:
        df=st['df']; intel=summarize_customer_intelligence(df); profiles=st.get('profiles',{}) or {}
        return json_safe({'ok':True,'intelligence':intel,'segmentation':{'profiles':profiles,'count':len(df),'n_clusters':len(profiles)},'audit':st.get('audit',{}),'learning_confirmed':bool(st.get('learning_confirmed'))})
    rows=load_canonical_customers(limit=5000, user_id=u['id']); df=build_customer_intelligence(rows) if rows else pd.DataFrame()
    intel=summarize_customer_intelligence(df) if not df.empty else summarize_customer_intelligence(pd.DataFrame())
    return json_safe({'ok':True,'intelligence':intel,'segmentation':{'profiles':{},'count':len(df),'n_clusters':0},'audit':{},'learning_confirmed':False})

@app.get('/api/segments')
def segments(req:Request):current_user(req); return json_safe({'items':get_customer_segments(limit=1000)})
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
    u=current_user(req); st=latest_state.get(u['id'])
    if not st: raise HTTPException(400,'Hãy tải dữ liệu khách hàng trước.')
    if st.get('audit_id') and not st.get('learning_confirmed'):
        raise HTTPException(400,'Bạn cần xem và xác nhận báo cáo AI Learning trước khi tạo khách hàng ảo.')
    labeled=st['df']; segment_ids=sorted(labeled['segment_id'].dropna().astype(int).unique().tolist()) if 'segment_id' in labeled.columns else [0]
    total=len(segment_ids)*b.count_per_segment; jid=str(uuid.uuid4())
    persona_jobs[jid]={'status':'running','progress':0,'created':0,'total':total,'error':None,'twins':[]}
    async def worker():
        try:
            all_twins=[]
            for idx,sid in enumerate(segment_ids):
                part=generate_synthetic_twins(labeled,segment_id=sid,twins_per_segment=b.count_per_segment)
                all_twins.extend(part.get('twins',[])); persona_jobs[jid]['created']=len(all_twins); persona_jobs[jid]['progress']=round(len(all_twins)/max(total,1)*100,1)
                await asyncio.sleep(0)
            st['twins']=all_twins; save_synthetic_customer_twins(all_twins,st['upload_id'])
            persona_jobs[jid].update(status='completed',progress=100,created=len(all_twins),twins=all_twins)
        except Exception as e: persona_jobs[jid].update(status='failed',error=str(e))
    asyncio.create_task(worker()); return {'ok':True,'job_id':jid,'total':total}
@app.get('/api/personas/generate/{job_id}')
def generate_personas_status(req:Request,job_id:str):
    current_user(req); j=persona_jobs.get(job_id)
    if not j: raise HTTPException(404,'Không tìm thấy tiến trình tạo khách hàng ảo.')
    d={k:v for k,v in j.items() if k!='twins'}
    if j['status']=='completed': d['count']=len(j['twins'])
    return json_safe(d)
@app.post('/api/personas/generate')
def generate_personas(req:Request,b:TwinBody):
    # Backward-compatible synchronous endpoint.
    u=current_user(req); st=latest_state.get(u['id'])
    if not st: raise HTTPException(400,'Hãy tải dữ liệu khách hàng trước.')
    if st.get('audit_id') and not st.get('learning_confirmed'):
        raise HTTPException(400,'Bạn cần xác nhận báo cáo AI Learning trước khi tạo khách hàng ảo.')
    result=generate_synthetic_twins(st['df'],twins_per_segment=b.count_per_segment); twins=result.get('twins',[]); st['twins']=twins; save_synthetic_customer_twins(twins,st['upload_id'])
    return json_safe({'ok':True,'count':len(twins),'twins':twins,'note':result.get('note')})
@app.get('/api/personas')
def personas(req:Request,limit:int=5000):
    u=current_user(req); st=latest_state.get(u['id'])
    if st and st.get('twins'): return json_safe({'items':st['twins'][:max(1,min(limit,5000))]})
    return json_safe({'items':get_synthetic_customer_twins(limit=max(1,min(limit,5000)))})

@app.post('/api/simulations/start')
async def start(req:Request,b:Sim):
    u=current_user(req); st=latest_state.get(u['id'])
    if not st: raise HTTPException(400,'Hãy tải dữ liệu và tạo khách hàng ảo trước.')
    if st.get('audit_id') and not st.get('learning_confirmed'):
        raise HTTPException(400,'Bạn cần xác nhận báo cáo AI Learning trước khi mô phỏng.')
    twins=st.get('twins') or generate_synthetic_twins(st['df'],twins_per_segment=max(1,b.count//max(1,st.get('seg_count',1) or 1))).get('twins',[])
    if not twins: raise HTTPException(400,'Không có khách hàng ảo để mô phỏng.')
    twins=twins[:b.count]; provider=(b.provider or config.AI_PROVIDER).lower(); jid=str(uuid.uuid4())
    jobs[jid]={
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
    }
    async def worker():
        try:
            # quantitative twin model first
            tdf=twins_to_dataframe(twins); model=simulate_twins(tdf,b.campaign)
            # LLM comments run concurrently with semaphore; use provider after real data is transformed to twins
            sem=asyncio.Semaphore(config.MAX_CONCURRENT_AI); done=0; lock=asyncio.Lock(); results=[None]*len(twins)
            async def one(i,t):
                nonlocal done
                async with sem:
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
                        'Trả đúng MỘT JSON, không markdown, schema: '
                        '{"score":1,"sentiment":"positive|neutral|negative","comment":"phản ứng của khách hàng","reason":"lý do dựa trên hồ sơ"}.\n'
                        'Chiến dịch: '+str(b.campaign)+'\n'
                        'Hồ sơ khách hàng tổng hợp: '+json.dumps(ai_twin,ensure_ascii=False,separators=(',',':'))
                    )
                    try:
                        raw=await _simulation_ai_call(prompt,provider); a,c=raw.find('{'),raw.rfind('}'); rr=json.loads(raw[a:c+1])
                        reaction={'score':max(1,min(10,int(rr.get('score',5)))),'sentiment':str(rr.get('sentiment','neutral')),'comment':str(rr.get('comment','')),'reason':str(rr.get('reason',''))}
                        ai_ok=True
                        ai_error=None
                    except Exception as e:
                        # Keep the original fallback behavior exactly as-is.
                        # We only expose the real AI/provider/JSON error for diagnosis.
                        ai_ok=False
                        ai_error=f'{type(e).__name__}: {e}'
                        twin_id=t.get('twin_id') or t.get('id') or f'index-{i}'
                        print(f'[SIMULATION AI ERROR] job={jid} provider={provider} twin={twin_id} error={ai_error}', flush=True)
                        base=model['results'].iloc[i] if i < len(model.get('results',[])) else {}
                        reaction={'score':int(base.get('score',5)),'sentiment':base.get('sentiment','neutral'),'comment':'Phản ứng được ước lượng từ mô hình định lượng của digital twin.','reason':'Fallback khi AI không phản hồi.'}
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
            analysis={'summary':f'Mô phỏng {len(results)} khách hàng ảo bằng mô hình digital twin và phản hồi AI.','strengths':[],'weaknesses':[],'star_rating':3}
            sid=save_simulation(b.name or b.campaign, [{'persona_name':x['persona'].get('twin_id'), 'score':x['reaction']['score'], 'sentiment':x['reaction']['sentiment'], 'reasoning':x['reaction']['comment']} for x in results], analysis, user_id=u['id'])
            jobs[jid].update(status='completed',progress=100,results=json_safe(results),scenario_id=sid)
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
    current_user(req); j=jobs.get(job_id)
    if not j: raise HTTPException(404,'Không tìm thấy tiến trình.')
    d={k:v for k,v in j.items() if k!='results'}
    if j['status']=='completed': d['results_count']=len(j['results']); d['results_preview']=j['results'][:100]
    return json_safe(d)
@app.get('/api/simulations/{sid}/results')
def sim_results(req:Request,sid:int):
    u=current_user(req)
    if get_scenario_by_id(sid,u['id']) is None:
        raise HTTPException(404,'Không tìm thấy chiến dịch.')
    return json_safe({'items':get_results_by_scenario(sid,u['id']).to_dict('records')})
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
    u=current_user(req); st=latest_state.get(u['id']); twins=st.get('twins') if st else []
    if not twins:raise HTTPException(400,'Hãy tạo digital twin trước.')
    r=paired_compare(twins_to_dataframe(twins),b.campaigns); table=r.get('table',pd.DataFrame()); rows=table.to_dict('records') if not table.empty else []
    return json_safe({'status':r['status'],'results':rows})
@app.post('/api/advanced/optimize')
def advanced_opt(req:Request,b:OptBody):
    u=current_user(req); st=latest_state.get(u['id']); twins=st.get('twins') if st else []
    if not twins:raise HTTPException(400,'Hãy tạo digital twin trước.')
    r=optimize_marketing(twins_to_dataframe(twins),b.budget,b.discount_options,b.channel_options); rows=r.get('candidates',pd.DataFrame()); return json_safe({'status':r['status'],'best':r.get('best'),'candidates':rows.head(100).to_dict('records') if not rows.empty else []})
@app.get('/api/advanced/experiments')
def advanced_experiments(req:Request):current_user(req);return json_safe({'items':get_advanced_experiments(100)})

@app.post('/api/feedback')
def feedback(req:Request,b:FeedbackBody):
    current_user(req)
    from marketing_learning import record_outcome
    metrics,cal=record_outcome(config.DB_PATH,b.experiment_id,b.predicted_conversion,b.actual_conversion,b.predicted_revenue,b.actual_revenue,b.notes)
    return {'ok':True,'metrics':metrics,'calibration':cal}
@app.get('/api/feedback')
def feedback_list(req:Request):
    current_user(req); from marketing_learning import feedback_history,latest_calibration
    return json_safe({'items':feedback_history(config.DB_PATH,100).to_dict('records'),'calibration':latest_calibration(config.DB_PATH)})

@app.post('/api/chat')
async def assistant(req:Request,b:Chat):
    current_user(req)
    context='Bạn là trợ lý MarketSim AI. Giải thích bằng tiếng Việt dễ hiểu. Dữ liệu khách hàng thật chỉ được xử lý cục bộ; chỉ thảo luận dữ liệu tổng hợp sau lọc. Không khẳng định dự đoán là sự thật.'
    try:return {'ok':True,'provider':b.provider or config.AI_PROVIDER,'answer':await chat([{'role':'system','content':context},{'role':'user','content':b.message}],b.provider or config.AI_PROVIDER)}
    except Exception as e:raise HTTPException(502,str(e))
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
