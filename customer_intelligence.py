"""Customer Intelligence for MarketSim AI.

Enterprise upgrade goals
------------------------
1. Prefer deterministic features calculated from confirmed business data.
2. Never turn a missing value into a fact just to make a profile look complete.
3. Keep every derived metric explainable and attach a source label.
4. Produce quality/readiness signals that can be shown before segmentation.
5. Remain backward-compatible with the fields used by Persona/Digital Twin.

This module does not call an LLM.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

import numpy as np
import pandas as pd


# Fields persisted in the canonical customer schema. Extra business fields are
# optional and are used only when the enterprise actually supplies them.
NUMERIC_FIELDS = [
    "age", "total_spending", "order_count", "average_order_value", "discount_usage",
    "monthly_income", "return_count", "website_visits_30d", "email_open_rate",
    "cart_abandon_rate", "satisfaction_score",
]

OPTIONAL_BEHAVIOR_FIELDS = [
    "product_category", "channel", "device", "acquisition_source", "review_text",
    "loyalty_tier", "signup_date",
]

# Reliability weights are deliberately conservative. AI inferred data can still
# be displayed, but deterministic intelligence does not silently treat it as
# equally strong as a real/derived-real field.
SOURCE_WEIGHTS = {
    "REAL": 1.00,
    "ORIGINAL": 1.00,
    "DERIVED_REAL": 0.95,
    "DERIVED": 0.95,
    "HUMAN_CONFIRMED": 1.00,
    "AI_INFERRED": 0.55,
    "AI": 0.55,
    "LEGACY_UNKNOWN": 0.50,
    "MISSING_SOURCE": 0.0,
    "MISSING_INVALID": 0.0,
    "NOT_APPLICABLE": 0.0,
    "MISSING": 0.0,
}

DERIVATION_CATALOG = {
    "recency_days": "Số ngày từ lần mua gần nhất đến ngày tham chiếu.",
    "average_order_value_final": "Tổng chi tiêu / số đơn khi AOV gốc không có.",
    "purchase_frequency_per_month": "Số đơn / số tháng kể từ ngày đăng ký.",
    "return_rate": "Số đơn hoàn trả / số đơn đã mua.",
    "discount_dependency": "Tỷ lệ sử dụng khuyến mãi đã chuẩn hóa về 0–1.",
    "engagement_score": "Chỉ số 0–1 từ lượt truy cập, tỷ lệ mở email và tỷ lệ bỏ giỏ (chỉ dùng tín hiệu có dữ liệu).",
    "customer_value_score": "Điểm 0–1 từ RFM sau khi chuẩn hóa nội bộ dataset; không phải doanh thu dự báo.",
    "behavioral_loyalty_index": "Chỉ số 0–1 từ RFM, hài lòng và tỷ lệ hoàn trả; không phải xác suất trung thành.",
    "churn_signal_score": "Chỉ số cảnh báo 0–1 từ recency, frequency, bỏ giỏ và hài lòng; không phải xác suất churn đã hiệu chỉnh.",
}


def _to_float(value):
    try:
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return np.nan
        return float(value)
    except (TypeError, ValueError):
        return np.nan


def _parse_date(value) -> Optional[pd.Timestamp]:
    if value is None or str(value).strip() == "":
        return None
    try:
        ts = pd.to_datetime(value, errors="coerce")
        if pd.isna(ts):
            return None
        # Drop timezone only for stable date arithmetic.
        if getattr(ts, "tzinfo", None) is not None:
            ts = ts.tz_convert(None)
        return ts.normalize()
    except Exception:
        return None


def _blank_scalar(value) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except Exception:
        pass
    return str(value).strip().lower() in {"", "nan", "none", "null", "n/a", "na", "unknown"}


def _field_sources(row: pd.Series) -> dict:
    src = row.get("_field_sources")
    return src if isinstance(src, dict) else {}


def _field_source(row: pd.Series, field: str) -> str:
    src = _field_sources(row)
    if field in src:
        return str(src.get(field) or "LEGACY_UNKNOWN").upper()
    # Old persisted datasets did not have provenance. Do not pretend they were
    # verified; give them an explicit legacy status.
    return "LEGACY_UNKNOWN"


def _source_weight(source: str) -> float:
    return float(SOURCE_WEIGHTS.get(str(source or "").upper(), 0.45))


def _sources_are_deterministic(row: pd.Series, fields: list[str]) -> bool:
    """True only when all present inputs are REAL/DERIVED_REAL/human confirmed.

    Legacy datasets have no provenance and therefore return False here. They can
    still be analyzed through backward-compatible features, but enterprise-only
    derived metrics will not be advertised as DERIVED_REAL.
    """
    good = {"REAL", "ORIGINAL", "DERIVED_REAL", "DERIVED", "HUMAN_CONFIRMED"}
    for field in fields:
        if _blank_scalar(row.get(field)):
            return False
        if _field_source(row, field) not in good:
            return False
    return True


def _derived_source(row: pd.Series, fields: list[str]) -> str:
    if _sources_are_deterministic(row, fields):
        return "DERIVED_REAL"
    # If values exist but provenance is legacy/AI, keep a lower-trust marker.
    if all(not _blank_scalar(row.get(f)) for f in fields):
        return "DERIVED_MIXED"
    return "MISSING"


def _score_series(series: pd.Series, higher_is_better: bool = True) -> pd.Series:
    """Rank a numeric series on a 1–5 scale without inventing missing values."""
    s = pd.to_numeric(series, errors="coerce")
    valid = s.dropna()
    result = pd.Series(np.nan, index=s.index, dtype="float64")
    if valid.empty:
        return result
    if valid.nunique() == 1:
        result.loc[valid.index] = 3
        return result
    ranks = valid.rank(method="average", pct=True)
    if not higher_is_better:
        ranks = 1 - ranks + (1 / len(valid))
    result.loc[valid.index] = np.ceil(ranks * 5).clip(1, 5)
    return result


def _percentile_01(series: pd.Series, higher_is_better: bool = True) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    result = pd.Series(np.nan, index=s.index, dtype="float64")
    valid = s.dropna()
    if valid.empty:
        return result
    if valid.nunique() == 1:
        result.loc[valid.index] = 0.5
        return result
    rank = valid.rank(method="average", pct=True)
    if not higher_is_better:
        rank = 1 - rank + (1 / len(valid))
    result.loc[valid.index] = rank.clip(0, 1)
    return result


def _normalize_rate(value):
    v = _to_float(value)
    if pd.isna(v):
        return np.nan
    if v > 1:
        v = v / 100.0
    if v < 0 or v > 1:
        return np.nan
    return float(v)


def _provenance_reliability(row: pd.Series) -> float:
    sources = _field_sources(row)
    if not sources:
        return 0.5
    tracked = [str(x).upper() for x in sources.values()]
    if not tracked:
        return 0.5
    return round(float(np.mean([_source_weight(x) for x in tracked])), 3)


def _source_breakdown(df: pd.DataFrame) -> dict:
    counts = {}
    total = 0
    if "_field_sources" not in df.columns:
        return {"LEGACY_UNKNOWN": 100.0}
    for src in df["_field_sources"]:
        if not isinstance(src, dict):
            continue
        for value in src.values():
            key = str(value or "LEGACY_UNKNOWN").upper()
            counts[key] = counts.get(key, 0) + 1
            total += 1
    if total == 0:
        return {"LEGACY_UNKNOWN": 100.0}
    return {k: round(v / total * 100, 1) for k, v in sorted(counts.items())}


def build_customer_intelligence(records: Iterable[dict], reference_date=None) -> pd.DataFrame:
    """Build deterministic customer-intelligence features.

    Existing MarketSim columns are preserved. New fields are additive and are
    left NaN when the enterprise did not supply enough evidence.
    """
    df = pd.DataFrame(list(records or []))
    if df.empty:
        return pd.DataFrame()

    if reference_date is None:
        reference = pd.Timestamp(datetime.now(timezone.utc).date())
    else:
        reference = pd.Timestamp(reference_date).normalize()

    for field in NUMERIC_FIELDS:
        if field not in df.columns:
            df[field] = np.nan
        df[field] = pd.to_numeric(df[field], errors="coerce")

    # Ensure optional columns exist for stable downstream code.
    for field in OPTIONAL_BEHAVIOR_FIELDS + ["last_purchase_date"]:
        if field not in df.columns:
            df[field] = np.nan

    recency_values, frequency_values, aov_values = [], [], []
    price_values, tenure_values, freq_month_values = [], [], []
    return_rate_values, discount_dep_values = [], []
    feature_sources = []

    for _, row in df.iterrows():
        fs = {}

        purchase_date = _parse_date(row.get("last_purchase_date"))
        if purchase_date is None:
            recency_values.append(np.nan)
            fs["recency_days"] = "MISSING"
        else:
            recency_values.append(max((reference - purchase_date).days, 0))
            fs["recency_days"] = _derived_source(row, ["last_purchase_date"])

        order_count = _to_float(row.get("order_count"))
        if pd.notna(order_count) and order_count >= 0:
            frequency_values.append(order_count)
            fs["frequency"] = _field_source(row, "order_count")
        else:
            frequency_values.append(np.nan)
            fs["frequency"] = "MISSING"

        aov = _to_float(row.get("average_order_value"))
        if pd.notna(aov) and aov >= 0:
            aov_values.append(aov)
            fs["average_order_value_final"] = _field_source(row, "average_order_value")
        else:
            spending = _to_float(row.get("total_spending"))
            if pd.notna(spending) and pd.notna(order_count) and order_count > 0:
                aov_values.append(spending / order_count)
                fs["average_order_value_final"] = _derived_source(row, ["total_spending", "order_count"])
            else:
                aov_values.append(np.nan)
                fs["average_order_value_final"] = "MISSING"

        discount = _normalize_rate(row.get("discount_usage"))
        price_values.append(discount)
        discount_dep_values.append(discount)
        if pd.notna(discount):
            fs["price_sensitivity"] = _field_source(row, "discount_usage")
            fs["discount_dependency"] = _derived_source(row, ["discount_usage"])
        else:
            fs["price_sensitivity"] = "MISSING"
            fs["discount_dependency"] = "MISSING"

        signup = _parse_date(row.get("signup_date"))
        if signup is not None and signup <= reference:
            tenure_days = max((reference - signup).days, 0)
            tenure_values.append(tenure_days)
            fs["customer_tenure_days"] = _derived_source(row, ["signup_date"])
            months = max(tenure_days / 30.4375, 1.0)
            if pd.notna(order_count) and order_count >= 0:
                freq_month_values.append(order_count / months)
                fs["purchase_frequency_per_month"] = _derived_source(row, ["order_count", "signup_date"])
            else:
                freq_month_values.append(np.nan)
                fs["purchase_frequency_per_month"] = "MISSING"
        else:
            tenure_values.append(np.nan)
            freq_month_values.append(np.nan)
            fs["customer_tenure_days"] = "MISSING"
            fs["purchase_frequency_per_month"] = "MISSING"

        returned = _to_float(row.get("return_count"))
        if pd.notna(returned) and returned >= 0 and pd.notna(order_count) and order_count > 0:
            return_rate_values.append(float(np.clip(returned / order_count, 0, 1)))
            fs["return_rate"] = _derived_source(row, ["return_count", "order_count"])
        elif pd.notna(order_count) and order_count == 0:
            return_rate_values.append(np.nan)
            fs["return_rate"] = "NOT_APPLICABLE"
        else:
            return_rate_values.append(np.nan)
            fs["return_rate"] = "MISSING"

        feature_sources.append(fs)

    df["recency_days"] = recency_values
    df["frequency"] = frequency_values
    df["monetary"] = pd.to_numeric(df["total_spending"], errors="coerce")
    df["average_order_value_final"] = aov_values
    df["price_sensitivity"] = price_values
    df["customer_tenure_days"] = tenure_values
    df["purchase_frequency_per_month"] = freq_month_values
    df["return_rate"] = return_rate_values
    df["discount_dependency"] = discount_dep_values

    # RFM is deterministic. Missing components remain missing.
    df["r_score"] = _score_series(df["recency_days"], higher_is_better=False)
    df["f_score"] = _score_series(df["frequency"], higher_is_better=True)
    df["m_score"] = _score_series(df["monetary"], higher_is_better=True)
    rfm_available = df[["r_score", "f_score", "m_score"]].notna().all(axis=1)
    df["rfm_score"] = np.where(
        rfm_available,
        df["r_score"] + df["f_score"] + df["m_score"],
        np.nan,
    )

    # Dataset-relative deterministic scores. These are indices, not calibrated
    # probabilities and the naming deliberately reflects that distinction.
    recency_good = _percentile_01(df["recency_days"], higher_is_better=False)
    freq_good = _percentile_01(df["frequency"], higher_is_better=True)
    monetary_good = _percentile_01(df["monetary"], higher_is_better=True)
    df["customer_value_score"] = pd.concat([freq_good, monetary_good], axis=1).mean(axis=1, skipna=False)

    visits = _percentile_01(df["website_visits_30d"], higher_is_better=True)
    email = df["email_open_rate"].map(_normalize_rate)
    cart = df["cart_abandon_rate"].map(_normalize_rate)
    engagement = []
    for idx in df.index:
        parts = []
        if pd.notna(visits.loc[idx]): parts.append((float(visits.loc[idx]), 0.40))
        if pd.notna(email.loc[idx]): parts.append((float(email.loc[idx]), 0.35))
        if pd.notna(cart.loc[idx]): parts.append((1 - float(cart.loc[idx]), 0.25))
        if len(parts) < 2:
            engagement.append(np.nan)
        else:
            denom = sum(w for _, w in parts)
            engagement.append(sum(v * w for v, w in parts) / denom)
    df["engagement_score"] = engagement

    satisfaction = pd.to_numeric(df["satisfaction_score"], errors="coerce")
    satisfaction01 = ((satisfaction - 1) / 4).clip(0, 1)
    return_good = 1 - pd.to_numeric(df["return_rate"], errors="coerce")

    loyalty_values, churn_values = [], []
    for idx in df.index:
        loyalty_parts = []
        for val, weight in [
            (recency_good.loc[idx], 0.25), (freq_good.loc[idx], 0.25),
            (monetary_good.loc[idx], 0.20), (satisfaction01.loc[idx], 0.20),
            (return_good.loc[idx], 0.10),
        ]:
            if pd.notna(val): loyalty_parts.append((float(val), weight))
        if len(loyalty_parts) >= 3:
            denom = sum(w for _, w in loyalty_parts)
            loyalty_values.append(sum(v*w for v,w in loyalty_parts)/denom)
        else:
            loyalty_values.append(np.nan)

        churn_parts = []
        if pd.notna(recency_good.loc[idx]): churn_parts.append((1-float(recency_good.loc[idx]), 0.40))
        if pd.notna(freq_good.loc[idx]): churn_parts.append((1-float(freq_good.loc[idx]), 0.25))
        c = cart.loc[idx]
        if pd.notna(c): churn_parts.append((float(c), 0.20))
        s = satisfaction01.loc[idx]
        if pd.notna(s): churn_parts.append((1-float(s), 0.15))
        if len(churn_parts) >= 2:
            denom = sum(w for _, w in churn_parts)
            churn_values.append(sum(v*w for v,w in churn_parts)/denom)
        else:
            churn_values.append(np.nan)

    df["behavioral_loyalty_index"] = loyalty_values
    df["churn_signal_score"] = churn_values

    # Attach source labels for deterministic features. For dataset-relative
    # indices, mark DERIVED_REAL only if the row has deterministic source inputs.
    for idx, row in df.iterrows():
        fs = feature_sources[idx]
        fs["r_score"] = _derived_source(row, ["last_purchase_date"])
        fs["f_score"] = _derived_source(row, ["order_count"])
        fs["m_score"] = _derived_source(row, ["total_spending"])
        fs["rfm_score"] = "DERIVED_REAL" if all(fs.get(x)=="DERIVED_REAL" for x in ["r_score","f_score","m_score"]) else "DERIVED_MIXED"
        fs["customer_value_score"] = _derived_source(row, ["order_count", "total_spending"])
        engagement_inputs = [f for f in ["website_visits_30d","email_open_rate","cart_abandon_rate"] if not _blank_scalar(row.get(f))]
        fs["engagement_score"] = _derived_source(row, engagement_inputs) if len(engagement_inputs) >= 2 else "MISSING"
        loyalty_inputs = [f for f in ["last_purchase_date","order_count","total_spending","satisfaction_score","return_count"] if not _blank_scalar(row.get(f))]
        fs["behavioral_loyalty_index"] = _derived_source(row, loyalty_inputs) if len(loyalty_inputs) >= 3 else "MISSING"
        churn_inputs = [f for f in ["last_purchase_date","order_count","cart_abandon_rate","satisfaction_score"] if not _blank_scalar(row.get(f))]
        fs["churn_signal_score"] = _derived_source(row, churn_inputs) if len(churn_inputs) >= 2 else "MISSING"

    df["_feature_sources"] = feature_sources
    df["data_reliability"] = df.apply(_provenance_reliability, axis=1)

    def label(row):
        if pd.isna(row["rfm_score"]):
            return "Insufficient Data"
        r, f, m = row["r_score"], row["f_score"], row["m_score"]
        if r >= 4 and f >= 4 and m >= 4:
            return "Champions"
        if r >= 4 and f >= 3:
            return "Loyal / Active"
        if r <= 2 and f >= 3:
            return "At Risk"
        if r <= 2 and f <= 2:
            return "Dormant"
        if r >= 4 and f <= 2:
            return "New / Promising"
        return "Potential"

    df["rfm_segment"] = df.apply(label, axis=1)

    def value_tier(v):
        if pd.isna(v): return "Unknown"
        if v >= 0.80: return "High Value"
        if v >= 0.45: return "Mid Value"
        return "Low Value"
    df["customer_value_tier"] = df["customer_value_score"].map(value_tier)

    return df


def _coverage(df: pd.DataFrame, field: str) -> float:
    if field not in df.columns or len(df) == 0:
        return 0.0
    s = df[field]
    valid = s.notna()
    if s.dtype == object:
        valid = valid & s.astype(str).str.strip().ne("")
    return round(float(valid.mean() * 100), 1)


def summarize_customer_intelligence(df: pd.DataFrame) -> dict:
    """Summary for UI and segmentation readiness."""
    if df is None or df.empty:
        return {
            "customers": 0, "rfm_available_pct": 0.0, "avg_reliability_pct": 0.0,
            "segments": {}, "fields_with_data": {}, "derived_metrics": {},
            "source_breakdown": {}, "quality": {"score": 0, "status": "NOT_READY", "warnings": ["Chưa có dữ liệu."]},
            "kpis": {}, "feature_catalog": DERIVATION_CATALOG,
        }

    fields = [
        "age", "gender", "job", "location", "total_spending", "order_count",
        "average_order_value", "discount_usage", "last_purchase_date", "product_category",
        "channel", "device", "acquisition_source", "review_text", "monthly_income",
        "signup_date", "return_count", "website_visits_30d", "email_open_rate",
        "cart_abandon_rate", "satisfaction_score", "loyalty_tier",
    ]
    coverage = {field: _coverage(df, field) for field in fields}

    derived = [
        "recency_days", "average_order_value_final", "purchase_frequency_per_month",
        "return_rate", "discount_dependency", "engagement_score", "customer_value_score",
        "behavioral_loyalty_index", "churn_signal_score",
    ]
    derived_cov = {field: _coverage(df, field) for field in derived}

    rfm_pct = round(float(df["rfm_score"].notna().mean() * 100), 1) if "rfm_score" in df else 0.0
    reliability = round(float(pd.to_numeric(df.get("data_reliability"), errors="coerce").mean() * 100), 1) if "data_reliability" in df else 0.0

    # Intelligence quality is about usable behavioral evidence, not generic file quality.
    core_weights = {
        "identity_demographic": np.mean([coverage.get("age",0), coverage.get("job",0), coverage.get("location",0)]),
        "transaction": np.mean([coverage.get("total_spending",0), coverage.get("order_count",0), coverage.get("last_purchase_date",0)]),
        "behavior": np.mean([coverage.get("discount_usage",0), coverage.get("product_category",0), coverage.get("channel",0)]),
        "engagement": np.mean([coverage.get("website_visits_30d",0), coverage.get("email_open_rate",0), coverage.get("cart_abandon_rate",0)]),
        "rfm": rfm_pct,
        "provenance": reliability,
    }
    q_score = round(
        core_weights["transaction"]*0.27 + core_weights["rfm"]*0.23 +
        core_weights["identity_demographic"]*0.15 + core_weights["behavior"]*0.12 +
        core_weights["engagement"]*0.08 + core_weights["provenance"]*0.15,
        1,
    )
    q_status = "READY" if q_score >= 75 else "CAUTION" if q_score >= 55 else "NOT_READY"
    warnings = []
    if rfm_pct < 60: warnings.append("RFM chưa đủ cho phần lớn khách hàng; phân khúc hành vi có thể kém ổn định.")
    if reliability < 70: warnings.append("Tỷ lệ dữ liệu nguồn có độ tin cậy cao còn thấp; nên kiểm tra provenance trước khi mô phỏng.")
    if core_weights["transaction"] < 60: warnings.append("Thiếu dữ liệu giao dịch như số đơn, tổng chi tiêu hoặc ngày mua gần nhất.")
    if core_weights["engagement"] < 30: warnings.append("Ít dữ liệu tương tác; Engagement Score sẽ chỉ có ở một phần khách hàng.")

    def med(field):
        s = pd.to_numeric(df.get(field), errors="coerce") if field in df else pd.Series(dtype=float)
        return round(float(s.median()), 2) if s.notna().any() else None
    def mean(field):
        s = pd.to_numeric(df.get(field), errors="coerce") if field in df else pd.Series(dtype=float)
        return round(float(s.mean()), 3) if s.notna().any() else None

    high_value = int((df.get("customer_value_tier") == "High Value").sum()) if "customer_value_tier" in df else 0
    churn_high = int((pd.to_numeric(df.get("churn_signal_score"), errors="coerce") >= 0.70).sum()) if "churn_signal_score" in df else 0

    return {
        "customers": int(len(df)),
        "rfm_available_pct": rfm_pct,
        "avg_reliability_pct": reliability,
        "segments": df["rfm_segment"].value_counts(dropna=False).to_dict() if "rfm_segment" in df else {},
        "fields_with_data": coverage,
        "derived_metrics": derived_cov,
        "source_breakdown": _source_breakdown(df),
        "quality": {
            "score": q_score, "status": q_status, "dimensions": {k: round(float(v),1) for k,v in core_weights.items()},
            "warnings": warnings,
        },
        "kpis": {
            "median_recency_days": med("recency_days"),
            "median_order_count": med("order_count"),
            "median_total_spending": med("total_spending"),
            "median_aov": med("average_order_value_final"),
            "mean_engagement_score": mean("engagement_score"),
            "mean_loyalty_index": mean("behavioral_loyalty_index"),
            "high_value_customers": high_value,
            "high_churn_signal_customers": churn_high,
        },
        "feature_catalog": DERIVATION_CATALOG,
    }
