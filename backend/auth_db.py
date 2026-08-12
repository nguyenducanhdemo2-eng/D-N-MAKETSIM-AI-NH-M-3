
import sqlite3, secrets, hashlib
from datetime import datetime, timezone
from config import DB_PATH

def _conn():
    c=sqlite3.connect(DB_PATH, timeout=30); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); return c

def init_auth():
    with _conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS web_sessions(token TEXT PRIMARY KEY,user_id INTEGER NOT NULL,created_at TEXT NOT NULL,FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)")
        c.commit()

def create_session(user_id):
    token=secrets.token_urlsafe(32)
    with _conn() as c:
        c.execute('INSERT INTO web_sessions VALUES (?,?,?)',(token,int(user_id),datetime.now(timezone.utc).isoformat())); c.commit()
    return token

def get_user(token):
    if not token:return None
    with _conn() as c:
        r=c.execute('SELECT u.id,u.email FROM web_sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?',(token,)).fetchone()
        return dict(r) if r else None

def delete_session(token):
    if token:
        with _conn() as c:c.execute('DELETE FROM web_sessions WHERE token=?',(token,)); c.commit()
