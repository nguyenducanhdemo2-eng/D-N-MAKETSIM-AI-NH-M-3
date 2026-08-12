"""PART 9-10: feedback loop helpers."""
from __future__ import annotations
import sqlite3
from datetime import datetime
import pandas as pd
from calibration import evaluate_predictions, fit_scalar_calibration

def record_outcome(db_path, experiment_id, predicted_conversion, actual_conversion, predicted_revenue=None, actual_revenue=None, notes=""):
    pred=[float(predicted_conversion)]; act=[float(actual_conversion)]
    metrics=evaluate_predictions(pred,act); cal=fit_scalar_calibration(pred,act)
    con=sqlite3.connect(db_path)
    con.execute("INSERT INTO campaign_feedback (experiment_id,predicted_conversion,actual_conversion,predicted_revenue,actual_revenue,mae,bias,calibration_factor,calibration_offset,notes) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (experiment_id,*pred,*act,predicted_revenue,actual_revenue,metrics["mae"],metrics["bias"],cal.get("factor",1),cal.get("offset",0),notes))
    con.commit(); con.close(); return metrics,cal

def feedback_history(db_path, limit=100):
    con=sqlite3.connect(db_path); df=pd.read_sql_query("SELECT * FROM campaign_feedback ORDER BY id DESC LIMIT ?",con,params=(limit,)); con.close(); return df

def latest_calibration(db_path):
    con=sqlite3.connect(db_path); row=con.execute("SELECT calibration_factor, calibration_offset FROM campaign_feedback ORDER BY id DESC LIMIT 1").fetchone(); con.close()
    return {"factor":float(row[0]),"offset":float(row[1])} if row else {"factor":1.0,"offset":0.0}
