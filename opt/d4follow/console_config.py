"""Game-scoped configuration API; no collector, scheduler or price-writer calls.

All cooperating writers must hold ``config_transaction_lock`` around their full
read/modify/write operation. A durable field-only journal precedes each atomic
configuration replacement. The journal never stores the full configuration.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
import uuid

from flask import Blueprint, jsonify, request

import game_parameters


MAX_BODY_BYTES = 64 * 1024
MAX_HISTORY = 100
ID_RE = re.compile(r"^[0-9]{8}T[0-9]{12}Z_[0-9a-f]{12}$")
_LOCAL_LOCKS = {}
_LOCAL_LOCKS_GUARD = threading.Lock()
SHANGHAI = timezone(timedelta(hours=8))


class ConfigError(Exception):
    def __init__(self, message, status=400, code="invalid_config", **extra):
        super().__init__(message)
        self.message, self.status, self.code, self.extra = message, status, code, extra


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _load(path):
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8-sig"), parse_constant=_reject_constant)
    if not isinstance(value, dict):
        raise ConfigError("当前配置格式异常，已停止保存。", 503, "config_unavailable")
    return raw, value


def _reject_constant(value):
    raise ValueError("不接受非有限数字：" + value)


def _fsync_directory(directory):
    if os.name != "nt":
        fd = os.open(str(directory), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _atomic_write(path, payload, mode=0o600):
    """Replace one file, preserving its existing permissions where applicable."""
    path = Path(path)
    if path.exists():
        mode = stat.S_IMODE(path.stat().st_mode)
    fd, temp_name = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        if os.name != "nt":
            os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as handle:
            fd = None
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        _fsync_directory(path.parent)
    finally:
        if fd is not None:
            os.close(fd)
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


@contextmanager
def config_transaction_lock(root, common_lock=None):
    """Thread + process lock shared by all console configuration writers.

Do not nest this context. The parent application's CFG_LOCK may be reentrant,
but the OS file lock deliberately has a single acquisition per transaction.
"""
    root = Path(root).resolve()
    with _LOCAL_LOCKS_GUARD:
        local_lock = _LOCAL_LOCKS.setdefault(str(root), threading.RLock())
    # Ordering is common lock -> local lock -> process lock for every caller.
    outer = common_lock if common_lock is not None else local_lock
    with outer, local_lock:
        directory = root / "data"
        directory.mkdir(parents=True, exist_ok=True)
        lock_path = directory / ".console-config.lock"
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
        with os.fdopen(fd, "r+b", buffering=0) as handle:
            if os.name == "nt":
                import msvcrt
                if os.fstat(handle.fileno()).st_size == 0:
                    handle.write(b"\0")
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _game(game_id):
    for entry in game_parameters.GAMES:
        if entry["id"] == game_id:
            filename = entry["file"]
            if filename not in ("config.json", "wow_gold_config.json", "aa_gold_config.json"):
                raise ConfigError("该游戏的配置来源尚未接入。", 503, "config_unavailable")
            return entry
    raise ConfigError("未找到这个游戏。", 404, "unknown_game")


def _get_path(doc, path):
    current = doc
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, copy.deepcopy(current)


def _remove_path(doc, path):
    current = doc
    for part in path[:-1]:
        if not isinstance(current, dict) or part not in current:
            return
        current = current[part]
    if isinstance(current, dict):
        current.pop(path[-1], None)


def _equal(left, right):
    # bool is an int subclass in Python; configuration comparison must distinguish it.
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    return left == right


def _schema(game_id, doc, common_cfg, raw):
    result = copy.deepcopy(game_parameters.get_game_schema(game_id, doc, common_cfg=common_cfg))
    result["version"] = _digest(raw)
    result["effective"] = "next_round"
    result["effect"] = "保存后从下一新轮次生效；正在运行的轮次使用原配置。"
    return result


def _origin_tuple(value):
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            return None
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            return None
        return parsed.scheme, parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return None


def _write_request():
    actor = request.headers.get("X-Authenticated-User", "").strip()
    if not actor or len(actor) > 128 or any(ord(c) < 32 for c in actor):
        raise ConfigError("登录状态已失效，请重新登录后保存。", 401, "authentication_required")
    # The production proxy overwrites these headers. Never accept an actor in JSON.
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
    expected = _origin_tuple(scheme + "://" + request.host)
    actual = _origin_tuple(request.headers.get("Origin", ""))
    if expected is None or actual != expected:
        raise ConfigError("请求来源不匹配，请从当前控制台重新打开配置页。", 403, "origin_mismatch")
    if request.mimetype != "application/json":
        raise ConfigError("保存请求需要 JSON 格式。", 415, "json_required")
    if request.content_length is not None and request.content_length > MAX_BODY_BYTES:
        raise ConfigError("配置变更内容过大。", 413, "body_too_large")
    raw = request.stream.read(MAX_BODY_BYTES + 1)
    if len(raw) > MAX_BODY_BYTES:
        raise ConfigError("配置变更内容过大。", 413, "body_too_large")
    try:
        body = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except (ValueError, UnicodeError):
        raise ConfigError("配置内容不是有效 JSON，数字必须为有限值。")
    if not isinstance(body, dict):
        raise ConfigError("配置内容需要是对象。")
    return actor, body


def _check_version(body, raw):
    expected = body.get("version")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ConfigError("缺少配置版本，请刷新后重新编辑。", 400, "version_required")
    current = _digest(raw)
    if expected != current:
        raise ConfigError("配置已被其他操作更新。你的输入已保留，请刷新核对后再保存。", 409,
                          "version_conflict", current_version=current)


class ConfigStore:
    def __init__(self, root, common_lock=None):
        self.root = Path(root).resolve()
        self.common_lock = common_lock
        self.history_dir = self.root / "data" / "config-history"

    def lock(self):
        return config_transaction_lock(self.root, self.common_lock)

    def _documents(self, game_id):
        game = _game(game_id)
        raw, doc = _load(self.root / game["file"])
        if game["file"] == "config.json":
            common = doc
        else:
            _, common = _load(self.root / "config.json")
        return game, raw, doc, common

    def read(self, game_id):
        with self.lock():
            game, raw, doc, common = self._documents(game_id)
            return _schema(game_id, doc, common, raw)

    def _event_path(self, event_id):
        if not isinstance(event_id, str) or not ID_RE.fullmatch(event_id):
            raise ConfigError("变更记录编号无效。", 400, "invalid_history_id")
        return self.history_dir / (event_id + ".json")

    def _recover(self):
        """Reconcile crash-window journal entries without replaying any config change."""
        if not self.history_dir.exists():
            return
        for path in self.history_dir.glob("*.json"):
            if not ID_RE.fullmatch(path.stem):
                continue
            _, event = _load(path)
            if event.get("state") != "prepared":
                continue
            filename = _game(event["game"])["file"]
            current = _digest((self.root / filename).read_bytes())
            if current == event["after_version"]:
                event["state"] = "committed"
                event["recovered"] = True
            elif current == event["before_version"]:
                event["state"] = "aborted"
            else:
                # A later non-cooperating writer changed the file. Do not infer success.
                event["state"] = "uncertain"
            _atomic_write(path, _json_bytes(event))

    def _changes(self, game_id, old_doc, new_doc, common, patch):
        fields = {field["key"]: field for field in game_parameters.get_game_schema(game_id, old_doc, common_cfg=common)["fields"]}
        changes = []
        for key in patch:
            field = fields[key]
            path = field["path"]
            before_exists, actual_before = _get_path(old_doc, path)
            after_exists, after = _get_path(new_doc, path)
            if before_exists == after_exists and _equal(actual_before, after):
                continue
            changes.append({"key": key, "label": field["label"], "path": path,
                            "before": actual_before if before_exists else field.get("value"),
                            "after": after, "before_exists": before_exists,
                            "after_exists": after_exists, "unit": field.get("unit", ""),
                            "scale": field.get("scale", 1)})
        return changes

    def _commit(self, game, old_raw, new_doc, changes, actor, action="save", restored_from=None):
        if not changes:
            return None, old_raw
        new_raw = _json_bytes(new_doc)
        self.history_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        event_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ_") + uuid.uuid4().hex[:12]
        event = {"id": event_id, "time": datetime.now(SHANGHAI).isoformat(timespec="seconds"),
                 "actor": actor, "game": game["id"], "game_name": game["name"],
                 "action": action, "state": "prepared", "changes": changes,
                 "before_version": _digest(old_raw), "after_version": _digest(new_raw)}
        if restored_from:
            event["restored_from"] = restored_from
        event_path = self._event_path(event_id)
        config_path = self.root / game["file"]
        # No config mutation is possible before the durable field-only recovery point.
        _atomic_write(event_path, _json_bytes(event))
        try:
            # Detect an external/non-cooperating writer before replacement too.
            if _digest(config_path.read_bytes()) != event["before_version"]:
                raise ConfigError("配置刚被其他操作更新，请刷新后重新保存。", 409, "version_conflict")
            _atomic_write(config_path, new_raw)
            event["state"] = "committed"
            _atomic_write(event_path, _json_bytes(event))
        except Exception:
            current = _digest(config_path.read_bytes())
            if current == event["after_version"]:
                _atomic_write(config_path, old_raw)
                current = event["before_version"]
            event["state"] = "aborted" if current == event["before_version"] else "uncertain"
            try:
                _atomic_write(event_path, _json_bytes(event))
            except Exception:
                pass  # The durable prepared entry is reconciled on the next operation.
            raise
        # Read back exact bytes before reporting a confirmed save.
        if _digest(config_path.read_bytes()) != event["after_version"]:
            raise ConfigError("保存后的配置又被其他操作更新，请刷新核对当前版本。", 409, "version_conflict")
        return event, new_raw

    def save(self, game_id, body, actor):
        if set(body) - {"version", "patch"}:
            raise ConfigError("请求包含不允许的字段。")
        patch = body.get("patch")
        if not isinstance(patch, dict) or not patch or len(patch) > 100:
            raise ConfigError("请选择需要修改的参数。")
        with self.lock():
            self._recover()
            game, raw, doc, common = self._documents(game_id)
            _check_version(body, raw)
            try:
                new_doc, _ = game_parameters.apply_fields(game_id, doc, patch, common_cfg=common)
            except (ValueError, TypeError, KeyError) as error:
                raise ConfigError(str(error))
            changes = self._changes(game_id, doc, new_doc, common, patch)
            event, new_raw = self._commit(game, raw, new_doc, changes, actor)
            common_after = new_doc if game["file"] == "config.json" else common
            return {"ok": True, "data": _schema(game_id, new_doc if changes else doc, common_after, new_raw),
                    "changes": self._public_changes(changes), "next_round": bool(changes),
                    "history_id": event["id"] if event else None,
                    "message": "已保存，下一新轮次生效。" if changes else "参数没有变化。"}

    @staticmethod
    def _public_changes(changes):
        return [{key: change.get(key) for key in ("key", "label", "before", "after", "unit", "scale")}
                for change in changes]

    @classmethod
    def _public_event(cls, event):
        result = {key: event.get(key) for key in ("id", "time", "actor", "game", "game_name", "action", "restored_from")}
        result["changes"] = cls._public_changes(event["changes"])
        return result

    def history(self, game_id=None, cursor=None, limit=50):
        if game_id:
            _game(game_id)
        if cursor:
            self._event_path(cursor)
        limit = min(MAX_HISTORY, max(1, int(limit)))
        with self.lock():
            self._recover()
            paths = sorted(self.history_dir.glob("*.json"), reverse=True) if self.history_dir.exists() else []
            entries = []
            for path in paths:
                if not ID_RE.fullmatch(path.stem) or (cursor and path.stem >= cursor):
                    continue
                _, event = _load(path)
                if event.get("state") != "committed" or (game_id and event.get("game") != game_id):
                    continue
                entries.append(self._public_event(event))
                if len(entries) > limit:
                    break
            next_cursor = entries[limit - 1]["id"] if len(entries) > limit else None
            return {"ok": True, "items": entries[:limit], "next_cursor": next_cursor}

    def restore(self, body, actor):
        if set(body) - {"id", "version"}:
            raise ConfigError("请求包含不允许的字段。")
        with self.lock():
            self._recover()
            event_path = self._event_path(body.get("id"))
            if not event_path.exists():
                raise ConfigError("未找到这条配置变更。", 404, "history_not_found")
            _, previous = _load(event_path)
            if previous.get("state") != "committed":
                raise ConfigError("这条变更没有确认成功，不能自动恢复。", 409, "restore_unconfirmed")
            game, raw, doc, common = self._documents(previous["game"])
            _check_version(body, raw)
            fields = {f["key"]: f for f in game_parameters.get_game_schema(game["id"], doc, common_cfg=common)["fields"]}
            patch = {}
            for change in previous["changes"]:
                field = fields.get(change["key"])
                if field is None or field["path"] != change["path"]:
                    raise ConfigError("该参数定义已更新，不能自动恢复旧记录。", 409, "restore_schema_changed")
                exists, current = _get_path(doc, change["path"])
                if exists != change["after_exists"] or not _equal(current, change["after"]):
                    raise ConfigError("这条记录涉及的参数已被再次修改，自动恢复已停止。", 409, "restore_conflict")
                patch[change["key"]] = change["before"]
            try:
                new_doc, _ = game_parameters.apply_fields(game["id"], doc, patch, common_cfg=common)
            except (ValueError, TypeError, KeyError) as error:
                raise ConfigError("旧参数不符合当前规则，不能自动恢复：" + str(error), 409, "restore_invalid")
            for change in previous["changes"]:
                if not change["before_exists"]:
                    _remove_path(new_doc, change["path"])
            restored_common = new_doc if game["file"] == "config.json" else common
            restored_fields = {f["key"]: f for f in game_parameters.get_game_schema(game["id"], new_doc, common_cfg=restored_common)["fields"]}
            if any(not _equal(restored_fields[c["key"]]["value"], c["before"]) for c in previous["changes"]):
                raise ConfigError("共享默认值已变化，恢复结果与历史值不同。请在游戏配置页核对并手动填写需要的值。", 409, "restore_inheritance_changed")
            changes = self._changes(game["id"], doc, new_doc, common, patch)
            event, new_raw = self._commit(game, raw, new_doc, changes, actor, "restore", previous["id"])
            common_after = new_doc if game["file"] == "config.json" else common
            return {"ok": True, "data": _schema(game["id"], new_doc, common_after, new_raw),
                    "changes": self._public_changes(changes), "next_round": bool(changes),
                    "history_id": event["id"] if event else None,
                    "message": "已恢复这条记录涉及的参数，下一新轮次生效。"}


def register_config(app, root, common_lock=None):
    """Register API routes and return the store for integration/tests."""
    store = ConfigStore(root, common_lock)
    blueprint = Blueprint("console_config", __name__)

    @blueprint.errorhandler(ConfigError)
    def known_error(error):
        return jsonify({"ok": False, "error": error.message, "code": error.code, **error.extra}), error.status

    @blueprint.errorhandler(Exception)
    def storage_error(error):
        app.logger.error("game configuration operation failed (%s)", type(error).__name__)
        return jsonify({"ok": False, "error": "配置操作未完成，请刷新核对当前版本后重试。", "code": "storage_error"}), 500

    @blueprint.route("/api/games/<game_id>/config", methods=["GET", "POST"])
    def configuration(game_id):
        _game(game_id)
        if request.method == "GET":
            return jsonify({"ok": True, "data": store.read(game_id)})
        actor, body = _write_request()
        return jsonify(store.save(game_id, body, actor))

    @blueprint.route("/api/config/history", methods=["GET"])
    def history():
        try:
            limit = int(request.args.get("limit", 50))
        except ValueError:
            raise ConfigError("每页条数需要是整数。")
        return jsonify(store.history(request.args.get("game") or None, request.args.get("cursor") or None, limit))

    @blueprint.route("/api/config/restore", methods=["POST"])
    def restore():
        actor, body = _write_request()
        return jsonify(store.restore(body, actor))

    app.register_blueprint(blueprint)
    return store
