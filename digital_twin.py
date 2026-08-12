"""PART 4 - SYNTHETIC CUSTOMER DIGITAL TWIN ENGINE

Creates synthetic customer twins from observed REAL customer distributions.

Design principles:
- Real customers are never overwritten or replaced.
- Synthetic twins are generated only from observed segment rows.
- Numeric fields use bootstrap + bounded jitter.
- Categorical/text fields are sampled from observed values in the same segment.
- No unsupported field is invented just because a schema contains it.
- Propensity values are explicitly heuristic/proxy scores, NOT calibrated probabilities.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Optional

import numpy as np
import pandas as pd

NUMERIC_FIELDS = [
    "age", "total_spending", "order_count", "average_order_value", "discount_usage",
    "recency_days", "frequency", "monetary", "r_score", "f_score", "m_score",
    "rfm_score", "price_sensitivity",
]
CATEGORICAL_FIELDS = [
    "gender", "job", "location", "product_category", "channel", "device", "acquisition_source",
    "rfm_segment",
]
TEXT_FIELDS = ["interest_keywords", "pain_point", "personality", "review_text"]


def _seed_from(*parts) -> int:
    raw = "|".join(str(x) for x in parts)
    return int(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8], 16)


def _num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _sample_categorical(s: pd.Series, rng: np.random.RandomState):
    vals = s.dropna().astype(str).str.strip()
    vals = vals[vals != ""]
    if vals.empty:
        return None
    counts = vals.value_counts()
    return str(rng.choice(counts.index.to_numpy(), p=(counts / counts.sum()).to_numpy()))


def _has_value(value) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except Exception:
        pass
    return str(value).strip() != ""


def _jitter_numeric_from_anchor(anchor_value, series: pd.Series, rng: np.random.RandomState, jitter_ratio: float = 0.04):
    """Jitter quanh CHÍNH giá trị của dòng anchor, nhưng luôn kẹp trong phân phối segment.

    Mục tiêu là giữ tương quan giữa các trường trên cùng một khách hàng gốc thay vì
    lấy độc lập từng numeric field từ những khách hàng khác nhau.
    """
    vals = pd.to_numeric(series, errors="coerce").dropna()
    if vals.empty:
        return None
    anchor = _num(anchor_value)
    if anchor is None:
        return _sample_numeric(series, rng, jitter_ratio=jitter_ratio)
    if len(vals) > 1:
        std = float(vals.std(ddof=0))
    else:
        std = 0.0
    # Jitter nhỏ hơn cách bootstrap độc lập trước đây để hồ sơ vẫn gần anchor.
    scale = max(std * 0.08, abs(anchor) * jitter_ratio, 1e-9)
    lo, hi = float(vals.min()), float(vals.max())
    if lo == hi:
        return lo
    return float(np.clip(anchor + float(rng.normal(0, scale)), lo, hi))


def _anchor_age(anchor_value, series: pd.Series, rng):
    value = _jitter_numeric_from_anchor(anchor_value, series, rng, jitter_ratio=0.015)
    if value is None:
        return None
    vals = pd.to_numeric(series, errors="coerce").dropna()
    lo, hi = (int(vals.min()), int(vals.max())) if not vals.empty else (18, 80)
    return int(np.clip(round(value), lo, hi))


def _profile_completeness(twin: dict) -> float:
    """Tỷ lệ trường hành vi có bằng chứng; chỉ là chỉ báo chất lượng hồ sơ, không phải xác suất."""
    important = [
        "age", "gender", "job", "location", "product_category", "channel",
        "rfm_segment", "interest_keywords", "pain_point", "personality",
        "total_spending", "frequency", "recency_days", "price_sensitivity",
    ]
    present = sum(1 for key in important if _has_value(twin.get(key)))
    return round(present / len(important), 3)


def _sample_numeric(series: pd.Series, rng: np.random.RandomState, jitter_ratio: float = 0.06):
    vals = pd.to_numeric(series, errors="coerce").dropna()
    if vals.empty:
        return None
    base = float(rng.choice(vals.to_numpy()))
    if len(vals) > 1:
        std = float(vals.std(ddof=0))
    else:
        std = 0.0
    # Keep synthetic values close to the empirical segment distribution.
    scale = max(std * 0.20, abs(base) * jitter_ratio, 1e-9)
    value = base + float(rng.normal(0, scale))
    lo, hi = float(vals.min()), float(vals.max())
    if lo == hi:
        return lo
    return float(np.clip(value, lo, hi))


def _sample_age(series: pd.Series, rng):
    value = _sample_numeric(series, rng, jitter_ratio=0.02)
    if value is None:
        return None
    vals = pd.to_numeric(series, errors="coerce").dropna()
    lo, hi = (int(vals.min()), int(vals.max())) if not vals.empty else (18, 80)
    return int(np.clip(round(value), lo, hi))


def _text_sample(series: pd.Series, rng):
    vals = series.dropna().astype(str).str.strip()
    vals = vals[vals != ""]
    if vals.empty:
        return None
    return str(rng.choice(vals.to_numpy()))


def _normalize_01(value, lo, hi):
    if value is None or not math.isfinite(float(value)) or hi <= lo:
        return None
    return float(np.clip((float(value) - lo) / (hi - lo), 0, 1))


def _proxy_scores(twin: dict, segment_df: pd.DataFrame) -> dict:
    """Heuristic segment-relative scores. Never label these as calibrated probabilities."""
    scores = {}
    # RFM readiness: only available when actual RFM fields have coverage.
    rfm = _num(twin.get("rfm_score"))
    if rfm is not None:
        scores["purchase_readiness_proxy"] = round(float(np.clip(rfm / 15.0, 0, 1)), 3)

    price = _num(twin.get("price_sensitivity"))
    if price is not None:
        scores["price_sensitivity_proxy"] = round(float(np.clip(price, 0, 1)), 3)

    freq = _num(twin.get("frequency"))
    monetary = _num(twin.get("monetary"))
    if freq is not None and "frequency" in segment_df:
        vals = pd.to_numeric(segment_df["frequency"], errors="coerce").dropna()
        if len(vals) > 1:
            scores["loyalty_proxy"] = round(float(np.clip((freq - vals.min()) / (vals.max() - vals.min()), 0, 1)), 3)
    recency = _num(twin.get("recency_days"))
    if recency is not None and "recency_days" in segment_df:
        vals = pd.to_numeric(segment_df["recency_days"], errors="coerce").dropna()
        if len(vals) > 1:
            # Higher recency days => higher churn risk proxy.
            scores["churn_risk_proxy"] = round(float(np.clip((recency - vals.min()) / (vals.max() - vals.min()), 0, 1)), 3)
    if monetary is not None and "monetary" in segment_df:
        vals = pd.to_numeric(segment_df["monetary"], errors="coerce").dropna()
        if len(vals) > 1 and float(vals.max()) > float(vals.min()):
            scores["value_proxy"] = round(float(np.clip((monetary - vals.min()) / (vals.max() - vals.min()), 0, 1)), 3)
    return scores


def _twin_confidence(segment_df: pd.DataFrame, twin: dict) -> float:
    available = []
    for c in NUMERIC_FIELDS + CATEGORICAL_FIELDS + TEXT_FIELDS:
        if c in segment_df.columns:
            available.append(float(segment_df[c].notna().mean()))
    coverage = float(np.mean(available)) if available else 0.0
    n_factor = min(1.0, len(segment_df) / 100.0)
    source_real = float(twin.get("source_data_reliability") or 0.5)
    return round(float(np.clip(0.45 * coverage + 0.25 * n_factor + 0.30 * source_real, 0, 1)), 3)


def generate_synthetic_twins(
    labeled_df: pd.DataFrame,
    segment_id: Optional[int] = None,
    twins_per_segment: int = 25,
    random_seed: int = 42,
) -> dict:
    """Generate coherent synthetic twins from observed customer rows.

    QUALITY UPGRADE (additive to the existing data-driven approach):
    - one REAL row in the selected segment is chosen as an anchor for each twin;
    - correlated categorical/text attributes are preserved from that same anchor;
    - numeric attributes are jittered around the anchor and clipped to the real segment range;
    - if an anchor field is missing, only then do we fall back to sampling that field from
      the same segment distribution;
    - no direct customer identifier is copied to the synthetic twin.

    This keeps the original principle: every generated value must be supported by observed
    data from the same segment. It does not use an LLM to invent customer attributes.
    """
    if labeled_df is None or labeled_df.empty:
        return {"status": "empty", "twins": [], "message": "Không có customer data."}
    if "segment_id" not in labeled_df.columns:
        return {"status": "error", "twins": [], "message": "Thiếu segment_id. Hãy chạy Hybrid Segmentation trước."}

    work = labeled_df.copy().reset_index(drop=True)
    if segment_id is not None:
        work = work[work["segment_id"].astype(int) == int(segment_id)].copy()
    if work.empty:
        return {"status": "empty", "twins": [], "message": "Segment được chọn không có dữ liệu."}

    per_segment = max(1, min(int(twins_per_segment), 500))
    segment_ids = sorted(work["segment_id"].dropna().astype(int).unique().tolist())
    if segment_id is not None:
        segment_ids = [int(segment_id)]

    all_twins = []
    counts = {}
    for sid in segment_ids:
        group = work[work["segment_id"].astype(int) == sid].copy().reset_index(drop=True)
        if group.empty:
            continue
        rng = np.random.RandomState(_seed_from(random_seed, sid, len(group)))
        for i in range(per_segment):
            source_idx = int(rng.randint(0, len(group)))
            source = group.iloc[source_idx]
            twin = {
                "twin_id": f"SYN-S{sid}-{i+1:04d}-{_seed_from(random_seed, sid, i) % 100000:05d}",
                "segment_id": sid,
                "is_synthetic": True,
                "generation_method": "anchor_row_plus_bounded_jitter",
                "source_segment_size": int(len(group)),
            }
            field_sources = {}

            # Numeric fields: keep the customer's numeric profile together by jittering around
            # the same anchor row. Missing anchor values fall back to the segment distribution.
            for c in NUMERIC_FIELDS:
                if c not in group.columns:
                    continue
                anchor_value = source.get(c)
                if c == "age":
                    value = _anchor_age(anchor_value, group[c], rng)
                else:
                    value = _jitter_numeric_from_anchor(anchor_value, group[c], rng)
                if value is not None:
                    twin[c] = value
                    field_sources[c] = "anchor_jitter" if _has_value(anchor_value) else "segment_fallback"

            # Categorical + text attributes remain tied to the SAME anchor customer whenever
            # evidence exists. This is the main coherence improvement over independent sampling.
            for c in CATEGORICAL_FIELDS + TEXT_FIELDS:
                if c not in group.columns:
                    continue
                anchor_value = source.get(c)
                if _has_value(anchor_value):
                    twin[c] = str(anchor_value).strip()
                    field_sources[c] = "anchor"
                else:
                    sampled = _sample_categorical(group[c], rng) if c in CATEGORICAL_FIELDS else _text_sample(group[c], rng)
                    if sampled is not None:
                        twin[c] = sampled
                        field_sources[c] = "segment_fallback"

            # Keep only a non-identifying hash for auditability; never copy customer_id itself.
            source_customer = str(source.get("customer_id") or "")
            twin["source_row_hash"] = hashlib.sha256(source_customer.encode("utf-8")).hexdigest()[:12] if source_customer else None
            twin["source_data_reliability"] = _num(source.get("data_reliability"))
            twin["proxy_scores"] = _proxy_scores(twin, group)
            twin["profile_completeness"] = _profile_completeness(twin)
            twin["confidence"] = _twin_confidence(group, twin)
            twin["data_provenance"] = {
                "real_source": "same_segment_anchor_and_distribution",
                "field_sources": field_sources,
                "anchor_fields": [k for k, v in field_sources.items() if v in ("anchor", "anchor_jitter")],
                "segment_fallback_fields": [k for k, v in field_sources.items() if v == "segment_fallback"],
                "source_row_hash": twin["source_row_hash"],
                "note": "Twin bám một dòng anchor cùng segment; chỉ trường thiếu ở anchor mới lấy từ phân phối segment. Không phải bản sao khách hàng thật.",
            }
            all_twins.append(twin)
        counts[sid] = per_segment

    return {
        "status": "ok",
        "twins": all_twins,
        "segment_counts": counts,
        "total": len(all_twins),
        "method": "anchor_row_plus_bounded_jitter",
        "note": "Twin được neo theo một hồ sơ thật cùng segment để giữ tương quan. proxy_scores vẫn là heuristic, chưa phải xác suất đã hiệu chỉnh.",
    }

def twins_to_dataframe(twins: list[dict]) -> pd.DataFrame:
    if not twins:
        return pd.DataFrame()
    rows = []
    for t in twins:
        row = {k: v for k, v in t.items() if k not in {"proxy_scores", "data_provenance"}}
        row["purchase_readiness_proxy"] = t.get("proxy_scores", {}).get("purchase_readiness_proxy")
        row["price_sensitivity_proxy"] = t.get("proxy_scores", {}).get("price_sensitivity_proxy")
        row["loyalty_proxy"] = t.get("proxy_scores", {}).get("loyalty_proxy")
        row["churn_risk_proxy"] = t.get("proxy_scores", {}).get("churn_risk_proxy")
        row["value_proxy"] = t.get("proxy_scores", {}).get("value_proxy")
        rows.append(row)
    return pd.DataFrame(rows)
