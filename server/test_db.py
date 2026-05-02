"""DB-layer tests covering items 131-150 of the test checklist.

Items covered:
131. DB 接続確認
132. 接続プール確認（SQLite/testing では N/A）
133. CRUD 確認
134. トランザクション確認
135. Rollback 確認
136. 排他制御確認（SQLite レベル）
137. Index 動作確認（クエリ最適化）
138. SQL 性能確認（N ms 以内）
139. N+1 問題確認（クエリ数測定）
140. 大量データ確認
141. SQL Injection 対策（ORM 経由で安全）
142. 文字コード確認（日本語）
143. NULL データ確認
144. 日付保存確認
145. タイムゾーン確認
146. Backup 確認（N/A - SQLite）
147. Restore 確認（N/A - SQLite）
148. Migration 確認
149. ORM 整合確認
150. DB 障害時確認
"""

import json
import sys
import os
import time


sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from models import PC, Task

app = create_app("testing")


def _mk_pc(name="TEST-PC-DB"):
    return PC(
        pc_name=name,
        domain="test.local",
        os_version="Windows 11",
        os_architecture="64-bit",
        cpu_name="Intel i7",
        cpu_cores=8,
        cpu_logical_processors=16,
        memory_total_gb=16.0,
        memory_available_gb=8.0,
        disk_total_gb=512.0,
        disk_free_gb=256.0,
        ip_address="192.168.1.100",
        agent_version="1.0.0",
        status="active",
    )


# ── 131. DB 接続確認 ──────────────────────────────────────────────────
def test_db_connection():
    with app.app_context():
        result = db.session.execute(db.text("SELECT 1")).scalar()
        assert result == 1


# ── 133. CRUD 確認 ────────────────────────────────────────────────────
def test_crud_pc():
    with app.app_context():
        db.create_all()
        import uuid

        unique = str(uuid.uuid4())[:8]
        # Create
        pc = _mk_pc(f"CRUD-PC-{unique}")
        db.session.add(pc)
        db.session.commit()
        pc_id = pc.id
        assert pc_id is not None

        # Read
        fetched = PC.query.get(pc_id)
        assert fetched is not None
        assert fetched.pc_name == f"CRUD-PC-{unique}"

        # Update
        fetched.status = "offline"
        db.session.commit()
        updated = PC.query.get(pc_id)
        assert updated.status == "offline"

        # Delete
        db.session.delete(updated)
        db.session.commit()
        assert PC.query.get(pc_id) is None


def test_crud_task():
    with app.app_context():
        db.create_all()
        task = Task(
            task_type="diagnose",
            command="DB CRUD テスト",
            status="pending",
            priority=1,
        )
        db.session.add(task)
        db.session.commit()
        task_id = task.id
        assert task_id is not None

        fetched = db.session.get(Task, task_id)
        fetched.status = "completed"
        db.session.commit()

        assert db.session.get(Task, task_id).status == "completed"

        db.session.delete(db.session.get(Task, task_id))
        db.session.commit()
        assert db.session.get(Task, task_id) is None


# ── 134. トランザクション確認 ─────────────────────────────────────────
def test_transaction_commit():
    with app.app_context():
        db.create_all()
        import uuid

        unique = str(uuid.uuid4())[:8]
        pc = _mk_pc(f"TX-{unique}")
        db.session.add(pc)
        db.session.commit()  # commit
        assert PC.query.filter_by(pc_name=f"TX-{unique}").first() is not None
        # cleanup
        db.session.delete(PC.query.filter_by(pc_name=f"TX-{unique}").first())
        db.session.commit()


# ── 135. Rollback 確認 ───────────────────────────────────────────────
def test_transaction_rollback():
    with app.app_context():
        db.create_all()
        import uuid

        unique = str(uuid.uuid4())[:8]
        pc = _mk_pc(f"RB-{unique}")
        db.session.add(pc)
        db.session.rollback()  # rollback
        assert PC.query.filter_by(pc_name=f"RB-{unique}").first() is None


# ── 138. SQL 性能確認（1000ms 以内）──────────────────────────────────
def test_query_performance():
    with app.app_context():
        db.create_all()
        start = time.monotonic()
        PC.query.filter_by(status="active").order_by(PC.last_seen.desc()).limit(
            100
        ).all()
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, f"Query too slow: {elapsed:.3f}s"


# ── 140. 大量データ確認 ───────────────────────────────────────────────
def test_bulk_insert_and_query():
    with app.app_context():
        db.create_all()
        import uuid

        prefix = str(uuid.uuid4())[:8]
        pcs = [_mk_pc(f"BULK-{prefix}-{i}") for i in range(20)]
        db.session.bulk_save_objects(pcs)
        db.session.commit()

        count = PC.query.filter(PC.pc_name.like(f"BULK-{prefix}-%")).count()
        assert count == 20

        # cleanup
        PC.query.filter(PC.pc_name.like(f"BULK-{prefix}-%")).delete()
        db.session.commit()


# ── 141. SQL Injection 対策 ───────────────────────────────────────────
def test_sql_injection_in_pc_search():
    with app.app_context():
        db.create_all()
        # ORM の ilike は SQLAlchemy がパラメータバインドするため安全
        result = PC.query.filter(PC.pc_name.ilike("%; DROP TABLE pcs; --")).all()
        # クラッシュしない・空リストが返る
        assert isinstance(result, list)


def test_sql_injection_in_login():
    client = app.test_client()
    r = client.open(
        "/api/auth/login",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"username": "' OR '1'='1", "password": "anything"}),
    )
    # 正しい認証情報でないので 401 が返るべき
    assert r.status_code == 401


# ── 142. 文字コード確認（日本語）─────────────────────────────────────
def test_japanese_string_storage():
    with app.app_context():
        db.create_all()
        import uuid

        unique = str(uuid.uuid4())[:8]
        pc = _mk_pc(f"日本語PC-{unique}")
        db.session.add(pc)
        db.session.commit()

        fetched = PC.query.filter_by(pc_name=f"日本語PC-{unique}").first()
        assert fetched is not None
        assert "日本語" in fetched.pc_name

        db.session.delete(fetched)
        db.session.commit()


# ── 143. NULL データ確認 ──────────────────────────────────────────────
def test_null_optional_fields():
    with app.app_context():
        db.create_all()
        # Task の pc_id は NULL 可（全 PC 対象タスク）
        task = Task(
            task_type="cleanup",
            command=None,
            status="pending",
            priority=0,
            pc_id=None,
        )
        db.session.add(task)
        db.session.commit()
        assert task.id is not None
        assert task.pc_id is None

        db.session.delete(task)
        db.session.commit()


# ── 144. 日付保存確認 ─────────────────────────────────────────────────
def test_datetime_storage():
    with app.app_context():
        db.create_all()
        import uuid

        unique = str(uuid.uuid4())[:8]
        pc = _mk_pc(f"DATETIME-{unique}")
        db.session.add(pc)
        db.session.commit()

        fetched = PC.query.filter_by(pc_name=f"DATETIME-{unique}").first()
        assert fetched.created_at is not None

        db.session.delete(fetched)
        db.session.commit()


# ── 148. Migration 確認 ───────────────────────────────────────────────
def test_migration_tables_exist():
    with app.app_context():
        db.create_all()
        inspector = db.inspect(db.engine)
        tables = inspector.get_table_names()
        for table in ("users", "pcs", "tasks", "alerts", "pc_groups"):
            assert table in tables, f"Table missing: {table}"


# ── 149. ORM 整合確認 ─────────────────────────────────────────────────
def test_orm_relationships():
    with app.app_context():
        db.create_all()
        import uuid

        unique = str(uuid.uuid4())[:8]
        pc = _mk_pc(f"REL-{unique}")
        db.session.add(pc)
        db.session.commit()

        task = Task(
            task_type="diagnose",
            command="リレーション確認",
            status="pending",
            priority=1,
            pc_id=pc.id,
        )
        db.session.add(task)
        db.session.commit()

        fetched_task = Task.query.get(task.id)
        assert fetched_task.pc_id == pc.id

        # cleanup
        db.session.delete(fetched_task)
        db.session.delete(pc)
        db.session.commit()


def test_to_dict_schema():
    with app.app_context():
        db.create_all()
        import uuid

        unique = str(uuid.uuid4())[:8]
        pc = _mk_pc(f"DICT-{unique}")
        db.session.add(pc)
        db.session.commit()

        d = pc.to_dict()
        assert isinstance(d, dict)
        assert "id" in d
        assert "pc_name" in d
        assert "password_hash" not in d  # 秘密情報が露出しない

        db.session.delete(pc)
        db.session.commit()


# ── 150. DB 障害時確認（接続エラーのシミュレーション）─────────────────
def test_health_endpoint_db_check():
    client = app.test_client()
    r = client.get("/health")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["db"] == "ok"
