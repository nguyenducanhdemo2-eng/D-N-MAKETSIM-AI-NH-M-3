"""PART 5-7: Twin campaign simulation, paired what-if/A-B tests and optimization.
All predictions are explicitly MODELLED ESTIMATES, not ground truth.
"""
from __future__ import annotations
import json, math, re
from itertools import product
import numpy as np
import pandas as pd

CHANNELS = ["Facebook", "TikTok", "Google", "Instagram", "Email"]

def parse_campaign(text: str) -> dict:
    text = str(text or "")
    m = re.search(r"(\d{1,3}(?:[\.,]\d+)?)\s*%", text)
    discount = float(m.group(1).replace(",", ".")) if m else 0.0
    lower = text.lower()
    channels = [c for c in CHANNELS if c.lower() in lower]
    urgency = 1.0 if any(k in lower for k in ["limited", "hôm nay", "today", "cuối tuần", "khẩn", "last chance"]) else 0.0
    free_ship = 1.0 if any(k in lower for k in ["free ship", "miễn phí vận chuyển", "freeship"]) else 0.0
    premium = 1.0 if any(k in lower for k in ["cao cấp", "premium", "exclusive", "limited edition"]) else 0.0
    return {"discount_pct": min(max(discount,0),90), "channels": channels, "urgency": urgency, "free_shipping": free_ship, "premium": premium}

def _clip(x): return float(np.clip(x, 0, 1))
def _num(t, *keys):
    for k in keys:
        try:
            v = float(t.get(k));
            if math.isfinite(v): return v
        except Exception: pass
    return None

def simulate_twins(twins_df: pd.DataFrame, campaign_text: str, seed: int=42, use_llm: bool=False, ollama_fn=None, calibration: dict | None=None) -> dict:
    if twins_df is None or twins_df.empty:
        return {"status":"empty", "results":pd.DataFrame(), "summary":{}}
    spec = parse_campaign(campaign_text)
    rng = np.random.RandomState(seed)
    positive_spends=[]
    for _, tt in twins_df.iterrows():
        vv=_num(tt,"average_order_value","monetary","total_spending")
        if vv is not None and vv>0: positive_spends.append(vv)
    default_spend=float(np.median(positive_spends)) if positive_spends else 300000.0
    rows=[]
    for _, t in twins_df.iterrows():
        price = _num(t,"price_sensitivity","price_sensitivity_proxy")
        loyalty = _num(t,"loyalty_proxy")
        churn = _num(t,"churn_risk_proxy")
        readiness = _num(t,"purchase_readiness_proxy")
        value = _num(t,"value_proxy")
        spend = _num(t,"average_order_value","monetary","total_spending")
        if spend is None or spend <= 0: spend = default_spend
        # Transparent heuristic: discount helps price-sensitive customers, urgency helps ready customers.
        disc = spec["discount_pct"]/100
        base = 0.18
        if readiness is not None: base += 0.25*(readiness-0.5)
        if loyalty is not None: base += 0.12*(loyalty-0.5)
        if churn is not None: base -= 0.16*(churn-0.5)
        if price is not None: base += 0.28*disc*(0.5+price)
        else: base += 0.16*disc
        base += 0.04*spec["urgency"]
        base += 0.03*spec["free_shipping"]
        if spec["premium"] and loyalty is not None: base += 0.04*loyalty
        # Small bounded noise gives population variation, seeded for reproducibility.
        raw_conversion = _clip(base + rng.normal(0,0.025))
        factor=float((calibration or {}).get('factor',1.0))
        offset=float((calibration or {}).get('offset',0.0))
        conversion=_clip(factor*raw_conversion+offset)
        click = _clip(conversion + 0.10 + rng.normal(0,0.015))
        purchase_intent = _clip(conversion + 0.08)
        revenue = spend*(1-disc)*conversion
        sentiment = "positive" if conversion >= .55 else ("neutral" if conversion >= .32 else "negative")
        score = int(np.clip(round(1+9*conversion),1,10))
        rows.append({
            "twin_id": t.get("twin_id"), "segment_id": t.get("segment_id"),
            "conversion_probability": round(conversion,4), "click_probability": round(click,4),
            "raw_conversion_probability": round(raw_conversion,4),
            "purchase_intent": round(purchase_intent,4), "expected_revenue": round(revenue,2),
            "sentiment": sentiment, "score": score,
            "discount_pct": spec["discount_pct"], "campaign": campaign_text,
            "model_version":"heuristic_v1_calibrated" if calibration and (factor!=1.0 or offset!=0.0) else "heuristic_v1",
            "prediction_type":"modelled_estimate",
        })
    df=pd.DataFrame(rows)
    summary={"population":len(df),"conversion_rate":float(df.conversion_probability.mean()),"click_rate":float(df.click_probability.mean()),"purchase_intent":float(df.purchase_intent.mean()),"expected_revenue":float(df.expected_revenue.sum()),"discount_pct":spec["discount_pct"],"calibration":calibration or {"factor":1.0,"offset":0.0}}
    return {"status":"ok","results":df,"summary":summary,"campaign_spec":spec,"note":"Ước tính mô hình, chưa calibration."}

def paired_compare(twins_df: pd.DataFrame, campaigns: list[str], seed:int=42, calibration: dict | None=None) -> dict:
    outputs=[]
    per_campaign={}
    for i,c in enumerate(campaigns):
        r=simulate_twins(twins_df,c,seed=seed,calibration=calibration)
        if r["status"]!="ok": continue
        per_campaign[c]=r
        s=r["summary"].copy(); s["campaign"]=c; outputs.append(s)
    table=pd.DataFrame(outputs)
    if not table.empty:
        table=table.sort_values(["conversion_rate","expected_revenue"],ascending=False).reset_index(drop=True)
        table["rank"]=np.arange(1,len(table)+1)
    return {"status":"ok" if outputs else "empty","table":table,"runs":per_campaign}

def _candidate_message(discount, channel):
    return f"Ưu đãi {discount:.0f}% trên {channel}: mua ngay hôm nay, sản phẩm phù hợp nhu cầu khách hàng."

def optimize_marketing(twins_df: pd.DataFrame, budget: float, discount_options=None, channel_options=None, message_options=None, calibration: dict | None=None) -> dict:
    if twins_df is None or twins_df.empty: return {"status":"empty","candidates":pd.DataFrame()}
    budget=float(max(0,budget)); discounts=discount_options or [0,10,20,30,40]; channels=channel_options or CHANNELS[:4]
    rows=[]
    for d,ch in product(discounts,channels):
        campaign=_candidate_message(d,ch)
        sim=simulate_twins(twins_df,campaign,seed=42,calibration=calibration)
        s=sim["summary"]
        revenue_per_1000=float(s["expected_revenue"])/max(1,len(twins_df))*1000.0
        cost_per_1000=(budget/max(1,len(twins_df)))*1000.0 if budget>0 else 0.0
        roi=(revenue_per_1000-cost_per_1000)/cost_per_1000 if cost_per_1000>0 else 0.0
        score=0.55*s["conversion_rate"]+0.25*s["purchase_intent"]+0.20*max(-1,min(1,roi))/2
        rows.append({"campaign":campaign,"discount_pct":d,"channel":ch,"conversion_rate":s["conversion_rate"],"purchase_intent":s["purchase_intent"],"expected_revenue_index":revenue_per_1000,"budget":budget,"roi_index":roi,"optimization_score":score})
    table=pd.DataFrame(rows).sort_values("optimization_score",ascending=False).reset_index(drop=True)
    return {"status":"ok","candidates":table,"best":table.iloc[0].to_dict() if not table.empty else None,"note":"ROI/revenue là chỉ số mô phỏng; cần calibration bằng campaign thật."}
