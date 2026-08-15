"""Additive staged data onboarding for MarketSim AI.
This module does not replace the existing ETL/simulation logic. It adds a
human-confirmed workflow: inspect -> confirm -> mapping -> AI learning/audit.
"""
from __future__ import annotations

import asyncio, json, math, random, re, time
from collections import Counter
from typing import Any
import numpy as np
import pandas as pd
from schema_mapper import CANONICAL_SCHEMA, REQUIRED_FIELDS
from backend.ai_bridge import call_text
from data_quality_engine import profile_dataframe, sanitize_canonical, derive_real_features, digital_twin_readiness


# Additive transport guard for AI Learning. This does not change how fields are
# selected, how provenance is marked, or how learned values are applied. It only
# spaces Groq requests, trims prompt context and retries provider rate limits.
_LEARNING_GROQ_LOCK = asyncio.Lock()
_LEARNING_GROQ_COOLDOWN_UNTIL = 0.0
_LEARNING_GROQ_LAST_CALL = 0.0
_LEARNING_GROQ_MIN_INTERVAL_SEC = 12.0
_LEARNING_GROQ_MAX_RETRIES = 3
_LEARNING_GROQ_MAX_WAIT_SEC = 180.0
_LEARNING_GROQ_MAX_COMPLETION_TOKENS = 180

def _learning_retry_seconds(error_text: str) -> float | None:
    text = str(error_text or "")
    m = re.search(r'(?:try\s+again\s+in|retry(?:[- ]after)?[=: ]+)\s*(?:(\d+(?:\.\d+)?)m)?\s*(?:(\d+(?:\.\d+)?)s)?', text, re.I)
    if m and (m.group(1) or m.group(2)):
        return float(m.group(1) or 0) * 60.0 + float(m.group(2) or 0)
    m = re.search(r'retry[- ]after[=: ]+(\d+(?:\.\d+)?)', text, re.I)
    return float(m.group(1)) if m else None

def _compact_learning_context(field: str, df: pd.DataFrame) -> dict:
    """Small evidence-only context for one target field.

    The original learning rules remain unchanged: the LLM still receives only
    observed dataset evidence and must return learned=false when evidence is weak.
    """
    preferred = [field, 'age', 'gender', 'job', 'location', 'total_spending',
                 'pain_point', 'personality', 'interest_keywords', 'last_purchase_date']
    fields=[]
    for f in preferred:
        if f in df.columns and f in CANONICAL_SCHEMA and f not in fields:
            fields.append(f)
    ctx={"rows": int(len(df)), "target_field": field, "stats": {}}
    for f in fields[:7]:
        series=df[f]
        meta={"null_pct": round(float(series.isna().mean()*100),1) if len(df) else 0.0}
        typ=CANONICAL_SCHEMA.get(f,{}).get('type')
        if typ=='numeric':
            n=pd.to_numeric(series,errors='coerce').dropna()
            if not n.empty:
                meta.update({"min":float(n.min()),"median":float(n.median()),"max":float(n.max()),"mean":round(float(n.mean()),3)})
        else:
            meta['top_values']=_top_values(series,5)
            meta['samples']=series.dropna().astype(str).head(4).tolist()
        ctx['stats'][f]=meta
    return ctx

async def _learning_ai_call(prompt: str, provider: str):
    global _LEARNING_GROQ_COOLDOWN_UNTIL, _LEARNING_GROQ_LAST_CALL
    if provider != 'groq':
        return await call_text(prompt, provider, 0.15, True, max_completion_tokens=_LEARNING_GROQ_MAX_COMPLETION_TOKENS)
    async with _LEARNING_GROQ_LOCK:
        for attempt in range(_LEARNING_GROQ_MAX_RETRIES + 1):
            now=time.monotonic()
            cooldown=max(0.0, _LEARNING_GROQ_COOLDOWN_UNTIL-now)
            spacing=max(0.0, _LEARNING_GROQ_MIN_INTERVAL_SEC-(now-_LEARNING_GROQ_LAST_CALL))
            wait=max(cooldown, spacing)
            if wait>0:
                await asyncio.sleep(min(wait,_LEARNING_GROQ_MAX_WAIT_SEC))
            try:
                result=await call_text(prompt, provider, 0.15, True, max_completion_tokens=_LEARNING_GROQ_MAX_COMPLETION_TOKENS)
                _LEARNING_GROQ_LAST_CALL=time.monotonic()
                return result
            except Exception as e:
                msg=f"{type(e).__name__}: {e}"
                is_429=('HTTP 429' in msg or 'rate_limit_exceeded' in msg.lower() or 'too many requests' in msg.lower())
                if not is_429 or attempt>=_LEARNING_GROQ_MAX_RETRIES:
                    raise
                retry=_learning_retry_seconds(msg)
                wait=min(_LEARNING_GROQ_MAX_WAIT_SEC, max(3.0, (retry if retry is not None else 5.0*(attempt+1))) + 1.0)
                _LEARNING_GROQ_COOLDOWN_UNTIL=max(_LEARNING_GROQ_COOLDOWN_UNTIL,time.monotonic()+wait)
                print(f'[AI LEARNING RATE LIMIT] waiting={wait:.1f}s attempt={attempt+1}/{_LEARNING_GROQ_MAX_RETRIES}', flush=True)
        raise RuntimeError('AI Learning retry loop ended unexpectedly.')


def _safe(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    if hasattr(v, "item"):
        try: return v.item()
        except Exception: pass
    if isinstance(v, (np.integer, np.floating)):
        return float(v) if isinstance(v, np.floating) else int(v)
    return v


def inspect_dataframe(df: pd.DataFrame, filename: str, rule_mapper) -> dict:
    """Enterprise inspection: pure Python profiling/validation. No AI call."""
    return profile_dataframe(df, filename, rule_mapper)


def _top_values(series, n=8):
    vals = series.dropna().astype(str).str.strip()
    vals = vals[vals != ""]
    return [{"value": str(k), "count": int(v)} for k, v in vals.value_counts().head(n).items()]


def _normalize_candidate_values(values) -> list:
    """Return scalar candidate values that are safe to put in a dataframe.

    Groq can mirror the evidence shape used in the prompt and return candidates
    such as {"value": "Than trong", "count": 103}.  The old implementation
    copied that whole dictionary into a canonical text column, which later made
    SQLite fail with "type 'dict' is not supported".  Keep only the observed
    value and reject nested containers.
    """
    if values is None:
        return []
    if not isinstance(values, (list, tuple, set)):
        values = [values]
    normalized = []
    for item in values:
        if isinstance(item, dict):
            item = item.get("value")
        if item is None or isinstance(item, (dict, list, tuple, set)):
            continue
        item = _safe(item)
        if item is None:
            continue
        if isinstance(item, str):
            item = item.strip()
            if not item:
                continue
        if item not in normalized:
            normalized.append(item)
    return normalized


def _dataset_context(df: pd.DataFrame, mapped_fields: list[str]) -> dict:
    context = {"rows": len(df), "fields": mapped_fields, "stats": {}}
    for field in mapped_fields:
        if field not in df.columns: continue
        s = df[field]
        meta = {"null_pct": round(float(s.isna().mean()*100), 1)}
        if CANONICAL_SCHEMA.get(field, {}).get("type") == "numeric":
            n = pd.to_numeric(s, errors="coerce").dropna()
            if not n.empty:
                meta.update({"min": float(n.min()), "median": float(n.median()), "max": float(n.max()), "mean": float(n.mean())})
        else:
            meta["top_values"] = _top_values(s)
        if CANONICAL_SCHEMA.get(field, {}).get("type") in ("string", "category", "date"):
            samples = s.dropna().astype(str).head(8).tolist()
            meta["samples"] = samples[:8]
        context["stats"][field] = meta
    return context


async def _learn_field(field: str, df: pd.DataFrame, provider: str) -> dict:
    context = _compact_learning_context(field, df)
    observed = _top_values(df[field], 8) if field in df.columns else []
    prompt = f"""Bạn là mô-đun AI Learning của MarketSim AI.
Hãy học quy luật từ dữ liệu khách hàng THẬT để đánh giá/bổ sung trường '{field}'.
Bắt buộc: chỉ dùng bằng chứng quan sát được; không tự tạo giá trị ngoài dữ liệu; nếu chưa đủ bằng chứng thì learned=false.
Evidence thống kê rút gọn: {json.dumps(context, ensure_ascii=False, default=str)}
Giá trị quan sát nổi bật của '{field}': {json.dumps(observed, ensure_ascii=False)}
Chỉ trả JSON: {{"field":"{field}","learned":true|false,"confidence":0.0,"strategy":"observed_distribution|observed_categories|not_enough_evidence","evidence":"...","candidate_values":[],"notes":"..."}}"""
    raw = await _learning_ai_call(prompt, provider)
    a, b = raw.find("{"), raw.rfind("}")
    if a < 0 or b <= a:
        raise ValueError("AI không trả JSON hợp lệ")
    data = json.loads(raw[a:b+1])
    data["field"] = field
    data["confidence"] = max(0.0, min(1.0, float(data.get("confidence", 0))))
    data["candidate_values"] = _normalize_candidate_values(data.get("candidate_values"))
    return data


def _sample_from_observed(series, candidates, rng):
    # This helper is used only for non-numeric canonical fields.  Convert every
    # accepted candidate to text so a provider response can never inject a dict
    # or list into a SQLite-bound column.
    cand = [str(x).strip() for x in _normalize_candidate_values(candidates)]
    cand = [x for x in cand if x]
    if cand:
        return cand[int(rng.randint(0, len(cand)))]
    observed = [str(x).strip() for x in _normalize_candidate_values(series.dropna().tolist())]
    observed = [x for x in observed if x]
    if observed:
        return observed[int(rng.randint(0, len(observed)))]
    return None


def _numeric_sample(series, rng):
    n = pd.to_numeric(series, errors="coerce").dropna().astype(float)
    if n.empty: return None
    if len(n) < 3: return float(n.median())
    # Sample observed values + tiny bounded jitter, staying inside observed range.
    v = float(n.iloc[int(rng.randint(0, len(n)))])
    std = float(n.std()) if math.isfinite(float(n.std())) else 0.0
    if std > 0:
        v += float(rng.normal(0, std * 0.03))
    return float(np.clip(v, float(n.min()), float(n.max())))


def apply_learned_fields(df: pd.DataFrame, learning: dict, seed: int = 42, initial_provenance: pd.DataFrame | None = None):
    out = df.copy()
    if initial_provenance is None:
        provenance = pd.DataFrame("REAL", index=out.index, columns=list(CANONICAL_SCHEMA.keys()))
        for field in CANONICAL_SCHEMA:
            if field not in out.columns:
                out[field] = np.nan
            missing = out[field].isna() | out[field].astype(str).str.strip().eq("")
            provenance.loc[missing, field] = "MISSING_SOURCE"
    else:
        provenance = initial_provenance.copy()
        for field in CANONICAL_SCHEMA:
            if field not in out.columns: out[field] = np.nan
            if field not in provenance.columns: provenance[field] = "MISSING_SOURCE"
    rng = np.random.RandomState(seed)
    filled_counts = Counter()
    for field, rule in learning.items():
        if not rule.get("learned"): continue
        if field not in out.columns: out[field] = np.nan
        missing_mask = out[field].isna() | out[field].astype(str).str.strip().eq("")
        # NOT_APPLICABLE must never be filled by AI.
        if field in provenance.columns:
            missing_mask = missing_mask & provenance[field].astype(str).ne("NOT_APPLICABLE")
        if not missing_mask.any(): continue
        typ = CANONICAL_SCHEMA.get(field, {}).get("type")
        candidates = rule.get("candidate_values") or []
        for idx in out.index[missing_mask]:
            value = _numeric_sample(out[field], rng) if typ == "numeric" else _sample_from_observed(out[field], candidates, rng)
            if value is not None:
                out.at[idx, field] = value
                provenance.at[idx, field] = "AI_INFERRED"
                filled_counts[field] += 1
    return out, provenance, dict(filled_counts)


def build_audit(df_before: pd.DataFrame, df_after: pd.DataFrame, provenance: pd.DataFrame, learning: dict):
    total = len(df_before)
    field_coverage = {}
    missing_tags = {"MISSING", "MISSING_SOURCE", "MISSING_INVALID"}
    for field in CANONICAL_SCHEMA:
        p = provenance[field].astype(str) if field in provenance else pd.Series(["MISSING_SOURCE"]*total)
        real = int((p == "REAL").sum())
        derived = int((p == "DERIVED_REAL").sum())
        ai = int((p == "AI_INFERRED").sum())
        na = int((p == "NOT_APPLICABLE").sum())
        invalid = int((p == "MISSING_INVALID").sum())
        missing = int(p.isin(missing_tags).sum())
        denom=max(1,total)
        field_coverage[field] = {
            "real": real, "derived_real":derived, "ai_inferred": ai, "missing": missing, "not_applicable":na, "invalid":invalid,
            "real_pct": round(real/denom*100,1), "derived_real_pct":round(derived/denom*100,1),
            "ai_inferred_pct": round(ai/denom*100,1), "missing_pct": round(missing/denom*100,1), "not_applicable_pct":round(na/denom*100,1),
        }
    tracked = [field_coverage[f] for f in REQUIRED_FIELDS]
    overall_real = round(sum(x["real_pct"] for x in tracked)/len(tracked),1) if tracked else 0
    overall_derived = round(sum(x["derived_real_pct"] for x in tracked)/len(tracked),1) if tracked else 0
    overall_ai = round(sum(x["ai_inferred_pct"] for x in tracked)/len(tracked),1) if tracked else 0
    overall_missing = round(sum(x["missing_pct"] for x in tracked)/len(tracked),1) if tracked else 0
    learned_items = [{"field":f, **{k:v for k,v in x.items() if k in ("learned","confidence","strategy","evidence","notes","candidate_values")}} for f,x in learning.items()]
    readiness=digital_twin_readiness(df_after, provenance)
    return {
        "total_records": total, "required_fields": REQUIRED_FIELDS, "field_coverage": field_coverage,
        "overall_real_data_pct": overall_real, "overall_derived_real_pct":overall_derived,
        "overall_ai_inferred_pct": overall_ai, "overall_missing_pct": overall_missing,
        "learned_fields": learned_items, "remaining_missing_fields": [f for f in REQUIRED_FIELDS if field_coverage[f]["missing"] > 0],
        "ai_inferred_cells": int(sum(x["ai_inferred"] for x in field_coverage.values())),
        "derived_real_cells":int(sum(x["derived_real"] for x in field_coverage.values())),
        "real_cells": int(sum(x["real"] for x in field_coverage.values())), "missing_cells": int(sum(x["missing"] for x in field_coverage.values())),
        "invalid_cells":int(sum(x["invalid"] for x in field_coverage.values())), "digital_twin_readiness":readiness,
    }
