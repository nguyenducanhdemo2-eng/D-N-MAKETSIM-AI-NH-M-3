"""PART 3 - DATA-DRIVEN PERSONA ENGINE

Builds one explainable persona per customer segment from real customer evidence.
Optional Ollama enrichment can improve naming/summary, but the statistical
profile and evidence remain the source of truth.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from typing import Optional

import pandas as pd
import requests


def _clean(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _mode(series: pd.Series) -> Optional[str]:
    if series is None:
        return None
    s = series.dropna().astype(str).str.strip()
    s = s[s != ""]
    return s.mode().iloc[0] if not s.empty else None


def _top_tokens(series: pd.Series, limit: int = 6) -> list[str]:
    text = " ".join(_clean(x).lower() for x in series.dropna())
    tokens = re.findall(r"[\wÀ-ỹ]{3,}", text, flags=re.UNICODE)
    stop = {"and", "the", "with", "cho", "các", "những", "khách", "hàng", "mua", "sản", "phẩm"}
    counter = Counter(x for x in tokens if x not in stop)
    return [x for x, _ in counter.most_common(limit)]


def _safe_float(v):
    try:
        if pd.isna(v):
            return None
        return float(v)
    except Exception:
        return None


def build_persona_from_segment(segment_id: int, group: pd.DataFrame, profile: dict) -> dict:
    """Create an evidence-backed persona. No random personality is generated."""
    size = len(group)
    top_gender = _mode(group.get("gender", pd.Series(dtype=object)))
    top_job = _mode(group.get("job", pd.Series(dtype=object)))
    top_location = _mode(group.get("location", pd.Series(dtype=object)))
    top_channel = _mode(group.get("channel", pd.Series(dtype=object)))
    top_category = _mode(group.get("product_category", pd.Series(dtype=object)))
    interests = _top_tokens(group.get("interest_keywords", pd.Series(dtype=object)), 6)
    pains = _top_tokens(group.get("pain_point", pd.Series(dtype=object)), 5)
    traits = _top_tokens(group.get("personality", pd.Series(dtype=object)), 5)

    age = _safe_float(group.get("age", pd.Series(dtype=float)).mean())
    spending = _safe_float(group.get("total_spending", pd.Series(dtype=float)).mean())
    aov = _safe_float(group.get("average_order_value", pd.Series(dtype=float)).mean())
    discount = _safe_float(group.get("discount_usage", pd.Series(dtype=float)).mean())
    price_sensitivity = _safe_float(group.get("price_sensitivity", pd.Series(dtype=float)).mean())
    reliability = _safe_float(group.get("data_reliability", pd.Series(dtype=float)).mean())

    rfm = profile.get("top_rfm_segment") or "Insufficient Data"
    if rfm != "Insufficient Data":
        base_name = str(rfm)
    elif top_channel and top_category:
        base_name = f"{top_channel} • {top_category}"
    elif top_category:
        base_name = str(top_category)
    elif interests:
        base_name = f"{interests[0].title()} Shoppers"
    else:
        base_name = f"Customer Segment {segment_id}"

    if price_sensitivity is not None:
        if price_sensitivity >= 0.70:
            behavior_label = "nhạy cảm với giá"
        elif price_sensitivity <= 0.30:
            behavior_label = "ít nhạy cảm với giá"
        else:
            behavior_label = "cân bằng giữa giá và giá trị"
    elif discount is not None:
        d = discount / 100 if discount > 1 else discount
        behavior_label = "nhạy cảm với khuyến mãi" if d >= .70 else "mức phản ứng khuyến mãi trung bình"
    else:
        behavior_label = "chưa đủ dữ liệu để kết luận về độ nhạy giá"

    summary_parts = [f"Nhóm gồm {size:,} khách hàng, {behavior_label}."]
    if top_job:
        summary_parts.append(f"Nghề nghiệp phổ biến: {top_job}.")
    if top_location:
        summary_parts.append(f"Khu vực phổ biến: {top_location}.")
    if interests:
        summary_parts.append(f"Mối quan tâm nổi bật: {', '.join(interests[:4])}.")
    if pains:
        summary_parts.append(f"Tín hiệu pain point: {', '.join(pains[:3])}.")

    evidence = {
        "sample_size": size,
        "age_mean": round(age, 2) if age is not None else None,
        "avg_total_spending": round(spending, 2) if spending is not None else None,
        "avg_order_value": round(aov, 2) if aov is not None else None,
        "discount_usage_mean": round(discount, 4) if discount is not None else None,
        "price_sensitivity_mean": round(price_sensitivity, 4) if price_sensitivity is not None else None,
        "data_reliability_mean": round(reliability, 4) if reliability is not None else None,
    }

    return {
        "segment_id": int(segment_id),
        "persona_name": base_name,
        "segment_size": size,
        "demographics": {
            "age_mean": round(age, 1) if age is not None else None,
            "gender": top_gender,
            "job": top_job,
            "location": top_location,
        },
        "behavior": {
            "rfm_segment": rfm,
            "channel": top_channel,
            "product_category": top_category,
            "average_order_value": round(aov, 2) if aov is not None else None,
            "discount_usage": round(discount, 4) if discount is not None else None,
            "price_sensitivity": round(price_sensitivity, 4) if price_sensitivity is not None else None,
        },
        "interests": interests,
        "pain_points": pains,
        "traits": traits,
        "behavior_label": behavior_label,
        "summary": " ".join(summary_parts),
        "evidence": evidence,
        "confidence": _persona_confidence(evidence, interests, pains),
        "generation_source": "real_data_profile",
    }


def _persona_confidence(evidence: dict, interests: list, pains: list) -> float:
    size = min(1.0, evidence.get("sample_size", 0) / 100.0)
    completeness_fields = [
        evidence.get("age_mean"), evidence.get("avg_total_spending"),
        evidence.get("avg_order_value"), evidence.get("data_reliability_mean")
    ]
    completeness = sum(v is not None for v in completeness_fields) / len(completeness_fields)
    text_signal = min(1.0, (len(interests) + len(pains)) / 8.0)
    reliability = evidence.get("data_reliability_mean")
    reliability = 0.5 if reliability is None else max(0.0, min(1.0, reliability))
    score = 0.25 * size + 0.30 * completeness + 0.20 * text_signal + 0.25 * reliability
    return round(max(0.0, min(1.0, score)), 3)


def build_data_driven_personas(labeled_df: pd.DataFrame, profiles: dict) -> list[dict]:
    if labeled_df is None or labeled_df.empty or "segment_id" not in labeled_df.columns:
        return []
    personas = []
    for sid, group in labeled_df.groupby("segment_id", sort=True):
        profile = profiles.get(int(sid), {}) if isinstance(profiles, dict) else {}
        personas.append(build_persona_from_segment(int(sid), group, profile))
    return personas


def enrich_personas_with_ollama(personas: list[dict], host: str, model: str, timeout: int = 60) -> list[dict]:
    """Optional naming/summary enrichment. Keeps evidence unchanged."""
    if not personas:
        return personas
    for persona in personas:
        prompt = f"""Bạn là chuyên gia nghiên cứu khách hàng. Dựa DUY NHẤT trên dữ liệu JSON dưới đây,
đặt tên persona bằng tiếng Việt ngắn gọn và viết mô tả 2 câu. Không được bịa thêm dữ liệu.
JSON: {json.dumps(persona, ensure_ascii=False)}
Trả về JSON: {{\"name\": \"...\", \"summary\": \"...\"}}"""
        try:
            resp = requests.post(
                f"{host.rstrip('/')}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False, "format": "json"},
                timeout=timeout,
            )
            resp.raise_for_status()
            raw = resp.json().get("response", "{}")
            data = json.loads(raw)
            if data.get("name"):
                persona["persona_name"] = str(data["name"]).strip()
            if data.get("summary"):
                persona["summary"] = str(data["summary"]).strip()
            persona["generation_source"] = "real_data_profile+ollama"
        except Exception:
            # Fallback to deterministic profile; do not fail the whole segment set.
            persona["generation_source"] = "real_data_profile"
    return personas
