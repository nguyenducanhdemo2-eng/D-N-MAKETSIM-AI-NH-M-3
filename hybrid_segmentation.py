"""Enterprise hybrid segmentation for MarketSim AI.

This upgrade keeps the existing Numeric + Categorical + Text idea, but adds:
- provenance-aware feature selection (AI-only fields do not dominate clustering),
- de-duplication of strongly overlapping engineered signals,
- automatic k selection with tiny-cluster penalties,
- silhouette / stability / balance / DB / CH diagnostics,
- per-customer segment confidence,
- deterministic segment differentiators and explanations.

No LLM is called in this module.
"""
from __future__ import annotations

import re
from typing import Optional

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix, hstack
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import (
    adjusted_rand_score,
    calinski_harabasz_score,
    davies_bouldin_score,
    silhouette_score,
)
from sklearn.preprocessing import OneHotEncoder, StandardScaler


# Avoid double-counting aliases of the same signal: monetary ~= total_spending,
# frequency ~= order_count, price_sensitivity ~= discount_dependency.
NUMERIC_CANDIDATES = [
    "age", "monthly_income", "total_spending", "order_count",
    "average_order_value_final", "discount_dependency", "recency_days",
    "purchase_frequency_per_month", "return_rate", "engagement_score",
    "customer_value_score", "behavioral_loyalty_index", "churn_signal_score",
    "satisfaction_score", "customer_tenure_days",
]
CATEGORICAL_CANDIDATES = [
    "gender", "job", "location", "product_category", "channel", "device",
    "acquisition_source", "rfm_segment", "loyalty_tier", "customer_value_tier",
]
TEXT_CANDIDATES = ["interest_keywords", "pain_point", "personality", "review_text"]

PROVENANCE_WEIGHT = {
    "REAL": 1.0, "ORIGINAL": 1.0, "HUMAN_CONFIRMED": 1.0,
    "DERIVED_REAL": 0.95, "DERIVED": 0.95,
    "DERIVED_MIXED": 0.65, "LEGACY_UNKNOWN": 0.55,
    "AI_INFERRED": 0.42, "AI": 0.42,
    "MISSING": 0.0, "MISSING_SOURCE": 0.0, "MISSING_INVALID": 0.0,
    "NOT_APPLICABLE": 0.0,
}

BLOCK_WEIGHTS = {"numeric": 1.0, "categorical": 0.75, "text": 0.55}


def _clean_text(value) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _blank_series(s: pd.Series) -> pd.Series:
    return s.isna() | s.astype(str).str.strip().str.lower().isin({"", "nan", "none", "null", "n/a", "na", "unknown"})


def _source_for_row(row: pd.Series, field: str) -> str:
    feature_sources = row.get("_feature_sources")
    if isinstance(feature_sources, dict) and field in feature_sources:
        return str(feature_sources.get(field) or "LEGACY_UNKNOWN").upper()
    field_sources = row.get("_field_sources")
    if isinstance(field_sources, dict) and field in field_sources:
        return str(field_sources.get(field) or "LEGACY_UNKNOWN").upper()
    return "LEGACY_UNKNOWN"


def _feature_quality(df: pd.DataFrame, field: str) -> dict:
    if field not in df.columns or len(df) == 0:
        return {"coverage_pct": 0.0, "quality_score": 0.0, "reliable_pct": 0.0, "ai_pct": 0.0, "legacy_pct": 0.0}
    valid = ~_blank_series(df[field])
    n = len(df)
    if not valid.any():
        return {"coverage_pct": 0.0, "quality_score": 0.0, "reliable_pct": 0.0, "ai_pct": 0.0, "legacy_pct": 0.0}
    weights, reliable, ai, legacy = [], 0, 0, 0
    good = {"REAL", "ORIGINAL", "HUMAN_CONFIRMED", "DERIVED_REAL", "DERIVED"}
    for idx in df.index[valid]:
        src = _source_for_row(df.loc[idx], field)
        weights.append(PROVENANCE_WEIGHT.get(src, 0.45))
        if src in good: reliable += 1
        if src in {"AI_INFERRED", "AI"}: ai += 1
        if src == "LEGACY_UNKNOWN": legacy += 1
    # quality_score combines coverage and source reliability across the full dataset.
    quality = (sum(weights) / n) if n else 0
    return {
        "coverage_pct": round(float(valid.mean() * 100), 1),
        "quality_score": round(float(quality), 3),
        "reliable_pct": round(reliable / n * 100, 1),
        "ai_pct": round(ai / n * 100, 1),
        "legacy_pct": round(legacy / n * 100, 1),
    }


def _select_features(df: pd.DataFrame) -> tuple[list[str], list[str], list[str], dict]:
    quality = {c: _feature_quality(df, c) for c in set(NUMERIC_CANDIDATES + CATEGORICAL_CANDIDATES + TEXT_CANDIDATES) if c in df.columns}

    numeric = []
    for c in NUMERIC_CANDIDATES:
        if c not in df.columns: continue
        s = pd.to_numeric(df[c], errors="coerce")
        q = quality.get(c, {})
        if s.notna().mean() >= 0.15 and s.nunique(dropna=True) > 1 and q.get("quality_score", 0) >= 0.40:
            numeric.append(c)

    categorical = []
    for c in CATEGORICAL_CANDIDATES:
        if c not in df.columns: continue
        s = df[c].fillna("").astype(str).str.strip()
        q = quality.get(c, {})
        unique = s[s != ""].nunique()
        if (s != "").mean() >= 0.15 and 1 < unique <= max(100, int(len(df)*0.35)) and q.get("quality_score", 0) >= 0.50:
            categorical.append(c)

    text = []
    for c in TEXT_CANDIDATES:
        if c not in df.columns: continue
        s = df[c].fillna("").astype(str).str.strip()
        q = quality.get(c, {})
        # Be intentionally stricter for text because AI-filled personality/pain
        # fields can otherwise dominate TF-IDF and create circular segments.
        if (s != "").mean() >= 0.15 and s.nunique() > 1 and q.get("quality_score", 0) >= 0.55:
            text.append(c)

    return numeric, categorical, text, quality


def _prepare_matrix(df: pd.DataFrame, numeric_cols: list[str], categorical_cols: list[str], text_cols: list[str], feature_quality: dict):
    blocks = []
    details = {"numeric": numeric_cols, "categorical": categorical_cols, "text": text_cols, "feature_quality": feature_quality}

    if numeric_cols:
        num = df[numeric_cols].apply(pd.to_numeric, errors="coerce")
        num = num.fillna(num.median(numeric_only=True)).fillna(0)
        scaled = StandardScaler().fit_transform(num)
        q_weights = np.array([max(0.35, min(1.0, feature_quality.get(c,{}).get("quality_score",0.5))) for c in numeric_cols])
        scaled = scaled * q_weights[None, :] * BLOCK_WEIGHTS["numeric"]
        blocks.append(csr_matrix(scaled))

    if categorical_cols:
        cat = df[categorical_cols].copy()
        for c in categorical_cols:
            cat[c] = cat[c].where(~_blank_series(cat[c]), "__MISSING__").astype(str)
        try:
            encoder = OneHotEncoder(handle_unknown="ignore", sparse_output=True)
        except TypeError:
            encoder = OneHotEncoder(handle_unknown="ignore", sparse=True)
        encoded = encoder.fit_transform(cat).tocsr()
        weights = []
        for c, cats in zip(categorical_cols, encoder.categories_):
            q = max(0.35, min(1.0, feature_quality.get(c,{}).get("quality_score",0.5)))
            weights.extend([q * BLOCK_WEIGHTS["categorical"]] * len(cats))
        encoded = encoded.multiply(np.asarray(weights)[None, :])
        blocks.append(encoded)

    if text_cols:
        # Prefix field names so the same word occurring in pain_point and interest
        # is not treated as identical context.
        texts = []
        for _, row in df[text_cols].fillna("").astype(str).iterrows():
            parts = []
            for c in text_cols:
                val = _clean_text(row.get(c))
                if val:
                    parts.append(f"{c}_{val}")
            texts.append(" ".join(parts))
        text = pd.Series(texts, index=df.index)
        if text.str.strip().any():
            vectorizer = TfidfVectorizer(max_features=600, min_df=2 if len(df) >= 100 else 1, ngram_range=(1, 2))
            matrix = vectorizer.fit_transform(text)
            if matrix.shape[1] > 0:
                avg_q = np.mean([feature_quality.get(c,{}).get("quality_score",0.5) for c in text_cols])
                matrix = matrix * float(max(0.35, min(1.0, avg_q))) * BLOCK_WEIGHTS["text"]
                blocks.append(matrix)

    if not blocks:
        return None, details

    # Normalize whole customer vector after field/block weighting. This prevents
    # high-cardinality one-hot/text blocks from winning purely by dimensionality.
    X = hstack(blocks).tocsr()
    row_norm = np.sqrt(X.multiply(X).sum(axis=1)).A1
    row_norm[row_norm == 0] = 1.0
    X = X.multiply((1.0 / row_norm)[:, None]).tocsr()
    return X, details


def _cluster_balance(labels: np.ndarray) -> dict:
    if labels is None or len(labels) == 0:
        return {"sizes": {}, "min_pct": 0.0, "max_pct": 0.0, "tiny_clusters": 0, "balance_score": 0.0}
    vals, counts = np.unique(labels, return_counts=True)
    pcts = counts / len(labels) * 100
    # 5% is a conservative minimum for an automatically generated business segment.
    tiny = int((pcts < 5).sum())
    min_pct, max_pct = float(pcts.min()), float(pcts.max())
    min_component = min(1.0, min_pct / 10.0)
    dominance_component = 1.0 - max(0.0, (max_pct - 60.0) / 40.0)
    score = np.clip((min_component*0.55 + dominance_component*0.45), 0, 1)
    return {
        "sizes": {int(v): int(c) for v,c in zip(vals,counts)},
        "min_pct": round(min_pct,1), "max_pct": round(max_pct,1),
        "tiny_clusters": tiny, "balance_score": round(float(score),3),
    }


def _sample_indices(n: int, random_state: int, max_n: int = 2500):
    if n <= max_n: return np.arange(n)
    return np.random.RandomState(random_state).choice(n, max_n, replace=False)


def _evaluate_candidate(X, k: int, random_state: int) -> dict:
    n = X.shape[0]
    idx = _sample_indices(n, random_state, 2500)
    Xs = X[idx]
    model = KMeans(n_clusters=k, random_state=random_state, n_init=10)
    labels = model.fit_predict(Xs)
    if len(np.unique(labels)) < 2:
        return {"k": k, "silhouette": -1.0, "adjusted_score": -9, "balance": _cluster_balance(labels)}
    sil = float(silhouette_score(Xs, labels))
    balance = _cluster_balance(labels)
    penalty = balance["tiny_clusters"] * 0.06
    if balance["max_pct"] > 75: penalty += 0.05
    adjusted = sil - penalty
    return {"k": k, "silhouette": round(sil,4), "adjusted_score": round(adjusted,4), "balance": balance}


def _best_k(X, requested_k: Optional[int], random_state: int, min_k: int = 2, max_k: int = 8):
    n = X.shape[0]
    if n <= 1: return 1, []
    if requested_k is not None:
        return max(2, min(int(requested_k), n-1)), []
    upper = min(max_k, n-1)
    if upper < min_k: return 1, []
    candidates = [_evaluate_candidate(X,k,random_state) for k in range(min_k,upper+1)]
    best = max(candidates, key=lambda x: x["adjusted_score"])
    return int(best["k"]), candidates


def _stability_score(X, k: int, random_state: int) -> float | None:
    if k <= 1 or X.shape[0] < k*3: return None
    idx = _sample_indices(X.shape[0], random_state, 1800)
    Xs = X[idx]
    base = KMeans(n_clusters=k, random_state=random_state, n_init=10).fit_predict(Xs)
    scores = []
    for seed in [random_state+1, random_state+7, random_state+19]:
        alt = KMeans(n_clusters=k, random_state=seed, n_init=10).fit_predict(Xs)
        scores.append(float(adjusted_rand_score(base, alt)))
    return round(float(np.mean(scores)),3) if scores else None


def _dense_cluster_metrics(X, labels: np.ndarray, random_state: int) -> tuple[float|None,float|None]:
    if len(np.unique(labels)) < 2: return None,None
    idx = _sample_indices(X.shape[0], random_state, 1200)
    dense = X[idx].toarray()
    labs = labels[idx]
    try: db = float(davies_bouldin_score(dense,labs))
    except Exception: db = None
    try: ch = float(calinski_harabasz_score(dense,labs))
    except Exception: ch = None
    return (round(db,3) if db is not None else None, round(ch,1) if ch is not None else None)


def _mode(series: pd.Series):
    s = series.dropna().astype(str).str.strip()
    s = s[(s != "") & (s.str.lower() != "nan")]
    return s.mode().iloc[0] if not s.empty else None


def _numeric_differentiators(group: pd.DataFrame, full: pd.DataFrame, cols: list[str]) -> list[dict]:
    out = []
    for c in cols:
        if c not in group or c not in full: continue
        g = pd.to_numeric(group[c], errors="coerce").dropna()
        a = pd.to_numeric(full[c], errors="coerce").dropna()
        if g.empty or a.empty or a.std(ddof=0) <= 1e-12: continue
        gm, am = float(g.median()), float(a.median())
        effect = (gm-am) / float(a.std(ddof=0))
        if abs(effect) < 0.20: continue
        out.append({
            "field": c, "type": "numeric", "direction": "higher" if effect>0 else "lower",
            "segment_value": round(gm,3), "overall_value": round(am,3), "effect": round(effect,3),
        })
    return sorted(out, key=lambda x: abs(x["effect"]), reverse=True)[:4]


def _categorical_differentiators(group: pd.DataFrame, full: pd.DataFrame, cols: list[str]) -> list[dict]:
    out = []
    for c in cols:
        if c not in group or c not in full: continue
        gv = group[c].dropna().astype(str).str.strip(); av = full[c].dropna().astype(str).str.strip()
        gv = gv[(gv!="") & (gv.str.lower()!="nan")]; av = av[(av!="") & (av.str.lower()!="nan")]
        if gv.empty or av.empty: continue
        top = gv.value_counts(normalize=True).index[0]
        gp = float((gv==top).mean()); ap = float((av==top).mean()); delta = gp-ap
        if delta < 0.08: continue
        out.append({"field":c,"type":"categorical","value":str(top),"segment_pct":round(gp*100,1),"overall_pct":round(ap*100,1),"lift":round(delta*100,1)})
    return sorted(out, key=lambda x:x["lift"], reverse=True)[:3]


def _humanize_diff(d: dict) -> str:
    names = {
        "total_spending":"chi tiêu", "order_count":"số đơn", "recency_days":"độ gần lần mua",
        "average_order_value_final":"giá trị đơn TB", "discount_dependency":"phụ thuộc khuyến mãi",
        "purchase_frequency_per_month":"tần suất mua/tháng", "engagement_score":"tương tác",
        "customer_value_score":"giá trị khách hàng", "behavioral_loyalty_index":"trung thành hành vi",
        "churn_signal_score":"tín hiệu rời bỏ", "monthly_income":"thu nhập", "age":"tuổi",
        "return_rate":"tỷ lệ hoàn", "satisfaction_score":"hài lòng",
    }
    field = names.get(d.get("field"), d.get("field","đặc trưng"))
    if d.get("type") == "numeric":
        return f"{field} {'cao hơn' if d.get('direction')=='higher' else 'thấp hơn'} mặt bằng chung"
    return f"{field}: {d.get('value')} nổi bật hơn toàn bộ dữ liệu"


def _segment_name(profile: dict, sid: int) -> str:
    rfm = profile.get("top_rfm_segment")
    cat = profile.get("top_category")
    job = profile.get("top_job")
    channel = profile.get("top_channel")
    value = profile.get("top_value_tier")
    if rfm and rfm != "Insufficient Data":
        suffix = cat or value or job
        return f"{rfm} • {suffix}" if suffix else rfm
    if value and value != "Unknown" and cat:
        return f"{value} • {cat}"
    if cat and job: return f"{cat} • {job}"
    if channel and job: return f"{channel} • {job}"
    if cat: return str(cat)
    if job: return str(job)
    if profile.get("top_interest"): return f"Quan tâm {profile['top_interest']}"
    return f"Customer Segment {sid+1}"


def build_segment_profiles(df: pd.DataFrame, labels: np.ndarray, selected_numeric: list[str], categorical_cols: list[str], segment_confidence: np.ndarray | None = None) -> dict:
    work = df.copy(); work["segment_id"] = labels
    if segment_confidence is not None: work["segment_confidence"] = segment_confidence
    profiles = {}
    used_names = set()
    for sid, group in work.groupby("segment_id", sort=True):
        profile = {"size": int(len(group)), "share_pct": round(len(group)/len(work)*100,1)}
        if "segment_confidence" in group:
            profile["avg_segment_confidence"] = round(float(pd.to_numeric(group["segment_confidence"],errors="coerce").mean()),3)
        for c in selected_numeric:
            s = pd.to_numeric(group[c], errors="coerce") if c in group else pd.Series(dtype=float)
            if s.notna().any():
                profile[f"avg_{c}"] = round(float(s.mean()),3)
                profile[f"median_{c}"] = round(float(s.median()),3)
        for c,key in [
            ("gender","top_gender"),("job","top_job"),("location","top_location"),
            ("channel","top_channel"),("device","top_device"),("product_category","top_category"),
            ("rfm_segment","top_rfm_segment"),("loyalty_tier","top_loyalty_tier"),
            ("customer_value_tier","top_value_tier"),
        ]:
            if c in group:
                value = _mode(group[c])
                if value: profile[key] = value
        if "interest_keywords" in group:
            text = " ".join(group["interest_keywords"].fillna("").astype(str)).lower()
            tokens = re.findall(r"[\wÀ-ỹ]{3,}", text, flags=re.UNICODE)
            stop = {"and","the","with","cho","các","những","khách","hàng","interest","keywords"}
            counts = pd.Series(tokens).value_counts() if tokens else pd.Series(dtype=int)
            counts = counts.drop([x for x in stop if x in counts.index], errors="ignore")
            profile["top_interest"] = counts.index[0] if not counts.empty else None
        diffs = _numeric_differentiators(group,work,selected_numeric) + _categorical_differentiators(group,work,categorical_cols)
        diffs = sorted(diffs, key=lambda x: abs(x.get("effect",x.get("lift",0))), reverse=True)[:5]
        profile["differentiators"] = diffs
        profile["explanation"] = "; ".join(_humanize_diff(x) for x in diffs[:3]) or "Phân khúc khác biệt theo tổ hợp nhiều đặc trưng, chưa có một yếu tố đơn lẻ đủ nổi bật."
        name = _segment_name(profile,int(sid))
        if name in used_names: name = f"{name} • Nhóm {int(sid)+1}"
        used_names.add(name); profile["segment_name"] = name
        profiles[int(sid)] = profile
    return profiles


def _segment_confidence(model: KMeans, X) -> np.ndarray:
    distances = model.transform(X)
    if distances.shape[1] <= 1: return np.ones(X.shape[0])
    order = np.partition(distances, 1, axis=1)
    d1, d2 = order[:,0], order[:,1]
    margin = (d2-d1) / (d2+1e-9)
    return np.clip(margin,0,1)


def _quality_summary(X, labels, silhouette, stability, feature_quality, selected, random_state, candidates, avg_customer_confidence: float) -> dict:
    balance = _cluster_balance(labels)
    db, ch = _dense_cluster_metrics(X, labels, random_state)
    selected_fields = selected["numeric"] + selected["categorical"] + selected["text"]
    qvals = [feature_quality.get(c,{}).get("quality_score",0) for c in selected_fields]
    feature_q = float(np.mean(qvals)) if qvals else 0
    # A segmentation is not "high quality" merely because k is stable. Customers
    # also need to sit clearly closer to their own centroid than alternatives.
    sil_component = float(np.clip((silhouette or 0)/0.45,0,1))
    stability_component = float(stability if stability is not None else 0.5)
    confidence_component = float(np.clip(avg_customer_confidence,0,1))
    score = round((sil_component*0.30 + stability_component*0.20 + balance["balance_score"]*0.15 + feature_q*0.15 + confidence_component*0.20)*100,1)
    status = "HIGH" if score>=80 else "MEDIUM" if score>=60 else "LOW"
    warnings = []
    if silhouette is None or silhouette < 0.20: warnings.append("Các phân khúc còn chồng lấn; nên bổ sung dữ liệu hành vi/giao dịch trước khi dùng cho quyết định quan trọng.")
    if stability is not None and stability < 0.70: warnings.append("Kết quả phân nhóm thay đổi đáng kể khi đổi seed; cấu trúc segment chưa ổn định.")
    if balance["tiny_clusters"]: warnings.append(f"Có {balance['tiny_clusters']} phân khúc dưới 5% dân số; cần kiểm tra xem đây là niche thật hay nhiễu.")
    if balance["max_pct"] > 75: warnings.append("Một phân khúc chiếm hơn 75% dữ liệu; khả năng feature chưa đủ để tách khách hàng.")
    if avg_customer_confidence < 0.40: warnings.append("Nhiều khách hàng nằm gần ranh giới giữa các phân khúc; hãy đọc segment như nhóm xu hướng thay vì nhãn tuyệt đối.")
    ai_heavy = [c for c in selected_fields if feature_quality.get(c,{}).get("ai_pct",0)>50]
    if ai_heavy: warnings.append("Một số feature được AI bổ sung nhiều: "+", ".join(ai_heavy[:6])+". MarketSim đã giảm trọng số nhưng vẫn nên kiểm tra.")
    return {
        "score": score, "status": status, "silhouette": round(float(silhouette),4) if silhouette is not None else None,
        "stability": stability, "davies_bouldin": db, "calinski_harabasz": ch,
        "balance": balance, "feature_quality_avg": round(feature_q*100,1), "avg_customer_confidence": round(avg_customer_confidence*100,1),
        "selected_feature_count": len(selected_fields), "selected_features": selected,
        "warnings": warnings, "k_candidates": candidates,
        "interpretation": "Phân khúc rõ và ổn định." if status=="HIGH" else ("Phân khúc sử dụng được nhưng nên đọc kèm cảnh báo." if status=="MEDIUM" else "Phân khúc chưa đủ mạnh để làm căn cứ duy nhất cho mô phỏng."),
    }


def hybrid_segment_customers(df: pd.DataFrame, n_clusters: Optional[int] = None, random_state: int = 42) -> dict:
    """Segment customers with quality diagnostics and confidence.

    n_clusters=None selects k automatically from 2..8. Missing raw values are
    imputed only inside the matrix used by KMeans; the source dataframe is never
    overwritten by those temporary medians/categories.
    """
    if df is None or df.empty:
        return {"status":"empty","labeled_df":pd.DataFrame(),"data":pd.DataFrame(),"message":"Không có dữ liệu."}

    work = df.copy().reset_index(drop=True)
    numeric, categorical, text, feature_quality = _select_features(work)
    X, details = _prepare_matrix(work,numeric,categorical,text,feature_quality)
    selected = {"numeric":numeric,"categorical":categorical,"text":text}

    if X is None or X.shape[1] == 0:
        return {
            "status":"insufficient_features","labeled_df":work,"data":work,
            "selected_features":details,"quality":{"score":0,"status":"LOW","warnings":["Không có đủ feature có độ tin cậy và biến thiên để phân cụm."]},
            "message":"Không có đủ feature có độ tin cậy và biến thiên để phân cụm.",
        }
    if len(work) < 2:
        work["segment_id"] = 0; work["segment_confidence"] = 1.0; work["segment_reason"] = "Chỉ có một khách hàng."
        profiles = {0:{"size":1,"share_pct":100.0,"segment_name":"Customer Segment 1","avg_segment_confidence":1.0,"differentiators":[],"explanation":"Chỉ có một khách hàng."}}
        return {"status":"ok","labeled_df":work,"data":work,"n_clusters":1,"silhouette":None,"selected_features":details,"profiles":profiles,"quality":{"score":0,"status":"LOW","warnings":["Chỉ có một khách hàng."],"selected_features":selected}}

    k, candidates = _best_k(X,n_clusters,random_state)
    if k <= 1:
        work["segment_id"] = 0; work["segment_confidence"] = 1.0; work["segment_reason"] = "Dữ liệu chưa tạo được nhiều phân khúc."
        profiles = {0:{"size":len(work),"share_pct":100.0,"segment_name":"Customer Segment 1","avg_segment_confidence":1.0,"differentiators":[],"explanation":"Dữ liệu chưa tạo được nhiều phân khúc."}}
        return {"status":"ok","labeled_df":work,"data":work,"n_clusters":1,"silhouette":None,"selected_features":details,"profiles":profiles,"quality":{"score":0,"status":"LOW","warnings":["Dữ liệu chưa tạo được nhiều phân khúc."],"selected_features":selected}}

    model = KMeans(n_clusters=k, random_state=random_state, n_init=20)
    labels = model.fit_predict(X)
    work["segment_id"] = labels
    idx = _sample_indices(len(work),random_state,2500)
    score = float(silhouette_score(X[idx],labels[idx])) if len(np.unique(labels[idx]))>1 else None
    confidence = _segment_confidence(model,X)
    work["segment_confidence"] = confidence

    profiles = build_segment_profiles(work,labels,numeric,categorical,confidence)
    reason_map = {sid:p.get("explanation","") for sid,p in profiles.items()}
    work["segment_reason"] = [reason_map.get(int(s),"") for s in labels]

    stability = _stability_score(X,k,random_state)
    avg_conf=float(np.mean(confidence))
    quality = _quality_summary(X,labels,score,stability,feature_quality,selected,random_state,candidates,avg_conf)
    quality["low_confidence_customers"] = int((confidence<0.15).sum())

    return {
        "status":"ok","labeled_df":work,"data":work,"n_clusters":int(k),
        "silhouette":score,"selected_features":details,"profiles":profiles,
        "quality":quality,"model":model,
    }
