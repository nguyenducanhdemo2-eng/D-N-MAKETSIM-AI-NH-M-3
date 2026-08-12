"""PART 8-9: evaluation, calibration and feedback learning."""
from __future__ import annotations
import json, math
import numpy as np
import pandas as pd

def evaluate_predictions(predicted, actual):
    p=np.asarray(predicted,dtype=float); a=np.asarray(actual,dtype=float)
    if len(p)!=len(a) or len(p)==0: raise ValueError("Predicted và actual phải cùng độ dài và không rỗng.")
    err=p-a; mae=float(np.mean(np.abs(err))); rmse=float(np.sqrt(np.mean(err**2))); bias=float(np.mean(err))
    denom=np.where(np.abs(a)<1e-9,np.nan,np.abs(a)); mape=float(np.nanmean(np.abs(err)/denom)) if np.isfinite(np.nanmean(np.abs(err)/denom)) else None
    return {"n":len(p),"mae":mae,"rmse":rmse,"bias":bias,"mape":mape}

def fit_scalar_calibration(predicted, actual):
    p=np.asarray(predicted,dtype=float); a=np.asarray(actual,dtype=float)
    mask=np.isfinite(p)&np.isfinite(a)&(p>=0)&(p<=1)&(a>=0)&(a<=1)
    if mask.sum()<3: return {"status":"insufficient","factor":1.0,"offset":0.0}
    p=p[mask]; a=a[mask]
    # Linear calibration a ~= alpha*p + beta; bounded later.
    A=np.column_stack([p,np.ones(len(p))]); alpha,beta=np.linalg.lstsq(A,a,rcond=None)[0]
    return {"status":"ok","factor":float(alpha),"offset":float(beta),"n":int(len(p))}

def apply_calibration(values, calibration):
    p=np.asarray(values,dtype=float); alpha=float(calibration.get("factor",1)); beta=float(calibration.get("offset",0))
    return np.clip(alpha*p+beta,0,1)
