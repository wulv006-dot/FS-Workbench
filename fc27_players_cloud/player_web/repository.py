"""持久化计划、任务及全局未决范围。生产状态库只允许显式初始化。"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


class StateError(ValueError):
    pass


class Repository:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        if not self.path.is_file():
            raise StateError("状态库不存在；须先显式执行 init-db，禁止自动创建空账本")
        db = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA journal_mode=WAL")
        try:
            yield db
        finally:
            db.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            raise StateError("状态库已经存在，拒绝重新初始化")
        db = sqlite3.connect(str(self.path))
        try:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=FULL;
                CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE collections (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, source_id TEXT NOT NULL,
                    source_time TEXT, status TEXT NOT NULL, total INTEGER NOT NULL,
                    snapshot_digest TEXT NOT NULL, filters_json TEXT NOT NULL
                );
                CREATE TABLE candidates (
                    collection_id TEXT NOT NULL REFERENCES collections(id),
                    futbin_id TEXT NOT NULL, row_json TEXT NOT NULL,
                    PRIMARY KEY(collection_id, futbin_id)
                );
                CREATE TABLE plans (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL, status TEXT NOT NULL,
                    digest TEXT NOT NULL, payload_json TEXT NOT NULL,
                    execution_id TEXT
                );
                CREATE TABLE executions (
                    id TEXT PRIMARY KEY, plan_id TEXT NOT NULL UNIQUE REFERENCES plans(id),
                    owner TEXT NOT NULL, status TEXT NOT NULL, step TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    error_code TEXT, job_id TEXT
                );
                CREATE TABLE active_scope (
                    futbin_id TEXT PRIMARY KEY, execution_id TEXT NOT NULL REFERENCES executions(id)
                );
                CREATE TABLE legacy_unresolved (
                    futbin_id TEXT PRIMARY KEY, evidence_json TEXT NOT NULL,
                    imported_at TEXT NOT NULL
                );
                CREATE TABLE events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, execution_id TEXT NOT NULL REFERENCES executions(id),
                    created_at TEXT NOT NULL, step TEXT NOT NULL, status TEXT NOT NULL,
                    detail_json TEXT NOT NULL
                );
                CREATE TABLE audit (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
                    actor TEXT NOT NULL, event TEXT NOT NULL, object_id TEXT NOT NULL,
                    detail_json TEXT NOT NULL
                );
                CREATE TABLE collection_meta (
                    collection_id TEXT PRIMARY KEY REFERENCES collections(id),
                    query_hash TEXT NOT NULL, started_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL, read_count INTEGER NOT NULL
                );
                CREATE TABLE candidate_rows_v2 (
                    collection_id TEXT NOT NULL REFERENCES collections(id),
                    candidate_key TEXT NOT NULL, futbin_id TEXT NOT NULL,
                    row_json TEXT NOT NULL, PRIMARY KEY(collection_id,candidate_key)
                );
                CREATE TABLE model_snapshots (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, created_at TEXT NOT NULL,
                    total INTEGER NOT NULL, snapshot_digest TEXT NOT NULL,
                    tag_catalog_json TEXT NOT NULL
                );
                CREATE TABLE model_snapshot_rows (
                    snapshot_id TEXT NOT NULL REFERENCES model_snapshots(id),
                    model_id INTEGER NOT NULL, row_json TEXT NOT NULL,
                    PRIMARY KEY(snapshot_id,model_id)
                );
                CREATE TABLE execution_items (
                    execution_id TEXT NOT NULL REFERENCES executions(id),
                    model_id INTEGER NOT NULL, status TEXT NOT NULL,
                    planned_json TEXT NOT NULL, before_json TEXT,
                    after_json TEXT, updated_at TEXT NOT NULL,
                    PRIMARY KEY(execution_id,model_id)
                );
            """)
            db.execute("INSERT INTO meta VALUES (?,?)", ("instance_id", uuid.uuid4().hex))
            db.execute("INSERT INTO meta VALUES (?,?)", ("schema_version", "1"))
            db.execute("INSERT INTO meta VALUES (?,?)", ("feature_parity_schema", "2"))
            db.commit()
        finally:
            db.close()

    def migrate_feature_parity(self) -> None:
        """只添加表和元数据；保留 schema_version=1 以便 cloud.4 应用回退。"""
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] != "1":
                raise StateError("基础状态库版本不兼容")
            existing = db.execute("SELECT value FROM meta WHERE key='feature_parity_schema'").fetchone()
            if existing is not None:
                raise StateError("功能对齐迁移已执行，拒绝重复覆盖")
            statements = (
                "CREATE TABLE collection_meta (collection_id TEXT PRIMARY KEY REFERENCES collections(id), query_hash TEXT NOT NULL, started_at TEXT NOT NULL, completed_at TEXT NOT NULL, read_count INTEGER NOT NULL)",
                "CREATE TABLE candidate_rows_v2 (collection_id TEXT NOT NULL REFERENCES collections(id), candidate_key TEXT NOT NULL, futbin_id TEXT NOT NULL, row_json TEXT NOT NULL, PRIMARY KEY(collection_id,candidate_key))",
                "CREATE TABLE model_snapshots (id TEXT PRIMARY KEY, owner TEXT NOT NULL, created_at TEXT NOT NULL, total INTEGER NOT NULL, snapshot_digest TEXT NOT NULL, tag_catalog_json TEXT NOT NULL)",
                "CREATE TABLE model_snapshot_rows (snapshot_id TEXT NOT NULL REFERENCES model_snapshots(id), model_id INTEGER NOT NULL, row_json TEXT NOT NULL, PRIMARY KEY(snapshot_id,model_id))",
                "CREATE TABLE execution_items (execution_id TEXT NOT NULL REFERENCES executions(id), model_id INTEGER NOT NULL, status TEXT NOT NULL, planned_json TEXT NOT NULL, before_json TEXT, after_json TEXT, updated_at TEXT NOT NULL, PRIMARY KEY(execution_id,model_id))",
            )
            for statement in statements:
                db.execute(statement)
            db.execute("INSERT INTO meta VALUES ('feature_parity_schema','2')")
            db.commit()

    def audit(self, actor: str, event: str, object_id: str, detail: Mapping[str, Any] | None = None) -> None:
        with self.connection() as db:
            db.execute("INSERT INTO audit(created_at,actor,event,object_id,detail_json) VALUES (?,?,?,?,?)",
                       (now(), actor, event, object_id, canonical(detail or {})))

    def import_legacy_blocks(self, records: Sequence[Mapping[str, Any]]) -> int:
        """显式导入旧端未决 ID；只加锁，不建立或重放任何执行任务。"""
        allowed = {"queued", "uploading", "unknown_status", "partial_or_unknown", "needs_reconcile"}
        if not records:
            raise StateError("旧端未决清单为空")
        per_id: dict[str, list[dict[str, str]]] = {}
        for record in records:
            if not isinstance(record, Mapping) or record.get("status") not in allowed:
                raise StateError("旧端未决状态无效")
            source = record.get("source")
            operation_digest = record.get("operation_digest")
            ids = record.get("futbin_ids")
            if source != "desktop_admin_tasks_20260928" or not isinstance(operation_digest, str) or len(operation_digest) != 64 or any(char not in "0123456789abcdef" for char in operation_digest):
                raise StateError("旧端未决证据来源或摘要无效")
            if not isinstance(ids, list) or not ids or len(ids) != len(set(ids)):
                raise StateError("旧端未决 ID 列表为空或重复")
            for item in ids:
                if not isinstance(item, str) or not item.isascii() or not item.isdecimal() or int(item) < 1:
                    raise StateError("旧端未决 FUTBIN ID 无效")
                per_id.setdefault(item, []).append({"source": source, "status": record["status"],
                                                     "operation_digest": operation_digest})
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS legacy_unresolved (futbin_id TEXT PRIMARY KEY, evidence_json TEXT NOT NULL, imported_at TEXT NOT NULL)")
            if db.execute("SELECT 1 FROM legacy_unresolved LIMIT 1").fetchone():
                raise StateError("旧端未决清单已导入；拒绝覆盖")
            stamp = now()
            db.executemany("INSERT INTO legacy_unresolved VALUES (?,?,?)", (
                (item, canonical(evidence), stamp) for item, evidence in sorted(per_id.items())
            ))
            db.execute("INSERT INTO audit(created_at,actor,event,object_id,detail_json) VALUES (?,?,?,?,?)",
                       (stamp, "system", "legacy_blocks_imported", "desktop_admin_tasks_20260928",
                        canonical({"record_count": len(records), "unique_futbin_ids": len(per_id),
                                   "payload_digest": digest(records)})))
            db.commit()
        return len(per_id)

    def legacy_blocks(self, ids: Sequence[str]) -> list[str]:
        if not ids:
            return []
        with self.connection() as db:
            rows = db.execute("SELECT futbin_id FROM legacy_unresolved WHERE futbin_id IN (" +
                              ",".join("?" for _ in ids) + ") ORDER BY futbin_id", tuple(ids)).fetchall()
            return [str(row["futbin_id"]) for row in rows]

    def save_collection(self, source_id: str, filters: Mapping[str, Any], rows: Sequence[Mapping[str, Any]],
                        source_time: str | None = None, *, started_at: str | None = None) -> str:
        from 球员维护工具.selection import extract_player_futbin_id
        collection_id = uuid.uuid4().hex
        ids = [extract_player_futbin_id(row) for row in rows]
        if any(not item for item in ids):
            raise StateError("候选缺少 FUTBIN ID；快照未发布")
        counts = Counter(ids)
        clean_rows: list[dict[str, Any]] = []
        keys: list[str] = []
        for row, futbin_id in zip(rows, ids):
            resource = row.get("resource_id")
            key = str(resource) if resource is not None and str(resource).isascii() and str(resource).isdecimal() and int(resource) > 0 else "futbin:" + str(futbin_id)
            item = dict(row)
            item["candidate_key"] = key
            item["identity_status"] = "ambiguous_futbin_id" if counts[futbin_id] > 1 else "valid"
            clean_rows.append(item)
            keys.append(key)
        if len(keys) != len(set(keys)):
            raise StateError("候选 resource_id 重复或身份不可区分；快照未发布")
        snapshot_digest = digest(clean_rows)
        stamp = now()
        query_hash = digest({"source_id": source_id, "filters": filters})
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO collections VALUES (?,?,?,?,?,?,?,?)",
                       (collection_id, stamp, source_id, source_time, "success_no_candidates" if not rows else "success",
                        len(clean_rows), snapshot_digest, canonical(filters)))
            db.execute("INSERT INTO collection_meta VALUES (?,?,?,?,?)",
                       (collection_id, query_hash, started_at or stamp, stamp, len(clean_rows)))
            db.executemany("INSERT INTO candidate_rows_v2 VALUES (?,?,?,?)",
                           ((collection_id, key, str(futbin_id), canonical(row))
                            for key, futbin_id, row in zip(keys, ids, clean_rows)))
            db.commit()
        return collection_id

    def latest_collection(self) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM collections ORDER BY rowid DESC LIMIT 1").fetchone()
            return self._collection_row(db, row) if row else None

    def last_successful_collection(self) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM collections WHERE status IN ('success','success_no_candidates') ORDER BY rowid DESC LIMIT 1").fetchone()
            return self._collection_row(db, row) if row else None

    @staticmethod
    def _collection_row(db: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        meta = db.execute("SELECT query_hash,started_at,completed_at,read_count FROM collection_meta WHERE collection_id=?",
                          (row["id"],)).fetchone()
        result.update(dict(meta) if meta else {"query_hash": digest({"source_id": row["source_id"],
                                                                        "filters": json.loads(row["filters_json"])}),
                                               "started_at": row["created_at"], "completed_at": row["created_at"],
                                               "read_count": row["total"]})
        return result

    def save_collection_failure(self, source_id: str, filters: Mapping[str, Any], code: str,
                                *, started_at: str | None = None) -> str:
        collection_id = uuid.uuid4().hex
        with self.connection() as db:
            stamp = now()
            db.execute("INSERT INTO collections VALUES (?,?,?,?,?,?,?,?)",
                       (collection_id, stamp, source_id, None, "failed:" + code, 0, "", canonical(filters)))
            db.execute("INSERT INTO collection_meta VALUES (?,?,?,?,?)",
                       (collection_id, digest({"source_id": source_id, "filters": filters}), started_at or stamp, stamp, 0))
        return collection_id

    def candidates(self, collection_id: str | None = None, limit: int = 100000) -> list[dict[str, Any]]:
        with self.connection() as db:
            if collection_id is None:
                latest = db.execute("SELECT id FROM collections WHERE status IN ('success','success_no_candidates') ORDER BY rowid DESC LIMIT 1").fetchone()
                if not latest:
                    return []
                collection_id = str(latest["id"])
            rows = db.execute("SELECT row_json FROM candidate_rows_v2 WHERE collection_id=? ORDER BY candidate_key LIMIT ?",
                              (collection_id, limit)).fetchall()
            if not rows:
                rows = db.execute("SELECT row_json FROM candidates WHERE collection_id=? ORDER BY futbin_id LIMIT ?",
                                  (collection_id, limit)).fetchall()
            return [json.loads(row["row_json"]) for row in rows]

    def get_collection(self, collection_id: str) -> dict[str, Any]:
        with self.connection() as db:
            row = db.execute("SELECT * FROM collections WHERE id=?", (collection_id,)).fetchone()
            if not row or row["status"] not in {"success", "success_no_candidates"}:
                raise StateError("候选快照不存在或未完整拉取")
            return {**self._collection_row(db, row), "filters": json.loads(row["filters_json"])}

    def save_model_snapshot(self, owner: str, rows: Sequence[Mapping[str, Any]],
                            tag_catalog: Mapping[int, str]) -> dict[str, Any]:
        if not owner:
            raise StateError("缺少模型快照操作者")
        ids = [row.get("model_id") for row in rows]
        if any(not isinstance(item, int) or isinstance(item, bool) or item < 1 for item in ids) or len(ids) != len(set(ids)):
            raise StateError("后台模型 ID 缺失或重复；拒绝发布不完整快照")
        snapshot_id, stamp = uuid.uuid4().hex, now()
        clean_rows = [dict(row) for row in rows]
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO model_snapshots VALUES (?,?,?,?,?,?)",
                       (snapshot_id, owner, stamp, len(rows), digest(clean_rows), canonical(tag_catalog)))
            db.executemany("INSERT INTO model_snapshot_rows VALUES (?,?,?)",
                           ((snapshot_id, item["model_id"], canonical(item)) for item in clean_rows))
            db.commit()
        return {"snapshot_id": snapshot_id, "created_at": stamp, "total": len(rows),
                "read_count": len(rows), "snapshot_digest": digest(clean_rows)}

    def model_snapshot(self, snapshot_id: str, owner: str) -> dict[str, Any]:
        with self.connection() as db:
            row = db.execute("SELECT * FROM model_snapshots WHERE id=? AND owner=?", (snapshot_id, owner)).fetchone()
            if not row:
                raise StateError("后台模型快照不存在或无权查看")
            count = db.execute("SELECT COUNT(*) FROM model_snapshot_rows WHERE snapshot_id=?", (snapshot_id,)).fetchone()[0]
            if count != row["total"]:
                raise StateError("后台模型快照不完整")
            return {"snapshot_id": row["id"], "created_at": row["created_at"], "total": row["total"],
                    "read_count": count, "snapshot_digest": row["snapshot_digest"],
                    "tag_catalog": json.loads(row["tag_catalog_json"])}

    def model_rows(self, snapshot_id: str, owner: str) -> list[dict[str, Any]]:
        self.model_snapshot(snapshot_id, owner)
        with self.connection() as db:
            rows = db.execute("SELECT row_json FROM model_snapshot_rows WHERE snapshot_id=? ORDER BY model_id",
                              (snapshot_id,)).fetchall()
            return [json.loads(row["row_json"]) for row in rows]

    def latest_model_snapshot(self, owner: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT id FROM model_snapshots WHERE owner=? ORDER BY rowid DESC LIMIT 1",
                             (owner,)).fetchone()
        return self.model_snapshot(row["id"], owner) if row else None

    def save_plan(self, owner: str, payload: Mapping[str, Any], ttl_seconds: int = 600) -> dict[str, Any]:
        if not owner or ttl_seconds < 1:
            raise StateError("计划所有者或有效期无效")
        scope = list(payload.get("scope_ids") or [])
        if not scope or len(scope) != len(set(scope)):
            raise StateError("计划范围为空或重复")
        plan_id = uuid.uuid4().hex
        created = datetime.now(timezone.utc)
        expiry = created + timedelta(seconds=ttl_seconds)
        clean = dict(payload)
        clean["schema_version"] = 1
        clean["plan_id"] = plan_id
        clean["owner"] = owner
        clean["created_at"] = created.isoformat(timespec="seconds")
        clean["expires_at"] = expiry.isoformat(timespec="seconds")
        clean["gid"] = 1327
        clean["cid"] = 9627
        plan_digest = digest(clean)
        with self.connection() as db:
            db.execute("INSERT INTO plans VALUES (?,?,?,?,?,?,?,NULL)",
                       (plan_id, owner, clean["created_at"], clean["expires_at"], "ready", plan_digest, canonical(clean)))
        return {**clean, "plan_digest": plan_digest, "status": "ready"}

    def get_plan(self, plan_id: str, owner: str) -> dict[str, Any]:
        with self.connection() as db:
            row = db.execute("SELECT * FROM plans WHERE id=? AND owner=?", (plan_id, owner)).fetchone()
            if not row:
                raise StateError("计划不存在或无权查看")
            payload = json.loads(row["payload_json"])
            return {**payload, "plan_digest": row["digest"], "status": row["status"], "execution_id": row["execution_id"]}

    def confirm(self, plan_id: str, owner: str, plan_digest: str, *, write_enabled: bool) -> tuple[str, bool]:
        if not write_enabled:
            raise StateError("WRITE_DISABLED")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM plans WHERE id=? AND owner=?", (plan_id, owner)).fetchone()
            if not row:
                raise StateError("计划不存在或无权确认")
            if row["digest"] != plan_digest:
                raise StateError("PLAN_STALE")
            if row["execution_id"]:
                db.commit()
                return str(row["execution_id"]), False
            if row["status"] != "ready" or row["expires_at"] <= now():
                raise StateError("PLAN_STALE")
            payload = json.loads(row["payload_json"])
            if payload.get("blockers"):
                raise StateError("PLAN_BLOCKED")
            scope = tuple(str(item) for item in payload["scope_ids"])
            overlap = db.execute(
                "SELECT futbin_id FROM active_scope WHERE futbin_id IN (" + ",".join("?" for _ in scope) + ") LIMIT 1",
                scope,
            ).fetchone()
            if overlap:
                raise StateError("UNRESOLVED_IMPORT")
            legacy_overlap = db.execute(
                "SELECT futbin_id FROM legacy_unresolved WHERE futbin_id IN (" + ",".join("?" for _ in scope) + ") LIMIT 1",
                scope,
            ).fetchone()
            if legacy_overlap:
                raise StateError("LEGACY_UNRESOLVED")
            execution_id = uuid.uuid4().hex
            stamp = now()
            db.execute("INSERT INTO executions VALUES (?,?,?,?,?,?,?,?,?)",
                       (execution_id, plan_id, owner, "queued", "not_started", stamp, stamp, None, None))
            db.executemany("INSERT INTO active_scope VALUES (?,?)", ((item, execution_id) for item in scope))
            items = payload.get("items") or []
            if items:
                if not isinstance(items, list) or len(items) != len({item.get("model_id") for item in items}):
                    raise StateError("计划逐模型范围无效")
                db.executemany("INSERT INTO execution_items VALUES (?,?,?,?,?,?,?)",
                               ((execution_id, int(item["model_id"]), "planned", canonical(item), None, None, stamp)
                                for item in items))
            db.execute("UPDATE plans SET status='consumed',execution_id=? WHERE id=?", (execution_id, plan_id))
            db.execute("INSERT INTO audit(created_at,actor,event,object_id,detail_json) VALUES (?,?,?,?,?)",
                       (stamp, owner, "confirm_plan", execution_id, canonical({"plan_id": plan_id, "scope_ids": scope})))
            db.commit()
            return execution_id, True

    def set_execution(self, execution_id: str, status: str, step: str, detail: Mapping[str, Any] | None = None,
                      *, job_id: str | None = None, release_scope: bool = False) -> None:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT id FROM executions WHERE id=?", (execution_id,)).fetchone()
            if not row:
                raise StateError("任务不存在")
            db.execute("UPDATE executions SET status=?,step=?,updated_at=?,job_id=COALESCE(?,job_id) WHERE id=?",
                       (status, step, now(), job_id, execution_id))
            db.execute("INSERT INTO events(execution_id,created_at,step,status,detail_json) VALUES (?,?,?,?,?)",
                       (execution_id, now(), step, status, canonical(detail or {})))
            if release_scope:
                db.execute("DELETE FROM active_scope WHERE execution_id=?", (execution_id,))
            db.commit()

    def get_execution(self, execution_id: str, owner: str) -> dict[str, Any]:
        with self.connection() as db:
            row = db.execute("SELECT * FROM executions WHERE id=? AND owner=?", (execution_id, owner)).fetchone()
            if not row:
                raise StateError("任务不存在或无权查看")
            result = dict(row)
            result["items"] = [{**dict(item), "planned": json.loads(item["planned_json"]),
                                "before": json.loads(item["before_json"]) if item["before_json"] else None,
                                "after": json.loads(item["after_json"]) if item["after_json"] else None}
                               for item in db.execute("SELECT * FROM execution_items WHERE execution_id=? ORDER BY model_id",
                                                      (execution_id,))]
            result["events"] = [{"seq": item["seq"], "created_at": item["created_at"],
                                 "step": item["step"], "status": item["status"],
                                 "detail": json.loads(item["detail_json"])}
                                for item in db.execute("SELECT * FROM events WHERE execution_id=? ORDER BY seq",
                                                       (execution_id,))]
            return result

    def set_execution_item(self, execution_id: str, model_id: int, status: str,
                           *, before: Mapping[str, Any] | None = None,
                           after: Mapping[str, Any] | None = None) -> None:
        allowed = {"planned", "dispatch_intent", "verified", "verified_no_change", "unknown", "not_started"}
        if status not in allowed:
            raise StateError("逐模型状态无效")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            found = db.execute("SELECT 1 FROM execution_items WHERE execution_id=? AND model_id=?",
                               (execution_id, model_id)).fetchone()
            if not found:
                raise StateError("逐模型任务范围不存在")
            db.execute("UPDATE execution_items SET status=?,before_json=COALESCE(?,before_json),after_json=COALESCE(?,after_json),updated_at=? WHERE execution_id=? AND model_id=?",
                       (status, canonical(before) if before is not None else None,
                        canonical(after) if after is not None else None, now(), execution_id, model_id))
            db.execute("INSERT INTO events(execution_id,created_at,step,status,detail_json) VALUES (?,?,?,?,?)",
                       (execution_id, now(), "model_action", status, canonical({"model_id": model_id})))
            db.commit()

    def list_executions(self, owner: str, limit: int = 20) -> list[dict[str, Any]]:
        with self.connection() as db:
            return [dict(row) for row in db.execute(
                "SELECT id,plan_id,status,step,created_at,updated_at FROM executions WHERE owner=? ORDER BY created_at DESC LIMIT ?",
                (owner, limit))]

    def interrupted_jobs(self) -> int:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT id FROM executions WHERE status IN ('queued','running')").fetchall()
            for row in rows:
                db.execute("UPDATE executions SET status='needs_reconcile',updated_at=? WHERE id=?", (now(), row["id"]))
                db.execute("INSERT INTO events(execution_id,created_at,step,status,detail_json) VALUES (?,?,?,?,?)",
                           (row["id"], now(), "restart", "needs_reconcile", "{}"))
            db.commit()
            return len(rows)

    def status_counts(self) -> dict[str, int]:
        with self.connection() as db:
            return {row["status"]: row["count"] for row in db.execute(
                "SELECT status, COUNT(*) AS count FROM executions GROUP BY status"
            )}
