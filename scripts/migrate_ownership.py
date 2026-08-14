#!/usr/bin/env python3
"""Audit and explicitly assign legacy MarketSim ownership without guessing.

Examples:
  python scripts/migrate_ownership.py --db ./marketsim.db --audit
  python scripts/migrate_ownership.py --db ./marketsim.db --plan scripts/ownership_plan.example.json
  python scripts/migrate_ownership.py --db ./marketsim.db --plan ownership_plan.json --apply

Without --apply every planned change runs in a transaction and is rolled back.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def connect(path: Path) -> sqlite3.Connection:
    conn=sqlite3.connect(path)
    conn.row_factory=sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def scalar(conn: sqlite3.Connection, sql: str, params=()) -> int:
    return int(conn.execute(sql,params).fetchone()[0] or 0)


def audit(conn: sqlite3.Connection) -> dict:
    result={
        'employees_without_company':scalar(conn,"SELECT COUNT(*) FROM users WHERE role='employee' AND company_id IS NULL"),
        'datasets_without_user':scalar(conn,'SELECT COUNT(*) FROM uploaded_datasets WHERE user_id IS NULL'),
        'datasets_without_company':scalar(conn,'SELECT COUNT(*) FROM uploaded_datasets WHERE company_id IS NULL'),
        'audits_without_user':scalar(conn,'SELECT COUNT(*) FROM learning_audit WHERE user_id IS NULL'),
        'audits_without_company':scalar(conn,'SELECT COUNT(*) FROM learning_audit WHERE company_id IS NULL'),
        'scenarios_without_user':scalar(conn,'SELECT COUNT(*) FROM scenarios WHERE user_id IS NULL'),
        'scenarios_without_company':scalar(conn,'SELECT COUNT(*) FROM scenarios WHERE company_id IS NULL'),
        'canonical_rows_in_unowned_datasets':scalar(conn,"""
            SELECT COUNT(*) FROM canonical_customers c
            JOIN uploaded_datasets d ON d.id=c.upload_id
            WHERE d.user_id IS NULL OR d.company_id IS NULL
        """),
    }
    result['unassigned_employee_ids']=[int(r[0]) for r in conn.execute(
        "SELECT id FROM users WHERE role='employee' AND company_id IS NULL ORDER BY id"
    )]
    result['unowned_dataset_ids']=[int(r[0]) for r in conn.execute(
        'SELECT id FROM uploaded_datasets WHERE user_id IS NULL OR company_id IS NULL ORDER BY id'
    )]
    result['unowned_scenario_ids']=[int(r[0]) for r in conn.execute(
        'SELECT id FROM scenarios WHERE user_id IS NULL OR company_id IS NULL ORDER BY id'
    )]
    return result


def require_employee(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row:
    user=conn.execute('SELECT id,role,company_id FROM users WHERE id=?',(user_id,)).fetchone()
    if not user:
        raise ValueError(f'user_id={user_id} không tồn tại')
    if user['role']!='employee':
        raise ValueError(f'user_id={user_id} không phải tài khoản nhân viên')
    return user


def require_company(conn: sqlite3.Connection, company_id: int) -> sqlite3.Row:
    company=conn.execute(
        'SELECT id,owner_admin_id,is_active FROM companies WHERE id=?',(company_id,),
    ).fetchone()
    if not company or not int(company['is_active'] or 0):
        raise ValueError(f'company_id={company_id} không tồn tại hoặc đã bị khóa')
    return company


def assign_membership(conn: sqlite3.Connection, item: dict) -> str:
    user_id=int(item['user_id']); company_id=int(item['company_id'])
    user=require_employee(conn,user_id); company=require_company(conn,company_id)
    if user['company_id'] is not None and int(user['company_id'])!=company_id:
        raise ValueError(f'user_id={user_id} đã thuộc company_id={user["company_id"]}; không tự chuyển doanh nghiệp')
    conn.execute(
        'UPDATE users SET company_id=?,admin_owner_id=? WHERE id=?',
        (company_id,int(company['owner_admin_id']),user_id),
    )
    conn.execute("""
        INSERT INTO company_memberships(user_id,company_id,admin_id,joined_at,updated_at)
        VALUES(?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
            company_id=excluded.company_id,admin_id=excluded.admin_id,updated_at=CURRENT_TIMESTAMP
    """,(user_id,company_id,int(company['owner_admin_id'])))
    return f'employee {user_id} -> company {company_id}'


def assignment_user_company(conn: sqlite3.Connection, user_id: int) -> int:
    user=require_employee(conn,user_id)
    if user['company_id'] is None:
        raise ValueError(f'user_id={user_id} chưa thuộc doanh nghiệp; hãy thêm vào memberships trong plan trước')
    require_company(conn,int(user['company_id']))
    return int(user['company_id'])


def refuse_conflicting_owner(row: sqlite3.Row, user_id: int, company_id: int, label: str):
    if row['user_id'] is not None and int(row['user_id'])!=user_id:
        raise ValueError(f'{label} đã thuộc user_id={row["user_id"]}; từ chối ghi đè')
    if row['company_id'] is not None and int(row['company_id'])!=company_id:
        raise ValueError(f'{label} đã thuộc company_id={row["company_id"]}; từ chối ghi đè')


def assign_dataset(conn: sqlite3.Connection, item: dict) -> str:
    dataset_id=int(item['dataset_id']); user_id=int(item['user_id'])
    company_id=assignment_user_company(conn,user_id)
    row=conn.execute(
        'SELECT id,user_id,company_id FROM uploaded_datasets WHERE id=?',(dataset_id,),
    ).fetchone()
    if not row:raise ValueError(f'dataset_id={dataset_id} không tồn tại')
    refuse_conflicting_owner(row,user_id,company_id,f'dataset_id={dataset_id}')
    conn.execute('UPDATE uploaded_datasets SET user_id=?,company_id=? WHERE id=?',(user_id,company_id,dataset_id))
    conn.execute("""
        UPDATE learning_audit SET user_id=?,company_id=?
        WHERE upload_id=? AND (user_id IS NULL OR user_id=?) AND (company_id IS NULL OR company_id=?)
    """,(user_id,company_id,dataset_id,user_id,company_id))
    return f'dataset {dataset_id} -> employee {user_id} / company {company_id}'


def assign_scenario(conn: sqlite3.Connection, item: dict) -> str:
    scenario_id=int(item['scenario_id']); user_id=int(item['user_id'])
    company_id=assignment_user_company(conn,user_id)
    row=conn.execute('SELECT id,user_id,company_id FROM scenarios WHERE id=?',(scenario_id,)).fetchone()
    if not row:raise ValueError(f'scenario_id={scenario_id} không tồn tại')
    refuse_conflicting_owner(row,user_id,company_id,f'scenario_id={scenario_id}')
    conn.execute('UPDATE scenarios SET user_id=?,company_id=? WHERE id=?',(user_id,company_id,scenario_id))
    return f'scenario {scenario_id} -> employee {user_id} / company {company_id}'


def apply_plan(conn: sqlite3.Connection, plan: dict) -> list[str]:
    operations=[]
    for item in plan.get('memberships',[]):operations.append(assign_membership(conn,item))
    for item in plan.get('datasets',[]):operations.append(assign_dataset(conn,item))
    for item in plan.get('scenarios',[]):operations.append(assign_scenario(conn,item))
    return operations


def main():
    parser=argparse.ArgumentParser(description='MarketSim explicit ownership migration')
    parser.add_argument('--db',required=True,type=Path)
    parser.add_argument('--audit',action='store_true')
    parser.add_argument('--plan',type=Path)
    parser.add_argument('--apply',action='store_true',help='Commit validated changes; default is rollback/dry-run')
    args=parser.parse_args()
    db=args.db.resolve()
    if not db.is_file():raise SystemExit(f'Không tìm thấy database: {db}')
    if args.apply and not args.plan:raise SystemExit('--apply bắt buộc phải đi cùng --plan')

    conn=connect(db)
    before=audit(conn)
    if args.audit or not args.plan:
        print(json.dumps({'database':str(db),'audit':before},ensure_ascii=False,indent=2))
    if not args.plan:
        conn.close(); return

    plan=json.loads(args.plan.read_text(encoding='utf-8'))
    backup=None
    if args.apply:
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        backup=db.with_name(f'{db.name}.ownership-backup-{stamp}')
        shutil.copy2(db,backup)
    try:
        conn.execute('BEGIN IMMEDIATE')
        operations=apply_plan(conn,plan)
        after=audit(conn)
        if args.apply:conn.commit()
        else:conn.rollback()
    except Exception:
        conn.rollback(); conn.close(); raise
    conn.close()
    print(json.dumps({
        'mode':'APPLIED' if args.apply else 'DRY_RUN_ROLLED_BACK',
        'backup':str(backup) if backup else None,
        'operations':operations,'before':before,'after_if_applied':after,
    },ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()

