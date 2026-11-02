"""Durable FS ownership and event ledger for the constrained Hermes runner.

The caller supplies the authenticated FS user. No upstream credential or raw tool
result is stored here; only public progress and original assistant output are kept.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone


RUN_ID = re.compile(r"run_[a-f0-9]{32}\Z")
REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{8,80}\Z")
PUBLIC_EVENTS = {
    "run.queued", "run.started", "run.completed", "run.failed", "run.cancelled",
    "run.stopping", "run.steered", "run.interrupted", "message.delta", "message.interim",
    "tool.started", "tool.completed", "tool.failed",
    "approval.request", "approval.responded", "replay.truncated",
}
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


class ConversationStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise ValueError("linked_store_root")
        self.path = self.root / "conversations.db"
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, session_id TEXT NOT NULL UNIQUE,
                    updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS turns (
                    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
                    request_id TEXT NOT NULL, input_sha256 TEXT NOT NULL, text TEXT NOT NULL,
                    state TEXT NOT NULL, run_id TEXT UNIQUE, task_id TEXT, lease TEXT,
                    UNIQUE(conversation_id, request_id));
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, turn_id TEXT NOT NULL,
                    upstream_seq INTEGER, type TEXT NOT NULL, payload TEXT NOT NULL,
                    UNIQUE(turn_id, upstream_seq));
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY, turn_id TEXT NOT NULL,
                    filename TEXT NOT NULL, mime TEXT NOT NULL,
                    sha256 TEXT NOT NULL, size INTEGER NOT NULL,
                    UNIQUE(turn_id,sha256));
                CREATE TABLE IF NOT EXISTS actions (
                    turn_id TEXT NOT NULL, request_id TEXT NOT NULL,
                    kind TEXT NOT NULL, input_sha256 TEXT NOT NULL,
                    state TEXT NOT NULL, PRIMARY KEY(turn_id,request_id));
            """)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        try:
            yield db
            if db.in_transaction:
                db.commit()
        except Exception:
            if db.in_transaction:
                db.rollback()
            raise
        finally:
            db.close()

    def create(self, owner):
        if not isinstance(owner, str) or not owner:
            raise PermissionError("login_required")
        conversation_id = uuid.uuid4().hex
        session_id = "hc_" + uuid.uuid4().hex + uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        with self.db() as db:
            db.execute("INSERT INTO conversations VALUES(?,?,?,?)", (conversation_id, owner, session_id, now))
        return {"conversation_id": conversation_id, "session_id": session_id}

    def _owned(self, db, owner, conversation_id):
        row = db.execute("SELECT * FROM conversations WHERE id=? AND owner=?", (conversation_id, owner)).fetchone()
        if row is None:
            raise LookupError("conversation_not_found")
        return row

    def reserve_turn(self, owner, conversation_id, text, request_id, file_ids=None, *, native=False):
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 12000:
            raise ValueError("invalid_input")
        if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
            raise ValueError("invalid_request_id")
        from conversation_file_bindings import FileBindings, normalize_file_ids
        file_ids = normalize_file_ids(file_ids, maximum=1000 if native else 10)
        payload = json.dumps({'text': text, 'file_ids': file_ids}, sort_keys=True) if file_ids else text
        fingerprint = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            conversation = self._owned(db, owner, conversation_id)
            old = db.execute("SELECT * FROM turns WHERE conversation_id=? AND request_id=?", (conversation_id, request_id)).fetchone()
            if old:
                bound = FileBindings(self).bound(db, owner, conversation_id, old['id'])
                if old["input_sha256"] != fingerprint or bound['inputs'] != file_ids:
                    raise ValueError("idempotency_conflict")
                return {"turn_id": old["id"], "run_id": old["run_id"], "state": old["state"], "session_id": conversation["session_id"], "reused": True}
            active = db.execute("SELECT 1 FROM turns WHERE conversation_id=? AND state IN ('preparing','dispatch_unknown','queued','running','stopping')", (conversation_id,)).fetchone()
            if active:
                raise RuntimeError("conversation_busy")
            turn_id = uuid.uuid4().hex
            db.execute("INSERT INTO turns(id,conversation_id,request_id,input_sha256,text,state) VALUES(?,?,?,?,?,?)", (turn_id, conversation_id, request_id, fingerprint, text, "preparing"))
            if file_ids:
                FileBindings(self).bind(db, owner, conversation_id, turn_id, file_ids)
            db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (datetime.now(timezone.utc).isoformat(), conversation_id))
            return {"turn_id": turn_id, "run_id": None, "state": "preparing", "session_id": conversation["session_id"], "reused": False}

    def bind_run(self, owner, conversation_id, turn_id, run_id):
        if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
            raise ValueError("invalid_run_id")
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            self._owned(db, owner, conversation_id)
            row = db.execute("SELECT run_id,state FROM turns WHERE id=? AND conversation_id=?", (turn_id, conversation_id)).fetchone()
            if row is None or row["run_id"] not in (None, run_id):
                raise LookupError("turn_not_found_or_run_conflict")
            db.execute("UPDATE turns SET run_id=?,state='queued' WHERE id=?", (run_id, turn_id))

    def bind_task(self, owner, conversation_id, turn_id, task_id, lease):
        if not re.fullmatch(r"[a-f0-9]{32}", task_id) or not re.fullmatch(r"[a-f0-9]{32}", lease):
            raise ValueError("task_binding")
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            self._owned(db, owner, conversation_id)
            row = db.execute("SELECT task_id,lease FROM turns WHERE id=? AND conversation_id=?", (turn_id, conversation_id)).fetchone()
            if row is None or row["task_id"] not in (None, task_id) or row["lease"] not in (None, lease):
                raise ValueError("task_binding_conflict")
            db.execute("UPDATE turns SET task_id=?,lease=? WHERE id=?", (task_id, lease, turn_id))

    def task_binding(self, owner, conversation_id, turn_id):
        with self.db() as db:
            self._owned(db, owner, conversation_id)
            row = db.execute("SELECT task_id,lease FROM turns WHERE id=? AND conversation_id=?", (turn_id, conversation_id)).fetchone()
            if row is None:
                raise LookupError("turn_not_found")
            return (row["task_id"], row["lease"])

    def set_state(self, owner, conversation_id, turn_id, state):
        if state not in {"dispatch_unknown", "queued", "running", "stopping", *TERMINAL}:
            raise ValueError("invalid_state")
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            self._owned(db, owner, conversation_id)
            row = db.execute("SELECT state FROM turns WHERE id=? AND conversation_id=?", (turn_id, conversation_id)).fetchone()
            if row is None:
                raise LookupError("turn_not_found")
            if row["state"] in TERMINAL and state != row["state"]:
                raise ValueError("terminal_turn")
            db.execute("UPDATE turns SET state=? WHERE id=?", (state, turn_id))

    def run(self, owner, conversation_id, run_id):
        with self.db() as db:
            self._owned(db, owner, conversation_id)
            row = db.execute("SELECT * FROM turns WHERE conversation_id=? AND run_id=?", (conversation_id, run_id)).fetchone()
            if row is None:
                raise LookupError("run_not_found")
            return dict(row)

    def action(self, owner, conversation_id, run_id, kind, request_id, text=""):
        if kind not in {"steer", "stop"} or not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
            raise ValueError("invalid_action")
        if not isinstance(text, str) or len(text) > 12000:
            raise ValueError("invalid_action_text")
        fingerprint = hashlib.sha256((kind + "\0" + text).encode()).hexdigest()
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            turn = self.run(owner, conversation_id, run_id)
            old = db.execute("SELECT * FROM actions WHERE turn_id=? AND request_id=?", (turn["id"], request_id)).fetchone()
            if old:
                if old["kind"] != kind or old["input_sha256"] != fingerprint:
                    raise ValueError("idempotency_conflict")
                return {"state": old["state"], "reused": True}
            db.execute("INSERT INTO actions VALUES(?,?,?,?,?)", (turn["id"], request_id, kind, fingerprint, "unknown"))
            return {"state": "unknown", "reused": False}

    def action_result(self, owner, conversation_id, run_id, request_id, state):
        if state not in {"accepted", "rejected"}:
            raise ValueError("action_state")
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            turn = self.run(owner, conversation_id, run_id)
            db.execute("UPDATE actions SET state=? WHERE turn_id=? AND request_id=? AND state='unknown'", (state, turn["id"], request_id))

    def active(self):
        with self.db() as db:
            return [dict(row) for row in db.execute("SELECT t.id turn_id,t.run_id,t.state,c.id conversation_id,c.owner FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE t.state NOT IN ('completed','failed','cancelled','interrupted')")]

    def append_event(self, owner, conversation_id, run_id, upstream_seq, event, *, _db=None):
        if (upstream_seq is not None and (type(upstream_seq) is not int or upstream_seq < 0)) or not isinstance(event, dict):
            raise ValueError("invalid_event")
        name = event.get("event")
        if name not in PUBLIC_EVENTS:
            return None  # No reasoning text, tool arguments, or arbitrary provider payload.
        allowed = {"event", "delta", "text", "tool", "status", "output", "error", "run_id"}
        payload = {key: value for key, value in event.items() if key in allowed and isinstance(value, str)}
        if "error" in payload:
            payload["error"] = "Hermes 运行失败，请检查任务状态" if name == "run.failed" else "Hermes 运行已中断"
        if "tool" in payload and not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", payload["tool"]):
            payload.pop("tool")
        for key in ("oldest_retained_seq", "requested_seq"):
            if type(event.get(key)) is int and event[key] >= 0:
                payload[key] = event[key]
        if "output" in payload and len(payload["output"]) > 10 * 1024 * 1024:
            raise ValueError("output_too_large")
        if "delta" in payload and len(payload["delta"]) > 16000:
            raise ValueError("event_too_large")
        from contextlib import nullcontext
        with self.db() if _db is None else nullcontext(_db) as db:
            if _db is None:db.execute("BEGIN IMMEDIATE")
            turn = self.run(owner, conversation_id, run_id)
            db.execute("INSERT OR IGNORE INTO events(turn_id,upstream_seq,type,payload) VALUES(?,?,?,?)",
                       (turn["id"], upstream_seq, name, json.dumps(payload, ensure_ascii=False)))
            if upstream_seq is None:
                return db.execute("SELECT last_insert_rowid()").fetchone()[0]
            row = db.execute("SELECT seq FROM events WHERE turn_id=? AND upstream_seq=?", (turn["id"], upstream_seq)).fetchone()
            return row["seq"]

    def events(self, owner, conversation_id, after=0):
        if type(after) is not int or after < 0:
            raise ValueError("invalid_cursor")
        with self.db() as db:
            self._owned(db, owner, conversation_id)
            rows = db.execute("SELECT e.seq,e.type,e.payload,t.id turn_id,t.run_id FROM events e JOIN turns t ON t.id=e.turn_id WHERE t.conversation_id=? AND e.seq>? ORDER BY e.seq LIMIT 500", (conversation_id, after)).fetchall()
            return [{"seq": row["seq"], "type": row["type"], "payload": json.loads(row["payload"]), "turn_id": row["turn_id"], "run_id": row["run_id"]} for row in rows]

    def last_upstream(self, owner, conversation_id, run_id):
        turn = self.run(owner, conversation_id, run_id)
        with self.db() as db:
            row = db.execute("SELECT max(upstream_seq) FROM events WHERE turn_id=? AND upstream_seq<9223372036854775807", (turn["id"],)).fetchone()
            return row[0] if row[0] is not None else -1

    def has_event(self, owner, conversation_id, run_id, kind):
        turn = self.run(owner, conversation_id, run_id)
        with self.db() as db:
            return db.execute("SELECT 1 FROM events WHERE turn_id=? AND type=? LIMIT 1", (turn["id"], kind)).fetchone() is not None

    def detail(self, owner, conversation_id):
        from conversation_file_bindings import FileBindings
        from conversation_files import ConversationFiles
        with self.db() as db:
            self._owned(db, owner, conversation_id)
            turns = db.execute("SELECT id,text,state,run_id,request_id FROM turns WHERE conversation_id=? ORDER BY rowid", (conversation_id,)).fetchall()
            result = []
            file_metadata = {}
            for turn in turns:
                last = db.execute("SELECT payload FROM events WHERE turn_id=? AND type='run.completed' ORDER BY seq DESC LIMIT 1", (turn["id"],)).fetchone()
                failure = db.execute("SELECT payload FROM events WHERE turn_id=? AND type IN ('run.failed','run.interrupted') ORDER BY seq DESC LIMIT 1", (turn["id"],)).fetchone()
                deltas = db.execute("SELECT payload FROM events WHERE turn_id=? AND type='message.delta' ORDER BY seq", (turn["id"],)).fetchall() if not last else []
                progress = db.execute("SELECT type,payload FROM events WHERE turn_id=? AND type IN ('tool.started','tool.completed','tool.failed','message.interim') ORDER BY seq DESC LIMIT 1", (turn["id"],)).fetchone()
                files = db.execute("SELECT id artifact_id,filename,mime,sha256,size FROM artifacts WHERE turn_id=? ORDER BY rowid", (turn["id"],)).fetchall()
                bindings = FileBindings(self).bound(db, owner, conversation_id, turn['id'])
                for fid in set(bindings['inputs'] + bindings['generated']):
                    if fid not in file_metadata:
                        file_metadata[fid] = ConversationFiles(self).describe(owner, conversation_id, fid, _db=db)
                metadata = {kind: [file_metadata[fid] for fid in ids] for kind, ids in bindings.items()}
                result.append({"turn_id": turn["id"], "client_request_id": turn['request_id'], "text": turn["text"], "state": turn["state"],
                               "run_id": turn["run_id"], "reply": json.loads(last["payload"]).get("output", "") if last else "".join(json.loads(row["payload"]).get("delta", "") for row in deltas),
                               "error": json.loads(failure["payload"]).get("error") if failure else None,
                               "progress": {"type": progress["type"], **json.loads(progress["payload"])} if progress else None,
                               "artifacts": [dict(row) for row in files],
                               "file_bindings": bindings, "files": metadata})
            seq = db.execute("SELECT coalesce(max(e.seq),0) FROM events e JOIN turns t ON t.id=e.turn_id WHERE t.conversation_id=?", (conversation_id,)).fetchone()[0]
            return {"conversation_id": conversation_id, "title": result[0]["text"][:80] if result else "新会话",
                    "turns": result, "last_seq": seq}

    def listed(self, owner):
        if not owner:
            raise PermissionError("login_required")
        with self.db() as db:
            rows = db.execute("SELECT c.id,c.updated_at,coalesce((SELECT text FROM turns WHERE conversation_id=c.id ORDER BY rowid LIMIT 1),'新会话') title FROM conversations c WHERE c.owner=? ORDER BY c.updated_at DESC LIMIT 100", (owner,)).fetchall()
            return {"items": [{"conversation_id": row["id"], "title": row["title"][:80], "updated_at": row["updated_at"]} for row in rows]}

    def save_original(self, owner, conversation_id, run_id, content, filename="hermes-original.txt", mime="text/plain"):
        if not isinstance(content, bytes) or len(content) > 10 * 1024 * 1024:
            raise ValueError("artifact_size")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", filename):
            raise ValueError("artifact_name")
        if mime not in {"text/plain", "text/html", "text/csv"}:
            raise ValueError("artifact_mime")
        turn = self.run(owner, conversation_id, run_id)
        sha = hashlib.sha256(content).hexdigest()
        with self.db() as db:
            old = db.execute("SELECT * FROM artifacts WHERE turn_id=? AND sha256=?", (turn["id"], sha)).fetchone()
            if old:
                return {"artifact_id": old["id"], "filename": old["filename"], "mime": old["mime"], "sha256": sha, "size": old["size"]}
        artifact_id = uuid.uuid4().hex
        directory = self.root / "artifacts"
        directory.mkdir(mode=0o700, exist_ok=True)
        if directory.is_symlink():
            raise ValueError("linked_artifact_root")
        target = directory / artifact_id
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            with self.db() as db:
                db.execute("INSERT INTO artifacts VALUES(?,?,?,?,?,?)", (artifact_id, turn["id"], filename, mime, sha, len(content)))
            return {"artifact_id": artifact_id, "filename": filename, "mime": mime, "sha256": sha, "size": len(content)}
        except Exception:
            target.unlink(missing_ok=True)
            raise

    def artifact(self, owner, conversation_id, artifact_id):
        if not isinstance(artifact_id, str) or not re.fullmatch(r"[a-f0-9]{32}", artifact_id):
            raise LookupError("artifact_not_found")
        with self.db() as db:
            self._owned(db, owner, conversation_id)
            row = db.execute("SELECT a.* FROM artifacts a JOIN turns t ON t.id=a.turn_id WHERE t.conversation_id=? AND a.id=?", (conversation_id, artifact_id)).fetchone()
        if row is None:
            raise LookupError("artifact_not_found")
        target = self.root / "artifacts" / artifact_id
        if target.is_symlink():
            raise ValueError("linked_artifact")
        content = target.read_bytes()
        if len(content) != row["size"] or hashlib.sha256(content).hexdigest() != row["sha256"]:
            raise ValueError("artifact_integrity")
        return {"filename": row["filename"], "mime": row["mime"], "sha256": row["sha256"], "content": content}
