"""ADMIN / multi-company organization layer for MarketSim AI.

Additive only: this module does not change customer intelligence, segmentation,
Digital Twin generation, simulation formulas, or AI Learning algorithms.

Architecture:
- companies: one tenant / business
- one ADMIN account owns one company (current product rule)
- employees join a company using that company's join_code
- all ADMIN reads are scoped by company_id

Legacy compatibility:
- existing admin_profiles and admin_owner_id are preserved
- existing ADMIN + employees are migrated into a company without deleting data
"""
from __future__ import annotations

import os
import re
import secrets
import sqlite3
from typing import Any

import config


def _conn():
    c = sqlite3.connect(config.DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


def _table_columns(c, table: str) -> set[str]:
    return {r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}


def normalize_join_code(value: str | None) -> str:
    """Normalize copy/pasted company join codes without weakening tenant checks.

    Accepted examples for the generated code MS-ABCD-EFGH:
      - MS-ABCD-EFGH
      - ms-abcd-efgh
      - " MS-ABCD-EFGH "
      - MS ABCD EFGH
      - MSABCDefgh
    The normalized value is always returned as MS-XXXX-XXXX when possible.
    """
    raw = (value or '').strip().upper()
    if not raw:
        return ''
    # Normalize common Unicode dash characters created by mobile/office copy-paste.
    raw = re.sub(r'[‐‑‒–—―−]+', '-', raw)
    compact = re.sub(r'[^A-Z0-9]', '', raw)
    if len(compact) == 10 and compact.startswith('MS'):
        return f"MS-{compact[2:6]}-{compact[6:10]}"
    return raw.replace(' ', '')


def _reconcile_memberships(c: sqlite3.Connection) -> dict[str, int]:
    """Repair only unambiguous legacy membership links.

    company_id is treated as the primary tenant link when present. If it is
    missing but admin_owner_id points to an ADMIN that owns a company, the
    company_id can be restored safely. No employee is moved from one explicit
    company_id to another company here.
    """
    repaired_company = 0
    repaired_owner = 0
    repaired_admin = 0

    # Every company owner must point back to its own company.
    owners = c.execute("SELECT id,owner_admin_id FROM companies").fetchall()
    for company in owners:
        cur = c.execute(
            "UPDATE users SET role='admin',admin_owner_id=NULL,company_id=? "
            "WHERE id=? AND (company_id IS NULL OR company_id=?) "
            "AND (role!='admin' OR admin_owner_id IS NOT NULL OR company_id IS NULL)",
            (int(company['id']), int(company['owner_admin_id']), int(company['id'])),
        )
        repaired_admin += max(0, int(cur.rowcount or 0))

    # Old employee records sometimes only had admin_owner_id.
    cur = c.execute("""
        UPDATE users
        SET company_id=(SELECT co.id FROM companies co WHERE co.owner_admin_id=users.admin_owner_id)
        WHERE role='employee' AND company_id IS NULL AND admin_owner_id IS NOT NULL
          AND EXISTS (SELECT 1 FROM companies co WHERE co.owner_admin_id=users.admin_owner_id)
    """)
    repaired_company += max(0, int(cur.rowcount or 0))

    # When company_id is known, keep the legacy admin_owner_id synchronized.
    cur = c.execute("""
        UPDATE users
        SET admin_owner_id=(SELECT co.owner_admin_id FROM companies co WHERE co.id=users.company_id)
        WHERE role='employee' AND company_id IS NOT NULL
          AND EXISTS (SELECT 1 FROM companies co WHERE co.id=users.company_id)
          AND (admin_owner_id IS NULL OR admin_owner_id != (SELECT co.owner_admin_id FROM companies co WHERE co.id=users.company_id))
    """)
    repaired_owner += max(0, int(cur.rowcount or 0))
    return {
        'company_id_repaired': repaired_company,
        'admin_owner_repaired': repaired_owner,
        'admin_repaired': repaired_admin,
    }


def init_admin_schema():
    """Add multi-company schema without resetting or deleting existing data."""
    with _conn() as c:
        user_cols = _table_columns(c, "users")
        migrations = [
            ("role", "TEXT NOT NULL DEFAULT 'employee'"),
            ("admin_owner_id", "INTEGER"),
            ("display_name", "TEXT"),
            ("is_active", "INTEGER NOT NULL DEFAULT 1"),
            ("company_id", "INTEGER"),
            ("ai_provider", "TEXT NOT NULL DEFAULT 'groq'"),
        ]
        for name, definition in migrations:
            if name not in user_cols:
                c.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")

        c.execute("""
            CREATE TABLE IF NOT EXISTS companies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_name TEXT NOT NULL,
                join_code TEXT UNIQUE NOT NULL,
                owner_admin_id INTEGER UNIQUE NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(owner_admin_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # Kept for backward compatibility with the earlier ADMIN patch.
        c.execute("""
            CREATE TABLE IF NOT EXISTS admin_profiles (
                admin_user_id INTEGER PRIMARY KEY,
                organization_name TEXT DEFAULT 'Doanh nghiệp của tôi',
                join_code TEXT UNIQUE NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(admin_user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS activity_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                endpoint TEXT,
                method TEXT,
                status_code INTEGER,
                details TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS company_memberships (
                user_id INTEGER PRIMARY KEY,
                company_id INTEGER NOT NULL,
                admin_id INTEGER NOT NULL,
                joined_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE,
                FOREIGN KEY(admin_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_users_admin_owner ON users(admin_owner_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_users_company ON users(company_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_users_company_role_created ON users(company_id, role, created_at)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_activity_user_created ON activity_logs(user_id, created_at DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_company_memberships_company ON company_memberships(company_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_company_memberships_admin ON company_memberships(admin_id)")

        # ---- Legacy migration: each old ADMIN profile becomes one company. ----
        profiles = c.execute("""
            SELECT p.admin_user_id,p.organization_name,p.join_code
            FROM admin_profiles p
            JOIN users u ON u.id=p.admin_user_id
            WHERE u.role='admin'
            ORDER BY p.admin_user_id
        """).fetchall()
        for p in profiles:
            existing = c.execute("SELECT id FROM companies WHERE owner_admin_id=?", (p["admin_user_id"],)).fetchone()
            if existing:
                company_id = int(existing[0])
            else:
                # join_code came from the old unique table, so reuse it if possible.
                try:
                    cur = c.execute("""
                        INSERT INTO companies(organization_name,join_code,owner_admin_id,is_active)
                        VALUES(?,?,?,1)
                    """, (p["organization_name"] or "Doanh nghiệp của tôi", p["join_code"], p["admin_user_id"]))
                    company_id = int(cur.lastrowid)
                except sqlite3.IntegrityError:
                    row = c.execute("SELECT id FROM companies WHERE join_code=?", (p["join_code"],)).fetchone()
                    if not row:
                        continue
                    company_id = int(row[0])
            c.execute("UPDATE users SET company_id=? WHERE id=?", (company_id, p["admin_user_id"]))
            c.execute("UPDATE users SET company_id=? WHERE admin_owner_id=? AND company_id IS NULL", (company_id, p["admin_user_id"]))

        _reconcile_memberships(c)

        # Dedicated membership mirror. This does not replace users.company_id;
        # it gives the ADMIN screen one stable source to recover from when old
        # installations contain partially migrated employee rows.
        c.execute("""
            INSERT INTO company_memberships(user_id,company_id,admin_id,joined_at,updated_at)
            SELECT u.id,u.company_id,co.owner_admin_id,
                   COALESCE(u.created_at,CURRENT_TIMESTAMP),CURRENT_TIMESTAMP
            FROM users u
            JOIN companies co ON co.id=u.company_id
            WHERE u.role='employee' AND u.company_id IS NOT NULL
            ON CONFLICT(user_id) DO UPDATE SET
                company_id=excluded.company_id,
                admin_id=excluded.admin_id,
                updated_at=CURRENT_TIMESTAMP
        """)
        c.commit()


def _new_join_code() -> str:
    init_admin_schema()
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        a = ''.join(secrets.choice(alphabet) for _ in range(4))
        b = ''.join(secrets.choice(alphabet) for _ in range(4))
        code = f"MS-{a}-{b}"
        with _conn() as c:
            if not c.execute("SELECT 1 FROM companies WHERE join_code=?", (code,)).fetchone() and not c.execute("SELECT 1 FROM admin_profiles WHERE join_code=?", (code,)).fetchone():
                return code


def admin_count() -> int:
    init_admin_schema()
    with _conn() as c:
        return int(c.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0] or 0)


def company_count() -> int:
    init_admin_schema()
    with _conn() as c:
        return int(c.execute("SELECT COUNT(*) FROM companies WHERE is_active=1").fetchone()[0] or 0)


def get_account(user_id: int) -> dict | None:
    init_admin_schema()
    with _conn() as c:
        r = c.execute("""
            SELECT id,email,created_at,role,admin_owner_id,display_name,is_active,company_id,ai_provider
            FROM users WHERE id=?
        """, (int(user_id),)).fetchone()
        return dict(r) if r else None


def _admin_company(admin_id: int) -> dict | None:
    init_admin_schema()
    with _conn() as c:
        r = c.execute("""
            SELECT c.id AS company_id,c.organization_name,c.join_code,c.is_active,c.created_at,c.updated_at,
                   c.owner_admin_id,u.email,u.display_name
            FROM companies c JOIN users u ON u.id=c.owner_admin_id
            WHERE c.owner_admin_id=?
        """, (int(admin_id),)).fetchone()
        return dict(r) if r else None


def _canonicalize_company_join_code(c: sqlite3.Connection, company_row: sqlite3.Row | dict) -> dict:
    """Return a company row with a canonical join code and safely repair dirty formatting.

    Older/local databases can contain a visually correct code with Unicode dashes,
    spaces or lower-case characters. The login form normalizes what the employee
    types, so comparing that normalized input to the raw stored string can produce
    a false "code does not exist" result.  This helper makes the DB representation
    canonical (MS-XXXX-XXXX) when doing so cannot collide with another company.
    """
    row = dict(company_row)
    stored = str(row.get('join_code') or '')
    canonical = normalize_join_code(stored)
    if not canonical:
        return row
    if canonical != stored:
        company_id = int(row['company_id'])
        owner_admin_id = int(row['id'])
        conflict = c.execute(
            "SELECT id FROM companies WHERE UPPER(join_code)=? AND id!=?",
            (canonical, company_id),
        ).fetchone()
        profile_conflict = c.execute(
            "SELECT admin_user_id FROM admin_profiles WHERE UPPER(join_code)=? AND admin_user_id!=?",
            (canonical, owner_admin_id),
        ).fetchone()
        if not conflict and not profile_conflict:
            c.execute(
                "UPDATE companies SET join_code=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (canonical, company_id),
            )
            # Keep the compatibility profile synchronized only for the SAME ADMIN.
            c.execute(
                "UPDATE admin_profiles SET join_code=?,updated_at=CURRENT_TIMESTAMP WHERE admin_user_id=?",
                (canonical, owner_admin_id),
            )
            row['join_code'] = canonical
    return row


def _company_rows_for_join_lookup(c: sqlite3.Connection) -> list[sqlite3.Row]:
    return c.execute("""
        SELECT u.id,u.email,u.display_name,c.id AS company_id,c.organization_name,c.join_code,
               c.owner_admin_id,c.is_active
        FROM companies c
        JOIN users u ON u.id=c.owner_admin_id
        WHERE c.is_active=1 AND u.role='admin' AND COALESCE(u.is_active,1)=1
        ORDER BY c.id
    """).fetchall()


def _migrate_legacy_profile_for_join_code(c: sqlite3.Connection, code: str) -> dict | None:
    """Recover a legacy ADMIN profile that has no companies row yet.

    We never accept a stale admin_profiles code when the ADMIN already owns a
    company, because a regenerated old code must stay invalid.  This path is only
    for genuinely unmigrated installations.
    """
    rows = c.execute("""
        SELECT p.admin_user_id AS id,u.email,u.display_name,p.organization_name,p.join_code,u.company_id
        FROM admin_profiles p
        JOIN users u ON u.id=p.admin_user_id
        LEFT JOIN companies co ON co.owner_admin_id=p.admin_user_id
        WHERE co.id IS NULL AND u.role='admin' AND COALESCE(u.is_active,1)=1
        ORDER BY p.admin_user_id
    """).fetchall()
    for legacy in rows:
        if normalize_join_code(legacy['join_code']) != code:
            continue
        canonical = normalize_join_code(legacy['join_code']) or code
        conflict = c.execute("SELECT id FROM companies WHERE UPPER(join_code)=?", (canonical,)).fetchone()
        if conflict:
            return None
        cur = c.execute("""
            INSERT INTO companies(organization_name,join_code,owner_admin_id,is_active)
            VALUES(?,?,?,1)
        """, (legacy['organization_name'] or 'Doanh nghiệp của tôi', canonical, int(legacy['id'])))
        company_id = int(cur.lastrowid)
        c.execute("UPDATE users SET company_id=? WHERE id=?", (company_id, int(legacy['id'])))
        c.execute("""
            UPDATE users SET company_id=?
            WHERE role='employee' AND admin_owner_id=? AND company_id IS NULL
        """, (company_id, int(legacy['id'])))
        c.execute(
            "UPDATE admin_profiles SET join_code=?,updated_at=CURRENT_TIMESTAMP WHERE admin_user_id=?",
            (canonical, int(legacy['id'])),
        )
        _reconcile_memberships(c)
        r = c.execute("""
            SELECT u.id,u.email,u.display_name,c.id AS company_id,c.organization_name,c.join_code,
                   c.owner_admin_id,c.is_active
            FROM companies c JOIN users u ON u.id=c.owner_admin_id
            WHERE c.id=?
        """, (company_id,)).fetchone()
        return dict(r) if r else None
    return None


def find_admin_by_join_code(join_code: str) -> dict | None:
    """Resolve a join code without false negatives from formatting/legacy rows.

    Security rule: the active companies.join_code remains the source of truth.
    A legacy admin_profiles code is considered only when that ADMIN does not yet
    own a companies row, so regenerating a code still invalidates the old code.
    """
    init_admin_schema()
    code = normalize_join_code(join_code)
    if not code:
        return None
    with _conn() as c:
        _reconcile_memberships(c)

        # Fast path for normal databases.
        r = c.execute("""
            SELECT u.id,u.email,u.display_name,c.id AS company_id,c.organization_name,c.join_code,
                   c.owner_admin_id,c.is_active
            FROM companies c JOIN users u ON u.id=c.owner_admin_id
            WHERE UPPER(c.join_code)=? AND c.is_active=1
              AND u.role='admin' AND COALESCE(u.is_active,1)=1
        """, (code,)).fetchone()
        if r:
            result = _canonicalize_company_join_code(c, r)
            c.commit()
            return result

        # Robust path: normalize the stored value too. This fixes codes copied
        # from a DB that contains Unicode dashes/spaces/lower-case formatting.
        for row in _company_rows_for_join_lookup(c):
            if normalize_join_code(row['join_code']) == code:
                result = _canonicalize_company_join_code(c, row)
                c.commit()
                return result

        # Last resort for a genuinely old DB that has admin_profiles but no
        # companies row for that ADMIN. Migrate it immediately so registration
        # and ADMIN views use one consistent tenant source afterwards.
        migrated = _migrate_legacy_profile_for_join_code(c, code)
        c.commit()
        return migrated



def _sync_employee_membership(c: sqlite3.Connection, user_id: int) -> dict | None:
    """Synchronize one employee's durable company link without guessing tenants."""
    row = c.execute("""
        SELECT u.id,u.role,u.company_id,u.admin_owner_id,co.owner_admin_id,co.organization_name
        FROM users u
        LEFT JOIN companies co ON co.id=u.company_id
        WHERE u.id=?
    """, (int(user_id),)).fetchone()
    if not row or row["role"] != "employee" or row["company_id"] is None or row["owner_admin_id"] is None:
        return None
    company_id = int(row["company_id"])
    admin_id = int(row["owner_admin_id"])
    # company_id is the authoritative tenant when it is present. Keep the old
    # admin_owner_id field synchronized for backward compatibility.
    if row["admin_owner_id"] is None or int(row["admin_owner_id"]) != admin_id:
        c.execute("UPDATE users SET admin_owner_id=? WHERE id=?", (admin_id, int(user_id)))
    c.execute("""
        INSERT INTO company_memberships(user_id,company_id,admin_id,joined_at,updated_at)
        VALUES(?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
            company_id=excluded.company_id,
            admin_id=excluded.admin_id,
            updated_at=CURRENT_TIMESTAMP
    """, (int(user_id), company_id, admin_id))
    return {
        "user_id": int(user_id),
        "company_id": company_id,
        "admin_id": admin_id,
        "organization_name": row["organization_name"],
    }


def employee_visible_to_admin(admin_id: int, user_id: int) -> bool:
    """True only when both authoritative tenant fields point to this ADMIN.

    `users.company_id` is the source of truth. `company_memberships` is a durable
    mirror used for recovery/auditing, never a rotating slot list. This makes
    the check independent of how many employees the company already has.
    """
    init_admin_schema()
    company = _admin_company(admin_id)
    if not company:
        return False
    company_id = int(company["company_id"])
    with _conn() as c:
        _reconcile_memberships(c)
        _sync_employee_membership(c, user_id)
        row = c.execute("""
            SELECT 1
            FROM users u
            JOIN company_memberships m ON m.user_id=u.id
            WHERE u.id=? AND u.role='employee'
              AND u.company_id=? AND u.admin_owner_id=?
              AND m.company_id=? AND m.admin_id=?
        """, (int(user_id), company_id, int(admin_id), company_id, int(admin_id))).fetchone()
        c.commit()
        return bool(row)


def repair_company_memberships(admin_id: int) -> dict:
    """Repair only links that can be proven to belong to this ADMIN's company."""
    require_admin_account(admin_id)
    company = _admin_company(admin_id)
    company_id = int(company["company_id"])
    repaired = 0
    with _conn() as c:
        base = _reconcile_memberships(c)
        candidates = c.execute("""
            SELECT id FROM users
            WHERE role='employee'
              AND (
                    company_id=?
                    OR (company_id IS NULL AND admin_owner_id=?)
                  )
        """, (company_id, int(admin_id))).fetchall()
        for row in candidates:
            before = c.execute("SELECT company_id,admin_id FROM company_memberships WHERE user_id=?", (int(row["id"]),)).fetchone()
            synced = _sync_employee_membership(c, int(row["id"]))
            after = c.execute("SELECT company_id,admin_id FROM company_memberships WHERE user_id=?", (int(row["id"]),)).fetchone()
            if synced and (before is None or tuple(before) != tuple(after)):
                repaired += 1
        c.commit()
    return {
        "company_id": company_id,
        "organization_name": company.get("organization_name"),
        "membership_rows_repaired": repaired,
        "legacy_repairs": base,
    }


def attach_employee(user_id: int, admin_id: int, display_name: str = '') -> dict:
    """Attach one employee without replacing any existing company member.

    There is deliberately no employee-capacity limit. The operation updates only
    the new/current `user_id`, then verifies that the company's pre-existing
    employee IDs are still present before committing.
    """
    init_admin_schema()
    company = _admin_company(admin_id)
    if not company or not int(company.get("is_active") or 0):
        raise ValueError("Doanh nghiệp không tồn tại hoặc đã bị vô hiệu hóa.")
    company_id = int(company["company_id"])
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        try:
            current = c.execute(
                "SELECT id,role,company_id,admin_owner_id FROM users WHERE id=?",
                (int(user_id),),
            ).fetchone()
            if not current:
                raise ValueError("Không tìm thấy tài khoản nhân viên vừa tạo.")
            existing_company = current["company_id"]
            if existing_company is not None and int(existing_company) != company_id:
                raise ValueError("Tài khoản này đã thuộc một doanh nghiệp khác.")
            if current["role"] == "admin":
                raise ValueError("Tài khoản quản trị viên không thể đăng ký lại dưới vai trò nhân viên.")

            # Snapshot the existing team. No later statement in this transaction
            # is allowed to make one of these IDs disappear from the company.
            existing_ids = {int(r[0]) for r in c.execute(
                "SELECT id FROM users WHERE company_id=? AND role='employee' AND id!=?",
                (company_id, int(user_id)),
            ).fetchall()}

            c.execute("""
                UPDATE users
                SET role='employee', admin_owner_id=?, company_id=?, display_name=?, is_active=1
                WHERE id=?
            """, (int(admin_id), company_id, (display_name or "").strip() or None, int(user_id)))

            membership = _sync_employee_membership(c, int(user_id))
            if not membership:
                raise ValueError("Không thể hoàn tất liên kết tài khoản với doanh nghiệp.")

            visible = c.execute("""
                SELECT 1 FROM company_memberships
                WHERE user_id=? AND company_id=? AND admin_id=?
            """, (int(user_id), company_id, int(admin_id))).fetchone()
            if not visible:
                raise ValueError("Tài khoản đã tạo nhưng chưa được thêm vào danh sách nhân viên. Hệ thống đã hủy thao tác để tránh dữ liệu lệch.")

            after_ids = {int(r[0]) for r in c.execute(
                "SELECT id FROM users WHERE company_id=? AND role='employee'",
                (company_id,),
            ).fetchall()}
            if int(user_id) not in after_ids or not existing_ids.issubset(after_ids):
                raise ValueError("Phát hiện danh sách nhân viên bị thay đổi ngoài dự kiến. Hệ thống đã hủy đăng ký để bảo toàn nhân viên cũ.")

            c.commit()
        except Exception:
            c.rollback()
            raise

    return {
        "user_id": int(user_id),
        "admin_id": int(admin_id),
        "company_id": company_id,
        "organization_name": company.get("organization_name"),
        "membership_verified": True,
    }


def create_company_admin(user_id: int, display_name: str = '', organization_name: str = '') -> dict:
    """Create one independent business tenant + its ADMIN. Multiple businesses are allowed."""
    init_admin_schema()
    organization_name = (organization_name or '').strip()
    if not organization_name:
        raise ValueError("Vui lòng nhập tên doanh nghiệp.")
    code = _new_join_code()
    with _conn() as c:
        # Prevent promoting an account already attached to another tenant.
        existing = c.execute("SELECT role,company_id FROM users WHERE id=?", (int(user_id),)).fetchone()
        if not existing:
            raise ValueError("Không tìm thấy tài khoản ADMIN vừa tạo.")
        if existing["company_id"] is not None:
            raise ValueError("Tài khoản này đã thuộc một doanh nghiệp.")

        c.execute("""
            UPDATE users SET role='admin', admin_owner_id=NULL, display_name=?, is_active=1 WHERE id=?
        """, ((display_name or '').strip() or None, int(user_id)))
        cur = c.execute("""
            INSERT INTO companies(organization_name,join_code,owner_admin_id,is_active)
            VALUES(?,?,?,1)
        """, (organization_name, code, int(user_id)))
        company_id = int(cur.lastrowid)
        c.execute("UPDATE users SET company_id=? WHERE id=?", (company_id, int(user_id)))
        # Keep old admin_profiles synchronized for compatibility with existing code/backups.
        c.execute("""
            INSERT OR REPLACE INTO admin_profiles(admin_user_id,organization_name,join_code,created_at,updated_at)
            VALUES(?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
        """, (int(user_id), organization_name, code))
        c.commit()
    return {"company_id": company_id, "organization_name": organization_name, "join_code": code}


def make_first_admin(user_id: int, display_name: str = '', organization_name: str = '') -> str:
    """Backward-compatible alias. It no longer enforces 'first only'."""
    return create_company_admin(user_id, display_name, organization_name)["join_code"]


def require_admin_account(user_id: int) -> dict:
    a = get_account(user_id)
    if not a or a.get('role') != 'admin' or not int(a.get('is_active') or 0):
        raise PermissionError("Bạn không có quyền ADMIN.")
    company = _admin_company(user_id)
    if not company or not int(company.get('is_active') or 0):
        raise PermissionError("Doanh nghiệp của tài khoản ADMIN không hoạt động.")
    return a


def require_employee_account(user_id: int) -> dict:
    """Reject ADMIN accounts from every employee/business-workspace API."""
    account=get_account(user_id)
    if not account or account.get('role')!='employee' or not int(account.get('is_active') or 0):
        raise PermissionError('Bạn không có quyền sử dụng khu vực nhân viên.')
    if account.get('company_id') is None:
        raise PermissionError('Tài khoản nhân viên chưa thuộc doanh nghiệp nào. Hãy liên hệ ADMIN.')
    return account


def set_user_ai_provider(user_id: int, provider: str) -> str:
    """Persist an AI provider per account; never mutate a process-global setting."""
    provider=str(provider or '').strip().lower()
    if provider not in ('groq','ollama'):
        raise ValueError('Provider phải là groq hoặc ollama.')
    with _conn() as c:
        cur=c.execute('UPDATE users SET ai_provider=? WHERE id=?',(provider,int(user_id)))
        if not cur.rowcount:
            raise ValueError('Không tìm thấy tài khoản.')
        c.commit()
    return provider


def get_admin_profile(admin_id: int) -> dict | None:
    require_admin_account(admin_id)
    return _admin_company(admin_id)


def regenerate_join_code(admin_id: int) -> str:
    require_admin_account(admin_id)
    code = _new_join_code()
    with _conn() as c:
        c.execute("UPDATE companies SET join_code=?,updated_at=CURRENT_TIMESTAMP WHERE owner_admin_id=?", (code, int(admin_id)))
        c.execute("UPDATE admin_profiles SET join_code=?,updated_at=CURRENT_TIMESTAMP WHERE admin_user_id=?", (code, int(admin_id)))
        c.commit()
    return code


def team_user_ids(admin_id: int, include_admin: bool = True) -> list[int]:
    require_admin_account(admin_id)
    company = _admin_company(admin_id)
    company_id = int(company["company_id"])
    with _conn() as c:
        rows = c.execute("SELECT id,role FROM users WHERE company_id=? AND is_active IN (0,1) ORDER BY id", (company_id,)).fetchall()
    ids = [int(r["id"]) for r in rows if include_admin or r["role"] != "admin"]
    return ids


def set_employee_active(admin_id: int, employee_id: int, active: bool):
    require_admin_account(admin_id)
    company = _admin_company(admin_id)
    with _conn() as c:
        r = c.execute("""
            SELECT id FROM users WHERE id=? AND company_id=? AND role='employee'
        """, (int(employee_id), int(company["company_id"]))).fetchone()
        if not r:
            raise ValueError("Không tìm thấy nhân viên thuộc doanh nghiệp này.")
        c.execute("UPDATE users SET is_active=? WHERE id=?", (1 if active else 0, int(employee_id)))
        if not active:
            c.execute("DELETE FROM web_sessions WHERE user_id=?", (int(employee_id),))
        c.commit()


def record_activity(user_id: int, action: str, endpoint: str = '', method: str = '', status_code: int | None = None, details: str = ''):
    try:
        init_admin_schema()
        with _conn() as c:
            c.execute("""
                INSERT INTO activity_logs(user_id,action,endpoint,method,status_code,details)
                VALUES(?,?,?,?,?,?)
            """, (int(user_id), str(action)[:160], str(endpoint)[:300], str(method)[:12], status_code, str(details or '')[:1500]))
            c.commit()
    except Exception:
        pass


def _placeholders(ids: list[int]) -> str:
    return ','.join('?' for _ in ids) or 'NULL'


def admin_overview(admin_id: int) -> dict[str, Any]:
    require_admin_account(admin_id)
    profile = _admin_company(admin_id) or {}
    company_id = int(profile.get("company_id") or 0)
    ids = team_user_ids(admin_id, include_admin=True)
    staff_ids = [i for i in ids if i != int(admin_id)]
    ph = _placeholders(ids)
    with _conn() as c:
        staff_total = int(c.execute("SELECT COUNT(*) FROM users WHERE company_id=? AND role='employee'", (company_id,)).fetchone()[0] or 0)
        staff_active = int(c.execute("SELECT COUNT(*) FROM users WHERE company_id=? AND role='employee' AND is_active=1", (company_id,)).fetchone()[0] or 0)
        if staff_ids:
            sph = _placeholders(staff_ids)
            active_today = int(c.execute(f"""
                SELECT COUNT(DISTINCT user_id) FROM activity_logs
                WHERE user_id IN ({sph}) AND date(created_at)=date('now','localtime')
            """, staff_ids).fetchone()[0] or 0)
        else:
            active_today = 0

        datasets = int(c.execute(f"SELECT COUNT(*) FROM uploaded_datasets WHERE user_id IN ({ph})", ids).fetchone()[0] or 0)
        customers = int(c.execute(f"""
            SELECT COUNT(*) FROM canonical_customers cc
            JOIN uploaded_datasets u ON u.id=cc.upload_id
            WHERE u.user_id IN ({ph})
        """, ids).fetchone()[0] or 0)
        projects = int(c.execute(f"SELECT COUNT(*) FROM scenarios WHERE user_id IN ({ph})", ids).fetchone()[0] or 0)
        responses = int(c.execute(f"""
            SELECT COUNT(*) FROM simulation_results r JOIN scenarios s ON s.id=r.scenario_id
            WHERE s.user_id IN ({ph})
        """, ids).fetchone()[0] or 0)
        twins = int(c.execute(f"""
            SELECT COUNT(*) FROM synthetic_customer_twins t
            JOIN uploaded_datasets u ON u.id=t.upload_id
            WHERE u.user_id IN ({ph})
        """, ids).fetchone()[0] or 0)
        personas = int(c.execute(f"""
            SELECT COUNT(*) FROM customer_personas p
            JOIN uploaded_datasets u ON u.id=p.upload_id
            WHERE u.user_id IN ({ph})
        """, ids).fetchone()[0] or 0)
        segments = int(c.execute(f"""
            SELECT COUNT(DISTINCT s.segment_name) FROM customer_segments s
            JOIN uploaded_datasets u ON u.id=s.upload_id
            WHERE u.user_id IN ({ph})
        """, ids).fetchone()[0] or 0)
        confirmed_learning = int(c.execute(f"SELECT COUNT(*) FROM learning_audit WHERE user_id IN ({ph}) AND confirmed=1", ids).fetchone()[0] or 0)
        avg_real = c.execute(f"SELECT AVG(overall_real_data_pct) FROM learning_audit WHERE user_id IN ({ph}) AND confirmed=1", ids).fetchone()[0]
        avg_score = c.execute(f"""
            SELECT AVG(r.score) FROM simulation_results r JOIN scenarios s ON s.id=r.scenario_id
            WHERE s.user_id IN ({ph})
        """, ids).fetchone()[0]

        intents = {'buy': 0, 'hesitate': 0, 'not_buy': 0}
        for k, n in c.execute(f"""
            SELECT COALESCE(r.purchase_intent,'hesitate'),COUNT(*)
            FROM simulation_results r JOIN scenarios s ON s.id=r.scenario_id
            WHERE s.user_id IN ({ph}) GROUP BY COALESCE(r.purchase_intent,'hesitate')
        """, ids).fetchall():
            if k in intents:
                intents[k] = int(n or 0)

        recent_activity = [dict(r) for r in c.execute(f"""
            SELECT a.id,a.user_id,u.email,u.display_name,a.action,a.endpoint,a.status_code,a.details,a.created_at
            FROM activity_logs a JOIN users u ON u.id=a.user_id
            WHERE a.user_id IN ({ph}) ORDER BY a.id DESC LIMIT 20
        """, ids).fetchall()]
        recent_datasets = [dict(r) for r in c.execute(f"""
            SELECT d.id,d.upload_name,d.record_count,d.uploaded_at,d.user_id,u.email,u.display_name
            FROM uploaded_datasets d LEFT JOIN users u ON u.id=d.user_id
            WHERE d.user_id IN ({ph}) ORDER BY d.id DESC LIMIT 10
        """, ids).fetchall()]
        recent_projects = [dict(r) for r in c.execute(f"""
            SELECT s.id,s.scenario_text,s.star_rating,s.user_id,u.email,u.display_name
            FROM scenarios s LEFT JOIN users u ON u.id=s.user_id
            WHERE s.user_id IN ({ph}) ORDER BY s.id DESC LIMIT 10
        """, ids).fetchall()]

    def pct(n: int) -> float:
        return round((n / responses * 100), 1) if responses else 0.0

    return {
        'company_id': company_id,
        'organization': profile.get('organization_name', 'Doanh nghiệp của tôi'),
        'staff': {'total': staff_total, 'enabled': staff_active, 'active_today': active_today},
        'datasets': datasets,
        'customers': customers,
        'projects': projects,
        'simulation_responses': responses,
        'digital_twins': twins,
        'personas': personas,
        'segments': segments,
        'confirmed_learning': confirmed_learning,
        'real_data_pct': round(float(avg_real or 0), 1),
        'avg_score': round(float(avg_score or 0), 2),
        'purchase_intent': {k: {'count': v, 'pct': pct(v)} for k, v in intents.items()},
        'recent_activity': recent_activity,
        'recent_datasets': recent_datasets,
        'recent_projects': recent_projects,
    }


def admin_team_health(admin_id: int) -> dict[str, Any]:
    """Easy-to-read membership status for one business only."""
    require_admin_account(admin_id)
    company = _admin_company(admin_id) or {}
    company_id = int(company.get("company_id") or 0)
    with _conn() as c:
        repairs = _reconcile_memberships(c)
        # Ensure every provably-owned employee has a durable membership row.
        ids = [int(r["id"]) for r in c.execute("""
            SELECT id FROM users
            WHERE role='employee'
              AND (company_id=? OR (company_id IS NULL AND admin_owner_id=?))
        """, (company_id, int(admin_id))).fetchall()]
        synced = 0
        for uid in ids:
            before = c.execute("SELECT company_id,admin_id FROM company_memberships WHERE user_id=?", (uid,)).fetchone()
            _sync_employee_membership(c, uid)
            after = c.execute("SELECT company_id,admin_id FROM company_memberships WHERE user_id=?", (uid,)).fetchone()
            if after is not None and (before is None or tuple(before) != tuple(after)):
                synced += 1

        # company_id is authoritative; this count has no LIMIT and therefore
        # cannot drop an older employee when a new one joins.
        total = int(c.execute("""
            SELECT COUNT(*) FROM users
            WHERE role='employee' AND company_id=?
        """, (company_id,)).fetchone()[0] or 0)
        active = int(c.execute("""
            SELECT COUNT(*) FROM users
            WHERE role='employee' AND company_id=? AND is_active=1
        """, (company_id,)).fetchone()[0] or 0)
        legacy_unlinked = int(c.execute("""
            SELECT COUNT(*) FROM users
            WHERE role='employee' AND company_id IS NULL AND admin_owner_id=?
        """, (int(admin_id),)).fetchone()[0] or 0)
        conflicts = int(c.execute("""
            SELECT COUNT(*) FROM users u
            WHERE u.role='employee' AND u.admin_owner_id=? AND u.company_id IS NOT NULL AND u.company_id!=?
        """, (int(admin_id), company_id)).fetchone()[0] or 0)
        membership_conflicts = int(c.execute("""
            SELECT COUNT(*)
            FROM company_memberships m
            JOIN users u ON u.id=m.user_id
            WHERE (m.company_id=? OR m.admin_id=?)
              AND (u.company_id IS NOT NULL AND u.company_id!=m.company_id)
        """, (company_id, int(admin_id))).fetchone()[0] or 0)
        c.commit()
    return {
        "ok": conflicts == 0 and membership_conflicts == 0,
        "company_id": company_id,
        "organization_name": company.get("organization_name"),
        "join_code": company.get("join_code"),
        "employees": total,
        "active_employees": active,
        "legacy_unlinked": legacy_unlinked,
        "membership_conflicts": conflicts + membership_conflicts,
        "repairs": {
            **repairs,
            "membership_rows_repaired": synced,
        },
    }


def admin_staff(admin_id: int) -> list[dict]:
    """Return every employee that can be proven to belong to this business."""
    require_admin_account(admin_id)
    company = _admin_company(admin_id)
    company_id = int(company["company_id"])
    with _conn() as c:
        _reconcile_memberships(c)
        # Backfill the durable membership mirror before reading the list.
        candidate_ids = [int(r["id"]) for r in c.execute("""
            SELECT id FROM users
            WHERE role='employee'
              AND (company_id=? OR (company_id IS NULL AND admin_owner_id=?))
        """, (company_id, int(admin_id))).fetchall()]
        for uid in candidate_ids:
            _sync_employee_membership(c, uid)
        c.commit()

        rows = c.execute("""
            SELECT
              u.id,u.email,u.display_name,u.created_at,u.is_active,
              u.company_id,u.admin_owner_id,
              (SELECT COUNT(*) FROM uploaded_datasets d WHERE d.user_id=u.id) datasets,
              (SELECT COALESCE(SUM(d.record_count),0) FROM uploaded_datasets d WHERE d.user_id=u.id) uploaded_records,
              (SELECT COUNT(*) FROM scenarios s WHERE s.user_id=u.id) projects,
              (SELECT COUNT(*) FROM simulation_results r JOIN scenarios s ON s.id=r.scenario_id WHERE s.user_id=u.id) responses,
              (SELECT MAX(a.created_at) FROM activity_logs a WHERE a.user_id=u.id) last_activity
            FROM users u
            WHERE u.role='employee' AND u.company_id=?
            ORDER BY u.id DESC
        """, (company_id,)).fetchall()
        return [dict(r) for r in rows]


def admin_employee_detail(admin_id: int, employee_id: int) -> dict:
    require_admin_account(admin_id)
    company = _admin_company(admin_id)
    with _conn() as c:
        _reconcile_memberships(c)
        c.commit()
        u = c.execute("""
            SELECT id,email,display_name,created_at,is_active,company_id,admin_owner_id FROM users
            WHERE id=? AND company_id=? AND role='employee'
        """, (int(employee_id), int(company["company_id"]))).fetchone()
        if not u:
            raise ValueError("Không tìm thấy nhân viên.")
        datasets = [dict(r) for r in c.execute("""
            SELECT id,upload_name,record_count,uploaded_at FROM uploaded_datasets
            WHERE user_id=? ORDER BY id DESC LIMIT 30
        """, (int(employee_id),)).fetchall()]
        projects = [dict(r) for r in c.execute("""
            SELECT id,scenario_text,star_rating FROM scenarios
            WHERE user_id=? ORDER BY id DESC LIMIT 30
        """, (int(employee_id),)).fetchall()]
        activity = [dict(r) for r in c.execute("""
            SELECT id,action,endpoint,status_code,details,created_at FROM activity_logs
            WHERE user_id=? ORDER BY id DESC LIMIT 50
        """, (int(employee_id),)).fetchall()]
        return {'employee': dict(u), 'datasets': datasets, 'projects': projects, 'activity': activity}


def admin_activity(admin_id: int, limit: int = 200) -> list[dict]:
    require_admin_account(admin_id)
    ids = team_user_ids(admin_id, include_admin=True)
    ph = _placeholders(ids)
    limit = max(1, min(int(limit), 1000))
    with _conn() as c:
        return [dict(r) for r in c.execute(f"""
            SELECT a.id,a.user_id,u.email,u.display_name,a.action,a.endpoint,a.method,a.status_code,a.details,a.created_at
            FROM activity_logs a JOIN users u ON u.id=a.user_id
            WHERE a.user_id IN ({ph}) ORDER BY a.id DESC LIMIT ?
        """, (*ids, limit)).fetchall()]


def activity_name(path: str, method: str) -> str:
    p = path or ''
    mapping = [
        ('/api/customers/inspect/', 'Xác nhận / xử lý dữ liệu khách hàng'),
        ('/api/customers/inspect', 'Đọc & kiểm tra file khách hàng'),
        ('/api/customers/learning/start', 'Bắt đầu AI Learning'),
        ('/api/customers/learning/confirm', 'Xác nhận AI Learning'),
        ('/api/customers/learning/history', 'Quản lý lịch sử AI Learning'),
        ('/api/trends/collect', 'Thu thập Google Trends'),
        ('/api/personas/generate', 'Tạo khách hàng đại diện'),
        ('/api/simulations/start', 'Chạy mô phỏng chiến dịch'),
        ('/api/advanced/ab', 'Chạy A/B Test'),
        ('/api/advanced/optimize', 'Tối ưu chiến dịch'),
        ('/api/feedback', 'Ghi nhận kết quả thực tế'),
        ('/api/chat', 'Sử dụng trợ lý AI'),
        ('/api/system/provider', 'Đổi AI provider'),
    ]
    for prefix, label in mapping:
        if p.startswith(prefix):
            return label
    return f"{method.upper()} {p}"

# ---------------------------------------------------------------------------
# Per-company schema memory: remembers column mappings that were explicitly
# confirmed through the staged onboarding flow. This reduces repeated LLM use.
# ---------------------------------------------------------------------------
def init_company_schema_memory():
    init_admin_schema()
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS company_schema_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                source_column TEXT NOT NULL,
                canonical_field TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 1.0,
                confirmation_count INTEGER NOT NULL DEFAULT 1,
                last_confirmed_by INTEGER,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(company_id, source_column),
                FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_company_schema_memory ON company_schema_memory(company_id,source_column)")
        c.commit()

def get_company_schema_mapping(company_id:int|None, source_column:str) -> dict|None:
    if not company_id:return None
    init_company_schema_memory()
    with _conn() as c:
        r=c.execute("SELECT source_column,canonical_field,confidence,confirmation_count,updated_at FROM company_schema_memory WHERE company_id=? AND LOWER(source_column)=LOWER(?)",(int(company_id),str(source_column))).fetchone()
        return dict(r) if r else None

def save_company_schema_mappings(company_id:int|None, user_id:int, mappings:list[dict]):
    if not company_id:return 0
    init_company_schema_memory(); saved=0
    with _conn() as c:
        for m in mappings or []:
            src=str(m.get('source_column') or '').strip(); field=str(m.get('canonical_field') or '').strip()
            if not src or not field or field in ('unmapped','unknown_column'):continue
            existing=c.execute("SELECT id,confirmation_count FROM company_schema_memory WHERE company_id=? AND LOWER(source_column)=LOWER(?)",(int(company_id),src)).fetchone()
            if existing:
                c.execute("UPDATE company_schema_memory SET canonical_field=?,confidence=1.0,confirmation_count=?,last_confirmed_by=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(field,int(existing['confirmation_count'] or 0)+1,int(user_id),int(existing['id'])))
            else:
                c.execute("INSERT INTO company_schema_memory(company_id,source_column,canonical_field,confidence,confirmation_count,last_confirmed_by) VALUES(?,?,?,?,1,?)",(int(company_id),src,field,1.0,int(user_id)))
            saved+=1
        c.commit()
    return saved
