
"""Server-side session storage with expiry and hashed bearer tokens."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

import config


def _conn():
    c=sqlite3.connect(config.DB_PATH,timeout=30)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA busy_timeout=30000')
    return c


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if parsed.tzinfo is None:
            parsed=parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError,ValueError):
        return None


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def init_auth():
    """Create/add session fields without preserving indefinitely valid sessions."""
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS web_sessions(
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT,
                last_seen_at TEXT,
                active_mode TEXT NOT NULL DEFAULT 'employee',
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        cols={r[1] for r in c.execute('PRAGMA table_info(web_sessions)').fetchall()}
        legacy_schema='expires_at' not in cols or 'last_seen_at' not in cols
        if 'expires_at' not in cols:
            c.execute('ALTER TABLE web_sessions ADD COLUMN expires_at TEXT')
        if 'last_seen_at' not in cols:
            c.execute('ALTER TABLE web_sessions ADD COLUMN last_seen_at TEXT')
        if 'active_mode' not in cols:
            c.execute("ALTER TABLE web_sessions ADD COLUMN active_mode TEXT DEFAULT 'employee'")
            c.execute("""
                UPDATE web_sessions
                SET active_mode=CASE
                    WHEN (SELECT role FROM users WHERE users.id=web_sessions.user_id)='admin' THEN 'admin'
                    ELSE 'employee'
                END
            """)

        # Tokens shipped in an older database may already have been exposed. The
        # one-time schema migration therefore revokes them instead of trusting or
        # silently extending them. Users sign in once to receive hashed tokens.
        if legacy_schema:
            c.execute('DELETE FROM web_sessions')

        # Defensive migration for partially upgraded installations.
        rows=c.execute("""
            SELECT token,created_at FROM web_sessions
            WHERE expires_at IS NULL OR expires_at=''
        """).fetchall()
        for row in rows:
            created=_parse_datetime(row['created_at'])
            expires=(created+timedelta(seconds=config.SESSION_MAX_AGE_SECONDS)) if created else _utcnow()
            c.execute(
                'UPDATE web_sessions SET expires_at=?,last_seen_at=COALESCE(last_seen_at,created_at) WHERE token=?',
                (_iso(expires),row['token']),
            )
        c.execute('CREATE INDEX IF NOT EXISTS idx_web_sessions_user ON web_sessions(user_id)')
        c.commit()


def create_session(user_id: int) -> str:
    """Return the cookie token while storing only its SHA-256 digest in SQLite."""
    init_auth()
    token=secrets.token_urlsafe(32)
    now=_utcnow()
    expires=now+timedelta(seconds=config.SESSION_MAX_AGE_SECONDS)
    with _conn() as c:
        account=c.execute('SELECT role FROM users WHERE id=?',(int(user_id),)).fetchone()
        active_mode='admin' if account and account['role']=='admin' else 'employee'
        c.execute(
            'INSERT INTO web_sessions(token,user_id,created_at,expires_at,last_seen_at,active_mode) VALUES (?,?,?,?,?,?)',
            (_token_digest(token),int(user_id),_iso(now),_iso(expires),_iso(now),active_mode),
        )
        c.commit()
    return token


def get_user(token: str | None):
    """Resolve a live session and enforce absolute plus inactivity timeouts."""
    if not token:
        return None
    init_auth()
    digest=_token_digest(token)
    now=_utcnow()
    with _conn() as c:
        # Raw-token lookup exists only to migrate an unexpired legacy row. New
        # sessions always store the digest, never the bearer token itself.
        row=c.execute("""
            SELECT s.token,s.user_id,s.created_at,s.expires_at,s.last_seen_at,s.active_mode,u.id,u.email,u.role
            FROM web_sessions s JOIN users u ON u.id=s.user_id
            WHERE s.token IN (?,?)
            ORDER BY CASE WHEN s.token=? THEN 0 ELSE 1 END
            LIMIT 1
        """,(digest,token,digest)).fetchone()
        if not row:
            return None

        created=_parse_datetime(row['created_at'])
        expires=_parse_datetime(row['expires_at'])
        last_seen=_parse_datetime(row['last_seen_at']) or created
        absolute_deadline=(created+timedelta(seconds=config.SESSION_MAX_AGE_SECONDS)) if created else now
        idle_deadline=(last_seen+timedelta(seconds=config.SESSION_IDLE_TIMEOUT_SECONDS)) if last_seen else now
        if not expires or now>=min(expires,absolute_deadline) or now>=idle_deadline:
            c.execute('DELETE FROM web_sessions WHERE token=?',(row['token'],))
            c.commit()
            return None

        if row['token']!=digest:
            try:
                c.execute('UPDATE web_sessions SET token=?,last_seen_at=? WHERE token=?',(digest,_iso(now),row['token']))
            except sqlite3.IntegrityError:
                c.execute('DELETE FROM web_sessions WHERE token=?',(row['token'],))
        else:
            c.execute('UPDATE web_sessions SET last_seen_at=? WHERE token=?',(_iso(now),digest))
        c.commit()
        active_mode=str(row['active_mode'] or '').lower()
        if row['role']!='admin' or active_mode not in ('admin','employee'):
            active_mode='employee'
        return {'id':int(row['id']),'email':row['email'],'active_mode':active_mode}


def set_session_mode(token: str | None, user_id: int, mode: str) -> bool:
    """Switch only the current session; employees can never elevate to ADMIN."""
    if not token:
        return False
    mode=str(mode or '').strip().lower()
    if mode not in ('admin','employee'):
        raise ValueError('Chế độ phải là admin hoặc employee.')
    init_auth()
    digest=_token_digest(token)
    with _conn() as c:
        account=c.execute('SELECT role,is_active,company_id FROM users WHERE id=?',(int(user_id),)).fetchone()
        if not account or not int(account['is_active'] or 0):
            return False
        if mode=='admin' and account['role']!='admin':
            raise PermissionError('Nhân viên không thể chuyển sang chế độ ADMIN.')
        if account['company_id'] is None:
            raise PermissionError('Tài khoản chưa thuộc doanh nghiệp nào.')
        cur=c.execute(
            'UPDATE web_sessions SET active_mode=?,last_seen_at=? WHERE token IN (?,?) AND user_id=?',
            (mode,_iso(_utcnow()),digest,token,int(user_id)),
        )
        c.commit()
        return bool(cur.rowcount)


def delete_session(token: str | None):
    if token:
        with _conn() as c:
            c.execute('DELETE FROM web_sessions WHERE token IN (?,?)',(_token_digest(token),token))
            c.commit()


def delete_all_sessions(user_id: int):
    with _conn() as c:
        c.execute('DELETE FROM web_sessions WHERE user_id=?',(int(user_id),))
        c.commit()
