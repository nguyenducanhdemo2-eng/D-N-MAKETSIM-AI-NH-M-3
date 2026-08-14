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
    if not (0<=pred[0]<=1 and 0<=act[0]<=1):
        raise ValueError('Tỷ lệ dự đoán và thực tế phải nằm trong khoảng 0 đến 1.')
    metrics=evaluate_predictions(pred,act)
    con=sqlite3.connect(db_path)
    cur=con.execute("""INSERT INTO campaign_feedback
        (experiment_id,predicted_conversion,actual_conversion,predicted_revenue,actual_revenue,
         mae,bias,calibration_factor,calibration_offset,notes,user_id,company_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (experiment_id,*pred,*act,predicted_revenue,actual_revenue,metrics["mae"],metrics["bias"],
         1.0,0.0,notes,user_id,company_id))
    feedback_id=int(cur.lastrowid)

    # Learn from the complete tenant/account history. Fitting on the single new
    # row always returned "insufficient" and could never affect later runs.
    sql='SELECT predicted_conversion,actual_conversion FROM campaign_feedback'
    params=[]; where=[]
    if user_id is not None:
        where.append('user_id=?'); params.append(int(user_id))
    elif company_id is not None:
        where.append('company_id=?'); params.append(int(company_id))
    if where:
        sql+=' WHERE '+' AND '.join(where)
    rows=con.execute(sql,tuple(params)).fetchall()
    all_pred=[float(r[0]) for r in rows]
    all_actual=[float(r[1]) for r in rows]
    cal=fit_scalar_calibration(all_pred,all_actual)
    con.execute(
        'UPDATE campaign_feedback SET calibration_factor=?,calibration_offset=? WHERE id=?',
        (float(cal.get('factor',1.0)),float(cal.get('offset',0.0)),feedback_id),
    )
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
