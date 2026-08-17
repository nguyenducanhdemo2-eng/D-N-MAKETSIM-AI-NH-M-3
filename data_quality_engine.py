"""Enterprise data-quality layer for MarketSim AI.

Additive only: this module validates/profiles customer data before the existing
AI Learning -> Segmentation -> Digital Twin pipeline. It never invents values.
"""
from __future__ import annotations
import re, math, warnings
from datetime import datetime, timezone
from difflib import SequenceMatcher
import numpy as np
import pandas as pd

NULL_STRINGS={"","nan","none","null","n/a","na","unknown","không rõ","khong ro"}

# These fields are the minimum evidence needed for a defensible customer
# persona.  A weighted average alone can hide severe gaps in one of them, so
# they are also used as explicit quality gates below.
REQUIRED_TWIN_FIELDS=('age','job','pain_point','personality','interest_keywords')

# Provenance is part of readiness: an AI-filled value is useful for exploration
# but cannot be treated as equally reliable as a value supplied by the user.
PROVENANCE_WEIGHTS={
    'REAL':1.0,
    'ORIGINAL':1.0,
    'DERIVED_REAL':.95,
    'AI_INFERRED':.55,
    'LEGACY_UNKNOWN':.50,
    'MISSING_SOURCE':0.0,
    'MISSING_INVALID':0.0,
    'NOT_APPLICABLE':None,
}

def _blank(s: pd.Series) -> pd.Series:
    return s.isna() | s.astype(str).str.strip().str.lower().isin(NULL_STRINGS)

def _semantic_type(s: pd.Series) -> tuple[str,float]:
    non=s[~_blank(s)]
    if non.empty:return "empty",1.0
    num=pd.to_numeric(non,errors="coerce").notna().mean()
    # Pandas warns when arbitrary text is tested as a date.  Profiling is
    # intentionally permissive here; suppress only that parser warning.
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',UserWarning)
        dt=pd.to_datetime(non,errors="coerce").notna().mean()
    vals=non.astype(str).str.strip()
    if num>=.92:return "numeric",round(float(num),2)
    if dt>=.92:return "date",round(float(dt),2)
    uniq=vals.nunique()/max(1,len(vals))
    if uniq<.08 or vals.nunique()<=25:return "category",round(float(1-min(uniq,1)),2)
    return "text",.9

def _norm(v):
    return re.sub(r"\W+","",str(v or "").lower(),flags=re.UNICODE)

def _stats(s: pd.Series, sem_type: str):
    out={}
    non=s[~_blank(s)]
    if sem_type=="numeric":
        n=pd.to_numeric(non,errors="coerce").dropna()
        if not n.empty:
            q1,q3=n.quantile([.25,.75]); iqr=q3-q1
            out={"min":float(n.min()),"median":float(n.median()),"mean":float(n.mean()),"max":float(n.max()),
                 "q1":float(q1),"q3":float(q3),"outlier_count":int(((n<q1-1.5*iqr)|(n>q3+1.5*iqr)).sum())}
    elif sem_type=="date":
        d=pd.to_datetime(non,errors="coerce").dropna()
        if not d.empty: out={"min":str(d.min().date()),"max":str(d.max().date()),"invalid_date_count":int(len(non)-len(d))}
    else:
        vc=non.astype(str).str.strip().value_counts().head(8)
        out={"top_values":[{"value":str(k),"count":int(v)} for k,v in vc.items()]}
    return out

# Conservative business constraints. Invalid values are flagged, not silently corrected.
def validation_mask(field: str, s: pd.Series) -> pd.Series:
    bad=pd.Series(False,index=s.index)
    non=~_blank(s)
    if field=="age":
        n=pd.to_numeric(s,errors="coerce"); bad=non & (n.isna() | (n<10) | (n>110))
    elif field in {"total_spending","average_order_value","order_count","discount_usage","monthly_income","return_count","website_visits_30d"}:
        n=pd.to_numeric(s,errors="coerce"); bad=non & (n.isna() | (n<0))
        if field=="discount_usage": bad=bad | (non & (n>100))
    elif field in {"email_open_rate","cart_abandon_rate"}:
        n=pd.to_numeric(s,errors="coerce"); bad=non & (n.isna() | (n<0) | (n>100))
    elif field=="satisfaction_score":
        n=pd.to_numeric(s,errors="coerce"); bad=non & (n.isna() | (n<1) | (n>5))
    elif field in {"last_purchase_date","signup_date"}:
        d=pd.to_datetime(s,errors="coerce"); now=pd.Timestamp.now().normalize()+pd.Timedelta(days=2); bad=non & (d.isna() | (d>now))
    return bad.fillna(False)

def profile_dataframe(df: pd.DataFrame, filename: str, rule_mapper) -> dict:
    rows=len(df); columns=[]; mapping=[]; used=set(); total_missing=0; type_conf=[]; map_conf=[]; invalid_total=0
    required_coverage={field:0.0 for field in REQUIRED_TWIN_FIELDS}
    invalid_rows_mask=pd.Series(False,index=df.index)
    issues=[]
    for col in df.columns:
        s=df[col]; blank=_blank(s); total_missing+=int(blank.sum())
        sem,conf=_semantic_type(s); type_conf.append(conf)
        field,mconf,reason=rule_mapper(str(col)); mapped=field if field and field not in used else "unmapped"
        if mapped!="unmapped":
            used.add(mapped); map_conf.append(float(mconf))
            if mapped in required_coverage:
                required_coverage[mapped]=float((~blank).mean()*100) if rows else 0.0
        bad=validation_mask(mapped,s) if mapped!="unmapped" else pd.Series(False,index=s.index)
        invalid=int(bad.sum()); invalid_total+=invalid; invalid_rows_mask=invalid_rows_mask | bad
        c={"name":str(col),"dtype":str(s.dtype),"semantic_type":sem,"type_confidence":conf,
           "non_null":int((~blank).sum()),"null_count":int(blank.sum()),"null_pct":round(float(blank.mean()*100),1) if rows else 0,
           "unique_count":int(s[~blank].nunique(dropna=True)),"sample_values":[x.item() if hasattr(x,'item') else x for x in s[~blank].head(5).tolist()],
           "rule_mapping":mapped,"rule_confidence":round(float(mconf if mapped!='unmapped' else 0),2),"rule_reasoning":reason or "Chưa có alias chắc chắn.",
           "invalid_count":invalid,"profile":_stats(s,sem)}
        columns.append(c); mapping.append({"source_column":str(col),"canonical_field":mapped,"confidence":c["rule_confidence"],"confidence_display":f'{int(c["rule_confidence"]*100)}%',"reasoning":c["rule_reasoning"],"source":"rule" if mapped!='unmapped' else "pending_ai"})
        if c["null_pct"]>=30: issues.append({"severity":"warning","code":"HIGH_MISSING","column":str(col),"message":f'{c["null_pct"]}% dữ liệu trống'})
        if invalid: issues.append({"severity":"danger","code":"INVALID_VALUE","column":str(col),"message":f'{invalid} giá trị không hợp lệ theo quy tắc {mapped}'})
    exact=int(df.duplicated().sum())
    if exact: issues.append({"severity":"warning","code":"EXACT_DUPLICATE","column":"","message":f'{exact} dòng trùng hoàn toàn'})
    empty_rows=int(df.isna().all(axis=1).sum()) if rows else 0
    cells=max(1,rows*max(1,len(df.columns)))
    completeness=max(0,100-total_missing/cells*100)
    validity=max(0,100-invalid_total/max(1,cells-total_missing)*100)
    uniqueness=max(0,100-exact/max(1,rows)*100)
    schema=100*(sum(map_conf)/max(1,len(df.columns))) if map_conf else 0
    consistency=max(0,100-(sum(1-c for c in type_conf)/max(1,len(type_conf))*100))
    freshness=100.0
    # Freshness only penalizes if a recognizable purchase date exists and is old.
    date_cols=[c for c in columns if c['rule_mapping']=='last_purchase_date']
    if date_cols:
        col=date_cols[0]['name']; d=pd.to_datetime(df[col],errors='coerce').dropna()
        if not d.empty:
            days=max(0,(pd.Timestamp.now().normalize()-d.max().normalize()).days)
            freshness=max(20.0,100.0-min(days,730)/730*80)
    weights={"completeness":.27,"validity":.25,"consistency":.15,"uniqueness":.12,"freshness":.08,"schema_confidence":.13}
    dims={"completeness":round(completeness,1),"validity":round(validity,1),"consistency":round(consistency,1),"uniqueness":round(uniqueness,1),"freshness":round(freshness,1),"schema_confidence":round(schema,1)}
    base_score=round(sum(dims[k]*w for k,w in weights.items()),1)

    # Quality gates prevent a high average from concealing a critical defect.
    # The final score remains explainable because every cap is returned to the UI.
    score_cap=100.0; gates=[]
    missing_pct=total_missing/cells*100
    duplicate_pct=exact/max(1,rows)*100
    invalid_pct=invalid_total/max(1,cells-total_missing)*100
    invalid_rows=int(invalid_rows_mask.sum())
    invalid_row_pct=invalid_rows/max(1,rows)*100
    required_missing=[field for field,value in required_coverage.items() if value<=0]
    required_min=min(required_coverage.values()) if required_coverage else 0.0

    def add_gate(code: str, cap: float, message: str):
        nonlocal score_cap
        score_cap=min(score_cap,cap)
        gates.append({"code":code,"cap":cap,"message":message})

    if required_missing:
        add_gate('REQUIRED_FIELD_UNMAPPED',59.9,
                 'Thiếu ánh xạ trường bắt buộc: '+', '.join(required_missing))
        for field in required_missing:
            issues.append({"severity":"danger","code":"REQUIRED_FIELD_UNMAPPED","column":field,
                           "message":f'Chưa ánh xạ được trường bắt buộc {field}'})
    elif required_min<50:
        add_gate('CRITICAL_REQUIRED_COVERAGE',59.9,
                 f'Trường bắt buộc thấp nhất chỉ đạt {required_min:.1f}% dữ liệu')
    elif required_min<70:
        add_gate('LOW_REQUIRED_COVERAGE',74.9,
                 f'Trường bắt buộc thấp nhất chỉ đạt {required_min:.1f}% dữ liệu')
    elif required_min<90:
        add_gate('PARTIAL_REQUIRED_COVERAGE',89.9,
                 f'Trường bắt buộc thấp nhất chỉ đạt {required_min:.1f}% dữ liệu')

    for field,coverage in required_coverage.items():
        if 0<coverage<90:
            severity='danger' if coverage<50 else 'warning'
            issues.append({"severity":severity,"code":"LOW_REQUIRED_COVERAGE","column":field,
                           "message":f'Trường bắt buộc {field} mới có {coverage:.1f}% dữ liệu'})

    if missing_pct>=30:
        add_gate('CRITICAL_MISSING_RATE',59.9,f'Tỷ lệ ô trống toàn bộ dữ liệu là {missing_pct:.1f}%')
    elif missing_pct>=15:
        add_gate('HIGH_MISSING_RATE',74.9,f'Tỷ lệ ô trống toàn bộ dữ liệu là {missing_pct:.1f}%')

    if duplicate_pct>=10:
        add_gate('CRITICAL_DUPLICATE_RATE',74.9,f'Tỷ lệ dòng trùng là {duplicate_pct:.1f}%')
    elif duplicate_pct>=5:
        add_gate('HIGH_DUPLICATE_RATE',89.9,f'Tỷ lệ dòng trùng là {duplicate_pct:.1f}%')

    if invalid_row_pct>=10:
        add_gate('CRITICAL_INVALID_RATE',59.9,f'{invalid_row_pct:.1f}% dòng có giá trị không hợp lệ')
    elif invalid_row_pct>=5:
        add_gate('HIGH_INVALID_RATE',74.9,f'{invalid_row_pct:.1f}% dòng có giá trị không hợp lệ')
    elif invalid_row_pct>=2:
        add_gate('ELEVATED_INVALID_RATE',89.9,f'{invalid_row_pct:.1f}% dòng có giá trị không hợp lệ')

    score=round(min(base_score,score_cap),1)
    label="Rất tốt" if score>=90 else "Tốt" if score>=75 else "Cần kiểm tra" if score>=60 else "Không nên mô phỏng"
    required_found=[field for field,value in required_coverage.items() if value>0]
    return {"filename":filename,"rows":rows,"columns_count":len(df.columns),"duplicate_rows":exact,"empty_rows":empty_rows,
            "columns":columns,"sample_rows":[{str(k):(None if pd.isna(v) else (v.item() if hasattr(v,'item') else v)) for k,v in r.items()} for r in df.head(10).to_dict('records')],
            "rule_mapping":mapping,"required_fields":list(REQUIRED_TWIN_FIELDS),"required_found_by_rule":required_found,
            "required_missing_by_rule":required_missing,"required_coverage":{k:round(v,1) for k,v in required_coverage.items()},
            "quality":{"score":score,"base_score":base_score,"score_cap":score_cap,"label":label,"dimensions":dims,
                       "gates":gates,"issues":issues,"invalid_cells":invalid_total,"invalid_rows":invalid_rows,"missing_cells":total_missing,
                       "missing_pct":round(missing_pct,1),"duplicate_pct":round(duplicate_pct,1),"invalid_pct":round(invalid_pct,1),
                       "invalid_row_pct":round(invalid_row_pct,1)}}

def detect_possible_duplicates(df: pd.DataFrame, mapping: list[dict], limit=30) -> dict:
    rename={m['source_column']:m['canonical_field'] for m in mapping if m.get('canonical_field') not in (None,'unmapped','unknown_column') and m['source_column'] in df.columns}
    x=df.rename(columns=rename)
    exact=int(x.duplicated().sum())
    id_fields=[c for c in ['customer_id','email','phone'] if c in x.columns]
    pairs=[]
    # Strong key duplicates only; avoids quadratic fuzzy scan on large enterprise files.
    for field in id_fields:
        vals=x[field].map(_norm)
        groups={}
        for idx,v in vals.items():
            if not v: continue
            groups.setdefault(v,[]).append(int(idx))
        for ids in groups.values():
            if len(ids)>1:
                base=ids[0]
                for other in ids[1:]:
                    pairs.append({"row_a":base+1,"row_b":other+1,"confidence":1.0,"matched_on":[field]})
                    if len(pairs)>=limit:return {"exact":exact,"possible":len(pairs),"pairs":pairs}
    return {"exact":exact,"possible":len(pairs),"pairs":pairs}

def sanitize_canonical(df: pd.DataFrame):
    out=df.copy(); flags=pd.DataFrame('REAL',index=out.index,columns=out.columns)
    invalid_summary={}
    for field in list(out.columns):
        bad=validation_mask(field,out[field])
        n=int(bad.sum())
        if n:
            invalid_summary[field]=n; out.loc[bad,field]=np.nan; flags.loc[bad,field]='MISSING_INVALID'
        blank=_blank(out[field]); flags.loc[blank & ~bad,field]='MISSING_SOURCE'
    # NOT_APPLICABLE: no purchase history makes last purchase date legitimately absent.
    if 'last_purchase_date' in out.columns and 'order_count' in out.columns:
        orders=pd.to_numeric(out['order_count'],errors='coerce')
        na=(orders.fillna(0)<=0) & _blank(out['last_purchase_date'])
        flags.loc[na,'last_purchase_date']='NOT_APPLICABLE'
    return out,flags,invalid_summary

def derive_real_features(df: pd.DataFrame, provenance: pd.DataFrame):
    out=df.copy(); p=provenance.copy(); derived={}
    if {'total_spending','order_count'}.issubset(out.columns):
        total=pd.to_numeric(out['total_spending'],errors='coerce'); count=pd.to_numeric(out['order_count'],errors='coerce')
        if 'average_order_value' not in out.columns: out['average_order_value']=np.nan; p['average_order_value']='MISSING_SOURCE'
        miss=_blank(out['average_order_value']); valid=miss & total.notna() & count.notna() & (count>0)
        out.loc[valid,'average_order_value']=(total[valid]/count[valid]).round(2); p.loc[valid,'average_order_value']='DERIVED_REAL'; derived['average_order_value']=int(valid.sum())
    return out,p,derived

def digital_twin_readiness(df: pd.DataFrame, provenance: pd.DataFrame|None=None) -> dict:
    groups={
      'Nhân khẩu học':['age','gender','job','location'],
      'Hành vi mua':['total_spending','order_count','average_order_value','last_purchase_date'],
      'RFM':['last_purchase_date','order_count','total_spending'],
      'Sở thích':['interest_keywords','product_category','pain_point'],
      'Hành vi giá':['discount_usage','average_order_value','total_spending'],
      'Tương tác':['channel','device','acquisition_source','review_text','website_visits_30d','email_open_rate','cart_abandon_rate'],
    }
    rows=len(df)

    def field_score(field: str) -> tuple[float|None,float]:
        """Return (reliability-adjusted score, raw coverage) for one field.

        NOT_APPLICABLE cells are removed from the denominator.  This keeps a
        new customer with no purchase history from being marked as bad data.
        """
        if field not in df.columns or not rows:
            return 0.0,0.0
        blank=_blank(df[field])
        applicable=pd.Series(True,index=df.index)
        if field in {'last_purchase_date','average_order_value'} and 'order_count' in df.columns:
            orders=pd.to_numeric(df['order_count'],errors='coerce')
            applicable=~((orders.fillna(0)<=0) & blank)
        if provenance is not None and field in provenance.columns:
            src=provenance[field].astype(str).str.strip().str.upper()
            applicable=applicable & ~src.eq('NOT_APPLICABLE')
        denominator=int(applicable.sum())
        if denominator==0:
            return None,100.0
        present=applicable & ~blank
        raw=float(present.sum()/denominator*100)
        if provenance is None or field not in provenance.columns:
            return raw,raw
        src=provenance[field].astype(str).str.strip().str.upper()
        weights=src.map(lambda value: PROVENANCE_WEIGHTS.get(value,.50)).fillna(0.0)
        adjusted=float((weights.where(present,0.0)[applicable].sum()/denominator)*100)
        return adjusted,raw

    all_fields={field for fields in groups.values() for field in fields} | set(REQUIRED_TWIN_FIELDS)
    field_scores={}; raw_coverage={}
    for field in sorted(all_fields):
        adjusted,raw=field_score(field)
        field_scores[field]=None if adjusted is None else round(adjusted,1)
        raw_coverage[field]=round(raw,1)

    scores={}
    for name,fields in groups.items():
        vals=[field_scores[field] for field in fields if field_scores.get(field) is not None]
        scores[name]=round(sum(vals)/len(vals),1) if vals else 100.0
    overall=round(sum(scores.values())/len(scores),1) if scores else 0

    required_values=[field_scores.get(field) or 0.0 for field in REQUIRED_TWIN_FIELDS]
    required_average=round(sum(required_values)/len(required_values),1)
    required_min=round(min(required_values),1)
    gate_reasons=[]
    if required_min<50:
        gate_reasons.append(f'Trường bắt buộc thấp nhất chỉ đạt {required_min:.1f}%')
    if required_average<65:
        gate_reasons.append(f'Trung bình trường bắt buộc chỉ đạt {required_average:.1f}%')
    if overall<55 or required_min<50 or required_average<65:
        status='NOT_READY'
    elif overall<75 or required_min<75 or required_average<85:
        status='CAUTION'
        if required_min<75:
            gate_reasons.append(f'Trường bắt buộc thấp nhất chưa đạt 75% ({required_min:.1f}%)')
        if required_average<85:
            gate_reasons.append(f'Trung bình trường bắt buộc chưa đạt 85% ({required_average:.1f}%)')
    else:
        status='READY'
    message={'READY':'Sẵn sàng tạo Digital Twin.',
             'CAUTION':'Có thể mô phỏng nhưng nên kiểm tra các vùng dữ liệu yếu.',
             'NOT_READY':'Chưa khuyến nghị tạo Digital Twin trước khi cải thiện dữ liệu.'}[status]
    return {'overall':overall,'status':status,'areas':scores,'field_scores':field_scores,
            'raw_coverage':raw_coverage,'required_average':required_average,'required_min':required_min,
            'gate_reasons':gate_reasons,'message':message}

def data_drift(current: pd.DataFrame, historical: pd.DataFrame) -> dict:
    if historical is None or historical.empty:return {'available':False,'alerts':[]}
    alerts=[]
    common=[c for c in current.columns if c in historical.columns]
    for c in common:
        a=current[c]; b=historical[c]
        an=pd.to_numeric(a,errors='coerce'); bn=pd.to_numeric(b,errors='coerce')
        if an.notna().mean()>.8 and bn.notna().mean()>.8 and an.notna().sum() and bn.notna().sum():
            ma,mb=float(an.median()),float(bn.median()); denom=max(abs(mb),1e-9); change=(ma-mb)/denom*100
            if abs(change)>=35: alerts.append({'field':c,'type':'median_shift','current':round(ma,2),'historical':round(mb,2),'change_pct':round(change,1)})
        else:
            av=a.dropna().astype(str).value_counts(normalize=True); bv=b.dropna().astype(str).value_counts(normalize=True)
            if len(av) and len(bv):
                top=av.index[0]; pa=float(av.iloc[0]); pb=float(bv.get(top,0))
                if abs(pa-pb)>=.25: alerts.append({'field':c,'type':'distribution_shift','value':str(top),'current_pct':round(pa*100,1),'historical_pct':round(pb*100,1)})
        if len(alerts)>=12:break
    return {'available':True,'alerts':alerts,'alert_count':len(alerts)}
