"""PART 9-10: feedback loop helpers.

Production tenant hardening is additive only: callers may pass user_id/company_id so
feedback/calibration stays isolated per account/company. Existing callers without
those arguments keep the legacy behavior for backward compatibility.
"""
from __future__ import annotations
import sqlite3
import pandas as pd
from calibration import evaluate_predictions, fit_scalar_calibration


def record_outcome(db_path, experiment_id, predicted_conversion, actual_conversion,
                   predicted_revenue=None, actual_revenue=None, notes="",
                   user_id=None, company_id=None):
    pred=[float(predicted_conversion)]; act=[float(actual_conversion)]
    metrics=evaluate_predictions(pred,act); cal=fit_scalar_calibration(pred,act)
    con=sqlite3.connect(db_path)
    con.execute("""INSERT INTO campaign_feedback
        (experiment_id,predicted_conversion,actual_conversion,predicted_revenue,actual_revenue,
         mae,bias,calibration_factor,calibration_offset,notes,user_id,company_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (experiment_id,*pred,*act,predicted_revenue,actual_revenue,metrics["mae"],metrics["bias"],
         cal.get("factor",1),cal.get("offset",0),notes,user_id,company_id))
    con.commit(); con.close(); return metrics,cal


def feedback_history(db_path, limit=100, user_id=None, company_id=None):
    con=sqlite3.connect(db_path)
    sql="SELECT * FROM campaign_feedback"; params=[]; where=[]
    if user_id is not None:
        where.append("user_id=?"); params.append(int(user_id))
    elif company_id is not None:
        where.append("company_id=?"); params.append(int(company_id))
    if where: sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"; params.append(int(limit))
    df=pd.read_sql_query(sql,con,params=tuple(params)); con.close(); return df


def latest_calibration(db_path, user_id=None, company_id=None):
    con=sqlite3.connect(db_path)
    sql="SELECT calibration_factor, calibration_offset FROM campaign_feedback"; params=[]; where=[]
    if user_id is not None:
        where.append("user_id=?"); params.append(int(user_id))
    elif company_id is not None:
        where.append("company_id=?"); params.append(int(company_id))
    if where: sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT 1"
    row=con.execute(sql,tuple(params)).fetchone(); con.close()
    return {"factor":float(row[0]),"offset":float(row[1])} if row else {"factor":1.0,"offset":0.0}
